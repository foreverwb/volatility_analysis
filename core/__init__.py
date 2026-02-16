"""
期权策略量化分析系统 v2.3.3 核心模块
Dynamic Parameter Adaptation Layer
"""
from .config import DEFAULT_CFG, INDEX_TICKERS, get_dynamic_thresholds, get_vol_score_threshold, validate_config
from .cleaning import clean_record, normalize_dataset
from .validation import validate_record
from .metrics import (
    compute_volume_bias, compute_notional_bias, compute_callput_ratio,
    compute_ivrv, compute_iv_ratio, compute_regime_ratio,
    compute_spot_vol_correlation_score, detect_squeeze_potential,
    compute_squeeze_score,
    compute_active_open_ratio, compute_term_structure,
    parse_earnings_date, days_until
)
from .features import build_features
from .term_structure import (
    compute_term_structure_ratios as compute_term_structure_ratios_shared,
    classify_term_structure_label,
    compute_term_structure_adjustment as compute_term_structure_adjustment_shared,
    map_horizon_bias_to_dte_bias,
)
from .scoring import (
    compute_direction_components, compute_direction_score,
    compute_vol_components, compute_vol_score
)
from .confidence import (
    compute_liquidity_score, map_liquidity, map_confidence, compute_confidence_components, compute_structure_factor,
    compute_intertemporal_consistency, penalize_extreme_move_low_vol
)
from .strategy import (
    map_direction_pref, map_vol_pref, combine_quadrant, get_strategy_info, get_strategy_structures, apply_disabled_structures, load_strategy_map
)
from .posture import compute_posture_5d
from .trend import compute_linear_slope, map_slope_trend
from .guards import detect_fear_regime, evaluate_trade_permission, build_watchlist_guidance
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
from .oi_fetcher import (
    fetch_total_oi, get_oi_with_delta, batch_fetch_oi,
    get_oi_info, clear_oi_cache
)
__all__ = [
    # 配置
    'DEFAULT_CFG', 'INDEX_TICKERS', 'get_dynamic_thresholds', 'get_vol_score_threshold', 'validate_config',
    
    # 数据清洗
    'clean_record', 'normalize_dataset', 'validate_record',
    
    # 指标计算
    'compute_volume_bias', 'compute_notional_bias', 'compute_callput_ratio',
    'compute_ivrv', 'compute_iv_ratio', 'compute_regime_ratio',
    'compute_spot_vol_correlation_score', 'detect_squeeze_potential',
    'compute_squeeze_score',
    'compute_active_open_ratio', 'compute_term_structure',
    'parse_earnings_date', 'days_until',
    'build_features',
    'compute_term_structure_ratios_shared', 'classify_term_structure_label', 'compute_term_structure_adjustment_shared', 'map_horizon_bias_to_dte_bias',
    
    # 评分
    'compute_direction_components', 'compute_direction_score',
    'compute_vol_components', 'compute_vol_score',
    
    # 置信度
    'compute_liquidity_score', 'map_liquidity', 'map_confidence', 'compute_confidence_components', 'compute_structure_factor',
    'compute_intertemporal_consistency', 'penalize_extreme_move_low_vol',
    
    # 策略
    'map_direction_pref', 'map_vol_pref', 'combine_quadrant', 'get_strategy_info', 'get_strategy_structures', 'apply_disabled_structures', 'load_strategy_map',
    'compute_posture_5d', 'compute_linear_slope', 'map_slope_trend',
    'detect_fear_regime', 'evaluate_trade_permission', 'build_watchlist_guidance',
    
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
    
    # v2.3.3: OI 数据
    'fetch_total_oi', 'get_oi_with_delta', 'batch_fetch_oi',
    'get_oi_info', 'clear_oi_cache',
]

__version__ = '2.3.3'
