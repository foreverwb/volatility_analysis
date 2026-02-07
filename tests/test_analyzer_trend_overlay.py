from types import SimpleNamespace

from core.analyzer import calculate_analysis


class DummyBridge:
    def to_dict(self):
        return {"execution_state": {}}


def test_calculate_analysis_adds_trend_overlay_without_breaking_existing_fields(monkeypatch):
    monkeypatch.setattr("core.analyzer.clean_record", lambda d: d)
    monkeypatch.setattr("core.analyzer.normalize_dataset", lambda ds: ds)
    monkeypatch.setattr("core.analyzer.validate_record", lambda *_: {"data_quality": "HIGH", "data_quality_issues": []})
    monkeypatch.setattr("core.analyzer.get_vix_with_fallback", lambda default=18.0: 18.0)
    monkeypatch.setattr("core.analyzer.compute_spot_vol_correlation_score", lambda *_: 0.0)
    monkeypatch.setattr("core.analyzer.detect_squeeze_potential", lambda *_: False)
    monkeypatch.setattr("core.analyzer.compute_term_structure", lambda *_: (1.0, "正常陡峭 (Normal steep)"))
    monkeypatch.setattr("core.analyzer.compute_term_structure_ratios", lambda *_: {"7_30": 1.0, "30_60": 1.0, "60_90": 1.0, "30_90": 1.0})
    monkeypatch.setattr("core.analyzer.detect_fear_regime", lambda *_: (False, []))
    monkeypatch.setattr("core.analyzer.compute_active_open_ratio", lambda *_: 0.0)
    monkeypatch.setattr("core.analyzer.compute_direction_score", lambda *_args, **_kwargs: 1.2)
    monkeypatch.setattr("core.analyzer.compute_vol_score", lambda *_args, **_kwargs: 0.5)
    monkeypatch.setattr("core.analyzer.map_liquidity", lambda *_: "高")
    monkeypatch.setattr("core.analyzer.map_confidence", lambda *_: ("高", 0.1, 0.8))
    monkeypatch.setattr("core.analyzer.penalize_extreme_move_low_vol", lambda *_: False)
    monkeypatch.setattr("core.analyzer.compute_ivrv", lambda *_: 0.0)
    monkeypatch.setattr("core.analyzer.compute_volume_bias", lambda *_: 0.0)
    monkeypatch.setattr("core.analyzer.compute_notional_bias", lambda *_: 0.0)
    monkeypatch.setattr("core.analyzer.compute_callput_ratio", lambda *_: 1.0)
    monkeypatch.setattr("core.analyzer.parse_earnings_date", lambda *_: None)
    monkeypatch.setattr("core.analyzer.days_until", lambda *_: None)
    monkeypatch.setattr("core.analyzer.compute_posture_5d", lambda *_: {
        "posture_5d": "TREND_CONFIRM",
        "posture_reasons": ["ok"],
        "posture_reason_codes": ["POSTURE_TREND_CONFIRM"],
        "posture_confidence": "高",
        "posture_inputs_snapshot": {"consistency_5d": 1.0},
    })
    monkeypatch.setattr("core.analyzer.evaluate_trade_permission", lambda **_: {
        "trade_permission": "NORMAL",
        "permission_reasons": [],
        "disabled_structures": [],
    })
    monkeypatch.setattr("core.analyzer.build_watchlist_guidance", lambda **_: {"watch_triggers": [], "what_to_monitor": []})
    monkeypatch.setattr("core.analyzer.select_micro_template", lambda *_: {
        "trade_permission": "NORMAL",
        "permission_reasons": [],
        "disabled_structures": [],
    })
    monkeypatch.setattr("core.analyzer.build_bridge_snapshot", lambda *_: DummyBridge())

    cfg = {
        "penalty_vol_pct_thresh": 0.4,
        "trend_days": 5,
        "trend_slope_up": 0.1,
        "trend_slope_down": 0.1,
        "enable_dynamic_params": False,
    }
    result = calculate_analysis({"symbol": "AAPL", "PriceChgPct": 2.0}, cfg=cfg, history_scores=[1.0, 1.2, 1.4, 1.6, 1.8])

    assert result["quadrant"] == "偏多—买波"
    assert result["posture_5d"] == "TREND_CONFIRM"
    assert "dir_slope_nd" in result
    assert result["dir_trend_label"] == "上行"
    assert result["trend_days_used"] == 5
