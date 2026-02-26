# v2.4 Upgrade Notes

## Phase B: Remove 清单（R1 / R2）

### 章节对齐
- R1 对齐：
  - `v2.4_upgrade.md` 第 3.1 节《缺失值处理重构》
  - `v2.4_upgrade.md` 第 6.1 节《单通道置信度机制》
- R2 对齐：
  - `v2.4_upgrade.md` 第 7.1 节《事件模块降级为标签层》
  - `v2.4_upgrade.md` 第 8.1 节《象限与策略模板解耦》

### R1 已落实（缺失值治理，移除常数注入）

#### 代码点与替代机制
- `core/metrics.py`
  - `compute_ivrv / compute_iv_ratio / compute_regime_ratio`
  - 旧：缺失时回退 `0.0/1.0`
  - 新：缺失时返回 `None`，并写入 `missing_features`
- `core/metrics.py`
  - `compute_active_open_ratio`
  - 旧：缺失 ΔOI 回退数值
  - 新：返回 `None` + 记录缺失
- `core/analyzer.py`
  - `derived_metrics` 的 `ivrv_ratio/ivrv_diff/ivrv_log/regime_ratio`
  - 旧：可被默认常数撑出结果
  - 新：缺失直接 `None`；`missing_features` 显式输出
- `core/scoring.py` + `core/factors.py`
  - 旧：缺失字段可能通过默认值间接入分
  - 新：缺失因子 `value=None`，评分层跳过无效项，不做默认补值
- `core/confidence.py`
  - 缺失影响集中在 `data_confidence` 分量，不再通过伪造输入回流 score

#### API 输出兼容
- 保留旧字段，新增解释字段：
  - `missing_features`
  - `score_breakdown`
  - `confidence_breakdown`

### R2 已落实（事件治理，移除 squeeze 覆盖式策略指令）

#### 代码点与替代机制
- `core/strategy.py::get_strategy_info`
  - 旧：`is_squeeze=True` 时覆盖为“强烈建议 Long Call”语义
  - 新：仅追加事件提示/风险提示，不覆盖策略主结构
- `core/analyzer.py`
  - 新增 `event_tags`
  - `is_squeeze=True` 时至少输出 `"POTENTIAL_GAMMA_SQUEEZE"`
- `core/guards.py::build_watchlist_guidance`
  - squeeze 仅进入 `watch_triggers/what_to_monitor` 提示，不改写象限/策略模板

### 前端同步改造点（records.js / drawer.js）
- `static/js/records.js`
  - 新增列表级审计标记：
    - 缺失字段数量 badge（`missing_features`）
    - 治理模式 badge（`permission_governance.mode`）
- `static/js/drawer.js`
  - 新增「治理与缺失审计」区块：
    - `event_tags`
    - `missing_features`
    - `trade_permission / permission_reasons`
    - `permission_governance.mode / authority`
  - 新增 `score_breakdown` 摘要区块：
    - 方向/波动基础分、调整系数
  - 新增 `confidence_breakdown` 摘要区块：
    - 总置信度、数据置信度、核心分量分数
  - `derived_metrics` 的 `None` 前端显示统一为 `N/A`，避免 UI 文本崩坏

## Phase F: 治理链路唯一化（对齐第 6/8/9 章）

### 决策
- 采用 **A 方案**：`guards` 为唯一裁决者。
- 权威写入函数：`core.guards.evaluate_trade_permission`。
- `micro-template` 降级为建议层（advisory-only），不再写入/覆盖：
  - `trade_permission`
  - `permission_reasons`
  - `disabled_structures`

### 代码落地点
- `core/guards.py`
  - 合并 posture 风险门控（`COUNTERTREND/ONE_DAY_SHOCK/CHOP`）到 guards。
  - 返回治理审计字段：
    - `governance_mode: A_GUARDS_SINGLE_AUTHORITY`
    - `governance_authority: core.guards.evaluate_trade_permission`
    - `governance_reason_codes`
    - `permission_trace`
- `core/analyzer.py`
  - 删除 analyzer 内 posture overlay 对权限字段的二次写入。
  - 删除 micro-template 回写权限字段逻辑。
  - 新增 `permission_governance`（authority/mode/reason_codes/trace）。
- `bridge/micro_templates.py`
  - 只返回建议字段（模板、DTE 倾向、风险提示、advisory reason codes）。
  - 新增 `governance_mode=ADVISORY_ONLY`, `permission_impact=none`。

### 审计约束
- 最终权限字段只允许来源于 guards：
  - `trade_permission`
  - `permission_reasons`
  - `disabled_structures`
- reason code 追踪路径：
  1. `permission_reasons`（最终码）
  2. `permission_governance.reason_codes`
  3. `permission_governance.trace[].code`（逐步轨迹）

### 兼容性
- `/api/analyze` 旧字段全部保留。
- 新增解释字段（不破坏兼容）：
  - `permission_governance`

## Phase G: 决策映射中性缓冲带（对齐第 8 章）

### 变更
- `core/strategy.py`
  - `map_direction_pref` 新增中性缓冲带：
    - `direction_pref_threshold`
    - `direction_pref_neutral_buffer`
  - `map_vol_pref` 新增中性缓冲带：
    - `vol_pref_neutral_buffer_ratio`
    - `vol_pref_neutral_buffer_min`
- `combine_quadrant` 输出枚举保持不变：
  - `偏多—买波 / 偏多—卖波 / 偏空—买波 / 偏空—卖波 / 中性/待观察`

### 稳定性
- 临界区小扰动优先映射为 `中性`，降低跨象限跳变频率。
- 监控触发器里的“阈值越线目标象限”使用无缓冲投影，不影响触发语义。
