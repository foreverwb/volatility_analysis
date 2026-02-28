"""
策略映射模块
"""
from typing import Any, Dict, Optional


def _safe_float(value: Any, default: float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def map_direction_pref(
    score: float,
    cfg: Optional[Dict[str, Any]] = None,
    use_neutral_buffer: bool = True,
) -> str:
    """
    方向偏好映射（Phase G）

    中性缓冲带：
    - abs(score) 接近阈值时保持“中性”，减少临界点跳变。
    """
    cfg = cfg or {}
    threshold = _safe_float(cfg.get("direction_pref_threshold", 1.0), 1.0)
    buffer_width = _safe_float(cfg.get("direction_pref_neutral_buffer", 0.15), 0.15) if use_neutral_buffer else 0.0
    upper = threshold + max(0.0, buffer_width)
    lower = -upper
    return "偏多" if score >= upper else "偏空" if score <= lower else "中性"


def map_vol_pref(
    score: float,
    cfg: Dict[str, Any],
    use_neutral_buffer: bool = True,
) -> str:
    """波动偏好映射（Phase G 中性缓冲带）"""
    th = float(cfg.get("vol_pref_threshold", cfg.get("penalty_vol_pct_thresh", 0.40)))
    if use_neutral_buffer:
        buffer_ratio = _safe_float(cfg.get("vol_pref_neutral_buffer_ratio", 0.25), 0.25)
        buffer_min = _safe_float(cfg.get("vol_pref_neutral_buffer_min", 0.05), 0.05)
        buffer_width = max(abs(th) * max(0.0, buffer_ratio), max(0.0, buffer_min))
    else:
        buffer_width = 0.0
    upper = th + buffer_width
    lower = -th - buffer_width
    return "买波" if score >= upper else "卖波" if score <= lower else "中性"


def combine_quadrant(dir_pref: str, vol_pref: str) -> str:
    """组合四象限"""
    if dir_pref == "中性" or vol_pref == "中性":
        return "中性/待观察"
    return f"{dir_pref}—{vol_pref}"


def get_strategy_info(quadrant: str, liquidity: str, is_squeeze: bool = False) -> Dict[str, str]:
    """
    获取策略建议
    
    Args:
        quadrant: 四象限定位
        liquidity: 流动性等级
        is_squeeze: 是否触发 Gamma Squeeze
        
    Returns:
        策略和风险建议
    """
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
        info["策略"] += "; 事件提示：出现 Gamma Squeeze 特征，优先执行仓位与止盈纪律"
        info["风险"] += "; 注意：挤压行情可能快速反转，避免把事件标签当作强制开仓指令"
    
    if liquidity == "低":
        info["风险"] += ";⚠️ 流动性低,用少腿、靠近ATM、限价单与缩小仓位"
    
    return info
