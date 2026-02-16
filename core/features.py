"""
统一派生特征构建模块
"""
import math
from typing import Any, Dict

from .metrics import (
    compute_active_open_ratio,
    compute_callput_ratio,
    compute_iv_ratio,
    compute_ivrv,
    compute_notional_bias,
    compute_regime_ratio,
    compute_spot_vol_correlation_score,
    compute_term_structure,
    compute_volume_bias,
    compute_squeeze_score,
    days_until,
    parse_earnings_date,
    safe_div,
)
from .term_structure import (
    classify_term_structure_label,
    compute_term_structure_adjustment as compute_term_structure_adjustment_shared,
    compute_term_structure_ratios,
    map_horizon_bias_to_dte_bias,
)


def _extract_oi_fields(rec: Dict[str, Any]) -> tuple:
    oi_info = rec.get("oi_info") if isinstance(rec.get("oi_info"), dict) else {}

    total_oi = None
    for key in ("total_oi", "current_oi"):
        val = oi_info.get(key)
        if isinstance(val, (int, float)):
            total_oi = float(val)
            break
    if total_oi is None:
        for key in ("TotalOI", "total_oi", "OI", "OpenInterest", "TotalOpenInterest"):
            val = rec.get(key)
            if isinstance(val, (int, float)):
                total_oi = float(val)
                break

    delta_oi_1d = None
    for key in ("delta_oi_1d", "delta_oi"):
        val = oi_info.get(key)
        if isinstance(val, (int, float)):
            delta_oi_1d = float(val)
            break
    if delta_oi_1d is None:
        for key in ("ΔOI_1D", "DeltaOI_1D", "delta_oi_1d"):
            val = rec.get(key)
            if isinstance(val, (int, float)):
                delta_oi_1d = float(val)
                break

    return (total_oi, delta_oi_1d)


