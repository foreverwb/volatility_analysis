from storage.sqlite_repo import RecordsRepository


def test_upsert_daily_latest_keeps_unique_by_symbol_trade_date_with_new_payload_fields(tmp_path):
    repo = RecordsRepository(str(tmp_path / "analysis_records.db"))

    repo.upsert_daily_latest([
        {
            "symbol": "AAPL",
            "timestamp": "2026-01-05 09:30:00",
            "quadrant": "中性/待观察",
            "confidence": "中",
            "dir_slope_nd": 0.1,
            "dir_trend_label": "上行",
            "trend_days_used": 5,
        }
    ])

    repo.upsert_daily_latest([
        {
            "symbol": "AAPL",
            "timestamp": "2026-01-05 15:30:00",
            "quadrant": "偏多—买波",
            "confidence": "高",
            "dir_slope_nd": 0.2,
            "dir_trend_label": "上行",
            "trend_days_used": 5,
        }
    ])

    rows = repo.list_records_by_symbol("AAPL")
    assert len(rows) == 1
    assert rows[0]["timestamp"] == "2026-01-05 15:30:00"
    assert rows[0]["dir_slope_nd"] == 0.2
