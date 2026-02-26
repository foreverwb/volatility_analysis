"""
评分模型模块 - v2.4 Phase C

仅组合高层因子子空间输出 direction_score / vol_score。
"""
from typing import Any, Dict, Optional, Set, Tuple

from .factors import build_direction_factor_space, build_volatility_factor_space


def _resolve_weights(cfg: Dict[str, Any], key: str, defaults: Dict[str, float]) -> Dict[str, float]:
    custom = cfg.get(key)
    if not isinstance(custom, dict):
        return defaults.copy()
    out = defaults.copy()
    for factor_name, val in custom.items():
        if factor_name in out and isinstance(val, (int, float)):
            out[factor_name] = float(val)
    return out


def _combine_factor_space(
    factor_space: Dict[str, Any],
    weights: Dict[str, float],
) -> Tuple[float, Dict[str, Any]]:
    factors = factor_space.get("factors", {})
    raw_weighted_sum = 0.0
    active_weight = 0.0
    active_factors = []

    for factor_name, weight in weights.items():
        payload = factors.get(factor_name, {})
        value = payload.get("value")
        if isinstance(value, (int, float)):
            raw_weighted_sum += float(weight) * float(value)
            active_weight += float(weight)
            active_factors.append(factor_name)

    normalized_score = raw_weighted_sum / active_weight if active_weight > 0 else 0.0
    breakdown = {
        "factors": factors,
        "weights": weights,
        "inputs_used": factor_space.get("inputs_used", {}),
        "declared_overlaps": factor_space.get("declared_overlaps", []),
        "active_factors": active_factors,
        "active_weight": round(active_weight, 6),
        "raw_weighted_sum": round(raw_weighted_sum, 6),
        "normalized_score": round(normalized_score, 6),
    }
    return normalized_score, breakdown


def compute_direction_score(
    rec: Dict[str, Any],
    cfg: Dict[str, Any],
    dynamic_params: Optional[Dict[str, float]] = None,
    skip_oi: bool = False,
    missing_features: Optional[Set[str]] = None,
    score_breakdown: Optional[Dict[str, Any]] = None,
) -> float:
    defaults = {
        "price_momentum": 0.45,
        "flow_imbalance": 0.35,
        "positioning": 0.20,
    }
    weights = _resolve_weights(cfg, "direction_factor_weights", defaults)
    factor_space = build_direction_factor_space(
        rec,
        cfg,
        skip_oi=skip_oi,
        missing_features=missing_features,
    )
    base_score, breakdown = _combine_factor_space(factor_space, weights)

    # 动态参数仍作为整体调节器，不引入底层字段重复计分
    adjustment_factor = 1.0
    adjustment_meta = {
        "source": "beta_t",
        "enabled": False,
        "raw_delta": 0.0,
        "clamped_delta": 0.0,
        "budget": float(cfg.get("dynamic_direction_adjustment_budget", 0.20)),
    }
    if dynamic_params and cfg.get("enable_dynamic_params", False):
        beta_t = dynamic_params.get("beta_t")
        beta_base = cfg.get("beta_base", 0.25)
        if isinstance(beta_t, (int, float)) and isinstance(beta_base, (int, float)) and beta_base != 0:
            raw_delta = (float(beta_t) - float(beta_base)) / float(beta_base)
            budget = float(cfg.get("dynamic_direction_adjustment_budget", 0.20))
            clamped_delta = max(-budget, min(budget, raw_delta))
            adjustment_factor = 1.0 + clamped_delta
            adjustment_meta = {
                "source": "beta_t",
                "enabled": True,
                "raw_delta": round(raw_delta, 6),
                "clamped_delta": round(clamped_delta, 6),
                "budget": round(budget, 6),
            }

    score = float(base_score * adjustment_factor)
    breakdown["dynamic_adjustment_factor"] = round(adjustment_factor, 6)
    breakdown["adjustment"] = {**adjustment_meta, "factor": round(adjustment_factor, 6)}
    breakdown["final_score"] = round(score, 6)
    if score_breakdown is not None:
        score_breakdown["direction"] = breakdown
    return score


def compute_vol_score(
    rec: Dict[str, Any],
    cfg: Dict[str, Any],
    ignore_earnings: bool = False,
    dynamic_params: Optional[Dict[str, float]] = None,
    missing_features: Optional[Set[str]] = None,
    score_breakdown: Optional[Dict[str, Any]] = None,
) -> float:
    defaults = {
        "vol_risk_premium": 0.50,
        "vol_level": 0.25,
        "term_structure": 0.20,
        "earnings_event": 0.05,
    }
    weights = _resolve_weights(cfg, "volatility_factor_weights", defaults)
    factor_space = build_volatility_factor_space(
        rec,
        cfg,
        ignore_earnings=ignore_earnings,
        missing_features=missing_features,
    )
    base_score, breakdown = _combine_factor_space(factor_space, weights)

    adjustment_factor = 1.0
    adjustment_meta = {
        "source": "lambda_t+alpha_t",
        "enabled": False,
        "raw_delta": 0.0,
        "clamped_delta": 0.0,
        "budget": float(cfg.get("dynamic_vol_adjustment_budget", 0.25)),
    }
    if dynamic_params and cfg.get("enable_dynamic_params", False):
        lambda_t = dynamic_params.get("lambda_t")
        alpha_t = dynamic_params.get("alpha_t")
        lambda_base = cfg.get("lambda_base", 0.45)
        alpha_base = cfg.get("alpha_base", 0.45)
        if (
            isinstance(lambda_t, (int, float))
            and isinstance(alpha_t, (int, float))
            and isinstance(lambda_base, (int, float))
            and isinstance(alpha_base, (int, float))
            and lambda_base != 0
            and alpha_base != 0
        ):
            delta_lambda = (float(lambda_t) - float(lambda_base)) / float(lambda_base)
            delta_alpha = (float(alpha_t) - float(alpha_base)) / float(alpha_base)
            raw_delta = 0.5 * (delta_lambda + delta_alpha)
            budget = float(cfg.get("dynamic_vol_adjustment_budget", 0.25))
            clamped_delta = max(-budget, min(budget, raw_delta))
            adjustment_factor = 1.0 + clamped_delta
            adjustment_meta = {
                "source": "lambda_t+alpha_t",
                "enabled": True,
                "raw_delta": round(raw_delta, 6),
                "clamped_delta": round(clamped_delta, 6),
                "budget": round(budget, 6),
            }

    score = float(base_score * adjustment_factor)
    breakdown["dynamic_adjustment_factor"] = round(adjustment_factor, 6)
    breakdown["adjustment"] = {**adjustment_meta, "factor": round(adjustment_factor, 6)}
    breakdown["final_score"] = round(score, 6)
    if score_breakdown is not None:
        score_breakdown["volatility"] = breakdown
    return score
