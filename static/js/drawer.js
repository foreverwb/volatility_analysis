/**
 * 详情抽屉模块 - v2.3.3
 * 新增动态参数展示
 */

/**
 * 显示详情抽屉
 */
function formatTermStructure(rawValue, record) {
    if (!rawValue || rawValue === 'N/A') return 'N/A';
    if (rawValue.includes('(')) {
        return buildTermStructureDisplay(rawValue, record);
    }

    var shortMatch = rawValue.match(/7\/30\s+([0-9.]+)/);
    var midMatch = rawValue.match(/30\/60\s+([0-9.]+)/);
    var longMatch = rawValue.match(/60\/90\s+([0-9.]+)/);
    if (!shortMatch || !midMatch || !longMatch) return rawValue;

    var short = parseFloat(shortMatch[1]);
    var mid = parseFloat(midMatch[1]);
    var long = parseFloat(longMatch[1]);
    if (isNaN(short) || isNaN(mid) || isNaN(long)) return rawValue;

    var label = classifyTermStructure(short, mid, long);
    return buildTermStructureDisplay(label + ' | ' + rawValue, record);
}

function classifyTermStructure(short, mid, long) {
    if (short > 1.05 && mid > 1.05 && long > 1.05) {
        return '全面倒挂 (Full inversion)';
    }
    if (short > 1.05 && mid <= 1.0) {
        return '短期倒挂 (Short-term inversion)';
    }
    if (mid > 1.05 && short <= 1.02 && long <= 1.0) {
        return '中期突起 (Mid-term bulge)';
    }
    if (long > 1.05 && mid <= 1.0) {
        return '远期过高 (Far-term elevated)';
    }
    if (short < 0.9 && mid >= 0.95) {
        return '短期低位 (Short-term low)';
    }
    if (short < 1.0 && mid < 1.0 && long < 1.0) {
        return '正常陡峭 (Normal steep)';
    }
    return '正常陡峭 (Normal steep)';
}

function buildTermStructureDisplay(rawValue, record) {
    var parts = rawValue.split(' | ');
    if (parts.length < 2) return rawValue;

    var label = parts[0];
    var baseRatio = parts[1];
    var ivLine = buildIvLine(record);

    return label + '<br>' + baseRatio + '<br>' + ivLine;
}

function buildIvLine(record) {
    var raw = (record && record.raw_data) ? record.raw_data : {};
    var iv7 = readIvValue(record, raw, 'IV7');
    var iv30 = readIvValue(record, raw, 'IV30');
    var iv60 = readIvValue(record, raw, 'IV60');
    var iv90 = readIvValue(record, raw, 'IV90');

    if (iv7 === null && iv30 === null && iv60 === null && iv90 === null) {
        return 'IV7 N/A | IV30 N/A | IV60 N/A | IV90 N/A';
    }

    return 'IV7 ' + formatIvValue(iv7) +
        ' | IV30 ' + formatIvValue(iv30) +
        ' | IV60 ' + formatIvValue(iv60) +
        ' | IV90 ' + formatIvValue(iv90);
}

function readIvValue(record, raw, key) {
    if (record && record[key] !== undefined && record[key] !== null) {
        return record[key];
    }
    if (raw && raw[key] !== undefined && raw[key] !== null) {
        return raw[key];
    }
    return null;
}

function formatIvValue(value) {
    if (value === null || value === undefined) return 'N/A';
    var num = parseFloat(value);
    if (isNaN(num)) return 'N/A';
    return num.toFixed(2);
}

function formatMaybeNumber(value, digits) {
    if (value === null || value === undefined) return 'N/A';
    var num = Number(value);
    if (isNaN(num)) return 'N/A';
    return num.toFixed(digits);
}

