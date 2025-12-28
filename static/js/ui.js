/**
 * UI 交互模块
 * 消息提示、抽屉组件
 */

/**
 * 显示消息提示
 */
function showMessage(text, type) {
    var container = document.getElementById('messageContainer');
    var messageBox = document.createElement('div');
    messageBox.className = 'message-box';
    
    var iconMap = {
        'success': '✓',
        'error': '✕',
        'warning': '!'
    };
    
    var durationMap = {
        'success': 3000,
        'error': 4000,
        'warning': 3500
    };
    
    var duration = durationMap[type] || 3000;
    var icon = iconMap[type] || '•';
    
    messageBox.innerHTML = 
        '<div class="message-icon ' + type + '">' + icon + '</div>' +
        '<div class="message-content">' +
            '<span class="message-text ' + type + '">' + text + '</span>' +
        '</div>' +
        '<button class="message-close" onclick="this.closest(\'.message-box\').remove()">×</button>';
    
    container.appendChild(messageBox);
    
    if (duration > 0) {
        setTimeout(function() {
            if (messageBox.parentNode) {
                messageBox.classList.add('hide');
                setTimeout(function() {
                    messageBox.remove();
                }, 300);
            }
        }, duration);
    }
}

/**
 * 打开输入抽屉
 */
function openInputDrawer() {
    document.getElementById('inputDrawerOverlay').classList.add('open');
    document.getElementById('inputDrawer').classList.add('open');
}

/**
 * 关闭输入抽屉
 */
function closeInputDrawer() {
    document.getElementById('inputDrawerOverlay').classList.remove('open');
    document.getElementById('inputDrawer').classList.remove('open');
}

/**
 * 打开详情抽屉
 */
function openDetailDrawer() {
    document.getElementById('detailDrawerOverlay').classList.add('open');
    document.getElementById('detailDrawer').classList.add('open');
}

/**
 * 关闭详情抽屉
 */
function closeDetailDrawer() {
    document.getElementById('detailDrawerOverlay').classList.remove('open');
    document.getElementById('detailDrawer').classList.remove('open');
}
/**
 * 显示 Loading
 * @param {string} text - 加载文本
 * @param {number} total - 总任务数
 */
function showLoading(text, total) {
    var overlay = document.getElementById('loadingOverlay');
    var loadingText = document.getElementById('loadingText');
    var progressTotal = document.getElementById('progressTotal');
    var progressCurrent = document.getElementById('progressCurrent');
    var progressFill = document.getElementById('progressFill');
    
    if (overlay) {
        overlay.classList.add('active');
        if (loadingText) loadingText.textContent = text || '正在获取数据...';
        if (progressTotal) progressTotal.textContent = total || 0;
        if (progressCurrent) progressCurrent.textContent = '0';
        if (progressFill) progressFill.style.width = '0%';
        
        // 禁用页面滚动
        document.body.style.overflow = 'hidden';
    }
}

/**
 * 隐藏 Loading
 */
function hideLoading() {
    var overlay = document.getElementById('loadingOverlay');
    if (overlay) {
        overlay.classList.remove('active');
        // 恢复页面滚动
        document.body.style.overflow = '';
    }
}

/**
 * 更新 Loading 进度
 * @param {number} current - 当前完成数
 * @param {number} total - 总任务数
 * @param {string} text - 可选的更新文本
 */
function updateLoadingProgress(current, total, text) {
    var progressCurrent = document.getElementById('progressCurrent');
    var progressFill = document.getElementById('progressFill');
    var loadingText = document.getElementById('loadingText');
    
    if (progressCurrent) {
        progressCurrent.textContent = current;
    }
    
    if (progressFill && total > 0) {
        var percentage = (current / total) * 100;
        progressFill.style.width = percentage + '%';
    }
    
    if (text && loadingText) {
        loadingText.textContent = text;
    }
}

// 导出到全局
window.showMessage = showMessage;
window.openInputDrawer = openInputDrawer;
window.closeInputDrawer = closeInputDrawer;
window.openDetailDrawer = openDetailDrawer;
window.closeDetailDrawer = closeDetailDrawer;
window.showLoading = showLoading;
window.hideLoading = hideLoading;
window.updateLoadingProgress = updateLoadingProgress;
