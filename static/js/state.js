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
    hasInitializedCanvas: false,
    sortBy: '',  // 排序字段：'direction' 或 'volatility' 或 ''
    symbolFilter: []  // 标的筛选：支持多个symbol，以逗号分隔
};

// 导出到全局 (兼容非模块环境)
window.AppState = AppState;
