from flask import Flask, render_template, request, jsonify, send_from_directory
import json
import os
import math
import re
from datetime import datetime, date
from typing import Any, Dict, List, Optional

app = Flask(__name__)

DATA_FILE = 'analysis_records.json'

# =========================
# 全局默认阈值配置
# =========================
DEFAULT_CFG = {
    "earnings_window_days": 14,
    "abs_volume_min": 20000,
    "liq_tradecount_min": 20000,
    "fear_ivrank_min": 75,
    "fear_ivrv_ratio_min": 1.30,
    "fear_regime_max": 1.05,
    "iv_longcheap_rank": 30,
    "iv_longcheap_ratio": 0.95,
    "iv_shortrich_rank": 70,
    "iv_shortrich_ratio": 1.15,
    "iv_pop_up": 10.0,
    "iv_pop_down": -10.0,
    "regime_hot": 1.20,
    "regime_calm": 0.80,
    "relvol_hot": 1.20,
    "relvol_cold": 0.80,
    "callput_ratio_bull": 1.30,
    "callput_ratio_bear": 0.77,
    "putpct_bear": 55.0,
    "putpct_bull": 45.0,
    "singleleg_high": 80.0,
    "multileg_high": 25.0,
    "contingent_high": 2.0,
    "liq_high_oi_rank": 60.0,
    "liq_med_oi_rank": 40.0,
    "penalty_extreme_chg": 20.0,
    "penalty_vol_pct_thresh": 0.40
}

INDEX_TICKERS = ["SPY", "QQQ", "IWM", "DIA"]

# =========================
# 数据清洗函数
# =========================
def clean_percent_string(s: Any) -> Optional[float]:
    """清洗百分比字符串: "+2.7%" -> 2.7"""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().replace('%', '').replace('+', '')
    try:
        return float(s)
    except:
        return None

def clean_number_string(s: Any) -> Optional[float]:
    """清洗数字字符串: "628,528" -> 628528"""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().replace(',', '')
    try:
        return float(s)
    except:
        return None

def clean_notional_string(s: Any) -> Optional[float]:
    """清洗名义金额: "261.75 M" -> 261750000"""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().replace(',', '')
    match = re.match(r'([0-9.]+)\s*([KMBkmb]?)', s)
    if not match:
        try:
            return float(s)
        except:
            return None
    value = float(match.group(1))
    unit = match.group(2).upper()
    multiplier = {'K': 1_000, 'M': 1_000_000, 'B': 1_000_000_000}.get(unit, 1)
    return value * multiplier

def clean_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    """清洗单条记录"""
    cleaned = dict(rec)
    # [关键修复] 加入 IV30ChgPct 确保能被正确转换为 float
    percent_fields = ['PriceChgPct', 'IV30ChgPct', 'IVR', 'IV_52W_P', 'OI_PctRank',
                      'PutPct', 'SingleLegPct', 'MultiLegPct', 'ContingentPct']
    for field in percent_fields:
        if field in cleaned:
            cleaned[field] = clean_percent_string(cleaned[field])
    
    number_fields = ['IV30', 'IV90', 'HV20', 'HV1Y', 'Volume', 'RelVolTo90D', 
                     'CallVolume', 'PutVolume', 'RelNotionalTo90D']
    for field in number_fields:
        if field in cleaned:
            cleaned[field] = clean_number_string(cleaned[field])
    
    notional_fields = ['CallNotional', 'PutNotional']
    for field in notional_fields:
        if field in cleaned:
            cleaned[field] = clean_notional_string(cleaned[field])
    
    return cleaned

