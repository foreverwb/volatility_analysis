"""
因子子空间定义（v2.4 Phase C）

目标：
- 将底层字段聚合为少量高层因子
- 明确每个因子的输入字段与缺失状态
- 为审计提供 declared_overlaps（允许但需声明的字段复用）
"""
import math
from typing import Any, Dict, List, Optional, Set

from .metrics import (
    compute_active_open_ratio,
    compute_ivrv,
    compute_term_structure_adjustment,
    compute_term_structure_ratios,
    parse_earnings_date,
    days_until,
)


def _to_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clip(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _factor_payload(
    value: Optional[float],
    inputs_used: List[str],
    missing_fields: List[str],
) -> Dict[str, Any]:
    return {
        "value": _clip(value) if isinstance(value, (int, float)) else None,
        "inputs_used": sorted(set(inputs_used)),
        "missing_fields": sorted(set(missing_fields)),
        "missing": not isinstance(value, (int, float)),
    }


def build_direction_factor_space(
    rec: Dict[str, Any],
    cfg: Dict[str, Any],
    skip_oi: bool = False,
    missing_features: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    factors: Dict[str, Dict[str, Any]] = {}

    # 1) price_momentum: PriceChgPct + RelVolTo90D
    pm_inputs: List[str] = []
    pm_missing: List[str] = []
    pm_parts: List[float] = []

    price_chg = _to_float(rec.get("PriceChgPct"))
    if price_chg is None:
        pm_missing.append("PriceChgPct")
    else:
        pm_inputs.append("PriceChgPct")
        pm_parts.append(0.85 * math.tanh(price_chg / 1.75))

    rel_vol = _to_float(rec.get("RelVolTo90D"))
    if rel_vol is None:
        pm_missing.append("RelVolTo90D")
    else:
        pm_inputs.append("RelVolTo90D")
        if rel_vol >= cfg["relvol_hot"]:
            pm_parts.append(0.15)
        elif rel_vol <= cfg["relvol_cold"]:
            pm_parts.append(-0.08)

    price_momentum = sum(pm_parts) if pm_parts else None
    factors["price_momentum"] = _factor_payload(price_momentum, pm_inputs, pm_missing)

    # 2) flow_imbalance: Call/Put Notional + Call/Put Volume + CP Ratio state
    fi_inputs: List[str] = []
    fi_missing: List[str] = []
    fi_parts: List[float] = []

    call_notional = _to_float(rec.get("CallNotional"))
    put_notional = _to_float(rec.get("PutNotional"))
    notional_bias = None
    if isinstance(call_notional, (int, float)) and isinstance(put_notional, (int, float)) and (call_notional + put_notional) > 0:
        notional_bias = (call_notional - put_notional) / (call_notional + put_notional)
        fi_inputs.extend(["CallNotional", "PutNotional"])
        fi_parts.append(0.55 * _clip(notional_bias))
    else:
        fi_missing.extend(["CallNotional", "PutNotional"])

    call_volume = _to_float(rec.get("CallVolume"))
    put_volume = _to_float(rec.get("PutVolume"))
    vol_bias = None
    if isinstance(call_volume, (int, float)) and isinstance(put_volume, (int, float)) and (call_volume + put_volume) > 0:
        vol_bias = (call_volume - put_volume) / (call_volume + put_volume)
        fi_inputs.extend(["CallVolume", "PutVolume"])
        fi_parts.append(0.30 * _clip(vol_bias))
    else:
        fi_missing.extend(["CallVolume", "PutVolume"])

    cp_ratio = None
    if isinstance(call_notional, (int, float)) and isinstance(put_notional, (int, float)) and call_notional > 0 and put_notional > 0:
        cp_ratio = call_notional / put_notional
        fi_inputs.append("CallNotional")
        fi_inputs.append("PutNotional")
    elif isinstance(call_volume, (int, float)) and isinstance(put_volume, (int, float)) and call_volume > 0 and put_volume > 0:
        cp_ratio = call_volume / put_volume
        fi_inputs.append("CallVolume")
        fi_inputs.append("PutVolume")

    if isinstance(cp_ratio, (int, float)):
        if cp_ratio >= cfg["callput_ratio_bull"]:
            fi_parts.append(0.20)
        elif cp_ratio <= cfg["callput_ratio_bear"]:
            fi_parts.append(-0.20)
    else:
        fi_missing.append("CP_RATIO")

    flow_imbalance = sum(fi_parts) if fi_parts else None
    factors["flow_imbalance"] = _factor_payload(flow_imbalance, fi_inputs, fi_missing)

    # 3) positioning: PutPct + Participation structure + AOR(optional)
    pos_inputs: List[str] = []
    pos_missing: List[str] = []
    pos_parts: List[float] = []

    put_pct = _to_float(rec.get("PutPct"))
    if put_pct is None:
        pos_missing.append("PutPct")
    else:
        pos_inputs.append("PutPct")
        pos_parts.append(0.50 * _clip((50.0 - put_pct) / 50.0))

    single_leg = _to_float(rec.get("SingleLegPct"))
    multi_leg = _to_float(rec.get("MultiLegPct"))
    contingent = _to_float(rec.get("ContingentPct"))
    if isinstance(single_leg, (int, float)):
        pos_inputs.append("SingleLegPct")
        if single_leg >= cfg["singleleg_high"]:
            pos_parts.append(0.15)
    if isinstance(multi_leg, (int, float)):
        pos_inputs.append("MultiLegPct")
        if multi_leg >= cfg["multileg_high"]:
            pos_parts.append(-0.10)
    if isinstance(contingent, (int, float)):
        pos_inputs.append("ContingentPct")
        if contingent >= cfg["contingent_high"]:
            pos_parts.append(-0.10)

    if not skip_oi:
        aor = compute_active_open_ratio(rec)
        if isinstance(aor, (int, float)):
            pos_inputs.append("ΔOI_1D")
            pos_parts.append(0.35 * math.tanh(aor * 3))
        else:
            pos_missing.append("ActiveOpenRatio")

    positioning = sum(pos_parts) if pos_parts else None
    factors["positioning"] = _factor_payload(positioning, pos_inputs, pos_missing)

    inputs_used = {name: payload["inputs_used"] for name, payload in factors.items()}
    return {
        "factors": factors,
        "inputs_used": inputs_used,
        "declared_overlaps": [],
    }


def build_volatility_factor_space(
    rec: Dict[str, Any],
    cfg: Dict[str, Any],
    ignore_earnings: bool = False,
    missing_features: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    factors: Dict[str, Dict[str, Any]] = {}

    # 1) vol_risk_premium: IV30/HV20 relation
    vrp_inputs: List[str] = []
    vrp_missing: List[str] = []
    ivrv_log = compute_ivrv(rec, missing_features=missing_features)
    if isinstance(ivrv_log, (int, float)):
        vrp_inputs.extend(["IV30", "HV20"])
        # IV 高于 HV（ivrv_log>0）通常对应卖波，故取反使其对买波为正
        vol_risk_premium = -ivrv_log
    else:
        vrp_missing.extend(["IV30", "HV20", "IVRV_LOG"])
        vol_risk_premium = None
    factors["vol_risk_premium"] = _factor_payload(vol_risk_premium, vrp_inputs, vrp_missing)

    # 2) vol_level: IVR level + daily IV shock
    vl_inputs: List[str] = []
    vl_missing: List[str] = []
    vl_parts: List[float] = []

    ivr = _to_float(rec.get("IVR"))
    if isinstance(ivr, (int, float)):
        vl_inputs.append("IVR")
        vl_parts.append(-((ivr - 50.0) / 50.0))
    else:
        vl_missing.append("IVR")
        if missing_features is not None:
            missing_features.add("IVR")

    iv30_chg = _to_float(rec.get("IV30ChgPct"))
    if isinstance(iv30_chg, (int, float)):
        vl_inputs.append("IV30ChgPct")
        if iv30_chg >= cfg["iv_pop_up"]:
            vl_parts.append(0.35)
        elif iv30_chg <= cfg["iv_pop_down"]:
            vl_parts.append(-0.35)
        else:
            vl_parts.append(0.0)
    else:
        vl_missing.append("IV30ChgPct")

    vol_level = (sum(vl_parts) / len(vl_parts)) if vl_parts else None
    factors["vol_level"] = _factor_payload(vol_level, vl_inputs, vl_missing)

    # 3) term_structure: dedicated shape factor
    ts_inputs: List[str] = []
    ts_missing: List[str] = []
    term_ratios = compute_term_structure_ratios(rec)
    if term_ratios:
        if "7_30" in term_ratios:
            ts_inputs.extend(["IV7", "IV30"])
        if "30_60" in term_ratios:
            ts_inputs.extend(["IV30", "IV60"])
        if "60_90" in term_ratios:
            ts_inputs.extend(["IV60", "IV90"])
        if "30_90" in term_ratios:
            ts_inputs.extend(["IV30", "IV90"])
        term_structure = compute_term_structure_adjustment(rec, cfg)
    else:
        ts_missing.extend(["IV7", "IV30", "IV60", "IV90"])
        term_structure = None
    factors["term_structure"] = _factor_payload(term_structure, ts_inputs, ts_missing)

    # 4) earnings_event(optional, bounded)
    ev_inputs: List[str] = []
    ev_missing: List[str] = []
    earnings_event = None
    if not ignore_earnings:
        ev_inputs.append("Earnings")
        earn_date = parse_earnings_date(rec.get("Earnings"))
        dte = days_until(earn_date)
        if dte is not None and dte > 0:
            if dte <= 2:
                earnings_event = 0.8
            elif dte <= 7:
                earnings_event = 0.4
            elif dte <= cfg.get("earnings_window_days", 14):
                earnings_event = 0.2
            else:
                earnings_event = 0.0
        else:
            earnings_event = 0.0
    factors["earnings_event"] = _factor_payload(earnings_event, ev_inputs, ev_missing)

    inputs_used = {name: payload["inputs_used"] for name, payload in factors.items()}
    return {
        "factors": factors,
        "inputs_used": inputs_used,
        # IV30 在 risk premium 与 term structure 中有结构性复用，需显式声明
        "declared_overlaps": [
            {"field": "IV30", "factors": ["vol_risk_premium", "term_structure"]},
        ],
    }
