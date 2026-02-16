"""
Micro 模板选择与姿态 Overlay
"""
from typing import Any, Dict, List

from core.term_structure import (
    classify_term_structure_label,
    compute_term_structure_ratios,
    map_horizon_bias_to_dte_bias,
)


def _base_template_from_quadrant(quadrant: str) -> str:
    mapping = {
        "偏多—买波": "bull_long_vol",
        "偏多—卖波": "bull_short_vol",
        "偏空—买波": "bear_long_vol",
        "偏空—卖波": "bear_short_vol",
        "中性/待观察": "neutral_watch",
    }
    return mapping.get(quadrant, "generic_micro")


def _resolve_term_structure_profile(payload: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, str]:
    label_code = payload.get("term_structure_label_code")
    horizon_bias = payload.get("term_structure_horizon_bias")

    if isinstance(label_code, str) and isinstance(horizon_bias, str):
        hb = horizon_bias.lower()
        if hb not in {"short", "mid", "long", "neutral"}:
            hb = "neutral"
        return {
            "label_code": label_code,
            "horizon_bias": hb,
            "dte_bias": map_horizon_bias_to_dte_bias(hb, cfg),
        }

    ratios = compute_term_structure_ratios(payload)
    if ratios:
        label_meta = classify_term_structure_label(ratios, cfg)
        hb = str(label_meta.get("horizon_bias", "neutral") or "neutral").lower()
        if hb not in {"short", "mid", "long", "neutral"}:
            hb = "neutral"
        return {
            "label_code": str(label_meta.get("label_code", "unknown")),
            "horizon_bias": hb,
            "dte_bias": map_horizon_bias_to_dte_bias(hb, cfg),
        }

    return {"label_code": "unknown", "horizon_bias": "neutral", "dte_bias": "neutral"}


def select_micro_template(payload: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    在桥接层选择 micro 模板，并叠加 posture overlay
    """
    quadrant = payload.get("quadrant")
    template = _base_template_from_quadrant(quadrant)
    
    overlays_hit: List[str] = []
    disable_conditions_hit: List[str] = []
    risk_overlays: List[str] = []
    
    permission = payload.get("trade_permission", "NORMAL")
    reasons = list(payload.get("permission_reasons") or [])
    disabled = set(payload.get("disabled_structures") or [])
    posture = payload.get("posture_5d")
    term_profile = _resolve_term_structure_profile(payload, cfg)
    
    severity = {"NORMAL": 0, "ALLOW_DEFINED_RISK_ONLY": 1, "NO_TRADE": 2}
    
    def elevate(target: str, code: str, add_disabled: bool = False) -> None:
        nonlocal permission
        if severity.get(target, 0) > severity.get(permission, 0):
            permission = target
        reasons.append(code)
        if add_disabled:
            disabled.update(["naked_short_put", "naked_short_call", "short_strangle", "short_call_ratio", "short_put_ratio"])
    
    dte_bias = term_profile["dte_bias"]
    if term_profile["label_code"] != "unknown":
        overlays_hit.append(f"term_structure_{term_profile['label_code']}")
    
    if posture == "TREND_CONFIRM":
        overlays_hit.append("posture_trend_confirm")
        if dte_bias == "neutral":
            dte_bias = "mid_term_30_60d"
        risk_overlays.append("顺势确认：保持系统化执行，关注时间止盈")
    elif posture == "COUNTERTREND":
        overlays_hit.append("posture_countertrend")
        elevate("ALLOW_DEFINED_RISK_ONLY", "POSTURE_COUNTERTREND_OVERLAY", add_disabled=True)
        if dte_bias == "neutral":
            dte_bias = "short_term_0_30d"
        disable_conditions_hit.append("posture_countertrend_defined_risk")
        risk_overlays.append("逆势尝试：仅定义风险，小仓位，等待确认")
    elif posture == "ONE_DAY_SHOCK":
        overlays_hit.append("posture_one_day_shock")
        elevate("ALLOW_DEFINED_RISK_ONLY", "POSTURE_ONE_DAY_SHOCK_OVERLAY", add_disabled=True)
        if dte_bias == "neutral":
            dte_bias = "short_term_0_30d"
        disable_conditions_hit.append("posture_one_day_shock_tail_guard")
        risk_overlays.append("单日冲击：避免裸露尾部/近翼，提示易反复")
    elif posture == "CHOP":
        overlays_hit.append("posture_chop")
        elevate("NO_TRADE", "POSTURE_CHOP_OVERLAY", add_disabled=True)
        dte_bias = "wait_and_see"
        disable_conditions_hit.append("posture_chop_watchlist")
        risk_overlays.append("震荡/混沌：默认观望，等待方向或期限结构改善")
    
    return {
        "template": template,
        "dte_bias": dte_bias,
        "risk_overlays": risk_overlays,
        "overlays_hit": overlays_hit,
        "disable_conditions_hit": disable_conditions_hit,
        "trade_permission": permission,
        "permission_reasons": reasons,
        "disabled_structures": list(disabled),
        "term_structure_label_code": term_profile["label_code"],
        "term_structure_horizon_bias": term_profile["horizon_bias"],
    }