def build_features(rec: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    构建统一派生特征字典。

    Args:
        rec: 已清洗/标准化/校验后的记录
        cfg: 当前有效配置
    """
    cfg = cfg or {}

    call_volume = rec.get("CallVolume", 0) or 0
    put_volume = rec.get("PutVolume", 0) or 0
    call_notional = rec.get("CallNotional", 0.0) or 0.0
    put_notional = rec.get("PutNotional", 0.0) or 0.0

    total_volume = float(call_volume + put_volume)
    total_notional = float(call_notional + put_notional)
    notional_base = float(cfg.get("dir_intensity_notional_base", 1_000_000.0) or 1_000_000.0)
    notional_intensity = math.log10(max(0.0, total_notional) / notional_base + 1.0)
    single_leg_pct = rec.get("SingleLegPct")
    multi_leg_pct = rec.get("MultiLegPct")
    contingent_pct = rec.get("ContingentPct")

    single_leg_val = float(single_leg_pct) if isinstance(single_leg_pct, (int, float)) else 0.0
    multi_leg_val = float(multi_leg_pct) if isinstance(multi_leg_pct, (int, float)) else 0.0
    contingent_val = float(contingent_pct) if isinstance(contingent_pct, (int, float)) else 0.0
    structure_purity_raw = (single_leg_val - multi_leg_val - 0.5 * contingent_val) / 100.0
    structure_purity = max(-1.0, min(1.0, structure_purity_raw))

    iv30 = rec.get("IV30")
    hv20 = rec.get("HV20", 1)
    hv1y = rec.get("HV1Y", 1)
    ivrv_ratio = (
        iv30 / hv20
        if (isinstance(iv30, (int, float)) and isinstance(hv20, (int, float)) and hv20 > 0)
        else 1.0
    )
    ivrv_diff = (
        iv30 - hv20
        if (isinstance(iv30, (int, float)) and isinstance(hv20, (int, float)))
        else 0.0
    )
    regime_ratio = (
        hv20 / hv1y
        if (isinstance(hv20, (int, float)) and isinstance(hv1y, (int, float)) and hv1y > 0)
        else 1.0
    )

    term_structure_value, term_structure_label = compute_term_structure(rec)
    term_structure_ratios = compute_term_structure_ratios(rec)
    term_structure_meta = classify_term_structure_label(term_structure_ratios, cfg)
    term_structure_horizon_bias = term_structure_meta.get("horizon_bias", "neutral")
    term_structure_dte_bias = map_horizon_bias_to_dte_bias(term_structure_horizon_bias, cfg)
    term_structure_adjustment = compute_term_structure_adjustment_shared(
        term_structure_meta,
        term_structure_ratios,
        cfg,
    )
    notional_bias = compute_notional_bias(rec)
    spot_vol_score = compute_spot_vol_correlation_score(rec)
    total_oi, delta_oi_1d = _extract_oi_fields(rec)
    delta_oi_pct = None
    oi_turnover = None
    if isinstance(total_oi, (int, float)) and total_oi > 0:
        if isinstance(delta_oi_1d, (int, float)):
            delta_oi_pct = safe_div(float(delta_oi_1d), float(total_oi), None)
        volume_for_turnover = rec.get("Volume")
        if not isinstance(volume_for_turnover, (int, float)):
            volume_for_turnover = total_volume
        oi_turnover = safe_div(float(volume_for_turnover), float(total_oi), None)

    missing_fields_count = sum(
        1
        for k in ["PriceChgPct", "RelVolTo90D", "CallVolume", "PutVolume", "IV30", "HV20", "IVR"]
        if rec.get(k) is None
    )

    features = {
        # 原始输入快照（供评分/置信度分项计算）
        "price_chg_pct": rec.get("PriceChgPct"),
        "rel_vol_to_90d": rec.get("RelVolTo90D"),
        "put_pct": rec.get("PutPct"),
        "single_leg_pct": single_leg_pct,
        "multi_leg_pct": multi_leg_pct,
        "contingent_pct": contingent_pct,
        "structure_purity": structure_purity,
        "iv30_chg_pct": rec.get("IV30ChgPct"),
        "ivr": rec.get("IVR"),
        "iv30": rec.get("IV30"),
        "hv20": rec.get("HV20"),
        "oi_pct_rank": rec.get("OI_PctRank"),
        "missing_fields_count": missing_fields_count,

        # 方向/成交结构
        "volume_bias": compute_volume_bias(rec),
        "notional_bias": notional_bias,
        "flow_bias": notional_bias,
        "cp_ratio": compute_callput_ratio(rec),
        # 波动相关
        "ivrv_log": compute_ivrv(rec),
        "ivrv_ratio": float(ivrv_ratio),
        "iv_ratio": compute_iv_ratio(rec),
        "ivrv_diff": float(ivrv_diff),
        "regime_ratio": float(regime_ratio),
        # 价格-波动联动
        "spot_vol_score": spot_vol_score,
        "spot_vol_corr_score": spot_vol_score,
        # OI/流量
        "active_open_ratio": compute_active_open_ratio(rec),
        "total_oi": total_oi,
        "delta_oi_1d": delta_oi_1d,
        "delta_oi_pct": delta_oi_pct,
        # 期限结构
        "term_structure_value": term_structure_value,
        "term_structure_ratio": term_structure_label,
        "term_structure_label": term_structure_meta.get("label", "N/A"),
        "term_structure_label_code": term_structure_meta.get("label_code", "unknown"),
        "term_structure_horizon_bias": term_structure_horizon_bias,
        "term_structure_dte_bias": term_structure_dte_bias,
        "term_structure_ratios": term_structure_ratios,
        "term_structure_adjustment": term_structure_adjustment,
        # 事件
        "days_to_earnings": days_until(parse_earnings_date(rec.get("Earnings"))),
        # 新增预留特征
        "total_volume": total_volume,
        "total_notional": total_notional,
        "notional_intensity": notional_intensity,
        "oi_turnover": oi_turnover,

        # 运行时上下文占位（由 analyzer 在调用链中补充）
        "skip_oi": False,
        "ignore_earnings": False,
        "dynamic_apply": False,
        "beta_t": None,
        "lambda_t": None,
        "alpha_t": None,
        "liquidity": None,
        "history_scores": [],
    }

    squeeze_score, squeeze_reasons = compute_squeeze_score(features, cfg)
    squeeze_trigger = float(cfg.get("squeeze_score_trigger", 0.70))
    features["squeeze_score"] = float(squeeze_score)
    features["squeeze_reasons"] = list(squeeze_reasons)
    features["is_squeeze"] = bool(squeeze_score >= squeeze_trigger)

    return features
