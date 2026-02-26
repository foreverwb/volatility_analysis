/**
 * 记录列表渲染模块
 *  - 支持新增字段显示
 */

/**
 * 获取象限 CSS 类
 */
function getQuadrantClass(quadrant) {
    if (quadrant.includes('偏多') && quadrant.includes('买波')) {
        return 'quad-bull-buy';
    } else if (quadrant.includes('偏多') && quadrant.includes('卖波')) {
        return 'quad-bull-sell';
    } else if (quadrant.includes('偏空') && quadrant.includes('买波')) {
        return 'quad-bear-buy';
    } else if (quadrant.includes('偏空') && quadrant.includes('卖波')) {
        return 'quad-bear-sell';
    } else if (quadrant.includes('中性')) {
        return 'quad-neutral';
    }
    return '';
}

/**
 * 获取流动性 CSS 类
 */
function getLiquidityClass(liquidity) {
    if (liquidity === '高') return 'liquidity-high';
    if (liquidity === '中') return 'liquidity-medium';
    if (liquidity === '低') return 'liquidity-low';
    return '';
}

/**
 * 获取置信度 Badge CSS 类
 */
function getBadgeClass(confidence) {
    if (confidence === '高') return 'badge-high';
    if (confidence === '中') return 'badge-medium';
    return 'badge-low';
}

/**
 * 根据内容高度设置展开/收起的 max-height，避免长列表被截断
 */
function setDateContentHeight(content, expanded) {
    if (!content) return;
    content.style.maxHeight = expanded ? (content.scrollHeight + 'px') : '0px';
}

/**
 * 渲染记录列表
 */
