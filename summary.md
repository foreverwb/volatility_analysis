# 期权策略量化分析系统 v2.4（治理版）—— summary

> 版本定位：**v2.4 是一次“结构治理升级”**，目标不是在既有规则上继续堆叠，而是把 v2.3.3 中的高自由度、同源因子冗余、缺失值污染、事件覆盖式决策等问题，转化为可审计、可约束、可复现的工程结构。

---

## 1. 核心目标与设计原则（v2.4）

### 1.1 v2.4 要解决的问题（从 v2.3.3 继承的结构风险）

1. **同源变量多重表达**  
   - 方向侧：成交量/名义金额/Put%/CallPut/相对量等多个投影并行叠加，容易重复计分。  
   - 波动侧：IV30/HV20 的比率/对数/差值等多种变换同时入模，属于同源重复表达。

2. **动态参数与评分输入重叠**  
   - βₜ/λₜ/αₜ 若直接读取与 DirScore/VolScore 同源的底层字段，会形成“跨层二次放大”。

3. **修正项乘性链路过长**  
   - 结构/跨期/流动性/恐慌/缺失惩罚等若以乘法叠加，会把评分系统变成难以治理的拟合管道。

4. **缺失值常数填充是结构污染源**  
   - 尤其对 IV/HV 族（比率/对数）用 0 填充，会产生物理不合理输入并制造伪信号。

5. **事件模块（Gamma Squeeze）对策略输出“覆盖式指导”**  
   - 事件应作为标签/提示，而不是替代评分体系的强制动作。

---

## 2. 系统结构总览（模块分层）

v2.4 的信息流可以抽象为：

1. **数据层**：期权量价/OI/IV/HV/IVR/期限结构 + VIX（市场环境）  
2. **清洗标准化层**：字段类型转换、百分比尺度归一、边界约束  
3. **因子子空间层（Phase C）**：把底层字段压缩为少量高层因子，并显式标注缺失  
4. **评分层**：DirScore / VolScore 由高层因子组合得到（默认归一到 [-1, 1]）  
5. **动态参数层（Phase D）**：βₜ/λₜ/αₜ 仅作为“整体调节器”，受预算与收缩约束  
6. **置信度单通道（Phase E）**：所有修正只进入 confidence，不允许改写 score  
7. **映射层（Phase G）**：方向偏好/波动偏好 → 四象限（+ 中性/待观察）  
8. **建议层（Phase F）**：micro-template 只输出 advisory，不覆盖交易权限  
9. **治理裁决层（Phase H）**：trade_permission / disabled_structures / watchlist guidance

---

## 3. 因子子空间（Phase C）

### 3.1 Direction 因子空间（3 个子空间）

| 因子名 | 经济含义 | 主要输入字段（示例） | 缺失策略 |
|---|---|---|---|
| price_momentum | 价格动量与放量确认 | PriceChgPct, RelVolTo90D | 缺失则该因子不计入 |
| flow_imbalance | 订单流方向强度（单因子聚合） | Call/Put Volume, Notional, PutPct 等（聚合） | 缺失则该因子不计入 |
| positioning | 仓位/结构形态（解释友好） | OI_PctRank, Single/Multi/ContingentPct, ActiveOpenRatio 等（聚合） | 缺失则该因子不计入 |

> 目标：把“同源字段的多种投影”压缩为少量可解释因子，避免重复计分。

### 3.2 Volatility 因子空间（4 个子空间）

| 因子名 | 经济含义 | 主要输入字段（示例） | 缺失策略 |
|---|---|---|---|
| vol_risk_premium | IV 相对 HV 的风险溢价 | IV30, HV20（以 ln(IV30/HV20) 聚合） | 若 IV/HV 缺失或 ≤0，则该因子缺失 |
| vol_level | 波动“价位/拥挤度” | IVR + IV30ChgPct | 缺失则该部分不计入 |
| term_structure | 期限结构形态 | IV7, IV30, IV60, IV90（由形态分类/调整表达） | 缺失则该因子缺失 |
| earnings_event | 财报事件临近度（可选、上限约束） | Earnings | 无财报信息则视为 0 |

---

## 4. 评分层（DirScore / VolScore）

### 4.1 默认权重（可配置，但治理上建议稳定）

- Direction：price_momentum 0.45 / flow_imbalance 0.35 / positioning 0.20  
- Volatility：vol_risk_premium 0.50 / vol_level 0.25 / term_structure 0.20 / earnings_event 0.05

