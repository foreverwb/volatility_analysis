# API Reference

This document describes the supported HTTP endpoints and request/response examples.

**Base**
- Default host: `http://<host>:8668`
- Content-Type: `application/json` for JSON requests
- Date format: `YYYY-MM-DD`

**Index**
- GET `/`
- GET `/static/<path:filename>`
- POST `/api/analyze`
- POST `/api/analyze/stream`
- GET `/api/records`
- DELETE `/api/records/<timestamp>/<symbol>`
- DELETE `/api/records/date/<date>`
- DELETE `/api/records/all`
- GET `/api/dates`
- GET `/api/config`
- POST `/api/config`
- GET `/api/vix/info`
- POST `/api/vix/clear`
- GET `/api/swing/params/<symbol>`
- POST `/api/swing/params/batch`
- GET `/api/swing/symbols`
- GET `/api/swing/dates/<symbol>`
- GET `/api/bridge/params/<symbol>`
- POST `/api/bridge/batch`

**GET /**
Returns the HTML landing page.

**GET /static/<path:filename>**
Serves static assets.

**POST /api/analyze**
Runs analysis for a list of records.

Query
| Field | Type | Required | Default | Notes |
| --- | --- | --- | --- | --- |
| ignore_earnings | bool | No | false | Skip earnings check. |

Body
| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| records | array | Yes | List of records to analyze. |

Response (201)
| Field | Type | Notes |
| --- | --- | --- |
| message | string | Summary message. |
| results | array | Analysis payloads. |
| errors | array or null | Error list. |
| oi_stats | object | OI stats summary. |

Example
```bash
curl -X POST http://localhost:8668/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{"records":[{"symbol":"NVDA","timestamp":"2025-12-15 14:30:00"}]}'
```

**POST /api/analyze/stream**
Runs analysis as Server-Sent Events (SSE).

Query
| Field | Type | Required | Default | Notes |
| --- | --- | --- | --- | --- |
| ignore_earnings | bool | No | false | Skip earnings check. |

Body
| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| records | array | Yes | List of records to analyze. |

Response
- `text/event-stream` with `data: { ... }` messages.
- Types include `init`, `analyze_progress`, `oi_complete`, `complete`, `error`.

Example
```bash
curl -N -X POST http://localhost:8668/api/analyze/stream \
  -H 'Content-Type: application/json' \
  -d '{"records":[{"symbol":"NVDA","timestamp":"2025-12-15 14:30:00"}]}'
```

**GET /api/records**
Lists analysis records.

Query
| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| date | string | No | Filter by trade date. |
| quadrant | string | No | Use `all` to disable. |
| confidence | string | No | Use `all` to disable. |

Response (200)
- JSON array of records.

Example
```bash
curl 'http://localhost:8668/api/records?date=2025-12-15'
```

**DELETE /api/records/<timestamp>/<symbol>**
Deletes a single record by timestamp and symbol.

Example
```bash
curl -X DELETE http://localhost:8668/api/records/2025-12-15%2014:30:00/NVDA
```

**DELETE /api/records/date/<date>**
Deletes all records for a date.

**DELETE /api/records/all**
Deletes all records.

**GET /api/dates**
Returns all available trade dates.

**GET /api/config**
Returns the current runtime config.

**POST /api/config**
Updates runtime config fields.

Example
```bash
curl -X POST http://localhost:8668/api/config \
  -H 'Content-Type: application/json' \
  -d '{"trend_days": 7}'
```

**GET /api/vix/info**
Returns VIX cache info.

**POST /api/vix/clear**
Clears VIX cache.

**GET /api/swing/params/<symbol>**
Returns swing params for a symbol.

Query
| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| date | string | No | Target trade date. |
| vix | number | No | Override VIX. |

Notes
- If `date` is provided but no record exists, response is 404 with available dates.
- Response includes `_source` and `params`.

Example
```bash
curl 'http://localhost:8668/api/swing/params/NVDA?date=2025-12-15&vix=19.5'
```

**POST /api/swing/params/batch**
Batch swing params for multiple symbols.

Body
| Field | Type | Required | Default | Notes |
| --- | --- | --- | --- | --- |
| date | string | No | If missing, use today if present else latest. |
| symbols | array or string | No | List or comma-separated string. Missing/empty returns empty results. |
| vix_override | number | No | Overrides VIX. |

Response (200)
| Field | Type | Notes |
| --- | --- | --- |
| success | bool | Always true if request is valid. |
| date | string or null | Resolved date. |
| results | array | Per-symbol payload (same as single endpoint). |
| errors | array | Per-symbol error list. |

Example
```bash
curl -X POST http://localhost:8668/api/swing/params/batch \
  -H 'Content-Type: application/json' \
  -d '{"date":"2025-12-15","symbols":["NVDA","TSLA"],"vix_override":19.5}'
```

**GET /api/swing/symbols**
Lists available symbols and latest date.

**GET /api/swing/dates/<symbol>**
Lists available dates for a symbol.

**GET /api/bridge/params/<symbol>**
Returns bridge snapshot for a symbol.

Query
| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| date | string | No | Target trade date. |
| source | string | No | For logging only. |

Notes
- If `date` is provided but missing, it falls back to latest.
- Response includes `requested_date` and `fallback_used`.

Example
```bash
curl 'http://localhost:8668/api/bridge/params/NVDA?date=2025-12-15&source=swing'
```

**POST /api/bridge/batch**
Batch bridge snapshots with filtering and sorting.

Body
| Field | Type | Required | Default | Notes |
| --- | --- | --- | --- | --- |
| date | string | No | If missing, use today if present else latest. |
| source | string | No | `swing` or `vol` (default `swing`). |
| symbols | array or string | No | List or comma-separated string. |
| min_direction_score | number | No | 1.0 | Threshold for direction score. |
| min_vol_score | number | No | 0.8 | Threshold for vol score. |
| limit | number | No | 50 | Max results. |

Notes
- If `date` is provided but that date has no records, API falls back to latest available trade date.
- Response includes:
- `requested_date`: original input date (or `null` if not provided)
- `fallback_used`: whether fallback date was used

Filtering
- `source = swing`: direction_bias in {\\u504f\\u591a, \\u504f\\u7a7a}, vol_bias == \\u4e70\\u6ce2, abs(direction_score) >= min_direction_score.
- `source = vol`: direction_bias in {\\u504f\\u591a, \\u504f\\u7a7a}, vol_bias == \\u5356\\u6ce2, abs(vol_score) >= min_vol_score.
- other: abs(direction_score) >= min_direction_score.

Sorting
- `source = swing`: abs(direction_score) desc.
- `source = vol`: abs(vol_score) desc.

Example (array)
```bash
curl -X POST http://localhost:8668/api/bridge/batch \
  -H 'Content-Type: application/json' \
  -d '{"date":"2025-12-15","source":"swing","symbols":["NVDA","TSLA"],"limit":10}'
```

Example (comma-separated symbols)
```bash
curl -X POST http://localhost:8668/api/bridge/batch \
  -H 'Content-Type: application/json' \
  -d '{"symbols":"NVDA,AMZN,INTC","source":"vol"}'
```
