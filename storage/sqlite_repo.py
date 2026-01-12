import json
import os
import sqlite3
import threading
from typing import Any, Dict, List, Optional

DEFAULT_DB_PATH = os.environ.get("ANALYSIS_DB_PATH", os.path.join("data", "analysis_records.db"))


class RecordsRepository:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._ensure_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_db(self) -> None:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    quadrant TEXT,
                    confidence TEXT,
                    payload TEXT NOT NULL,
                    UNIQUE(symbol, trade_date)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_date ON analysis_records(trade_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_symbol ON analysis_records(symbol)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_quadrant ON analysis_records(quadrant)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_confidence ON analysis_records(confidence)")

    def list_records(
        self,
        date: Optional[str] = None,
        quadrant: Optional[str] = None,
        confidence: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        filters = []
        params: List[Any] = []

        if date:
            filters.append("trade_date = ?")
            params.append(date)
        if quadrant:
            filters.append("quadrant = ?")
            params.append(quadrant)
        if confidence:
            filters.append("confidence = ?")
            params.append(confidence)

        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        query = f"""
            SELECT payload
            FROM analysis_records
            {where_clause}
            ORDER BY id ASC
        """
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def list_records_by_symbol(self, symbol: str) -> List[Dict[str, Any]]:
        query = """
            SELECT payload
            FROM analysis_records
            WHERE symbol = ?
            ORDER BY timestamp DESC
        """
        with self._connect() as conn:
            rows = conn.execute(query, (symbol.upper(),)).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def upsert_daily_latest(self, records: List[Dict[str, Any]]) -> None:
        if not records:
            return
        with self._lock, self._connect() as conn:
            for record in records:
                symbol = record.get("symbol")
                timestamp = record.get("timestamp")
                if not symbol or not timestamp:
                    continue
                trade_date = timestamp.split(" ")[0]
                conn.execute(
                    """
                    INSERT INTO analysis_records (
                        symbol, timestamp, trade_date, quadrant, confidence, payload
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(symbol, trade_date) DO UPDATE SET
                        timestamp = excluded.timestamp,
                        quadrant = excluded.quadrant,
                        confidence = excluded.confidence,
                        payload = excluded.payload
                    WHERE excluded.timestamp > analysis_records.timestamp
                    """,
                    (
                        symbol.upper(),
                        timestamp,
                        trade_date,
                        record.get("quadrant"),
                        record.get("confidence"),
                        json.dumps(record, ensure_ascii=False),
                    ),
                )

    def get_latest_by_symbol(self, symbol: str, target_date: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if target_date:
            query = """
                SELECT payload
                FROM analysis_records
                WHERE symbol = ? AND trade_date = ?
                ORDER BY timestamp DESC
                LIMIT 1
            """
            params = (symbol.upper(), target_date)
        else:
            query = """
                SELECT payload
                FROM analysis_records
                WHERE symbol = ?
                ORDER BY timestamp DESC
                LIMIT 1
            """
            params = (symbol.upper(),)
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        return json.loads(row["payload"]) if row else None

    def list_symbols(self) -> List[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT symbol FROM analysis_records ORDER BY symbol ASC"
            ).fetchall()
        return [row["symbol"] for row in rows]

    def list_dates(self) -> List[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT trade_date FROM analysis_records ORDER BY trade_date DESC"
            ).fetchall()
        return [row["trade_date"] for row in rows]

    def delete_record(self, timestamp: str, symbol: str) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM analysis_records WHERE symbol = ? AND timestamp = ?",
                (symbol.upper(), timestamp),
            )
        return cursor.rowcount > 0

    def delete_by_date(self, date: str) -> int:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM analysis_records WHERE trade_date = ?",
                (date,),
            )
        return cursor.rowcount

    def delete_all(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM analysis_records")


_repo_instance: Optional[RecordsRepository] = None


def get_records_repo() -> RecordsRepository:
    global _repo_instance
    if _repo_instance is None:
        _repo_instance = RecordsRepository()
    return _repo_instance
