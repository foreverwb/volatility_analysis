"""
核心指标计算模块
v2.3.2 - 新增 ActiveOpenRatio, Term Structure 等
✨ NEW: 优雅处理缺失的 ΔOI 数据
"""
import math
from datetime import datetime, date
from typing import Any, Dict, Optional, Set


def safe_div(a: float, b: float, default: float = 0.0) -> float:
    """安全除法"""
    try:
        return a / b if b != 0 else default
    except:
        return default


def _mark_missing(missing_features: Optional[Set[str]], *feature_names: str) -> None:
    if missing_features is None:
        return
    for feature_name in feature_names:
        if feature_name:
            missing_features.add(feature_name)


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


def compute_ivrv(rec: Dict[str, Any], missing_features: Optional[Set[str]] = None) -> Optional[float]:
    """计算 IVRV (log): ln(IV30 / HV20)"""
    iv30 = rec.get("IV30")
    hv20 = rec.get("HV20")
    if not isinstance(iv30, (int, float)) or not isinstance(hv20, (int, float)):
        if not isinstance(iv30, (int, float)):
            _mark_missing(missing_features, "IV30")
        if not isinstance(hv20, (int, float)):
            _mark_missing(missing_features, "HV20")
        return None
    if iv30 <= 0 or hv20 <= 0:
        return None
    return math.log(iv30 / hv20)


def compute_iv_ratio(rec: Dict[str, Any], missing_features: Optional[Set[str]] = None) -> Optional[float]:
    """计算 IV/HV 比率: IV30 / HV20"""
    iv30 = rec.get("IV30")
    hv20 = rec.get("HV20")
    if not isinstance(iv30, (int, float)):
        _mark_missing(missing_features, "IV30")
    if not isinstance(hv20, (int, float)) or (isinstance(hv20, (int, float)) and hv20 <= 0):
        _mark_missing(missing_features, "HV20")
    if not isinstance(iv30, (int, float)) or not isinstance(hv20, (int, float)) or hv20 <= 0:
        return None
    return float(iv30) / float(hv20)


def compute_regime_ratio(rec: Dict[str, Any], missing_features: Optional[Set[str]] = None) -> Optional[float]:
    """计算 Regime 比率: HV20 / HV1Y"""
    hv20 = rec.get("HV20")
    hv1y = rec.get("HV1Y")
    if not isinstance(hv20, (int, float)):
        _mark_missing(missing_features, "HV20")
    if not isinstance(hv1y, (int, float)) or (isinstance(hv1y, (int, float)) and hv1y <= 0):
        _mark_missing(missing_features, "HV1Y")
    if not isinstance(hv20, (int, float)) or not isinstance(hv1y, (int, float)) or hv1y <= 0:
        return None
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


def detect_squeeze_potential(rec: Dict[str, Any], cfg: Dict[str, Any]) -> bool:
    """
    检测 Gamma Squeeze 潜力
    
    条件:
    - 期权便宜: IV30/HV20 < 0.95
    - 仓位拥挤: OI_PctRank > 70
    - 价格启动: PriceChgPct > 1.5%
    - 显著放量: RelVolTo90D > 1.2
    """
    iv_ratio = compute_iv_ratio(rec)
    oi_rank = rec.get("OI_PctRank", 0.0) or 0.0
    price_chg = rec.get("PriceChgPct", 0.0) or 0.0
    rel_vol = rec.get("RelVolTo90D", 0.0) or 0.0
    
    try:
        price_chg = float(price_chg)
        rel_vol = float(rel_vol)
        oi_rank = float(oi_rank)
    except:
        return False
    
    if (isinstance(iv_ratio, (int, float)) and
        iv_ratio < 0.95 and
        oi_rank > 70.0 and
        price_chg > 1.5 and
        rel_vol > 1.2):
        return True
    return False


