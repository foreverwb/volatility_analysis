from app import app
import app as app_module


class FakeRepo:
    def __init__(self):
        self.saved = []

    def list_records_by_symbol(self, _symbol):
        return [
            {
                "symbol": "AAPL",
                "timestamp": "2026-01-03 09:30:00",
                "analysis": {"direction_score": 0.9, "vol_score": 0.2},
                "direction_score": 0.7,
                "vol_score": 0.1,
            },
            {
                "symbol": "AAPL",
                "timestamp": "2026-01-03 15:30:00",
                "analysis": {"direction_score": 1.1, "vol_score": 0.3},
                "direction_score": 0.8,
                "vol_score": 0.2,
            },
            {
                "symbol": "AAPL",
                "timestamp": "2026-01-02 15:30:00",
                "analysis": {"direction_score": 1.3, "vol_score": 0.4},
            },
        ]

    def upsert_daily_latest(self, records):
        self.saved.extend(records)


class EmptyIv:
    iv7 = None
    iv30 = None
    iv60 = None
    iv90 = None
    total_oi = None


def test_analyze_uses_history_series_and_returns_new_fields(monkeypatch):
    fake_repo = FakeRepo()
    captured = {}

    monkeypatch.setattr(app_module, "records_repo", fake_repo)
    monkeypatch.setattr(app_module, "should_skip_oi_fetch", lambda: False)
    monkeypatch.setattr(app_module, "fetch_iv_terms", lambda symbols: {s: EmptyIv() for s in symbols})
    monkeypatch.setattr(app_module, "batch_compute_delta_oi", lambda *_: {})

    def fake_calculate_analysis(record, ignore_earnings=False, history_scores=None, skip_oi=False):
        captured["history_scores"] = history_scores
        return {
            "symbol": record["symbol"],
            "timestamp": "2026-01-04 15:30:00",
            "quadrant": "中性/待观察",
            "confidence": "中",
            "posture_5d": "CHOP",
            "direction_score": 0.2,
            "vol_score": 0.1,
            "dir_slope_nd": 0.12,
            "dir_trend_label": "上行",
            "trend_days_used": 2,
        }

    monkeypatch.setattr(app_module, "calculate_analysis", fake_calculate_analysis)

    client = app.test_client()
    resp = client.post("/api/analyze", json={"records": [{"symbol": "AAPL"}]})

    assert resp.status_code == 201
    payload = resp.get_json()
    assert captured["history_scores"] == [1.1, 1.3]
    assert payload["results"][0]["dir_slope_nd"] == 0.12
    assert payload["results"][0]["dir_trend_label"] == "上行"
    assert payload["results"][0]["trend_days_used"] == 2
    assert fake_repo.saved
