"""
置信度与流动性计算模块 - v2.4 Phase E

核心约束：
1) 所有修正项只通过 confidence 通道表达，不改写 score。
2) 缺失数据只进入 data_confidence 分量。
3) 与 score 同源的结构项保留为解释层，不做二次加权。
"""
from typing import Any, Dict, List, Optional, Tuple


CRITICAL_MISSING_FEATURES = {"IV30", "HV20", "HV1Y", "IVR", "VIX"}

# 单通道聚合权重（structure 默认 explain-only，不参与最终加权）
CONFIDENCE_COMPONENT_WEIGHTS = {
    "strength_confidence": 0.45,
    "data_confidence": 0.35,
    "execution_confidence": 0.15,
    "structure_confidence": 0.00,
    "consistency_confidence": 0.05,
}


def _to_label(score: float) -> str:
    if score >= 0.72:
        return "高"
    if score >= 0.45:
        return "中"
    return "低"


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _component_payload(
    score: float,
    *,
    configured_weight: float,
    applied: bool,
    inputs: Dict[str, Any],
    notes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    applied_weight = configured_weight if applied else 0.0
    return {
        "score": round(_clamp01(score), 4),
        "label": _to_label(_clamp01(score)),
        "configured_weight": round(float(configured_weight), 4),
        "applied_weight": round(float(applied_weight), 4),
        "applied": bool(applied),
        "inputs": inputs,
        "notes": notes or [],
    }


def map_liquidity(rec: Dict[str, Any], cfg: Dict[str, Any]) -> str:
    """
    流动性分级（保持不变）
    """
    call_v = rec.get("CallVolume", 0) or 0
    put_v = rec.get("PutVolume", 0) or 0
    total_v = call_v + put_v
    rel_vol = rec.get("RelVolTo90D", 1.0) or 1.0
    call_n = rec.get("CallNotional", 0.0) or 0.0
    put_n = rec.get("PutNotional", 0.0) or 0.0
    total_n = call_n + put_n
    oi_rank = rec.get("OI_PctRank", None)
    trade_cnt = rec.get("TradeCount", None)
    
    high = (total_v >= max(1_000_000, cfg["abs_volume_min"] * 20) or
            total_n >= 300_000_000 or
            rel_vol >= cfg["relvol_hot"] or
            (isinstance(oi_rank, (int, float)) and oi_rank >= cfg["liq_high_oi_rank"]) or
            (isinstance(trade_cnt, (int, float)) and trade_cnt >= cfg["liq_tradecount_min"] * 5))
    if high:
        return "高"
    
    med = (total_v >= max(200_000, cfg["abs_volume_min"]) or
           total_n >= 100_000_000 or
           rel_vol >= 1.00 or
           (isinstance(oi_rank, (int, float)) and oi_rank >= cfg["liq_med_oi_rank"]) or
           (isinstance(trade_cnt, (int, float)) and trade_cnt >= cfg["liq_tradecount_min"]))
    return "中" if med else "低"


def compute_structure_factor(rec: Dict[str, Any], cfg: Dict[str, Any]) -> float:
    """
    结构置信度调整因子（保持不变）
    """
    multi_leg = rec.get("MultiLegPct", 0) or 0
    single_leg = rec.get("SingleLegPct", 0) or 0
    contingent = rec.get("ContingentPct", 0) or 0
    
    thresh_multi = cfg.get("multileg_conf_thresh", 40.0)
    thresh_single = cfg.get("singleleg_conf_thresh", 70.0)
    thresh_cont = cfg.get("contingent_conf_thresh", 10.0)
    
    if isinstance(multi_leg, (int, float)) and multi_leg >= thresh_multi:
        return 0.8
    elif isinstance(single_leg, (int, float)) and single_leg >= thresh_single:
        return 1.1
    elif isinstance(contingent, (int, float)) and contingent >= thresh_cont:
        return 0.9
    return 1.0


def compute_intertemporal_consistency(
    history_scores: List[float],
    n_days: int = 5
) -> float:
    """
    跨期一致性（保持不变）
    """
    if not history_scores:
        return 0.0
    
    scores = history_scores[:n_days]
    if not scores:
        return 0.0
    
    sign_sum = sum(1 if s > 0 else (-1 if s < 0 else 0) for s in scores)
    return sign_sum / len(scores)


def _strength_confidence_component(
    dir_score: float,
    vol_score: float,
    cfg: Dict[str, Any],
) -> Tuple[float, Dict[str, Any]]:
    dir_abs = abs(float(dir_score))
    vol_abs = abs(float(vol_score))
    vol_threshold = float(cfg.get("vol_pref_threshold", cfg.get("penalty_vol_pct_thresh", 0.40)))

    dir_strength = 1.0 if dir_abs >= 1.0 else 0.65 if dir_abs >= 0.6 else 0.35
    vol_strength = 1.0 if vol_abs >= (vol_threshold + 0.4) else 0.65 if vol_abs >= vol_threshold else 0.35
    score = 0.5 * (dir_strength + vol_strength)

    return score, {
        "dir_abs": round(dir_abs, 4),
        "vol_abs": round(vol_abs, 4),
        "dir_strength": round(dir_strength, 4),
        "vol_strength": round(vol_strength, 4),
        "vol_threshold": round(vol_threshold, 4),
    }


def _data_confidence_component(
    missing_features: Optional[List[str]],
    data_quality: Optional[str],
) -> Tuple[float, str, Dict[str, Any], float]:
    explicit_missing = sorted(set(missing_features or []))
    critical_missing = sorted(set(explicit_missing).intersection(CRITICAL_MISSING_FEATURES))
    missing_penalty_legacy = min(0.6, 0.15 * len(critical_missing))

    if len(critical_missing) >= 3:
        score = 0.2
    elif len(critical_missing) >= 1:
        score = 0.55
    else:
        score = 0.9

    dq = str(data_quality or "HIGH").upper()
    if dq == "LOW":
        score = min(score, 0.2)
    elif dq == "MED":
        score = min(score, 0.55)

    inputs = {
        "critical_missing_features": critical_missing,
        "critical_missing_count": len(critical_missing),
        "data_quality": dq,
        "missing_penalty_legacy": round(missing_penalty_legacy, 3),
    }
    return score, _to_label(score), inputs, missing_penalty_legacy


def _execution_confidence_component(liquidity: str) -> Tuple[float, Dict[str, Any]]:
    liq = str(liquidity or "")
    if liq == "高":
        score = 0.9
    elif liq == "中":
        score = 0.6
    else:
        score = 0.3
    return score, {"liquidity": liq}


def _structure_confidence_component(rec: Dict[str, Any], cfg: Dict[str, Any]) -> Tuple[float, float, Dict[str, Any]]:
    structure_factor = compute_structure_factor(rec, cfg)
    if structure_factor >= 1.05:
        score = 0.75
    elif structure_factor >= 0.95:
        score = 0.6
    elif structure_factor >= 0.85:
        score = 0.45
    else:
        score = 0.3
    inputs = {
        "structure_factor": round(structure_factor, 4),
        "overlap_policy": "explain_only_due_to_score_overlap",
    }
    return score, structure_factor, inputs


def _consistency_confidence_component(
    history_scores: Optional[List[float]],
    cfg: Dict[str, Any],
) -> Tuple[float, float, Dict[str, Any]]:
    n_days = int(cfg.get("consistency_days", 5))
    consistency = compute_intertemporal_consistency(history_scores or [], n_days)
    consistency = max(-1.0, min(1.0, consistency))
    abs_consistency = abs(consistency)
    strong_threshold = float(cfg.get("consistency_strong", 0.6))

    if abs_consistency >= strong_threshold:
        score = 0.8
    elif abs_consistency >= 0.3:
        score = 0.65
    else:
        score = 0.5

    inputs = {
        "consistency": round(consistency, 4),
        "abs_consistency": round(abs_consistency, 4),
        "n_days": n_days,
        "strong_threshold": round(strong_threshold, 4),
    }
    return score, consistency, inputs


def map_confidence(
    dir_score: float,
    vol_score: float,
    liquidity: str,
    rec: Dict[str, Any],
    cfg: Dict[str, Any],
    history_scores: Optional[List[float]] = None,
    data_quality: Optional[str] = None,
    missing_features: Optional[List[str]] = None,
    confidence_breakdown: Optional[Dict[str, Any]] = None,
) -> Tuple[str, float, float]:
    """
    置信度评估 - v2.4 Phase E 单通道机制

    Returns:
        (confidence_label, structure_factor, consistency)
    """
    notes: List[str] = []

    strength_score, strength_inputs = _strength_confidence_component(dir_score, vol_score, cfg)
    data_score, data_label, data_inputs, missing_penalty = _data_confidence_component(missing_features, data_quality)
    execution_score, execution_inputs = _execution_confidence_component(liquidity)
    structure_score, structure_factor, structure_inputs = _structure_confidence_component(rec, cfg)
    consistency_score, consistency, consistency_inputs = _consistency_confidence_component(history_scores, cfg)

    components = {
        "strength_confidence": _component_payload(
            strength_score,
            configured_weight=CONFIDENCE_COMPONENT_WEIGHTS["strength_confidence"],
            applied=True,
            inputs=strength_inputs,
        ),
        "data_confidence": _component_payload(
            data_score,
            configured_weight=CONFIDENCE_COMPONENT_WEIGHTS["data_confidence"],
            applied=True,
            inputs=data_inputs,
        ),
        "execution_confidence": _component_payload(
            execution_score,
            configured_weight=CONFIDENCE_COMPONENT_WEIGHTS["execution_confidence"],
            applied=True,
            inputs=execution_inputs,
        ),
        # 结构项与 direction.positioning 同源：保留解释，不参与二次加权
        "structure_confidence": _component_payload(
            structure_score,
            configured_weight=CONFIDENCE_COMPONENT_WEIGHTS["structure_confidence"],
            applied=False,
            inputs=structure_inputs,
            notes=["overlap_with_direction_positioning_factor"],
        ),
        "consistency_confidence": _component_payload(
            consistency_score,
            configured_weight=CONFIDENCE_COMPONENT_WEIGHTS["consistency_confidence"],
            applied=True,
            inputs=consistency_inputs,
        ),
    }

    weighted_sum = 0.0
    total_weight = 0.0
    for payload in components.values():
        w = float(payload.get("applied_weight", 0.0))
        s = float(payload.get("score", 0.0))
        weighted_sum += w * s
        total_weight += w
    confidence_score = weighted_sum / total_weight if total_weight > 0 else 0.5
    confidence_score = _clamp01(confidence_score)
    confidence_label = _to_label(confidence_score)

    if data_label == "低":
        notes.append("关键字段缺失或数据质量低，data_confidence=低")
    elif data_label == "中":
        notes.append("关键字段部分缺失或数据质量中等，data_confidence=中")

    if confidence_breakdown is not None:
        confidence_breakdown.update({
            "governance_version": "v2.4-phase-e",
            "confidence_score": round(confidence_score, 4),
            "confidence_label": confidence_label,
            "final_confidence": confidence_label,
            "data_confidence": data_label,
            "components": components,
            "weights": {k: round(v, 4) for k, v in CONFIDENCE_COMPONENT_WEIGHTS.items()},
            "critical_missing_features": data_inputs.get("critical_missing_features", []),
            # 兼容旧字段
            "missing_penalty": round(missing_penalty, 3),
            "consistency": round(consistency, 3),
            "structure_factor": round(structure_factor, 3),
            "notes": notes,
        })

    return (confidence_label, structure_factor, consistency)


def penalize_extreme_move_low_vol(rec: Dict[str, Any], cfg: Dict[str, Any]) -> bool:
    """
    检测极端变动低量情况（保持不变）
    """
    p = rec.get("PriceChgPct", None)
    rel_vol = rec.get("RelVolTo90D", None)
    ivchg = rec.get("IV30ChgPct", None)
    if not isinstance(p, (int, float)):
        return False
    cond_price = abs(float(p)) >= float(cfg["penalty_extreme_chg"])
    cond_vol = isinstance(rel_vol, (int, float)) and float(rel_vol) <= float(cfg["relvol_cold"])
    cond_iv = isinstance(ivchg, (int, float)) and float(ivchg) <= float(cfg["iv_pop_down"])
    return bool(cond_price and (cond_vol or cond_iv))
