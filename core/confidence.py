"""
置信度与流动性计算模块 - v2.3.2 参数化改进版

修复内容：
1. 跨期一致性修正系数从硬编码改为可配置
2. 增加边界条件保护
3. 优化可读性
"""
from typing import Any, Dict, List, Optional

from .metrics import compute_iv_ratio, compute_regime_ratio, compute_active_open_ratio


def map_liquidity(rec: Dict[str, Any], cfg: Dict[str, Any]) -> str:
    """
    流动性分级（保持不变）
    """
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


def compute_structure_factor(rec: Dict[str, Any], cfg: Dict[str, Any]) -> float:
    """
    结构置信度调整因子（保持不变）
    """
    multi_leg = rec.get("MultiLegPct", 0) or 0
    single_leg = rec.get("SingleLegPct", 0) or 0
    contingent = rec.get("ContingentPct", 0) or 0
    
    thresh_multi = cfg.get("multileg_conf_thresh", 40.0)
    thresh_single = cfg.get("singleleg_conf_thresh", 70.0)
    thresh_cont = cfg.get("contingent_conf_thresh", 10.0)
    
    if isinstance(multi_leg, (int, float)) and multi_leg >= thresh_multi:
        return 0.8
    elif isinstance(single_leg, (int, float)) and single_leg >= thresh_single:
        return 1.1
    elif isinstance(contingent, (int, float)) and contingent >= thresh_cont:
        return 0.9
    return 1.0


def compute_intertemporal_consistency(
    history_scores: List[float],
    n_days: int = 5
) -> float:
    """
    跨期一致性（保持不变）
    """
    if not history_scores:
        return 0.0
    
    scores = history_scores[:n_days]
    if not scores:
        return 0.0
    
    sign_sum = sum(1 if s > 0 else (-1 if s < 0 else 0) for s in scores)
    return sign_sum / len(scores)


def map_confidence(
    dir_score: float,
    vol_score: float,
    liquidity: str,
    rec: Dict[str, Any],
    cfg: Dict[str, Any],
    history_scores: Optional[List[float]] = None
) -> tuple:
    """
    置信度评估 - v2.3.2 参数化改进版
    
    修复内容：
    1. 跨期一致性修正系数从硬编码 0.3 改为从配置读取
    2. 增加边界条件保护（防止 consistency 过大导致异常）
    3. 优化代码结构和注释
    
    Returns:
        (confidence_label, structure_factor, consistency)
    """
    strength = 0.0
    
    # ========== 1. 分数强度 ==========
    strength += 0.6 if abs(dir_score) >= 1.0 else 0.3 if abs(dir_score) >= 0.6 else 0.0
    v_abs = abs(vol_score)
    th = float(cfg.get("penalty_vol_pct_thresh", 0.40))
    strength += 0.6 if v_abs >= (th + 0.4) else 0.3 if v_abs >= th else 0.0
    
    # ========== 2. 流动性 ==========
    strength += 0.5 if liquidity == "高" else 0.25 if liquidity == "中" else 0.0
    
    # ========== 3. 恐慌环境扣分 ==========
    ivr = rec.get("IVR", None)
    iv_ratio = compute_iv_ratio(rec)
    regime = compute_regime_ratio(rec)
    if (isinstance(ivr, (int, float)) and
        ivr >= cfg["fear_ivrank_min"] and
        iv_ratio >= cfg["fear_ivrv_ratio_min"] and
        regime <= cfg["fear_regime_max"]):
        strength -= 0.2
    
    # ========== 4. 缺失数据惩罚 ==========
    missing = sum(1 for k in ["PriceChgPct", "RelVolTo90D", "CallVolume",
                              "PutVolume", "IV30", "HV20", "IVR"]
                  if rec.get(k) is None)
    strength -= 0.1 * missing
    
    # ========== 5. 极端价动但缩量惩罚 ==========
    p = rec.get("PriceChgPct", None)
    rel_vol = rec.get("RelVolTo90D", 1.0) or 1.0
    if isinstance(p, (int, float)) and abs(p) >= cfg["penalty_extreme_chg"] and rel_vol <= cfg["relvol_cold"]:
        strength -= 0.3
    
    # ========== 6. 结构置信度修正 ==========
    structure_factor = compute_structure_factor(rec, cfg)
    strength *= structure_factor
    
    # ========== 🔧 7. 跨期一致性修正（参数化改进） ==========
    consistency = 0.0
    if history_scores:
        n_days = cfg.get("consistency_days", 5)
        consistency = compute_intertemporal_consistency(history_scores, n_days)
        
        # 🔧 从配置读取修正系数（原为硬编码 0.3）
        consistency_weight = cfg.get("consistency_weight", 0.3)
        consistency_thresh = cfg.get("consistency_strong", 0.6)
        
        # 🔧 增加边界保护：consistency 在 [-1, 1] 范围内
        consistency = max(-1.0, min(1.0, consistency))
        
        # 应用修正公式
        if consistency > consistency_thresh:
            # 正向趋势：Confidence × (1 + weight·Consistency)
            adjustment = 1 + consistency_weight * consistency
            strength *= adjustment
        elif consistency < -consistency_thresh:
            # 反向趋势：Confidence × (1 - weight·|Consistency|)
            adjustment = 1 - consistency_weight * abs(consistency)
            strength *= max(0.1, adjustment)  # 🔧 防止过度惩罚（最低保留 10%）
    
    # ========== 8. OI Rank 加分 ==========
    oi_rank = rec.get("OI_PctRank", 0) or 0
    if isinstance(oi_rank, (int, float)) and oi_rank >= cfg["liq_high_oi_rank"]:
        strength *= 1.2
    
    # ========== 9. 相对量加分 ==========
    if isinstance(rel_vol, (int, float)) and rel_vol >= cfg["relvol_hot"]:
        strength *= 1.1
    
    # ========== 10. ActiveOpenRatio 平仓信号降权 ==========
    active_open_ratio = compute_active_open_ratio(rec)
    if active_open_ratio < cfg.get("active_open_ratio_bear", -0.05):
        strength *= 0.8
    
    # ========== 11. 最终映射 ==========
    strength = max(0.0, strength)
    
    if strength >= 1.5:
        label = "高"
    elif strength >= 0.75:
        label = "中"
    else:
        label = "低"
    
    return (label, structure_factor, consistency)


def penalize_extreme_move_low_vol(rec: Dict[str, Any], cfg: Dict[str, Any]) -> bool:
    """
    检测极端变动低量情况（保持不变）
    """
    p = rec.get("PriceChgPct", None)
    rel_vol = rec.get("RelVolTo90D", None)
    ivchg = rec.get("IV30ChgPct", None)
    if not isinstance(p, (int, float)):
        return False
    cond_price = abs(float(p)) >= float(cfg["penalty_extreme_chg"])
    cond_vol = isinstance(rel_vol, (int, float)) and float(rel_vol) <= float(cfg["relvol_cold"])
    cond_iv = isinstance(ivchg, (int, float)) and float(ivchg) <= float(cfg["iv_pop_down"])
    return bool(cond_price and (cond_vol or cond_iv))