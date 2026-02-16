"""
核心分析函数 - v2.3.3 (VIX持久化增强版)
✨ NEW: 支持时间限制跳过 OI 数据
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from .config import DEFAULT_CFG, INDEX_TICKERS, get_dynamic_thresholds
from .cleaning import clean_record, normalize_dataset
from .validation import validate_record
from .features import build_features
from .scoring import (
    compute_direction_components,
    compute_direction_score,
    compute_vol_components,
    compute_vol_score,
)
from .confidence import (
    compute_liquidity_score,
    map_liquidity,
    compute_confidence_components,
    penalize_extreme_move_low_vol,
)
from .strategy import (
    map_direction_pref,
    map_vol_pref,
    combine_quadrant,
    get_strategy_info,
    get_strategy_structures,
)
from .posture import compute_posture_5d
from .trend import compute_linear_slope, map_slope_trend
from .guards import detect_fear_regime, evaluate_trade_permission, build_watchlist_guidance
from .metrics import compute_squeeze_score

from .market_data import get_vix_with_fallback
from .rolling_cache import get_global_cache, update_cache_with_record
from .dynamic_params import compute_all_dynamic_params, validate_dynamic_params
from bridge.builders import build_bridge_snapshot
from bridge.micro_templates import select_micro_template


def _count_valid_points(scores: Optional[List[float]], n_days: int) -> int:
    if not scores or n_days <= 0:
        return 0
    valid = 0
    for score in scores:
        if isinstance(score, bool) or score is None:
            continue
        try:
            float(score)
            valid += 1
        except (TypeError, ValueError):
            continue
        if valid >= n_days:
            break
    return valid


def calculate_analysis(
    data: Dict[str, Any],
    cfg: Dict[str, Any] = None,
    ignore_earnings: bool = False,
    history_scores: Optional[List[float]] = None,
    skip_oi: bool = False,  # ✨ NEW: 是否跳过 OI 相关计算
    vix_value: Optional[float] = None
) -> Dict[str, Any]:
    """
    核心分析函数 - v2.3.3 (VIX持久化增强版)
    
    改进:
    1. 确保 VIX 值被持久化到分析记录的顶层 (非仅在 dynamic_params 中)
    2. 所有分析记录都包含 VIX 值，即使动态参数未启用
    3. ✨ NEW: 支持时间限制跳过 OI 数据
    
    Args:
        data: 原始输入数据
        cfg: 配置参数
        ignore_earnings: 是否忽略财报事件
        history_scores: 历史方向评分列表
        skip_oi: ✨ 是否跳过 OI 相关计算（18:00 前为 True）
        
    Returns:
        完整分析结果 (包含 vix 字段)
    """
    if cfg is None:
        cfg = DEFAULT_CFG
    
    cleaned = clean_record(data)
    normed = normalize_dataset([cleaned])[0]
    symbol = normed.get('symbol', 'N/A')
    
    effective_cfg = get_dynamic_thresholds(symbol, cfg)
    
    validation = validate_record(normed, effective_cfg)
    data_quality = validation["data_quality"]
    data_quality_issues = validation["data_quality_issues"]

    # ============ 统一特征构建 ============
    features = build_features(normed, effective_cfg)
    oi_info = normed.get("oi_info") if isinstance(normed.get("oi_info"), dict) else {}
    if isinstance(oi_info.get("data_available"), bool):
        oi_data_available = bool(oi_info.get("data_available"))
    elif skip_oi:
        oi_data_available = False
    else:
        oi_info_total = oi_info.get("total_oi", oi_info.get("current_oi"))
        oi_info_delta = oi_info.get("delta_oi_1d", oi_info.get("delta_oi"))
        if oi_info_total is None and oi_info_delta is None:
            oi_data_available = (
                isinstance(features.get("total_oi"), (int, float))
                or isinstance(features.get("delta_oi_1d"), (int, float))
            )
        else:
            oi_data_available = True
    
    # ============ 🟢 强制获取 VIX (不受动态参数开关影响) ============
    if vix_value is None:
        vix_value = get_vix_with_fallback(
            default=effective_cfg.get("vix_fallback_value", 18.0)
        )
    
    # ============ 动态参数计算 ============
    dynamic_params = None
    
    if effective_cfg.get("enable_dynamic_params", True):
        try:
            cache = get_global_cache()
            history_cache = cache.get_data()
            
            dynamic_params = compute_all_dynamic_params(
                normed,
                vix_value,
                history_cache,
                effective_cfg
            )
            
            if not validate_dynamic_params(dynamic_params):
                print(f"⚠ Warning: Invalid dynamic params for {symbol}, using fallback")
                dynamic_params = None
        
        except Exception as e:
            print(f"⚠ Warning: Dynamic params calculation failed: {e}")
            dynamic_params = None

    # 运行时上下文注入到 features（供评分/置信度分项计算）
    dynamic_apply = bool(dynamic_params and effective_cfg.get("enable_dynamic_params", True))
    features["skip_oi"] = bool(skip_oi)
    features["oi_data_available"] = bool(oi_data_available)
    features["ignore_earnings"] = bool(ignore_earnings)
    features["dynamic_apply"] = dynamic_apply
    if dynamic_apply:
        features["beta_t"] = float(dynamic_params.get("beta_t", effective_cfg.get("beta_base", 0.25)))
        features["lambda_t"] = float(dynamic_params.get("lambda_t", effective_cfg.get("lambda_base", 0.45)))
        features["alpha_t"] = float(dynamic_params.get("alpha_t", effective_cfg.get("alpha_base", 0.45)))
    else:
        features["beta_t"] = float(effective_cfg.get("active_open_ratio_beta", 0.5))
        features["lambda_t"] = None
        features["alpha_t"] = None
    
    # ============ 基础指标计算 ============
    spot_vol_score = float(features.get("spot_vol_score", 0.0) or 0.0)
    squeeze_score, squeeze_reasons = compute_squeeze_score(features, effective_cfg)
    squeeze_trigger = float(effective_cfg.get("squeeze_score_trigger", 0.70))
    is_squeeze = bool(squeeze_score >= squeeze_trigger)
    features["squeeze_score"] = float(squeeze_score)
    features["squeeze_reasons"] = list(squeeze_reasons)
    features["is_squeeze"] = is_squeeze
    term_structure_str = features.get("term_structure_ratio", "N/A")
    term_structure_label_code = features.get("term_structure_label_code", "unknown")
    term_structure_horizon_bias = features.get("term_structure_horizon_bias", "neutral")
    term_structure_dte_bias = features.get("term_structure_dte_bias", "neutral")
    fear_flag, fear_reasons = detect_fear_regime(normed, term_structure_str, vix_value, effective_cfg)
    
    # ✨ NEW: 条件计算 ActiveOpenRatio
    if skip_oi:
        active_open_ratio = 0.0  # 跳过 OI 时设为 0
    else:
        active_open_ratio = float(features.get("active_open_ratio", 0.0) or 0.0)
    
    # ============ 评分计算 ============
    direction_components = compute_direction_components(features, effective_cfg)
    dir_score = compute_direction_score(features, effective_cfg)

    vol_components = compute_vol_components(features, effective_cfg)
    vol_score = compute_vol_score(features, effective_cfg)
    
    # ============ 偏好映射 ============
    dir_pref = map_direction_pref(dir_score)
    vol_pref = map_vol_pref(vol_score, effective_cfg)
    quadrant = combine_quadrant(dir_pref, vol_pref)
    
    # ============ 流动性与置信度 ============
    liquidity_score, liquidity_reasons = compute_liquidity_score(normed, effective_cfg)
    liquidity = map_liquidity(liquidity_score, effective_cfg)
    features["liquidity"] = liquidity
    features["liquidity_score"] = float(liquidity_score)
    features["liquidity_reasons"] = list(liquidity_reasons)
    features["history_scores"] = list(history_scores) if isinstance(history_scores, list) else []

    confidence_components = compute_confidence_components(
        features,
        dir_score,
        vol_score,
        effective_cfg,
        oi_data_available=oi_data_available,
    )
    confidence = confidence_components.get("label", "低")
    confidence_score = float(
        confidence_components.get(
            "confidence_score",
            confidence_components.get("final_strength", 0.0),
        )
    )
    structure_factor = float(confidence_components.get("structure_factor", 1.0))
    consistency = float(confidence_components.get("consistency", 0.0))
    confidence_notes = []
    if data_quality == "LOW" and confidence != "低":
        confidence_notes.append("数据质量LOW→置信度降级")
        confidence = "低"
    elif data_quality == "MED" and confidence == "高":
        confidence_notes.append("数据质量MED→置信度降级为中")
        confidence = "中"
    confidence_components["label_after_quality_gate"] = confidence
    confidence_components["quality_gate_applied"] = bool(confidence_notes)
    penal_flag = penalize_extreme_move_low_vol(normed, effective_cfg)
    
    # ============ 策略建议 ============
    strategy_info = get_strategy_info(
        quadrant,
        liquidity,
        is_squeeze=is_squeeze,
        features=features,
        cfg=effective_cfg,
    )
    
    # ============ 派生指标 ============
    ivrv_ratio = float(features.get("ivrv_ratio", 1.0) or 1.0)
    ivrv_diff = float(features.get("ivrv_diff", 0.0) or 0.0)
    ivrv_log = float(features.get("ivrv_log", 0.0) or 0.0)
    regime_ratio = float(features.get("regime_ratio", 1.0) or 1.0)
    vol_bias = float(features.get("volume_bias", 0.0) or 0.0)
    notional_bias = float(features.get("notional_bias", 0.0) or 0.0)
    cp_ratio = float(features.get("cp_ratio", 1.0) or 1.0)
    days_to_earnings = features.get("days_to_earnings")
    total_oi = features.get("total_oi")
    delta_oi_1d = features.get("delta_oi_1d")
    delta_oi_pct = features.get("delta_oi_pct")
    oi_turnover = features.get("oi_turnover")
    posture_info = compute_posture_5d(dir_score, history_scores, effective_cfg)

    # 数值斜率趋势（与 posture_5d 的符号一致性互补）
    trend_days = int(effective_cfg.get("trend_days", 5))
    dir_slope = compute_linear_slope(history_scores or [], trend_days)
    dir_trend_label = map_slope_trend(dir_slope, effective_cfg)
    trend_days_used = _count_valid_points(history_scores, trend_days)
    
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
    
    # ✨ NEW: 只在有 OI 数据时显示
    if not skip_oi:
        if active_open_ratio >= 0.05:
            direction_factors.append(f"📈 主动开仓 {active_open_ratio:.3f}")
        elif active_open_ratio <= -0.05:
            direction_factors.append(f"📉 平仓信号 {active_open_ratio:.3f}")
    
    if spot_vol_score >= 0.4:
        direction_factors.append("🔥 逼空/动量 (价升波升)")
    elif spot_vol_score <= -0.5:
        direction_factors.append("⚠️ 恐慌抛售 (价跌波降)")
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
    
    if term_structure_str and term_structure_str != "N/A":
        vol_factors.append(f"期限结构: {term_structure_str}")
    
    permission_info = evaluate_trade_permission(
        quadrant=quadrant,
        vol_pref=vol_pref,
        confidence=confidence,
        days_to_earnings=days_to_earnings,
        data_quality=data_quality,
        fear_reasons=fear_reasons,
        cfg=effective_cfg
    )
    # 姿态层风险覆盖
    posture_overlay_notes = []
    severity_map = {"NORMAL": 0, "ALLOW_DEFINED_RISK_ONLY": 1, "NO_TRADE": 2}
    posture_perm = permission_info["trade_permission"]
    perm_reasons = list(permission_info["permission_reasons"])
    disabled_structures = set(permission_info["disabled_structures"])
    posture_tag = posture_info.get("posture_5d")
    
    def elevate(target: str, code: str, add_disabled: bool = False):
        nonlocal posture_perm
        if severity_map.get(target, 0) > severity_map.get(posture_perm, 0):
            posture_perm = target
        perm_reasons.append(code)
        if add_disabled:
            disabled_structures.update(["naked_short_put", "naked_short_call", "short_strangle", "short_call_ratio", "short_put_ratio"])
    
    if posture_tag == "COUNTERTREND":
        elevate("ALLOW_DEFINED_RISK_ONLY", "POSTURE_COUNTERTREND")
        posture_overlay_notes.append("逆势反转：降级为定义风险")
    elif posture_tag == "ONE_DAY_SHOCK":
        elevate("ALLOW_DEFINED_RISK_ONLY", "POSTURE_ONE_DAY_SHOCK")
        disabled_structures.update(["naked_short_put", "naked_short_call", "short_strangle"])
        posture_overlay_notes.append("单日冲击：避免裸露尾部")
    elif posture_tag == "CHOP":
        elevate("NO_TRADE", "POSTURE_CHOP", add_disabled=True)
        posture_overlay_notes.append("震荡/摇摆：倾向观望")
    
    permission_info["trade_permission"] = posture_perm
    permission_info["permission_reasons"] = perm_reasons
    permission_info["disabled_structures"] = list(disabled_structures)
    
    watch_guidance = build_watchlist_guidance(
        quadrant=quadrant,
        dir_score=dir_score,
        vol_score=vol_score,
        active_open_ratio=active_open_ratio,
        structure_factor=structure_factor,
        term_structure_label=term_structure_str,
        cfg=effective_cfg
    )
    
    # ============ 🟢 构建返回结果 (VIX 提升到顶层) ============
    result = {
        'symbol': symbol,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'quadrant': quadrant,
        'confidence': confidence,
        'confidence_score': round(confidence_score, 3),
        'confidence_notes': confidence_notes,
        'liquidity': liquidity,
        'liquidity_score': round(float(liquidity_score), 3),
        'liquidity_reasons': list(liquidity_reasons),
        'data_quality': data_quality,
        'data_quality_issues': data_quality_issues,
        'penalized_extreme_move_low_vol': penal_flag,
        'fear_regime': fear_flag,
        'trade_permission': permission_info["trade_permission"],
        'permission_reasons': permission_info["permission_reasons"],
        'disabled_structures': permission_info["disabled_structures"],
        'watch_triggers': watch_guidance.get("watch_triggers", []),
        'what_to_monitor': watch_guidance.get("what_to_monitor", []),
        'posture_5d': posture_info.get("posture_5d"),
        'posture_reasons': posture_info.get("posture_reasons"),
        'posture_reason_codes': posture_info.get("posture_reason_codes"),
        'posture_confidence': posture_info.get("posture_confidence"),
        'posture_inputs_snapshot': posture_info.get("posture_inputs_snapshot"),
        'posture_overlay_notes': posture_overlay_notes,
        # 趋势叠加：最近 N 日方向评分线性斜率及标签
        'dir_slope_nd': round(dir_slope, 3),
        'dir_trend_label': dir_trend_label,
        'trend_days_used': trend_days_used,
        
        # 🟢 VIX 提升到顶层 (与 IVR/IV30 等同级)
        'vix': round(vix_value, 2) if vix_value else None,
        
        # 🟢 清洗后的核心字段 (供 API 直接使用)
        'ivr': normed.get('IVR'),
        'iv30': normed.get('IV30'),
        'hv20': normed.get('HV20'),
        
        # 高级指标
        'is_squeeze': is_squeeze,
        'squeeze_score': round(float(squeeze_score), 3),
        'squeeze_reasons': list(squeeze_reasons),
        'is_index': symbol in INDEX_TICKERS,
        'spot_vol_corr_score': round(spot_vol_score, 2),
        'term_structure_ratio': term_structure_str,
        'term_structure_label_code': term_structure_label_code,
        'term_structure_horizon_bias': term_structure_horizon_bias,
        'term_structure_dte_bias': term_structure_dte_bias,
        
        'active_open_ratio': round(active_open_ratio, 4),
        'total_oi': total_oi,
        'delta_oi_1d': delta_oi_1d,
        'delta_oi_pct': delta_oi_pct,
        'oi_turnover': oi_turnover,
        'consistency': round(consistency, 3),
        'structure_factor': round(structure_factor, 2),
        'flow_bias': round(notional_bias, 3),
        
        # ✨ NEW: 添加 OI 状态标记
        'oi_data_available': bool(oi_data_available),
        
        # 评分
        'direction_score': round(dir_score, 3),
        'vol_score': round(vol_score, 3),
        'direction_components': direction_components,
        'vol_components': vol_components,
        'confidence_components': confidence_components,
        'direction_bias': dir_pref,
        'vol_bias': vol_pref,
        'direction_factors': direction_factors,
        'vol_factors': vol_factors,
        
        # 动态参数详情
        'dynamic_params': {
            'enabled': effective_cfg.get("enable_dynamic_params", True),
            'vix': round(vix_value, 2) if vix_value else None,  # 保留此字段用于兼容
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
        'features': features,
        
        # 策略建议
        'strategy': strategy_info['策略'],
        'risk': strategy_info['风险'],
        'strategy_structures': [],
        'raw_data': data
    }

    # ============ Bridge Snapshot (供 micro 层消费) ============
    bridge_payload = dict(normed)
    bridge_payload.update({
        'symbol': symbol,
        'timestamp': result['timestamp'],
        'vix': vix_value,
        'IVR': normed.get('IVR'),
        'iv30': result.get('iv30'),
        'hv20': result.get('hv20'),
        'hv1y': normed.get('HV1Y'),
        'quadrant': quadrant,
        'direction_score': result.get('direction_score'),
        'vol_score': result.get('vol_score'),
        'direction_bias': dir_pref,
        'vol_bias': vol_pref,
        'confidence': confidence,
        'confidence_score': confidence_score,
        'confidence_notes': confidence_notes,
        'data_quality': data_quality,
        'data_quality_issues': data_quality_issues,
        'trade_permission': permission_info["trade_permission"],
        'permission_reasons': permission_info["permission_reasons"],
        'disabled_structures': permission_info["disabled_structures"],
        'liquidity': liquidity,
        'liquidity_score': liquidity_score,
        'liquidity_reasons': liquidity_reasons,
        'active_open_ratio': active_open_ratio,
        'total_oi': total_oi,
        'delta_oi_1d': delta_oi_1d,
        'delta_oi_pct': delta_oi_pct,
        'oi_turnover': oi_turnover,
        'oi_data_available': result.get('oi_data_available'),
        'flow_bias': notional_bias,
        'is_squeeze': is_squeeze,
        'squeeze_score': squeeze_score,
        'squeeze_reasons': squeeze_reasons,
        'is_index': symbol in INDEX_TICKERS,
        'days_to_earnings': days_to_earnings,
        'penalized_extreme_move_low_vol': penal_flag,
        'fear_regime': fear_flag,
        'fear_reasons': fear_reasons,
        'watch_triggers': watch_guidance.get("watch_triggers", []),
        'what_to_monitor': watch_guidance.get("what_to_monitor", []),
        'posture_5d': posture_info.get("posture_5d"),
        'posture_reasons': posture_info.get("posture_reasons"),
        'posture_reason_codes': posture_info.get("posture_reason_codes"),
        'posture_confidence': posture_info.get("posture_confidence"),
        'posture_inputs_snapshot': posture_info.get("posture_inputs_snapshot"),
        'posture_overlay_notes': posture_overlay_notes,
        'dir_slope_nd': result.get('dir_slope_nd'),
        'dir_trend_label': result.get('dir_trend_label'),
        'trend_days_used': result.get('trend_days_used'),
        'term_structure_label_code': term_structure_label_code,
        'term_structure_horizon_bias': term_structure_horizon_bias,
        'term_structure_dte_bias': term_structure_dte_bias,
    })
    
    micro_template = select_micro_template(bridge_payload, effective_cfg)
    
    # 同步权限到姿态 overlay 后
    permission_info["trade_permission"] = micro_template["trade_permission"]
    permission_info["permission_reasons"] = micro_template["permission_reasons"]
    permission_info["disabled_structures"] = micro_template["disabled_structures"]
    result['trade_permission'] = permission_info["trade_permission"]
    result['permission_reasons'] = permission_info["permission_reasons"]
    result['disabled_structures'] = permission_info["disabled_structures"]
    strategy_structures = get_strategy_structures(
        quadrant=quadrant,
        disabled_structures=permission_info["disabled_structures"],
        permission_reasons=permission_info["permission_reasons"],
        cfg=effective_cfg,
    )
    dte_bias = micro_template.get("dte_bias")
    if isinstance(dte_bias, str) and dte_bias and dte_bias != "neutral":
        for structure in strategy_structures:
            notes = list(structure.get("notes") or [])
            notes.append(f"DTE_BIAS:{dte_bias}")
            structure["notes"] = notes
    result['strategy_structures'] = strategy_structures
    bridge_payload.update({
        'trade_permission': permission_info["trade_permission"],
        'permission_reasons': permission_info["permission_reasons"],
        'disabled_structures': permission_info["disabled_structures"],
        'strategy_structures': strategy_structures,
    })
    
    bridge_snapshot = build_bridge_snapshot(bridge_payload, effective_cfg).to_dict()
    bridge_snapshot["micro_template"] = micro_template
    result['bridge'] = bridge_snapshot
    result['micro_template'] = micro_template
    
    # ============ 更新缓存 ============
    if effective_cfg.get("enable_dynamic_params", True) and dynamic_params and vix_value:
        try:
            cache = get_global_cache()
            update_cache_with_record(normed, vix_value, dynamic_params, cache)
        except Exception as e:
            print(f"⚠ Warning: Failed to update cache: {e}")
    
    return result
