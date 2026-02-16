"""
核心指标计算模块
v2.3.2 - 新增 ActiveOpenRatio, Term Structure 等
✨ NEW: 优雅处理缺失的 ΔOI 数据
"""
import math
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple

from .term_structure import (
    classify_term_structure_label as _classify_term_structure_label_shared,
    compute_term_structure_adjustment as _compute_term_structure_adjustment_shared,
    compute_term_structure_ratios as _compute_term_structure_ratios_shared,
)


def safe_div(a: float, b: float, default: float = 0.0) -> float:
    """安全除法"""
    try:
        return a / b if b != 0 else default
    except:
        return default


def compute_volume_bias(rec: Dict[str, Any]) -> float:
    """计算成交量偏度: (CallVol - PutVol) / (CallVol + PutVol)"""
    cv = rec.get("CallVolume", 0) or 0
    pv = rec.get("PutVolume", 0) or 0
    return safe_div((cv - pv), (cv + pv), 0.0)


def compute_notional_bias(rec: Dict[str, Any]) -> float:
    """
    计算名义金额偏度 (FlowBias)
    FlowBias = (CallNotional - PutNotional) / (CallNotional + PutNotional)
    """
    cn = rec.get("CallNotional", 0) or 0.0
    pn = rec.get("PutNotional", 0) or 0.0
    return safe_div((cn - pn), (cn + pn), 0.0)


def compute_callput_ratio(rec: Dict[str, Any]) -> float:
    """计算 Call/Put 比率"""
    cn = rec.get("CallNotional", 0) or 0.0
    pn = rec.get("PutNotional", 0) or 0.0
    if cn > 0 and pn > 0:
        return safe_div(cn, pn, 1.0)
    cv = rec.get("CallVolume", 0) or 0
    pv = rec.get("PutVolume", 0) or 0
    return safe_div(cv, pv, 1.0)


def compute_ivrv(rec: Dict[str, Any]) -> float:
    """计算 IVRV (log): ln(IV30 / HV20)"""
    iv30 = rec.get("IV30")
    hv20 = rec.get("HV20")
    if not isinstance(iv30, (int, float)) or not isinstance(hv20, (int, float)):
        return 0.0
    if iv30 <= 0 or hv20 <= 0:
        return 0.0
    return math.log(iv30 / hv20)


def compute_iv_ratio(rec: Dict[str, Any]) -> float:
    """计算 IV/HV 比率: IV30 / HV20"""
    iv30 = rec.get("IV30")
    hv20 = rec.get("HV20")
    if not isinstance(iv30, (int, float)) or not isinstance(hv20, (int, float)) or hv20 <= 0:
        return 1.0
    return float(iv30) / float(hv20)


def compute_regime_ratio(rec: Dict[str, Any]) -> float:
    """计算 Regime 比率: HV20 / HV1Y"""
    hv20 = rec.get("HV20")
    hv1y = rec.get("HV1Y")
    if not isinstance(hv20, (int, float)) or not isinstance(hv1y, (int, float)) or hv1y <= 0:
        return 1.0
    return float(hv20) / float(hv1y)


def compute_spot_vol_correlation_score(rec: Dict[str, Any]) -> float:
    """
    计算价-波相关性分数 (Spot-Vol Correlation)
    
    场景 A: 🔥 逼空/动量 (价升波升) -> +0.4
    场景 B: ⚠️ 恐慌抛售 (价跌波升) -> -0.5
    场景 C: 📈 磨涨/稳健 (价升波降) -> +0.2
    """
    price_chg = rec.get("PriceChgPct", 0.0) or 0.0
    iv_chg = rec.get("IV30ChgPct", 0.0) or 0.0
    
    try:
        price_chg = float(price_chg)
        iv_chg = float(iv_chg)
    except:
        return 0.0
    
    # 场景 A: 逼空/动量 (价升波升)
    if price_chg > 0.5 and iv_chg > 2.0:
        return 0.4
    # 场景 B: 恐慌抛售 (价跌波升)
    elif price_chg < -0.5 and iv_chg > 2.0:
        return -0.5
    # 场景 C: 磨涨 (价升波降)
    elif price_chg > 0 and iv_chg < -2.0:
        return 0.2
    return 0.0


def _as_float(val: Any, default: float = 0.0) -> float:
    try:
        if isinstance(val, bool) or val is None:
            return float(default)
        return float(val)
    except Exception:
        return float(default)


def _ramp(x: float, low: float, high: float) -> float:
    """线性映射到 [0, 1]。"""
    if high <= low:
        return 1.0 if x >= high else 0.0
    if x <= low:
        return 0.0
    if x >= high:
        return 1.0
    return (x - low) / (high - low)


