/**
 * 期权策略量化分析系统 
 * 前端主入口
 */

// 窗口大小改变时重绘
window.addEventListener('resize', function() {
    if (AppState.canvas) {
        AppState.canvas.width = AppState.canvas.offsetWidth;
        AppState.canvas.height = AppState.canvas.offsetHeight;
        drawQuadrant();
    }
});

// 点击外部关闭下拉框
document.addEventListener('click', function(e) {
    var filter = document.querySelector('.quadrant-filter');
    var dropdown = document.getElementById('quadrantDropdown');
    if (filter && !filter.contains(e.target)) {
        dropdown.classList.remove('open');
    }
});

// 页面加载完成后初始化
window.onload = function() {
    console.log('期权策略量化分析系统 ');
    console.log('新增特性: ActiveOpenRatio, Intertemporal Consistency, Structural Confidence Adjustment');
    
    // 加载数据
    loadRecords();
    loadDates();
    
    // 绑定事件
    document.getElementById('btnAnalyze').addEventListener('click', openInputDrawer);
    document.getElementById('btnSubmitAnalyze').addEventListener('click', analyzeData);
    document.getElementById('btnCancelAnalyze').addEventListener('click', closeInputDrawer);
    document.getElementById('btnCloseInputDrawer').addEventListener('click', closeInputDrawer);
    document.getElementById('btnClear').addEventListener('click', clearCanvas);
    document.getElementById('dateFilterSelect').addEventListener('change', filterRecords);
    document.getElementById('quadrantSelectBtn').addEventListener('click', toggleQuadrantDropdown);
    document.getElementById('detailDrawerOverlay').addEventListener('click', closeDetailDrawer);
    document.getElementById('btnCloseDetailDrawer').addEventListener('click', closeDetailDrawer);
    document.getElementById('inputDrawerOverlay').addEventListener('click', closeInputDrawer);
    document.getElementById('sortFilterSelect').addEventListener('change', handleSortChange);
    document.getElementById('slopeFilterSelect').addEventListener('change', handleSlopeFilterChange);
    document.getElementById('symbolFilterInput').addEventListener('input', handleSymbolFilterChange);
    
    // 象限筛选
    var allCheckbox = document.getElementById('quad-all');
    var checkboxIds = ['quad-1', 'quad-2', 'quad-3', 'quad-4', 'quad-5'];
    
    if (allCheckbox) {
        allCheckbox.addEventListener('change', handleQuadrantChange);
    }
    
    checkboxIds.forEach(function(id) {
        var cb = document.getElementById(id);
        if (cb) {
            cb.addEventListener('change', handleQuadrantChange);
        }
    });
};
