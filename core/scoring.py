"""
评分模型模块 - v2.3.3
应用动态参数化机制
✨ NEW: 支持时间限制跳过 OI 修正
"""
import math
from typing import Any, Dict, Optional

from .metrics import (
    compute_volume_bias, compute_notional_bias, compute_callput_ratio,
    compute_ivrv, compute_iv_ratio, compute_regime_ratio,
    compute_spot_vol_correlation_score, compute_active_open_ratio,
    compute_term_structure_adjustment,
    parse_earnings_date, days_until
)


def compute_direction_score(
    rec: Dict[str, Any],
    cfg: Dict[str, Any],
    dynamic_params: Optional[Dict[str, float]] = None,
    skip_oi: bool = False  # ✨ NEW: 是否跳过 OI 修正
) -> float:
    """
    方向分数计算 - v2.3.3 动态参数版本
    
    改进：
    1. 支持动态 βₜ 参数（从 dynamic_params 获取）
    2. 如果 dynamic_params 为 None，回退到 v2.3.2 固定参数
    3. ✨ NEW: 支持时间限制跳过 AOR 修正（18:00 前）
    
    公式：DirScore_adj = DirScore × (1 + βₜ·tanh(ActiveOpenRatio))
    
    Args:
        rec: 记录数据
        cfg: 配置参数
        dynamic_params: 动态参数字典
        skip_oi: ✨ 是否跳过 AOR 修正（无 OI 数据时为 True）
    """
    price_chg_pct = rec.get("PriceChgPct", 0.0) or 0.0
    rel_vol = rec.get("RelVolTo90D", 1.0) or 1.0
    vol_bias = compute_volume_bias(rec)
    notional_bias = compute_notional_bias(rec)
    cp_ratio = compute_callput_ratio(rec)
    put_pct = rec.get("PutPct", None)
    single_leg = rec.get("SingleLegPct", None)
    multi_leg = rec.get("MultiLegPct", None)
    contingent = rec.get("ContingentPct", None)
    
    # ============ 基础分数计算 ============
    
    # 价格项: tanh 平滑
    price_term = 0.90 * math.tanh(float(price_chg_pct) / 1.75)
    
    # 名义与量偏度
    notional_term = 0.60 * notional_bias
    vol_bias_term = 0.35 * vol_bias
    
    # 放量微调
    relvol_term = 0.0
    if rel_vol >= cfg["relvol_hot"]:
        relvol_term = 0.18
    elif rel_vol <= cfg["relvol_cold"]:
        relvol_term = -0.05
    
    # Call/Put 比率
    cpr_term = 0.0
    if cp_ratio >= cfg["callput_ratio_bull"]:
        cpr_term = 0.30
    elif cp_ratio <= cfg["callput_ratio_bear"]:
        cpr_term = -0.30
    
    # Put 比例
    put_term = 0.0
    if isinstance(put_pct, (int, float)):
        if put_pct >= cfg["putpct_bear"]:
            put_term = -0.20
        elif put_pct <= cfg["putpct_bull"]:
            put_term = 0.20
        else:
            put_term = 0.20 * (50.0 - float(put_pct)) / 50.0
    
    score = price_term + notional_term + vol_bias_term + relvol_term + cpr_term + put_term
    
    # 加入价-波相关性得分
    score += compute_spot_vol_correlation_score(rec)
    
    # 结构加权
    amp = 1.0
    if isinstance(single_leg, (int, float)) and single_leg >= cfg["singleleg_high"]:
        amp *= 1.10
    if isinstance(multi_leg, (int, float)) and multi_leg >= cfg["multileg_high"]:
        amp *= 0.90
    if isinstance(contingent, (int, float)) and contingent >= cfg["contingent_high"]:
        amp *= 0.90
    
    score = float(score * amp)
    
    # ============ 🟩 v2.3.3: 动态 βₜ 修正 ============
    # ✨ NEW: 只在有 OI 数据时应用修正
    if not skip_oi:
        active_open_ratio = compute_active_open_ratio(rec)
        
        # 获取动态参数（如果启用）
        if dynamic_params and cfg.get("enable_dynamic_params", True):
            # 使用动态 βₜ
            beta_t = dynamic_params.get("beta_t", cfg.get("beta_base", 0.25))
        else:
            # 回退到 v2.3.2 固定参数
            beta_t = cfg.get("active_open_ratio_beta", 0.5)
        
        # 应用连续修正公式
        aor_capped = math.tanh(active_open_ratio * 3)  # 软截断
        adjustment_factor = 1 + beta_t * aor_capped
        
        score *= adjustment_factor
    else:
        # ✨ 跳过 AOR 修正（记录日志）
        # print(f"⏰ Skipped AOR adjustment (no OI data)")
        pass
    
    return score


