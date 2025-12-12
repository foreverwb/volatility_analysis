// ========================================
// Part 1: 全局变量与工具函数
// ========================================

// 全局状态
const AppState = {
    allRecords: [],
    canvasRecords: [],
    currentFilter: '',
    selectedQuadrants: ['全部'],
    expandedDates: new Set(),
    earningsToggles: {},
    canvas: null,
    ctx: null
};

// ========================================
// 消息通知系统
// ========================================
const MessageSystem = {
    show(text, type = 'success') {
        const container = document.getElementById('messageContainer');
        const messageBox = document.createElement('div');
        messageBox.className = 'message-box';
        
        const iconMap = { success: '✓', error: '✕', warning: '!' };
        const durationMap = { success: 3000, error: 4000, warning: 3500 };
        
        const duration = durationMap[type] || 3000;
        const icon = iconMap[type] || '•';
        
        messageBox.innerHTML = `
            <div class="message-icon ${type}">${icon}</div>
            <div class="message-content">
                <span class="message-text ${type}">${text}</span>
            </div>
            <button class="message-close" onclick="this.closest('.message-box').remove()">×</button>
        `;
        
        container.appendChild(messageBox);
        
        if (duration > 0) {
            setTimeout(() => {
                if (messageBox.parentNode) {
                    messageBox.classList.add('hide');
                    setTimeout(() => messageBox.remove(), 300);
                }
            }, duration);
        }
    }
};

// ========================================
// 样式工具函数
// ========================================
const StyleUtils = {
    getQuadrantClass(quadrant) {
        const map = {
            '偏多买波': 'quad-bull-buy',
            '偏多卖波': 'quad-bull-sell',
            '偏空买波': 'quad-bear-buy',
            '偏空卖波': 'quad-bear-sell',
            '中性': 'quad-neutral'
        };
        
        for (const [key, value] of Object.entries(map)) {
            if (quadrant.includes(key.substring(0, 2)) && quadrant.includes(key.substring(2))) {
                return value;
            }
        }
        return quadrant.includes('中性') ? 'quad-neutral' : '';
    },
    
    getLiquidityClass(liquidity) {
        const map = { '高': 'liquidity-high', '中': 'liquidity-medium', '低': 'liquidity-low' };
        return map[liquidity] || '';
    },
    
    getConfidenceBadge(confidence) {
        const map = { '高': 'badge-high', '中': 'badge-medium', '低': 'badge-low' };
        return map[confidence] || 'badge-low';
    },
    
    // 🆕 v2.2: 主动建仓方向图标
    getActiveOpenIcon(ratio) {
        if (ratio > 0.05) return '<span class="ao-icon ao-buy">↑建仓</span>';
        if (ratio < -0.05) return '<span class="ao-icon ao-sell">↓平仓</span>';
        return '<span class="ao-icon">━</span>';
    },
    
    // 🆕 v2.2: 期限结构标签
    getTermShapeLabel(shape) {
        const map = {
            'Short Steep': '<span class="term-label short-steep">📉 短端陡峭</span>',
            'Long Steep': '<span class="term-label long-steep">📈 长端陡峭</span>',
            'Smooth': '<span class="term-label smooth">━ 平滑</span>',
            'N/A': '<span class="term-label">N/A</span>'
        };
        return map[shape] || shape;
    }
};

// ========================================
// 数据格式化工具
// ========================================
const DataFormatter = {
    formatNumber(num, decimals = 2) {
        if (num == null || num === 0) return '0';
        return Number(num).toFixed(decimals);
    },
    
    formatPercent(num, decimals = 2) {
        if (num == null) return 'N/A';
        return `${this.formatNumber(num, decimals)}%`;
    },
    
    formatLargeNumber(num) {
        if (num == null || num === 0) return '0';
        if (Math.abs(num) >= 1e9) return `${(num / 1e9).toFixed(2)}B`;
        if (Math.abs(num) >= 1e6) return `${(num / 1e6).toFixed(2)}M`;
        if (Math.abs(num) >= 1e3) return `${(num / 1e3).toFixed(2)}K`;
        return num.toFixed(0);
    },
    
    // 🆕 v2.2: 主动建仓比格式化
    formatActiveOpen(ratio) {
        if (ratio == null) return 'N/A';
        const percent = (ratio * 100).toFixed(2);
        return `${percent > 0 ? '+' : ''}${percent}%`;
    }
};

// ========================================
// Part 2: 抽屉管理模块
// ========================================

const DrawerManager = {
    openInputDrawer() {
        document.getElementById('inputDrawerOverlay').classList.add('open');
        document.getElementById('inputDrawer').classList.add('open');
    },
    
    closeInputDrawer() {
        document.getElementById('inputDrawerOverlay').classList.remove('open');
        document.getElementById('inputDrawer').classList.remove('open');
    },
    
    openDetailDrawer() {
        document.getElementById('detailDrawerOverlay').classList.add('open');
        document.getElementById('detailDrawer').classList.add('open');
    },
    
    closeDetailDrawer() {
        document.getElementById('detailDrawerOverlay').classList.remove('open');
        document.getElementById('detailDrawer').classList.remove('open');
    }
};

// ========================================
// API 交互模块
// ========================================

const API = {
    async analyzeData(records) {
        const response = await fetch('/api/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ records })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || '分析失败');
        }
        
        return response.json();
    },
    
    async loadRecords() {
        const response = await fetch('/api/records');
        if (!response.ok) return [];
        return response.json();
    },
    
    async loadDates() {
        const response = await fetch('/api/dates');
        if (!response.ok) return [];
        return response.json();
    },
    
    async deleteRecord(timestamp, symbol) {
        const response = await fetch(
            `/api/records/${encodeURIComponent(timestamp)}/${encodeURIComponent(symbol)}`,
            { method: 'DELETE' }
        );
        return response.json();
    },
    
    async deleteRecordsByDate(date) {
        const response = await fetch(`/api/records/date/${date}`, { method: 'DELETE' });
        return response.json();
    }
};

// ========================================
// 数据分析处理
// ========================================

