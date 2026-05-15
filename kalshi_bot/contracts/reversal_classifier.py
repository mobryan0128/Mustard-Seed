"""Deterministic reversal probability classifier."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from kalshi_bot.forecast.progression_memory import ProgressionMemoryState


ZERO = Decimal("0")
ONE = Decimal("1")


@dataclass(frozen=True)
class ReversalClassification:
    reversal_probability: Decimal
    reversal_quality_band: str
    fake_continuation_signature: bool
    rejection_reason: str | None
    component_scores: dict[str, Decimal]

    def as_payload(self) -> dict[str, object]:
        return {
            "reversal_probability": self.reversal_probability,
            "reversal_quality_band": self.reversal_quality_band,
            "fake_continuation_signature": self.fake_continuation_signature,
            "reversal_classifier_rejection_reason": self.rejection_reason,
            "reversal_component_scores": dict(self.component_scores),
        }


def classify_reversal_probability(
    *,
    return_range_ratio: Decimal | None,
    ratio_floor: Decimal,
    near_extreme_distance_bps: Decimal | None,
    near_extreme_threshold_bps: Decimal,
    deceleration_status: str | None,
    range_expansion_status: str | None,
    trend_confirmation_status: str | None,
    required_bps_per_minute: Decimal | None,
    memory_state: ProgressionMemoryState | None,
) -> ReversalClassification:
    """Estimate reversal probability from auditable deterministic components."""

    components: dict[str, Decimal] = {}
    probability = Decimal("0.20")
    if return_range_ratio is None:
        components["ratio_missing"] = Decimal("0.00")
    elif return_range_ratio < ratio_floor:
        score = min((ratio_floor - return_range_ratio) / max(ratio_floor, Decimal("0.01")), ONE)
        components["low_ratio"] = (score * Decimal("0.20")).quantize(Decimal("0.0001"))
        probability += components["low_ratio"]
    else:
        components["ratio_supports_continuation"] = Decimal("-0.05")
        probability -= Decimal("0.05")

    if near_extreme_distance_bps is not None and near_extreme_distance_bps <= near_extreme_threshold_bps:
        components["near_extreme"] = Decimal("0.15")
        probability += Decimal("0.15")

    if deceleration_status in {"decelerating_after_burst", "bursting", "still_moving"}:
        components["deceleration"] = Decimal("0.15")
        probability += Decimal("0.15")

    if range_expansion_status in {"expanding", "bursting"}:
        components["range_expansion"] = Decimal("0.10")
        probability += Decimal("0.10")

    if trend_confirmation_status in {"weak_recent_return", "unconfirmed"}:
        components["weak_trend_confirmation"] = Decimal("0.08")
        probability += Decimal("0.08")

    if required_bps_per_minute is not None and required_bps_per_minute > Decimal("0.25"):
        components["required_bps_pressure"] = Decimal("0.07")
        probability += Decimal("0.07")

    if memory_state is not None and not memory_state.memory_cold_start:
        memory_component = (
            memory_state.reversal_buildup_score * Decimal("0.25")
            + Decimal(memory_state.failed_continuation_count) * Decimal("0.05")
            + Decimal(memory_state.deceleration_persistence_count) * Decimal("0.03")
        )
        memory_component = min(memory_component, Decimal("0.20"))
        components["progression_memory"] = memory_component.quantize(Decimal("0.0001"))
        probability += memory_component
        if memory_state.progression_continuation_quality == "strengthening":
            components["memory_strengthening_continuation"] = Decimal("-0.10")
            probability -= Decimal("0.10")

    probability = _bounded(probability)
    fake_signature = probability >= Decimal("0.55")
    if probability >= Decimal("0.65"):
        band = "high"
    elif probability >= Decimal("0.55"):
        band = "qualified"
    elif probability >= Decimal("0.45"):
        band = "borderline"
    else:
        band = "low"
    rejection = None if fake_signature else "reversal_probability_below_signature"
    return ReversalClassification(
        reversal_probability=probability,
        reversal_quality_band=band,
        fake_continuation_signature=fake_signature,
        rejection_reason=rejection,
        component_scores=components,
    )


def reversal_expected_value(
    *,
    reversal_probability: Decimal | None,
    executable_price: Decimal | None,
) -> Decimal | None:
    if reversal_probability is None or executable_price is None:
        return None
    return (Decimal(str(reversal_probability)) - Decimal(str(executable_price))).quantize(
        Decimal("0.0001")
    )


def _bounded(value: Decimal) -> Decimal:
    return min(max(value, ZERO), ONE).quantize(Decimal("0.0001"))
