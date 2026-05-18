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
    uncapped_composite_score: Decimal | None = None
    capped_composite_score: Decimal | None = None
    high_score_danger_cap_applied: bool = False
    high_score_danger_cap_reason: str | None = None
    distance_to_target_abs_bps: Decimal | None = None
    overextension_distance_bps: Decimal | None = None
    side_adjusted_distance_status: str | None = None
    burst_context_status: str | None = None
    cold_start_high_ratio_overextension_reasons: tuple[str, ...] = ()
    continuation_major_danger_combo_blocked: bool = False
    continuation_major_danger_combo_reasons: tuple[str, ...] = ()

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
            "uncapped_composite_score": self.uncapped_composite_score,
            "capped_composite_score": self.capped_composite_score,
            "high_score_danger_cap_applied": self.high_score_danger_cap_applied,
            "high_score_danger_cap_reason": self.high_score_danger_cap_reason,
            "distance_to_target_abs_bps": self.distance_to_target_abs_bps,
            "overextension_distance_bps": self.overextension_distance_bps,
            "side_adjusted_distance_status": self.side_adjusted_distance_status,
            "burst_context_status": self.burst_context_status,
            "cold_start_high_ratio_overextension_reasons": list(
                self.cold_start_high_ratio_overextension_reasons
            ),
            "continuation_major_danger_combo_blocked": (
                self.continuation_major_danger_combo_blocked
            ),
            "continuation_major_danger_combo_reasons": list(
                self.continuation_major_danger_combo_reasons
            ),
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
    fake_continuation_signature: bool = False,
    reversal_probability_threshold: Decimal = Decimal("0.55"),
    is_reversal_candidate: bool = False,
    distance_to_target_bps: Decimal | None = None,
    recent_3m_return_bps: Decimal | None = None,
    recent_3m_range_bps: Decimal | None = None,
    cold_start_high_ratio_block_enabled: bool = True,
    cold_start_high_ratio_min: Decimal = Decimal("3.00"),
    cold_start_overextension_distance_bps: Decimal = Decimal("5"),
    cold_start_burst_block_enabled: bool = True,
    high_score_danger_cap_enabled: bool = True,
    high_score_danger_cap_min_score: Decimal = Decimal("0.80"),
    high_score_danger_cap_max_score: Decimal = Decimal("0.49"),
    continuation_major_danger_combo_block_enabled: bool = True,
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
    near_extreme = (
        near_extreme_distance_bps is not None
        and near_extreme_distance_bps <= near_extreme_threshold_bps
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
    components["deceleration_persistence"] = _deceleration_component(
        deceleration_persistence_count
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
    progression_weakening = False
    progression_strengthening = False
    if progression_memory is not None and not progression_memory.memory_cold_start:
        if progression_memory.progression_continuation_quality == "strengthening":
            memory_component += Decimal("0.08")
            progression_strengthening = True
            bonuses.append("progression_strengthening")
        elif progression_memory.progression_continuation_quality in {"weakening", "decaying"}:
            memory_component -= Decimal("0.25")
            progression_weakening = True
            downgrades.append("progression_weakening")
        memory_component += (progression_memory.retry_degradation_factor - ONE_DECIMAL) * Decimal("0.20")
    components["progression_memory"] = memory_component.quantize(Decimal("0.0001"))

    reversal_probability_decimal = (
        Decimal(str(reversal_probability)) if reversal_probability is not None else None
    )
    high_reversal_probability = (
        reversal_probability_decimal is not None
        and reversal_probability_decimal >= reversal_probability_threshold
    )
    reversal_component = ZERO_DECIMAL
    if reversal_probability_decimal is not None:
        if is_reversal_candidate:
            reversal_component = (
                reversal_probability_decimal - Decimal("0.50")
            ) * Decimal("0.40")
        elif high_reversal_probability:
            reversal_component = (
                Decimal("-0.18")
                if reversal_probability_decimal >= Decimal("0.65")
                else Decimal("-0.10")
            )
            downgrades.append("high_reversal_probability")
    components["reversal_probability"] = reversal_component.quantize(Decimal("0.0001"))
    if fake_continuation_signature:
        downgrades.append("fake_continuation_signature")

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
    weak_recent_return = trend_confirmation_status == "weak_recent_return"
    weak_trend_confirmation = trend_confirmation_status != "confirmed"
    ratio_decaying = ratio_decay is not None and ratio_decay > ZERO_DECIMAL
    explicit_positive_confirmation = (
        progression_strengthening
        and not ratio_decaying
        and deceleration_persistence_count <= 1
        and trend_confirmation_status == "confirmed"
        and ev is not None
        and ev >= ZERO_DECIMAL
        and not fake_continuation_signature
    )
    distance_abs = _abs_decimal(distance_to_target_bps)
    overextension_distance = (
        max(distance_abs - cold_start_overextension_distance_bps, ZERO_DECIMAL)
        if distance_abs is not None
        else None
    )
    side_adjusted_distance_status = _side_adjusted_distance_status(
        distance_abs=distance_abs,
        threshold=cold_start_overextension_distance_bps,
    )
    burst_context_status = _burst_context_status(
        recent_3m_return_bps=recent_3m_return_bps,
        recent_3m_range_bps=recent_3m_range_bps,
        recent_5m_return_bps=recent_5m_return_bps,
        recent_5m_range_bps=recent_5m_range_bps,
        range_expansion_status=range_expansion_status,
        enabled=cold_start_burst_block_enabled,
    )
    cold_or_unconfirmed = _cold_or_unconfirmed_progression(
        progression_memory=progression_memory,
        progression_strengthening=progression_strengthening,
    )
    high_ratio = (
        return_range_ratio is not None
        and return_range_ratio > cold_start_high_ratio_min
    )
    distance_overextended = (
        distance_abs is not None
        and distance_abs >= cold_start_overextension_distance_bps
    )
    burst_context = burst_context_status not in {"clear", "disabled"}
    cold_start_reasons: list[str] = []
    danger_flags = []
    if progression_weakening:
        danger_flags.append("progression_weakening")
    if deceleration_persistence_count >= 2:
        danger_flags.append("persistent_deceleration")
    if weak_recent_return:
        danger_flags.append("weak_recent_return")
        downgrades.append("weak_recent_return")
    if fake_continuation_signature:
        danger_flags.append("fake_continuation_signature")
    near_extreme_danger = near_extreme and (
        weak_recent_return
        or progression_weakening
        or deceleration_persistence_count >= 2
        or fake_continuation_signature
        or high_reversal_probability
        or (ratio_decaying and weak_trend_confirmation)
    )
    if near_extreme_danger:
        danger_flags.append("near_extreme_danger_combo")
        downgrades.append("near_extreme_danger_combo")
    if cold_or_unconfirmed:
        cold_start_reasons.append("progression_not_confirmed")
    if high_ratio:
        cold_start_reasons.append("return_range_ratio_above_high_threshold")
    if distance_overextended:
        cold_start_reasons.append("distance_to_target_abs_bps_over_threshold")
    if near_extreme_danger:
        cold_start_reasons.append("near_extreme_danger_combo")
    if burst_context:
        cold_start_reasons.append(burst_context_status)
    cold_start_high_ratio_overextension = (
        cold_start_high_ratio_block_enabled
        and cold_or_unconfirmed
        and high_ratio
        and (distance_overextended or near_extreme_danger or burst_context)
    )
    if cold_start_high_ratio_overextension:
        danger_flags.append("cold_start_high_ratio_overextension")
        downgrades.append("cold_start_high_ratio_overextension_blocked")
        hard_gates["cold_start_high_ratio_overextension"] = "blocked"
    else:
        hard_gates["cold_start_high_ratio_overextension"] = "clear"
    if high_reversal_probability and (
        progression_weakening
        or deceleration_persistence_count >= 2
        or fake_continuation_signature
        or cold_start_high_ratio_overextension
    ):
        danger_flags.append("high_reversal_probability_with_danger")

    major_combo_reasons: list[str] = []
    if progression_weakening:
        major_combo_reasons.append("progression_weakening")
    if deceleration_persistence_count >= 3:
        major_combo_reasons.append("persistent_deceleration")
    if fake_continuation_signature:
        major_combo_reasons.append("fake_continuation_signature")
    if cold_start_high_ratio_overextension:
        major_combo_reasons.append("cold_start_high_ratio_overextension")
    if near_extreme_danger:
        major_combo_reasons.append("near_extreme_danger_combo")
    if (weak_recent_return or high_reversal_probability) and (
        cold_or_unconfirmed
        or high_ratio
        or distance_overextended
        or burst_context
        or fake_continuation_signature
    ):
        if weak_recent_return:
            major_combo_reasons.append("weak_recent_return_combo")
        if high_reversal_probability:
            major_combo_reasons.append("high_reversal_probability_combo")
    major_danger = (
        progression_weakening
        or deceleration_persistence_count >= 3
        or fake_continuation_signature
        or cold_start_high_ratio_overextension
        or (
            continuation_major_danger_combo_block_enabled
            and bool(major_combo_reasons)
            and (
                weak_recent_return
                or near_extreme_danger
                or high_reversal_probability
                or high_ratio
                or distance_overextended
                or burst_context
            )
        )
    )
    uncapped_composite = continuation_score
    high_score_cap_applied = False
    high_score_cap_reason = None
    cap_danger = bool(
        progression_weakening
        or deceleration_persistence_count >= 2
        or fake_continuation_signature
        or near_extreme_danger
        or cold_start_high_ratio_overextension
        or "high_reversal_probability_with_danger" in danger_flags
        or (
            weak_recent_return
            and (
                cold_or_unconfirmed
                or high_ratio
                or distance_overextended
                or burst_context
            )
        )
    )
    if (
        high_score_danger_cap_enabled
        and cap_danger
        and continuation_score > high_score_danger_cap_min_score
        and not explicit_positive_confirmation
    ):
        continuation_score = min(continuation_score, high_score_danger_cap_max_score)
        high_score_cap_applied = True
        high_score_cap_reason = "danger_combo_high_score_cap"
        hard_gates["continuation_danger_cap"] = "capped_high_score"
        downgrades.append("continuation_danger_cap")
    else:
        hard_gates["continuation_danger_cap"] = "clear"
    if major_danger and not explicit_positive_confirmation:
        continuation_score = min(continuation_score, high_score_danger_cap_max_score)
        hard_gates["continuation_major_danger"] = "blocked"
        downgrades.append("continuation_major_danger")
    else:
        hard_gates["continuation_major_danger"] = "clear"
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
        uncapped_composite_score=uncapped_composite,
        capped_composite_score=(
            continuation_score if high_score_cap_applied or major_danger else None
        ),
        high_score_danger_cap_applied=high_score_cap_applied,
        high_score_danger_cap_reason=high_score_cap_reason,
        distance_to_target_abs_bps=distance_abs,
        overextension_distance_bps=overextension_distance,
        side_adjusted_distance_status=side_adjusted_distance_status,
        burst_context_status=burst_context_status,
        cold_start_high_ratio_overextension_reasons=tuple(
            dict.fromkeys(cold_start_reasons)
        ),
        continuation_major_danger_combo_blocked=bool(
            major_danger and not explicit_positive_confirmation
        ),
        continuation_major_danger_combo_reasons=tuple(
            dict.fromkeys(major_combo_reasons)
        ),
    )


def _ratio_component(value: Decimal | None, floor: Decimal) -> Decimal:
    if value is None:
        return Decimal("-0.08")
    if value > Decimal("3.00"):
        return Decimal("0.04")
    if value >= Decimal("1.00"):
        return Decimal("0.18")
    if value >= floor:
        return Decimal("0.08")
    return -min((floor - value) / max(floor, Decimal("0.01")) * Decimal("0.18"), Decimal("0.18"))


def _near_extreme_component(distance: Decimal | None, threshold: Decimal) -> Decimal:
    if distance is None:
        return Decimal("-0.01")
    if distance <= threshold:
        return Decimal("-0.02")
    if distance >= threshold * Decimal("1.50"):
        return Decimal("0.02")
    return Decimal("0.01")


def _decay_component(value: Decimal | None) -> Decimal:
    if value is None:
        return ZERO_DECIMAL
    if value > ZERO_DECIMAL:
        return -min(value * Decimal("0.02"), Decimal("0.03"))
    return min(abs(value) * Decimal("0.02"), Decimal("0.03"))


def _deceleration_component(count: int) -> Decimal:
    if count <= 0:
        return ZERO_DECIMAL
    if count == 1:
        return Decimal("-0.06")
    if count == 2:
        return Decimal("-0.18")
    return Decimal("-0.30")


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
        return Decimal("0.05")
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


def _abs_decimal(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return abs(Decimal(str(value)))


def _side_adjusted_distance_status(
    *,
    distance_abs: Decimal | None,
    threshold: Decimal,
) -> str:
    if distance_abs is None:
        return "distance_missing"
    if distance_abs >= threshold:
        return "overextended"
    return "not_overextended"


def _burst_context_status(
    *,
    recent_3m_return_bps: Decimal | None,
    recent_3m_range_bps: Decimal | None,
    recent_5m_return_bps: Decimal | None,
    recent_5m_range_bps: Decimal | None,
    range_expansion_status: str | None,
    enabled: bool,
) -> str:
    if not enabled:
        return "disabled"
    if range_expansion_status in {"expanding", "bursting"}:
        return "range_expansion_burst"
    recent_5m_return = _abs_decimal(recent_5m_return_bps)
    recent_5m_range = _abs_decimal(recent_5m_range_bps)
    if (
        recent_5m_return is not None
        and recent_5m_range is not None
        and recent_5m_range > ZERO_DECIMAL
        and recent_5m_return >= recent_5m_range * Decimal("0.80")
        and recent_5m_return >= Decimal("8")
    ):
        return "recent_5m_return_large_vs_range"
    recent_3m_return = _abs_decimal(recent_3m_return_bps)
    recent_3m_range = _abs_decimal(recent_3m_range_bps)
    if (
        recent_3m_return is not None
        and recent_3m_range is not None
        and recent_3m_range > ZERO_DECIMAL
        and recent_3m_return >= recent_3m_range * Decimal("0.80")
        and recent_3m_return >= Decimal("6")
    ):
        return "recent_3m_return_large_vs_range"
    return "clear"


def _cold_or_unconfirmed_progression(
    *,
    progression_memory: ProgressionMemoryState | None,
    progression_strengthening: bool,
) -> bool:
    if progression_strengthening:
        return False
    if progression_memory is None:
        return True
    if progression_memory.memory_cold_start:
        return True
    return progression_memory.progression_continuation_quality != "strengthening"


def _bounded(value: Decimal) -> Decimal:
    return min(max(value, ZERO_DECIMAL), ONE_DECIMAL).quantize(Decimal("0.0001"))


def _quality_band(score: Decimal) -> str:
    if score >= Decimal("0.60"):
        return "high_quality"
    if score >= Decimal("0.40"):
        return "borderline"
    return "block"