评分计算是**加权平均**（仅对有效因子归一），输出默认落在 **[-1, 1]**。

### 4.2 动态参数（Phase D）作为“整体调节器”

- DirScore 仅允许被整体乘以 `1 + Δ(beta_t)`（Δ 受预算约束）  
- VolScore 仅允许被整体乘以 `1 + Δ(lambda_t, alpha_t)`（Δ 受预算约束）  
- **禁止**动态参数再读取与评分同源的底层字段并重复计分。

---

## 5. 置信度单通道（Phase E）

v2.4 的原则是：**score 只表达信号内容；所有修正只进入 confidence 通道**。

### 5.1 置信度组成（单通道聚合）

- strength_confidence：由 |dir_score| 与 |vol_score| 的强度映射而来  
- data_confidence：由 missing_features + data_quality（校验器）决定  
- execution_confidence：由流动性分级决定  
- consistency_confidence：由近 N 日 score 一致性决定  
- structure_confidence：**解释层**保留但默认不参与最终加权（避免二次计分）

---

## 6. 映射层（Phase G）：偏好 → 四象限

### 6.1 方向偏好（direction_pref）

使用阈值 + 中性缓冲带（避免临界跳变）：

- `upper = direction_pref_threshold + direction_pref_neutral_buffer`
- dir_score ≥ upper → **偏多**
- dir_score ≤ -upper → **偏空**
- 否则 → **中性**

**v2.4 默认配置（建议值）**
- direction_pref_threshold = 0.50  
- direction_pref_neutral_buffer = 0.05  
- ⇒ 有效触发阈值 upper = 0.55

### 6.2 波动偏好（vol_pref）

为避免把“惩罚阈值”与“偏好阈值”混用，v2.4 引入独立键：

- `vol_pref_threshold`：波动偏好阈值（建议比 penalty 阈值更贴合 vol_score 的归一尺度）
- `buffer = max(|vol_pref_threshold|*ratio, min)`
- `upper = |vol_pref_threshold| + buffer`
- vol_score ≥ upper → **买波**
- vol_score ≤ -upper → **卖波**
- 否则 → **中性**

**v2.4 默认配置（建议值）**
- vol_pref_threshold = 0.07  
- vol_pref_neutral_buffer_ratio = 0.25  
- vol_pref_neutral_buffer_min = 0.05  
- ⇒ 有效触发阈值 upper ≈ 0.12

### 6.3 四象限合成（quadrant）

- 当 `direction_pref` 与 `vol_pref` **均非中性**：  
  quadrant ∈ {偏多—买波, 偏多—卖波, 偏空—买波, 偏空—卖波}
- 否则：**中性/待观察**

### 6.4 映射可达性约束（治理校验）

配置校验必须保证：  
- `upper` 不得超过 score 的可达上界（否则系统会“长期塌缩为中性/待观察”）。  
- v2.4 在配置校验中加入 reachability check，防止阈值设置不合理导致四象限失效。

---

## 7. 事件模块（Gamma Squeeze）降级为标签

- Gamma Squeeze 检测仍存在（作为 `event_tags`）  
- **不允许**用事件标签覆盖四象限与交易权限  
- 事件仅提供风险/机会提示与监控点（watchlist）

---

## 8. 输出结构（payload 审计友好）

每次分析输出应包含：

- scores：direction_score / vol_score  
- prefs：direction_bias / vol_bias / quadrant  
- confidence：label + breakdown（包含 data_confidence 与 missing_features）  
- governance：trade_permission / disabled_structures / watch_triggers  
- advisory：micro_template（仅建议层，不覆盖 permission）  
- raw_data：保留关键原始字段快照（便于复盘与数据修复）

---

## 9. v2.4 的 Keep / Optimize / Remove（治理清单）

### ✅ Keep
- 数据源覆盖与标准化框架（统一尺度、限幅、平滑）  
- 期限结构作为独立维度  
- 输出审计结构（factors / breakdown / missing_features）

### 🔧 Optimize
- 因子子空间：控制同源复用并显式 declared_overlaps  
- 动态参数：预算 + shrink + 仅高层输入  
- 映射层：阈值可达性校验 + watchlist 触发器一致性  
- 交易权限：事件/姿态只做约束或提示，不做覆盖式决策

### ❌ Remove
- 缺失值常数填充（尤其 IV/HV 填 0）  
- Gamma Squeeze → “强烈建议某单一策略”的覆盖式输出

---
