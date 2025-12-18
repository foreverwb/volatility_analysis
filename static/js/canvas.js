/**
 * Canvas 四象限绘制模块
 */

/**
 * 绘制四象限图
 */
function drawQuadrant() {
    if (!AppState.canvas) {
        AppState.canvas = document.getElementById('quadrantCanvas');
        AppState.ctx = AppState.canvas.getContext('2d');
        AppState.canvas.width = AppState.canvas.offsetWidth;
        AppState.canvas.height = AppState.canvas.offsetHeight;
        AppState.canvas.addEventListener('click', handleCanvasClick);
    }
    
    var canvas = AppState.canvas;
    var ctx = AppState.ctx;
    
    var width = canvas.width;
    var height = canvas.height;
    
    var size = Math.min(width, height);
    var centerX = width / 2;
    var centerY = height / 2;
    
    var paddingRatio = size < 600 ? 0.08 : (size < 800 ? 0.10 : 0.12);
    var padding = Math.max(50, size * paddingRatio);
    
    var quadrantSize = Math.min(width - 2 * padding, height - 2 * padding);
    var halfQuadrant = quadrantSize / 2;
    
    var left = centerX - halfQuadrant;
    var right = centerX + halfQuadrant;
    var top = centerY - halfQuadrant;
    var bottom = centerY + halfQuadrant;
    
    ctx.clearRect(0, 0, width, height);
    
    // 背景色
    ctx.globalAlpha = 0.08;
    ctx.fillStyle = '#34C759'; // 偏空—买波
    ctx.fillRect(left, top, halfQuadrant, halfQuadrant);
    ctx.fillStyle = '#00C853'; // 偏多—买波
    ctx.fillRect(centerX, top, halfQuadrant, halfQuadrant);
    ctx.fillStyle = '#007AFF'; // 偏空—卖波
    ctx.fillRect(left, centerY, halfQuadrant, halfQuadrant);
    ctx.fillStyle = '#FF9500'; // 偏多—卖波
    ctx.fillRect(centerX, centerY, halfQuadrant, halfQuadrant);
    ctx.globalAlpha = 1.0;
    
    // 坐标轴
    ctx.strokeStyle = '#333';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(left, centerY);
    ctx.lineTo(right, centerY);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(centerX, top);
    ctx.lineTo(centerX, bottom);
    ctx.stroke();
    
    // 网格线
    ctx.strokeStyle = '#ddd';
    ctx.lineWidth = 1;
    ctx.setLineDash([5, 5]);
    
    for (var i = 1; i <= 3; i++) {
        var xRight = centerX + (i * halfQuadrant / 4);
        ctx.beginPath();
        ctx.moveTo(xRight, top);
        ctx.lineTo(xRight, bottom);
        ctx.stroke();
        
        var xLeft = centerX - (i * halfQuadrant / 4);
        ctx.beginPath();
        ctx.moveTo(xLeft, top);
        ctx.lineTo(xLeft, bottom);
        ctx.stroke();
        
        var yDown = centerY + (i * halfQuadrant / 4);
        ctx.beginPath();
        ctx.moveTo(left, yDown);
        ctx.lineTo(right, yDown);
        ctx.stroke();
        
        var yUp = centerY - (i * halfQuadrant / 4);
        ctx.beginPath();
        ctx.moveTo(left, yUp);
        ctx.lineTo(right, yUp);
        ctx.stroke();
    }
    
    ctx.setLineDash([]);
    
    // 日期信息
    if (AppState.canvasRecords.length > 0) {
        var datesInCanvas = {};
        AppState.canvasRecords.forEach(function(r) {
            var date = r.timestamp.split(' ')[0];
            datesInCanvas[date] = (datesInCanvas[date] || 0) + 1;
        });
        
        var sortedDates = Object.keys(datesInCanvas).sort();
        
        ctx.fillStyle = '#1890ff';
        ctx.font = '12px Arial';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        
        if (sortedDates.length === 1) {
            var dateText = sortedDates[0] + ' (' + datesInCanvas[sortedDates[0]] + ')';
            ctx.fillText(dateText, centerX, 10);
        } else if (sortedDates.length <= 3) {
            var dateTexts = sortedDates.map(function(date) {
                return date + '(' + datesInCanvas[date] + ')';
            });
            ctx.fillText(dateTexts.join(' | '), centerX, 10);
        } else {
            var totalCount = AppState.canvasRecords.length;
            ctx.fillText(sortedDates.length + ' dates, ' + totalCount + ' records', centerX, 10);
        }
    }
    
    // 轴标签
    ctx.fillStyle = '#333';
    var fontSize = size < 600 ? 10 : 12;
    ctx.font = 'bold ' + fontSize + 'px Arial';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'alphabetic';
    ctx.fillText('买波', centerX, top - 10);
    ctx.fillText('卖波', centerX, bottom + 20);
    ctx.textAlign = 'left';
    ctx.fillText('偏空', left - 26, centerY + 3);
    ctx.textAlign = 'right';
    ctx.fillText('偏多', right + 26, centerY + 3);
    
    // 象限标签
    var labelFontSize = size < 600 ? 11 : 13;
    ctx.font = 'bold ' + labelFontSize + 'px Arial';
    ctx.fillStyle = '#666';
    ctx.textAlign = 'center';
    ctx.fillText('偏空—买波', left + halfQuadrant / 2, top + 20);
    ctx.fillText('偏多—买波', centerX + halfQuadrant / 2, top + 20);
    ctx.fillText('偏空—卖波', left + halfQuadrant / 2, bottom - 12);
    ctx.fillText('偏多—卖波', centerX + halfQuadrant / 2, bottom - 12);
    
    // 筛选记录
    var filteredRecords = AppState.canvasRecords.filter(function(r) {
        if (AppState.selectedQuadrants.includes('全部')) return true;
        
        var quadrant = r.quadrant || '';
        if (AppState.selectedQuadrants.includes(quadrant)) return true;
        
        var normalizedQuadrant = quadrant.replace(/—/g, '--');
        return AppState.selectedQuadrants.some(function(selected) {
            var normalizedSelected = selected.replace(/—/g, '--');
            return normalizedQuadrant === normalizedSelected;
        });
    });
    
    if (!Array.isArray(filteredRecords) || filteredRecords.length === 0) {
        ctx.fillStyle = '#999';
        ctx.font = '16px Arial';
        ctx.textAlign = 'center';
        ctx.fillText('暂无数据', centerX, centerY);
        return;
    }
    
    // 计算点位置
    var pointScale = size < 600 ? 0.85 : (size < 800 ? 0.80 : 0.75);
    var points = filteredRecords.map(function(record) {
        var xRange = record.direction_score >= 0 ? halfQuadrant : halfQuadrant;
        var yRange = record.vol_score >= 0 ? halfQuadrant : halfQuadrant;
        var x = centerX + (record.direction_score / 5) * xRange * pointScale;
        var y = centerY - (record.vol_score / 5) * yRange * pointScale;
        return { record: record, x: x, y: y };
    });
    
    // 避免重叠
    var minDistance = size < 600 ? 40 : Math.max(45, size * 0.06);
    var maxIterations = 50;
    for (var iter = 0; iter < maxIterations; iter++) {
        var moved = false;
        for (var i = 0; i < points.length; i++) {
            for (var j = i + 1; j < points.length; j++) {
                var dx = points[j].x - points[i].x;
                var dy = points[j].y - points[i].y;
                var dist = Math.sqrt(dx * dx + dy * dy);
                
                if (dist < minDistance && dist > 0) {
                    var angle = Math.atan2(dy, dx);
                    var offset = (minDistance - dist) / 2;
                    points[j].x += Math.cos(angle) * offset;
                    points[j].y += Math.sin(angle) * offset;
                    points[i].x -= Math.cos(angle) * offset;
                    points[i].y -= Math.sin(angle) * offset;
                    moved = true;
                }
            }
        }
        if (!moved) break;
    }
    
    // 绘制点
    var symbolFontSize = size < 600 ? 12 : 14;
    points.forEach(function(item) {
        var record = item.record;
        var x = item.x;
        var y = item.y;
        
        var color;
        var quadrant = record.quadrant || '';
        
        if (quadrant.includes('偏多') && quadrant.includes('买波')) color = '#00C853';
        else if (quadrant.includes('偏多') && quadrant.includes('卖波')) color = '#FF9500';
        else if (quadrant.includes('偏空') && quadrant.includes('买波')) color = '#34C759';
        else if (quadrant.includes('偏空') && quadrant.includes('卖波')) color = '#007AFF';
        else color = '#9C27B0';

        // Gamma 挤压的高亮绘制
        if (record.is_squeeze) {
            ctx.beginPath();
            ctx.arc(x, y, symbolFontSize + 10, 0, 2 * Math.PI);
            ctx.fillStyle = 'rgba(255, 59, 48, 0.2)';
            ctx.fill();
            ctx.strokeStyle = '#FF3B30';
            ctx.lineWidth = 2;
            ctx.stroke();
        }
        
        // : 趋势一致性高亮
        var consistency = record.consistency || 0;
        if (Math.abs(consistency) > 0.6) {
            ctx.beginPath();
            ctx.arc(x, y, symbolFontSize + 6, 0, 2 * Math.PI);
            ctx.fillStyle = consistency > 0 ? 'rgba(0, 200, 83, 0.15)' : 'rgba(255, 59, 48, 0.15)';
            ctx.fill();
        }
        
        ctx.fillStyle = color;
        ctx.font = 'bold ' + symbolFontSize + 'px "Comic Sans MS", cursive, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(record.symbol, x, y);
        
        var textWidth = ctx.measureText(record.symbol).width;
        record._canvasX = x;
        record._canvasY = y;
        record._clickRadius = Math.max(textWidth / 2 + 5, 15);
    });
}

