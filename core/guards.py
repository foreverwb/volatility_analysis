"""
交易权限与观望触发器
"""
from typing import Any, Dict, List, Optional, Tuple

from .metrics import compute_iv_ratio, compute_regime_ratio
from .strategy import map_direction_pref, map_vol_pref, combine_quadrant


def detect_fear_regime(rec: Dict[str, Any], term_structure_label: str, vix_value: Any, cfg: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """复用既有恐慌/倒挂/VIX 高逻辑"""
    reasons: List[str] = []
    ivr = rec.get("IVR")
    iv_ratio = compute_iv_ratio(rec)
    regime = compute_regime_ratio(rec)
    
    if (
        isinstance(ivr, (int, float))
        and ivr >= cfg.get("fear_ivrank_min", 75)
        and isinstance(iv_ratio, (int, float))
        and iv_ratio >= cfg.get("fear_ivrv_ratio_min", 1.3)
        and isinstance(regime, (int, float))
        and regime <= cfg.get("fear_regime_max", 1.05)
    ):
        reasons.append("FEAR_SELL_PRESSURE")
    
    if term_structure_label and ("倒挂" in term_structure_label or "inversion" in str(term_structure_label).lower()):
        reasons.append("TERM_STRUCTURE_INVERSION")
    
    if isinstance(vix_value, (int, float)) and vix_value >= cfg.get("fear_vix_high", 25.0):
        reasons.append("HIGH_VIX_ENV")
    
    return (len(reasons) > 0, reasons)


def _elevate_permission(current: str, target: str) -> str:
    order = {"NORMAL": 0, "ALLOW_DEFINED_RISK_ONLY": 1, "NO_TRADE": 2}
    return target if order.get(target, 0) > order.get(current, 0) else current


def evaluate_trade_permission(
    quadrant: str,
    vol_pref: str,
    confidence: str,
    days_to_earnings: Any,
    data_quality: str,
    fear_reasons: List[str],
    cfg: Dict[str, Any],
    data_confidence: Optional[str] = None,
    missing_features: Optional[List[str]] = None,
    posture_5d: Optional[str] = None,
) -> Dict[str, Any]:
    """唯一治理裁决器：返回权限/原因/禁用结构/审计轨迹"""
    permission = "NORMAL"
    reasons: List[str] = []
    disabled = set()
    posture_overlay_notes: List[str] = []
    permission_trace: List[Dict[str, Any]] = []
    
    is_short_vol = (quadrant and "卖波" in quadrant) or vol_pref == "卖波"
    base_disabled = ["naked_short_put", "naked_short_call", "short_strangle"]
    hard_disabled = base_disabled + ["short_put_ratio", "short_call_ratio"]
    
    def flag(target: str, code: str, hard: bool = False, source: str = "guards") -> None:
        nonlocal permission
        before = permission
        permission = _elevate_permission(permission, target)
        reasons.append(code)
        if target in ("ALLOW_DEFINED_RISK_ONLY", "NO_TRADE"):
            disabled.update(hard_disabled if hard or target == "NO_TRADE" else base_disabled)
        permission_trace.append({
            "source": source,
            "code": code,
            "target": target,
            "before": before,
            "after": permission,
            "hard": bool(hard),
        })

    def render_result() -> Dict[str, Any]:
        return {
            "trade_permission": permission,
            "permission_reasons": reasons,
            "disabled_structures": sorted(disabled),
            "posture_overlay_notes": posture_overlay_notes,
            "governance_mode": "A_GUARDS_SINGLE_AUTHORITY",
            "governance_authority": "core.guards.evaluate_trade_permission",
            "governance_reason_codes": list(reasons),
            "permission_trace": permission_trace,
        }
    
    # 数据质量（即便非短波也需要阻断）
    if data_quality == "LOW":
        flag("NO_TRADE", "DATA_QUALITY_LOW", hard=True)
        return render_result()
    elif data_quality == "MED":
        if is_short_vol:
            flag("ALLOW_DEFINED_RISK_ONLY", "DATA_QUALITY_MED")

    if data_confidence == "低":
        flag("ALLOW_DEFINED_RISK_ONLY", "DATA_CONFIDENCE_LOW", hard=is_short_vol)
    elif data_confidence == "中" and is_short_vol:
        flag("ALLOW_DEFINED_RISK_ONLY", "DATA_CONFIDENCE_MED")

    core_missing = set(missing_features or []).intersection({"IVR", "IV30", "HV20", "HV1Y", "VIX"})
    if len(core_missing) >= 3:
        flag("NO_TRADE", "MISSING_CORE_FEATURES", hard=True)
    elif len(core_missing) >= 2:
        flag("ALLOW_DEFINED_RISK_ONLY", "MISSING_CORE_FEATURES")

    # posture 风险门控合并到 guards，避免 analyzer/micro 二次写入
    if posture_5d == "COUNTERTREND":
        flag("ALLOW_DEFINED_RISK_ONLY", "POSTURE_COUNTERTREND")
        posture_overlay_notes.append("逆势反转：降级为定义风险")
    elif posture_5d == "ONE_DAY_SHOCK":
        flag("ALLOW_DEFINED_RISK_ONLY", "POSTURE_ONE_DAY_SHOCK")
        disabled.update(base_disabled)
        posture_overlay_notes.append("单日冲击：避免裸露尾部")
    elif posture_5d == "CHOP":
        flag("NO_TRADE", "POSTURE_CHOP", hard=True)
        posture_overlay_notes.append("震荡/摇摆：倾向观望")
    
    if not is_short_vol:
        return render_result()
    
    # 财报事件
    if isinstance(days_to_earnings, (int, float)) and days_to_earnings >= 0 and days_to_earnings <= 7:
        flag("ALLOW_DEFINED_RISK_ONLY", "EARNINGS_WINDOW_SHORT_VOL")
    
    # 置信度
    if confidence == "低":
        flag("ALLOW_DEFINED_RISK_ONLY", "LOW_CONFIDENCE_SHORT_VOL")
    
    # 恐慌/倒挂/VIX 高
    for fr in fear_reasons or []:
        flag("ALLOW_DEFINED_RISK_ONLY", f"FEAR_REGIME_{fr}")
    
    return render_result()


def build_watchlist_guidance(
    quadrant: str,
    dir_score: float,
    vol_score: float,
    active_open_ratio: Optional[float],
    structure_factor: float,
    term_structure_label: str,
    cfg: Dict[str, Any],
    event_tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    当处于中性/待观察时，提供触发器与监控点。

    设计原则（v2.4）：
    - trigger 阈值使用 watch_* 配置（或从偏好阈值派生），避免把“触发阈值”误用成“偏好映射阈值”。
    - target_quadrant 用于提示“触发后预期状态”。若另一维仍中性，则用“偏多—中性 / 中性—买波”的形式表达，
      而不是强行折叠回“中性/待观察”（否则 watch_triggers 将长期失真）。
    """
    triggers: List[Dict[str, str]] = []
    monitors: List[str] = []
    if quadrant and "中性" in quadrant:
        watch_dir_th = float(cfg.get("watch_direction_trigger", cfg.get("direction_pref_threshold", 0.50)))
        watch_vol_th = float(
            cfg.get(
                "watch_vol_trigger",
                cfg.get("vol_pref_threshold", cfg.get("penalty_vol_pct_thresh", 0.40)),
            )
        )

        # 当前偏好（使用正式映射，包含中性缓冲带）
        dir_pref_now = map_direction_pref(dir_score, cfg, use_neutral_buffer=True)
        vol_pref_now = map_vol_pref(vol_score, cfg, use_neutral_buffer=True)

        # ========== 方向触发 ==========
        # 触发条件本身就定义了“方向确认”，无需再通过偏好映射函数二次投影
        dir_up = "偏多"
        dir_dn = "偏空"

        tgt_up = combine_quadrant(dir_up, vol_pref_now)
        if "中性" in tgt_up:
            tgt_up = f"{dir_up}—{vol_pref_now}"
        triggers.append({
            "trigger": f"direction_score ≥ {watch_dir_th}",
            "target_quadrant": tgt_up
        })

        tgt_dn = combine_quadrant(dir_dn, vol_pref_now)
        if "中性" in tgt_dn:
            tgt_dn = f"{dir_dn}—{vol_pref_now}"
        triggers.append({
            "trigger": f"direction_score ≤ -{watch_dir_th}",
            "target_quadrant": tgt_dn
        })

        # ========== 波动触发 ==========
        # 波动触发使用 watch_vol_th（不带缓冲），以避免“缓冲带”掩盖监控意义
        vol_cfg = dict(cfg)
        vol_cfg["vol_pref_threshold"] = watch_vol_th

        vol_buy = map_vol_pref(watch_vol_th + 0.01, vol_cfg, use_neutral_buffer=False)
        vol_sell = map_vol_pref(-watch_vol_th - 0.01, vol_cfg, use_neutral_buffer=False)

        tgt_buy = combine_quadrant(dir_pref_now, vol_buy)
        if "中性" in tgt_buy:
            tgt_buy = f"{dir_pref_now}—{vol_buy}"
        triggers.append({
            "trigger": f"vol_score ≥ {watch_vol_th}",
            "target_quadrant": tgt_buy
        })

        tgt_sell = combine_quadrant(dir_pref_now, vol_sell)
        if "中性" in tgt_sell:
            tgt_sell = f"{dir_pref_now}—{vol_sell}"
        triggers.append({
            "trigger": f"vol_score ≤ -{watch_vol_th}",
            "target_quadrant": tgt_sell
        })

    aor_text = f"{active_open_ratio:.3f}" if isinstance(active_open_ratio, (int, float)) else "N/A"
    monitors.extend([
        "方向/波动得分趋势与突破",
        f"ActiveOpenRatio/结构因子变化 (当前 {aor_text} / {structure_factor:.2f})",
        f"期限结构恢复正常 vs 倒挂 ({term_structure_label or 'N/A'})",
    ])

    tags = set(event_tags or [])
    if "POTENTIAL_GAMMA_SQUEEZE" in tags:
        triggers.append({
            "trigger": "Gamma squeeze 挤压动量衰减（价升放缓或IV回落）",
            "target_quadrant": quadrant or "中性/待观察",
        })
        monitors.append("Gamma squeeze 事件延续性：关注量能/IV短端与OI拥挤度变化")

    return {"watch_triggers": triggers, "what_to_monitor": monitors}
