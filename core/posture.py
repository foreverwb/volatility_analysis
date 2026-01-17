"""
5日态势标签 (posture_5d)
"""
from typing import Any, Dict, List, Optional

from .confidence import compute_intertemporal_consistency


def _strength_bucket(dir_score: float, cfg: Dict[str, Any]) -> str:
    strong_th = cfg.get("posture_direction_strong_threshold", 1.0)
    med_th = cfg.get("posture_direction_med_threshold", 0.6)
    if abs(dir_score) >= strong_th:
        return "strong"
    if abs(dir_score) >= med_th:
        return "medium"
    return "weak"


def compute_posture_5d(
    dir_score: float,
    history_scores: Optional[List[float]],
    cfg: Dict[str, Any]
) -> Dict[str, Any]:
    """
    基于 5 日一致性 + 今日方向强度输出 posture_5d
    """
    n_days = cfg.get("consistency_days", 5)
    consistency_5d = compute_intertemporal_consistency(history_scores or [], n_days)
    consistency_5d = max(-1.0, min(1.0, consistency_5d))
    abs_consistency = abs(consistency_5d)
    
    consistency_strong = cfg.get("posture_consistency_strong_threshold", 0.6)
    consistency_weak = cfg.get("posture_consistency_weak_threshold", 0.2)
    
    today_sign = 1 if dir_score > 0 else -1 if dir_score < 0 else 0
    trend_sign = 1 if consistency_5d > 0 else -1 if consistency_5d < 0 else 0
    strength_bucket = _strength_bucket(dir_score, cfg)
    
    posture = "CHOP"
    reason_codes: List[str] = []
    reasons: List[str] = []
    
    # 解释性文本
    reasons.append(f"5日一致性 {'强' if abs_consistency >= consistency_strong else '弱' if abs_consistency <= consistency_weak else '中等'} ({consistency_5d:.2f})")
    if today_sign == trend_sign and today_sign != 0:
        reasons.append("与今日方向同向")
    elif today_sign != 0 and trend_sign != 0 and today_sign != trend_sign:
        reasons.append("与今日方向反向")
    else:
        reasons.append("方向尚未形成趋势")
    reasons.append(f"今日方向强度: {strength_bucket}")
    
    # 分类
    if abs_consistency >= consistency_strong and today_sign != 0 and today_sign == trend_sign:
        posture = "TREND_CONFIRM"
        reason_codes.append("POSTURE_TREND_CONFIRM")
    elif abs_consistency >= consistency_strong and today_sign != 0 and trend_sign != 0 and today_sign != trend_sign:
        posture = "COUNTERTREND"
        reason_codes.append("POSTURE_COUNTERTREND")
    elif abs_consistency <= consistency_weak and strength_bucket == "strong":
        posture = "ONE_DAY_SHOCK"
        reason_codes.append("POSTURE_ONE_DAY_SHOCK")
    else:
        posture = "CHOP"
        reason_codes.append("POSTURE_CHOP")
    
    # 置信度
    posture_confidence = "中"
    if posture in ("TREND_CONFIRM", "COUNTERTREND") and abs_consistency >= consistency_strong and strength_bucket != "weak":
        posture_confidence = "高"
    elif posture == "CHOP" and strength_bucket == "weak" and abs_consistency <= consistency_weak:
        posture_confidence = "低"
    
    return {
        "posture_5d": posture,
        "posture_reasons": reasons,
        "posture_reason_codes": reason_codes,
        "posture_confidence": posture_confidence,
        "posture_inputs_snapshot": {
            "consistency_5d": round(consistency_5d, 3),
            "today_direction_sign": today_sign,
            "abs_direction_strength_bucket": strength_bucket
        }
    }