function renderRecordsList() {
    var container = document.getElementById('recordsList');
    
    if (!AppState.allRecords || AppState.allRecords.length === 0) {
        container.innerHTML = '<div class="empty-state">暂无数据,请先提交分析</div>';
        return;
    }
    
    // 先进行标的筛选
    var filteredRecords = filterBySymbol(AppState.allRecords);
    filteredRecords = filterBySlope(filteredRecords);
    
    var groupedByDate = {};
    filteredRecords.forEach(function(record) {
        var date = record.timestamp.split(' ')[0];
        if (AppState.currentFilter && date !== AppState.currentFilter) return;
        if (!groupedByDate[date]) groupedByDate[date] = [];
        groupedByDate[date].push(record);
    });
    
    // 象限筛选
    if (!AppState.selectedQuadrants.includes('全部')) {
        for (var date in groupedByDate) {
            groupedByDate[date] = groupedByDate[date].filter(function(record) {
                var quadrant = record.quadrant || '';
                if (AppState.selectedQuadrants.includes(quadrant)) return true;
                var normalizedQuadrant = quadrant.replace(/—/g, '--');
                return AppState.selectedQuadrants.some(function(selected) {
                    var normalizedSelected = selected.replace(/—/g, '--');
                    return normalizedQuadrant === normalizedSelected;
                });
            });
            if (groupedByDate[date].length === 0) delete groupedByDate[date];
        }
    }
    
    // 对每个日期组内的记录进行排序
    for (var date in groupedByDate) {
        groupedByDate[date] = sortRecords(groupedByDate[date]);
    }

    var sortedDates = Object.keys(groupedByDate).sort().reverse();
    
    if (sortedDates.length === 0) {
        container.innerHTML = '<div class="empty-state">没有符合条件的数据</div>';
        return;
    }
    
    var html = '';
    sortedDates.forEach(function(date) {
        var records = groupedByDate[date];
        var count = records.length;
        var isExpanded = AppState.expandedDates.has(date);
        
        html += '<div class="date-group" data-date="' + date + '">';
        html += '<div class="date-header sticky" data-date="' + date + '">';
        html += '<div class="date-title">';
        html += '<span class="date-toggle ' + (isExpanded ? 'expanded' : '') + '" id="toggle-' + date + '">▼</span>';
        html += '<span>' + date + ' (' + count + '条)</span>';
        html += '</div>';
        html += '<div class="date-actions">';
        html += '<div class="earnings-toggle">';
        html += '<label class="switch">';
        var isChecked = AppState.earningsToggles[date] ? 'checked' : '';
        html += '<input type="checkbox" class="earnings-checkbox" data-date="' + date + '" ' + isChecked + '>';
        html += '<span class="slider"><span class="slider-text open">E-ON</span><span class="slider-text close">E-OFF</span></span></label></div>';
        
        // 重绘按钮
        html += '<button class="icon-btn" data-date="' + date + '" data-action="redraw" title="重绘">';
        html += '<svg class="icon" viewBox="0 0 1024 1024" width="16" height="16"><path d="M242.27 421.75v131.84c0 12.1 8.41 23.29 20.56 25.21a24.541 24.541 0 0 0 28.82-23.89v-71.86c0-7.72 6.38-13.97 14.23-13.97 7.88 0 14.26 6.25 14.26 13.97v42.32c0 12.1 8.38 23.27 20.53 25.21 7.11 1.26 14.4-0.67 19.96-5.27 5.55-4.6 8.81-11.41 8.89-18.62v-43.63c0-7.72 6.37-13.97 14.21-13.97 7.88 0 14.26 6.25 14.26 13.97v19.82c0 7.98 6.59 14.47 14.71 14.47 8.12 0 14.71-6.49 14.71-14.47v-15.1c0-10.32 8.53-18.69 19.03-18.69h10.35c10.49 0 19.02 8.36 19.02 18.69 0 13.39 11.05 24.25 24.7 24.25 13.64 0 24.68-10.86 24.68-24.25v-18.69h177.29v-71.88H242.27v24.54z" fill="#FFB74D"></path><path d="M744.88 271.25h-17.81v50.82h17.81c14.28 0 25.88 11.43 25.88 25.42v137.3c0 14.02-11.59 25.42-25.88 25.42H607.15c-42.82 0-77.64 34.19-77.64 76.24v24.56h51.76v-24.56c0-14.02 11.6-25.45 25.88-25.45h137.73c42.79 0 77.63-34.17 77.63-76.22V347.5c0-42.06-34.84-76.25-77.63-76.25z" fill="#607D8B"></path><path d="M503.61 757.16c-5.2 31.29 19.45 59.73 51.75 59.73s56.93-28.46 51.71-59.73l-21.56-130.11H525.2l-21.59 130.11z" fill="#EB6C57"></path><path d="M245.79 386.24c-1.25 0-2.33-0.55-3.52-0.72v11.64h460.29v-11.64c-1.22 0.14-2.3 0.72-3.55 0.72H245.79z" fill="#FB8C00"></path><path d="M727.07 235.19c0-15.5-12.55-28.08-28.08-28.08h-453.2c-15.5 0-28.08 12.58-28.08 28.08v122.97c0 14.25 10.78 25.57 24.54 27.39 1.2 0.17 2.28 0.72 3.52 0.72h453.2c1.27 0 2.35-0.55 3.55-0.72 13.91-1.65 24.42-13.38 24.51-27.39V235.19h0.04z" fill="#FFB74D"></path></svg></button>';
        
        // 删除按钮
        html += '<button class="icon-btn delete-all" data-date="' + date + '" data-action="delete" title="全部删除">';
        html += '<svg class="icon" viewBox="0 0 1024 1024" width="16" height="16"><path d="M512 311.893333m-178.773333 0a178.773333 178.773333 0 1 0 357.546666 0 178.773333 178.773333 0 1 0-357.546666 0Z" fill="#FF354A"></path><path d="M746.666667 890.88H277.333333c-47.146667 0-85.333333-38.186667-85.333333-85.333333v-384c0-47.146667 38.186667-85.333333 85.333333-85.333334h469.333334c47.146667 0 85.333333 38.186667 85.333333 85.333334v384c0 47.146667-38.186667 85.333333-85.333333 85.333333z" fill="#2953FF"></path><path d="M345.386667 708.48v-149.333333a53.333333 53.333333 0 0 1 106.666666 0v149.333333a53.333333 53.333333 0 0 1-106.666666 0zM571.946667 708.48v-149.333333a53.333333 53.333333 0 0 1 106.666666 0v149.333333a53.333333 53.333333 0 0 1-106.666666 0z" fill="#93A8FF"></path><path d="M857.813333 397.226667H166.186667C133.333333 397.226667 106.666667 370.56 106.666667 337.706667v-8.746667c0-32.853333 26.666667-59.52 59.52-59.52H857.6c32.853333 0 59.52 26.666667 59.52 59.52v8.746667a59.221333 59.221333 0 0 1-59.306667 59.52z" fill="#FCCA1E"></path></svg></button>';
        html += '</div></div>';
        html += '<div class="date-content ' + (isExpanded ? 'expanded' : '') + '" id="content-' + date + '">';
        
        records.forEach(function(record) {
            var quadrantClass = getQuadrantClass(record.quadrant);
            var daysToEarnings = record.derived_metrics ? record.derived_metrics.days_to_earnings : null;
            var showEarnings = daysToEarnings !== null && 
                  daysToEarnings > 0 && 
                  daysToEarnings <= AppState.earningsDisplayThreshold;
            var eventBadge = record.earnings_event_enabled ? '<span class="earnings-badge">E</span>' : '';
            
            //  新增标记
            var isSqueeze = record.is_squeeze || false;
            var isIndex = record.is_index || false;
            var squeezeBadge = isSqueeze ? '<span class="badge-squeeze">🚀 Squeeze</span>' : '';
            var typeBadge = isIndex ? '<span class="badge-type">Index</span>' : '';
            
            //  新增: ActiveOpenRatio 标记
            var activeOpenRatio = record.active_open_ratio || 0;
            var aorBadge = '';
            if (activeOpenRatio >= 0.05) {
                aorBadge = '<span class="badge-aor-bull">📈 开仓</span>';
            } else if (activeOpenRatio <= -0.05) {
                aorBadge = '<span class="badge-aor-bear">📉 平仓</span>';
            }

            // v2.4: 数据缺失标记
            var missingCount = Array.isArray(record.missing_features) ? record.missing_features.length : 0;
            var missingBadge = missingCount > 0
                ? '<span style="display:inline-block;margin-left:4px;padding:1px 6px;border-radius:10px;background:#fff3e0;color:#ad6800;font-size:11px;">缺失:' + missingCount + '</span>'
                : '';
            
            //  新增: 跨期一致性标记
            var consistency = record.consistency || 0;
            var consistencyBadge = '';
            if (consistency > 0.6) {
                consistencyBadge = '<span class="badge-consistency-bull">🔥 趋势</span>';
            } else if (consistency < -0.6) {
                consistencyBadge = '<span class="badge-consistency-bear">❄️ 反转</span>';
            }

            // 方案B: 数值斜率趋势标记（前端可视化）
            var trendLabel = record.dir_trend_label || '横盘';
            var trendDaysUsed = Number(record.trend_days_used || 0);
            var dirSlope = Number(record.dir_slope_nd || 0);
            var slopeBadge = '';
            var slopeClass = trendLabel === '上行' ? 'badge-slope-up' : (trendLabel === '下行' ? 'badge-slope-down' : 'badge-slope-flat');
            if (record.dir_trend_label !== undefined || record.dir_slope_nd !== undefined) {
                slopeBadge = '<span class="' + slopeClass + '" title="基于最近' + trendDaysUsed + '天方向评分线性斜率">斜率:' + trendLabel + ' (' + dirSlope.toFixed(3) + ')</span>';
            }

            var dirScore = record.direction_score;
            var volScore = record.vol_score;
            var dirColor = dirScore > 0 ? '#00C853' : (dirScore < 0 ? '#FF3B30' : '#9E9E9E');
            var volColor = volScore > 0 ? '#00C853' : (volScore < 0 ? '#FF3B30' : '#9E9E9E');
            
            var confidenceBadge = getBadgeClass(record.confidence);
            var liquidityClass = getLiquidityClass(record.liquidity);

            html += '<div class="record-item" data-timestamp="' + record.timestamp + '" data-symbol="' + record.symbol + '">';
            html += '<div class="record-info">';
            html += '<div class="record-symbol">' + record.symbol + eventBadge + typeBadge + squeezeBadge + aorBadge + consistencyBadge + slopeBadge + missingBadge + '</div>';
            html += '<div class="record-meta">';
            html += '<span class="record-quadrant ' + quadrantClass + '">' + record.quadrant + '</span>';
            html += '<span class="record-confidence">置信度: <span class="badge ' + confidenceBadge + '">' + record.confidence + '</span></span>';
            html += '<span class="record-liquidity ' + liquidityClass + '">流动性: ' + record.liquidity + '</span>';
            
            html += '<span class="record-score-dir" style="color: ' + dirColor + ';">方向: ' + dirScore + '</span>';
            html += '<span class="record-score-vol" style="color: ' + volColor + ';">波动: ' + volScore + '</span>';
            
            if (showEarnings) {
                html += '<span class="record-earnings">财报: ' + daysToEarnings + '天</span>';
            }
            html += '</div></div>';
            html += '<button class="btn-delete-item" data-timestamp="' + record.timestamp + '" data-symbol="' + record.symbol + '">&times;</button>';
            html += '</div>';
        });
        
        html += '</div></div>';
    });
    
    container.innerHTML = html;
    
    // 渲染后同步各日期块高度，防止条目过多时被 max-height 截断
    sortedDates.forEach(function(date) {
        var content = document.getElementById('content-' + date);
        var expanded = AppState.expandedDates.has(date);
        setDateContentHeight(content, expanded);
    });
    
    container.addEventListener('click', handleRecordsListClick);
}

