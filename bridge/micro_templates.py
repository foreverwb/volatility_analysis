"""
Micro 模板选择与姿态 Overlay
"""
from typing import Any, Dict, List


def _base_template_from_quadrant(quadrant: str) -> str:
    mapping = {
        "偏多—买波": "bull_long_vol",
        "偏多—卖波": "bull_short_vol",
        "偏空—买波": "bear_long_vol",
        "偏空—卖波": "bear_short_vol",
        "中性/待观察": "neutral_watch",
    }
    return mapping.get(quadrant, "generic_micro")


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
    
    severity = {"NORMAL": 0, "ALLOW_DEFINED_RISK_ONLY": 1, "NO_TRADE": 2}
    
    def elevate(target: str, code: str, add_disabled: bool = False) -> None:
        nonlocal permission
        if severity.get(target, 0) > severity.get(permission, 0):
            permission = target
        reasons.append(code)
        if add_disabled:
            disabled.update(["naked_short_put", "naked_short_call", "short_strangle", "short_call_ratio", "short_put_ratio"])
    
    dte_bias = "neutral"
    
    if posture == "TREND_CONFIRM":
        overlays_hit.append("posture_trend_confirm")
        dte_bias = "systematic_mid_dte"
        risk_overlays.append("顺势确认：保持系统化执行，关注时间止盈")
    elif posture == "COUNTERTREND":
        overlays_hit.append("posture_countertrend")
        elevate("ALLOW_DEFINED_RISK_ONLY", "POSTURE_COUNTERTREND_OVERLAY", add_disabled=True)
        dte_bias = "shorter_defined_risk"
        disable_conditions_hit.append("posture_countertrend_defined_risk")
        risk_overlays.append("逆势尝试：仅定义风险，小仓位，等待确认")
    elif posture == "ONE_DAY_SHOCK":
        overlays_hit.append("posture_one_day_shock")
        elevate("ALLOW_DEFINED_RISK_ONLY", "POSTURE_ONE_DAY_SHOCK_OVERLAY", add_disabled=True)
        dte_bias = "conservative_short_dte"
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
    }
