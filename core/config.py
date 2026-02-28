"""
配置常量和默认阈值 - v2.3.2 增强版
新增可配置的修正系数
"""
import os
from typing import Any, Dict, List

import yaml

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
    "vol_pref_threshold": 0.07,  # v2.4: 波动偏好阈值（与 penalty 语义解耦）
    # ========== Phase G: 决策映射中性缓冲带 ==========
    "direction_pref_threshold": 0.50,
    "direction_pref_neutral_buffer": 0.05,
    "vol_pref_neutral_buffer_ratio": 0.25,
    "vol_pref_neutral_buffer_min": 0.05,
    
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
    
    # ========== 数据质量校验 ==========
    "data_quality_volume_tolerance": 0.15,
    "data_quality_putpct_tolerance": 0.12,
    "data_quality_missing_warn": 2,
    "data_quality_missing_fail": 4,
    "data_quality_volume_ceiling": 50_000_000,
    "data_quality_notional_ceiling": 5_000_000_000,
    "data_quality_iv_ceiling": 300,
    
    # 趋势叠加（数值斜率）配置
    "trend_days": 5,
    "trend_slope_up": 0.10,
    "trend_slope_down": 0.10,

    # ========== 姿态/模板 Overlay ==========
    "posture_consistency_strong_threshold": 0.6,
    "posture_consistency_weak_threshold": 0.2,
    "posture_direction_strong_threshold": 1.0,
    "posture_direction_med_threshold": 0.6,
    "watch_direction_trigger": 0.65,
    "watch_vol_trigger": 0.12,
    "fear_vix_high": 25.0,

    # ========== v2.4 Phase D: 动态参数解耦与预算 ==========
    "enable_dynamic_params": False,
    "beta_base": 0.25,
    "beta_min": 0.20,
    "beta_max": 0.40,
    "lambda_base": 0.45,
    "lambda_min": 0.35,
    "lambda_max": 0.55,
    "alpha_base": 0.45,
    "alpha_min": 0.35,
    "alpha_max": 0.60,
    "beta_ema_span": 10,
    "lambda_ema_span": 10,
    "alpha_ema_span": 20,
    "dynamic_regime_min_samples": 8,
    "beta_regime_gain": 0.12,
    "lambda_regime_gain": 0.18,
    "alpha_regime_gain": 0.16,
    "dynamic_beta_budget": 0.25,
    "dynamic_lambda_budget": 0.22,
    "dynamic_alpha_budget": 0.22,
    "dynamic_edge_epsilon": 0.01,
    "dynamic_edge_hit_threshold": 3,
    "dynamic_shrink_ratio": 0.35,
    "dynamic_direction_adjustment_budget": 0.20,
    "dynamic_vol_adjustment_budget": 0.25,
}

# 指数类标的
INDEX_TICKERS = ["SPY", "QQQ", "IWM", "DIA"]


def _load_bridge_term_structure_rules() -> Dict[str, Any]:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    package_dir = os.path.abspath(os.path.dirname(__file__))
    env_path = os.environ.get("BRIDGE_TERM_RULES_PATH")

    candidates: List[str] = [
        os.path.join(repo_root, "config", "bridge_term_structure_rules.yaml"),
        os.path.join(package_dir, "config", "bridge_term_structure_rules.yaml"),
    ]
    if env_path:
        candidates.append(os.path.abspath(env_path))

    attempted = []
    for path in candidates:
        attempted.append(path)
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                if data:
                    return data
        except Exception as e:
            print(f"⚠ Warning: Failed to load bridge_term_structure_rules.yaml from {path}: {e}")
            continue

    return {}


# 桥接层配置
BRIDGE_TERM_STRUCTURE_RULES = _load_bridge_term_structure_rules()
DEFAULT_CFG["bridge_term_structure_rules"] = BRIDGE_TERM_STRUCTURE_RULES
DEFAULT_CFG["bridge_term_structure_horizon_bias"] = BRIDGE_TERM_STRUCTURE_RULES.get(
    "horizon_bias_defaults", {}
)


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

    if cfg.get("trend_days", 5) < 2:
        raise ValueError("trend_days must be >= 2")

    if cfg.get("trend_slope_up", 0.10) < 0:
        raise ValueError("trend_slope_up must be >= 0")

    if cfg.get("trend_slope_down", 0.10) < 0:
        raise ValueError("trend_slope_down must be >= 0")

    if cfg.get("direction_pref_threshold", 1.0) <= 0:
        raise ValueError("direction_pref_threshold must be > 0")

    if cfg.get("direction_pref_neutral_buffer", 0.15) < 0:
        raise ValueError("direction_pref_neutral_buffer must be >= 0")

    if cfg.get("vol_pref_neutral_buffer_ratio", 0.25) < 0:
        raise ValueError("vol_pref_neutral_buffer_ratio must be >= 0")

    if cfg.get("vol_pref_neutral_buffer_min", 0.05) < 0:
        raise ValueError("vol_pref_neutral_buffer_min must be >= 0")


    # ---- Phase G: 映射阈值可达性约束（防止象限永远中性） ----
    # 理论上 score ∈ [-1, 1]；若开启动态参数，则可被整体放大到 (1+budget) 倍。
    dir_budget = float(cfg.get("dynamic_direction_adjustment_budget", 0.20)) if cfg.get("enable_dynamic_params", False) else 0.0
    vol_budget = float(cfg.get("dynamic_vol_adjustment_budget", 0.25)) if cfg.get("enable_dynamic_params", False) else 0.0
    dir_max = 1.0 * (1.0 + max(0.0, dir_budget))
    vol_max = 1.0 * (1.0 + max(0.0, vol_budget))

    dir_upper = float(cfg.get("direction_pref_threshold", 0.50)) + float(cfg.get("direction_pref_neutral_buffer", 0.05))
    if dir_upper > dir_max + 1e-9:
        raise ValueError(
            f"direction pref upper ({dir_upper:.3f}) exceeds reachable max ({dir_max:.3f}); "
            "mapping will collapse to neutral"
        )

    vol_th = float(cfg.get("vol_pref_threshold", cfg.get("penalty_vol_pct_thresh", 0.40)))
    buffer_ratio = float(cfg.get("vol_pref_neutral_buffer_ratio", 0.25))
    buffer_min = float(cfg.get("vol_pref_neutral_buffer_min", 0.05))
    vol_buffer = max(abs(vol_th) * max(0.0, buffer_ratio), max(0.0, buffer_min))
    vol_upper = abs(vol_th) + vol_buffer
    if vol_upper > vol_max + 1e-9:
        raise ValueError(
            f"vol pref upper ({vol_upper:.3f}) exceeds reachable max ({vol_max:.3f}); "
            "mapping will collapse to neutral"
        )

    for key in ("dynamic_beta_budget", "dynamic_lambda_budget", "dynamic_alpha_budget",
                "dynamic_direction_adjustment_budget", "dynamic_vol_adjustment_budget"):
        val = cfg.get(key, 0.25)
        if not (0 <= val <= 1.0):
            raise ValueError(f"{key} must be in [0, 1.0]")

    if not (0 < cfg.get("dynamic_shrink_ratio", 0.35) < 1.0):
        raise ValueError("dynamic_shrink_ratio must be in (0, 1.0)")

    if cfg.get("dynamic_edge_hit_threshold", 3) < 1:
        raise ValueError("dynamic_edge_hit_threshold must be >= 1")
    
    return True
