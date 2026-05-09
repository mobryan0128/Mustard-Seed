"""Deterministic market-structure classification helpers for the bias engine."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


VALID_DIRECTIONS = frozenset({"up", "down", "neutral"})
VALID_STRUCTURES = frozenset({"trend", "reversal", "chop", "exhaustion"})


@dataclass(frozen=True)
class BiasClassification:
    """Normalized classification result for one product."""

    direction: str
    structure: str
    confidence: int
    classification_reason: str


def classify_bias_state(
    *,
    lookback_return_bps: Decimal | None,
    recent_return_bps: Decimal | None,
    chop_threshold_bps: Decimal,
    insufficient_history: bool,
    stale_data: bool,
    time_sync_failed: bool,
) -> BiasClassification:
    """Classify rolling returns into a deterministic bias state."""

    hard_risk = insufficient_history or stale_data or time_sync_failed
    if hard_risk or lookback_return_bps is None or recent_return_bps is None:
        return BiasClassification(
            direction="neutral",
            structure="chop",
            confidence=0,
            classification_reason="hard_risk_or_missing_returns",
        )

    abs_lookback = abs(lookback_return_bps)
    abs_recent = abs(recent_return_bps)
    signs_match = _sign(lookback_return_bps) == _sign(recent_return_bps)

    if abs_lookback <= chop_threshold_bps and abs_recent <= chop_threshold_bps:
        return BiasClassification(
            direction="neutral",
            structure="chop",
            confidence=10,
            classification_reason="below_chop_threshold",
        )

    if abs_lookback > chop_threshold_bps and abs_recent <= chop_threshold_bps:
        return BiasClassification(
            direction="neutral",
            structure="exhaustion",
            confidence=30,
            classification_reason="recent_below_chop_exhaustion",
        )

    if signs_match and _sign(recent_return_bps) != 0:
        confidence = _trend_confidence(abs_lookback, abs_recent, chop_threshold_bps)
        direction = "up" if recent_return_bps > 0 else "down"
        return BiasClassification(
            direction=direction,
            structure="trend",
            confidence=confidence,
            classification_reason="aligned_trend",
        )

    if _sign(lookback_return_bps) != 0 and _sign(recent_return_bps) != 0:
        confidence = _trend_confidence(abs_lookback, abs_recent, chop_threshold_bps)
        direction = "up" if recent_return_bps > 0 else "down"
        return BiasClassification(
            direction=direction,
            structure="reversal",
            confidence=confidence,
            classification_reason="countertrend_reversal",
        )

    return BiasClassification(
        direction="neutral",
        structure="chop",
        confidence=10,
        classification_reason="neutral_chop_fallback",
    )


def _trend_confidence(
    abs_lookback_return_bps: Decimal,
    abs_recent_return_bps: Decimal,
    chop_threshold_bps: Decimal,
) -> int:
    triple_threshold = chop_threshold_bps * Decimal("3")
    double_threshold = chop_threshold_bps * Decimal("2")
    if abs_lookback_return_bps >= triple_threshold and abs_recent_return_bps >= triple_threshold:
        return 80
    if abs_lookback_return_bps >= double_threshold and abs_recent_return_bps >= double_threshold:
        return 60
    return 40


def _sign(value: Decimal) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0
