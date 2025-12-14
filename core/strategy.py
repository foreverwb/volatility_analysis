"""
策略映射模块
"""
from typing import Any, Dict


def map_direction_pref(score: float) -> str:
    """方向偏好映射"""
    return "偏多" if score >= 1.0 else "偏空" if score <= -1.0 else "中性"


def map_vol_pref(score: float, cfg: Dict[str, Any]) -> str:
    """波动偏好映射"""
    th = float(cfg.get("penalty_vol_pct_thresh", 0.40))
    return "买波" if score >= th else "卖波" if score <= -th else "中性"


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
        prefix = "🔥 【Gamma Squeeze 预警】强烈建议买入看涨期权 (Long Call) 利用爆发。 "
        info["策略"] = prefix + info["策略"]
        info["风险"] += "; 注意：挤压行情可能快速反转，需设移动止盈"
    
    if liquidity == "低":
        info["风险"] += ";⚠️ 流动性低,用少腿、靠近ATM、限价单与缩小仓位"
    
    return info
