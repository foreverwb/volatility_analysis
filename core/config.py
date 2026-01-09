"""
配置常量和默认阈值 - v2.3.2 增强版
新增可配置的修正系数
"""

# 全局默认阈值配置
DEFAULT_CFG = {
    # ========== 基础配置 ==========
    
    # 财报窗口
    "earnings_window_days": 14,
    
    # 流动性阈值
    "abs_volume_min": 20000,
    "liq_tradecount_min": 20000,
    
    # 恐慌环境检测
    "fear_ivrank_min": 75,
    "fear_ivrv_ratio_min": 1.30,
    "fear_regime_max": 1.05,
    
    # 波动率便宜/昂贵阈值
    "iv_longcheap_rank": 30,
    "iv_longcheap_ratio": 0.95,
    "iv_shortrich_rank": 70,
    "iv_shortrich_ratio": 1.15,
    
    # IV 变动阈值
    "iv_pop_up": 10.0,
    "iv_pop_down": -10.0,

    # 期限结构调整权重
    "term_short_weight": 0.35,
    "term_mid_weight": 0.25,
    "term_long_weight": 0.15,
    "term_adjust_cap": 0.6,
    
    # Regime 阈值
    "regime_hot": 1.20,
    "regime_calm": 0.80,
    
    # 相对成交量阈值
    "relvol_hot": 1.20,
    "relvol_cold": 0.80,
    
    # Call/Put 比率阈值 (个股)
    "callput_ratio_bull": 1.30,
    "callput_ratio_bear": 0.77,
    
    # Put% 阈值 (个股)
    "putpct_bear": 55.0,
    "putpct_bull": 45.0,
    
    # 交易结构阈值
    "singleleg_high": 80.0,
    "multileg_high": 25.0,
    "contingent_high": 2.0,
    
    # 流动性 OI Rank 阈值
    "liq_high_oi_rank": 60.0,
    "liq_med_oi_rank": 40.0,
    
    # 惩罚阈值
    "penalty_extreme_chg": 20.0,
    "penalty_vol_pct_thresh": 0.40,
    
    # ========== 🟩 v2.3.2 新增配置 ==========
    
    # ActiveOpenRatio 阈值
    "active_open_ratio_bull": 0.05,
    "active_open_ratio_bear": -0.05,
    
    # 🔧 NEW: ActiveOpenRatio 修正强度系数 β
    "active_open_ratio_beta": 0.5,  # 控制 AOR 对方向分数的影响强度
    
    # 跨期一致性配置
    "consistency_strong": 0.6,      # 一致性阈值
    "consistency_days": 5,           # 计算天数
    
    # 🔧 NEW: 跨期一致性修正系数
    "consistency_weight": 0.3,       # 原为硬编码 0.3，现可配置
    
    # 结构置信度修正阈值
    "multileg_conf_thresh": 40.0,
    "singleleg_conf_thresh": 70.0,
    "contingent_conf_thresh": 10.0,
}

# 指数类标的
INDEX_TICKERS = ["SPY", "QQQ", "IWM", "DIA"]


def get_dynamic_thresholds(symbol: str, base_cfg: dict) -> dict:
    """
    根据标的类型(指数/个股)动态调整阈值
    
    Args:
        symbol: 标的代码
        base_cfg: 基础配置
        
    Returns:
        调整后的配置
    """
    cfg = base_cfg.copy()
    if symbol in INDEX_TICKERS:
        # 指数通常 Put 更多，所以提高"看空"的门槛
        cfg["putpct_bear"] = 65.0
        cfg["putpct_bull"] = 50.0
        cfg["callput_ratio_bull"] = 1.0
    return cfg


# 🔧 NEW: 配置验证函数
def validate_config(cfg: dict) -> bool:
    """
    验证配置参数的合理性
    
    Returns:
        True if valid, raises ValueError if invalid
    """
    # 检查关键参数范围
    if not (0 < cfg.get("active_open_ratio_beta", 0.5) <= 2.0):
        raise ValueError("active_open_ratio_beta must be in (0, 2.0]")
    
    if not (0 < cfg.get("consistency_weight", 0.3) <= 1.0):
        raise ValueError("consistency_weight must be in (0, 1.0]")
    
    if not (1 <= cfg.get("consistency_days", 5) <= 30):
        raise ValueError("consistency_days must be in [1, 30]")
    
    return True