const DataAnalyzer = {
    async analyze() {
        const input = document.getElementById('dataInput').value.trim();
        
        if (!input) {
            MessageSystem.show('请输入数据', 'error');
            return;
        }
        
        try {
            // 清理输入
            const cleanedInput = input
                .replace(/^\s*\w+\s*=\s*/, '')
                .replace(/;\s*$/, '');
            
            const records = JSON.parse(cleanedInput);
            
            if (!Array.isArray(records) || records.length === 0) {
                MessageSystem.show('数据格式错误或为空', 'error');
                return;
            }
            
            // 调用API
            const result = await API.analyzeData(records);
            
            // 成功处理
            MessageSystem.show(result.message, 'success');
            document.getElementById('dataInput').value = '';
            DrawerManager.closeInputDrawer();
            
            // 收集新日期
            const newDates = new Set();
            if (result.results && Array.isArray(result.results)) {
                result.results.forEach(r => {
                    const date = r.timestamp.split(' ')[0];
                    newDates.add(date);
                });
                AppState.canvasRecords.push(...result.results);
            }
            
            // 刷新数据
            await RecordManager.loadRecords();
            await RecordManager.loadDates();
            
            // 自动展开新日期
            newDates.forEach(date => {
                AppState.expandedDates.add(date);
                const content = document.getElementById(`content-${date}`);
                const toggle = document.getElementById(`toggle-${date}`);
                if (content && toggle) {
                    content.classList.add('expanded');
                    toggle.classList.add('expanded');
                }
            });
            
        } catch (e) {
            MessageSystem.show(`数据格式错误: ${e.message}`, 'error');
        }
    }
};

// ========================================
// Part 3: 记录管理模块
// ========================================

const RecordManager = {
    async loadRecords() {
        try {
            const data = await API.loadRecords();
            AppState.allRecords = Array.isArray(data) ? data : [];
            
            // 首次加载时，自动选择今天的数据到画布
            if (!window.hasInitializedCanvas) {
                window.hasInitializedCanvas = true;
                const today = new Date();
                const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
                AppState.canvasRecords = AppState.allRecords.filter(r => 
                    r.timestamp.startsWith(todayStr)
                );
            }
            
            RecordRenderer.render();
            QuadrantCanvas.draw();
        } catch (e) {
            console.error('Load records error:', e);
            AppState.allRecords = [];
            AppState.canvasRecords = [];
            RecordRenderer.render();
            QuadrantCanvas.draw();
        }
    },
    
    async loadDates() {
        try {
            const dates = await API.loadDates();
            const select = document.getElementById('dateFilterSelect');
            const currentValue = select.value;
            
            select.innerHTML = '<option value="">全部日期</option>';
            dates.forEach(date => {
                const option = document.createElement('option');
                option.value = date;
                option.textContent = date;
                select.appendChild(option);
            });
            
            select.value = currentValue;
        } catch (e) {
            console.error('Load dates error:', e);
        }
    },
    
    filterRecords() {
        AppState.currentFilter = document.getElementById('dateFilterSelect').value;
        RecordRenderer.render();
    },
    
    clearCanvas() {
        AppState.canvasRecords = [];
        QuadrantCanvas.draw();
        MessageSystem.show('画布已清空', 'success');
    },
    
    async deleteRecord(timestamp, symbol) {
        const date = timestamp.split(' ')[0];
        const wasExpanded = AppState.expandedDates.has(date);
        
        try {
            await API.deleteRecord(timestamp, symbol);
            MessageSystem.show('删除成功', 'success');
            
            if (wasExpanded) {
                AppState.expandedDates.add(date);
            }
            
            AppState.canvasRecords = AppState.canvasRecords.filter(r => 
                !(r.timestamp === timestamp && r.symbol === symbol)
            );
            
            await this.loadRecords();
        } catch (e) {
            MessageSystem.show(`删除失败: ${e.message}`, 'error');
        }
    },
    
    async deleteByDate(date) {
        try {
            await API.deleteRecordsByDate(date);
            MessageSystem.show(`已删除 ${date} 的所有记录`, 'success');
            
            AppState.canvasRecords = AppState.canvasRecords.filter(r => 
                !r.timestamp.startsWith(date)
            );
            
            await this.loadRecords();
            await this.loadDates();
        } catch (e) {
            MessageSystem.show(`删除失败: ${e.message}`, 'error');
        }
    },
    
    redrawDate(date) {
        let dateRecords = AppState.allRecords.filter(r => 
            r.timestamp.startsWith(date)
        );
        
        if (dateRecords.length === 0) {
            MessageSystem.show('该日期没有数据', 'error');
            return;
        }
        
        // 应用象限筛选
        if (!AppState.selectedQuadrants.includes('全部')) {
            dateRecords = dateRecords.filter(record => 
                this._matchesQuadrantFilter(record.quadrant)
            );
        }
        
        if (dateRecords.length === 0) {
            MessageSystem.show('该日期没有符合筛选条件的数据', 'warning');
            return;
        }
        
        const otherDatesExist = AppState.canvasRecords.some(r => 
            !r.timestamp.startsWith(date)
        );
        
        if (otherDatesExist) {
            AppState.canvasRecords = dateRecords;
            MessageSystem.show(`已清空画布并重绘 ${date} 的 ${dateRecords.length} 条数据`, 'success');
        } else {
            const existingCount = AppState.canvasRecords.filter(r => 
                r.timestamp.startsWith(date)
            ).length;
            
            if (existingCount > 0) {
                AppState.canvasRecords = AppState.canvasRecords.filter(r => 
                    !r.timestamp.startsWith(date)
                );
                AppState.canvasRecords.push(...dateRecords);
                MessageSystem.show(`已更新 ${date} 的 ${dateRecords.length} 条数据`, 'success');
            } else {
                AppState.canvasRecords.push(...dateRecords);
                MessageSystem.show(`已重绘 ${date} 的 ${dateRecords.length} 条数据`, 'success');
            }
        }
        
        QuadrantCanvas.draw();
    },
    
    _matchesQuadrantFilter(quadrant) {
        if (AppState.selectedQuadrants.includes('全部')) return true;
        if (AppState.selectedQuadrants.includes(quadrant)) return true;
        
        const normalized = quadrant.replace(/—/g, '--');
        return AppState.selectedQuadrants.some(selected => 
            normalized === selected.replace(/—/g, '--')
        );
    }
};

// ========================================
// Part 4: 记录列表渲染器
// ========================================

