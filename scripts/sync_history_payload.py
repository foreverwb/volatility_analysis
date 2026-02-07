"""同步历史 analysis_records payload 字段。

用途：修复旧记录仅在 payload.analysis 内有 direction_score/vol_score，
但顶层为缺失或 0 导致前端展示异常（例如 TSLA 历史 5 日显示为 0）。

执行：
    python scripts/sync_history_payload.py
或：
    ANALYSIS_DB_PATH=/path/to/analysis_records.db python scripts/sync_history_payload.py
"""

import json
import os
import sqlite3
from typing import Any, Dict, Tuple

DB_PATH = os.environ.get("ANALYSIS_DB_PATH", os.path.join("data", "analysis_records.db"))


def _safe_float(value: Any):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_payload(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """将 analysis 子对象中的关键字段回填到 payload 顶层。"""
    if not isinstance(payload, dict):
        return payload, False

    changed = False
    analysis = payload.get("analysis")
    if not isinstance(analysis, dict):
        return payload, False

    for key in ("direction_score", "vol_score", "dir_slope_nd", "dir_trend_label", "trend_days_used"):
        top_val = payload.get(key)
        sub_val = analysis.get(key)

        if key in ("direction_score", "vol_score", "dir_slope_nd"):
            top_num = _safe_float(top_val)
            sub_num = _safe_float(sub_val)
            if (top_num is None or top_num == 0.0) and sub_num is not None:
                payload[key] = sub_num
                changed = True
        else:
            if (top_val is None or top_val == 0 or top_val == "") and sub_val not in (None, ""):
                payload[key] = sub_val
                changed = True

    return payload, changed


def main() -> None:
    if not os.path.exists(DB_PATH):
        print(f"❌ DB not found: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    updated = 0
    total = 0
    with conn:
        rows = conn.execute("SELECT id, payload FROM analysis_records").fetchall()
        total = len(rows)
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except Exception:
                continue
            new_payload, changed = normalize_payload(payload)
            if not changed:
                continue

            conn.execute(
                "UPDATE analysis_records SET payload = ? WHERE id = ?",
                (json.dumps(new_payload, ensure_ascii=False), row["id"]),
            )
            updated += 1

    conn.close()
    print(f"✅ Sync finished. total={total}, updated={updated}, db={DB_PATH}")


if __name__ == "__main__":
    main()
