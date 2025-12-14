"""
期权策略量化分析系统 v2.3.3 核心模块
Dynamic Parameter Adaptation Layer
"""
from .config import DEFAULT_CFG, INDEX_TICKERS, get_dynamic_thresholds, validate_config
from .cleaning import clean_record, normalize_dataset
from .metrics import (
    compute_volume_bias, compute_notional_bias, compute_callput_ratio,
    compute_ivrv, compute_iv_ratio, compute_regime_ratio,
    compute_spot_vol_correlation_score, detect_squeeze_potential,
    compute_active_open_ratio, compute_term_structure,
    parse_earnings_date, days_until
)
from .scoring import compute_direction_score, compute_vol_score
from .confidence import (
    map_liquidity, map_confidence, compute_structure_factor,
    compute_intertemporal_consistency, penalize_extreme_move_low_vol
)
from .strategy import (
    map_direction_pref, map_vol_pref, combine_quadrant, get_strategy_info
)
from .analyzer import calculate_analysis

# v2.3.3 新增模块
from .dynamic_params import (
    compute_z_score, compute_beta_t, compute_lambda_t, compute_alpha_t,
    apply_ema_smoothing, compute_all_dynamic_params, validate_dynamic_params
)
from .rolling_cache import (
    RollingCache, get_global_cache, update_cache_with_record
)
from .market_data import (
    get_current_vix, get_vix_history, get_vix_with_fallback,
    validate_vix, get_vix_info, clear_vix_cache
)

__all__ = [
    # 配置
    'DEFAULT_CFG', 'INDEX_TICKERS', 'get_dynamic_thresholds', 'validate_config',
    
    # 数据清洗
    'clean_record', 'normalize_dataset',
    
    # 指标计算
    'compute_volume_bias', 'compute_notional_bias', 'compute_callput_ratio',
    'compute_ivrv', 'compute_iv_ratio', 'compute_regime_ratio',
    'compute_spot_vol_correlation_score', 'detect_squeeze_potential',
    'compute_active_open_ratio', 'compute_term_structure',
    'parse_earnings_date', 'days_until',
    
    # 评分
    'compute_direction_score', 'compute_vol_score',
    
    # 置信度
    'map_liquidity', 'map_confidence', 'compute_structure_factor',
    'compute_intertemporal_consistency', 'penalize_extreme_move_low_vol',
    
    # 策略
    'map_direction_pref', 'map_vol_pref', 'combine_quadrant', 'get_strategy_info',
    
    # 分析器
    'calculate_analysis',
    
    # v2.3.3: 动态参数
    'compute_z_score', 'compute_beta_t', 'compute_lambda_t', 'compute_alpha_t',
    'apply_ema_smoothing', 'compute_all_dynamic_params', 'validate_dynamic_params',
    
    # v2.3.3: 缓存管理
    'RollingCache', 'get_global_cache', 'update_cache_with_record',
    
    # v2.3.3: 市场数据
    'get_current_vix', 'get_vix_history', 'get_vix_with_fallback',
    'validate_vix', 'get_vix_info', 'clear_vix_cache',
]

__version__ = '2.3.3'