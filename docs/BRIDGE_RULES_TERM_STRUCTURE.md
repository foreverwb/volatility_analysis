# BRIDGE_RULES_TERM_STRUCTURE

Version: v1.0  
Scope: `volatility_analysis` → `vol_quant_workflow` / `swing_workflow` term‑structure bridge

---

## 0. Goal

Unify how the **meso** layer (volatility_analysis) describes option term structure (IV7 / IV30 / IV60 / IV90) and expose it as a stable, machine‑readable contract that both **micro** layers consume:

- `vol_quant_workflow` – vol / options micro
- `swing_workflow` – swing trading micro

The bridge must:

1. Compute and classify term structure on the meso side.
2. Output a **structured snapshot** (ratios + label + horizon biases).
3. Let micro layers **adjust horizons (DTE / window)** based only on these bridge fields, not on ad‑hoc hard‑coded rules.

---

## 1. Inputs (from volatility_analysis)

For each symbol + date, after cleaning, we assume these fields exist (when data is available):

- `IV7`, `IV30`, `IV60`, `IV90` – implied volatilities for ~7 / 30 / 60 / 90 days.
- `VIX` (optional but recommended).
- `IVR` (Implied Vol Rank, 0–100).
- `HV20` (20‑day realized vol).
- Any existing derived metrics that use these IVs (VRP, term structure adjustments, etc.).

The bridge layer in `volatility_analysis` must compute:

```python
ratios = {
  "7_30":  IV7 / IV30,   # if both available
  "30_60": IV30 / IV60,
  "60_90": IV60 / IV90,
  "30_90": IV30 / IV90,
}
```

Missing denominators or invalid numbers → that ratio is omitted.

---

## 2. Term structure classification (meso canonical states)

Using the 7_30 / 30_60 / 60_90 ratios (when available), the bridge classifies term structure into **one** of these labels:

- `Full inversion`       – 全面倒挂
- `Short‑term inversion` – 短期倒挂
- `Mid‑term bulge`       – 中期突起
- `Far‑term elevated`    – 远期过高
- `Short‑term low`       – 短期低位
- `Normal steep`         – 正常陡峭
- `N/A`                  – 数据不足或无法分类

### 2.1 Classification rules

Let:

- `short = ratios["7_30"]`   (IV7 / IV30)
- `mid   = ratios["30_60"]`  (IV30 / IV60)
- `long  = ratios["60_90"]`  (IV60 / IV90)

If any of `short, mid, long` is missing → label = `"N/A"`.

Otherwise:

1. **Full inversion（全面倒挂）**  
   `short > 1.05 and mid > 1.05 and long > 1.05`

2. **Short‑term inversion（短期倒挂）**  
   `short > 1.05 and mid <= 1.0`

3. **Mid‑term bulge（中期突起）**  
   `mid > 1.05 and short <= 1.02 and long <= 1.0`

4. **Far‑term elevated（远期过高）**  
   `long > 1.05 and mid <= 1.0`

5. **Short‑term low（短期低位）**  
   `short < 0.9 and mid >= 0.95`

6. **Normal steep（正常陡峭）**  
   `short < 1.0 and mid < 1.0 and long < 1.0`  
   or **fallback** if none of the above matched.

If all three ratios are present but none rule matches, treat as `Normal steep`.

---

## 3. Bridge output: TermStructureSnapshot

The meso → micro bridge must expose a **structured object**, e.g.:

```json
"term_structure": {
  "ratios": {
    "7_30": 0.98,
    "30_60": 1.03,
    "60_90": 1.07,
    "30_90": 1.05
  },
  "label": "Mid-term bulge",
  "ratio_30_90": 1.05,
  "adjustment": -0.18,
  "horizon_bias": {
    "short": -0.2,
    "mid":   0.6,
    "long":  0.3
  },
  "state_flags": {
    "full_inversion":  false,
    "short_inversion": false,
    "mid_bulge":       true,
    "far_elevated":    false,
    "short_low":       false,
    "normal_steep":    false
  }
}
```

Notes:

