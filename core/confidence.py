"""
置信度与流动性计算模块 - v2.3.2 参数化改进版
支持分项贡献（components）输出
"""
import math
from typing import Any, Dict, List, Optional

from .config import get_vol_score_threshold
from .metrics import compute_iv_ratio, compute_regime_ratio, compute_active_open_ratio


def _is_number(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool)


def _as_float(val: Any, default: float = 0.0) -> float:
    if _is_number(val):
        return float(val)
    try:
        return float(val)
    except Exception:
        return float(default)


def _ramp(x: float, low: float, high: float) -> float:
    if high <= low:
        return 1.0 if x >= high else 0.0
    if x <= low:
        return 0.0
    if x >= high:
        return 1.0
    return (x - low) / (high - low)


def compute_liquidity_score(rec: Dict[str, Any], cfg: Dict[str, Any]) -> tuple:
    """
    计算流动性分数与触发原因。

    Returns:
        (score, reasons)
        - score: [0, 1] 区间
        - reasons: 触发原因编码
    """
    rec = rec or {}
    cfg = cfg or {}

    call_v = rec.get("CallVolume", 0) or 0
    put_v = rec.get("PutVolume", 0) or 0
    total_v = _as_float(call_v + put_v, 0.0)
    rel_vol = _as_float(rec.get("RelVolTo90D", 1.0), 1.0)
    call_n = rec.get("CallNotional", 0.0) or 0.0
    put_n = rec.get("PutNotional", 0.0) or 0.0
    total_n = _as_float(call_n + put_n, 0.0)
    oi_rank = rec.get("OI_PctRank", None)
    trade_cnt = rec.get("TradeCount", None)

    vol_med = max(200_000.0, _as_float(cfg.get("abs_volume_min"), 20_000.0))
    vol_high = max(1_000_000.0, _as_float(cfg.get("abs_volume_min"), 20_000.0) * 20.0)
    notional_med = _as_float(cfg.get("liq_notional_med"), 100_000_000.0)
    notional_high = _as_float(cfg.get("liq_notional_high"), 300_000_000.0)
    oi_med = _as_float(cfg.get("liq_med_oi_rank"), 40.0)
    oi_high = _as_float(cfg.get("liq_high_oi_rank"), 60.0)
    trade_med = _as_float(cfg.get("liq_tradecount_min"), 20_000.0)
    trade_high = max(trade_med * 5.0, trade_med + 1.0)
    relvol_med = 1.0
    relvol_high = _as_float(cfg.get("relvol_hot"), 1.2)

    vol_component = _ramp(math.log10(max(0.0, total_v) + 1.0), math.log10(vol_med + 1.0), math.log10(vol_high + 1.0))
    notional_component = _ramp(
        math.log10(max(0.0, total_n) + 1.0),
        math.log10(max(1.0, notional_med) + 1.0),
        math.log10(max(notional_med + 1.0, notional_high) + 1.0),
    )
    oi_component = _ramp(_as_float(oi_rank, 0.0), oi_med, oi_high) if _is_number(oi_rank) else 0.0
    trade_component = _ramp(_as_float(trade_cnt, 0.0), trade_med, trade_high) if _is_number(trade_cnt) else 0.0
    relvol_component = _ramp(rel_vol, relvol_med, max(relvol_med + 1e-6, relvol_high))

    w_volume = max(0.0, _as_float(cfg.get("liq_weight_volume"), 0.30))
    w_notional = max(0.0, _as_float(cfg.get("liq_weight_notional"), 0.30))
    w_oi = max(0.0, _as_float(cfg.get("liq_weight_oi_rank"), 0.15))
    w_trade = max(0.0, _as_float(cfg.get("liq_weight_tradecount"), 0.15))
    w_relvol = max(0.0, _as_float(cfg.get("liq_weight_relvol"), 0.10))
    w_sum = w_volume + w_notional + w_oi + w_trade + w_relvol
    if w_sum <= 0:
        w_volume, w_notional, w_oi, w_trade, w_relvol = 0.30, 0.30, 0.15, 0.15, 0.10
        w_sum = 1.0
    w_volume /= w_sum
    w_notional /= w_sum
    w_oi /= w_sum
    w_trade /= w_sum
    w_relvol /= w_sum

    score = (
        w_volume * vol_component
        + w_notional * notional_component
        + w_oi * oi_component
        + w_trade * trade_component
        + w_relvol * relvol_component
    )
    score = max(0.0, min(1.0, float(score)))

    reasons: List[str] = []
    if total_v >= vol_high:
        reasons.append("VOLUME_HIGH")
    elif total_v >= vol_med:
        reasons.append("VOLUME_MED")
    else:
        reasons.append("VOLUME_LOW")

    if total_n >= notional_high:
        reasons.append("NOTIONAL_HIGH")
    elif total_n >= notional_med:
        reasons.append("NOTIONAL_MED")
    else:
        reasons.append("NOTIONAL_LOW")

    if _is_number(oi_rank):
        if _as_float(oi_rank) >= oi_high:
            reasons.append("OI_RANK_HIGH")
        elif _as_float(oi_rank) >= oi_med:
            reasons.append("OI_RANK_MED")
        else:
            reasons.append("OI_RANK_LOW")

    if _is_number(trade_cnt):
        trade_low_ratio = max(0.0, _as_float(cfg.get("liq_tradecount_low_ratio"), 0.5))
        if _as_float(trade_cnt) < trade_med * trade_low_ratio:
            reasons.append("TRADECOUNT_LOW")
        elif _as_float(trade_cnt) >= trade_high:
            reasons.append("TRADECOUNT_HIGH")
    else:
        reasons.append("TRADECOUNT_MISSING")

    if rel_vol >= relvol_high:
        reasons.append("RELVOL_HIGH")

    return score, reasons


