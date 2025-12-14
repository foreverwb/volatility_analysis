"""
核心分析函数 - v2.3.3
集成动态参数化机制
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from .config import DEFAULT_CFG, INDEX_TICKERS, get_dynamic_thresholds
from .cleaning import clean_record, normalize_dataset
from .metrics import (
    compute_volume_bias, compute_notional_bias, compute_callput_ratio,
    compute_ivrv, compute_iv_ratio, compute_regime_ratio,
    compute_spot_vol_correlation_score, detect_squeeze_potential,
    compute_active_open_ratio, compute_term_structure,
    parse_earnings_date, days_until
)
from .scoring import compute_direction_score, compute_vol_score
from .confidence import map_liquidity, map_confidence, penalize_extreme_move_low_vol
from .strategy import map_direction_pref, map_vol_pref, combine_quadrant, get_strategy_info

# v2.3.3 新增导入
from .market_data import get_vix_with_fallback
from .rolling_cache import get_global_cache, update_cache_with_record
from .dynamic_params import compute_all_dynamic_params, validate_dynamic_params


def calculate_analysis(
    data: Dict[str, Any],
    cfg: Dict[str, Any] = None,
    ignore_earnings: bool = False,
    history_scores: Optional[List[float]] = None
) -> Dict[str, Any]:
    """
    核心分析函数 - v2.3.3
    
    新增流程：
    1. 获取 VIX 数据
    2. 从缓存加载历史数据
    3. 计算动态参数 (βₜ, λₜ, αₜ)
    4. 应用动态参数到评分
    5. 更新缓存
    
    Args:
        data: 原始输入数据
        cfg: 配置参数 (默认使用 DEFAULT_CFG)
        ignore_earnings: 是否忽略财报事件
        history_scores: 历史方向评分列表 (用于跨期一致性计算)
        
    Returns:
        完整分析结果（包含动态参数）
    """
    if cfg is None:
        cfg = DEFAULT_CFG
    
    # 1. 数据清洗与归一化
    cleaned = clean_record(data)
    normed = normalize_dataset([cleaned])[0]
    symbol = normed.get('symbol', 'N/A')
    
    # 2. 获取生效配置 (Index vs Stock)
    effective_cfg = get_dynamic_thresholds(symbol, cfg)
    
    # ============ 🟩 v2.3.3: 动态参数计算 ============
    
    dynamic_params = None
    vix_value = None
    
    if effective_cfg.get("enable_dynamic_params", True):
        try:
            # 获取 VIX 数据
            vix_value = get_vix_with_fallback(
                default=effective_cfg.get("vix_fallback_value", 18.0)
            )
            
            # 获取历史缓存
            cache = get_global_cache()
            history_cache = cache.get_data()
            
            # 计算动态参数
            dynamic_params = compute_all_dynamic_params(
                normed,
                vix_value,
                history_cache,
                effective_cfg
            )
            
            # 验证参数
            if not validate_dynamic_params(dynamic_params):
                print(f"⚠ Warning: Invalid dynamic params for {symbol}, using fallback")
                dynamic_params = None
        
        except Exception as e:
            print(f"⚠ Warning: Dynamic params calculation failed: {e}")
            dynamic_params = None
    
    # ============ 基础指标计算 ============
    
    spot_vol_score = compute_spot_vol_correlation_score(normed)
    is_squeeze = detect_squeeze_potential(normed, effective_cfg)
    term_structure_val, term_structure_str = compute_term_structure(normed)
    active_open_ratio = compute_active_open_ratio(normed)
    
    # ============ 🟩 评分计算（应用动态参数） ============
    
    dir_score = compute_direction_score(
        normed,
        effective_cfg,
        dynamic_params=dynamic_params  # v2.3.3 新增参数
    )
    
    vol_score = compute_vol_score(
        normed,
        effective_cfg,
        ignore_earnings=ignore_earnings,
        dynamic_params=dynamic_params  # v2.3.3 新增参数
    )
    
    # ============ 偏好映射 ============
    
    dir_pref = map_direction_pref(dir_score)
    vol_pref = map_vol_pref(vol_score, effective_cfg)
    quadrant = combine_quadrant(dir_pref, vol_pref)
    
    # ============ 流动性与置信度 ============
    
    liquidity = map_liquidity(normed, effective_cfg)
    confidence, structure_factor, consistency = map_confidence(
        dir_score, vol_score, liquidity, normed, effective_cfg, history_scores
    )
    
    penal_flag = penalize_extreme_move_low_vol(normed, effective_cfg)
    
    # ============ 策略建议 ============
    
    strategy_info = get_strategy_info(quadrant, liquidity, is_squeeze=is_squeeze)
    
    # ============ 派生指标 ============
    
    iv30 = normed.get("IV30")
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
    
    # ============ 驱动因素 ============
    
    direction_factors = []
    price_chg = normed.get("PriceChgPct", 0) or 0
    
    if price_chg >= 1.0:
        direction_factors.append(f"涨幅 {price_chg:.1f}%")
    elif price_chg <= -1.0:
        direction_factors.append(f"跌幅 {price_chg:.1f}%")
    else:
        direction_factors.append(f"涨跌幅 {price_chg:.1f}% (中性)")
    
    direction_factors.append(f"量偏度 {vol_bias:.2f}")
    direction_factors.append(f"名义偏度 {notional_bias:.2f}")
    direction_factors.append(f"Call/Put比率 {cp_ratio:.2f}")
    direction_factors.append(f"相对量 {normed.get('RelVolTo90D', 1.0):.2f}x")
    
    if active_open_ratio >= 0.05:
        direction_factors.append(f"📈 主动开仓 {active_open_ratio:.3f}")
    elif active_open_ratio <= -0.05:
        direction_factors.append(f"📉 平仓信号 {active_open_ratio:.3f}")
    
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
    
    if term_structure_val:
        if term_structure_val > 1.1:
            vol_factors.append("📉 期限倒挂 (恐慌)")
        elif term_structure_val < 0.9:
            vol_factors.append("📈 期限陡峭 (正常)")
    
    # ============ 构建返回结果 ============
    
    result = {
        'symbol': symbol,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'quadrant': quadrant,
        'confidence': confidence,
        'liquidity': liquidity,
        'penalized_extreme_move_low_vol': penal_flag,
        
        # 高级指标
        'is_squeeze': is_squeeze,
        'is_index': symbol in INDEX_TICKERS,
        'spot_vol_corr_score': round(spot_vol_score, 2),
        'term_structure_ratio': term_structure_str,
        
        # v2.3.2 字段
        'active_open_ratio': round(active_open_ratio, 4),
        'consistency': round(consistency, 3),
        'structure_factor': round(structure_factor, 2),
        'flow_bias': round(notional_bias, 3),
        
        # 评分
        'direction_score': round(dir_score, 3),
        'vol_score': round(vol_score, 3),
        'direction_bias': dir_pref,
        'vol_bias': vol_pref,
        'direction_factors': direction_factors,
        'vol_factors': vol_factors,
        
        # 🟩 v2.3.3: 动态参数
        'dynamic_params': {
            'enabled': effective_cfg.get("enable_dynamic_params", True),
            'vix': round(vix_value, 2) if vix_value else None,
            'beta_t': round(dynamic_params['beta_t'], 4) if dynamic_params else None,
            'lambda_t': round(dynamic_params['lambda_t'], 4) if dynamic_params else None,
            'alpha_t': round(dynamic_params['alpha_t'], 4) if dynamic_params else None,
            'beta_t_raw': round(dynamic_params['beta_t_raw'], 4) if dynamic_params else None,
            'lambda_t_raw': round(dynamic_params['lambda_t_raw'], 4) if dynamic_params else None,
            'alpha_t_raw': round(dynamic_params['alpha_t_raw'], 4) if dynamic_params else None,
        },
        
        # 派生指标
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
        
        # 策略建议
        'strategy': strategy_info['策略'],
        'risk': strategy_info['风险'],
        'raw_data': data
    }
    
    if effective_cfg.get("enable_dynamic_params", True) and dynamic_params and vix_value:
        try:
            cache = get_global_cache()
            update_cache_with_record(normed, vix_value, dynamic_params, cache)
        except Exception as e:
            print(f"⚠ Warning: Failed to update cache: {e}")
    
    return result