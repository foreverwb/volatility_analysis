/**
 * 详情抽屉模块 - v2.5.0
 * ✨ NEW: 期限结构可视化展示
 */

/**
 * 显示详情抽屉
 */
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
    
    var spotVolCorr = record.spot_vol_corr_score || 0;
    var isSqueeze = record.is_squeeze || false;
    var termStructure = record.term_structure_ratio || 'N/A';
    
    var activeOpenRatio = record.active_open_ratio || 0;
    var consistency = record.consistency || 0;
    var structureFactor = record.structure_factor || 1.0;
    var flowBias = record.flow_bias || 0;
    
    var dynamicParams = record.dynamic_params || {};
    var hasDynamicParams = dynamicParams.enabled && dynamicParams.beta_t !== null;
    
    // ✨ NEW: 期限结构数据
    var termStructureData = record.term_structure || null;
    var termStructureColor = record.term_structure_color || '#8E8E93';
    
    var dirScore = record.direction_score;
    var volScore = record.vol_score;
    var dirColor = dirScore > 0 ? '#00C853' : (dirScore < 0 ? '#FF3B30' : '#9E9E9E');
    var volColor = volScore > 0 ? '#00C853' : (volScore < 0 ? '#FF3B30' : '#9E9E9E');
    var liquidityClass = getLiquidityClass(record.liquidity);

    var html = '<p class="timestamp">' + record.timestamp + '</p>';
    
    // ========== 核心结论区块 ==========
    html += '<div class="detail-section"><h3>核心结论</h3>';
    html += '<div class="detail-row"><div class="detail-label">四象限定位:</div><div class="detail-value"><strong><span class="record-quadrant ' + quadrantClass + '">' + record.quadrant + '</span></strong></div></div>';
    
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
    
    // ========== ✨ NEW: 期限结构分析区块 ==========
    if (termStructureData) {
        html += '<div class="detail-section term-structure-section">';
        html += '<h3>📊 期限结构分析</h3>';
        
        // 形态名称和信号
        html += '<div class="term-structure-header">';
        html += '<div class="term-structure-pattern" style="color: ' + termStructureColor + ';">';
        html += '<strong>' + termStructureData.pattern_name + '</strong>';
        html += '</div>';
        html += '<div class="term-structure-signal">';
        html += '<span class="signal-badge" style="background-color: ' + termStructureColor + '20; color: ' + termStructureColor + ';">';
        html += termStructureData.signal;
        html += '</span>';
        html += '<span class="confidence-badge ' + getBadgeClass(termStructureData.confidence) + '">';
        html += termStructureData.confidence + '置信';
        html += '</span>';
        html += '</div>';
        html += '</div>';
        
        // IV 曲线可视化
        html += '<div class="iv-curve-container">';
        html += renderIVCurve(termStructureData.iv_curve, termStructureData.curve_labels, termStructureColor);
        html += '</div>';
        
        // 斜率信息
        html += '<div class="slope-info">';
        html += '<div class="slope-item">';
        html += '<span class="slope-label">短期斜率 (7D→30D):</span>';
        html += '<span class="slope-value" style="color: ' + getSlopeColor(termStructureData.slopes.short) + ';">';
        html += formatSlope(termStructureData.slopes.short);
        html += '</span>';
        html += '</div>';
        html += '<div class="slope-item">';
        html += '<span class="slope-label">中期斜率 (30D→60D):</span>';
        html += '<span class="slope-value" style="color: ' + getSlopeColor(termStructureData.slopes.mid) + ';">';
        html += formatSlope(termStructureData.slopes.mid);
        html += '</span>';
        html += '</div>';
        html += '<div class="slope-item">';
        html += '<span class="slope-label">长期斜率 (60D→90D):</span>';
        html += '<span class="slope-value" style="color: ' + getSlopeColor(termStructureData.slopes.long) + ';">';
        html += formatSlope(termStructureData.slopes.long);
        html += '</span>';
        html += '</div>';
        html += '</div>';
    }
    
    // ========== 动态参数区块 ==========
    if (hasDynamicParams) {
        html += '<div class="detail-section"><h3>🎛️ 动态参数</h3>';
        
        if (dynamicParams.vix !== null) {
            var vixColor = dynamicParams.vix > 20 ? '#FF9500' : (dynamicParams.vix > 15 ? '#1890ff' : '#00C853');
            html += '<div class="detail-row"><div class="detail-label">VIX 指数:</div><div class="detail-value" style="color: ' + vixColor + '; font-weight: bold;">' + dynamicParams.vix + '</div></div>';
        }
        
        html += '<div class="detail-row"><div class="detail-label">βₜ (行为权重):</div><div class="detail-value">' + dynamicParams.beta_t + ' <span class="param-range">[0.20, 0.40]</span></div></div>';
        html += '<div class="detail-row"><div class="detail-label">λₜ (波动灵敏度):</div><div class="detail-value">' + dynamicParams.lambda_t + ' <span class="param-range">[0.35, 0.55]</span></div></div>';
        html += '<div class="detail-row"><div class="detail-label">αₜ (市场放大系数):</div><div class="detail-value">' + dynamicParams.alpha_t + ' <span class="param-range">[0.35, 0.60]</span></div></div>';
        
        html += '</div>';
    }
    
    // ========== 高级指标区块 ==========
    html += '<div class="detail-section"><h3>高级指标</h3>';
    html += '<div class="detail-row"><div class="detail-label">价-波相关性:</div><div class="detail-value">' + spotVolCorr.toFixed(2) + '</div></div>';
    html += '<div class="detail-row"><div class="detail-label">期限结构:</div><div class="detail-value">' + termStructure + '</div></div>';
    
    var aorColor = activeOpenRatio >= 0.05 ? '#00C853' : (activeOpenRatio <= -0.05 ? '#FF3B30' : '#9E9E9E');
    var aorLabel = activeOpenRatio >= 0.05 ? '(新建仓)' : (activeOpenRatio <= -0.05 ? '(平仓信号)' : '(中性)');
    html += '<div class="detail-row"><div class="detail-label">📊 主动开仓比:</div><div class="detail-value" style="color: ' + aorColor + '; font-weight: bold;">' + activeOpenRatio.toFixed(4) + ' ' + aorLabel + '</div></div>';
    
    var consColor = consistency > 0.6 ? '#00C853' : (consistency < -0.6 ? '#FF3B30' : '#9E9E9E');
    var consLabel = consistency > 0.6 ? '(趋势持续)' : (consistency < -0.6 ? '(趋势反转)' : '(无明确趋势)');
    html += '<div class="detail-row"><div class="detail-label">📈 跨期一致性:</div><div class="detail-value" style="color: ' + consColor + '; font-weight: bold;">' + consistency.toFixed(3) + ' ' + consLabel + '</div></div>';
    
    var sfLabel = structureFactor > 1 ? '(单边趋势主导)' : (structureFactor < 1 ? '(对冲/联动交易)' : '(正常)');
    html += '<div class="detail-row"><div class="detail-label">🏗️ 结构因子:</div><div class="detail-value">' + structureFactor.toFixed(2) + ' ' + sfLabel + '</div></div>';
    
    var fbColor = flowBias > 0.2 ? '#00C853' : (flowBias < -0.2 ? '#FF3B30' : '#9E9E9E');
    html += '<div class="detail-row"><div class="detail-label">💰 资金流偏向:</div><div class="detail-value" style="color: ' + fbColor + ';">' + flowBias.toFixed(3) + '</div></div>';
    html += '</div>';

    // ========== 衍生指标区块 ==========
    html += '<div class="detail-section"><h3>衍生指标</h3>';
    if (record.derived_metrics) {
        html += '<div class="detail-row"><div class="detail-label">IVRV 比值:</div><div class="detail-value">' + record.derived_metrics.ivrv_ratio + '</div></div>';
        html += '<div class="detail-row"><div class="detail-label">IVRV 差值:</div><div class="detail-value">' + record.derived_metrics.ivrv_diff + '</div></div>';
        html += '<div class="detail-row"><div class="detail-label">Call/Put 比值:</div><div class="detail-value">' + record.derived_metrics.cp_ratio + '</div></div>';
        html += '<div class="detail-row"><div class="detail-label">Regime 比值:</div><div class="detail-value">' + record.derived_metrics.regime_ratio + '</div></div>';
    }
    html += '</div>';
    
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

