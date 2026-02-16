"""
策略映射模块（YAML 驱动）
"""
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .config import get_vol_score_threshold


_NEUTRAL_QUADRANT = "中性/待观察"
_DEFAULT_QUADRANT_KEY = "neutral_watch"

# 象限标签仅用于 key 解析，不承载策略内容本身
_DIRECTION_ALIAS = {
    "偏多": "bull",
    "偏空": "bear",
    "中性": "neutral",
}
_VOL_ALIAS = {
    "买波": "long_vol",
    "卖波": "short_vol",
    "中性": "neutral",
}
_QUADRANT_FALLBACK_ALIAS = {
    "偏多—买波": "bull_long_vol",
    "偏多—卖波": "bull_short_vol",
    "偏空—买波": "bear_long_vol",
    "偏空—卖波": "bear_short_vol",
    _NEUTRAL_QUADRANT: _DEFAULT_QUADRANT_KEY,
}

_SAFE_DEFAULT_BUNDLE: Dict[str, Any] = {
    "strategy_text_zh": "观望或使用定义风险垂直价差",
    "risk_text_zh": "策略配置缺失，默认保守执行并控制仓位",
    "structures": [
        {
            "name": "defined_risk_vertical",
            "risk_defined": True,
            "direction": "neutral",
            "vol_bias": "neutral",
            "dte_hint": [21, 45],
            "delta_hint": {"short_leg_delta": 0.25, "long_leg_delta": 0.40},
            "description_zh": "配置缺失时的保守默认策略",
        }
    ],
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return default


def _normalize_cfg(cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return cfg if isinstance(cfg, dict) else {}


def _strategy_map_candidates(cfg: Dict[str, Any]) -> List[Path]:
    explicit = cfg.get("strategy_map_path") if isinstance(cfg.get("strategy_map_path"), str) else None
    env_path = os.environ.get("STRATEGY_MAP_PATH")
    repo_candidate = _repo_root() / "config" / "strategy_map.yaml"
    package_candidate = Path(__file__).resolve().parent / "config" / "strategy_map.yaml"

    candidates: List[Path] = []
    for raw in (explicit, env_path):
        if isinstance(raw, str) and raw.strip():
            candidates.append(Path(raw).expanduser())
    candidates.extend([repo_candidate, package_candidate])

    unique: List[Path] = []
    seen = set()
    for path in candidates:
        resolved = path.resolve() if path.is_absolute() else (_repo_root() / path).resolve()
        if str(resolved) in seen:
            continue
        seen.add(str(resolved))
        unique.append(resolved)
    return unique


def _build_fallback_strategy_map() -> Dict[str, Any]:
    return {
        "quadrants": {_DEFAULT_QUADRANT_KEY: deepcopy(_SAFE_DEFAULT_BUNDLE)},
        "quadrant_aliases": {},
        "meta": {"fallback": True, "source": "built_in_safe_default"},
    }


def load_strategy_map(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    加载策略 YAML 配置。

    支持优先级:
    1) cfg["strategy_map_path"]
    2) 环境变量 STRATEGY_MAP_PATH
    3) <repo>/config/strategy_map.yaml
    """
    cfg = _normalize_cfg(cfg)
    for path in _strategy_map_candidates(cfg):
        if not path.exists():
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        quadrants = data.get("quadrants")
        if not isinstance(quadrants, dict) or not quadrants:
            continue
        aliases = data.get("quadrant_aliases")
        if not isinstance(aliases, dict):
            aliases = {}
        loaded = deepcopy(data)
        loaded["quadrant_aliases"] = aliases
        meta = loaded.get("meta") if isinstance(loaded.get("meta"), dict) else {}
        meta.update({"fallback": False, "source": str(path)})
        loaded["meta"] = meta
        return loaded
    return _build_fallback_strategy_map()


def _quadrant_to_key(quadrant: str, strategy_map: Dict[str, Any]) -> str:
    quadrants = strategy_map.get("quadrants") if isinstance(strategy_map.get("quadrants"), dict) else {}
    if quadrant in quadrants:
        return str(quadrant)

    aliases = strategy_map.get("quadrant_aliases") if isinstance(strategy_map.get("quadrant_aliases"), dict) else {}
    mapped = aliases.get(quadrant)
    if isinstance(mapped, str) and mapped in quadrants:
        return mapped

    fallback = _QUADRANT_FALLBACK_ALIAS.get(quadrant)
    if fallback and fallback in quadrants:
        return fallback

    if isinstance(quadrant, str) and "—" in quadrant:
        dir_pref, vol_pref = quadrant.split("—", 1)
        dir_key = _DIRECTION_ALIAS.get(dir_pref.strip(), "neutral")
        vol_key = _VOL_ALIAS.get(vol_pref.strip(), "neutral")
        if dir_key == "neutral" or vol_key == "neutral":
            return _DEFAULT_QUADRANT_KEY if _DEFAULT_QUADRANT_KEY in quadrants else next(iter(quadrants.keys()), _DEFAULT_QUADRANT_KEY)
        candidate = f"{dir_key}_{vol_key}"
        if candidate in quadrants:
            return candidate

    return _DEFAULT_QUADRANT_KEY if _DEFAULT_QUADRANT_KEY in quadrants else next(iter(quadrants.keys()), _DEFAULT_QUADRANT_KEY)


def _infer_direction(quadrant_key: str) -> str:
    if quadrant_key.startswith("bull"):
        return "bull"
    if quadrant_key.startswith("bear"):
        return "bear"
    return "neutral"


def _infer_vol_bias(quadrant_key: str) -> str:
    if "long_vol" in quadrant_key:
        return "long_vol"
    if "short_vol" in quadrant_key:
        return "short_vol"
    return "neutral"


def _bundle_for_quadrant(quadrant: str, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    strategy_map = load_strategy_map(cfg)
    quadrants = strategy_map.get("quadrants") if isinstance(strategy_map.get("quadrants"), dict) else {}
    if not quadrants:
        return deepcopy(_SAFE_DEFAULT_BUNDLE)
    key = _quadrant_to_key(quadrant, strategy_map)
    bundle = quadrants.get(key)
    if isinstance(bundle, dict):
        enriched = deepcopy(bundle)
        enriched.setdefault("_quadrant_key", key)
        return enriched
    fallback = quadrants.get(_DEFAULT_QUADRANT_KEY)
    if isinstance(fallback, dict):
        enriched = deepcopy(fallback)
        enriched.setdefault("_quadrant_key", _DEFAULT_QUADRANT_KEY)
        return enriched
    enriched = deepcopy(_SAFE_DEFAULT_BUNDLE)
    enriched.setdefault("_quadrant_key", _DEFAULT_QUADRANT_KEY)
    return enriched


def _build_disable_note(permission_reasons: Optional[List[str]]) -> str:
    reason_codes = [str(code) for code in (permission_reasons or []) if code]
    if not reason_codes:
        return "已禁用：受交易权限约束"
    preview = ", ".join(reason_codes[:3])
    return f"已禁用：{preview}"


def apply_disabled_structures(
    strategy_structures: List[Dict[str, Any]],
    disabled_structures: Optional[List[str]] = None,
    permission_reasons: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    将 disabled_structures 应用于结构化策略列表，补充 enabled 和禁用说明。
    """
    disabled = {str(name) for name in (disabled_structures or []) if name}
    disabled_note = _build_disable_note(permission_reasons)
    normalized: List[Dict[str, Any]] = []

    for item in strategy_structures or []:
        row = deepcopy(item) if isinstance(item, dict) else {"name": str(item)}
        name = str(row.get("name") or "")
        notes = [str(note) for note in (row.get("notes") or []) if note]
        enabled = name not in disabled
        if not enabled:
            notes.append(disabled_note)
        row["name"] = name
        row["risk_defined"] = bool(row.get("risk_defined", False))
        row["direction"] = str(row.get("direction") or "neutral")
        row["vol_bias"] = str(row.get("vol_bias") or "neutral")
        dte_hint = row.get("dte_hint") or []
        row["dte_hint"] = [int(x) for x in dte_hint if isinstance(x, (int, float))]
        delta_hint = row.get("delta_hint") if isinstance(row.get("delta_hint"), dict) else {}
        row["delta_hint"] = {
            str(k): float(v)
            for k, v in delta_hint.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        }
        row["notes"] = notes
        row["enabled"] = bool(enabled)
        normalized.append(row)

    return normalized


