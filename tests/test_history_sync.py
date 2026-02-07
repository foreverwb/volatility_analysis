import app as app_module
from scripts.sync_history_payload import normalize_payload


def test_get_history_scores_fallbacks_to_analysis_payload(monkeypatch):
    class FakeRepo:
        def list_records_by_symbol(self, _symbol):
            return [
                {
                    "symbol": "TSLA",
                    "timestamp": "2026-02-07 15:30:00",
                    "analysis": {"direction_score": 1.2, "vol_score": 0.2},
                    "direction_score": None,
                },
                {
                    "symbol": "TSLA",
                    "timestamp": "2026-02-06 15:30:00",
                    "analysis": {"direction_score": 0.9, "vol_score": 0.1},
                },
            ]

    monkeypatch.setattr(app_module, "records_repo", FakeRepo())
    scores = app_module.get_history_scores("TSLA", days=5)
    assert scores == [1.2, 0.9]


def test_normalize_payload_backfills_top_level_fields():
    payload = {
        "symbol": "TSLA",
        "direction_score": 0,
        "analysis": {
            "direction_score": 1.1,
            "vol_score": 0.3,
            "dir_slope_nd": 0.12,
            "dir_trend_label": "上行",
            "trend_days_used": 5,
        },
    }
    normalized, changed = normalize_payload(payload)

    assert changed is True
    assert normalized["direction_score"] == 1.1
    assert normalized["vol_score"] == 0.3
    assert normalized["dir_slope_nd"] == 0.12
    assert normalized["dir_trend_label"] == "上行"
    assert normalized["trend_days_used"] == 5