/**
 * ✨ NEW: 渲染 IV 曲线
 */
function renderIVCurve(ivCurve, labels, color) {
    if (!ivCurve || ivCurve.length === 0) {
        return '<p class="no-data">数据不足</p>';
    }
    
    // 找到最小和最大值用于归一化
    var minIV = Math.min.apply(null, ivCurve);
    var maxIV = Math.max.apply(null, ivCurve);
    var range = maxIV - minIV;
    
    // 如果范围太小，固定高度
    if (range < 1) {
        range = 10;
        minIV = Math.max(0, maxIV - 10);
    }
    
    var html = '<div class="iv-curve-chart">';
    
    // 绘制点和连线
    html += '<svg class="iv-curve-svg" viewBox="0 0 400 150" preserveAspectRatio="xMidYMid meet">';
    
    // 计算点的位置
    var points = [];
    var xStep = 400 / (ivCurve.length - 1);
    
    for (var i = 0; i < ivCurve.length; i++) {
        var x = i * xStep;
        var normalized = (ivCurve[i] - minIV) / range;
        var y = 120 - (normalized * 100); // 反转 Y 轴，上方为高值
        points.push({x: x, y: y, iv: ivCurve[i], label: labels[i]});
    }
    
    // 绘制连线
    var pathData = 'M ' + points[0].x + ' ' + points[0].y;
    for (var i = 1; i < points.length; i++) {
        pathData += ' L ' + points[i].x + ' ' + points[i].y;
    }
    
    html += '<path d="' + pathData + '" fill="none" stroke="' + color + '" stroke-width="2"/>';
    
    // 绘制点
    for (var i = 0; i < points.length; i++) {
        var point = points[i];
        html += '<circle cx="' + point.x + '" cy="' + point.y + '" r="4" fill="' + color + '"/>';
        
        // 标签
        html += '<text x="' + point.x + '" y="140" text-anchor="middle" font-size="12" fill="#666">' + point.label + '</text>';
        
        // IV 值
        html += '<text x="' + point.x + '" y="' + (point.y - 10) + '" text-anchor="middle" font-size="11" font-weight="bold" fill="' + color + '">' + point.iv.toFixed(1) + '%</text>';
    }
    
    html += '</svg>';
    html += '</div>';
    
    return html;
}

/**
 * ✨ NEW: 获取斜率颜色
 */
function getSlopeColor(slope) {
    if (slope > 2) return '#00C853';      // 绿色 - 正斜率
    if (slope < -2) return '#FF3B30';     // 红色 - 负斜率（倒挂）
    return '#8E8E93';                      // 灰色 - 平坦
}

/**
 * ✨ NEW: 格式化斜率
 */
function formatSlope(slope) {
    var sign = slope >= 0 ? '+' : '';
    var arrow = slope > 2 ? ' ↗' : (slope < -2 ? ' ↘' : ' →');
    return sign + slope.toFixed(2) + '%' + arrow;
}

// 导出到全局
window.showDrawer = showDrawer;
window.renderIVCurve = renderIVCurve;
window.getSlopeColor = getSlopeColor;
window.formatSlope = formatSlope;