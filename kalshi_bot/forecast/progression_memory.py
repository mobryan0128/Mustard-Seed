"""Short-term deterministic progression memory for scanner decisions."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Deque, Iterable


ZERO = Decimal("0")
ONE = Decimal("1")


@dataclass(frozen=True)
class ProgressionObservation:
    product_id: str
    market_ticker: str | None
    direction: str | None
    structure: str | None
    return_range_ratio: Decimal | None
    near_extreme: bool | None
    near_extreme_distance_bps: Decimal | None
    deceleration_status: str | None
    range_expansion_status: str | None
    side_currently_itm: bool | None
    side_needs_cross: bool | None
    distance_to_target_bps: Decimal | None
    required_bps_per_minute: Decimal | None
    accepted: bool
    failed_continuation: bool
    recorded_at: datetime


@dataclass(frozen=True)
class ProgressionMemoryState:
    product_id: str
    sample_count: int
    trend_age_cycles: int
    consecutive_same_side_intents: int
    failed_continuation_count: int
    near_extreme_retest_count: int
    deceleration_persistence_count: int
    range_expansion_persistence_count: int
    ratio_decay: Decimal | None
    retry_degradation_factor: Decimal
    itm_strengthening_status: str
    distance_to_target_worsening: bool
    progression_continuation_quality: str
    reversal_buildup_score: Decimal
    last_direction: str | None
    last_market_ticker: str | None
    memory_cold_start: bool

    def as_payload(self) -> dict[str, object]:
        return {
            "progression_product_id": self.product_id,
            "progression_sample_count": self.sample_count,
            "trend_age_cycles": self.trend_age_cycles,
            "consecutive_same_side_intents": self.consecutive_same_side_intents,
            "failed_continuation_count": self.failed_continuation_count,
            "near_extreme_retest_count": self.near_extreme_retest_count,
            "deceleration_persistence_count": self.deceleration_persistence_count,
            "range_expansion_persistence_count": self.range_expansion_persistence_count,
            "ratio_decay": self.ratio_decay,
            "retry_degradation_factor": self.retry_degradation_factor,
            "itm_strengthening_status": self.itm_strengthening_status,
            "distance_to_target_worsening": self.distance_to_target_worsening,
            "progression_continuation_quality": self.progression_continuation_quality,
            "reversal_buildup_score": self.reversal_buildup_score,
            "progression_last_direction": self.last_direction,
            "progression_last_market_ticker": self.last_market_ticker,
            "memory_cold_start": self.memory_cold_start,
        }


class ProgressionMemory:
    """Maintain bounded per-product memory without external side effects."""

    def __init__(
        self,
        *,
        window_cycles: int,
        max_age_seconds: int,
        retry_score_decay: Decimal,
    ) -> None:
        self._window_cycles = max(int(window_cycles), 1)
        self._max_age_seconds = max(int(max_age_seconds), 1)
        self._retry_score_decay = Decimal(str(retry_score_decay))
        self._history: dict[str, Deque[ProgressionObservation]] = {}

    def states_by_product(self) -> dict[str, ProgressionMemoryState]:
        return {product_id: self.state(product_id) for product_id in self._history}

    def state(self, product_id: str) -> ProgressionMemoryState:
        product_key = product_id.upper()
        history = tuple(self._active_history(product_key))
        if not history:
            return ProgressionMemoryState(
                product_id=product_key,
                sample_count=0,
                trend_age_cycles=0,
                consecutive_same_side_intents=0,
                failed_continuation_count=0,
                near_extreme_retest_count=0,
                deceleration_persistence_count=0,
                range_expansion_persistence_count=0,
                ratio_decay=None,
                retry_degradation_factor=ONE,
                itm_strengthening_status="unknown",
                distance_to_target_worsening=False,
                progression_continuation_quality="cold_start",
                reversal_buildup_score=ZERO,
                last_direction=None,
                last_market_ticker=None,
                memory_cold_start=True,
            )
        last = history[-1]
        same_side = _count_suffix(history, lambda item: item.direction == last.direction)
        failed = sum(1 for item in history if item.failed_continuation)
        near_extreme = sum(1 for item in history if item.near_extreme)
        decel = _count_suffix(
            history,
            lambda item: item.deceleration_status
            in {"decelerating_after_burst", "bursting", "still_moving"},
        )
        expanding = _count_suffix(
            history,
            lambda item: item.range_expansion_status in {"expanding", "bursting"},
        )
        ratio_decay = _ratio_decay(history)
        retry_factor = max(ZERO, ONE - (self._retry_score_decay * Decimal(failed)))
        itm_status = _itm_strengthening_status(history)
        distance_worsening = _distance_worsening(history)
        reversal_buildup = _bounded_probability(
            Decimal(near_extreme) * Decimal("0.10")
            + Decimal(decel) * Decimal("0.15")
            + Decimal(failed) * Decimal("0.15")
            + (Decimal("0.15") if ratio_decay is not None and ratio_decay > ZERO else ZERO)
        )
        continuation_quality = _continuation_quality(
            history=history,
            ratio_decay=ratio_decay,
            deceleration_count=decel,
            failed_count=failed,
        )
        return ProgressionMemoryState(
            product_id=product_key,
            sample_count=len(history),
            trend_age_cycles=len(history),
            consecutive_same_side_intents=same_side,
            failed_continuation_count=failed,
            near_extreme_retest_count=near_extreme,
            deceleration_persistence_count=decel,
            range_expansion_persistence_count=expanding,
            ratio_decay=ratio_decay,
            retry_degradation_factor=retry_factor.quantize(Decimal("0.0001")),
            itm_strengthening_status=itm_status,
            distance_to_target_worsening=distance_worsening,
            progression_continuation_quality=continuation_quality,
            reversal_buildup_score=reversal_buildup,
            last_direction=last.direction,
            last_market_ticker=last.market_ticker,
            memory_cold_start=False,
        )

    def update_many(self, observations: Iterable[ProgressionObservation]) -> None:
        for observation in observations:
            self.update(observation)

    def update(self, observation: ProgressionObservation) -> None:
        product_key = observation.product_id.upper()
        history = self._history.setdefault(
            product_key,
            deque(maxlen=self._window_cycles),
        )
        history.append(observation)
        self._history[product_key] = deque(
            self._active_history(product_key),
            maxlen=self._window_cycles,
        )

    def _active_history(self, product_id: str) -> tuple[ProgressionObservation, ...]:
        history = tuple(self._history.get(product_id.upper(), ()))
        if not history:
            return ()
        now = datetime.now(timezone.utc)
        active = tuple(
            item
            for item in history
            if (now - item.recorded_at.astimezone(timezone.utc)).total_seconds()
            <= self._max_age_seconds
        )
        return active[-self._window_cycles :]


def observation_from_payload(
    *,
    product_id: str,
    market_ticker: str | None,
    direction: str | None,
    structure: str | None,
    return_range_ratio: Decimal | None,
    near_extreme: bool | None,
    near_extreme_distance_bps: Decimal | None,
    deceleration_status: str | None,
    range_expansion_status: str | None,
    side_currently_itm: bool | None,
    side_needs_cross: bool | None,
    distance_to_target_bps: Decimal | None,
    required_bps_per_minute: Decimal | None,
    accepted: bool,
    reason: str | None = None,
) -> ProgressionObservation:
    failed_continuation = (
        structure == "trend"
        and not accepted
        and reason
        in {
            "exhaustion_guard_blocked",
            "composite_quality_blocked",
            "retry_persistence_blocked",
            "quiet_continuation_near_recent_extreme",
            "quiet_continuation_decelerating_after_burst",
        }
    )
    return ProgressionObservation(
        product_id=product_id,
        market_ticker=market_ticker,
        direction=direction,
        structure=structure,
        return_range_ratio=return_range_ratio,
        near_extreme=near_extreme,
        near_extreme_distance_bps=near_extreme_distance_bps,
        deceleration_status=deceleration_status,
        range_expansion_status=range_expansion_status,
        side_currently_itm=side_currently_itm,
        side_needs_cross=side_needs_cross,
        distance_to_target_bps=distance_to_target_bps,
        required_bps_per_minute=required_bps_per_minute,
        accepted=accepted,
        failed_continuation=failed_continuation,
        recorded_at=datetime.now(timezone.utc),
    )


def _count_suffix(
    history: tuple[ProgressionObservation, ...],
    predicate,
) -> int:
    count = 0
    for item in reversed(history):
        if not predicate(item):
            break
        count += 1
    return count


def _ratio_decay(history: tuple[ProgressionObservation, ...]) -> Decimal | None:
    ratios = [item.return_range_ratio for item in history if item.return_range_ratio is not None]
    if len(ratios) < 2:
        return None
    return (ratios[-2] - ratios[-1]).quantize(Decimal("0.0001"))


def _itm_strengthening_status(history: tuple[ProgressionObservation, ...]) -> str:
    distances = [
        item.distance_to_target_bps
        for item in history
        if item.side_currently_itm and item.distance_to_target_bps is not None
    ]
    if len(distances) < 2:
        return "unknown"
    if abs(distances[-1]) > abs(distances[-2]):
        return "weakening"
    if abs(distances[-1]) < abs(distances[-2]):
        return "strengthening"
    return "flat"


def _distance_worsening(history: tuple[ProgressionObservation, ...]) -> bool:
    distances = [item.distance_to_target_bps for item in history if item.distance_to_target_bps is not None]
    if len(distances) < 2:
        return False
    return abs(distances[-1]) > abs(distances[-2])


def _continuation_quality(
    *,
    history: tuple[ProgressionObservation, ...],
    ratio_decay: Decimal | None,
    deceleration_count: int,
    failed_count: int,
) -> str:
    latest_ratio = history[-1].return_range_ratio
    if latest_ratio is not None and latest_ratio >= Decimal("1.00") and deceleration_count == 0:
        return "strengthening"
    if failed_count > 0 or deceleration_count >= 2:
        return "weakening"
    if ratio_decay is not None and ratio_decay > ZERO:
        return "decaying"
    return "stable"


def _bounded_probability(value: Decimal) -> Decimal:
    return min(max(value, ZERO), ONE).quantize(Decimal("0.0001"))
