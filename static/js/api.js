/**
 * API 调用模块
 * ✨ NEW: 支持显示 OI 跳过状态
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

        // 计算标的数量
        var symbolCount = new Set(records.map(r => r.symbol)).size;
        
        // 🟢 显示 Loading
        showLoading('正在初始化...', symbolCount);
        closeInputDrawer();
        
        console.log('🚀 开始流式请求...');
        
        // 🟢 创建 POST 请求获取流式响应
        var response = await fetch('/api/analyze/stream', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'text/event-stream'
            },
            body: JSON.stringify({ records: records })
        });
        
        if (!response.ok) {
            throw new Error('请求失败: ' + response.status);
        }
        
        console.log('✓ 连接建立');
        
        var reader = response.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';
        
        // ✨ NEW: 标记 OI 是否被跳过
        var oiSkipped = false;
        
        // 🟢 读取流
        var loopCount = 0;
        while (true) {
            var readResult = await reader.read();
            loopCount++;
            
            if (readResult.done) {
                console.log('✓ 流读取完成，总循环次数:', loopCount);
                break;
            }
            
            // 🟢 解码新数据
            buffer += decoder.decode(readResult.value, { stream: true });
            
            // 🟢 处理完整的消息（以 \n\n 分隔）
            var lines = buffer.split('\n');
            
            // 保留最后一行（可能不完整）
            buffer = lines.pop() || '';
            
            for (var i = 0; i < lines.length; i++) {
                var line = lines[i].trim();
                
                // 跳过空行和非 data 行
                if (!line || !line.startsWith('data:')) {
                    continue;
                }
                
                try {
                    // 🟢 解析 JSON 数据
                    var jsonStr = line.substring(5).trim(); // 移除 "data:" 前缀
                    
                    if (!jsonStr) continue;
                    
                    var data = JSON.parse(jsonStr);
                    
                    console.log('📦 收到事件:', data.type, data);
                    
                    // 🟢 根据事件类型处理
                    switch (data.type) {
                        case 'init':
                            console.log('✓ 初始化，总数:', data.total);
                            updateLoadingProgress(0, data.total, '正在初始化...');
                            break;
                            
                        case 'info':
                            console.log('✓ 配置信息:', {
                                workers: data.workers,
                                estimated_time: data.estimated_time,
                                message: data.message
                            });
                            
                            // ✨ NEW: 检测 OI 跳过消息
                            if (data.message && data.message.includes('跳过 OI')) {
                                oiSkipped = true;
                                updateLoadingProgress(
                                    0, 
                                    symbolCount, 
                                    '⏰ 当前时间早于 18:00，跳过 OI 数据获取'
                                );
                            } else {
                                updateLoadingProgress(
                                    0, 
                                    symbolCount, 
                                    `正在获取 OI 数据（预计 ${Math.ceil(data.estimated_time)} 秒）...`
                                );
                            }
                            break;
                            
                        case 'progress':
                            // 🟢 实时更新进度
                            console.log(`📈 进度更新: ${data.completed}/${data.total} (${data.percentage}%) - ${data.symbol}`);
                            updateLoadingProgress(
                                data.completed, 
                                data.total, 
                                `正在获取 OI 数据: ${data.symbol} (${data.percentage}%)`
                            );
                            break;
                            
                        case 'oi_complete':
                            console.log('✓ OI 获取完成，成功:', data.success, '跳过:', data.skipped);
                            
                            // ✨ NEW: 根据跳过状态显示不同消息
                            if (data.skipped) {
                                updateLoadingProgress(
                                    symbolCount, 
                                    symbolCount, 
                                    '⏰ 已跳过 OI 数据，开始分析...'
                                );
                            } else {
                                updateLoadingProgress(
                                    symbolCount, 
                                    symbolCount, 
                                    '开始分析数据...'
                                );
                            }
                            break;
                            
                        case 'analyze_progress':
                            console.log(`📊 分析进度: ${data.completed}/${data.total}`);
                            updateLoadingProgress(
                                data.completed, 
                                data.total, 
                                `正在分析数据 (${data.completed}/${data.total})...`
                            );
                            break;
                            
                        case 'complete':
                            console.log('✅ 全部完成');
                            // 分析完成
                            updateLoadingProgress(symbolCount, symbolCount, '数据处理完成');
                            
                            // 等待一小段时间让用户看到100%
                            await new Promise(resolve => setTimeout(resolve, 500));
                            
                            // 隐藏 Loading
                            hideLoading();
                            
                            // 处理结果
                            var oiStats = data.oi_stats || {};
                            var message = data.message;
                            
                            // ✨ NEW: 根据 OI 状态显示不同消息
                            if (oiStats.skipped) {
                                message += ' ⏰';
                                showMessage(message, 'warning');
                            } else if (oiStats.with_delta) {
                                message += ` (OI数据: ${oiStats.with_delta}/${oiStats.total})`;
                                showMessage(message, 'success');
                            } else {
                                showMessage(message, 'success');
                            }
                            
                            document.getElementById('dataInput').value = '';
                            
                            var newDates = new Set();
                            if (data.results && Array.isArray(data.results)) {
                                data.results.forEach(function(r) {
                                    var date = r.timestamp.split(' ')[0];
                                    newDates.add(date);
                                });
                                
                                // 🔴 先清空画布，再添加新数据
                                AppState.canvasRecords = data.results;
                            }
                            
                            await loadRecords();
                            await loadDates();
                            
                            // 重绘画布
                            drawQuadrant();
                            
                            newDates.forEach(function(date) {
                                AppState.expandedDates.add(date);
                                var content = document.getElementById('content-' + date);
                                var toggle = document.getElementById('toggle-' + date);
                                if (content && toggle) {
                                    content.classList.add('expanded');
                                    toggle.classList.add('expanded');
                                }
                            });
                            break;
                            
                        case 'error':
                            console.error('❌ 服务器错误:', data.error);
                            hideLoading();
                            showMessage(data.error || '分析失败', 'error');
                            return;
                            
                        default:
                            console.warn('⚠ 未知事件类型:', data.type);
                    }
                } catch (e) {
                    console.error('❌ 解析消息失败:', e, '原始数据:', line);
                }
            }
        }
        
        console.log('✅ 数据分析流程完成');
        
    } catch (e) {
        console.error('❌ 请求异常:', e);
        hideLoading();
        showMessage('请求失败: ' + e.message, 'error');
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