def _build_structures_from_bundle(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    quadrant_key = str(bundle.get("_quadrant_key") or _DEFAULT_QUADRANT_KEY)
    direction_default = _infer_direction(quadrant_key)
    vol_bias_default = _infer_vol_bias(quadrant_key)

    raw_structures = bundle.get("structures")
    if not isinstance(raw_structures, list):
        raw_structures = []

    structures: List[Dict[str, Any]] = []
    for raw in raw_structures:
        if not isinstance(raw, dict):
            continue
        description_zh = raw.get("description_zh")
        notes = []
        if isinstance(description_zh, str) and description_zh.strip():
            notes.append(description_zh.strip())
        notes.extend(str(note) for note in (raw.get("notes") or []) if note)
        dte_hint = raw.get("dte_hint") if isinstance(raw.get("dte_hint"), list) else []
        delta_hint = raw.get("delta_hint") if isinstance(raw.get("delta_hint"), dict) else {}

        item = {
            "name": str(raw.get("name") or "unknown_structure"),
            "risk_defined": _coerce_bool(raw.get("risk_defined"), default=True),
            "direction": str(raw.get("direction") or direction_default),
            "vol_bias": str(raw.get("vol_bias") or vol_bias_default),
            "dte_hint": [int(x) for x in dte_hint if isinstance(x, (int, float))],
            "delta_hint": {
                str(k): float(v)
                for k, v in delta_hint.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            },
            "notes": notes,
        }
        structures.append(item)

    if structures:
        return structures

    safe = deepcopy(_SAFE_DEFAULT_BUNDLE["structures"][0])
    safe["direction"] = direction_default
    safe["vol_bias"] = vol_bias_default
    safe["notes"] = [str(safe.pop("description_zh"))]
    return [safe]


def get_strategy_structures(
    quadrant: str,
    disabled_structures: Optional[List[str]] = None,
    permission_reasons: Optional[List[str]] = None,
    cfg: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    获取结构化策略列表，并按禁用清单打标。
    """
    bundle = _bundle_for_quadrant(quadrant, cfg=cfg)
    structures = _build_structures_from_bundle(bundle)
    return apply_disabled_structures(
        structures,
        disabled_structures=disabled_structures,
        permission_reasons=permission_reasons,
    )


def map_direction_pref(score: float) -> str:
    """方向偏好映射"""
    return "偏多" if score >= 1.0 else "偏空" if score <= -1.0 else "中性"


def map_vol_pref(score: float, cfg: Dict[str, Any]) -> str:
    """波动偏好映射（使用 VolScore 显著阈值）。"""
    th = get_vol_score_threshold(cfg, default=0.40)
    return "买波" if score >= th else "卖波" if score <= -th else "中性"


def combine_quadrant(dir_pref: str, vol_pref: str) -> str:
    """组合四象限"""
    if dir_pref == "中性" or vol_pref == "中性":
        return _NEUTRAL_QUADRANT
    return f"{dir_pref}—{vol_pref}"


def get_strategy_info(
    quadrant: str,
    liquidity: str,
    is_squeeze: bool = False,
    features: Optional[Dict[str, Any]] = None,
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """
    获取策略建议。
    """
    squeeze_score = 1.0 if is_squeeze else 0.0
    if isinstance(features, dict):
        raw_score = features.get("squeeze_score")
        if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool):
            squeeze_score = max(0.0, min(1.0, float(raw_score)))

    bundle = _bundle_for_quadrant(quadrant, cfg=cfg)
    strategy_text = str(bundle.get("strategy_text_zh") or "").strip()
    risk_text = str(bundle.get("risk_text_zh") or "").strip()

    if not strategy_text:
        descriptions = []
        for s in bundle.get("structures", []) if isinstance(bundle.get("structures"), list) else []:
            if not isinstance(s, dict):
                continue
            d = s.get("description_zh")
            if isinstance(d, str) and d.strip():
                descriptions.append(d.strip())
        strategy_text = ";".join(descriptions) if descriptions else _SAFE_DEFAULT_BUNDLE["strategy_text_zh"]
    if not risk_text:
        risk_text = _SAFE_DEFAULT_BUNDLE["risk_text_zh"]

    info = {
        "策略": strategy_text,
        "风险": risk_text,
    }

    if squeeze_score >= 0.8:
        prefix = "🔥 【Gamma Squeeze 强预警】强烈建议买入看涨期权 (Long Call) 利用爆发。 "
        info["策略"] = prefix + info["策略"]
        info["风险"] += "; 注意：挤压行情可能快速反转，需设移动止盈"
    elif squeeze_score >= 0.6:
        prefix = "⚠️ 【Gamma Squeeze 弱预警】可考虑顺势偏多结构，等待确认后加仓。 "
        info["策略"] = prefix + info["策略"]
        info["风险"] += "; 挤压信号未完全确认，注意回撤与假突破"

    if liquidity == "低":
        info["风险"] += ";⚠️ 流动性低,用少腿、靠近ATM、限价单与缩小仓位"

    return info
