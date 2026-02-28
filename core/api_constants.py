"""
API-specific defaults and thresholds.
"""

BRIDGE_BATCH_MIN_DIRECTION_SCORE = 1.0
# Legacy fallback only; runtime default for /api/bridge/batch is now derived from cfg
# via vol_pref_threshold + neutral buffer (currently 0.12).
BRIDGE_BATCH_MIN_VOL_SCORE = 0.12
BRIDGE_BATCH_DEFAULT_LIMIT = 50
