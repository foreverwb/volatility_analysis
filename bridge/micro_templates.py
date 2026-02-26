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
    在桥接层选择 micro 模板。

    治理模式（Phase F）：
    - micro-template 只输出建议层字段（advisory）
    - 不写入、不覆盖 trade_permission / disabled_structures / permission_reasons
    """
    quadrant = payload.get("quadrant")
    template = _base_template_from_quadrant(quadrant)
    
    overlays_hit: List[str] = []
    disable_conditions_hit: List[str] = []
    risk_overlays: List[str] = []
    advisory_reason_codes: List[str] = []
    
    posture = payload.get("posture_5d")
    
    dte_bias = "neutral"
    
    if posture == "TREND_CONFIRM":
        overlays_hit.append("posture_trend_confirm")
        dte_bias = "systematic_mid_dte"
        advisory_reason_codes.append("POSTURE_TREND_CONFIRM_ADVISORY")
        risk_overlays.append("顺势确认：保持系统化执行，关注时间止盈")
    elif posture == "COUNTERTREND":
        overlays_hit.append("posture_countertrend")
        dte_bias = "shorter_defined_risk"
        advisory_reason_codes.append("POSTURE_COUNTERTREND_ADVISORY")
        disable_conditions_hit.append("posture_countertrend_defined_risk")
        risk_overlays.append("逆势尝试：仅定义风险，小仓位，等待确认")
    elif posture == "ONE_DAY_SHOCK":
        overlays_hit.append("posture_one_day_shock")
        dte_bias = "conservative_short_dte"
        advisory_reason_codes.append("POSTURE_ONE_DAY_SHOCK_ADVISORY")
        disable_conditions_hit.append("posture_one_day_shock_tail_guard")
        risk_overlays.append("单日冲击：避免裸露尾部/近翼，提示易反复")
    elif posture == "CHOP":
        overlays_hit.append("posture_chop")
        dte_bias = "wait_and_see"
        advisory_reason_codes.append("POSTURE_CHOP_ADVISORY")
        disable_conditions_hit.append("posture_chop_watchlist")
        risk_overlays.append("震荡/混沌：默认观望，等待方向或期限结构改善")
    
    return {
        "template": template,
        "dte_bias": dte_bias,
        "risk_overlays": risk_overlays,
        "overlays_hit": overlays_hit,
        "disable_conditions_hit": disable_conditions_hit,
        "advisory_reason_codes": advisory_reason_codes,
        "governance_mode": "ADVISORY_ONLY",
        "permission_impact": "none",
    }