def compute_vol_score(
    rec: Dict[str, Any],
    cfg: Dict[str, Any],
    ignore_earnings: bool = False,
    dynamic_params: Optional[Dict[str, float]] = None
) -> float:
    """
    波动分数计算 - v2.3.3 动态参数版本
    
    改进：
    1. 支持动态 λₜ 和 αₜ 参数
    2. 应用市场环境放大：VolScore × (1 + αₜ·λₜ)
    """
    ivr = rec.get("IVR", None)
    ivrv = compute_ivrv(rec)
    iv_ratio = compute_iv_ratio(rec)
    iv30_chg = rec.get("IV30ChgPct", 0.0) or 0.0
    hv20 = rec.get("HV20", None)
    iv30 = rec.get("IV30", None)
    regime = compute_regime_ratio(rec)
    multi_leg = rec.get("MultiLegPct", None)
    
    # ============ 基础分数计算 ============
    
    # IVR 中心化
    ivr_center = 0.0
    if isinstance(ivr, (int, float)):
        ivr_center = (float(ivr) - 50.0) / 50.0
    
    # 卖波压力
    sell_pressure = 1.2 * ivr_center + 1.2 * ivrv
    
    # 当日 IV 变化
    ivchg_buy = 0.5 if iv30_chg >= cfg["iv_pop_up"] else 0.0
    ivchg_sell = 0.5 if iv30_chg <= cfg["iv_pop_down"] else 0.0
    
    # 折价项
    discount_term = 0.0
    if isinstance(hv20, (int, float)) and isinstance(iv30, (int, float)) and hv20 > 0:
        discount_term = max(0.0, (float(hv20) - float(iv30)) / float(hv20))
    
    # 长便宜/短昂贵
    longcheap = ((isinstance(ivr, (int, float)) and ivr <= cfg["iv_longcheap_rank"]) or
                 (iv_ratio <= cfg["iv_longcheap_ratio"]))
    shortrich = ((isinstance(ivr, (int, float)) and ivr >= cfg["iv_shortrich_rank"]) or
                 (iv_ratio >= cfg["iv_shortrich_ratio"]))
    cheap_boost = 0.6 if longcheap else 0.0
    rich_pressure = 0.6 if shortrich else 0.0
    
    # 财报事件
    earn_boost = 0.0
    if not ignore_earnings:
        earn_date = parse_earnings_date(rec.get("Earnings"))
        dte = days_until(earn_date)
        if dte is not None and dte > 0:
            if dte <= 2:
                earn_boost = 0.8
            elif dte <= 7:
                earn_boost = 0.4
            elif dte <= cfg["earnings_window_days"]:
                earn_boost = 0.2
    
    # 恐慌环境卖波倾向
    fear_sell = 0.0
    if (isinstance(ivr, (int, float)) and
        ivr >= cfg["fear_ivrank_min"] and
        iv_ratio >= cfg["fear_ivrv_ratio_min"] and
        regime <= cfg["fear_regime_max"]):
        fear_sell = 0.4
    
    # Regime 调整
    regime_term = 0.0
    if regime >= cfg["regime_hot"]:
        regime_term = 0.2
    elif regime <= cfg["regime_calm"]:
        regime_term = -0.2
    
    # 汇总
    buy_side = 0.8 * discount_term + ivchg_buy + cheap_boost + earn_boost + regime_term
    sell_side = sell_pressure + rich_pressure + ivchg_sell + fear_sell
    vol_score = float(buy_side - sell_side)

    # 期限结构修正
    vol_score += compute_term_structure_adjustment(rec, cfg)
    
    # v2.3.2: 多腿修正
    if isinstance(multi_leg, (int, float)) and isinstance(ivr, (int, float)):
        if multi_leg > 40 and ivr > 70:
            vol_score *= 0.8
        elif multi_leg > 40 and ivr < 30:
            vol_score *= 0.9
    
    # ============ 🟩 v2.3.3: 动态市场环境调整 ============
    
    if dynamic_params and cfg.get("enable_dynamic_params", True):
        lambda_t = dynamic_params.get("lambda_t", cfg.get("lambda_base", 0.45))
        alpha_t = dynamic_params.get("alpha_t", cfg.get("alpha_base", 0.45))
        
        # 应用公式: VolScore × (1 + αₜ·λₜ)
        adjustment_factor = 1 + alpha_t * lambda_t
        vol_score *= adjustment_factor
    
    return vol_score
