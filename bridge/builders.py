from datetime import datetime
from typing import Any, Dict, Optional

from core.metrics import (
    compute_term_structure_adjustment,
    compute_term_structure_ratios,
    parse_earnings_date,
)

from .spec import BridgeSnapshot, TermStructureSnapshot


def _safe_float(val: Any) -> Optional[float]:
    if isinstance(val, (int, float)):
        return float(val)
    if val is None:
        return None
    try:
        return float(str(val).replace("%", "").replace(",", ""))
    except Exception:
        return None


def _classify_term_structure(ratios: Dict[str, float]) -> str:
    short = ratios.get("7_30")
    mid = ratios.get("30_60")
    long = ratios.get("60_90")

    if short is None or mid is None or long is None:
        return "N/A"

    if short > 1.05 and mid > 1.05 and long > 1.05:
        return "全面倒挂 (Full inversion)"
    if short > 1.05 and mid <= 1.0:
        return "短期倒挂 (Short-term inversion)"
    if mid > 1.05 and short <= 1.02 and long <= 1.0:
        return "中期突起 (Mid-term bulge)"
    if long > 1.05 and mid <= 1.0:
        return "远期过高 (Far-term elevated)"
    if short < 0.9 and mid >= 0.95:
        return "短期低位 (Short-term low)"
    if short < 1.0 and mid < 1.0 and long < 1.0:
        return "正常陡峭 (Normal steep)"
    return "正常陡峭 (Normal steep)"


def _state_flags(label: str) -> Dict[str, bool]:
    label = label or ""
    return {
        "full_inversion": "Full inversion" in label or "全面倒挂" in label,
        "short_inversion": "Short-term inversion" in label or "短期倒挂" in label,
        "mid_bulge": "Mid-term bulge" in label or "中期突起" in label,
        "far_elevated": "Far-term elevated" in label or "远期过高" in label,
        "short_low": "Short-term low" in label or "短期低位" in label,
        "normal_steep": "Normal steep" in label or "正常陡峭" in label,
    }


def _derive_label_code(flags: Dict[str, bool]) -> str:
    priority = [
        "full_inversion",
        "short_inversion",
        "mid_bulge",
        "far_elevated",
        "short_low",
        "normal_steep",
    ]
    for key in priority:
        if flags.get(key):
            return key
    return "unknown"


def _heuristic_bias(label_code: str) -> Dict[str, float]:
    heuristics = {
        "short_low": {"short": 0.20, "mid": -0.05, "long": -0.10},
        "full_inversion": {"short": 0.25, "mid": -0.10, "long": -0.20},
        "far_elevated": {"short": -0.05, "mid": 0.10, "long": 0.20},
        "normal_steep": {"short": -0.05, "mid": 0.05, "long": 0.10},
    }
    return heuristics.get(label_code, {"short": 0.0, "mid": 0.0, "long": 0.0})


def _horizon_bias(label_code: str, cfg: Dict[str, Any]) -> Dict[str, float]:
    defaults = (cfg or {}).get("bridge_term_structure_horizon_bias", {}) or {}
    bias = defaults.get(label_code) or defaults.get("default")
    if bias:
        return bias
    return _heuristic_bias(label_code)


def _extract_symbol(rec: Dict[str, Any]) -> Optional[str]:
    symbol = rec.get("symbol") or rec.get("Symbol")
    if isinstance(symbol, str):
        return symbol.upper()
    return symbol


def _extract_as_of(rec: Dict[str, Any]) -> str:
    ts = rec.get("timestamp") or rec.get("as_of")
    if isinstance(ts, str) and ts:
        return ts.split(" ")[0]
    return datetime.now().strftime("%Y-%m-%d")


def _parse_earnings_iso(rec: Dict[str, Any]) -> Optional[str]:
    earnings_raw = rec.get("earning_date") or rec.get("Earnings")
    if isinstance(earnings_raw, str):
        try:
            return datetime.strptime(earnings_raw, "%Y-%m-%d").date().isoformat()
        except ValueError:
            pass
    d = parse_earnings_date(earnings_raw)
    if d:
        return d.isoformat()
    return None


def build_term_structure_snapshot(rec: Dict[str, Any], cfg: Dict[str, Any]) -> TermStructureSnapshot:
    ratios = compute_term_structure_ratios(rec)
    ratio_30_90 = ratios.get("30_90")

    # compute_term_structure returns (ratio, ratio_string), but we only need ratios + label
    label = _classify_term_structure(ratios)

    try:
        adjustment = compute_term_structure_adjustment(rec, cfg)
    except Exception:
        adjustment = 0.0

    state_flags = _state_flags(label)
    label_code = _derive_label_code(state_flags)
    horizon_bias = _horizon_bias(label_code, cfg)

    return TermStructureSnapshot(
        ratios=ratios,
        label=label,
        label_code=label_code,
        ratio_30_90=ratio_30_90,
        adjustment=adjustment,
        horizon_bias=horizon_bias,
        state_flags=state_flags,
    )


def build_bridge_snapshot(rec: Dict[str, Any], cfg: Dict[str, Any]) -> BridgeSnapshot:
    term_structure = build_term_structure_snapshot(rec, cfg)
    symbol = _extract_symbol(rec)
    as_of = _extract_as_of(rec)

    earnings_iso = _parse_earnings_iso(rec)
    days_to_earnings = rec.get("days_to_earnings")
    is_earnings_window = False
    try:
        is_earnings_window = (
            isinstance(days_to_earnings, (int, float))
            and days_to_earnings >= 0
            and days_to_earnings <= cfg.get("earnings_window_days", 14)
        )
    except Exception:
        is_earnings_window = False

    market_state = {
        "symbol": symbol,
        "as_of": as_of,
        "vix": _safe_float(rec.get("vix") or rec.get("VIX")),
        "ivr": _safe_float(rec.get("IVR") or rec.get("ivr")),
        "iv30": _safe_float(rec.get("IV30") or rec.get("iv30")),
        "hv20": _safe_float(rec.get("HV20") or rec.get("hv20")),
        "hv1y": _safe_float(rec.get("HV1Y") or rec.get("hv1y")),
        "term_structure_label": term_structure.label,
        "term_structure_ratio": term_structure.ratio_30_90,
        "term_structure_adjustment": term_structure.adjustment,
    }

    event_state = {
        "earnings_date": earnings_iso,
        "days_to_earnings": days_to_earnings,
        "is_earnings_window": is_earnings_window,
        "is_index": bool(rec.get("is_index", False)),
        "is_squeeze": bool(rec.get("is_squeeze", False)),
    }

    execution_state = {
        "quadrant": rec.get("quadrant"),
        "direction_score": _safe_float(rec.get("direction_score")),
        "vol_score": _safe_float(rec.get("vol_score")),
        "direction_bias": rec.get("direction_bias"),
        "vol_bias": rec.get("vol_bias"),
        "confidence": rec.get("confidence"),
        "liquidity": rec.get("liquidity"),
        "active_open_ratio": _safe_float(rec.get("active_open_ratio")),
        "oi_data_available": rec.get("oi_data_available"),
        "penalized_extreme_move_low_vol": rec.get("penalized_extreme_move_low_vol"),
        "flow_bias": _safe_float(rec.get("flow_bias")),
    }

    return BridgeSnapshot(
        symbol=symbol,
        as_of=as_of,
        market_state=market_state,
        event_state=event_state,
        execution_state=execution_state,
        term_structure=term_structure,
    )
