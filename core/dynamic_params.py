"""
动态参数计算模块 - v2.3.3
Dynamic Parameter Adaptation Layer

实现三层动态参数：
- βₜ (行为层): 控制 DirectionScore 对主动建仓的响应
- λₜ (波动层): 调整 VolScore 对波动差异的敏感性
- αₜ (市场层): 市场环境放大系数
"""
import math
from typing import Dict, List, Optional, Tuple
import numpy as np


def compute_z_score(
    current_value: float,
    historical_values: List[float],
    min_samples: int = 10
) -> float:
    """
    计算滚动 Z-score
    
    Args:
        current_value: 当前值
        historical_values: 历史值列表（不含当前值）
        min_samples: 最小样本数要求
        
    Returns:
        Z-score，如果数据不足返回 0.0
    """
    if not historical_values or len(historical_values) < min_samples:
        return 0.0
    
    try:
        mean = np.mean(historical_values)
        std = np.std(historical_values, ddof=1)
        
        if std < 1e-6:  # 标准差过小，视为常数序列
            return 0.0
        
        z = (current_value - mean) / std
        
        # 限制极端值
        z = max(-3.0, min(3.0, z))
        
        return float(z)
    except Exception as e:
        print(f"Warning: Z-score calculation failed: {e}")
        return 0.0


def compute_beta_t(
    record: Dict,
    history_cache: Dict,
    config: Dict
) -> float:
    """
    计算行为层动态参数 βₜ
    
    公式: βₜ = β_base × (1 + 0.15·z(RelVol) + 0.10·z(OI_Rank))
    
    Args:
        record: 当前分析记录
        history_cache: 历史数据缓存
        config: 配置参数
        
    Returns:
        βₜ ∈ [beta_min, beta_max]
    """
    beta_base = config.get("beta_base", 0.25)
    beta_min = config.get("beta_min", 0.20)
    beta_max = config.get("beta_max", 0.40)
    
    symbol = record.get("symbol", "")
    rel_vol = record.get("RelVolTo90D", 1.0) or 1.0
    oi_rank = record.get("OI_PctRank", 50.0) or 50.0
    
    # 获取历史数据
    symbol_history = history_cache.get("symbols", {}).get(symbol, {})
    rel_vol_hist = symbol_history.get("RelVolTo90D", [])
    oi_rank_hist = symbol_history.get("OI_PctRank", [])
    
    # 计算 Z-scores
    z_rel_vol = compute_z_score(rel_vol, rel_vol_hist)
    z_oi_rank = compute_z_score(oi_rank, oi_rank_hist)
    
    # 应用公式
    beta_t = beta_base * (1 + 0.15 * z_rel_vol + 0.10 * z_oi_rank)
    
    # 边界限制
    beta_t = max(beta_min, min(beta_max, beta_t))
    
    return beta_t


def compute_lambda_t(
    record: Dict,
    history_cache: Dict,
    config: Dict
) -> float:
    """
    计算波动层动态参数 λₜ
    
    公式: λₜ = λ_base × (1 + 0.25·z(IV30) - 0.10·z(HV20))
    
    Args:
        record: 当前分析记录
        history_cache: 历史数据缓存
        config: 配置参数
        
    Returns:
        λₜ ∈ [lambda_min, lambda_max]
    """
    lambda_base = config.get("lambda_base", 0.45)
    lambda_min = config.get("lambda_min", 0.35)
    lambda_max = config.get("lambda_max", 0.55)
    
    symbol = record.get("symbol", "")
    iv30 = record.get("IV30", 0) or 0
    hv20 = record.get("HV20", 0) or 0
    
    # 获取历史数据
    symbol_history = history_cache.get("symbols", {}).get(symbol, {})
    iv30_hist = symbol_history.get("IV30", [])
    hv20_hist = symbol_history.get("HV20", [])
    
    # 计算 Z-scores
    z_iv30 = compute_z_score(iv30, iv30_hist)
    z_hv20 = compute_z_score(hv20, hv20_hist)
    
    # 应用公式
    lambda_t = lambda_base * (1 + 0.25 * z_iv30 - 0.10 * z_hv20)
    
    # 边界限制
    lambda_t = max(lambda_min, min(lambda_max, lambda_t))
    
    return lambda_t


