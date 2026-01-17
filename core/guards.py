"""
交易权限与观望触发器
"""
from typing import Any, Dict, List, Tuple

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
        and iv_ratio >= cfg.get("fear_ivrv_ratio_min", 1.3)
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
    cfg: Dict[str, Any]
) -> Dict[str, Any]:
    """短波闸门，返回权限/原因/禁用结构"""
    permission = "NORMAL"
    reasons: List[str] = []
    disabled = set()
    
    is_short_vol = (quadrant and "卖波" in quadrant) or vol_pref == "卖波"
    base_disabled = ["naked_short_put", "naked_short_call", "short_strangle"]
    hard_disabled = base_disabled + ["short_put_ratio", "short_call_ratio"]
    
    def flag(target: str, code: str, hard: bool = False) -> None:
        nonlocal permission
        permission = _elevate_permission(permission, target)
        reasons.append(code)
        if target in ("ALLOW_DEFINED_RISK_ONLY", "NO_TRADE"):
            disabled.update(hard_disabled if hard or target == "NO_TRADE" else base_disabled)
    
    # 数据质量（即便非短波也需要阻断）
    if data_quality == "LOW":
        flag("NO_TRADE", "DATA_QUALITY_LOW", hard=True)
        return {
            "trade_permission": permission,
            "permission_reasons": reasons,
            "disabled_structures": list(disabled),
        }
    elif data_quality == "MED":
        if is_short_vol:
            flag("ALLOW_DEFINED_RISK_ONLY", "DATA_QUALITY_MED")
    
    if not is_short_vol:
        return {
            "trade_permission": permission,
            "permission_reasons": reasons,
            "disabled_structures": list(disabled),
        }
    
    # 财报事件
    if isinstance(days_to_earnings, (int, float)) and days_to_earnings >= 0 and days_to_earnings <= 7:
        flag("ALLOW_DEFINED_RISK_ONLY", "EARNINGS_WINDOW_SHORT_VOL")
    
    # 置信度
    if confidence == "低":
        flag("ALLOW_DEFINED_RISK_ONLY", "LOW_CONFIDENCE_SHORT_VOL")
    
    # 恐慌/倒挂/VIX 高
    for fr in fear_reasons or []:
        flag("ALLOW_DEFINED_RISK_ONLY", f"FEAR_REGIME_{fr}")
    
    return {
        "trade_permission": permission,
        "permission_reasons": reasons,
        "disabled_structures": list(disabled),
    }


def build_watchlist_guidance(
    quadrant: str,
    dir_score: float,
    vol_score: float,
    active_open_ratio: float,
    structure_factor: float,
    term_structure_label: str,
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """
    当处于中性/待观察时，提供触发器与监控点
    """
    if not quadrant or "中性" not in quadrant:
        return {"watch_triggers": [], "what_to_monitor": []}
    
    triggers: List[Dict[str, str]] = []
    watch_dir_th = float(cfg.get("watch_direction_trigger", 0.8))
    vol_th = float(cfg.get("penalty_vol_pct_thresh", 0.4))
    
    # 方向触发
    dir_up = map_direction_pref(watch_dir_th + 0.01)
    dir_dn = map_direction_pref(-watch_dir_th - 0.01)
    vol_pref_now = map_vol_pref(vol_score, cfg)
    triggers.append({
        "trigger": f"direction_score ≥ {watch_dir_th}",
        "target_quadrant": combine_quadrant(dir_up, vol_pref_now)
    })
    triggers.append({
        "trigger": f"direction_score ≤ -{watch_dir_th}",
        "target_quadrant": combine_quadrant(dir_dn, vol_pref_now)
    })
    
    # 波动触发
    vol_buy = map_vol_pref(vol_th + 0.01, cfg)
    vol_sell = map_vol_pref(-vol_th - 0.01, cfg)
    dir_pref_now = map_direction_pref(dir_score)
    triggers.append({
        "trigger": f"vol_score ≥ {vol_th}",
        "target_quadrant": combine_quadrant(dir_pref_now, vol_buy)
    })
    triggers.append({
        "trigger": f"vol_score ≤ -{vol_th}",
        "target_quadrant": combine_quadrant(dir_pref_now, vol_sell)
    })
    
    # 结构/期限监控
    monitors = [
        "方向/波动得分趋势与突破",
        f"ActiveOpenRatio/结构因子变化 (当前 {active_open_ratio:.3f} / {structure_factor:.2f})",
        f"期限结构恢复正常 vs 倒挂 ({term_structure_label or 'N/A'})",
    ]
    
    return {"watch_triggers": triggers, "what_to_monitor": monitors}
