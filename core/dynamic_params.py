"""
动态参数计算模块 - v2.4 Phase D

核心原则：
- βₜ/λₜ/αₜ 输入来自高层 regime 因子，而非底层共线字段
- 参数变化受固定预算约束（budget）
- 贴边触发收缩机制（shrink）并可审计
"""
import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .factors import build_direction_factor_space, build_volatility_factor_space


def compute_z_score(
    current_value: float,
    historical_values: List[float],
    min_samples: int = 10
) -> float:
    """
    计算滚动 Z-score
    """
    if not historical_values or len(historical_values) < min_samples:
        return 0.0

    try:
        mean = np.mean(historical_values)
        std = np.std(historical_values, ddof=1)
        if std < 1e-6:
            return 0.0
        z = (current_value - mean) / std
        return float(max(-3.0, min(3.0, z)))
    except Exception as e:
        print(f"Warning: Z-score calculation failed: {e}")
        return 0.0


def _safe_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _weighted_average(items: List[Tuple[Optional[float], float]]) -> float:
    num = 0.0
    den = 0.0
    for value, weight in items:
        if isinstance(value, (int, float)):
            num += float(value) * float(weight)
            den += float(weight)
    if den <= 0:
        return 0.0
    return num / den


def _market_regime_from_vix(vix_value: Any) -> float:
    if not isinstance(vix_value, (int, float)):
        return 0.0
    # 20 附近中性，极端值平滑到 [-1, 1]
    return math.tanh((float(vix_value) - 20.0) / 10.0)


def _get_regime_histories(history_cache: Dict[str, Any], symbol: str) -> Dict[str, List[float]]:
    regimes = history_cache.get("regimes", {})
    symbol_regimes = regimes.get("symbols", {}).get(symbol, {})
    market_regimes = regimes.get("market", {})
    market_hist = market_regimes.get("market_regime", [])

    # 兼容旧缓存：若还没有 market_regime，回退到 VIX 历史并映射
    if not market_hist:
        vix_hist = history_cache.get("vix", {}).get("values", [])
        market_hist = [_market_regime_from_vix(v) for v in vix_hist]

    return {
        "flow_imbalance_regime": list(symbol_regimes.get("flow_imbalance_regime", [])),
        "vol_regime": list(symbol_regimes.get("vol_regime", [])),
        "market_regime": list(market_hist),
    }