# =========================
# 数据归一化
# =========================
def median(values: List[float]) -> float:
    vals = [v for v in values if v is not None and not math.isnan(v)]
    if not vals:
        return 0.0
    vals.sort()
    n = len(vals)
    return vals[n // 2] if n % 2 == 1 else 0.5 * (vals[n // 2 - 1] + vals[n // 2])

def detect_scale(records: List[Dict[str, Any]], key: str) -> str:
    vals = [abs(float(r.get(key, 0))) for r in records 
            if isinstance(r.get(key), (int, float))]
    med = median(vals)
    return "fraction" if 0 < med <= 1 else "percent"

def normalize_percent_value(value: Optional[float], expected: str) -> Optional[float]:
    if value is None:
        return None
    try:
        v = float(value)
        return v * 100.0 if expected == "fraction" else v
    except:
        return None

def normalize_dataset(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    pct_keys = ["PutPct", "SingleLegPct", "MultiLegPct", "ContingentPct",
                "IVR", "IV_52W_P", "OI_PctRank", "PriceChgPct", "IV30ChgPct"]
    scale_map = {k: detect_scale(records, k) for k in pct_keys}
    
    normed = []
    for r in records:
        r2 = dict(r)
        for k in pct_keys:
            r2[k] = normalize_percent_value(r2.get(k), scale_map[k])
        for cap_k in ["IVR", "IV_52W_P", "OI_PctRank"]:
            if isinstance(r2.get(cap_k), (int, float)):
                r2[cap_k] = max(0.0, min(100.0, float(r2[cap_k])))
        normed.append(r2)
    return normed

# =========================
# 辅助计算函数
# =========================
def safe_div(a: float, b: float, default: float = 0.0) -> float:
    try:
        return a / b if b != 0 else default
    except:
        return default

def compute_volume_bias(rec: Dict[str, Any]) -> float:
    cv = rec.get("CallVolume", 0) or 0
    pv = rec.get("PutVolume", 0) or 0
    return safe_div((cv - pv), (cv + pv), 0.0)

def compute_notional_bias(rec: Dict[str, Any]) -> float:
    cn = rec.get("CallNotional", 0) or 0.0
    pn = rec.get("PutNotional", 0) or 0.0
    return safe_div((cn - pn), (cn + pn), 0.0)

def compute_callput_ratio(rec: Dict[str, Any]) -> float:
    cn = rec.get("CallNotional", 0) or 0.0
    pn = rec.get("PutNotional", 0) or 0.0
    if cn > 0 and pn > 0:
        return safe_div(cn, pn, 1.0)
    cv = rec.get("CallVolume", 0) or 0
    pv = rec.get("PutVolume", 0) or 0
    return safe_div(cv, pv, 1.0)

def compute_ivrv(rec: Dict[str, Any]) -> float:
    iv30 = rec.get("IV30")
    hv20 = rec.get("HV20")
    if not isinstance(iv30, (int, float)) or not isinstance(hv20, (int, float)):
        return 0.0
    if iv30 <= 0 or hv20 <= 0:
        return 0.0
    return math.log(iv30 / hv20)

def compute_iv_ratio(rec: Dict[str, Any]) -> float:
    iv30 = rec.get("IV30")
    hv20 = rec.get("HV20")
    if not isinstance(iv30, (int, float)) or not isinstance(hv20, (int, float)) or hv20 <= 0:
        return 1.0
    return float(iv30) / float(hv20)

def compute_regime_ratio(rec: Dict[str, Any]) -> float:
    hv20 = rec.get("HV20")
    hv1y = rec.get("HV1Y")
    if not isinstance(hv20, (int, float)) or not isinstance(hv1y, (int, float)) or hv1y <= 0:
        return 1.0
    return float(hv20) / float(hv1y)

def parse_earnings_date(s: Optional[str]) -> Optional[date]:
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
    if d is None:
        return None
    as_of = as_of or date.today()
    return (d - as_of).days

# =========================
# 高级量化逻辑
# =========================
def get_dynamic_thresholds(symbol: str, base_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """根据标的类型(指数/个股)动态调整阈值"""
    cfg = base_cfg.copy()
    if symbol in INDEX_TICKERS:
        # 指数通常 Put 更多，所以提高“看空”的门槛
        cfg["putpct_bear"] = 65.0  
        cfg["putpct_bull"] = 50.0  
        cfg["callput_ratio_bull"] = 1.0 
    return cfg

def compute_spot_vol_correlation_score(rec: Dict[str, Any]) -> float:
    """计算价-波相关性分数"""
    price_chg = rec.get("PriceChgPct", 0.0) or 0.0
    iv_chg = rec.get("IV30ChgPct", 0.0) or 0.0
    
    # 确保是浮点数
    try:
        price_chg = float(price_chg)
        iv_chg = float(iv_chg)
    except:
        return 0.0

    # 场景 A: 逼空/动量 (价升波升) -> 强看多
    if price_chg > 0.5 and iv_chg > 2.0:
        return 0.4 
    # 场景 B: 恐慌抛售 (价跌波升) -> 强看空
    elif price_chg < -0.5 and iv_chg > 2.0:
        return -0.5
    # 场景 C: 磨涨 (价升波降) -> 稳健看多
    elif price_chg > 0 and iv_chg < -2.0:
        return 0.2
    return 0.0

def detect_squeeze_potential(rec: Dict[str, Any], cfg: Dict[str, Any]) -> bool:
    """检测 Gamma Squeeze 潜力"""
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
    
    # 条件：期权便宜 + 仓位拥挤 + 价格上涨 + 交易放量
    if (iv_ratio < 0.95 and 
        oi_rank > 70.0 and 
        price_chg > 1.5 and 
        rel_vol > 1.2):
        return True
    return False

# =========================
# 核心评分算法
# =========================
def compute_direction_score(rec: Dict[str, Any], cfg: Dict[str, Any]) -> float:
    """方向分数计算"""
    price_chg_pct = rec.get("PriceChgPct", 0.0) or 0.0
    rel_vol = rec.get("RelVolTo90D", 1.0) or 1.0
    vol_bias = compute_volume_bias(rec)
    notional_bias = compute_notional_bias(rec)
    cp_ratio = compute_callput_ratio(rec)
    put_pct = rec.get("PutPct", None)
    single_leg = rec.get("SingleLegPct", None)
    multi_leg = rec.get("MultiLegPct", None)
    contingent = rec.get("ContingentPct", None)
    
    # 价格项:tanh平滑
    price_term = 0.90 * math.tanh(float(price_chg_pct) / 1.75)
    
    # 名义与量偏度
    notional_term = 0.60 * notional_bias
    vol_bias_term = 0.35 * vol_bias
    
    # 放量微调
    relvol_term = 0.0
    if rel_vol >= cfg["relvol_hot"]:
        relvol_term = 0.18
    elif rel_vol <= cfg["relvol_cold"]:
        relvol_term = -0.05
    
    # Call/Put比率
    cpr_term = 0.0
    if cp_ratio >= cfg["callput_ratio_bull"]:
        cpr_term = 0.30
    elif cp_ratio <= cfg["callput_ratio_bear"]:
        cpr_term = -0.30
    
    # Put比例
    put_term = 0.0
    if isinstance(put_pct, (int, float)):
        if put_pct >= cfg["putpct_bear"]:
            put_term = -0.20
        elif put_pct <= cfg["putpct_bull"]:
            put_term = 0.20
        else:
            put_term = 0.20 * (50.0 - float(put_pct)) / 50.0
    
    score = price_term + notional_term + vol_bias_term + relvol_term + cpr_term + put_term
    
    # [新增] 加入价-波相关性得分
    score += compute_spot_vol_correlation_score(rec)
    
    # 结构加权
    amp = 1.0
    if isinstance(single_leg, (int, float)) and single_leg >= cfg["singleleg_high"]:
        amp *= 1.10
    if isinstance(multi_leg, (int, float)) and multi_leg >= cfg["multileg_high"]:
        amp *= 0.90
    if isinstance(contingent, (int, float)) and contingent >= cfg["contingent_high"]:
        amp *= 0.90
    
    return float(score * amp)

def compute_vol_score(rec: Dict[str, Any], cfg: Dict[str, Any], 
                     ignore_earnings: bool = False) -> float:
    """波动分数计算"""
    ivr = rec.get("IVR", None)
    ivrv = compute_ivrv(rec)
    iv_ratio = compute_iv_ratio(rec)
    iv30_chg = rec.get("IV30ChgPct", 0.0) or 0.0
    hv20 = rec.get("HV20", None)
    iv30 = rec.get("IV30", None)
    regime = compute_regime_ratio(rec)
    
    # IVR中心化
    ivr_center = 0.0
    if isinstance(ivr, (int, float)):
        ivr_center = (float(ivr) - 50.0) / 50.0
    
    # 卖波压力
    sell_pressure = 1.2 * ivr_center + 1.2 * ivrv
    
    # 当日IV变化
    ivchg_buy = 0.5 if iv30_chg >= cfg["iv_pop_up"] else 0.0
    ivchg_sell = 0.5 if iv30_chg <= cfg["iv_pop_down"] else 0.0
    
    # 折价项
    discount_term = 0.0
    if isinstance(hv20, (int, float)) and isinstance(iv30, (int, float)) and hv20 > 0:
        discount_term = max(0.0, (float(hv20) - float(iv30)) / float(hv20))
    
    # 长便宜/短昂贵
    longcheap = ((isinstance(ivr, (int, float)) and ivr <= cfg["iv_longcheap_rank"]) or 
                 (iv_ratio <= cfg["iv_longcheap_ratio"]))
    shortrich = ((isinstance(ivr, (int, float)) and ivr >= cfg["iv_shortrich_rank"]) or 
                 (iv_ratio >= cfg["iv_shortrich_ratio"]))
    cheap_boost = 0.6 if longcheap else 0.0
    rich_pressure = 0.6 if shortrich else 0.0
    
    # 财报事件
    earn_boost = 0.0
    if not ignore_earnings:
        earn_date = parse_earnings_date(rec.get("Earnings"))
        dte = days_until(earn_date)
        if dte is not None and dte > 0:
            if dte <= 2:
                earn_boost = 0.8
            elif dte <= 7:
                earn_boost = 0.4
            elif dte <= cfg["earnings_window_days"]:
                earn_boost = 0.2
    
    # 恐慌环境卖波倾向
    fear_sell = 0.0
    if (isinstance(ivr, (int, float)) and 
        ivr >= cfg["fear_ivrank_min"] and 
        iv_ratio >= cfg["fear_ivrv_ratio_min"] and 
        regime <= cfg["fear_regime_max"]):
        fear_sell = 0.4
    
    # Regime调整
    regime_term = 0.0
    if regime >= cfg["regime_hot"]:
        regime_term = 0.2
    elif regime <= cfg["regime_calm"]:
        regime_term = -0.2
    
    # 汇总
    buy_side = 0.8 * discount_term + ivchg_buy + cheap_boost + earn_boost + regime_term
    sell_side = sell_pressure + rich_pressure + ivchg_sell + fear_sell
    return float(buy_side - sell_side)

# =========================
# 流动性与置信度
# =========================
def map_liquidity(rec: Dict[str, Any], cfg: Dict[str, Any]) -> str:
    call_v = rec.get("CallVolume", 0) or 0
    put_v = rec.get("PutVolume", 0) or 0
    total_v = call_v + put_v
    rel_vol = rec.get("RelVolTo90D", 1.0) or 1.0
    call_n = rec.get("CallNotional", 0.0) or 0.0
    put_n = rec.get("PutNotional", 0.0) or 0.0
    total_n = call_n + put_n
    oi_rank = rec.get("OI_PctRank", None)
    trade_cnt = rec.get("TradeCount", None)
    
    high = (total_v >= max(1_000_000, cfg["abs_volume_min"] * 20) or
            total_n >= 300_000_000 or
            rel_vol >= cfg["relvol_hot"] or
            (isinstance(oi_rank, (int, float)) and oi_rank >= cfg["liq_high_oi_rank"]) or
            (isinstance(trade_cnt, (int, float)) and trade_cnt >= cfg["liq_tradecount_min"] * 5))
    if high:
        return "高"
    
    med = (total_v >= max(200_000, cfg["abs_volume_min"]) or
           total_n >= 100_000_000 or
           rel_vol >= 1.00 or
           (isinstance(oi_rank, (int, float)) and oi_rank >= cfg["liq_med_oi_rank"]) or
           (isinstance(trade_cnt, (int, float)) and trade_cnt >= cfg["liq_tradecount_min"]))
    return "中" if med else "低"

def map_confidence(dir_score: float, vol_score: float, liquidity: str,
                   rec: Dict[str, Any], cfg: Dict[str, Any]) -> str:
    """置信度计算"""
    strength = 0.0
    
    # 分数强度
    strength += 0.6 if abs(dir_score) >= 1.0 else 0.3 if abs(dir_score) >= 0.6 else 0.0
    v_abs = abs(vol_score)
    th = float(cfg.get("penalty_vol_pct_thresh", 0.40))
    strength += 0.6 if v_abs >= (th + 0.4) else 0.3 if v_abs >= th else 0.0
    
    # 流动性
    strength += 0.5 if liquidity == "高" else 0.25 if liquidity == "中" else 0.0
    
    # 恐慌环境扣分
    ivr = rec.get("IVR", None)
    iv_ratio = compute_iv_ratio(rec)
    regime = compute_regime_ratio(rec)
    if (isinstance(ivr, (int, float)) and 
        ivr >= cfg["fear_ivrank_min"] and 
        iv_ratio >= cfg["fear_ivrv_ratio_min"] and 
        regime <= cfg["fear_regime_max"]):
        strength -= 0.2
    
    # 缺失数据惩罚
    missing = sum(1 for k in ["PriceChgPct", "RelVolTo90D", "CallVolume", 
                              "PutVolume", "IV30", "HV20", "IVR"] 
                  if rec.get(k) is None)
    strength -= 0.1 * missing
    
    # 极端价动但缩量惩罚
    p = rec.get("PriceChgPct", None)
    rel_vol = rec.get("RelVolTo90D", 1.0) or 1.0
    if isinstance(p, (int, float)) and abs(p) >= cfg["penalty_extreme_chg"] and rel_vol <= cfg["relvol_cold"]:
        strength -= 0.3
    
    strength = max(0.0, strength)
    if strength >= 1.5:
        return "高"
    if strength >= 0.75:
        return "中"
    return "低"

def penalize_extreme_move_low_vol(rec: Dict[str, Any], cfg: Dict[str, Any]) -> bool:
    p = rec.get("PriceChgPct", None)
    rel_vol = rec.get("RelVolTo90D", None)
    ivchg = rec.get("IV30ChgPct", None)
    if not isinstance(p, (int, float)):
        return False
    cond_price = abs(float(p)) >= float(cfg["penalty_extreme_chg"])
    cond_vol = isinstance(rel_vol, (int, float)) and float(rel_vol) <= float(cfg["relvol_cold"])
    cond_iv = isinstance(ivchg, (int, float)) and float(ivchg) <= float(cfg["iv_pop_down"])
    return bool(cond_price and (cond_vol or cond_iv))

# =========================
# 偏好映射与策略
# =========================
def map_direction_pref(score: float) -> str:
    return "偏多" if score >= 1.0 else "偏空" if score <= -1.0 else "中性"

def map_vol_pref(score: float, cfg: Dict[str, Any]) -> str:
    th = float(cfg.get("penalty_vol_pct_thresh", 0.40))
    return "买波" if score >= th else "卖波" if score <= -th else "中性"

def combine_quadrant(dir_pref: str, vol_pref: str) -> str:
    if dir_pref == "中性" or vol_pref == "中性":
        return "中性/待观察"
    return f"{dir_pref}—{vol_pref}"

def get_strategy_info(quadrant: str, liquidity: str, is_squeeze: bool = False) -> Dict[str, str]:
    strategy_map = {
        "偏多—买波": {
            "策略": "看涨期权或看涨借记价差;临近事件做看涨日历/对角;IV低位或事件前可小仓位跨式",
            "风险": "事件落空或IV回落导致时间与IV双杀;注意期限结构与滑点"
        },
        "偏多—卖波": {
            "策略": "卖出看跌价差/现金担保卖PUT;偏多铁鹰或备兑开仓",
            "风险": "突发利空引发大跌;优先使用带翼结构限制尾部"
        },
        "偏空—买波": {
            "策略": "看跌期权或看跌借记价差;偏空日历/对角;IV低位时可小仓位跨式",
            "风险": "反弹或IV回落引发损耗;通过期限与delta控制theta"
        },
        "偏空—卖波": {
            "策略": "看涨价差/看涨备兑;偏空铁鹰",
            "风险": "逼空与踏空;选更远虚值并加翼防尾部"
        },
        "中性/待观察": {
            "策略": "观望或铁鹰/蝶式等中性策略",
            "风险": "方向不明确,建议等待更清晰信号"
        }
    }
    info = strategy_map.get(quadrant, strategy_map["中性/待观察"]).copy()
    
    if is_squeeze:
        prefix = "🔥 【Gamma Squeeze 预警】强烈建议买入看涨期权 (Long Call) 利用爆发。 "
        info["策略"] = prefix + info["策略"]
        info["风险"] += "; 注意：挤压行情可能快速反转，需设移动止盈"
    
    if liquidity == "低":
        info["风险"] += ";⚠️ 流动性低,用少腿、靠近ATM、限价单与缩小仓位"
    return info

# =========================
# 核心分析函数
# =========================
def calculate_analysis(data: Dict[str, Any], cfg: Dict[str, Any] = None, ignore_earnings: bool = False) -> Dict[str, Any]:
    if cfg is None:
        cfg = DEFAULT_CFG
    
    # 1. 数据清洗与归一化
    cleaned = clean_record(data)
    normed = normalize_dataset([cleaned])[0]
    symbol = normed.get('symbol', 'N/A')
    
    # 2. 获取生效配置 (Index vs Stock)
    effective_cfg = get_dynamic_thresholds(symbol, cfg)
    
    # 3. 计算高级指标
    spot_vol_score = compute_spot_vol_correlation_score(normed)
    is_squeeze = detect_squeeze_potential(normed, effective_cfg)
    
    # 计算期限结构
    iv30 = normed.get("IV30")
    iv90 = normed.get("IV90")
    term_structure_val = None
    term_structure_str = "N/A"
    if isinstance(iv30, (int, float)) and isinstance(iv90, (int, float)) and iv90 > 0:
        term_structure_val = iv30 / iv90
        term_structure_str = f"{term_structure_val:.2f}"
        if term_structure_val > 1.1:
            term_structure_str += " (倒挂/恐慌)"
        elif term_structure_val < 0.9:
            term_structure_str += " (陡峭/正常)"

    # 4. 计算基础评分 (注意：dir_score 内已包含 spot_vol_score)
    dir_score = compute_direction_score(normed, effective_cfg)
    vol_score = compute_vol_score(normed, effective_cfg, ignore_earnings=ignore_earnings)
    
    # 5. 偏好映射
    dir_pref = map_direction_pref(dir_score)
    vol_pref = map_vol_pref(vol_score, effective_cfg)
    quadrant = combine_quadrant(dir_pref, vol_pref)
    
    # 6. 流动性与置信度
    liquidity = map_liquidity(normed, effective_cfg)
    confidence = map_confidence(dir_score, vol_score, liquidity, normed, effective_cfg)
    
    # 7. 风险标记
    penal_flag = penalize_extreme_move_low_vol(normed, effective_cfg)
    
    # 8. 策略建议
    strategy_info = get_strategy_info(quadrant, liquidity, is_squeeze=is_squeeze)
    
    # 9. 派生指标计算
    hv20 = normed.get("HV20", 1)
    hv1y = normed.get("HV1Y", 1)
    ivrv_ratio = (iv30 / hv20) if (isinstance(iv30, (int, float)) and isinstance(hv20, (int, float)) and hv20 > 0) else 1.0
    ivrv_diff = (iv30 - hv20) if (isinstance(iv30, (int, float)) and isinstance(hv20, (int, float))) else 0.0
    ivrv_log = compute_ivrv(normed)
    regime_ratio = (hv20 / hv1y) if (isinstance(hv20, (int, float)) and isinstance(hv1y, (int, float)) and hv1y > 0) else 1.0
    vol_bias = compute_volume_bias(normed)
    notional_bias = compute_notional_bias(normed)
    cp_ratio = compute_callput_ratio(normed)
    days_to_earnings = days_until(parse_earnings_date(normed.get("Earnings")))
    
    # 10. 生成驱动因素列表 (修复缺失部分)
    direction_factors = []
    price_chg = normed.get("PriceChgPct", 0) or 0
    
    # 价格因素
    if price_chg >= 1.0:
        direction_factors.append(f"涨幅 {price_chg:.1f}%")
    elif price_chg <= -1.0:
        direction_factors.append(f"跌幅 {price_chg:.1f}%")
    else:
        direction_factors.append(f"涨跌幅 {price_chg:.1f}% (中性)")
    
    # 供需偏度因素
    direction_factors.append(f"量偏度 {vol_bias:.2f}")
    direction_factors.append(f"名义偏度 {notional_bias:.2f}")
    direction_factors.append(f"Call/Put比率 {cp_ratio:.2f}")
    direction_factors.append(f"相对量 {normed.get('RelVolTo90D', 1.0):.2f}x")
    
    # 价-波相关性说明
    if spot_vol_score >= 0.4:
         direction_factors.append("🔥 逼空/动量 (价升波升)")
    elif spot_vol_score <= -0.5:
         direction_factors.append("⚠️ 恐慌抛售 (价跌波升)")
    elif spot_vol_score >= 0.2:
         direction_factors.append("📈 磨涨 (价升波降)")

    vol_factors = []
    ivr = normed.get("IVR", 50)
    vol_factors.append(f"IVR {ivr:.1f}%")
    vol_factors.append(f"IVRV(log) {ivrv_log:.3f}")
    vol_factors.append(f"IVRV比率 {ivrv_ratio:.2f}")
    vol_factors.append(f"IV变动 {normed.get('IV30ChgPct', 0):.1f}%")
    vol_factors.append(f"Regime {regime_ratio:.2f}")
    
    if days_to_earnings is not None and 0 < days_to_earnings <= 14:
        vol_factors.append(f"📅 财报 {days_to_earnings}天内")
        
    # 期限结构说明
    if term_structure_val:
        if term_structure_val > 1.1:
            vol_factors.append("📉 期限倒挂 (恐慌)")
        elif term_structure_val < 0.9:
            vol_factors.append("📈 期限陡峭 (正常)")
    
    # 11. 构建返回结果
    result = {
        'symbol': symbol,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'quadrant': quadrant,
        'confidence': confidence,
        'liquidity': liquidity,
        'penalized_extreme_move_low_vol': penal_flag,
        
        # === 新增字段 ===
        'is_squeeze': is_squeeze,
        'is_index': symbol in INDEX_TICKERS,
        'spot_vol_corr_score': round(spot_vol_score, 2),
        'term_structure_ratio': term_structure_str,
        # ===============
        
        'direction_score': round(dir_score, 3),
        'vol_score': round(vol_score, 3),
        'direction_bias': dir_pref,
        'vol_bias': vol_pref,
        'direction_factors': direction_factors,
        'vol_factors': vol_factors,
        'derived_metrics': {
            'ivrv_ratio': round(ivrv_ratio, 3),
            'ivrv_diff': round(ivrv_diff, 2),
            'ivrv_log': round(ivrv_log, 3),
            'regime_ratio': round(regime_ratio, 3),
            'vol_bias': round(vol_bias, 3),
            'notional_bias': round(notional_bias, 3),
            'cp_ratio': round(cp_ratio, 3),
            'days_to_earnings': days_to_earnings
        },
        'strategy': strategy_info['策略'],
        'risk': strategy_info['风险'],
        'raw_data': data
    }
    
    return result

# =========================
# Flask 路由
# =========================
@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/analyze', methods=['POST'])
def analyze():
    try:
        ignore_earnings = request.args.get('ignore_earnings', 'false').lower() == 'true'
        records = request.json.get('records', [])
        
        if not isinstance(records, list):
            return jsonify({'error': '数据格式错误,需要是列表'}), 400
        
        if len(records) == 0:
            return jsonify({'error': '数据列表不能为空'}), 400
        
        results = []
        errors = []
        
        for i, record in enumerate(records):
            try:
                analysis = calculate_analysis(record, ignore_earnings=ignore_earnings)
                results.append(analysis)
            except Exception as e:
                error_msg = f"标的 {record.get('symbol', f'#{i+1}')} 分析失败: {str(e)}"
                errors.append(error_msg)
                print(f"错误: {error_msg}")
        
        if results:
            all_data = load_data()
            new_records_map = {}
            for r in results:
                date = r['timestamp'].split(' ')[0]
                symbol = r['symbol']
                key = (date, symbol)
                new_records_map[key] = r
            
            filtered_old_data = []
            for old_record in all_data:
                date = old_record.get('timestamp', '').split(' ')[0]
                symbol = old_record.get('symbol', '')
                key = (date, symbol)
                if key not in new_records_map:
                    filtered_old_data.append(old_record)
            
            all_data = filtered_old_data + results
            save_data(all_data)
        
        message = f'成功分析 {len(results)} 个标的'
        if errors:
            message += f',{len(errors)} 个失败'
        
        return jsonify({
            'message': message,
            'results': results,
            'errors': errors if errors else None
        }), 201
    
    except Exception as e:
        print(f"分析失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/records', methods=['GET'])
def get_records():
    try:
        data = load_data()
        if not isinstance(data, list):
            return jsonify([])
        
        date_filter = request.args.get('date')
        quadrant_filter = request.args.get('quadrant')
        confidence_filter = request.args.get('confidence')
        
        filtered_data = data
        
        if date_filter:
            filtered_data = [d for d in filtered_data if d.get('timestamp', '').startswith(date_filter)]
        
        if quadrant_filter and quadrant_filter != 'all':
            filtered_data = [d for d in filtered_data if d.get('quadrant') == quadrant_filter]
        
        if confidence_filter and confidence_filter != 'all':
            filtered_data = [d for d in filtered_data if d.get('confidence') == confidence_filter]
        
        return jsonify(filtered_data)
    
    except Exception as e:
        return jsonify([])

@app.route('/api/records/<timestamp>/<symbol>', methods=['DELETE'])
def delete_record(timestamp, symbol):
    try:
        data = load_data()
        original_length = len(data)
        data = [d for d in data if not (d['timestamp'] == timestamp and d['symbol'] == symbol)]
        if len(data) == original_length:
            return jsonify({'error': '未找到该记录'}), 404
        save_data(data)
        return jsonify({'message': '删除成功'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/records/date/<date>', methods=['DELETE'])
def delete_records_by_date(date):
    try:
        data = load_data()
        original_length = len(data)
        data = [d for d in data if not d.get('timestamp', '').startswith(date)]
        deleted_count = original_length - len(data)
        if deleted_count == 0:
            return jsonify({'error': '未找到该日期的记录'}), 404
        save_data(data)
        return jsonify({'message': f'成功删除 {deleted_count} 条记录'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/records/all', methods=['DELETE'])
def delete_all_records():
    try:
        save_data([])
        return jsonify({'message': '所有数据已删除'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/dates', methods=['GET'])
def get_dates():
    try:
        data = load_data()
        dates = sorted(set(d.get('timestamp', '')[:10] for d in data if d.get('timestamp')), reverse=True)
        return jsonify(dates)
    except Exception as e:
        return jsonify([]), 200

@app.route('/api/config', methods=['GET'])
def get_config():
    return jsonify(DEFAULT_CFG)

@app.route('/api/config', methods=['POST'])
def update_config():
    try:
        new_cfg = request.json
        DEFAULT_CFG.update(new_cfg)
        return jsonify({'message': '配置更新成功', 'config': DEFAULT_CFG})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("期权策略分析系统 - 整合优化版 v2.1")
    print("=" * 60)
    app.run(debug=True, host='0.0.0.0', port=8668)