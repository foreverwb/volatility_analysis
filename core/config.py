"""
配置常量和默认阈值 - v2.5.0
✨ NEW: 期限结构识别配置
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
    
    # ========== ActiveOpenRatio 配置 ==========
    "active_open_ratio_bull": 0.05,
    "active_open_ratio_bear": -0.05,
    "active_open_ratio_beta": 0.5,
    
    # ========== 跨期一致性配置 ==========
    "consistency_strong": 0.6,
    "consistency_days": 5,
    "consistency_weight": 0.3,
    
    # ========== 结构置信度配置 ==========
    "multileg_conf_thresh": 40.0,
    "singleleg_conf_thresh": 70.0,
    "contingent_conf_thresh": 10.0,
    
    # ========== ✨ NEW: 期限结构配置 ==========
    
    # 是否启用期限结构分析
    "enable_term_structure": True,
    
    # 是否让期限结构影响 Vol Score
    "enable_term_structure_adjustment": True,
    
    # 期限结构斜率判断阈值（百分点）
    # 例如：threshold=2.0 表示斜率超过 ±2% 时认为有显著变化
    "term_structure_threshold": 2.0,
    
    # 期限结构权重（对 Vol Score 的影响强度）
    # 范围: 0.0 - 1.0
    # 0.0 = 不影响
    # 1.0 = 完全按期限结构调整
    "term_structure_weight": 0.8,
    
    # ========== 期限结构形态权重配置 ==========
    # 用于 calculate_term_structure_score() 函数
    # 可根据实际交易经验调整
    
    # 短期倒挂 - 买波信号
    "ts_short_backwardation_score": 0.6,
    
    # 短期低位 - 强买波信号
    "ts_short_undervalued_score": 0.8,
    
    # 正常陡峭 - 卖波信号
    "ts_normal_upward_score": -0.5,
    
    # 远期过高 - 卖远期
    "ts_long_steep_score": -0.4,
    
    # 全面倒挂 - 观望
    "ts_full_backwardation_score": 0.0,
    
    # 中期突起 - 避开中期
    "ts_mid_hump_score": -0.2,
    
    # 平坦/混合 - 中性
    "ts_flat_or_mixed_score": 0.0,
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
        
        # ✨ NEW: 指数期限结构通常更平缓
        cfg["term_structure_threshold"] = 1.5  # 降低阈值
    return cfg


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
    
    # ✨ NEW: 期限结构参数验证
    if not (0.5 <= cfg.get("term_structure_threshold", 2.0) <= 10.0):
        raise ValueError("term_structure_threshold must be in [0.5, 10.0]")
    
    if not (0.0 <= cfg.get("term_structure_weight", 0.8) <= 1.0):
        raise ValueError("term_structure_weight must be in [0.0, 1.0]")
    
    return True


# ========== ✨ NEW: 期限结构帮助文档 ==========

TERM_STRUCTURE_HELP = """
期限结构识别功能使用说明
=======================

## 配置参数说明

1. enable_term_structure (bool)
   - 是否启用期限结构分析
   - 默认: True
   - 建议: 保持开启

2. enable_term_structure_adjustment (bool)
   - 是否让期限结构影响 Vol Score
   - 默认: True
   - 建议: 开启以获得更准确的波动评分

3. term_structure_threshold (float)
   - 斜率判断阈值（百分点）
   - 默认: 2.0
   - 范围: 0.5 - 10.0
   - 说明: 
     * 2.0 = 中等敏感度（推荐）
     * 1.0 = 高敏感度（捕捉更多形态）
     * 3.0 = 低敏感度（只识别明显形态）

4. term_structure_weight (float)
   - 期限结构对 Vol Score 的影响强度
   - 默认: 0.8
   - 范围: 0.0 - 1.0
   - 说明:
     * 0.0 = 不影响 Vol Score
     * 0.5 = 中等影响
     * 1.0 = 完全按期限结构调整

## 形态权重配置

各形态的得分权重可在配置中调整：
- ts_short_backwardation_score: 短期倒挂（默认 +0.6）
- ts_short_undervalued_score: 短期低位（默认 +0.8）
- ts_normal_upward_score: 正常陡峭（默认 -0.5）
- ts_long_steep_score: 远期过高（默认 -0.4）
- ts_full_backwardation_score: 全面倒挂（默认 0.0）
- ts_mid_hump_score: 中期突起（默认 -0.2）
- ts_flat_or_mixed_score: 平坦/混合（默认 0.0）

## 调优建议

1. 保守交易者:
   - term_structure_threshold = 3.0（降低噪音）
   - term_structure_weight = 0.5（减少影响）

2. 激进交易者:
   - term_structure_threshold = 1.5（捕捉更多机会）
   - term_structure_weight = 1.0（完全依赖期限结构）

3. 指数交易:
   - 系统已自动降低 threshold 到 1.5
   - 因为指数期限结构通常更平缓

4. 个股交易:
   - 使用默认配置即可
   - 个股期限结构波动更大
"""