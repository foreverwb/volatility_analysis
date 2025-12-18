/**
 * 全局状态管理
 * 
 */
var AppState = {
    allRecords: [],
    canvasRecords: [],
    currentFilter: '',
    selectedQuadrants: ['全部'],
    expandedDates: new Set(),
    earningsToggles: {},
    canvas: null,
    ctx: null,
    hasInitializedCanvas: false
};

// 导出到全局 (兼容非模块环境)
window.AppState = AppState;