function showDrawer(timestamp, symbol) {
    var record = AppState.allRecords.find(function(r) {
        return r.timestamp === timestamp && r.symbol === symbol;
    });
    
    if (!record) return;
    
    var eventBadge = record.earnings_event_enabled ? ' <span class="earnings-badge">E</span>' : '';
    var typeBadge = record.is_index ? ' <span class="badge-type">ETF</span>' : '';
    document.getElementById('detailDrawerTitle').innerHTML = record.symbol + eventBadge + typeBadge + ' - 详细分析';
    
    var confidenceBadge = getBadgeClass(record.confidence);
    var quadrantClass = getQuadrantClass(record.quadrant);
    var daysToEarnings = record.derived_metrics ? record.derived_metrics.days_to_earnings : null;
    var showEarnings = daysToEarnings !== null && 
                  daysToEarnings > 0 && 
                  daysToEarnings <= AppState.earningsDisplayThreshold;
    
    // 高级指标数据
    var spotVolCorr = record.spot_vol_corr_score || 0;
    var isSqueeze = record.is_squeeze || false;
    var termStructure = formatTermStructure(record.term_structure_ratio || 'N/A', record);
    
    // v2.3.2 字段
    var activeOpenRatio = record.active_open_ratio || 0;
    var consistency = record.consistency || 0;
    var structureFactor = record.structure_factor || 1.0;
    var flowBias = record.flow_bias || 0;
    var dirSlope = Number(record.dir_slope_nd || 0);
    var dirTrendLabel = record.dir_trend_label || '横盘';
    var trendDaysUsed = Number(record.trend_days_used || 0);
    
    // 🟩 v2.3.3: 动态参数
    var dynamicParams = record.dynamic_params || {};
    var hasDynamicParams = dynamicParams.enabled && dynamicParams.beta_t !== null;
    var scoreBreakdown = record.score_breakdown || {};
    var confidenceBreakdown = record.confidence_breakdown || {};
    
    var dirScore = record.direction_score;
    var volScore = record.vol_score;
    var dirColor = dirScore > 0 ? '#00C853' : (dirScore < 0 ? '#FF3B30' : '#9E9E9E');
    var volColor = volScore > 0 ? '#00C853' : (volScore < 0 ? '#FF3B30' : '#9E9E9E');
    var liquidityClass = getLiquidityClass(record.liquidity);

    var html = '<p class="timestamp">' + record.timestamp + '</p>';
    
    // ========== 核心结论区块 ==========
    html += '<div class="detail-section"><h3>核心结论</h3>';
    html += '<div class="detail-row"><div class="detail-label">四象限定位:</div><div class="detail-value"><strong><span class="record-quadrant ' + quadrantClass + '">' + record.quadrant + '</span></strong></div></div>';
    
    // Gamma 挤压
    if (isSqueeze) {
        html += '<div class="detail-row"><div class="detail-label">特殊状态:</div><div class="detail-value"><span class="badge-squeeze">🚀 GAMMA SQUEEZE DETECTED</span></div></div>';
    }
    
    html += '<div class="detail-row"><div class="detail-label">置信度:</div><div class="detail-value"><span class="badge ' + confidenceBadge + ' detail-value-highlight">' + record.confidence + '</span></div></div>';
    html += '<div class="detail-row"><div class="detail-label">流动性:</div><div class="detail-value"><span class="detail-value-liquidity ' + liquidityClass + '">' + record.liquidity + '</span></div></div>';
    
    if (showEarnings) {
        html += '<div class="detail-row"><div class="detail-label">距离财报:</div><div class="detail-value">' + daysToEarnings + ' 天</div></div>';
    }
    
    html += '<div class="detail-row"><div class="detail-label">方向评分:</div><div class="detail-value" style="color: ' + dirColor + '; font-weight: bold;">' + record.direction_score + ' (' + record.direction_bias + ')</div></div>';
    html += '<div class="detail-row"><div class="detail-label">波动评分:</div><div class="detail-value" style="color: ' + volColor + '; font-weight: bold;">' + record.vol_score + ' (' + record.vol_bias + ')</div></div></div>';

    // ========== 🟩 v2.3.3: 动态参数区块 ==========
    if (hasDynamicParams) {
        html += '<div class="detail-section"><h3>🎛️ 动态参数</h3>';
        
        // VIX
        if (dynamicParams.vix !== null) {
            var vixColor = dynamicParams.vix > 20 ? '#FF9500' : (dynamicParams.vix > 15 ? '#1890ff' : '#00C853');
            html += '<div class="detail-row"><div class="detail-label">VIX 指数:</div><div class="detail-value" style="color: ' + vixColor + '; font-weight: bold;">' + dynamicParams.vix + '</div></div>';
        }
        
        // βₜ (行为层)
        html += '<div class="detail-row"><div class="detail-label">βₜ (行为权重):</div><div class="detail-value">' + dynamicParams.beta_t + ' <span class="param-range">[0.20, 0.40]</span></div></div>';
        
        // λₜ (波动层)
        html += '<div class="detail-row"><div class="detail-label">λₜ (波动灵敏度):</div><div class="detail-value">' + dynamicParams.lambda_t + ' <span class="param-range">[0.35, 0.55]</span></div></div>';
        
        // αₜ (市场层)
        html += '<div class="detail-row"><div class="detail-label">αₜ (市场放大系数):</div><div class="detail-value">' + dynamicParams.alpha_t + ' <span class="param-range">[0.35, 0.60]</span></div></div>';
        
        html += '</div>';
    }
    
    // ========== v2.3.2: 高级量化指标区块 ==========
    html += '<div class="detail-section"><h3>高级指标</h3>';
    html += '<div class="detail-row"><div class="detail-label">价-波相关性:</div><div class="detail-value">' + spotVolCorr.toFixed(2) + '</div></div>';
    html += '<div class="detail-row"><div class="detail-label">期限结构:</div><div class="detail-value">' + termStructure + '</div></div>';
    
    // ActiveOpenRatio
    var aorColor = activeOpenRatio >= 0.05 ? '#00C853' : (activeOpenRatio <= -0.05 ? '#FF3B30' : '#9E9E9E');
    var aorLabel = activeOpenRatio >= 0.05 ? '(新建仓)' : (activeOpenRatio <= -0.05 ? '(平仓信号)' : '(中性)');
    html += '<div class="detail-row"><div class="detail-label">📊 主动开仓比:</div><div class="detail-value" style="color: ' + aorColor + '; font-weight: bold;">' + activeOpenRatio.toFixed(4) + ' ' + aorLabel + '</div></div>';
    
    // Consistency
    var consColor = consistency > 0.6 ? '#00C853' : (consistency < -0.6 ? '#FF3B30' : '#9E9E9E');
    var consLabel = consistency > 0.6 ? '(趋势持续)' : (consistency < -0.6 ? '(趋势反转)' : '(无明确趋势)');
    html += '<div class="detail-row"><div class="detail-label">📈 跨期一致性:</div><div class="detail-value" style="color: ' + consColor + '; font-weight: bold;">' + consistency.toFixed(3) + ' ' + consLabel + '</div></div>';

    // 方案B: 数值斜率趋势叠加
    var slopeColor = dirTrendLabel === '上行' ? '#00C853' : (dirTrendLabel === '下行' ? '#FF3B30' : '#9E9E9E');
    html += '<div class="detail-row"><div class="detail-label">📐 斜率趋势:</div><div class="detail-value" style="color: ' + slopeColor + '; font-weight: bold;">' + dirTrendLabel + ' (' + dirSlope.toFixed(3) + ') · 样本' + trendDaysUsed + '天</div></div>';
    
    // Structure Factor
    var sfLabel = structureFactor > 1 ? '(单边趋势主导)' : (structureFactor < 1 ? '(对冲/联动交易)' : '(正常)');
    html += '<div class="detail-row"><div class="detail-label">🏗️ 结构因子:</div><div class="detail-value">' + structureFactor.toFixed(2) + ' ' + sfLabel + '</div></div>';
    
    // Flow Bias
    var fbColor = flowBias > 0.2 ? '#00C853' : (flowBias < -0.2 ? '#FF3B30' : '#9E9E9E');
    html += '<div class="detail-row"><div class="detail-label">💰 资金流偏向:</div><div class="detail-value" style="color: ' + fbColor + ';">' + flowBias.toFixed(3) + '</div></div>';
    html += '</div>';

    // ========== 衍生指标区块 ==========
    html += '<div class="detail-section"><h3>衍生指标</h3>';
    if (record.derived_metrics) {
        html += '<div class="detail-row"><div class="detail-label">IVRV 比值:</div><div class="detail-value">' + formatMaybeNumber(record.derived_metrics.ivrv_ratio, 3) + '</div></div>';
        html += '<div class="detail-row"><div class="detail-label">IVRV 差值:</div><div class="detail-value">' + formatMaybeNumber(record.derived_metrics.ivrv_diff, 2) + '</div></div>';
        html += '<div class="detail-row"><div class="detail-label">Call/Put 比值:</div><div class="detail-value">' + formatMaybeNumber(record.derived_metrics.cp_ratio, 3) + '</div></div>';
        html += '<div class="detail-row"><div class="detail-label">Regime 比值:</div><div class="detail-value">' + formatMaybeNumber(record.derived_metrics.regime_ratio, 3) + '</div></div>';
    }
    html += '</div>';

    // ========== v2.4: 评分与置信度分解（审计关键字段） ==========
    if (scoreBreakdown && (scoreBreakdown.direction || scoreBreakdown.volatility)) {
        var dirNorm = scoreBreakdown.direction ? scoreBreakdown.direction.normalized_score : null;
        var volNorm = scoreBreakdown.volatility ? scoreBreakdown.volatility.normalized_score : null;
        var dirAdj = scoreBreakdown.direction && scoreBreakdown.direction.adjustment ? scoreBreakdown.direction.adjustment.factor : null;
        var volAdj = scoreBreakdown.volatility && scoreBreakdown.volatility.adjustment ? scoreBreakdown.volatility.adjustment.factor : null;
        html += '<div class="detail-section"><h3>评分分解 (score_breakdown)</h3>';
        html += '<div class="detail-row"><div class="detail-label">方向基础分:</div><div class="detail-value">' + formatMaybeNumber(dirNorm, 3) + '</div></div>';
        html += '<div class="detail-row"><div class="detail-label">方向调整系数:</div><div class="detail-value">' + formatMaybeNumber(dirAdj, 3) + '</div></div>';
        html += '<div class="detail-row"><div class="detail-label">波动基础分:</div><div class="detail-value">' + formatMaybeNumber(volNorm, 3) + '</div></div>';
        html += '<div class="detail-row"><div class="detail-label">波动调整系数:</div><div class="detail-value">' + formatMaybeNumber(volAdj, 3) + '</div></div>';
        html += '</div>';
    }

    if (confidenceBreakdown && confidenceBreakdown.components) {
        var comps = confidenceBreakdown.components;
        html += '<div class="detail-section"><h3>置信度分解 (confidence_breakdown)</h3>';
        html += '<div class="detail-row"><div class="detail-label">总置信度:</div><div class="detail-value">' + (confidenceBreakdown.confidence_label || record.confidence || 'N/A') + ' (' + formatMaybeNumber(confidenceBreakdown.confidence_score, 3) + ')</div></div>';
        html += '<div class="detail-row"><div class="detail-label">数据置信度:</div><div class="detail-value">' + (confidenceBreakdown.data_confidence || 'N/A') + '</div></div>';
        html += '<div class="detail-row"><div class="detail-label">strength:</div><div class="detail-value">' + formatMaybeNumber(comps.strength_confidence && comps.strength_confidence.score, 3) + '</div></div>';
        html += '<div class="detail-row"><div class="detail-label">execution:</div><div class="detail-value">' + formatMaybeNumber(comps.execution_confidence && comps.execution_confidence.score, 3) + '</div></div>';
        html += '<div class="detail-row"><div class="detail-label">consistency:</div><div class="detail-value">' + formatMaybeNumber(comps.consistency_confidence && comps.consistency_confidence.score, 3) + '</div></div>';
        html += '</div>';
    }
    
    // ========== 方向驱动因素区块 ==========
    html += '<div class="detail-section"><h3>方向驱动因素</h3><ul class="factor-list">';
    if (record.direction_factors) {
        record.direction_factors.forEach(function(f) { html += '<li>' + f + '</li>'; });
    }
    html += '</ul></div>';
    
    // ========== 波动驱动因素区块 ==========
    html += '<div class="detail-section"><h3>波动驱动因素</h3><ul class="factor-list">';
    if (record.vol_factors) {
        record.vol_factors.forEach(function(f) { html += '<li>' + f + '</li>'; });
    }
    html += '</ul></div>';
    
    document.getElementById('detailDrawerContent').innerHTML = html;
    openDetailDrawer();
}

// 导出到全局
window.showDrawer = showDrawer;