def compute_alpha_t(
    vix_value: float,
    history_cache: Dict,
    config: Dict
) -> float:
    """
    计算市场层动态参数 αₜ
    
    公式: αₜ = α_base × (1 + 0.4·z(VIX))
    
    Args:
        vix_value: 当前 VIX 值
        history_cache: 历史数据缓存
        config: 配置参数
        
    Returns:
        αₜ ∈ [alpha_min, alpha_max]
    """
    alpha_base = config.get("alpha_base", 0.45)
    alpha_min = config.get("alpha_min", 0.35)
    alpha_max = config.get("alpha_max", 0.60)
    
    # 获取 VIX 历史数据
    vix_history = history_cache.get("vix", {}).get("values", [])
    
    # 计算 Z-score
    z_vix = compute_z_score(vix_value, vix_history)
    
    # 应用公式
    alpha_t = alpha_base * (1 + 0.4 * z_vix)
    
    # 边界限制
    alpha_t = max(alpha_min, min(alpha_max, alpha_t))
    
    return alpha_t


def apply_ema_smoothing(
    current_value: float,
    previous_ema: Optional[float],
    span: int
) -> float:
    """
    应用指数移动平均（EMA）平滑
    
    公式: EMA_t = α·Value_t + (1-α)·EMA_{t-1}
    其中: α = 2 / (span + 1)
    
    Args:
        current_value: 当前值
        previous_ema: 前一个 EMA 值（None 表示首次计算）
        span: EMA 周期
        
    Returns:
        平滑后的值
    """
    if previous_ema is None:
        return current_value
    
    alpha = 2.0 / (span + 1)
    ema = alpha * current_value + (1 - alpha) * previous_ema
    
    return ema


def compute_all_dynamic_params(
    record: Dict,
    vix_value: float,
    history_cache: Dict,
    config: Dict
) -> Dict[str, float]:
    """
    计算所有动态参数（含 EMA 平滑）
    
    Args:
        record: 当前分析记录
        vix_value: 当前 VIX 值
        history_cache: 历史数据缓存
        config: 配置参数
        
    Returns:
        {
            'beta_t': βₜ 值,
            'lambda_t': λₜ 值,
            'alpha_t': αₜ 值,
            'beta_t_raw': βₜ 原始值（未平滑）,
            'lambda_t_raw': λₜ 原始值,
            'alpha_t_raw': αₜ 原始值
        }
    """
    symbol = record.get("symbol", "")
    
    # 计算原始动态参数
    beta_t_raw = compute_beta_t(record, history_cache, config)
    lambda_t_raw = compute_lambda_t(record, history_cache, config)
    alpha_t_raw = compute_alpha_t(vix_value, history_cache, config)
    
    # 获取历史 EMA 值
    param_history = history_cache.get("params", {}).get(symbol, {})
    beta_ema_prev = param_history.get("beta_t")
    lambda_ema_prev = param_history.get("lambda_t")
    
    # 全局 alpha EMA
    alpha_ema_prev = history_cache.get("params", {}).get("_global", {}).get("alpha_t")
    
    # 应用 EMA 平滑
    beta_t = apply_ema_smoothing(
        beta_t_raw,
        beta_ema_prev,
        config.get("beta_ema_span", 10)
    )
    
    lambda_t = apply_ema_smoothing(
        lambda_t_raw,
        lambda_ema_prev,
        config.get("lambda_ema_span", 10)
    )
    
    alpha_t = apply_ema_smoothing(
        alpha_t_raw,
        alpha_ema_prev,
        config.get("alpha_ema_span", 20)
    )
    
    return {
        'beta_t': beta_t,
        'lambda_t': lambda_t,
        'alpha_t': alpha_t,
        'beta_t_raw': beta_t_raw,
        'lambda_t_raw': lambda_t_raw,
        'alpha_t_raw': alpha_t_raw
    }


def validate_dynamic_params(params: Dict[str, float]) -> bool:
    """
    验证动态参数的有效性
    
    Args:
        params: 动态参数字典
        
    Returns:
        True if valid, False otherwise
    """
    required_keys = ['beta_t', 'lambda_t', 'alpha_t']
    
    for key in required_keys:
        if key not in params:
            return False
        
        value = params[key]
        if not isinstance(value, (int, float)):
            return False
        
        if math.isnan(value) or math.isinf(value):
            return False
        
        # 检查合理范围
        if value < 0 or value > 1.0:
            return False
    
    return True