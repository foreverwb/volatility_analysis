import importlib
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _make_record(
    symbol: str,
    date: str,
    time: str = "14:30:00",
    direction_score: float = 0.0,
    vol_score: float = 0.0,
    direction_bias: str = "偏多",
    vol_bias: str = "买波",
    quadrant: str = "偏多—买波",
    confidence: str = "高",
    term_structure_ratio: float = 1.1,
    ivrv_ratio: float = 1.2,
    ivr: float = 50.0,
    iv30: float = 20.0,
    hv20: float = 18.0,
    vix: float = 18.0,
) -> Dict[str, Any]:
    timestamp = f"{date} {time}"
    return {
        "symbol": symbol.upper(),
        "timestamp": timestamp,
        "direction_score": direction_score,
        "vol_score": vol_score,
        "direction_bias": direction_bias,
        "vol_bias": vol_bias,
        "quadrant": quadrant,
        "confidence": confidence,
        "term_structure_ratio": term_structure_ratio,
        "derived_metrics": {
            "ivrv_ratio": ivrv_ratio,
            "regime_ratio": 1.0,
            "days_to_earnings": 10,
        },
        "ivr": ivr,
        "iv30": iv30,
        "hv20": hv20,
        "vix": vix,
        "raw_data": {
            "Earnings": "22-Oct-2025 BMO",
            "IVR": ivr,
            "IV30": iv30,
            "HV20": hv20,
        },
        "bridge": {
            "market_state": {"ivr": ivr, "iv30": iv30, "hv20": hv20},
            "event_state": {"earnings_date": "2025-10-22"},
        },
    }


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    db_path = tmp_path / "analysis_records.db"
    monkeypatch.setenv("ANALYSIS_DB_PATH", str(db_path))

    import storage.sqlite_repo as sqlite_repo

    sqlite_repo._repo_instance = None
    import core
    import api_extension

    importlib.reload(core)
    importlib.reload(api_extension)

    app = Flask(__name__)
    api_extension.register_swing_api(app)
    api_extension.register_bridge_api(app, core.DEFAULT_CFG)

    repo = sqlite_repo.get_records_repo()
    with app.test_client() as client:
        yield client, repo


def _seed_records(repo) -> None:
    records: List[Dict[str, Any]] = []

    # NVDA history (rising IV30)
    records.append(_make_record("NVDA", "2025-12-13", iv30=20.0, direction_score=0.8))
    records.append(_make_record("NVDA", "2025-12-14", iv30=21.0, direction_score=0.9))
    records.append(_make_record("NVDA", "2025-12-15", iv30=23.0, direction_score=1.5))

    # TSLA history (falling IV30)
    records.append(_make_record("TSLA", "2025-12-13", iv30=25.0, direction_score=-0.7, vol_bias="卖波"))
    records.append(_make_record("TSLA", "2025-12-14", iv30=24.0, direction_score=-0.9, vol_bias="卖波"))
    records.append(
        _make_record(
            "TSLA",
            "2025-12-15",
            iv30=22.0,
            direction_score=-1.2,
            vol_score=1.1,
            direction_bias="偏空",
            vol_bias="卖波",
        )
    )

    # Additional symbols for bridge batch filtering
    records.append(
        _make_record(
            "META",
            "2025-12-15",
            direction_score=-2.2,
            direction_bias="偏空",
            vol_bias="买波",
        )
    )
    records.append(
        _make_record(
            "AMZN",
            "2025-12-15",
            direction_score=0.2,
            vol_score=-2.5,
            direction_bias="偏多",
            vol_bias="卖波",
        )
    )
    records.append(
        _make_record(
            "AAPL",
            "2025-12-15",
            direction_score=0.5,
            direction_bias="偏多",
            vol_bias="买波",
        )
    )
    records.append(
        _make_record(
            "AMD",
            "2025-12-15",
            direction_score=2.0,
            direction_bias="中性",
            vol_bias="买波",
        )
    )

    repo.upsert_daily_latest(records)


def test_bridge_batch_swing_filter_sort_limit(app_client):
    client, repo = app_client
    _seed_records(repo)

    resp = client.post(
        "/api/bridge/batch",
        json={"date": "2025-12-15", "source": "swing", "limit": 1},
    )
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["date"] == "2025-12-15"
    assert data["source"] == "swing"
    assert data["count"] == 1
    assert data["results"][0]["symbol"] == "META"


def test_bridge_batch_vol_filter_sort(app_client):
    client, repo = app_client
    _seed_records(repo)

    resp = client.post(
        "/api/bridge/batch",
        json={"date": "2025-12-15", "source": "vol"},
    )
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["count"] == 2
    assert [item["symbol"] for item in data["results"]] == ["AMZN", "TSLA"]


def test_bridge_batch_date_default(app_client):
    client, repo = app_client
    _seed_records(repo)

    resp = client.post("/api/bridge/batch", json={"source": "swing"})
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["date"] == "2025-12-15"
    assert data["count"] >= 1


def test_bridge_batch_date_fallback_when_requested_date_missing(app_client):
    client, repo = app_client
    _seed_records(repo)

    resp = client.post(
        "/api/bridge/batch",
        json={"date": "2025-12-16", "source": "vol"},
    )
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["requested_date"] == "2025-12-16"
    assert data["fallback_used"] is True
    assert data["date"] == "2025-12-15"
    assert data["count"] > 0


def test_swing_params_batch_happy_path(app_client):
    client, repo = app_client
    _seed_records(repo)

    resp = client.post(
        "/api/swing/params/batch",
        json={
            "date": "2025-12-15",
            "symbols": ["NVDA", "TSLA"],
            "vix_override": 19.5,
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["date"] == "2025-12-15"
    assert data["errors"] == []
    assert {item["symbol"] for item in data["results"]} == {"NVDA", "TSLA"}
    for item in data["results"]:
        assert item["params"]["vix"] == 19.5


def test_swing_params_batch_missing_and_invalid_symbols(app_client):
    client, repo = app_client
    _seed_records(repo)

    resp = client.post(
        "/api/swing/params/batch",
        json={
            "date": "2025-12-15",
            "symbols": ["NVDA", "MISSING", 123],
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()

    assert {item["symbol"] for item in data["results"]} == {"NVDA"}
    error_symbols = {item["symbol"] for item in data["errors"]}
    assert error_symbols == {"MISSING", "123"}


def test_swing_params_batch_empty_symbols_returns_empty_success(app_client):
    client, repo = app_client
    _seed_records(repo)

    resp = client.post(
        "/api/swing/params/batch",
        json={
            "date": "2025-12-15",
            "symbols": [],
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["success"] is True
    assert data["date"] == "2025-12-15"
    assert data["results"] == []
    assert data["errors"] == []


def test_swing_params_batch_missing_symbols_returns_empty_success(app_client):
    client, repo = app_client
    _seed_records(repo)

    resp = client.post(
        "/api/swing/params/batch",
        json={
            "date": "2025-12-15",
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["success"] is True
    assert data["date"] == "2025-12-15"
    assert data["results"] == []
    assert data["errors"] == []