def map_liquidity(score: Any, cfg: Dict[str, Any]) -> str:
    """
    流动性分级映射。

    兼容旧调用：若传入 dict，会先计算 score 再映射。
    """
    cfg = cfg or {}
    if isinstance(score, dict):
        score, _ = compute_liquidity_score(score, cfg)
    score = _as_float(score, 0.0)

    high_th = _as_float(cfg.get("liquidity_high_th"), 0.72)
    med_th = _as_float(cfg.get("liquidity_med_th"), 0.40)
    if high_th < med_th:
        high_th, med_th = med_th, high_th

    if score >= high_th:
        return "高"
    if score >= med_th:
        return "中"
    return "低"


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
    if isinstance(single_leg, (int, float)) and single_leg >= thresh_single:
        return 1.1
    if isinstance(contingent, (int, float)) and contingent >= thresh_cont:
        return 0.9
    return 1.0


def compute_intertemporal_consistency(history_scores: List[float], n_days: int = 5) -> float:
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


def compute_confidence_components(
    features: Dict[str, Any],
    dir_score: float,
    vol_score: float,
    cfg: Dict[str, Any],
    oi_data_available: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    置信度分项贡献。

    总强度还原公式：
      final_strength = max(0,
          pre_structure_strength
          * structure_factor
          * consistency_factor
          * oi_rank_factor
          * relvol_factor
          * aor_factor
      )
    """
    features = features or {}
    cfg = cfg or {}

    liquidity = features.get("liquidity") or "低"
    ivr_raw = features.get("ivr")
    ivr = _as_float(ivr_raw, 0.0)
    iv_ratio = _as_float(features.get("ivrv_ratio"), 1.0)
    regime = _as_float(features.get("regime_ratio"), 1.0)
    price_chg_raw = features.get("price_chg_pct")
    price_chg = _as_float(price_chg_raw, 0.0)
    rel_vol_raw = features.get("rel_vol_to_90d")
    rel_vol = _as_float(rel_vol_raw, 1.0)
    missing_fields_count = int(_as_float(features.get("missing_fields_count"), 0.0))
    active_open_ratio = _as_float(features.get("active_open_ratio"), 0.0)
    oi_rank_raw = features.get("oi_pct_rank")
    oi_rank = _as_float(oi_rank_raw, 0.0)
    if oi_data_available is None:
        feature_oi_available = features.get("oi_data_available")
        if isinstance(feature_oi_available, bool):
            oi_data_available = feature_oi_available
        elif isinstance(features.get("skip_oi"), bool):
            oi_data_available = not bool(features.get("skip_oi"))
        else:
            oi_data_available = True

    # 1) 分数强度
    dir_strength = 0.6 if abs(dir_score) >= 1.0 else 0.3 if abs(dir_score) >= 0.6 else 0.0
    v_abs = abs(vol_score)
    th = get_vol_score_threshold(cfg, default=0.40)
    vol_strength = 0.6 if v_abs >= (th + 0.4) else 0.3 if v_abs >= th else 0.0

    # 2) 流动性
    liquidity_bonus = 0.5 if liquidity == "高" else 0.25 if liquidity == "中" else 0.0

    # 3) 恐慌环境
    fear_penalty = 0.0
    if (
        _is_number(ivr_raw)
        and ivr >= _as_float(cfg.get("fear_ivrank_min"), 75.0)
        and iv_ratio >= _as_float(cfg.get("fear_ivrv_ratio_min"), 1.30)
        and regime <= _as_float(cfg.get("fear_regime_max"), 1.05)
    ):
        fear_penalty = -0.2

    # 4) 缺失惩罚
    missing_penalty = -0.1 * max(0, missing_fields_count)

    # 5) 极端价动+缩量惩罚
    extreme_move_penalty = 0.0
    if (
        _is_number(price_chg_raw)
        and abs(price_chg) >= _as_float(cfg.get("penalty_extreme_chg"), 20.0)
        and rel_vol <= _as_float(cfg.get("relvol_cold"), 0.8)
    ):
        extreme_move_penalty = -0.3

    # 6) OI 缺失惩罚：数据不可得不等于中性
    missing_oi_penalty = 0.0
    if oi_data_available is False:
        missing_oi_penalty = -max(0.0, _as_float(cfg.get("confidence_missing_oi_penalty"), 0.2))

    pre_structure_strength = (
        dir_strength
        + vol_strength
        + liquidity_bonus
        + fear_penalty
        + missing_penalty
        + extreme_move_penalty
        + missing_oi_penalty
    )

    # 7) 结构因子
    structure_factor = compute_structure_factor(
        {
            "MultiLegPct": features.get("multi_leg_pct"),
            "SingleLegPct": features.get("single_leg_pct"),
            "ContingentPct": features.get("contingent_pct"),
        },
        cfg,
    )

    # 8) 一致性因子
    consistency = _as_float(features.get("consistency"), 0.0)
    history_scores = features.get("history_scores")
    if isinstance(history_scores, list) and history_scores:
        n_days = int(_as_float(cfg.get("consistency_days"), 5.0))
        consistency = compute_intertemporal_consistency(history_scores, n_days)
    consistency = max(-1.0, min(1.0, consistency))

    consistency_weight = _as_float(cfg.get("consistency_weight"), 0.3)
    consistency_thresh = _as_float(cfg.get("consistency_strong"), 0.6)
    consistency_factor = 1.0
    if consistency > consistency_thresh:
        consistency_factor = 1.0 + consistency_weight * consistency
    elif consistency < -consistency_thresh:
        consistency_factor = max(0.1, 1.0 - consistency_weight * abs(consistency))

    # 9) OI Rank 因子
    oi_rank_factor = 1.2 if _is_number(oi_rank_raw) and oi_rank >= _as_float(cfg.get("liq_high_oi_rank"), 60.0) else 1.0

    # 10) 相对量因子
    relvol_factor = 1.1 if _is_number(rel_vol_raw) and rel_vol >= _as_float(cfg.get("relvol_hot"), 1.2) else 1.0

    # 11) AOR 因子
    aor_factor = 0.8 if active_open_ratio < _as_float(cfg.get("active_open_ratio_bear"), -0.05) else 1.0

    after_structure = pre_structure_strength * structure_factor
    after_consistency = after_structure * consistency_factor
    after_oi = after_consistency * oi_rank_factor
    after_relvol = after_oi * relvol_factor
    final_strength = max(0.0, after_relvol * aor_factor)

    confidence_high_th = _as_float(cfg.get("confidence_high_th"), 1.5)
    confidence_med_th = _as_float(cfg.get("confidence_med_th"), 0.75)
    if confidence_high_th < confidence_med_th:
        confidence_high_th, confidence_med_th = confidence_med_th, confidence_high_th

    if final_strength >= confidence_high_th:
        label = "高"
    elif final_strength >= confidence_med_th:
        label = "中"
    else:
        label = "低"

    return {
        "dir_strength": float(dir_strength),
        "vol_strength": float(vol_strength),
        "liquidity_bonus": float(liquidity_bonus),
        "fear_penalty": float(fear_penalty),
        "missing_penalty": float(missing_penalty),
        "extreme_move_penalty": float(extreme_move_penalty),
        "missing_oi_penalty": float(missing_oi_penalty),
        "oi_data_available": bool(oi_data_available),
        "pre_structure_strength": float(pre_structure_strength),
        "structure_factor": float(structure_factor),
        "consistency": float(consistency),
        "consistency_factor": float(consistency_factor),
        "oi_rank_factor": float(oi_rank_factor),
        "relvol_factor": float(relvol_factor),
        "aor_factor": float(aor_factor),
        "final_strength": float(final_strength),
        "confidence_score": float(final_strength),
        "confidence_high_th": float(confidence_high_th),
        "confidence_med_th": float(confidence_med_th),
        "label": label,
    }


def map_confidence(
    dir_score: float,
    vol_score: float,
    liquidity: str,
    rec: Dict[str, Any],
    cfg: Dict[str, Any],
    history_scores: Optional[List[float]] = None,
    features: Optional[Dict[str, Any]] = None,
    oi_data_available: Optional[bool] = None,
) -> tuple:
    """
    置信度评估：兼容旧接口，内部由 components 结果驱动。

    Returns:
        (confidence_label, structure_factor, consistency)
    """
    working_features = dict(features or {})

    # 兼容历史调用：缺什么就从 rec 补什么
    working_features.setdefault("liquidity", liquidity)
    working_features.setdefault("ivr", rec.get("IVR"))
    working_features.setdefault("ivrv_ratio", compute_iv_ratio(rec))
    working_features.setdefault("regime_ratio", compute_regime_ratio(rec))
    working_features.setdefault("price_chg_pct", rec.get("PriceChgPct"))
    working_features.setdefault("rel_vol_to_90d", rec.get("RelVolTo90D"))
    working_features.setdefault("single_leg_pct", rec.get("SingleLegPct"))
    working_features.setdefault("multi_leg_pct", rec.get("MultiLegPct"))
    working_features.setdefault("contingent_pct", rec.get("ContingentPct"))
    working_features.setdefault("active_open_ratio", compute_active_open_ratio(rec))
    working_features.setdefault("oi_pct_rank", rec.get("OI_PctRank"))
    if "oi_data_available" not in working_features:
        if isinstance(oi_data_available, bool):
            working_features["oi_data_available"] = oi_data_available
        else:
            oi_info = rec.get("oi_info") if isinstance(rec.get("oi_info"), dict) else {}
            if isinstance(oi_info.get("data_available"), bool):
                working_features["oi_data_available"] = oi_info.get("data_available")
            elif isinstance(rec.get("oi_data_available"), bool):
                working_features["oi_data_available"] = rec.get("oi_data_available")

    if "missing_fields_count" not in working_features:
        working_features["missing_fields_count"] = sum(
            1
            for k in ["PriceChgPct", "RelVolTo90D", "CallVolume", "PutVolume", "IV30", "HV20", "IVR"]
            if rec.get(k) is None
        )

    if history_scores is not None and "history_scores" not in working_features:
        working_features["history_scores"] = list(history_scores)

    components = compute_confidence_components(
        working_features,
        dir_score,
        vol_score,
        cfg,
        oi_data_available=working_features.get("oi_data_available")
        if isinstance(working_features.get("oi_data_available"), bool)
        else oi_data_available,
    )
    return (
        components["label"],
        float(components["structure_factor"]),
        float(components["consistency"]),
    )


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