def _coalesce_value(src: Dict[str, Any], keys: Tuple[str, ...], default: Any = None) -> Any:
    for key in keys:
        if key in src and src.get(key) is not None:
            return src.get(key)
    return default


def compute_squeeze_score(features: Dict[str, Any], cfg: Dict[str, Any]) -> Tuple[float, List[str]]:
    """
    连续 Gamma Squeeze 评分，返回 (score, reasons)。

    评分范围: [0, 1]
    """
    features = features or {}
    cfg = cfg or {}
    reasons: List[str] = []

    # 1) IV30/HV20 越低越容易挤压（0.8 以下给满分，1.2 以上为 0）
    iv_ratio = _as_float(
        _coalesce_value(features, ("ivrv_ratio", "iv_ratio"), compute_iv_ratio(features)),
        1.0,
    )
    iv_discount_score = 1.0 - _ramp(iv_ratio, 0.8, 1.2)
    if iv_ratio <= 0.95:
        reasons.append("LOW_IV_VS_HV")

    # 2) OI rank 越高越拥挤
    oi_rank = _as_float(_coalesce_value(features, ("oi_pct_rank", "OI_PctRank"), 0.0), 0.0)
    oi_score = _ramp(oi_rank, 40.0, 90.0)
    if oi_rank >= 70.0:
        reasons.append("HIGH_OI_RANK")

    # 3) 相对成交量/强度越高越容易形成挤压链式反应
    rel_vol = _as_float(
        _coalesce_value(features, ("rel_vol_to_90d", "RelVolTo90D", "volume_intensity"), 1.0),
        1.0,
    )
    rel_vol_score = _ramp(rel_vol, 1.0, 2.2)
    if rel_vol >= 1.3:
        reasons.append("HIGH_REL_VOLUME")

    # 4) 价格上行且达到“异动强度”门槛
    price_chg = _as_float(_coalesce_value(features, ("price_chg_pct", "PriceChgPct"), 0.0), 0.0)
    price_z = _coalesce_value(features, ("price_z",), None)
    if price_z is None:
        price_z = price_chg / max(1e-6, _as_float(cfg.get("squeeze_price_z_scale"), 2.0))
    price_z = _as_float(price_z, 0.0)
    price_z_thresh = _as_float(cfg.get("squeeze_price_z_thresh"), 1.0)
    price_move_score = 0.0
    if price_chg > 0:
        price_move_score = _ramp(price_chg, 0.5, 4.0) * _ramp(price_z, price_z_thresh, 2.0)
    if price_chg >= 1.0 and price_z >= price_z_thresh:
        reasons.append("HIGH_PRICE_MOMENTUM")

    # 5) Call 偏度：名义/成交量/C-P 多维联合
    notional_bias = _as_float(_coalesce_value(features, ("notional_bias", "flow_bias"), 0.0), 0.0)
    volume_bias = _as_float(_coalesce_value(features, ("volume_bias",), 0.0), 0.0)
    cp_ratio = _as_float(_coalesce_value(features, ("cp_ratio",), 1.0), 1.0)
    call_bias_score = (
        _ramp(notional_bias, 0.05, 0.6)
        + _ramp(volume_bias, 0.05, 0.6)
        + _ramp(cp_ratio, 1.0, 2.2)
    ) / 3.0
    if call_bias_score >= 0.55:
        reasons.append("HIGH_CALL_BIAS")

    # 6) 结构纯度：SingleLeg 高、MultiLeg/Contingent 低
    structure_purity = _coalesce_value(features, ("structure_purity",), None)
    if structure_purity is None:
        single_leg = _as_float(_coalesce_value(features, ("single_leg_pct", "SingleLegPct"), 0.0), 0.0)
        multi_leg = _as_float(_coalesce_value(features, ("multi_leg_pct", "MultiLegPct"), 0.0), 0.0)
        contingent = _as_float(_coalesce_value(features, ("contingent_pct", "ContingentPct"), 0.0), 0.0)
        structure_purity = (single_leg - multi_leg - 0.5 * contingent) / 100.0
    structure_purity = max(-1.0, min(1.0, _as_float(structure_purity, 0.0)))
    structure_score = _ramp(structure_purity, 0.1, 0.9)
    if structure_purity >= 0.5:
        reasons.append("CLEAN_SINGLE_LEG_STRUCTURE")

    # 加权汇总
    score = (
        0.23 * iv_discount_score
        + 0.20 * oi_score
        + 0.17 * rel_vol_score
        + 0.15 * price_move_score
        + 0.15 * call_bias_score
        + 0.10 * structure_score
    )
    score = max(0.0, min(1.0, float(score)))

    # reasons 去重保序
    deduped_reasons: List[str] = []
    seen = set()
    for code in reasons:
        if code not in seen:
            deduped_reasons.append(code)
            seen.add(code)

    return score, deduped_reasons