/**
 * 处理记录列表点击事件
 */
function handleRecordsListClick(e) {
    var target = e.target;
    
    var dateHeader = target.closest('.date-header');
    if (dateHeader) {
        var date = dateHeader.getAttribute('data-date');
        if (date && !target.closest('.date-actions')) {
            toggleDateGroup(date);
            return;
        }
    }
    
    var iconBtn = target.closest('.icon-btn');
    if (iconBtn) {
        e.stopPropagation();
        var date = iconBtn.getAttribute('data-date');
        var action = iconBtn.getAttribute('data-action');
        
        if (action === 'redraw') {
            redrawDate(e, date);
        } else if (action === 'delete') {
            deleteAllByDate(e, date);
        }
        return;
    }
    
    var recordItem = target.closest('.record-item');
    if (recordItem && !target.classList.contains('btn-delete-item')) {
        window.showDrawer(recordItem.getAttribute('data-timestamp'), recordItem.getAttribute('data-symbol'));
        return;
    }
    
    if (target.classList.contains('btn-delete-item')) {
        e.stopPropagation();
        deleteRecord(e, target.getAttribute('data-timestamp'), target.getAttribute('data-symbol'));
        return;
    }
    
    if (target.classList.contains('earnings-checkbox')) {
        e.stopPropagation();
        handleEarningsToggle(target);
        return;
    }
}