/**
 * 处理 Canvas 点击事件
 */
function handleCanvasClick(event) {
    if (!Array.isArray(AppState.canvasRecords) || AppState.canvasRecords.length === 0) return;
    
    var rect = AppState.canvas.getBoundingClientRect();
    var x = event.clientX - rect.left;
    var y = event.clientY - rect.top;
    
    var filteredRecords = AppState.canvasRecords.filter(function(r) {
        if (AppState.selectedQuadrants.includes('全部')) return true;
        
        var quadrant = r.quadrant || '';
        if (AppState.selectedQuadrants.includes(quadrant)) return true;
        
        var normalizedQuadrant = quadrant.replace(/—/g, '--');
        return AppState.selectedQuadrants.some(function(selected) {
            var normalizedSelected = selected.replace(/—/g, '--');
            return normalizedQuadrant === normalizedSelected;
        });
    });
    
    for (var i = 0; i < filteredRecords.length; i++) {
        var record = filteredRecords[i];
        if (!record._canvasX || !record._canvasY) continue;
        
        var dx = x - record._canvasX;
        var dy = y - record._canvasY;
        var distance = Math.sqrt(dx * dx + dy * dy);
        var clickRadius = record._clickRadius || 15;
        
        if (distance <= clickRadius) {
            showDrawer(record.timestamp, record.symbol);
            return;
        }
    }
}

// 导出到全局
window.drawQuadrant = drawQuadrant;
window.handleCanvasClick = handleCanvasClick;
