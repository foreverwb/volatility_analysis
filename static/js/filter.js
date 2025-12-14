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

// 导出到全局
window.toggleQuadrantDropdown = toggleQuadrantDropdown;
window.handleQuadrantChange = handleQuadrantChange;
window.updateQuadrantDisplay = updateQuadrantDisplay;