const RecordRenderer = {
    render() {
        const container = document.getElementById('recordsList');
        
        if (!AppState.allRecords || AppState.allRecords.length === 0) {
            container.innerHTML = '<div class="empty-state">暂无数据,请先提交分析</div>';
            return;
        }
        
        // 按日期分组
        const groupedByDate = this._groupByDate();
        
        // 应用筛选
        const filteredGroups = this._applyFilters(groupedByDate);
        
        const sortedDates = Object.keys(filteredGroups).sort().reverse();
        
        if (sortedDates.length === 0) {
            container.innerHTML = '<div class="empty-state">没有符合条件的数据</div>';
            return;
        }
        
        // 生成HTML
        const html = sortedDates.map(date => 
            this._renderDateGroup(date, filteredGroups[date])
        ).join('');
        
        container.innerHTML = html;
        container.addEventListener('click', this._handleClick);
    },
    
    _groupByDate() {
        const groups = {};
        AppState.allRecords.forEach(record => {
            const date = record.timestamp.split(' ')[0];
            
            // 应用日期筛选
            if (AppState.currentFilter && date !== AppState.currentFilter) return;
            
            if (!groups[date]) groups[date] = [];
            groups[date].push(record);
        });
        return groups;
    },
    
    _applyFilters(groups) {
        if (AppState.selectedQuadrants.includes('全部')) {
            return groups;
        }
        
        const filtered = {};
        for (const [date, records] of Object.entries(groups)) {
            const filteredRecords = records.filter(record => 
                RecordManager._matchesQuadrantFilter(record.quadrant)
            );
            if (filteredRecords.length > 0) {
                filtered[date] = filteredRecords;
            }
        }
        return filtered;
    },
    
    _renderDateGroup(date, records) {
        const count = records.length;
        const isExpanded = AppState.expandedDates.has(date);
        const isChecked = AppState.earningsToggles[date] ? 'checked' : '';
        
        return `
            <div class="date-group" data-date="${date}">
                ${this._renderDateHeader(date, count, isExpanded, isChecked)}
                ${this._renderDateContent(date, records, isExpanded)}
            </div>
        `;
    },
    
    _renderDateHeader(date, count, isExpanded, isChecked) {
        return `
            <div class="date-header sticky" data-date="${date}">
                <div class="date-title">
                    <span class="date-toggle ${isExpanded ? 'expanded' : ''}" id="toggle-${date}">▼</span>
                    <span>${date} (${count}条)</span>
                </div>
                <div class="date-actions">
                    <div class="earnings-toggle">
                        <label class="switch">
                            <input type="checkbox" class="earnings-checkbox" data-date="${date}" ${isChecked}>
                            <span class="slider">
                                <span class="slider-text open">E-ON</span>
                                <span class="slider-text close">E-OFF</span>
                            </span>
                        </label>
                    </div>
                    <button class="icon-btn" data-date="${date}" data-action="redraw" title="重绘"><svg class="icon" viewBox="0 0 1024 1024" width="16" height="16"><path d="M242.27 421.75v131.84c0 12.1 8.41 23.29 20.56 25.21a24.541 24.541 0 0 0 28.82-23.89v-71.86c0-7.72 6.38-13.97 14.23-13.97 7.88 0 14.26 6.25 14.26 13.97v42.32c0 12.1 8.38 23.27 20.53 25.21 7.11 1.26 14.4-0.67 19.96-5.27 5.55-4.6 8.81-11.41 8.89-18.62v-43.63c0-7.72 6.37-13.97 14.21-13.97 7.88 0 14.26 6.25 14.26 13.97v19.82c0 7.98 6.59 14.47 14.71 14.47 8.12 0 14.71-6.49 14.71-14.47v-15.1c0-10.32 8.53-18.69 19.03-18.69h10.35c10.49 0 19.02 8.36 19.02 18.69 0 13.39 11.05 24.25 24.7 24.25 13.64 0 24.68-10.86 24.68-24.25v-18.69h177.29v-71.88H242.27v24.54z m0 0" fill="#FFB74D"></path><path d="M744.88 271.25h-17.81v50.82h17.81c14.28 0 25.88 11.43 25.88 25.42v137.3c0 14.02-11.59 25.42-25.88 25.42H607.15c-42.82 0-77.64 34.19-77.64 76.24v24.56h51.76v-24.56c0-14.02 11.6-25.45 25.88-25.45h137.73c42.79 0 77.63-34.17 77.63-76.22V347.5c0-42.06-34.84-76.25-77.63-76.25z m0 0" fill="#607D8B"></path><path d="M522.26 611a8.09 8.09 0 0 0-8.17 8.03c0 4.45 3.67 8.02 8.17 8.02h66.25a8.09 8.09 0 0 0 8.17-8.02 8.09 8.09 0 0 0-8.17-8.03h-66.25z m0 0" fill="#E2543F"></path><path d="M503.61 757.16c-5.2 31.29 19.45 59.73 51.75 59.73s56.93-28.46 51.71-59.73l-21.56-130.11H525.2l-21.59 130.11z m0 0" fill="#EB6C57"></path><path d="M245.79 386.24c-1.25 0-2.33-0.55-3.52-0.72v11.64h460.29v-11.64c-1.22 0.14-2.3 0.72-3.55 0.72H245.79z m0 0" fill="#FB8C00"></path><path d="M727.07 235.19c0-15.5-12.55-28.08-28.08-28.08h-453.2c-15.5 0-28.08 12.58-28.08 28.08v122.97c0 14.25 10.78 25.57 24.54 27.39 1.2 0.17 2.28 0.72 3.52 0.72h453.2c1.27 0 2.35-0.55 3.55-0.72 13.91-1.65 24.42-13.38 24.51-27.39V235.19h0.04z m0 0" fill="#FFB74D"></path><path d="M201.49 275.02h16.22v43.32h-16.22z" fill="#FB8C00"></path></svg></button>
                    <button class="icon-btn delete-all" data-date="${date}" data-action="delete" title="全部删除">
                        <svg class="icon" viewBox="0 0 1024 1024" width="16" height="16"><path d="M512 311.893333m-178.773333 0a178.773333 178.773333 0 1 0 357.546666 0 178.773333 178.773333 0 1 0-357.546666 0Z" fill="#FF354A"></path><path d="M746.666667 890.88H277.333333c-47.146667 0-85.333333-38.186667-85.333333-85.333333v-384c0-47.146667 38.186667-85.333333 85.333333-85.333334h469.333334c47.146667 0 85.333333 38.186667 85.333333 85.333334v384c0 47.146667-38.186667 85.333333-85.333333 85.333333z" fill="#2953FF"></path><path d="M345.386667 708.48v-149.333333a53.333333 53.333333 0 0 1 106.666666 0v149.333333a53.333333 53.333333 0 0 1-106.666666 0zM571.946667 708.48v-149.333333a53.333333 53.333333 0 0 1 106.666666 0v149.333333a53.333333 53.333333 0 0 1-106.666666 0z" fill="#93A8FF"></path><path d="M857.813333 397.226667H166.186667C133.333333 397.226667 106.666667 370.56 106.666667 337.706667v-8.746667c0-32.853333 26.666667-59.52 59.52-59.52H857.6c32.853333 0 59.52 26.666667 59.52 59.52v8.746667a59.221333 59.221333 0 0 1-59.306667 59.52z" fill="#FCCA1E"></path></svg>
                    </button>
                </div>
            </div>
        `;
    },
    
    _renderDateContent(date, records, isExpanded) {
        const recordsHtml = records.map(record => this._renderRecordItem(record)).join('');
        return `
            <div class="date-content ${isExpanded ? 'expanded' : ''}" id="content-${date}">
                ${recordsHtml}
            </div>
        `;
    },
    
    _renderRecordItem(record) {
        const quadrantClass = StyleUtils.getQuadrantClass(record.quadrant);
        const liquidityClass = StyleUtils.getLiquidityClass(record.liquidity);
        const confidenceBadge = StyleUtils.getConfidenceBadge(record.confidence);
        
        // 徽章
        const eventBadge = record.earnings_event_enabled ? '<span class="earnings-badge">E</span>' : '';
        const typeBadge = record.is_index ? '<span class="badge-type">ETF</span>' : '';
        const squeezeBadge = record.is_squeeze ? '<span class="badge-squeeze">🚀 Squeeze</span>' : '';
        
        // 🆕 v2.2: 主动建仓图标
        const aoIcon = StyleUtils.getActiveOpenIcon(record.active_open_ratio || 0);
        
        // 分数颜色
        const dirScore = record.direction_score || 0;
        const volScore = record.vol_score || 0;
        const dirColor = dirScore > 0 ? '#00C853' : (dirScore < 0 ? '#FF3B30' : '#9E9E9E');
        const volColor = volScore > 0 ? '#00C853' : (volScore < 0 ? '#FF3B30' : '#9E9E9E');
        
        // 财报显示
        const daysToEarnings = record.derived_metrics?.days_to_earnings;
        const showEarnings = daysToEarnings !== null && daysToEarnings > 0;
        const earningsHtml = showEarnings ? `<span class="record-earnings">财报: ${daysToEarnings}天</span>` : '';
        
        return `
            <div class="record-item" data-timestamp="${record.timestamp}" data-symbol="${record.symbol}">
                <div class="record-info">
                    <div class="record-symbol">
                        ${record.symbol}${eventBadge}${typeBadge}${squeezeBadge}${aoIcon}
                    </div>
                    <div class="record-meta">
                        <span class="record-quadrant ${quadrantClass}">${record.quadrant}</span>
                        <span class="record-confidence">置信度: <span class="badge ${confidenceBadge}">${record.confidence}</span></span>
                        <span class="record-liquidity ${liquidityClass}">流动性: ${record.liquidity}</span>
                        <span class="record-score-dir" style="color: ${dirColor};">方向: ${dirScore}</span>
                        <span class="record-score-vol" style="color: ${volColor};">波动: ${volScore}</span>
                        ${earningsHtml}
                    </div>
                </div>
                <button class="btn-delete-item" data-timestamp="${record.timestamp}" data-symbol="${record.symbol}">&times;</button>
            </div>
        `;
    },
    
    _handleClick(e) {
        const target = e.target;
        
        // 日期头部点击
        const dateHeader = target.closest('.date-header');
        if (dateHeader && !target.closest('.date-actions')) {
            const date = dateHeader.getAttribute('data-date');
            RecordRenderer._toggleDateGroup(date);
            return;
        }
        
        // 图标按钮
        const iconBtn = target.closest('.icon-btn');
        if (iconBtn) {
            e.stopPropagation();
            const date = iconBtn.getAttribute('data-date');
            const action = iconBtn.getAttribute('data-action');
            
            if (action === 'redraw') {
                RecordManager.redrawDate(date);
            } else if (action === 'delete') {
                RecordManager.deleteByDate(date);
            }
            return;
        }
        
        // 记录项点击
        const recordItem = target.closest('.record-item');
        if (recordItem && !target.classList.contains('btn-delete-item')) {
            DetailDrawer.show(
                recordItem.getAttribute('data-timestamp'),
                recordItem.getAttribute('data-symbol')
            );
            return;
        }
        
        // 删除按钮
        if (target.classList.contains('btn-delete-item')) {
            e.stopPropagation();
            RecordManager.deleteRecord(
                target.getAttribute('data-timestamp'),
                target.getAttribute('data-symbol')
            );
            return;
        }
        
        // 财报开关
        if (target.classList.contains('earnings-checkbox')) {
            e.stopPropagation();
            EarningsToggle.handle(target);
            return;
        }
    },
    
    _toggleDateGroup(date) {
        const content = document.getElementById(`content-${date}`);
        const toggle = document.getElementById(`toggle-${date}`);
        
        if (content.classList.contains('expanded')) {
            content.classList.remove('expanded');
            toggle.classList.remove('expanded');
            AppState.expandedDates.delete(date);
        } else {
            content.classList.add('expanded');
            toggle.classList.add('expanded');
            AppState.expandedDates.add(date);
        }
    }
};