def detect_squeeze_potential(rec: Dict[str, Any], cfg: Dict[str, Any]) -> bool:
    """
    检测 Gamma Squeeze 潜力
    
    条件:
    - 期权便宜: IV30/HV20 < 0.95
    - 仓位拥挤: OI_PctRank > 70
    - 价格启动: PriceChgPct > 1.5%
    - 显著放量: RelVolTo90D > 1.2
    """
    score, _ = compute_squeeze_score(rec, cfg)
    trigger = _as_float((cfg or {}).get("squeeze_score_trigger"), 0.70)
    return bool(score >= trigger)


def compute_active_open_ratio(rec: Dict[str, Any]) -> float:
    """
    🟩 v2.3.2 新增: 计算主动开仓比 (ActiveOpenRatio)
    ✨ NEW: 优雅处理缺失的 ΔOI 数据
    
    ActiveOpenRatio = ΔOI_1D / TotalVolume
    
    TotalVolume = CallVolume + PutVolume (若 Volume 字段不存在)
    
    判断规则:
    - ≥ 0.05 → 新建仓信号
    - ≤ -0.05 → 平仓信号
    
    Returns:
        ActiveOpenRatio 值，如果 ΔOI 不存在返回 0.0
    """
    # ✨ NEW: 优先检查 ΔOI 是否存在
    delta_oi = rec.get("ΔOI_1D") or rec.get("DeltaOI_1D")
    
    # ✨ 如果 ΔOI 不存在或为 None，返回 0.0（而非报错）
    if delta_oi is None:
        return 0.0
    
    # 优先使用 Volume 字段，否则用 CallVolume + PutVolume
    volume = rec.get("Volume")
    if volume is None or volume == 0:
        call_vol = rec.get("CallVolume", 0) or 0
        put_vol = rec.get("PutVolume", 0) or 0
        volume = call_vol + put_vol
    
    if volume == 0:
        volume = 1  # 防止除零
    
    try:
        delta_oi = float(delta_oi)
        volume = float(volume)
    except:
        return 0.0
    
    return safe_div(delta_oi, volume, 0.0)


def compute_term_structure_ratios(rec: Dict[str, Any]) -> Dict[str, float]:
    """
    计算期限结构比率（统一实现，兼容旧键名）。
    """
    return _compute_term_structure_ratios_shared(rec)


def compute_term_structure_adjustment(rec: Dict[str, Any], cfg: Dict[str, Any]) -> float:
    """
    期限结构对波动评分的修正（统一实现）。
    """
    ratios = compute_term_structure_ratios(rec)
    if not ratios:
        return 0.0
    label = _classify_term_structure_label_shared(ratios, cfg)
    return _compute_term_structure_adjustment_shared(label, ratios, cfg)


def compute_term_structure(rec: Dict[str, Any]) -> tuple:
    """
    计算期限结构 (Term Structure)
    
    Returns:
        (ratio_value, ratio_string): 数值和描述字符串
    """
    ratios = compute_term_structure_ratios(rec)
    ratio = ratios.get("30_90", ratios.get("iv30_iv90_ratio"))
    if ratio is None:
        return (None, "N/A")

    label_info = _classify_term_structure_label_shared(ratios, {})
    label = label_info.get("label", "N/A")
    ratio_str = f"{ratio:.2f}"

    parts = [label, ratio_str]
    if "7_30" in ratios:
        parts.append(f"7/30 {ratios['7_30']:.2f}")
    if "30_60" in ratios:
        parts.append(f"30/60 {ratios['30_60']:.2f}")
    if "60_90" in ratios:
        parts.append(f"60/90 {ratios['60_90']:.2f}")
    return (ratio, " | ".join(parts))


def parse_earnings_date(s: Optional[str]) -> Optional[date]:
    """
    解析财报日期字符串
    
    支持格式:
    - "22-Oct-2025 BMO"
    - "19-Nov-2025 AMC"
    - "22 Oct 2025"
    """
    if not s or not isinstance(s, str):
        return None
    t = s.strip()
    parts = t.split()
    if len(parts) >= 2 and parts[-1] in ("AMC", "BMO"):
        t = " ".join(parts[:-1])
    t = t.replace("  ", " ")
    for fmt in ("%d-%b-%Y", "%d %b %Y", "%d-%b-%y", "%d %b %y"):
        try:
            return datetime.strptime(t, fmt).date()
        except:
            continue
    return None


def days_until(d: Optional[date], as_of: Optional[date] = None) -> Optional[int]:
    """计算距离目标日期的天数"""
    if d is None:
        return None
    as_of = as_of or date.today()
    return (d - as_of).days
