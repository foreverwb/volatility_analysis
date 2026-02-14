/**
 * 筛选器模块
 */

/**
 * 切换象限下拉框
 */
function toggleQuadrantDropdown() {
    var dropdown = document.getElementById('quadrantDropdown');
    dropdown.classList.toggle('open');
}

/**
 * 处理象限选择变化
 */
function handleQuadrantChange(e) {
    var allCheckbox = document.getElementById('quad-all');
    var checkboxes = [
        document.getElementById('quad-1'),
        document.getElementById('quad-2'),
        document.getElementById('quad-3'),
        document.getElementById('quad-4'),
        document.getElementById('quad-5')
    ];
    
    var targetId = e.target.id;
    
    if (targetId === 'quad-all') {
        if (allCheckbox.checked) {
            checkboxes.forEach(function(cb) { cb.checked = false; });
            AppState.selectedQuadrants = ['全部'];
        }
    } else {
        allCheckbox.checked = false;
        AppState.selectedQuadrants = checkboxes.filter(function(cb) { return cb.checked; })
                                       .map(function(cb) { return cb.value; });
        
        if (AppState.selectedQuadrants.length === 0) {
            allCheckbox.checked = true;
            AppState.selectedQuadrants = ['全部'];
        }
    }
    
    updateQuadrantDisplay();
    filterRecords();
}

/**
 * 更新象限显示
 */
function updateQuadrantDisplay() {
    var display = document.getElementById('quadrantSelected');
    
    if (AppState.selectedQuadrants.includes('全部')) {
        display.textContent = '全部';
    } else if (AppState.selectedQuadrants.length === 0) {
        display.textContent = '全部';
    } else {
        display.textContent = AppState.selectedQuadrants.join('、');
    }
}

/**
 * 处理排序变化
 */
function handleSortChange() {
    var sortSelect = document.getElementById('sortFilterSelect');
    AppState.sortBy = sortSelect.value;
    renderRecordsList();
}

/**
 * 处理标的筛选变化
 */
function handleSymbolFilterChange() {
    var input = document.getElementById('symbolFilterInput');
    var value = input.value.trim();
    
    if (value === '') {
        AppState.symbolFilter = [];
    } else {
        // 以逗号分隔，去除空白，转换为大写以便不区分大小写匹配
        AppState.symbolFilter = value.split(',')
            .map(function(s) { return s.trim().toUpperCase(); })
            .filter(function(s) { return s.length > 0; });
    }
    
    renderRecordsList();
}

/**
 * 处理斜率筛选变化
 */
function handleSlopeFilterChange() {
    var slopeSelect = document.getElementById('slopeFilterSelect');
    AppState.slopeFilter = slopeSelect.value;
    renderRecordsList();
}

/**
 * 根据标的筛选记录
 */
function filterBySymbol(records) {
    if (!AppState.symbolFilter || AppState.symbolFilter.length === 0) {
        return records;
    }
    
    return records.filter(function(record) {
        var symbol = (record.symbol || '').toUpperCase();
        // 检查是否匹配任一筛选条件（支持部分匹配）
        return AppState.symbolFilter.some(function(filter) {
            return symbol.indexOf(filter) !== -1;
        });
    });
}

/**
 * 根据斜率筛选记录
 */
function filterBySlope(records) {
    if (!AppState.slopeFilter || records.length === 0) {
        return records;
    }

    return records.filter(function(record) {
        var trendLabel = record.dir_trend_label;
        if (trendLabel === '上行') return AppState.slopeFilter === 'up';
        if (trendLabel === '下行') return AppState.slopeFilter === 'down';
        if (trendLabel === '横盘') return AppState.slopeFilter === 'flat';

        // 兼容历史数据：无趋势标签时，退化为按数值斜率符号判断
        var slope = Number(record.dir_slope_nd);
        if (!isFinite(slope)) return false;
        if (slope > 0) return AppState.slopeFilter === 'up';
        if (slope < 0) return AppState.slopeFilter === 'down';
        return AppState.slopeFilter === 'flat';
    });
}

/**
 * 根据排序设置对记录进行排序
 */
function sortRecords(records) {
    if (!AppState.sortBy || records.length === 0) {
        return records;
    }
    
    var sortedRecords = records.slice();
    
    if (AppState.sortBy === 'direction') {
        // 按方向得分从高到低排序
        sortedRecords.sort(function(a, b) {
            return (b.direction_score || 0) - (a.direction_score || 0);
        });
    } else if (AppState.sortBy === 'volatility') {
        // 按波动得分从高到低排序
        sortedRecords.sort(function(a, b) {
            return (b.vol_score || 0) - (a.vol_score || 0);
        });
    }
    
    return sortedRecords;
}

// 导出到全局
window.toggleQuadrantDropdown = toggleQuadrantDropdown;
window.handleQuadrantChange = handleQuadrantChange;
window.updateQuadrantDisplay = updateQuadrantDisplay;
window.handleSortChange = handleSortChange;
window.sortRecords = sortRecords;
window.handleSymbolFilterChange = handleSymbolFilterChange;
window.filterBySymbol = filterBySymbol;
window.handleSlopeFilterChange = handleSlopeFilterChange;
window.filterBySlope = filterBySlope;