// ========================================
// Part 5: 详情抽屉（v2.2 完整字段展示）
// ========================================

const DetailDrawer = {
    show(timestamp, symbol) {
        const record = AppState.allRecords.find(r => 
            r.timestamp === timestamp && r.symbol === symbol
        );
        
        if (!record) return;
        
        // 标题
        const eventBadge = record.earnings_event_enabled ? ' <span class="earnings-badge">E</span>' : '';
        const typeBadge = record.is_index ? ' <span class="badge-type">ETF</span>' : '';
        document.getElementById('detailDrawerTitle').innerHTML = 
            `${record.symbol}${eventBadge}${typeBadge} - 详细分析`;
        
        // 内容
        const html = this._buildContent(record);
        document.getElementById('detailDrawerContent').innerHTML = html;
        
        DrawerManager.openDetailDrawer();
    },
    
    _buildContent(record) {
        return `
            <p class="timestamp">${record.timestamp}</p>
            ${this._buildCoreConclusionSection(record)}
            ${this._buildMeso22IndicatorsSection(record)}
            ${this._buildDerivedMetricsSection(record)}
            ${this._buildDirectionFactorsSection(record)}
            ${this._buildVolFactorsSection(record)}
            ${this._buildStrategySection(record)}
            ${this._buildRiskSection(record)}
        `;
    },
    
    // 核心结论
    _buildCoreConclusionSection(record) {
        const quadrantClass = StyleUtils.getQuadrantClass(record.quadrant);
        const confidenceBadge = StyleUtils.getConfidenceBadge(record.confidence);
        const liquidityClass = StyleUtils.getLiquidityClass(record.liquidity);
        const isSqueeze = record.is_squeeze || false;
        
        const dirScore = record.direction_score || 0;
        const volScore = record.vol_score || 0;
        const dirColor = dirScore > 0 ? '#00C853' : (dirScore < 0 ? '#FF3B30' : '#9E9E9E');
        const volColor = volScore > 0 ? '#00C853' : (volScore < 0 ? '#FF3B30' : '#9E9E9E');
        
        const daysToEarnings = record.derived_metrics?.days_to_earnings;
        const showEarnings = daysToEarnings !== null && daysToEarnings > 0;
        const earningsRow = showEarnings ? 
            `<div class="detail-row">
                <div class="detail-label">距离财报:</div>
                <div class="detail-value">${daysToEarnings} 天</div>
            </div>` : '';
        
        const squeezeRow = isSqueeze ? 
            `<div class="detail-row">
                <div class="detail-label">特殊状态:</div>
                <div class="detail-value"><span class="badge-squeeze">🚀 GAMMA SQUEEZE DETECTED</span></div>
            </div>` : '';
        
        return `
            <div class="detail-section">
                <h3>核心结论</h3>
                <div class="detail-row">
                    <div class="detail-label">四象限定位:</div>
                    <div class="detail-value">
                        <strong><span class="record-quadrant ${quadrantClass}">${record.quadrant}</span></strong>
                    </div>
                </div>
                ${squeezeRow}
                <div class="detail-row">
                    <div class="detail-label">置信度:</div>
                    <div class="detail-value">
                        <span class="badge ${confidenceBadge} detail-value-highlight">${record.confidence}</span>
                    </div>
                </div>
                <div class="detail-row">
                    <div class="detail-label">流动性:</div>
                    <div class="detail-value">
                        <span class="detail-value-liquidity ${liquidityClass}">${record.liquidity}</span>
                    </div>
                </div>
                ${earningsRow}
                <div class="detail-row">
                    <div class="detail-label">方向评分:</div>
                    <div class="detail-value" style="color: ${dirColor}; font-weight: bold;">
                        ${dirScore} (${record.direction_bias || '中性'})
                    </div>
                </div>
                <div class="detail-row">
                    <div class="detail-label">波动评分:</div>
                    <div class="detail-value" style="color: ${volColor}; font-weight: bold;">
                        ${volScore} (${record.vol_bias || '中性'})
                    </div>
                </div>
            </div>
        `;
    },
    
    // 🆕 v2.2: Meso 高级指标（新增模块）
    _buildMeso22IndicatorsSection(record) {
        const spotVolCorr = record.spot_vol_corr_score || 0;
        const netSent = record.net_sentiment || 0;
        const crowdSens = record.crowd_sensitivity || 0;
        const activeOpen = record.active_open_ratio || 0;
        const deltaOI = record.delta_oi || 0;
        const termShape = record.term_structure_ratio || 'N/A';
        
        // 主动建仓比高亮样式
        const aoClass = Math.abs(activeOpen) > 0.05 ? 'detail-row-highlight' : 'detail-row';
        const aoIcon = StyleUtils.getActiveOpenIcon(activeOpen);
        const aoLabel = activeOpen > 0.05 ? '主动建仓' : 
                        activeOpen < -0.05 ? '主动平仓' : '平衡';
        
        return `
            <div class="detail-section">
                <h3>🎯  核心指标</h3>
                
                <div class="${aoClass}">
                    <div class="detail-label">主动建仓比:</div>
                    <div class="detail-value">
                        <span class="active-open-value">${DataFormatter.formatActiveOpen(activeOpen)}</span>
                        ${aoIcon}
                        <span class="active-open-label">${aoLabel}</span>
                    </div>
                </div>
                
                <div class="detail-row">
                    <div class="detail-label">OI 变化量:</div>
                    <div class="detail-value ${deltaOI > 0 ? 'oi-delta-positive' : deltaOI < 0 ? 'oi-delta-negative' : ''}">
                        ${deltaOI > 0 ? '+' : ''}${DataFormatter.formatLargeNumber(deltaOI)}
                    </div>
                </div>
                
                <div class="detail-row">
                    <div class="detail-label">净期权情绪:</div>
                    <div class="detail-value" style="color: ${netSent > 0 ? '#00C853' : netSent < 0 ? '#FF3B30' : '#9E9E9E'}">
                        ${DataFormatter.formatNumber(netSent, 2)}
                    </div>
                </div>
                
                <div class="detail-row">
                    <div class="detail-label">群体敏感度:</div>
                    <div class="detail-value">
                        ${DataFormatter.formatNumber(crowdSens, 2)}
                        <small style="color: #00000045; margin-left: 8px;">
                            (ΔIV/ΔPrice)
                        </small>
                    </div>
                </div>
                
                <div class="detail-row">
                    <div class="detail-label">价-波相关性:</div>
                    <div class="detail-value">
                        ${DataFormatter.formatNumber(spotVolCorr, 2)}
                        <small style="color: #00000045; margin-left: 8px;">
                            (情绪放大系数)
                        </small>
                    </div>
                </div>
                
                <div class="detail-row">
                    <div class="detail-label">期限结构:</div>
                    <div class="detail-value">
                        ${StyleUtils.getTermShapeLabel(termShape)}
                    </div>
                </div>
            </div>
        `;
    },
    
    // 衍生指标
    _buildDerivedMetricsSection(record) {
        const metrics = record.derived_metrics || {};
        return `
            <div class="detail-section">
                <h3>衍生指标</h3>
                <div class="detail-row">
                    <div class="detail-label">IVRV 比值:</div>
                    <div class="detail-value">${metrics.ivrv_ratio || 'N/A'}</div>
                </div>
                <div class="detail-row">
                    <div class="detail-label">IVRV 差值:</div>
                    <div class="detail-value">${metrics.ivrv_diff || 'N/A'}</div>
                </div>
                <div class="detail-row">
                    <div class="detail-label">Call/Put 比值:</div>
                    <div class="detail-value">${metrics.cp_ratio || 'N/A'}</div>
                </div>
            </div>
        `;
    },
    
    // 方向驱动因素
    _buildDirectionFactorsSection(record) {
        const factors = record.direction_factors || [];
        const factorsHtml = factors.map(f => `<li>${f}</li>`).join('');
        return `
            <div class="detail-section">
                <h3>方向驱动因素</h3>
                <ul class="factor-list">${factorsHtml}</ul>
            </div>
        `;
    },
    
    // 波动驱动因素
    _buildVolFactorsSection(record) {
        const factors = record.vol_factors || [];
        const factorsHtml = factors.map(f => `<li>${f}</li>`).join('');
        return `
            <div class="detail-section">
                <h3>波动驱动因素</h3>
                <ul class="factor-list">${factorsHtml}</ul>
            </div>
        `;
    },
    
    // 策略建议
    _buildStrategySection(record) {
        let strategyText = record.strategy || '观望';
        
        // 挤压强化
        if (record.is_squeeze) {
            strategyText = `🔥 <strong>强烈建议：</strong>买入看涨期权 (Long Call) 利用 Gamma 爆发。<br>${strategyText}`;
        }
        
        return `
            <div class="detail-section">
                <h3>策略建议</h3>
                <div class="detail-row">
                    <div class="detail-value">${strategyText}</div>
                </div>
            </div>
        `;
    },
    
    // 风险提示
    _buildRiskSection(record) {
        return `
            <div class="detail-section">
                <h3>风险提示</h3>
                <div class="detail-row">
                    <div class="detail-value risk-text">${record.risk || '请注意风控'}</div>
                </div>
            </div>
        `;
    }
};

