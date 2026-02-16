"""
统一期限结构计算与分类模块
"""
from typing import Any, Dict, Optional


def _safe_float(val: Any) -> Optional[float]:
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    if val is None:
        return None
    try:
        return float(str(val).replace("%", "").replace(",", ""))
    except Exception:
        return None


def _first_number(rec: Dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        val = _safe_float(rec.get(key))
        if val is not None:
            return val
    return None


def _ratio(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _default_horizon_bias(label_code: str) -> str:
    mapping = {
        # 近端昂贵，倾向避免短期限裸露 gamma，偏向中长周期结构
        "full_inversion": "long",
        "short_inversion": "long",
        # 中段突起更适合中周期表达
        "mid_bulge": "mid",
        # 远端偏贵或正常陡峭，偏向短端 carry
        "far_elevated": "short",
        "short_low": "short",
        "normal_steep": "short",
        "flat": "neutral",
        "unknown": "neutral",
    }
    return mapping.get(label_code, "neutral")


def _resolve_horizon_bias(label_code: str, cfg: Dict[str, Any]) -> str:
    """
    解析期限偏好（short/mid/long/neutral）。
    兼容旧配置中使用 dict 权重的形式：取权重最大的方向。
    """
    cfg = cfg or {}
    defaults = cfg.get("bridge_term_structure_horizon_bias", {}) or {}
    raw = defaults.get(label_code) or defaults.get("default")
    if isinstance(raw, str):
        v = raw.strip().lower()
        if v in {"short", "mid", "long", "neutral"}:
            return v
    if isinstance(raw, dict):
        ranked = sorted(
            (
                ("short", float(raw.get("short", 0.0))),
                ("mid", float(raw.get("mid", 0.0))),
                ("long", float(raw.get("long", 0.0))),
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        if ranked and ranked[0][1] > 0:
            return ranked[0][0]
    return _default_horizon_bias(label_code)


def map_horizon_bias_to_dte_bias(horizon_bias: Any, cfg: Dict[str, Any]) -> str:
    """
    将 horizon_bias 映射为可执行的 DTE 偏好标签。
    """
    cfg = cfg or {}
    default_map = {
        "short": "short_term_0_30d",
        "mid": "mid_term_30_60d",
        "long": "long_term_60d_plus",
        "neutral": "neutral",
    }
    custom_map = cfg.get("term_structure_dte_bias_map")
    mapping = default_map
    if isinstance(custom_map, dict):
        mapping = {
            "short": str(custom_map.get("short", default_map["short"])),
            "mid": str(custom_map.get("mid", default_map["mid"])),
            "long": str(custom_map.get("long", default_map["long"])),
            "neutral": str(custom_map.get("neutral", default_map["neutral"])),
        }

    hb = str(horizon_bias or "neutral").lower()
    if hb not in {"short", "mid", "long", "neutral"}:
        hb = "neutral"
    return mapping[hb]


def compute_term_structure_ratios(rec: Dict[str, Any]) -> Dict[str, float]:
    """
    计算期限结构比率（包含标准命名与兼容命名）。
    """
    rec = rec or {}
    iv7 = _first_number(rec, "IV7", "iv7")
    iv30 = _first_number(rec, "IV30", "iv30")
    iv60 = _first_number(rec, "IV60", "iv60")
    iv90 = _first_number(rec, "IV90", "iv90")

    r_7_30 = _ratio(iv7, iv30)
    r_30_60 = _ratio(iv30, iv60)
    r_60_90 = _ratio(iv60, iv90)
    r_30_90 = _ratio(iv30, iv90)

    ratios: Dict[str, float] = {}
    if r_7_30 is not None:
        ratios["iv7_iv30_ratio"] = r_7_30
        ratios["7_30"] = r_7_30
    if r_30_60 is not None:
        ratios["iv30_iv60_ratio"] = r_30_60
        ratios["30_60"] = r_30_60
    if r_60_90 is not None:
        ratios["iv60_iv90_ratio"] = r_60_90
        ratios["60_90"] = r_60_90
    if r_30_90 is not None:
        ratios["iv30_iv90_ratio"] = r_30_90
        ratios["30_90"] = r_30_90
    return ratios


def classify_term_structure_label(ratios: Dict[str, float], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    统一期限结构分类。

    Returns:
        {
          "label": str,
          "label_code": str,
          "horizon_bias": "short|mid|long|neutral",
        }
    """
    ratios = ratios or {}
    cfg = cfg or {}
    short = ratios.get("7_30", ratios.get("iv7_iv30_ratio"))
    mid = ratios.get("30_60", ratios.get("iv30_iv60_ratio"))
    long = ratios.get("60_90", ratios.get("iv60_iv90_ratio"))
    ratio_30_90 = ratios.get("30_90", ratios.get("iv30_iv90_ratio"))

    inv_th = float(cfg.get("term_inversion_threshold", 1.05))
    flat_tol = float(cfg.get("term_flat_tolerance", 0.025))
    short_low_th = float(cfg.get("term_short_low_threshold", 0.90))
    far_elevated_th = float(cfg.get("term_far_elevated_threshold", 0.95))

    label_code = "unknown"
    label = "N/A"
    if short is not None and mid is not None and long is not None:
        is_flat = (
            abs(short - 1.0) <= flat_tol
            and abs(mid - 1.0) <= flat_tol
            and abs(long - 1.0) <= flat_tol
        )
        if short >= inv_th and mid >= inv_th and long >= 1.0:
            label_code = "full_inversion"
            label = "全面倒挂 (Full inversion)"
        elif short >= inv_th:
            label_code = "short_inversion"
            label = "短期倒挂 (Short-term inversion)"
        elif mid >= inv_th and short <= 1.02 and long <= 1.02:
            label_code = "mid_bulge"
            label = "中期突起 (Mid-term bulge)"
        elif long <= far_elevated_th and short <= 1.02 and mid <= 1.02:
            label_code = "far_elevated"
            label = "远期过高 (Far-term elevated)"
        elif short <= short_low_th and mid >= 0.95:
            label_code = "short_low"
            label = "短期低位 (Short-term low)"
        elif is_flat:
            label_code = "flat"
            label = "平坦结构 (Flat)"
        elif short < 1.0 and mid < 1.0 and long < 1.0:
            label_code = "normal_steep"
            label = "正常陡峭 (Normal steep)"
        else:
            label_code = "flat"
            label = "平坦结构 (Flat)"
    elif ratio_30_90 is not None:
        if abs(ratio_30_90 - 1.0) <= flat_tol:
            label_code = "flat"
            label = "平坦结构 (Flat)"
        elif ratio_30_90 < 1.0:
            label_code = "normal_steep"
            label = "正常陡峭 (Normal steep)"
        elif ratio_30_90 >= inv_th:
            label_code = "short_inversion"
            label = "短期倒挂 (Short-term inversion)"
        else:
            label_code = "flat"
            label = "平坦结构 (Flat)"

    return {
        "label": label,
        "label_code": label_code,
        "horizon_bias": _resolve_horizon_bias(label_code, cfg),
    }


def compute_term_structure_adjustment(label: Dict[str, Any], ratios: Dict[str, float], cfg: Dict[str, Any]) -> float:
    """
    基于期限结构状态输出 VolScore 调整项（正值偏买波，负值偏卖波）。
    """
    ratios = ratios or {}
    cfg = cfg or {}
    if not ratios:
        return 0.0

    short_weight = float(cfg.get("term_short_weight", 0.35))
    mid_weight = float(cfg.get("term_mid_weight", 0.25))
    long_weight = float(cfg.get("term_long_weight", 0.15))
    cap = float(cfg.get("term_adjust_cap", 0.6))

    short = ratios.get("7_30", ratios.get("iv7_iv30_ratio"))
    mid = ratios.get("30_60", ratios.get("iv30_iv60_ratio"))
    long = ratios.get("60_90", ratios.get("iv60_iv90_ratio"))
    ratio_30_90 = ratios.get("30_90", ratios.get("iv30_iv90_ratio"))

    ratio_component = 0.0
    if isinstance(short, (int, float)):
        ratio_component += short_weight * (short - 1.0)
    if isinstance(mid, (int, float)):
        ratio_component += mid_weight * (mid - 1.0)
    if isinstance(long, (int, float)):
        ratio_component += long_weight * (long - 1.0)
    if (not isinstance(long, (int, float))) and isinstance(ratio_30_90, (int, float)):
        ratio_component += long_weight * (ratio_30_90 - 1.0)

    label_code = str((label or {}).get("label_code") or "unknown")
    state_bonus_map = {
        "full_inversion": 0.10,
        "short_inversion": 0.07,
        "mid_bulge": 0.04,
        "far_elevated": -0.10,
        "short_low": -0.05,
        "normal_steep": -0.06,
        "flat": 0.0,
        "unknown": 0.0,
    }
    state_bonus_overrides = cfg.get("term_structure_state_bonus")
    if isinstance(state_bonus_overrides, dict):
        for key in state_bonus_map:
            if key in state_bonus_overrides:
                try:
                    state_bonus_map[key] = float(state_bonus_overrides[key])
                except (TypeError, ValueError):
                    continue

    adj = ratio_component + state_bonus_map.get(label_code, 0.0)
    return max(-cap, min(cap, float(adj)))
