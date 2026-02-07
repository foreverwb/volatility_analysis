from app import app
import app as app_module


def test_api_records_backfills_missing_trend_fields(monkeypatch):
    class FakeRepo:
        def list_records(self, date=None, quadrant=None, confidence=None):
            return [
                {
                    "symbol": "TSLA",
                    "timestamp": "2026-02-03 20:00:00",
                    "direction_score": -0.8,
                    "quadrant": "中性/待观察",
                    "confidence": "中",
                },
                {
                    "symbol": "TSLA",
                    "timestamp": "2026-02-04 20:00:00",
                    "analysis": {"direction_score": -0.5},
                    "quadrant": "中性/待观察",
                    "confidence": "中",
                },
                {
                    "symbol": "TSLA",
                    "timestamp": "2026-02-05 20:00:00",
                    "analysis": {"direction_score": -0.2},
                    "quadrant": "中性/待观察",
                    "confidence": "中",
                },
            ]

    monkeypatch.setattr(app_module, "records_repo", FakeRepo())

    client = app.test_client()
    resp = client.get("/api/records")
    assert resp.status_code == 200

    data = resp.get_json()
    assert len(data) == 3

    # 第一天没有历史，保持横盘/0天
    assert data[0]["dir_trend_label"] == "横盘"
    assert data[0]["trend_days_used"] == 0

    # 第三天可利用前两日历史，样本天数应>0
    assert data[2]["trend_days_used"] == 2
    assert "dir_slope_nd" in data[2]