- `ratios` – as computed above (missing keys simply omitted).
- `label` – one of the states defined in §2.
- `ratio_30_90` – IV30 / IV90 when available (float, nullable).
- `adjustment` – of type `float`, representing any existing term‑structure adjustment that VA already computes for vol score (if not available, default 0.0).
- `horizon_bias` – **new**: a vector controlling short/mid/long horizon preference in micro layers.
- `state_flags` – convenience booleans for consumption, derived from `label`.

---

## 4. Horizon bias: semantic meaning & numeric ranges

`horizon_bias` is a dict:

```python
{
  "short": float,  # bias for near-term horizon
  "mid":   float,  # bias for mid-term horizon
  "long":  float   # bias for long-term horizon
}
```

Semantic:

- Values in range roughly **[-1.0, +1.0]**.
- Positive → *extend/emphasize* that horizon.
- Negative → *compress/de‑emphasize* that horizon.
- Magnitude is relative; micro layers may apply an additional scale factor.

### 4.1 Recommended mapping from label → horizon_bias

These are **default values**; actual numbers can be made configurable.

#### Full inversion（全面倒挂）

All segments > 1.05 (front elevated across curve).

```json
"horizon_bias": {
  "short": -0.8,
  "mid":   -0.2,
  "long":   0.7
}
```

- Short: avoid leaning too heavily on near‑term only.
- Long: favor longer horizons (e.g., 60–90D) for structuring risk.

#### Short‑term inversion（短期倒挂）

Short > 1.05, mid <= 1.0.

```json
"horizon_bias": {
  "short": -0.6,
  "mid":    0.3,
  "long":   0.2
}
```

- Shift some attention away from ultra‑near‑term, toward 30–60D.

#### Mid‑term bulge（中期突起）

Mid > 1.05, short <= 1.02, long <= 1.0.

```json
"horizon_bias": {
  "short": -0.2,
  "mid":    0.6,
  "long":   0.3
}
```

- Use mid bucket (30–60D) as the main structural focus.

#### Far‑term elevated（远期过高）

Long > 1.05, mid <= 1.0.

```json
"horizon_bias": {
  "short": -0.1,
  "mid":    0.0,
  "long":   0.7
}
```

- Long‑term risk premium is elevated; favor calendars/diagonals.

#### Short‑term low（短期低位）

Short < 0.9, mid >= 0.95.

```json
"horizon_bias": {
  "short":  0.7,
  "mid":    0.2,
  "long":   0.0
}
```

- Short‑term gamma is relatively cheap; more weight on short bucket.

#### Normal steep（正常陡峭）

Default / fallback.

```json
"horizon_bias": {
  "short": 0.0,
  "mid":   0.0,
  "long":  0.0
}
```

---

## 5. state_flags derivation

Given `label`, derive:

```python
def build_state_flags(label: str) -> dict[str, bool]:
    return {
        "full_inversion":  "Full inversion" in label or "全面倒挂" in label,
        "short_inversion": "Short-term inversion" in label or "短期倒挂" in label,
        "mid_bulge":       "Mid-term bulge" in label or "中期突起" in label,
        "far_elevated":    "Far-term elevated" in label or "远期过高" in label,
        "short_low":       "Short-term low" in label or "短期低位" in label,
        "normal_steep":    "Normal steep" in label or "正常陡峭" in label,
    }
```

---

## 6. Implementation guidance: volatility_analysis

### 6.1 New helper: build_term_structure_snapshot

Create a helper, e.g. `build_term_structure_snapshot(rec, cfg) -> dict` that:

1. Calls `compute_term_structure_ratios(rec)` to get ratios.
2. Calls existing classification (`_classify_term_structure`) to get `label`.
3. Computes `ratio_30_90 = ratios.get("30_90")` when available.
4. Calls any existing term‑structure adjustment logic to get `adjustment` (else 0.0).
5. Builds `horizon_bias` as per §4.1.
6. Builds `state_flags` as per §5.
7. Returns the full `TermStructureSnapshot` dict.

Attach it to the per‑symbol snapshot:

```python
snapshot["term_structure"] = build_term_structure_snapshot(normed_record, cfg)
```