def _build_regime_state(
    record: Dict[str, Any],
    vix_value: float,
    history_cache: Dict[str, Any],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    symbol = str(record.get("symbol", "") or "")
    direction_space = build_direction_factor_space(
        record,
        config,
        skip_oi=False,
        missing_features=None,
    )
    volatility_space = build_volatility_factor_space(
        record,
        config,
        ignore_earnings=False,
        missing_features=None,
    )

    d_factors = direction_space.get("factors", {})
    v_factors = volatility_space.get("factors", {})

    flow_regime = _weighted_average([
        (d_factors.get("flow_imbalance", {}).get("value"), 0.75),
        (d_factors.get("positioning", {}).get("value"), 0.25),
    ])
    vol_regime = _weighted_average([
        (v_factors.get("vol_risk_premium", {}).get("value"), 0.55),
        (v_factors.get("vol_level", {}).get("value"), 0.25),
        (v_factors.get("term_structure", {}).get("value"), 0.20),
    ])
    market_regime = _market_regime_from_vix(vix_value)

    histories = _get_regime_histories(history_cache, symbol)
    min_samples = int(config.get("dynamic_regime_min_samples", 8))

    zscores = {
        "flow_imbalance_regime": compute_z_score(flow_regime, histories["flow_imbalance_regime"], min_samples=min_samples),
        "vol_regime": compute_z_score(vol_regime, histories["vol_regime"], min_samples=min_samples),
        "market_regime": compute_z_score(market_regime, histories["market_regime"], min_samples=min_samples),
    }

    return {
        "symbol": symbol,
        "regimes": {
            "flow_imbalance_regime": round(flow_regime, 6),
            "vol_regime": round(vol_regime, 6),
            "market_regime": round(market_regime, 6),
        },
        "regime_zscores": {k: round(v, 6) for k, v in zscores.items()},
        "factor_inputs_used": {
            "direction": direction_space.get("inputs_used", {}),
            "volatility": volatility_space.get("inputs_used", {}),
        },
        "declared_overlaps": {
            "direction": direction_space.get("declared_overlaps", []),
            "volatility": volatility_space.get("declared_overlaps", []),
        },
        "history_lengths": {k: len(v) for k, v in histories.items()},
    }


def _budgeted_param(
    param_name: str,
    base: float,
    min_v: float,
    max_v: float,
    budget: float,
    gain: float,
    regime_z: float,
) -> Tuple[float, Dict[str, Any]]:
    proposed = base * (1 + gain * regime_z)
    lower = max(min_v, base * (1 - budget))
    upper = min(max_v, base * (1 + budget))
    budgeted = _clip(proposed, lower, upper)
    return budgeted, {
        "param": param_name,
        "base": round(base, 6),
        "proposed": round(proposed, 6),
        "budget": round(budget, 6),
        "bounds": {"lower": round(lower, 6), "upper": round(upper, 6)},
        "hit_budget": not math.isclose(proposed, budgeted, rel_tol=0.0, abs_tol=1e-12),
    }


def _apply_edge_shrink(
    param_name: str,
    value: float,
    base: float,
    min_v: float,
    max_v: float,
    prev_edge_hits: int,
    config: Dict[str, Any],
) -> Tuple[float, Dict[str, Any], int]:
    edge_eps = float(config.get("dynamic_edge_epsilon", 0.01))
    hit_threshold = int(config.get("dynamic_edge_hit_threshold", 3))
    shrink_ratio = float(config.get("dynamic_shrink_ratio", 0.35))

    near_lower = abs(value - min_v) <= edge_eps
    near_upper = abs(value - max_v) <= edge_eps
    near_edge = near_lower or near_upper
    edge_hits = prev_edge_hits + 1 if near_edge else max(0, prev_edge_hits - 1)
    triggered = edge_hits >= hit_threshold

    shrunk = value
    if triggered:
        shrunk = base + (value - base) * (1 - shrink_ratio)
        shrunk = _clip(shrunk, min_v, max_v)
        edge_hits = 0

    snapshot = {
        "near_edge": near_edge,
        "near_lower_edge": near_lower,
        "near_upper_edge": near_upper,
        "prev_edge_hits": int(prev_edge_hits),
        "edge_hits_after": int(edge_hits),
        "triggered": bool(triggered),
        "shrink_ratio": round(shrink_ratio, 6),
        "value_before": round(value, 6),
        "value_after": round(shrunk, 6),
    }
    return shrunk, snapshot, edge_hits


def compute_beta_t(
    record: Dict,
    history_cache: Dict,
    config: Dict,
    regime_state: Optional[Dict[str, Any]] = None,
) -> float:
    beta_base = _safe_float(config.get("beta_base", 0.25), 0.25)
    beta_min = _safe_float(config.get("beta_min", 0.20), 0.20)
    beta_max = _safe_float(config.get("beta_max", 0.40), 0.40)
    beta_budget = _safe_float(config.get("dynamic_beta_budget", 0.25), 0.25)
    beta_gain = _safe_float(config.get("beta_regime_gain", 0.12), 0.12)

    if regime_state is None:
        regime_state = _build_regime_state(record, _safe_float(record.get("vix")), history_cache, config)
    z_flow = _safe_float(regime_state.get("regime_zscores", {}).get("flow_imbalance_regime"), 0.0)
    value, _ = _budgeted_param("beta_t", beta_base, beta_min, beta_max, beta_budget, beta_gain, z_flow)
    return value


def compute_lambda_t(
    record: Dict,
    history_cache: Dict,
    config: Dict,
    regime_state: Optional[Dict[str, Any]] = None,
) -> float:
    lambda_base = _safe_float(config.get("lambda_base", 0.45), 0.45)
    lambda_min = _safe_float(config.get("lambda_min", 0.35), 0.35)
    lambda_max = _safe_float(config.get("lambda_max", 0.55), 0.55)
    lambda_budget = _safe_float(config.get("dynamic_lambda_budget", 0.22), 0.22)
    lambda_gain = _safe_float(config.get("lambda_regime_gain", 0.18), 0.18)

    if regime_state is None:
        regime_state = _build_regime_state(record, _safe_float(record.get("vix")), history_cache, config)
    z_vol = _safe_float(regime_state.get("regime_zscores", {}).get("vol_regime"), 0.0)
    value, _ = _budgeted_param("lambda_t", lambda_base, lambda_min, lambda_max, lambda_budget, lambda_gain, z_vol)
    return value


def compute_alpha_t(
    vix_value: float,
    history_cache: Dict,
    config: Dict,
    regime_state: Optional[Dict[str, Any]] = None,
) -> float:
    alpha_base = _safe_float(config.get("alpha_base", 0.45), 0.45)
    alpha_min = _safe_float(config.get("alpha_min", 0.35), 0.35)
    alpha_max = _safe_float(config.get("alpha_max", 0.60), 0.60)
    alpha_budget = _safe_float(config.get("dynamic_alpha_budget", 0.22), 0.22)
    alpha_gain = _safe_float(config.get("alpha_regime_gain", 0.16), 0.16)

    if regime_state is None:
        symbol = ""
        regime_state = _build_regime_state({"symbol": symbol}, vix_value, history_cache, config)
    z_market = _safe_float(regime_state.get("regime_zscores", {}).get("market_regime"), 0.0)
    value, _ = _budgeted_param("alpha_t", alpha_base, alpha_min, alpha_max, alpha_budget, alpha_gain, z_market)
    return value


def apply_ema_smoothing(
    current_value: float,
    previous_ema: Optional[float],
    span: int
) -> float:
    """
    应用指数移动平均（EMA）平滑
    """
    if previous_ema is None:
        return current_value

    alpha = 2.0 / (span + 1)
    return alpha * current_value + (1 - alpha) * previous_ema


def compute_all_dynamic_params(
    record: Dict,
    vix_value: float,
    history_cache: Dict,
    config: Dict
) -> Dict[str, Any]:
    """
    计算所有动态参数（高层 regime 输入 + budget + shrink + EMA）
    """
    symbol = str(record.get("symbol", "") or "")
    regime_state = _build_regime_state(record, vix_value, history_cache, config)

    beta_base = _safe_float(config.get("beta_base", 0.25), 0.25)
    beta_min = _safe_float(config.get("beta_min", 0.20), 0.20)
    beta_max = _safe_float(config.get("beta_max", 0.40), 0.40)
    beta_budget = _safe_float(config.get("dynamic_beta_budget", 0.25), 0.25)
    beta_gain = _safe_float(config.get("beta_regime_gain", 0.12), 0.12)
    z_flow = _safe_float(regime_state["regime_zscores"]["flow_imbalance_regime"], 0.0)
    beta_t_raw, beta_budget_meta = _budgeted_param("beta_t", beta_base, beta_min, beta_max, beta_budget, beta_gain, z_flow)

    lambda_base = _safe_float(config.get("lambda_base", 0.45), 0.45)
    lambda_min = _safe_float(config.get("lambda_min", 0.35), 0.35)
    lambda_max = _safe_float(config.get("lambda_max", 0.55), 0.55)
    lambda_budget = _safe_float(config.get("dynamic_lambda_budget", 0.22), 0.22)
    lambda_gain = _safe_float(config.get("lambda_regime_gain", 0.18), 0.18)
    z_vol = _safe_float(regime_state["regime_zscores"]["vol_regime"], 0.0)
    lambda_t_raw, lambda_budget_meta = _budgeted_param("lambda_t", lambda_base, lambda_min, lambda_max, lambda_budget, lambda_gain, z_vol)

    alpha_base = _safe_float(config.get("alpha_base", 0.45), 0.45)
    alpha_min = _safe_float(config.get("alpha_min", 0.35), 0.35)
    alpha_max = _safe_float(config.get("alpha_max", 0.60), 0.60)
    alpha_budget = _safe_float(config.get("dynamic_alpha_budget", 0.22), 0.22)
    alpha_gain = _safe_float(config.get("alpha_regime_gain", 0.16), 0.16)
    z_market = _safe_float(regime_state["regime_zscores"]["market_regime"], 0.0)
    alpha_t_raw, alpha_budget_meta = _budgeted_param("alpha_t", alpha_base, alpha_min, alpha_max, alpha_budget, alpha_gain, z_market)

    param_history = history_cache.get("params", {}).get(symbol, {})
    beta_ema_prev = param_history.get("beta_t")
    lambda_ema_prev = param_history.get("lambda_t")
    alpha_ema_prev = history_cache.get("params", {}).get("_global", {}).get("alpha_t")

    beta_t = apply_ema_smoothing(beta_t_raw, beta_ema_prev, int(config.get("beta_ema_span", 10)))
    lambda_t = apply_ema_smoothing(lambda_t_raw, lambda_ema_prev, int(config.get("lambda_ema_span", 10)))
    alpha_t = apply_ema_smoothing(alpha_t_raw, alpha_ema_prev, int(config.get("alpha_ema_span", 20)))

    beta_prev_hits = int(param_history.get("beta_t_edge_hits", 0))
    lambda_prev_hits = int(param_history.get("lambda_t_edge_hits", 0))
    alpha_prev_hits = int(history_cache.get("params", {}).get("_global", {}).get("alpha_t_edge_hits", 0))

    beta_t, beta_shrink, beta_hits = _apply_edge_shrink(
        "beta_t", _clip(beta_t, beta_min, beta_max), beta_base, beta_min, beta_max, beta_prev_hits, config
    )
    lambda_t, lambda_shrink, lambda_hits = _apply_edge_shrink(
        "lambda_t", _clip(lambda_t, lambda_min, lambda_max), lambda_base, lambda_min, lambda_max, lambda_prev_hits, config
    )
    alpha_t, alpha_shrink, alpha_hits = _apply_edge_shrink(
        "alpha_t", _clip(alpha_t, alpha_min, alpha_max), alpha_base, alpha_min, alpha_max, alpha_prev_hits, config
    )

    inputs_snapshot = {
        "version": "v2.4-phase-d",
        "symbol": symbol,
        "regimes": regime_state["regimes"],
        "regime_zscores": regime_state["regime_zscores"],
        "history_lengths": regime_state["history_lengths"],
        "factor_inputs_used": regime_state["factor_inputs_used"],
        "declared_overlaps": regime_state["declared_overlaps"],
        "param_inputs": {
            "beta_t": ["flow_imbalance_regime"],
            "lambda_t": ["vol_regime"],
            "alpha_t": ["market_regime"],
        },
        "budget": {
            "beta_t": beta_budget_meta,
            "lambda_t": lambda_budget_meta,
            "alpha_t": alpha_budget_meta,
        },
        "shrinkage": {
            "beta_t": beta_shrink,
            "lambda_t": lambda_shrink,
            "alpha_t": alpha_shrink,
        },
    }

    return {
        "beta_t": beta_t,
        "lambda_t": lambda_t,
        "alpha_t": alpha_t,
        "beta_t_raw": beta_t_raw,
        "lambda_t_raw": lambda_t_raw,
        "alpha_t_raw": alpha_t_raw,
        "inputs_snapshot": inputs_snapshot,
        "state_updates": {
            "beta_t_edge_hits": beta_hits,
            "lambda_t_edge_hits": lambda_hits,
            "alpha_t_edge_hits": alpha_hits,
        },
    }


def validate_dynamic_params(params: Dict[str, float]) -> bool:
    """
    验证动态参数的有效性
    """
    required_keys = ["beta_t", "lambda_t", "alpha_t"]
    for key in required_keys:
        if key not in params:
            return False
        value = params[key]
        if not isinstance(value, (int, float)):
            return False
        if math.isnan(value) or math.isinf(value):
            return False
        if value < 0 or value > 1.0:
            return False
    return True
