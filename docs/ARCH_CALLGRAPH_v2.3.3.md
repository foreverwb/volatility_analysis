# ARCH Callgraph v2.3.3

## Scope
- Read-only inspection targets:
  - Backend: `app.py`, `core/analyzer.py`, `core/scoring.py`, `core/metrics.py`, `core/confidence.py`, `core/dynamic_params.py`, `core/guards.py`, `core/posture.py`, `bridge/builders.py`, `bridge/micro_templates.py`
  - Frontend: `templates/index.html`, `static/js/api.js`, `static/js/records.js`, `static/js/drawer.js`

## Entry Points To `calculate_analysis`
- `/api/analyze`:
  - `app.py:271` route handler `analyze()`
  - Calls `calculate_analysis(...)` at `app.py:357`
- `/api/analyze/stream`:
  - `app.py:480` route handler `analyze_stream()`
  - Calls `calculate_analysis(...)` at `app.py:584`

Both routes preprocess IV/OI data, collect per-symbol history scores, then call `core/analyzer.py::calculate_analysis`.

## `calculate_analysis` Pipeline (v2.3.3)

Function entry: `core/analyzer.py:49`

### Stage 1: Clean / Normalize
- `clean_record(data)` -> `core/analyzer.py:78`
- `normalize_dataset([cleaned])[0]` -> `core/analyzer.py:79`
- `get_dynamic_thresholds(symbol, cfg)` -> `core/analyzer.py:82`

### Stage 2: Validation
- `validate_record(normed, effective_cfg)` -> `core/analyzer.py:84`
- Outputs:
  - `data_quality`
  - `data_quality_issues`

### Stage 3: Metrics
- VIX fetch:
  - `get_vix_with_fallback(...)` -> `core/analyzer.py:90`
- Dynamic params:
  - `get_global_cache().get_data()` -> `core/analyzer.py:99-100`
  - `compute_all_dynamic_params(...)` -> `core/analyzer.py:102`
  - `validate_dynamic_params(...)` -> `core/analyzer.py:109`
- Core metric functions:
  - `compute_spot_vol_correlation_score` -> `core/analyzer.py:118`
  - `detect_squeeze_potential` -> `core/analyzer.py:119`
  - `compute_term_structure` -> `core/analyzer.py:120`
  - `compute_term_structure_ratios` -> `core/analyzer.py:121`
  - `detect_fear_regime` -> `core/analyzer.py:122`
  - `compute_active_open_ratio` (if not `skip_oi`) -> `core/analyzer.py:128`

### Stage 4: Scoring
- `compute_direction_score(...)` -> `core/analyzer.py:132`
- `compute_vol_score(...)` -> `core/analyzer.py:139`

### Stage 5: Confidence
- `map_liquidity(...)` -> `core/analyzer.py:152`
- `map_confidence(...)` -> `core/analyzer.py:153`
- `penalize_extreme_move_low_vol(...)` -> `core/analyzer.py:163`

### Stage 6: Strategy / Quadrant
- `map_direction_pref(dir_score)` -> `core/analyzer.py:147`
- `map_vol_pref(vol_score, effective_cfg)` -> `core/analyzer.py:148`
- `combine_quadrant(dir_pref, vol_pref)` -> `core/analyzer.py:149`
- `get_strategy_info(quadrant, liquidity, is_squeeze=...)` -> `core/analyzer.py:166`

### Stage 7: Guards / Posture
- Posture computation:
  - `compute_posture_5d(...)`
- **Single authority decision (Phase F / Option A):**
  - `evaluate_trade_permission(..., posture_5d=...)`
  - authority: `core.guards.evaluate_trade_permission`
  - outputs: `trade_permission`, `permission_reasons`, `disabled_structures`, `permission_trace`, `governance_authority`
- Watchlist guidance:
  - `build_watchlist_guidance(...)`

### Stage 8: Bridge / Micro-template
- Build initial `result` with current permission fields -> `core/analyzer.py:283-368`
- Build `bridge_payload` (includes current permission fields) -> `core/analyzer.py:371-413`
- Select micro template:
  - `select_micro_template(bridge_payload, effective_cfg)` -> `core/analyzer.py:415`
- Phase F governance:
  - micro-template is advisory-only (`governance_mode=ADVISORY_ONLY`)
  - micro-template does **not** write permission fields
- Build bridge snapshot:
  - `build_bridge_snapshot(bridge_payload, effective_cfg)` -> `core/analyzer.py:430`
  - Attach to output:
    - `result["bridge"] = bridge_snapshot` -> `core/analyzer.py:432`
    - `result["micro_template"] = micro_template` -> `core/analyzer.py:433`

### Stage 9: Cache
- Conditional cache update:
  - `update_cache_with_record(normed, vix_value, dynamic_params, cache)` -> `core/analyzer.py:439`

---

## `trade_permission` Write / Override Map (Phase F)

### Timeline (single-authority chain)
1. **Guards唯一写入**
   - File: `core/guards.py`
   - Function: `evaluate_trade_permission(...)`
   - Semantics: final decision from quality/data_confidence/posture/fear/earnings/short-vol guards.
   - Traceability: `permission_reasons` + `permission_trace` + `governance_authority`.

2. **Result serialization (镜像，不新增裁决)**
   - File: `core/analyzer.py`
   - Function: `calculate_analysis(...)`
   - `result`/`bridge_payload`仅复制 guards 输出。

3. **micro-template advisory-only**
   - File: `bridge/micro_templates.py`
   - Function: `select_micro_template(...)`
   - 不返回 `trade_permission/permission_reasons/disabled_structures`。
   - 仅返回模板建议字段（`template/dte_bias/risk_overlays/...`）。

4. **Bridge snapshot pass-through**
   - File: `bridge/builders.py`
   - Function: `build_bridge_snapshot(...)`
   - `execution_state`仅透传 guards 权限字段与治理元数据。

## Frontend Consumption Path (for audit fields)

### Script load order
- `templates/index.html:154-161`:
  - `/static/js/state.js`
  - `/static/js/ui.js`
  - `/static/js/api.js`
  - `/static/js/records.js`
  - `/static/js/drawer.js`
  - `/static/js/canvas.js`
  - `/static/js/filter.js`
  - `/static/js/main.js`

### Data flow
1. `api.js::analyzeData()` posts to `/api/analyze/stream` (`static/js/api.js:38`)
2. Completion event calls `loadRecords()` (`static/js/api.js:206`)
3. `loadRecords()` fetches `/api/records` (`static/js/api.js:252`)
4. `records.js::renderRecordsList()` renders summary cards (`static/js/records.js:54`)
5. Click row -> `window.showDrawer(...)` (`static/js/records.js:246`)
6. `drawer.js::showDrawer(...)` renders details (`static/js/drawer.js:96`)

### Current audit-field rendering status
- `trade_permission`, `permission_reasons`, `disabled_structures`, `bridge`, `micro_template`:
  - Present in backend result
  - **Not displayed** in current drawer template (`static/js/drawer.js`)
- Displayed examples:
  - `active_open_ratio`, `flow_bias` (`static/js/drawer.js:120-123`)
  - `term_structure_ratio` (`static/js/drawer.js:117`)

## Governance Observation (current state)
- Current permission governance is **single-writer** (Option A):
  - `core.guards.evaluate_trade_permission` is the only decision writer.
  - analyzer/bridge are serialization-only for permission fields.
  - micro-template is advisory-only and cannot override permission.