def compute_active_open_ratio(rec: Dict[str, Any], missing_features: Optional[Set[str]] = None) -> Optional[float]:
    """
    🟩 v2.3.2 新增: 计算主动开仓比 (ActiveOpenRatio)
    ✨ NEW: 优雅处理缺失的 ΔOI 数据
    
    ActiveOpenRatio = ΔOI_1D / TotalVolume
    
    TotalVolume = CallVolume + PutVolume (若 Volume 字段不存在)
    
    判断规则:
    - ≥ 0.05 → 新建仓信号
    - ≤ -0.05 → 平仓信号
    
    Returns:
        ActiveOpenRatio 值，如果 ΔOI 不存在返回 None
    """
    # ✨ NEW: 优先检查 ΔOI 是否存在
    delta_oi = rec.get("ΔOI_1D")
    if delta_oi is None and "DeltaOI_1D" in rec:
        delta_oi = rec.get("DeltaOI_1D")
    
    # ✨ 如果 ΔOI 不存在或为 None，返回 None（缺失状态）
    if delta_oi is None:
        return None
    
    # 优先使用 Volume 字段，否则用 CallVolume + PutVolume
    volume = rec.get("Volume")
    if volume is None or volume == 0:
        call_vol = rec.get("CallVolume", 0) or 0
        put_vol = rec.get("PutVolume", 0) or 0
        volume = call_vol + put_vol
    
    if volume == 0:
        return None
    
    try:
        delta_oi = float(delta_oi)
        volume = float(volume)
    except:
        return None
    
    return safe_div(delta_oi, volume, 0.0)


def compute_term_structure_ratios(rec: Dict[str, Any]) -> Dict[str, float]:
    """
    计算期限结构比率
    """
    iv7 = rec.get("IV7")
    iv30 = rec.get("IV30")
    iv60 = rec.get("IV60")
    iv90 = rec.get("IV90")
    ratios = {}
    if isinstance(iv7, (int, float)) and isinstance(iv30, (int, float)) and iv30 > 0:
        ratios["7_30"] = iv7 / iv30
    if isinstance(iv30, (int, float)) and isinstance(iv60, (int, float)) and iv60 > 0:
        ratios["30_60"] = iv30 / iv60
    if isinstance(iv60, (int, float)) and isinstance(iv90, (int, float)) and iv90 > 0:
        ratios["60_90"] = iv60 / iv90
    if isinstance(iv30, (int, float)) and isinstance(iv90, (int, float)) and iv90 > 0:
        ratios["30_90"] = iv30 / iv90
    return ratios


def compute_term_structure_adjustment(rec: Dict[str, Any], cfg: Dict[str, Any]) -> float:
    """
    期限结构对波动评分的修正
    """
    ratios = compute_term_structure_ratios(rec)
    if not ratios:
        return 0.0

    short_weight = float(cfg.get("term_short_weight", 0.35))
    mid_weight = float(cfg.get("term_mid_weight", 0.25))
    long_weight = float(cfg.get("term_long_weight", 0.15))
    cap = float(cfg.get("term_adjust_cap", 0.6))

    adj = 0.0
    if "7_30" in ratios:
        adj -= short_weight * (ratios["7_30"] - 1.0)
    if "30_60" in ratios:
        adj -= mid_weight * (ratios["30_60"] - 1.0)
    if "60_90" in ratios:
        adj -= long_weight * (ratios["60_90"] - 1.0)
    if "30_90" in ratios and "60_90" not in ratios:
        adj -= long_weight * (ratios["30_90"] - 1.0)

    return max(-cap, min(cap, adj))


def compute_term_structure(rec: Dict[str, Any]) -> tuple:
    """
    计算期限结构 (Term Structure)
    
    Returns:
        (ratio_value, ratio_string): 数值和描述字符串
    """
    ratios = compute_term_structure_ratios(rec)
    ratio = ratios.get("30_90")
    if ratio is None:
        return (None, "N/A")

    label = _classify_term_structure(ratios)
    ratio_str = f"{ratio:.2f}"

    parts = [label, ratio_str]
    if "7_30" in ratios:
        parts.append(f"7/30 {ratios['7_30']:.2f}")
    if "30_60" in ratios:
        parts.append(f"30/60 {ratios['30_60']:.2f}")
    if "60_90" in ratios:
        parts.append(f"60/90 {ratios['60_90']:.2f}")
    return (ratio, " | ".join(parts))


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