// ========================================
// Part 6: 四象限画布绘制
// ========================================

const QuadrantCanvas = {
    init() {
        if (!AppState.canvas) {
            AppState.canvas = document.getElementById('quadrantCanvas');
            AppState.ctx = AppState.canvas.getContext('2d');
            AppState.canvas.width = AppState.canvas.offsetWidth;
            AppState.canvas.height = AppState.canvas.offsetHeight;
            AppState.canvas.addEventListener('click', this.handleClick.bind(this));
        }
    },
    
    draw() {
        this.init();
        const { canvas, ctx } = AppState;
        
        const width = canvas.width;
        const height = canvas.height;
        const size = Math.min(width, height);
        const centerX = width / 2;
        const centerY = height / 2;
        
        // 自适应padding
        const paddingRatio = size < 600 ? 0.08 : (size < 800 ? 0.10 : 0.12);
        const padding = Math.max(50, size * paddingRatio);
        
        const quadrantSize = Math.min(width - 2 * padding, height - 2 * padding);
        const halfQuadrant = quadrantSize / 2;
        
        const left = centerX - halfQuadrant;
        const right = centerX + halfQuadrant;
        const top = centerY - halfQuadrant;
        const bottom = centerY + halfQuadrant;
        
        // 清空画布
        ctx.clearRect(0, 0, width, height);
        
        // 绘制背景色块
        this._drawBackgrounds(ctx, left, top, centerX, centerY, halfQuadrant);
        
        // 绘制坐标轴
        this._drawAxes(ctx, left, right, top, bottom, centerX, centerY);
        
        // 绘制网格
        this._drawGrid(ctx, left, right, top, bottom, centerX, centerY, halfQuadrant);
        
        // 绘制日期信息
        this._drawDateInfo(ctx, centerX);
        
        // 绘制轴标签
        this._drawAxisLabels(ctx, centerX, centerY, left, right, top, bottom, size);
        
        // 绘制象限标签
        this._drawQuadrantLabels(ctx, left, top, bottom, centerX, halfQuadrant, size);
        
        // 绘制数据点
        this._drawDataPoints(ctx, centerX, centerY, halfQuadrant, size);
    },
    
    _drawBackgrounds(ctx, left, top, centerX, centerY, halfQuadrant) {
        ctx.globalAlpha = 0.08;
        
        // 偏空—买波 (左上)
        ctx.fillStyle = '#34C759';
        ctx.fillRect(left, top, halfQuadrant, halfQuadrant);
        
        // 偏多—买波 (右上)
        ctx.fillStyle = '#00C853';
        ctx.fillRect(centerX, top, halfQuadrant, halfQuadrant);
        
        // 偏空—卖波 (左下)
        ctx.fillStyle = '#007AFF';
        ctx.fillRect(left, centerY, halfQuadrant, halfQuadrant);
        
        // 偏多—卖波 (右下)
        ctx.fillStyle = '#FF9500';
        ctx.fillRect(centerX, centerY, halfQuadrant, halfQuadrant);
        
        ctx.globalAlpha = 1.0;
    },
    
    _drawAxes(ctx, left, right, top, bottom, centerX, centerY) {
        ctx.strokeStyle = '#333';
        ctx.lineWidth = 2;
        
        // 水平轴
        ctx.beginPath();
        ctx.moveTo(left, centerY);
        ctx.lineTo(right, centerY);
        ctx.stroke();
        
        // 垂直轴
        ctx.beginPath();
        ctx.moveTo(centerX, top);
        ctx.lineTo(centerX, bottom);
        ctx.stroke();
    },
    
    _drawGrid(ctx, left, right, top, bottom, centerX, centerY, halfQuadrant) {
        ctx.strokeStyle = '#ddd';
        ctx.lineWidth = 1;
        ctx.setLineDash([5, 5]);
        
        for (let i = 1; i <= 3; i++) {
            // 垂直网格
            const xRight = centerX + (i * halfQuadrant / 4);
            const xLeft = centerX - (i * halfQuadrant / 4);
            
            ctx.beginPath();
            ctx.moveTo(xRight, top);
            ctx.lineTo(xRight, bottom);
            ctx.stroke();
            
            ctx.beginPath();
            ctx.moveTo(xLeft, top);
            ctx.lineTo(xLeft, bottom);
            ctx.stroke();
            
            // 水平网格
            const yDown = centerY + (i * halfQuadrant / 4);
            const yUp = centerY - (i * halfQuadrant / 4);
            
            ctx.beginPath();
            ctx.moveTo(left, yDown);
            ctx.lineTo(right, yDown);
            ctx.stroke();
            
            ctx.beginPath();
            ctx.moveTo(left, yUp);
            ctx.lineTo(right, yUp);
            ctx.stroke();
        }
        
        ctx.setLineDash([]);
    },
    
    _drawDateInfo(ctx, centerX) {
        if (AppState.canvasRecords.length === 0) return;
        
        const datesInCanvas = {};
        AppState.canvasRecords.forEach(r => {
            const date = r.timestamp.split(' ')[0];
            datesInCanvas[date] = (datesInCanvas[date] || 0) + 1;
        });
        
        const sortedDates = Object.keys(datesInCanvas).sort();
        
        ctx.fillStyle = '#1890ff';
        ctx.font = '12px Arial';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        
        if (sortedDates.length === 1) {
            const dateText = `${sortedDates[0]} (${datesInCanvas[sortedDates[0]]})`;
            ctx.fillText(dateText, centerX, 10);
        } else if (sortedDates.length <= 3) {
            const dateTexts = sortedDates.map(date => 
                `${date}(${datesInCanvas[date]})`
            );
            ctx.fillText(dateTexts.join(' | '), centerX, 10);
        } else {
            const totalCount = AppState.canvasRecords.length;
            ctx.fillText(`${sortedDates.length} dates, ${totalCount} records`, centerX, 10);
        }
    },
    
    _drawAxisLabels(ctx, centerX, centerY, left, right, top, bottom, size) {
        ctx.fillStyle = '#333';
        const fontSize = size < 600 ? 10 : 12;
        ctx.font = `bold ${fontSize}px Arial`;
        
        ctx.textAlign = 'center';
        ctx.textBaseline = 'alphabetic';
        ctx.fillText('买波', centerX, top - 10);
        ctx.fillText('卖波', centerX, bottom + 20);
        
        ctx.textAlign = 'left';
        ctx.fillText('偏空', left - 26, centerY + 3);
        
        ctx.textAlign = 'right';
        ctx.fillText('偏多', right + 26, centerY + 3);
    },
    
    _drawQuadrantLabels(ctx, left, top, bottom, centerX, halfQuadrant, size) {
        const labelFontSize = size < 600 ? 11 : 13;
        ctx.font = `bold ${labelFontSize}px Arial`;
        ctx.fillStyle = '#666';
        ctx.textAlign = 'center';
        
        ctx.fillText('偏空—买波', left + halfQuadrant / 2, top + 20);
        ctx.fillText('偏多—买波', centerX + halfQuadrant / 2, top + 20);
        ctx.fillText('偏空—卖波', left + halfQuadrant / 2, bottom - 12);
        ctx.fillText('偏多—卖波', centerX + halfQuadrant / 2, bottom - 12);
    },
    
    _drawDataPoints(ctx, centerX, centerY, halfQuadrant, size) {
        const filteredRecords = AppState.canvasRecords.filter(r => 
            RecordManager._matchesQuadrantFilter(r.quadrant)
        );
        
        if (filteredRecords.length === 0) {
            ctx.fillStyle = '#999';
            ctx.font = '16px Arial';
            ctx.textAlign = 'center';
            ctx.fillText('暂无数据', centerX, centerY);
            return;
        }
        
        // 计算点位置
        const pointScale = size < 600 ? 0.85 : (size < 800 ? 0.80 : 0.75);
        const points = filteredRecords.map(record => {
            const xRange = halfQuadrant;
            const yRange = halfQuadrant;
            const x = centerX + (record.direction_score / 5) * xRange * pointScale;
            const y = centerY - (record.vol_score / 5) * yRange * pointScale;
            return { record, x, y };
        });
        
        // 碰撞检测
        const minDistance = size < 600 ? 40 : Math.max(45, size * 0.06);
        this._avoidCollisions(points, minDistance);
        
        // 绘制点
        const symbolFontSize = size < 600 ? 12 : 14;
        points.forEach(({ record, x, y }) => {
            const color = this._getQuadrantColor(record.quadrant);
            
            // 🆕 Gamma 挤压高亮
            if (record.is_squeeze) {
                ctx.beginPath();
                ctx.arc(x, y, symbolFontSize + 10, 0, 2 * Math.PI);
                ctx.fillStyle = 'rgba(255, 59, 48, 0.2)';
                ctx.fill();
                ctx.strokeStyle = '#FF3B30';
                ctx.lineWidth = 2;
                ctx.stroke();
            }
            
            ctx.fillStyle = record.is_squeeze ? '#D32F2F' : color;
            ctx.font = `bold ${symbolFontSize}px "Comic Sans MS", cursive, sans-serif`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(record.symbol, x, y);
            
            // 保存点击区域
            const textWidth = ctx.measureText(record.symbol).width;
            record._canvasX = x;
            record._canvasY = y;
            record._clickRadius = Math.max(textWidth / 2 + 5, 15);
        });
    },
    
    _avoidCollisions(points, minDistance) {
        const maxIterations = 50;
        for (let iter = 0; iter < maxIterations; iter++) {
            let moved = false;
            for (let i = 0; i < points.length; i++) {
                for (let j = i + 1; j < points.length; j++) {
                    const dx = points[j].x - points[i].x;
                    const dy = points[j].y - points[i].y;
                    const dist = Math.sqrt(dx * dx + dy * dy);
                    
                    if (dist < minDistance && dist > 0) {
                        const angle = Math.atan2(dy, dx);
                        const offset = (minDistance - dist) / 2;
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
    },
    
    _getQuadrantColor(quadrant) {
        if (quadrant.includes('偏多') && quadrant.includes('买波')) return '#00C853';
        if (quadrant.includes('偏多') && quadrant.includes('卖波')) return '#FF9500';
        if (quadrant.includes('偏空') && quadrant.includes('买波')) return '#34C759';
        if (quadrant.includes('偏空') && quadrant.includes('卖波')) return '#007AFF';
        return '#9C27B0';
    },
    
    handleClick(event) {
        if (AppState.canvasRecords.length === 0) return;
        
        const rect = AppState.canvas.getBoundingClientRect();
        const x = event.clientX - rect.left;
        const y = event.clientY - rect.top;
        
        const filteredRecords = AppState.canvasRecords.filter(r => 
            RecordManager._matchesQuadrantFilter(r.quadrant)
        );
        
        for (const record of filteredRecords) {
            if (!record._canvasX || !record._canvasY) continue;
            
            const dx = x - record._canvasX;
            const dy = y - record._canvasY;
            const distance = Math.sqrt(dx * dx + dy * dy);
            
            if (distance <= (record._clickRadius || 15)) {
                DetailDrawer.show(record.timestamp, record.symbol);
                return;
            }
        }
    }
};

// ========================================
// 筛选器模块
// ========================================

const FilterManager = {
    toggleQuadrantDropdown() {
        const dropdown = document.getElementById('quadrantDropdown');
        dropdown.classList.toggle('open');
    },
    
    handleQuadrantChange(e) {
        const allCheckbox = document.getElementById('quad-all');
        const checkboxes = [
            document.getElementById('quad-1'),
            document.getElementById('quad-2'),
            document.getElementById('quad-3'),
            document.getElementById('quad-4'),
            document.getElementById('quad-5')
        ];
        
        if (e.target.id === 'quad-all') {
            if (allCheckbox.checked) {
                checkboxes.forEach(cb => cb.checked = false);
                AppState.selectedQuadrants = ['全部'];
            }
        } else {
            allCheckbox.checked = false;
            AppState.selectedQuadrants = checkboxes
                .filter(cb => cb.checked)
                .map(cb => cb.value);
            
            if (AppState.selectedQuadrants.length === 0) {
                allCheckbox.checked = true;
                AppState.selectedQuadrants = ['全部'];
            }
        }
        
        this.updateDisplay();
        RecordManager.filterRecords();
    },
    
    updateDisplay() {
        const display = document.getElementById('quadrantSelected');
        
        if (AppState.selectedQuadrants.includes('全部')) {
            display.textContent = '全部';
        } else if (AppState.selectedQuadrants.length === 0) {
            display.textContent = '全部';
        } else {
            display.textContent = AppState.selectedQuadrants.join('、');
        }
    }
};
// ========================================
// Part 7: 财报开关处理
// ========================================

const EarningsToggle = {
    async handle(checkbox) {
        const date = checkbox.getAttribute('data-date');
        const ignoreEarnings = checkbox.checked;
        
        AppState.earningsToggles[date] = ignoreEarnings;
        
        MessageSystem.show(`正在重新计算 ${date} 的数据...`, 'warning');
        
        const dateRecords = AppState.allRecords.filter(r => 
            r.timestamp.startsWith(date)
        );
        
        if (dateRecords.length === 0) {
            MessageSystem.show('该日期没有数据', 'error');
            return;
        }
        
        const rawDataList = dateRecords.map(r => r.raw_data);
        
        try {
            const response = await fetch(`/api/analyze?ignore_earnings=${ignoreEarnings}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ records: rawDataList })
            });
            
            const result = await response.json();
            
            if (response.ok && result.results) {
                // 标记财报事件状态
                result.results.forEach(r => {
                    r.earnings_event_enabled = ignoreEarnings;
                });
                
                // 更新记录
                AppState.allRecords = AppState.allRecords.filter(r => 
                    !r.timestamp.startsWith(date)
                );
                AppState.allRecords.push(...result.results);
                
                // 更新画布（如果包含该日期）
                const hasDateInCanvas = AppState.canvasRecords.some(r => 
                    r.timestamp.startsWith(date)
                );
                
                if (hasDateInCanvas) {
                    let filteredResults = result.results;
                    
                    if (!AppState.selectedQuadrants.includes('全部')) {
                        filteredResults = result.results.filter(record => 
                            RecordManager._matchesQuadrantFilter(record.quadrant)
                        );
                    }
                    
                    AppState.canvasRecords = AppState.canvasRecords.filter(r => 
                        !r.timestamp.startsWith(date)
                    );
                    AppState.canvasRecords.push(...filteredResults);
                    QuadrantCanvas.draw();
                }
                
                RecordRenderer.render();
                MessageSystem.show(`已${ignoreEarnings ? '开启' : '关闭'}财报事件计算`, 'success');
            } else {
                MessageSystem.show(`重新计算失败: ${result.error || '未知错误'}`, 'error');
                checkbox.checked = !ignoreEarnings;
                AppState.earningsToggles[date] = !ignoreEarnings;
            }
        } catch (e) {
            MessageSystem.show(`重新计算失败: ${e.message}`, 'error');
            checkbox.checked = !ignoreEarnings;
            AppState.earningsToggles[date] = !ignoreEarnings;
        }
    }
};

// ========================================
// 应用初始化
// ========================================

const App = {
    init() {
        // 加载数据
        RecordManager.loadRecords();
        RecordManager.loadDates();
        
        // 绑定事件
        this._bindEvents();
        
        // 响应式画布
        window.addEventListener('resize', () => {
            if (AppState.canvas) {
                AppState.canvas.width = AppState.canvas.offsetWidth;
                AppState.canvas.height = AppState.canvas.offsetHeight;
                QuadrantCanvas.draw();
            }
        });
        
        // 关闭下拉菜单（点击外部）
        document.addEventListener('click', (e) => {
            const filter = document.querySelector('.quadrant-filter');
            const dropdown = document.getElementById('quadrantDropdown');
            if (filter && !filter.contains(e.target)) {
                dropdown.classList.remove('open');
            }
        });
    },
    
    _bindEvents() {
        // 按钮事件
        document.getElementById('btnAnalyze').addEventListener('click', 
            () => DrawerManager.openInputDrawer()
        );
        document.getElementById('btnSubmitAnalyze').addEventListener('click', 
            () => DataAnalyzer.analyze()
        );
        document.getElementById('btnCancelAnalyze').addEventListener('click', 
            () => DrawerManager.closeInputDrawer()
        );
        document.getElementById('btnCloseInputDrawer').addEventListener('click', 
            () => DrawerManager.closeInputDrawer()
        );
        document.getElementById('btnClear').addEventListener('click', 
            () => RecordManager.clearCanvas()
        );
        
        // 筛选器
        document.getElementById('dateFilterSelect').addEventListener('change', 
            () => RecordManager.filterRecords()
        );
        document.getElementById('quadrantSelectBtn').addEventListener('click', 
            () => FilterManager.toggleQuadrantDropdown()
        );
        
        // 抽屉
        document.getElementById('detailDrawerOverlay').addEventListener('click', 
            () => DrawerManager.closeDetailDrawer()
        );
        document.getElementById('btnCloseDetailDrawer').addEventListener('click', 
            () => DrawerManager.closeDetailDrawer()
        );
        document.getElementById('inputDrawerOverlay').addEventListener('click', 
            () => DrawerManager.closeInputDrawer()
        );
        
        // 象限筛选
        const allCheckbox = document.getElementById('quad-all');
        const checkboxIds = ['quad-1', 'quad-2', 'quad-3', 'quad-4', 'quad-5'];
        
        if (allCheckbox) {
            allCheckbox.addEventListener('change', 
                (e) => FilterManager.handleQuadrantChange(e)
            );
        }
        
        checkboxIds.forEach(id => {
            const cb = document.getElementById(id);
            if (cb) {
                cb.addEventListener('change', 
                    (e) => FilterManager.handleQuadrantChange(e)
                );
            }
        });
    }
};

// ========================================
// 启动应用
// ========================================

window.onload = () => {
    App.init();
};

// ========================================
// 向后兼容的全局函数（供HTML调用）
// ========================================

// 如果HTML中有内联onclick事件，提供兼容性
window.showMessage = (text, type) => MessageSystem.show(text, type);
window.openInputDrawer = () => DrawerManager.openInputDrawer();
window.closeInputDrawer = () => DrawerManager.closeInputDrawer();
window.openDetailDrawer = () => DrawerManager.openDetailDrawer();
window.closeDetailDrawer = () => DrawerManager.closeDetailDrawer();
window.analyzeData = () => DataAnalyzer.analyze();
window.loadRecords = () => RecordManager.loadRecords();
window.loadDates = () => RecordManager.loadDates();
window.clearCanvas = () => RecordManager.clearCanvas();
window.filterRecords = () => RecordManager.filterRecords();