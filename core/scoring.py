"""
评分模型模块 - v2.3.3
支持分项贡献（components）输出，便于调试与回测
"""
import math
from typing import Any, Dict

from .term_structure import (
    classify_term_structure_label,
    compute_term_structure_adjustment,
    compute_term_structure_ratios,
    map_horizon_bias_to_dte_bias,
)


def _is_number(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool)


def _as_float(val: Any, default: float = 0.0) -> float:
    if _is_number(val):
        return float(val)
    try:
        return float(val)
    except Exception:
        return float(default)


def compute_direction_components(features: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    DirectionScore 分项贡献。

    总分还原公式：
      final_score = base_sum * structure_amp * aor_gate
    """
    features = features or {}
    cfg = cfg or {}

    price_chg_pct = _as_float(features.get("price_chg_pct"), 0.0)
    rel_vol = _as_float(features.get("rel_vol_to_90d"), 1.0)
    vol_bias = _as_float(features.get("volume_bias"), 0.0)
    notional_bias = _as_float(features.get("notional_bias"), 0.0)
    notional_intensity = _as_float(features.get("notional_intensity"), 0.0)
    cp_ratio_raw = _as_float(features.get("cp_ratio"), 1.0)
    put_pct_raw = features.get("put_pct")
    put_pct = _as_float(put_pct_raw, 50.0)
    spot_vol = _as_float(features.get("spot_vol_score"), 0.0)

    intensity_enable = bool(cfg.get("dir_intensity_enable", True))
    intensity_k = _as_float(cfg.get("dir_intensity_k"), 0.10)
    cap_low = _as_float(cfg.get("dir_intensity_cap_low"), 0.80)
    cap_high = _as_float(cfg.get("dir_intensity_cap_high"), 1.30)
    if cap_low > cap_high:
        cap_low, cap_high = cap_high, cap_low
    intensity_multiplier_raw = 1.0 + intensity_k * notional_intensity
    intensity_multiplier = (
        max(cap_low, min(cap_high, intensity_multiplier_raw))
        if intensity_enable
        else 1.0
    )

    # 加法项
    price_momentum = 0.90 * math.tanh(price_chg_pct / 1.75)
    flow_bias_raw = 0.60 * notional_bias
    volume_bias_raw = 0.35 * vol_bias
    flow_bias = flow_bias_raw * intensity_multiplier
    volume_bias = volume_bias_raw * intensity_multiplier

    relvol_raw = 0.0
    if rel_vol >= _as_float(cfg.get("relvol_hot"), 1.2):
        relvol_raw = 0.18
    elif rel_vol <= _as_float(cfg.get("relvol_cold"), 0.8):
        relvol_raw = -0.05
    relvol = relvol_raw * intensity_multiplier

    cp_ratio = 0.0
    if cp_ratio_raw >= _as_float(cfg.get("callput_ratio_bull"), 1.3):
        cp_ratio = 0.30
    elif cp_ratio_raw <= _as_float(cfg.get("callput_ratio_bear"), 0.77):
        cp_ratio = -0.30

    put_pct_term = 0.0
    if _is_number(put_pct_raw):
        if put_pct >= _as_float(cfg.get("putpct_bear"), 55.0):
            put_pct_term = -0.20
        elif put_pct <= _as_float(cfg.get("putpct_bull"), 45.0):
            put_pct_term = 0.20
        else:
            put_pct_term = 0.20 * (50.0 - put_pct) / 50.0

    base_sum = price_momentum + flow_bias + volume_bias + relvol + cp_ratio + put_pct_term + spot_vol

    # 结构放大项（连续函数，避免阶跃）
    structure_purity = features.get("structure_purity")
    if not _is_number(structure_purity):
        single_leg = _as_float(features.get("single_leg_pct"), 0.0)
        multi_leg = _as_float(features.get("multi_leg_pct"), 0.0)
        contingent = _as_float(features.get("contingent_pct"), 0.0)
        structure_purity = (single_leg - multi_leg - 0.5 * contingent) / 100.0
    structure_purity = max(-1.0, min(1.0, _as_float(structure_purity, 0.0)))

    structure_amp_base = _as_float(cfg.get("dir_structure_amp_base"), 1.0)
    structure_amp_k = _as_float(cfg.get("dir_structure_amp_k"), 0.15)
    structure_amp_raw = structure_amp_base + structure_amp_k * structure_purity
    structure_amp = max(0.7, min(1.3, structure_amp_raw))

    # AOR 闸门
    skip_oi = bool(features.get("skip_oi", False))
    active_open_ratio = _as_float(features.get("active_open_ratio"), 0.0)
    dynamic_apply = bool(features.get("dynamic_apply", False))

    if dynamic_apply:
        beta_t = _as_float(features.get("beta_t"), _as_float(cfg.get("beta_base"), 0.25))
    else:
        beta_t = _as_float(cfg.get("active_open_ratio_beta"), 0.5)

    aor_capped = math.tanh(active_open_ratio * 3.0)
    aor_gate = 1.0 if skip_oi else (1.0 + beta_t * aor_capped)

    final_score = float(base_sum * structure_amp * aor_gate)

    return {
        "price_momentum": float(price_momentum),
        "flow_bias_raw": float(flow_bias_raw),
        "flow_bias": float(flow_bias),
        "volume_bias_raw": float(volume_bias_raw),
        "volume_bias": float(volume_bias),
        "relvol_raw": float(relvol_raw),
        "relvol": float(relvol),
        "cp_ratio": float(cp_ratio),
        "put_pct": float(put_pct_term),
        "spot_vol": float(spot_vol),
        "notional_intensity": float(notional_intensity),
        "intensity_multiplier_raw": float(intensity_multiplier_raw),
        "intensity_multiplier": float(intensity_multiplier),
        "intensity_enable": bool(intensity_enable),
        "base_sum": float(base_sum),
        "structure_purity": float(structure_purity),
        "structure_amp_base": float(structure_amp_base),
        "structure_amp_k": float(structure_amp_k),
        "structure_amp_raw": float(structure_amp_raw),
        "structure_amp": float(structure_amp),
        "aor_gate": float(aor_gate),
        "aor_capped": float(aor_capped),
        "beta_t": float(beta_t),
        "skip_oi": bool(skip_oi),
        "active_open_ratio": float(active_open_ratio),
        "final_score": float(final_score),
    }


def compute_direction_score(features: Dict[str, Any], cfg: Dict[str, Any]) -> float:
    """DirectionScore 总分（由 components 组合还原）。"""
    components = compute_direction_components(features, cfg)
    return float(components["final_score"])


def compute_vol_components(features: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    VolScore 分项贡献。

    总分还原公式：
      final_score = (base_spread + term_structure) * multileg_gate * dynamic_gate
    """
    features = features or {}
    cfg = cfg or {}

    ivr_raw = features.get("ivr")
    ivr = _as_float(ivr_raw, 50.0)
    ivrv = _as_float(features.get("ivrv_log"), 0.0)
    iv_ratio = _as_float(features.get("ivrv_ratio"), 1.0)
    iv30_chg = _as_float(features.get("iv30_chg_pct"), 0.0)
    hv20_raw = features.get("hv20")
    iv30_raw = features.get("iv30")
    hv20 = _as_float(hv20_raw, 0.0)
    iv30 = _as_float(iv30_raw, 0.0)
    regime = _as_float(features.get("regime_ratio"), 1.0)
    multi_leg_raw = features.get("multi_leg_pct")
    multi_leg = _as_float(multi_leg_raw, 0.0)

    # 卖波压力
    ivr_center = (ivr - 50.0) / 50.0 if _is_number(ivr_raw) else 0.0
    sell_pressure_ivr = 1.2 * ivr_center
    sell_pressure_ivrv = 1.2 * ivrv
    sell_pressure = sell_pressure_ivr + sell_pressure_ivrv

    # 当日 IV 变化
    iv_change_buy = 0.5 if iv30_chg >= _as_float(cfg.get("iv_pop_up"), 10.0) else 0.0
    iv_change_sell = 0.5 if iv30_chg <= _as_float(cfg.get("iv_pop_down"), -10.0) else 0.0

    # 折价项
    discount_ratio = 0.0
    if _is_number(hv20_raw) and _is_number(iv30_raw) and hv20 > 0:
        discount_ratio = max(0.0, (hv20 - iv30) / hv20)
    discount = 0.8 * discount_ratio

    # 便宜/昂贵
    longcheap = (
        (_is_number(ivr_raw) and ivr <= _as_float(cfg.get("iv_longcheap_rank"), 30.0))
        or (iv_ratio <= _as_float(cfg.get("iv_longcheap_ratio"), 0.95))
    )
    shortrich = (
        (_is_number(ivr_raw) and ivr >= _as_float(cfg.get("iv_shortrich_rank"), 70.0))
        or (iv_ratio >= _as_float(cfg.get("iv_shortrich_ratio"), 1.15))
    )
    cheap_boost = 0.6 if longcheap else 0.0
    rich_pressure = 0.6 if shortrich else 0.0

    # 财报事件
    ignore_earnings = bool(features.get("ignore_earnings", False))
    dte_raw = features.get("days_to_earnings")
    dte = _as_float(dte_raw, -1.0)
    earn_boost = 0.0
    if not ignore_earnings and _is_number(dte_raw) and dte > 0:
        if dte <= 2:
            earn_boost = 0.8
        elif dte <= 7:
            earn_boost = 0.4
        elif dte <= _as_float(cfg.get("earnings_window_days"), 14.0):
            earn_boost = 0.2

    # 恐慌环境卖波倾向
    fear_sell = 0.0
    if (
        _is_number(ivr_raw)
        and ivr >= _as_float(cfg.get("fear_ivrank_min"), 75.0)
        and iv_ratio >= _as_float(cfg.get("fear_ivrv_ratio_min"), 1.3)
        and regime <= _as_float(cfg.get("fear_regime_max"), 1.05)
    ):
        fear_sell = 0.4

    # Regime 调整
    regime_term = 0.0
    if regime >= _as_float(cfg.get("regime_hot"), 1.2):
        regime_term = 0.2
    elif regime <= _as_float(cfg.get("regime_calm"), 0.8):
        regime_term = -0.2

    buy_side = discount + iv_change_buy + cheap_boost + earn_boost + regime_term
    sell_side = sell_pressure + rich_pressure + iv_change_sell + fear_sell
    base_spread = buy_side - sell_side

    term_structure_ratios = features.get("term_structure_ratios")
    if not isinstance(term_structure_ratios, dict):
        term_structure_ratios = {}
    if not term_structure_ratios:
        term_structure_ratios = compute_term_structure_ratios(features)

    term_structure_label_code = features.get("term_structure_label_code")
    term_structure_horizon_bias = features.get("term_structure_horizon_bias")
    if not isinstance(term_structure_label_code, str) or not isinstance(term_structure_horizon_bias, str):
        term_structure_meta = classify_term_structure_label(term_structure_ratios, cfg)
        term_structure_label_code = str(term_structure_meta.get("label_code", "unknown"))
        term_structure_horizon_bias = str(term_structure_meta.get("horizon_bias", "neutral"))
    else:
        term_structure_meta = {
            "label_code": term_structure_label_code,
            "horizon_bias": term_structure_horizon_bias,
        }

    term_structure_term = features.get("term_structure_adjustment")
    if not _is_number(term_structure_term):
        term_structure_term = compute_term_structure_adjustment(term_structure_meta, term_structure_ratios, cfg)
    term_structure_term = _as_float(term_structure_term, 0.0)
    term_structure_dte_bias = map_horizon_bias_to_dte_bias(term_structure_horizon_bias, cfg)

    pre_multileg_score = base_spread + term_structure_term

    multileg_gate = 1.0
    if _is_number(multi_leg_raw) and _is_number(ivr_raw):
        if multi_leg > 40 and ivr > 70:
            multileg_gate = 0.8
        elif multi_leg > 40 and ivr < 30:
            multileg_gate = 0.9

    after_multileg = pre_multileg_score * multileg_gate

    dynamic_apply = bool(features.get("dynamic_apply", False))
    lambda_t = _as_float(features.get("lambda_t"), _as_float(cfg.get("lambda_base"), 0.45))
    alpha_t = _as_float(features.get("alpha_t"), _as_float(cfg.get("alpha_base"), 0.45))
    dynamic_gate = (1.0 + alpha_t * lambda_t) if dynamic_apply else 1.0

    final_score = float(after_multileg * dynamic_gate)

    return {
        "discount": float(discount),
        "iv_change_buy": float(iv_change_buy),
        "cheap_boost": float(cheap_boost),
        "earn_boost": float(earn_boost),
        "regime_term": float(regime_term),
        "buy_side": float(buy_side),
        "sell_pressure_ivr": float(sell_pressure_ivr),
        "sell_pressure_ivrv": float(sell_pressure_ivrv),
        "sell_pressure": float(sell_pressure),
        "rich_pressure": float(rich_pressure),
        "iv_change_sell": float(iv_change_sell),
        "fear_sell": float(fear_sell),
        "sell_side": float(sell_side),
        "base_spread": float(base_spread),
        "term_structure": float(term_structure_term),
        "term_structure_term": float(term_structure_term),
        "term_structure_label_code": str(term_structure_label_code),
        "term_structure_horizon_bias": str(term_structure_horizon_bias),
        "term_structure_dte_bias": str(term_structure_dte_bias),
        "pre_multileg_score": float(pre_multileg_score),
        "multileg_gate": float(multileg_gate),
        "dynamic_gate": float(dynamic_gate),
        "lambda_t": float(lambda_t),
        "alpha_t": float(alpha_t),
        "dynamic_apply": bool(dynamic_apply),
        "final_score": float(final_score),
    }


def compute_vol_score(features: Dict[str, Any], cfg: Dict[str, Any]) -> float:
    """VolScore 总分（由 components 组合还原）。"""
    components = compute_vol_components(features, cfg)
    return float(components["final_score"])