### 6.2 API / output contract

Any API (REST / CLI JSON) that is consumed by micro layers must expose `term_structure` in exactly this shape.  
Micro layers must not parse descriptive strings to reconstruct ratios or biases.

---

## 7. Implementation guidance: vol_quant_workflow

### 7.1 Extend MarketContext

Extend the context model to include term‑structure fields:

```python
@dataclass
class MarketContext:
    symbol: str
    as_of: str
    # existing fields...
    term_structure_label: Optional[str] = None
    term_structure_ratios: dict[str, float] = field(default_factory=dict)
    term_structure_adjustment: float = 0.0
    term_horizon_bias: dict[str, float] = field(default_factory=dict)
```

Populate from VA API response:

```python
ts = snapshot.get("term_structure", {})
ctx.term_structure_label = ts.get("label")
ctx.term_structure_ratios = ts.get("ratios") or {}
ctx.term_structure_adjustment = ts.get("adjustment", 0.0)
ctx.term_horizon_bias = ts.get("horizon_bias") or {}
```

### 7.2 Use term_horizon_bias to tilt DTE ranges

In `generate_dynamic_config(ctx, cfg)`:

```python
bias = ctx.term_horizon_bias or {}

dyn.dte_short = adjust_dte_range(dyn.dte_short, bias.get("short", 0.0), cfg.term_bias_scale)
dyn.dte_mid   = adjust_dte_range(dyn.dte_mid,   bias.get("mid",   0.0), cfg.term_bias_scale)
dyn.dte_long  = adjust_dte_range(dyn.dte_long,  bias.get("long",  0.0), cfg.term_bias_scale)
```

With:

```python
def adjust_dte_range(rng: tuple[int, int], bias: float, scale: float) -> tuple[int, int]:
    factor = 1.0 + bias * scale   # e.g. scale = 0.25
    lo, hi = rng
    lo = max(1, int(round(lo * factor)))
    hi = max(lo + 1, int(round(hi * factor)))
    return (lo, hi)
```

---

## 8. Implementation guidance: swing_workflow

### 8.1 Extend MarketStateCalculator input

Update `MarketStateCalculator.calculate_fetch_params` (or equivalent) to accept an optional `term_structure` payload from VA:

```python
@staticmethod
def calculate_fetch_params(vix, ivr, iv30, hv20, term_structure: dict | None = None) -> dict:
    ...
```

### 8.2 Apply horizon_bias to dyn_dte* & dyn_window

After existing VRP / IVR‑based logic sets:

- `dyn_dte_short`
- `dyn_dte_mid`
- `dyn_dte_long_backup`
- `dyn_window`

Apply:

```python
bias = (term_structure or {}).get("horizon_bias", {})
short_bias = bias.get("short", 0.0)
mid_bias   = bias.get("mid",   0.0)
long_bias  = bias.get("long",  0.0)

params["dyn_dte_short"]       = _scale_dte(params["dyn_dte_short"],       short_bias, scale=0.3)
params["dyn_dte_mid"]         = _scale_dte(params["dyn_dte_mid"],         mid_bias,   scale=0.3)
params["dyn_dte_long_backup"] = _scale_dte(params["dyn_dte_long_backup"], long_bias,  scale=0.3)

window_bias = 0.5 * mid_bias + 0.5 * long_bias
params["dyn_window"] = max(5, int(round(params["dyn_window"] * (1 + window_bias * 0.3))))
```

Where `_scale_dte("14 w", bias, scale)`:

1. Parses `value, unit = parse_dte_string("14 w")`.
2. Applies `value *= (1 + bias * scale)` and rounds.
3. Rebuilds string `"{value} {unit}"`.

Downstream command‑list code continues to use `dyn_*` without additional term‑structure logic.

---

## 9. Non‑goals

- Do **not** decide long/short vol here; that belongs to scoring/probability layers.
- Do **not** encode strategy templates here; those belong to strategy‑mapping layers.
- This spec is only about **how meso exposes term structure** and **how micro adjusts its time horizons accordingly**.
