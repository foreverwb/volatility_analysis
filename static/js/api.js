/**
 * API 调用模块
 */

/**
 * 分析数据
 */
async function analyzeData() {
    var input = document.getElementById('dataInput').value.trim();
    
    if (!input) {
        showMessage('请输入数据', 'error');
        return;
    }
    
    try {
        input = input.replace(/^\s*\w+\s*=\s*/, '').replace(/;\s*$/, '');
        var records = JSON.parse(input);
        
        if (!Array.isArray(records)) {
            showMessage('数据必须是数组格式', 'error');
            return;
        }
        
        if (records.length === 0) {
            showMessage('数据数组不能为空', 'error');
            return;
        }

        //显示进度提示
        var symbolCount = new Set(records.map(r => r.symbol)).size;
        var estimatedTime = Math.ceil(symbolCount / 8 * 3); // 粗略估算
        
        showMessage(
            `正在获取 ${symbolCount} 个标的的 OI 数据，预计 ${estimatedTime} 秒...`, 
            'warning'
        );
        
        var response = await fetch('/api/analyze', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ records: records })
        });
        
        var result = await response.json();
        
        if (response.ok) {
            // 🟩 显示 OI 统计信息
            var oiStats = result.oi_stats || {};
            var message = result.message;
            
            if (oiStats.with_delta) {
                message += ` (OI数据: ${oiStats.with_delta}/${oiStats.total})`;
            }
            
            showMessage(result.message, 'success');
            document.getElementById('dataInput').value = '';
            closeInputDrawer();
            
            var newDates = new Set();
            if (result.results && Array.isArray(result.results)) {
                result.results.forEach(function(r) {
                    var date = r.timestamp.split(' ')[0];
                    newDates.add(date);
                });
                AppState.canvasRecords.push.apply(AppState.canvasRecords, result.results);
            }
            
            await loadRecords();
            await loadDates();
            
            newDates.forEach(function(date) {
                AppState.expandedDates.add(date);
                var content = document.getElementById('content-' + date);
                var toggle = document.getElementById('toggle-' + date);
                if (content && toggle) {
                    content.classList.add('expanded');
                    toggle.classList.add('expanded');
                }
            });
        } else {
            showMessage(result.error || '分析失败', 'error');
        }
    } catch (e) {
        showMessage('数据格式错误: ' + e.message, 'error');
    }
}

/**
 * 加载记录
 */
async function loadRecords() {
    try {
        var response = await fetch('/api/records');
        if (!response.ok) {
            AppState.allRecords = [];
            AppState.canvasRecords = [];
            renderRecordsList();
            drawQuadrant();
            return;
        }
        
        var data = await response.json();
        AppState.allRecords = Array.isArray(data) ? data : [];
        
        if (!AppState.hasInitializedCanvas) {
            AppState.hasInitializedCanvas = true;
            var today = new Date();
            var todayStr = today.getFullYear() + '-' + 
                          String(today.getMonth() + 1).padStart(2, '0') + '-' + 
                          String(today.getDate()).padStart(2, '0');
            var todayRecords = AppState.allRecords.filter(function(r) {
                return r.timestamp.startsWith(todayStr);
            });
            AppState.canvasRecords = todayRecords;
        }
        
        renderRecordsList();
        drawQuadrant();
    } catch (e) {
        console.error('Load data error:', e);
        AppState.allRecords = [];
        AppState.canvasRecords = [];
        renderRecordsList();
        drawQuadrant();
    }
}

/**
 * 加载日期列表
 */
async function loadDates() {
    try {
        var response = await fetch('/api/dates');
        if (!response.ok) return;
        
        var dates = await response.json();
        var select = document.getElementById('dateFilterSelect');
        var currentValue = select.value;
        select.innerHTML = '<option value="">全部日期</option>';
        
        dates.forEach(function(date) {
            var option = document.createElement('option');
            option.value = date;
            option.textContent = date;
            select.appendChild(option);
        });
        
        select.value = currentValue;
    } catch (e) {
        console.error('Load dates error:', e);
    }
}

/**
 * 删除单条记录
 */
