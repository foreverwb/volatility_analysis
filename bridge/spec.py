from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class TermStructureSnapshot:
    """Structured term-structure payload for micro layers."""

    ratios: Dict[str, float] = field(default_factory=dict)
    label: Optional[str] = None
    label_code: Optional[str] = None
    ratio_30_90: Optional[float] = None
    adjustment: float = 0.0
    horizon_bias: Dict[str, float] = field(default_factory=dict)
    state_flags: Dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ratios": self.ratios,
            "label": self.label,
            "label_code": self.label_code,
            "ratio_30_90": self.ratio_30_90,
            "adjustment": self.adjustment,
            "horizon_bias": self.horizon_bias,
            "state_flags": self.state_flags,
        }


@dataclass
class BridgeSnapshot:
    """Bridge snapshot consumed by micro layers."""

    symbol: Optional[str] = None
    as_of: Optional[str] = None
    market_state: Dict[str, Any] = field(default_factory=dict)
    event_state: Dict[str, Any] = field(default_factory=dict)
    execution_state: Dict[str, Any] = field(default_factory=dict)
    term_structure: Optional[TermStructureSnapshot] = None

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "symbol": self.symbol,
            "as_of": self.as_of,
            "market_state": self.market_state,
            "event_state": self.event_state,
            "execution_state": self.execution_state,
        }
        data["term_structure"] = (
            self.term_structure.to_dict() if self.term_structure else None
        )
        return data
