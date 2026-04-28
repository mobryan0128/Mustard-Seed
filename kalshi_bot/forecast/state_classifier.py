"""Deterministic market-structure classification helpers for the bias engine."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


VALID_DIRECTIONS = frozenset({"up", "down", "neutral"})
VALID_STRUCTURES = frozenset({"trend", "reversal", "chop", "exhaustion"})
TREND_CONFIRMATION_MULTIPLIER = Decimal("1.5")
TREND_CONFIDENCE_60_MULTIPLIER = Decimal("3")
TREND_CONFIDENCE_80_MULTIPLIER = Decimal("5")


@dataclass(frozen=True)
class BiasClassification:
    """Normalized classification result for one product."""

    direction: str
    structure: str
    confidence: int
    classification_reason: str | None = None
    confidence_reason: str | None = None
    trend_confirmation_met: bool | None = None


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
            confidence_reason="suppressed_by_risk_or_missing_returns",
            trend_confirmation_met=False,
        )

    abs_lookback = abs(lookback_return_bps)
    abs_recent = abs(recent_return_bps)
    signs_match = _sign(lookback_return_bps) == _sign(recent_return_bps)
    trend_confirmation_threshold = chop_threshold_bps * TREND_CONFIRMATION_MULTIPLIER

    if abs_lookback <= chop_threshold_bps and abs_recent <= chop_threshold_bps:
        return BiasClassification(
            direction="neutral",
            structure="chop",
            confidence=10,
            classification_reason="both_returns_within_chop_threshold",
            confidence_reason="chop_floor_confidence",
            trend_confirmation_met=False,
        )

    if signs_match and _sign(recent_return_bps) != 0:
        if (
            abs_lookback >= trend_confirmation_threshold
            and abs_recent >= trend_confirmation_threshold
        ):
            confidence, confidence_reason = _trend_confidence(
                abs_lookback,
                abs_recent,
                chop_threshold_bps,
            )
            direction = "up" if recent_return_bps > 0 else "down"
            return BiasClassification(
                direction=direction,
                structure="trend",
                confidence=confidence,
                classification_reason="confirmed_matching_direction_returns",
                confidence_reason=confidence_reason,
                trend_confirmation_met=True,
            )
        if abs_lookback >= trend_confirmation_threshold:
            return BiasClassification(
                direction="neutral",
                structure="exhaustion",
                confidence=30,
                classification_reason="lookback_directional_recent_unconfirmed",
                confidence_reason="exhaustion_fixed_confidence",
                trend_confirmation_met=False,
            )
        return BiasClassification(
            direction="neutral",
            structure="chop",
            confidence=10,
            classification_reason="recent_directional_lookback_unconfirmed",
            confidence_reason="chop_floor_confidence",
            trend_confirmation_met=False,
        )

    if abs_lookback > chop_threshold_bps and abs_recent <= chop_threshold_bps:
        return BiasClassification(
            direction="neutral",
            structure="exhaustion",
            confidence=30,
            classification_reason="lookback_directional_recent_chop",
            confidence_reason="exhaustion_fixed_confidence",
            trend_confirmation_met=False,
        )

    if _sign(lookback_return_bps) != 0 and _sign(recent_return_bps) != 0:
        confidence, confidence_reason = _reversal_confidence(
            abs_lookback,
            abs_recent,
            chop_threshold_bps,
        )
        direction = "up" if recent_return_bps > 0 else "down"
        return BiasClassification(
            direction=direction,
            structure="reversal",
            confidence=confidence,
            classification_reason="opposing_direction_returns",
            confidence_reason=confidence_reason,
            trend_confirmation_met=False,
        )

    return BiasClassification(
        direction="neutral",
        structure="chop",
        confidence=10,
        classification_reason="fallback_chop",
        confidence_reason="chop_floor_confidence",
        trend_confirmation_met=False,
    )


def _trend_confidence(
    abs_lookback_return_bps: Decimal,
    abs_recent_return_bps: Decimal,
    chop_threshold_bps: Decimal,
) -> tuple[int, str]:
    high_threshold = chop_threshold_bps * TREND_CONFIDENCE_80_MULTIPLIER
    medium_threshold = chop_threshold_bps * TREND_CONFIDENCE_60_MULTIPLIER
    if abs_lookback_return_bps >= high_threshold and abs_recent_return_bps >= high_threshold:
        return 80, "trend_both_returns_at_5x_chop"
    if abs_lookback_return_bps >= medium_threshold and abs_recent_return_bps >= medium_threshold:
        return 60, "trend_both_returns_at_3x_chop"
    return 40, "trend_confirmed_below_3x_chop"


def _reversal_confidence(
    abs_lookback_return_bps: Decimal,
    abs_recent_return_bps: Decimal,
    chop_threshold_bps: Decimal,
) -> tuple[int, str]:
    triple_threshold = chop_threshold_bps * Decimal("3")
    double_threshold = chop_threshold_bps * Decimal("2")
    if abs_lookback_return_bps >= triple_threshold and abs_recent_return_bps >= triple_threshold:
        return 80, "reversal_both_returns_at_3x_chop"
    if abs_lookback_return_bps >= double_threshold and abs_recent_return_bps >= double_threshold:
        return 60, "reversal_both_returns_at_2x_chop"
    return 40, "reversal_directional_below_2x_chop"


def _sign(value: Decimal) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0