async function deleteRecord(event, timestamp, symbol) {
    event.stopPropagation();
    
    var date = timestamp.split(' ')[0];
    var wasExpanded = AppState.expandedDates.has(date);
    
    try {
        var response = await fetch('/api/records/' + encodeURIComponent(timestamp) + '/' + encodeURIComponent(symbol), {
            method: 'DELETE'
        });
        
        if (response.ok) {
            showMessage('删除成功', 'success');
            
            if (wasExpanded) {
                AppState.expandedDates.add(date);
            }
            
            AppState.canvasRecords = AppState.canvasRecords.filter(function(r) {
                return !(r.timestamp === timestamp && r.symbol === symbol);
            });
            
            await loadRecords();
        } else {
            showMessage('删除失败', 'error');
        }
    } catch (e) {
        showMessage('删除失败: ' + e.message, 'error');
    }
}

/**
 * 按日期删除所有记录
 */
async function deleteAllByDate(event, date) {
    event.stopPropagation();
    
    try {
        var response = await fetch('/api/records/date/' + date, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            showMessage('已删除 ' + date + ' 的所有记录', 'success');
            AppState.canvasRecords = AppState.canvasRecords.filter(function(r) {
                return !r.timestamp.startsWith(date);
            });
            await loadRecords();
            await loadDates();
        } else {
            showMessage('删除失败', 'error');
        }
    } catch (e) {
        showMessage('删除失败: ' + e.message, 'error');
    }
}

/**
 * 处理财报开关切换
 */
async function handleEarningsToggle(checkbox) {
    var date = checkbox.getAttribute('data-date');
    var ignoreEarnings = checkbox.checked;
    
    AppState.earningsToggles[date] = ignoreEarnings;
    
    showMessage('正在重新计算 ' + date + ' 的数据...', 'warning');
    
    var dateRecords = AppState.allRecords.filter(function(r) {
        return r.timestamp.startsWith(date);
    });
    
    if (dateRecords.length === 0) {
        showMessage('该日期没有数据', 'error');
        return;
    }
    
    var rawDataList = dateRecords.map(function(r) { return r.raw_data; });
    
    try {
        var response = await fetch('/api/analyze?ignore_earnings=' + ignoreEarnings, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ records: rawDataList })
        });
        
        var result = await response.json();
        
        if (response.ok && result.results) {
            result.results.forEach(function(r) {
                r.earnings_event_enabled = ignoreEarnings;
            });
            
            AppState.allRecords = AppState.allRecords.filter(function(r) {
                return !r.timestamp.startsWith(date);
            });
            AppState.allRecords.push.apply(AppState.allRecords, result.results);
            
            var hasDateInCanvas = AppState.canvasRecords.some(function(r) {
                return r.timestamp.startsWith(date);
            });
            
            if (hasDateInCanvas) {
                var filteredResults = result.results;
                if (!AppState.selectedQuadrants.includes('全部')) {
                    filteredResults = result.results.filter(function(record) {
                        var quadrant = record.quadrant || '';
                        if (AppState.selectedQuadrants.includes(quadrant)) return true;
                        var normalizedQuadrant = quadrant.replace(/—/g, '--');
                        return AppState.selectedQuadrants.some(function(selected) {
                            var normalizedSelected = selected.replace(/—/g, '--');
                            return normalizedQuadrant === normalizedSelected;
                        });
                    });
                }
                
                AppState.canvasRecords = AppState.canvasRecords.filter(function(r) {
                    return !r.timestamp.startsWith(date);
                });
                AppState.canvasRecords.push.apply(AppState.canvasRecords, filteredResults);
                drawQuadrant();
            }
            
            renderRecordsList();
            
            showMessage('已' + (ignoreEarnings ? '开启' : '关闭') + '财报事件计算', 'success');
        } else {
            showMessage('重新计算失败: ' + (result.error || '未知错误'), 'error');
            checkbox.checked = !ignoreEarnings;
            AppState.earningsToggles[date] = !ignoreEarnings;
        }
    } catch (e) {
        showMessage('重新计算失败: ' + e.message, 'error');
        checkbox.checked = !ignoreEarnings;
        AppState.earningsToggles[date] = !ignoreEarnings;
    }
}

// 导出到全局
window.analyzeData = analyzeData;
window.loadRecords = loadRecords;
window.loadDates = loadDates;
window.deleteRecord = deleteRecord;
window.deleteAllByDate = deleteAllByDate;
window.handleEarningsToggle = handleEarningsToggle;