/**
 * 切换日期组展开/收起
 */
function toggleDateGroup(date) {
    var content = document.getElementById('content-' + date);
    var toggle = document.getElementById('toggle-' + date);
    
    if (!content || !toggle) return;
    
    if (content.classList.contains('expanded')) {
        content.classList.remove('expanded');
        toggle.classList.remove('expanded');
        setDateContentHeight(content, false);
        AppState.expandedDates.delete(date);
    } else {
        content.classList.add('expanded');
        toggle.classList.add('expanded');
        setDateContentHeight(content, true);
        AppState.expandedDates.add(date);
    }
}

/**
 * 重绘指定日期的数据
 */
function redrawDate(event, date) {
    event.stopPropagation();
    
    var dateRecords = AppState.allRecords.filter(function(r) {
        return r.timestamp.startsWith(date);
    });
    
    if (dateRecords.length === 0) {
        showMessage('该日期没有数据', 'error');
        return;
    }
    
    var filteredDateRecords = dateRecords;
    if (!AppState.selectedQuadrants.includes('全部')) {
        filteredDateRecords = dateRecords.filter(function(record) {
            var quadrant = record.quadrant || '';
            if (AppState.selectedQuadrants.includes(quadrant)) {
                return true;
            }
            var normalizedQuadrant = quadrant.replace(/—/g, '--');
            var matchFound = AppState.selectedQuadrants.some(function(selected) {
                var normalizedSelected = selected.replace(/—/g, '--');
                return normalizedQuadrant === normalizedSelected;
            });
            return matchFound;
        });
    }
    
    if (filteredDateRecords.length === 0) {
        showMessage('该日期没有符合筛选条件的数据', 'warning');
        return;
    }
    
    var otherDatesExist = AppState.canvasRecords.some(function(r) {
        return !r.timestamp.startsWith(date);
    });
    
    if (otherDatesExist) {
        AppState.canvasRecords = filteredDateRecords;
        drawQuadrant();
        showMessage('已清空画布并重绘 ' + date + ' 的 ' + filteredDateRecords.length + ' 条数据', 'success');
    } else {
        var existingCount = AppState.canvasRecords.filter(function(r) {
            return r.timestamp.startsWith(date);
        }).length;
        
        if (existingCount > 0) {
            AppState.canvasRecords = AppState.canvasRecords.filter(function(r) {
                return !r.timestamp.startsWith(date);
            });
            AppState.canvasRecords.push.apply(AppState.canvasRecords, filteredDateRecords);
            drawQuadrant();
            showMessage('已更新 ' + date + ' 的 ' + filteredDateRecords.length + ' 条数据', 'success');
        } else {
            AppState.canvasRecords.push.apply(AppState.canvasRecords, filteredDateRecords);
            drawQuadrant();
            showMessage('已重绘 ' + date + ' 的 ' + filteredDateRecords.length + ' 条数据', 'success');
        }
    }
}

/**
 * 筛选记录
 */
function filterRecords() {
    AppState.currentFilter = document.getElementById('dateFilterSelect').value;
    renderRecordsList();
}

/**
 * 清空画布
 */
function clearCanvas() {
    AppState.canvasRecords = [];
    drawQuadrant();
    showMessage('画布已清空', 'success');
}

// 导出到全局
window.getQuadrantClass = getQuadrantClass;
window.getLiquidityClass = getLiquidityClass;
window.getBadgeClass = getBadgeClass;
window.renderRecordsList = renderRecordsList;
window.handleRecordsListClick = handleRecordsListClick;
window.toggleDateGroup = toggleDateGroup;
window.redrawDate = redrawDate;
window.filterRecords = filterRecords;
window.clearCanvas = clearCanvas;
