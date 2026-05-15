"""Pure contract scoring helpers for Phase 6 ranking."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from kalshi_bot.forecast.progression_memory import ProgressionMemoryState


ZERO_DECIMAL = Decimal("0")
ONE_DECIMAL = Decimal("1")


@dataclass(frozen=True)
class ContractScore:
    """Component score used for deterministic contract ranking."""

    confidence: int
    spread_width: Decimal
    top_of_book_liquidity: Decimal
    dollar_volume: Decimal
    composite_score: Decimal | None = None

    def ranking_key(self) -> tuple[int, Decimal, Decimal, Decimal, Decimal]:
        """Return the deterministic sort key used by the scanner."""

        return (
            -self.confidence,
            -(self.composite_score or ZERO_DECIMAL),
            self.spread_width,
            -self.top_of_book_liquidity,
            -self.dollar_volume,
        )


@dataclass(frozen=True)
class CompositeQualityScore:
    """Deterministic continuation/reversal scoring payload."""

    composite_score: Decimal
    continuation_score: Decimal
    reversal_score: Decimal
    hit_probability_estimate: Decimal
    quality_band: str
    component_scores: dict[str, Decimal]
    downgrade_reasons: tuple[str, ...]
    bonus_reasons: tuple[str, ...]
    hard_gate_statuses: dict[str, str]

    def as_payload(self) -> dict[str, object]:
        return {
            "composite_score": self.composite_score,
            "continuation_score": self.continuation_score,
            "reversal_score": self.reversal_score,
            "hit_probability_estimate": self.hit_probability_estimate,
            "quality_band": self.quality_band,
            "score_components": dict(self.component_scores),
            "candidate_downgrade_reasons": list(self.downgrade_reasons),
            "candidate_upgrade_reasons": list(self.bonus_reasons),
            "hard_gate_results": dict(self.hard_gate_statuses),
        }


def score_contract(
    *,
    confidence: int,
    best_bid: Decimal,
    best_ask: Decimal,
    yes_bid_size_fp: Decimal | None,
    yes_ask_size_fp: Decimal | None,
    dollar_volume: Decimal | None,
    composite_score: Decimal | None = None,
) -> ContractScore:
    """Score one contract from already-normalized market and bias inputs."""

    return ContractScore(
        confidence=confidence,
        spread_width=best_ask - best_bid,
        top_of_book_liquidity=(yes_bid_size_fp or ZERO_DECIMAL) + (yes_ask_size_fp or ZERO_DECIMAL),
        dollar_volume=dollar_volume or ZERO_DECIMAL,
        composite_score=composite_score,
    )


def score_candidate_quality(
    *,
    return_range_ratio: Decimal | None,
    ratio_floor: Decimal,
    ratio_decay: Decimal | None,
    near_extreme_distance_bps: Decimal | None,
    near_extreme_threshold_bps: Decimal,
    recent_5m_range_bps: Decimal | None,
    recent_5m_return_bps: Decimal | None,
    lookback_return_bps: Decimal | None,
    trend_confirmation_status: str | None,
    deceleration_persistence_count: int,
    range_expansion_status: str | None,
    ev: Decimal | None,
    price: Decimal | None,
    side_needs_cross: bool | None,
    required_bps_per_minute: Decimal | None,
    required_bps_per_minute_limit: Decimal,
    product_volatility_scale: Decimal,
    trend_age_cycles: int,
    failed_attempts: int,
    progression_memory: ProgressionMemoryState | None,
    reversal_probability: Decimal | None,
    is_reversal_candidate: bool = False,
) -> CompositeQualityScore:
    """Score one candidate using fixed, explainable components."""

    components: dict[str, Decimal] = {}
    downgrades: list[str] = []
    bonuses: list[str] = []
    hard_gates: dict[str, str] = {}

    ratio_component = _ratio_component(return_range_ratio, ratio_floor)
    components["return_range_ratio"] = ratio_component
    if return_range_ratio is None:
        downgrades.append("return_range_ratio_missing")
    elif return_range_ratio < ratio_floor:
        downgrades.append("return_range_ratio_below_floor")
    else:
        bonuses.append("return_range_ratio_supportive")

    near_extreme_component = _near_extreme_component(
        near_extreme_distance_bps,
        near_extreme_threshold_bps,
    )
    components["near_extreme_distance"] = near_extreme_component
    if near_extreme_component < ZERO_DECIMAL:
        downgrades.append("near_extreme")

    components["ratio_decay"] = _decay_component(ratio_decay)
    if ratio_decay is not None and ratio_decay > ZERO_DECIMAL:
        downgrades.append("ratio_decaying")

    components["recent_5m_range"] = _range_component(recent_5m_range_bps)
    components["recent_5m_return"] = _return_component(recent_5m_return_bps)
    components["lookback_return"] = _return_component(lookback_return_bps)
    components["trend_confirmation"] = _trend_component(trend_confirmation_status)
    components["deceleration_persistence"] = -min(
        Decimal(deceleration_persistence_count) * Decimal("0.04"),
        Decimal("0.16"),
    )
    if deceleration_persistence_count >= 2:
        downgrades.append("persistent_deceleration")

    components["range_expansion"] = (
        Decimal("-0.08")
        if range_expansion_status in {"expanding", "bursting"}
        else Decimal("0.04")
    )
    components["ev"] = _ev_component(ev)
    components["price"] = _price_component(price)
    components["required_bps_per_minute"] = _required_bps_component(
        required_bps_per_minute,
        required_bps_per_minute_limit,
    )
    components["product_volatility"] = -max(
        product_volatility_scale - ONE_DECIMAL,
        ZERO_DECIMAL,
    ) * Decimal("0.03")
    components["trend_age"] = -min(Decimal(trend_age_cycles) * Decimal("0.01"), Decimal("0.08"))
    components["failed_attempts"] = -min(
        Decimal(failed_attempts) * Decimal("0.06"),
        Decimal("0.18"),
    )
    if failed_attempts:
        downgrades.append("failed_continuation_memory")

    memory_component = ZERO_DECIMAL
    if progression_memory is not None and not progression_memory.memory_cold_start:
        if progression_memory.progression_continuation_quality == "strengthening":
            memory_component += Decimal("0.08")
            bonuses.append("progression_strengthening")
        elif progression_memory.progression_continuation_quality in {"weakening", "decaying"}:
            memory_component -= Decimal("0.08")
            downgrades.append("progression_weakening")
        memory_component += (progression_memory.retry_degradation_factor - ONE_DECIMAL) * Decimal("0.20")
    components["progression_memory"] = memory_component.quantize(Decimal("0.0001"))

    reversal_component = ZERO_DECIMAL
    if reversal_probability is not None:
        reversal_component = (Decimal(str(reversal_probability)) - Decimal("0.50")) * Decimal("0.40")
    components["reversal_probability"] = reversal_component.quantize(Decimal("0.0001"))

    hard_gates["needs_cross"] = "blocked" if side_needs_cross else "clear"
    hard_gates["required_bps_per_minute"] = (
        "blocked"
        if required_bps_per_minute is not None
        and required_bps_per_minute > required_bps_per_minute_limit
        else "clear"
    )

    base = Decimal("0.45")
    continuation_raw = base + sum(components.values(), ZERO_DECIMAL)
    reversal_raw = (
        base
        + ratio_component
        + near_extreme_component
        + components["ratio_decay"]
        + components["deceleration_persistence"]
        + components["range_expansion"]
        + components["ev"]
        + components["price"]
        + reversal_component
        + memory_component
    )
    continuation_score = _bounded(continuation_raw)
    reversal_score = _bounded(reversal_raw)
    composite = reversal_score if is_reversal_candidate else continuation_score
    hit_probability = _bounded(Decimal("0.35") + composite * Decimal("0.50"))
    quality_band = _quality_band(composite)

    return CompositeQualityScore(
        composite_score=composite,
        continuation_score=continuation_score,
        reversal_score=reversal_score,
        hit_probability_estimate=hit_probability,
        quality_band=quality_band,
        component_scores={key: value.quantize(Decimal("0.0001")) for key, value in components.items()},
        downgrade_reasons=tuple(dict.fromkeys(downgrades)),
        bonus_reasons=tuple(dict.fromkeys(bonuses)),
        hard_gate_statuses=hard_gates,
    )


def _ratio_component(value: Decimal | None, floor: Decimal) -> Decimal:
    if value is None:
        return Decimal("-0.08")
    if value >= Decimal("1.00"):
        return Decimal("0.18")
    if value >= floor:
        return Decimal("0.08")
    return -min((floor - value) / max(floor, Decimal("0.01")) * Decimal("0.18"), Decimal("0.18"))


def _near_extreme_component(distance: Decimal | None, threshold: Decimal) -> Decimal:
    if distance is None:
        return Decimal("-0.03")
    if distance <= threshold:
        return Decimal("-0.12")
    if distance >= threshold * Decimal("1.50"):
        return Decimal("0.08")
    return Decimal("0.02")


def _decay_component(value: Decimal | None) -> Decimal:
    if value is None:
        return ZERO_DECIMAL
    if value > ZERO_DECIMAL:
        return -min(value * Decimal("0.05"), Decimal("0.12"))
    return min(abs(value) * Decimal("0.03"), Decimal("0.06"))


def _range_component(value: Decimal | None) -> Decimal:
    if value is None:
        return ZERO_DECIMAL
    if value <= Decimal("15"):
        return Decimal("0.04")
    if value <= Decimal("30"):
        return ZERO_DECIMAL
    return Decimal("-0.05")


def _return_component(value: Decimal | None) -> Decimal:
    if value is None:
        return ZERO_DECIMAL
    magnitude = abs(value)
    if magnitude >= Decimal("12"):
        return Decimal("0.06")
    if magnitude >= Decimal("5"):
        return Decimal("0.02")
    return Decimal("-0.03")


def _trend_component(status: str | None) -> Decimal:
    if status == "confirmed":
        return Decimal("0.08")
    if status == "weak_recent_return":
        return Decimal("-0.02")
    if status in {"missing_recent_return", "missing_feasibility"}:
        return Decimal("-0.04")
    return ZERO_DECIMAL


def _ev_component(value: Decimal | None) -> Decimal:
    if value is None:
        return ZERO_DECIMAL
    if value >= Decimal("0.10"):
        return Decimal("0.10")
    if value >= ZERO_DECIMAL:
        return Decimal("0.04")
    return Decimal("-0.12")


def _price_component(value: Decimal | None) -> Decimal:
    if value is None:
        return ZERO_DECIMAL
    if value <= Decimal("0.35"):
        return Decimal("0.08")
    if value <= Decimal("0.60"):
        return Decimal("0.02")
    if value <= Decimal("0.70"):
        return Decimal("-0.04")
    return Decimal("-0.10")


def _required_bps_component(value: Decimal | None, limit: Decimal) -> Decimal:
    if value is None:
        return Decimal("-0.03")
    if value <= ZERO_DECIMAL:
        return Decimal("0.06")
    if value <= limit:
        return Decimal("0.02")
    return Decimal("-0.12")


def _bounded(value: Decimal) -> Decimal:
    return min(max(value, ZERO_DECIMAL), ONE_DECIMAL).quantize(Decimal("0.0001"))


def _quality_band(score: Decimal) -> str:
    if score >= Decimal("0.60"):
        return "high_quality"
    if score >= Decimal("0.40"):
        return "borderline"
    return "block"
