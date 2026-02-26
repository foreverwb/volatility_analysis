"""
Futu OpenAPI OI 缓存与 ΔOI 计算（SQLite 持久化）
"""
import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

DEFAULT_OI_DB_PATH = os.path.join("data", "analysis_records.db")
LEGACY_OI_CACHE_FILE = "oi_cache.json"
OI_CACHE_TABLE = "oi_cache_history"
CACHE_LOCK = threading.Lock()


def get_oi_db_path() -> str:
    return os.environ.get("ANALYSIS_DB_PATH", DEFAULT_OI_DB_PATH)


def _connect() -> sqlite3.Connection:
    db_path = get_oi_db_path()
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_oi_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {OI_CACHE_TABLE} (
            symbol TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            oi INTEGER NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(symbol, trade_date)
        )
        """
    )
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{OI_CACHE_TABLE}_symbol_date "
        f"ON {OI_CACHE_TABLE}(symbol, trade_date)"
    )


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").upper()


def _migrate_legacy_json_cache_if_needed(conn: sqlite3.Connection) -> None:
    if not os.path.exists(LEGACY_OI_CACHE_FILE):
        return

    row = conn.execute(f"SELECT COUNT(1) AS cnt FROM {OI_CACHE_TABLE}").fetchone()
    if row and int(row["cnt"]) > 0:
        return

    try:
        with open(LEGACY_OI_CACHE_FILE, "r") as f:
            legacy = json.load(f)
    except Exception:
        return

    rows = []
    for symbol, date_to_oi in (legacy or {}).items():
        if not isinstance(date_to_oi, dict):
            continue
        norm_symbol = _normalize_symbol(symbol)
        if not norm_symbol:
            continue
        for trade_date, oi in date_to_oi.items():
            if not isinstance(trade_date, str):
                continue
            if isinstance(oi, bool) or not isinstance(oi, (int, float)):
                continue
            rows.append((norm_symbol, trade_date, int(oi)))

    if rows:
        conn.executemany(
            f"""
            INSERT OR REPLACE INTO {OI_CACHE_TABLE}(symbol, trade_date, oi, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """,
            rows,
        )
    migrated_path = f"{LEGACY_OI_CACHE_FILE}.migrated"
    try:
        if os.path.exists(LEGACY_OI_CACHE_FILE):
            os.replace(LEGACY_OI_CACHE_FILE, migrated_path)
    except Exception:
        # 迁移失败不影响主流程，保留下一次兜底机会
        pass


def _find_recent_oi(
    symbol_cache: Dict[str, int],
    min_days_ago: int,
    max_days_ago: int,
) -> Optional[int]:
    """在给定天数窗口内寻找最近可用 OI（兼容周末/节假日）。"""
    now = datetime.now()
    for days_ago in range(min_days_ago, max_days_ago + 1):
        past_date = (now - timedelta(days=days_ago)).strftime('%Y-%m-%d')
        if past_date in symbol_cache:
            return symbol_cache[past_date]
    return None


def compute_delta_oi_windows(
    current_oi: Optional[int],
    symbol_cache: Dict[str, int],
) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """
    计算 ΔOI_1D / ΔOI_3D / ΔOI_5D（若历史不足返回 None）。
    """
    if current_oi is None:
        return (None, None, None)

    oi_1d = _find_recent_oi(symbol_cache, min_days_ago=1, max_days_ago=7)
    oi_3d = _find_recent_oi(symbol_cache, min_days_ago=3, max_days_ago=10)
    oi_5d = _find_recent_oi(symbol_cache, min_days_ago=5, max_days_ago=14)

    delta_1d = current_oi - oi_1d if oi_1d is not None else None
    delta_3d = current_oi - oi_3d if oi_3d is not None else None
    delta_5d = current_oi - oi_5d if oi_5d is not None else None
    return (delta_1d, delta_3d, delta_5d)


def format_delta_oi(value: Optional[int]) -> str:
    if value is None:
        return "N/A"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,}"


def load_oi_cache() -> dict:
    """加载 OI 缓存（线程安全，SQLite -> Dict 兼容结构）"""
    with CACHE_LOCK, _connect() as conn:
        _ensure_oi_table(conn)
        _migrate_legacy_json_cache_if_needed(conn)
        rows = conn.execute(
            f"""
            SELECT symbol, trade_date, oi
            FROM {OI_CACHE_TABLE}
            ORDER BY symbol ASC, trade_date ASC
            """
        ).fetchall()

    cache: Dict[str, Dict[str, int]] = {}
    for row in rows:
        symbol = row["symbol"]
        trade_date = row["trade_date"]
        oi = row["oi"]
        if symbol not in cache:
            cache[symbol] = {}
        cache[symbol][trade_date] = int(oi)
    return cache


def save_oi_cache(cache: dict) -> None:
    """保存 OI 缓存（线程安全，写入 SQLite）"""
    rows = []
    for symbol, date_to_oi in (cache or {}).items():
        if not isinstance(date_to_oi, dict):
            continue
        norm_symbol = _normalize_symbol(symbol)
        if not norm_symbol:
            continue
        for trade_date, oi in date_to_oi.items():
            if not isinstance(trade_date, str):
                continue
            if isinstance(oi, bool) or not isinstance(oi, (int, float)):
                continue
            rows.append((norm_symbol, trade_date, int(oi)))

    with CACHE_LOCK, _connect() as conn:
        _ensure_oi_table(conn)
        conn.execute(f"DELETE FROM {OI_CACHE_TABLE}")
        if rows:
            conn.executemany(
                f"""
                INSERT INTO {OI_CACHE_TABLE}(symbol, trade_date, oi, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                """,
                rows,
            )


def clear_oi_cache() -> None:
    """清空 OI 缓存（SQLite 表）。"""
    with CACHE_LOCK, _connect() as conn:
        _ensure_oi_table(conn)
        conn.execute(f"DELETE FROM {OI_CACHE_TABLE}")


def batch_compute_delta_oi(
    symbol_to_oi: Dict[str, Optional[int]]
) -> Dict[str, Tuple[Optional[int], Optional[int]]]:
    """
    批量计算 ΔOI_1D（基于 Futu OI）
    """
    cache = load_oi_cache()
    today = datetime.now().strftime('%Y-%m-%d')
    cutoff = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    results: Dict[str, Tuple[Optional[int], Optional[int]]] = {}

    for symbol, current_oi in symbol_to_oi.items():
        if current_oi is None:
            results[symbol] = (None, None)
            continue

        symbol_key = _normalize_symbol(symbol)
        symbol_cache = cache.get(symbol_key) or cache.get(symbol) or {}
        delta_oi, _, _ = compute_delta_oi_windows(current_oi, symbol_cache)

        if symbol_key not in cache:
            cache[symbol_key] = {}
        cache[symbol_key][today] = int(current_oi)
        cache[symbol_key] = {
            date: oi for date, oi in cache[symbol_key].items()
            if date >= cutoff
        }

        results[symbol] = (current_oi, delta_oi)

    save_oi_cache(cache)
    return results
