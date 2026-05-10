"""Rolling directional bias engine fed by external crypto price state."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Deque, Mapping

from kalshi_bot.config.settings import KalshiSettings
from kalshi_bot.forecast.state_classifier import BiasClassification, classify_bias_state
from kalshi_bot.timing.time_sync_checker import TimeSyncObservation

if TYPE_CHECKING:
    from kalshi_bot.clients.crypto_feed_client import CryptoFeedSnapshot


BASIS_POINTS_MULTIPLIER = Decimal("10000")
IMPULSE_SHORT_WINDOW = timedelta(seconds=20)
IMPULSE_AVERAGE_WINDOW = timedelta(seconds=120)
IMPULSE_MULTIPLIER = Decimal("2")
IMPULSE_OVERRIDE_NEAR_CONFIDENCE = 30
IMPULSE_OVERRIDE_MAX_CONFIDENCE = 40


class BiasEngineError(ValueError):
    """Raised when bias engine configuration or input is invalid."""


@dataclass(frozen=True)
class PriceObservation:
    """One price observation retained in the rolling window."""

    observed_at: datetime
    price: Decimal


@dataclass(frozen=True)
class BiasRiskFlags:
    """Risk flags that suppress actionable bias output."""

    insufficient_history: bool
    stale_data: bool
    time_sync_failed: bool


@dataclass(frozen=True)
class BiasState:
    """Normalized per-product bias output."""

    product_id: str
    direction: str
    confidence: int
    structure: str
    risk_flags: BiasRiskFlags
    latest_price: Decimal | None
    lookback_return_bps: Decimal | None
    recent_return_bps: Decimal | None
    observation_count: int
    as_of: str | None
    impulse_direction: str | None = None
    impulse_return_bps: Decimal | None = None
    impulse_detected: bool = False
    classification_reason: str | None = None
    chop_threshold_bps: Decimal | None = None
    recent_window_seconds: int | None = None
    lookback_window_seconds: int | None = None
    recent_abs_bps: Decimal | None = None
    lookback_abs_bps: Decimal | None = None
    recent_threshold_gap_bps: Decimal | None = None
    lookback_threshold_gap_bps: Decimal | None = None
    recent_3m_return_bps: Decimal | None = None
    recent_5m_return_bps: Decimal | None = None
    recent_3m_range_bps: Decimal | None = None
    recent_5m_range_bps: Decimal | None = None
    distance_to_recent_high_bps: Decimal | None = None
    distance_to_recent_low_bps: Decimal | None = None


@dataclass(frozen=True)
class BiasSnapshot:
    """Current bias state for all configured products."""

    products: dict[str, BiasState]


class BiasEngine:
    """Maintain rolling price history and emit deterministic bias states."""

    def __init__(
        self,
        *,
        products: tuple[str, ...],
        lookback_seconds: int,
        recent_window_seconds: int,
        min_samples: int,
        stale_data_seconds: int,
        chop_threshold_bps: int | Decimal,
        impulse_min_abs_bps: Decimal,
    ) -> None:
        normalized_products = tuple(
            dict.fromkeys(product.strip() for product in products if product.strip())
        )
        if not normalized_products:
            raise BiasEngineError("At least one bias product is required.")
        if lookback_seconds <= 0:
            raise BiasEngineError("lookback_seconds must be greater than zero.")
        if recent_window_seconds <= 0 or recent_window_seconds > lookback_seconds:
            raise BiasEngineError(
                "recent_window_seconds must be greater than zero and less than or equal to "
                "lookback_seconds."
            )
        if min_samples <= 1:
            raise BiasEngineError("min_samples must be greater than one.")
        if stale_data_seconds <= 0:
            raise BiasEngineError("stale_data_seconds must be greater than zero.")
        if impulse_min_abs_bps <= 0:
            raise BiasEngineError("impulse_min_abs_bps must be greater than zero.")

        self._products = normalized_products
        self._lookback = timedelta(seconds=lookback_seconds)
        self._recent_window = timedelta(seconds=recent_window_seconds)
        self._min_samples = min_samples
        self._stale_data = timedelta(seconds=stale_data_seconds)
        self._chop_threshold_bps = Decimal(str(chop_threshold_bps))
        self._impulse_min_abs_bps = Decimal(str(impulse_min_abs_bps))
        self._history: dict[str, Deque[PriceObservation]] = {
            product: deque() for product in self._products
        }
        self._latest_snapshot = BiasSnapshot(products={})

    @classmethod
    def from_settings(cls, settings: KalshiSettings) -> "BiasEngine":
        return cls(
            products=settings.bias_products,
            lookback_seconds=settings.bias_lookback_seconds,
            recent_window_seconds=settings.bias_recent_window_seconds,
            min_samples=settings.bias_min_samples,
            stale_data_seconds=settings.bias_stale_data_seconds,
            chop_threshold_bps=settings.bias_chop_threshold_bps,
            impulse_min_abs_bps=settings.bias_impulse_min_abs_bps,
        )

    def ingest(
        self,
        snapshot: "CryptoFeedSnapshot",
        time_sync_observations: Mapping[str, TimeSyncObservation] | None = None,
    ) -> BiasSnapshot:
        products: dict[str, BiasState] = {}
        sync_observations = time_sync_observations or {}

        for product_id in self._products:
            state = snapshot.products.get(product_id)
            if state is not None and state.price is not None and state.source_timestamp:
                observed_at = _parse_timestamp(state.source_timestamp)
                self._append_observation(product_id, observed_at, state.price)

            history = self._history[product_id]
            latest_observation = history[-1] if history else None
            as_of = latest_observation.observed_at if latest_observation else None
            if as_of is not None:
                self._prune_history(product_id, as_of)
                history = self._history[product_id]
                latest_observation = history[-1] if history else None

            lookback_return_bps = _compute_return_bps(history, history[0] if history else None)
            recent_anchor = _recent_anchor(history, self._recent_window)
            recent_return_bps = _compute_return_bps(history, recent_anchor)
            recent_3m_return_bps = _window_return_bps(
                history,
                window=timedelta(minutes=3),
            )
            recent_5m_return_bps = _window_return_bps(
                history,
                window=timedelta(minutes=5),
            )
            recent_3m_range_bps = _window_range_bps(
                history,
                window=timedelta(minutes=3),
            )
            recent_5m_range_bps = _window_range_bps(
                history,
                window=timedelta(minutes=5),
            )
            (
                distance_to_recent_high_bps,
                distance_to_recent_low_bps,
            ) = _distance_to_recent_extremes_bps(
                history,
                window=timedelta(minutes=5),
            )
            impulse_diagnostics = _impulse_diagnostics(
                history,
                min_abs_bps=self._impulse_min_abs_bps,
            )

            risk_flags = BiasRiskFlags(
                insufficient_history=(
                    latest_observation is None
                    or len(history) < self._min_samples
                    or recent_anchor is None
                ),
                stale_data=(
                    latest_observation is None
                    or as_of is None
                    or datetime.now(timezone.utc) - as_of > self._stale_data
                ),
                time_sync_failed=(
                    product_id in sync_observations
                    and not sync_observations[product_id].within_threshold
                ),
            )
            classification = classify_bias_state(
                lookback_return_bps=lookback_return_bps,
                recent_return_bps=recent_return_bps,
                chop_threshold_bps=self._chop_threshold_bps,
                insufficient_history=risk_flags.insufficient_history,
                stale_data=risk_flags.stale_data,
                time_sync_failed=risk_flags.time_sync_failed,
            )
            classification = _apply_impulse_bias_override(
                classification=classification,
                risk_flags=risk_flags,
                impulse_diagnostics=impulse_diagnostics,
                impulse_min_abs_bps=self._impulse_min_abs_bps,
            )

            products[product_id] = BiasState(
                product_id=product_id,
                direction=classification.direction,
                confidence=classification.confidence,
                structure=classification.structure,
                risk_flags=risk_flags,
                latest_price=latest_observation.price if latest_observation else None,
                lookback_return_bps=lookback_return_bps,
                recent_return_bps=recent_return_bps,
                observation_count=len(history),
                as_of=as_of.isoformat() if as_of is not None else None,
                impulse_direction=impulse_diagnostics.direction,
                impulse_return_bps=impulse_diagnostics.return_bps,
                impulse_detected=impulse_diagnostics.detected,
                classification_reason=classification.classification_reason,
                chop_threshold_bps=self._chop_threshold_bps,
                recent_window_seconds=int(self._recent_window.total_seconds()),
                lookback_window_seconds=int(self._lookback.total_seconds()),
                recent_abs_bps=_absolute_return_bps(recent_return_bps),
                lookback_abs_bps=_absolute_return_bps(lookback_return_bps),
                recent_threshold_gap_bps=_threshold_gap_bps(
                    recent_return_bps,
                    threshold_bps=self._chop_threshold_bps,
                ),
                lookback_threshold_gap_bps=_threshold_gap_bps(
                    lookback_return_bps,
                    threshold_bps=self._chop_threshold_bps,
                ),
                recent_3m_return_bps=recent_3m_return_bps,
                recent_5m_return_bps=recent_5m_return_bps,
                recent_3m_range_bps=recent_3m_range_bps,
                recent_5m_range_bps=recent_5m_range_bps,
                distance_to_recent_high_bps=distance_to_recent_high_bps,
                distance_to_recent_low_bps=distance_to_recent_low_bps,
            )

        self._latest_snapshot = BiasSnapshot(products=products)
        return self._latest_snapshot

    def snapshot(self) -> BiasSnapshot:
        return self._latest_snapshot

    def _append_observation(
        self,
        product_id: str,
        observed_at: datetime,
        price: Decimal,
    ) -> None:
        history = self._history[product_id]
        if history and observed_at < history[-1].observed_at:
            return
        if history and observed_at == history[-1].observed_at and price == history[-1].price:
            return
        history.append(PriceObservation(observed_at=observed_at, price=price))
        self._prune_history(product_id, observed_at)

    def _prune_history(self, product_id: str, as_of: datetime) -> None:
        cutoff = as_of - self._lookback
        history = self._history[product_id]
        while history and history[0].observed_at < cutoff:
            history.popleft()


@dataclass(frozen=True)
class _ImpulseDiagnostics:
    direction: str | None
    return_bps: Decimal | None
    detected: bool


def _apply_impulse_bias_override(
    *,
    classification: BiasClassification,
    risk_flags: BiasRiskFlags,
    impulse_diagnostics: _ImpulseDiagnostics,
    impulse_min_abs_bps: Decimal,
) -> BiasClassification:
    clean_risk = not (
        risk_flags.insufficient_history
        or risk_flags.stale_data
        or risk_flags.time_sync_failed
    )
    if (
        classification.direction == "neutral"
        and classification.structure == "chop"
        and classification.confidence <= 10
        and clean_risk
        and impulse_diagnostics.detected
        and impulse_diagnostics.direction in {"up", "down"}
    ):
        return BiasClassification(
            direction=impulse_diagnostics.direction,
            structure="trend",
            confidence=_impulse_override_confidence(
                impulse_diagnostics.return_bps,
                impulse_min_abs_bps=impulse_min_abs_bps,
            ),
            classification_reason="impulse_override_from_chop",
        )
    return classification


def _parse_timestamp(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise BiasEngineError("Crypto feed source_timestamp must be ISO-8601.") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _recent_anchor(
    history: Deque[PriceObservation],
    recent_window: timedelta,
) -> PriceObservation | None:
    if len(history) < 2:
        return None
    latest = history[-1]
    cutoff = latest.observed_at - recent_window
    candidate: PriceObservation | None = None
    for observation in history:
        if observation.observed_at >= cutoff:
            candidate = observation
            break
    if candidate is None:
        candidate = history[-1]
    if candidate.observed_at == latest.observed_at:
        return None
    return candidate


def _impulse_diagnostics(
    history: Deque[PriceObservation],
    *,
    min_abs_bps: Decimal,
) -> _ImpulseDiagnostics:
    short_anchor = _recent_anchor(history, IMPULSE_SHORT_WINDOW)
    short_return_bps = _compute_return_bps(history, short_anchor)
    average_movement_bps = _average_absolute_movement_bps(
        history,
        average_window=IMPULSE_AVERAGE_WINDOW,
        movement_window=IMPULSE_SHORT_WINDOW,
    )
    direction = _return_direction(short_return_bps)
    detected = (
        short_return_bps is not None
        and average_movement_bps is not None
        and average_movement_bps > 0
        and abs(short_return_bps) >= min_abs_bps
        and abs(short_return_bps) > average_movement_bps * IMPULSE_MULTIPLIER
    )
    return _ImpulseDiagnostics(
        direction=direction if detected else None,
        return_bps=short_return_bps,
        detected=detected,
    )


def _impulse_override_confidence(
    return_bps: Decimal | None,
    *,
    impulse_min_abs_bps: Decimal,
) -> int:
    if return_bps is None:
        return IMPULSE_OVERRIDE_NEAR_CONFIDENCE
    if abs(return_bps) >= impulse_min_abs_bps * Decimal("2"):
        return IMPULSE_OVERRIDE_MAX_CONFIDENCE
    return IMPULSE_OVERRIDE_NEAR_CONFIDENCE


def _average_absolute_movement_bps(
    history: Deque[PriceObservation],
    *,
    average_window: timedelta,
    movement_window: timedelta,
) -> Decimal | None:
    if len(history) < 2:
        return None
    latest = history[-1]
    cutoff = latest.observed_at - average_window
    observations = tuple(history)
    window_observations = tuple(
        observation for observation in history if observation.observed_at >= cutoff
    )
    if len(window_observations) < 2:
        return None

    movements: list[Decimal] = []
    for observation in window_observations:
        anchor = _anchor_for_observation(
            observations,
            observation=observation,
            window=movement_window,
        )
        if anchor is None or anchor.observed_at == observation.observed_at:
            continue
        if anchor.price <= 0:
            raise BiasEngineError("Anchor price must be greater than zero.")
        movement = (
            (observation.price - anchor.price)
            / anchor.price
            * BASIS_POINTS_MULTIPLIER
        ).quantize(Decimal("0.001"))
        movements.append(abs(movement))

    if not movements:
        return None
    return (sum(movements) / Decimal(len(movements))).quantize(Decimal("0.001"))


def _anchor_for_observation(
    observations: tuple[PriceObservation, ...],
    *,
    observation: PriceObservation,
    window: timedelta,
) -> PriceObservation | None:
    cutoff = observation.observed_at - window
    candidate: PriceObservation | None = None
    for item in observations:
        if item.observed_at > observation.observed_at:
            break
        if item.observed_at >= cutoff:
            candidate = item
            break
    return candidate


def _return_direction(return_bps: Decimal | None) -> str | None:
    if return_bps is None:
        return None
    if return_bps > 0:
        return "up"
    if return_bps < 0:
        return "down"
    return None


def _compute_return_bps(
    history: Deque[PriceObservation],
    anchor: PriceObservation | None,
) -> Decimal | None:
    if anchor is None or len(history) < 2:
        return None
    latest = history[-1]
    if latest.observed_at == anchor.observed_at:
        return None
    if anchor.price <= 0:
        raise BiasEngineError("Anchor price must be greater than zero.")
    return ((latest.price - anchor.price) / anchor.price * BASIS_POINTS_MULTIPLIER).quantize(
        Decimal("0.001")
    )


def _window_return_bps(
    history: Deque[PriceObservation],
    *,
    window: timedelta,
) -> Decimal | None:
    return _compute_return_bps(history, _recent_anchor(history, window))


def _window_observations(
    history: Deque[PriceObservation],
    *,
    window: timedelta,
) -> tuple[PriceObservation, ...]:
    if not history:
        return ()
    latest = history[-1]
    cutoff = latest.observed_at - window
    return tuple(observation for observation in history if observation.observed_at >= cutoff)


def _window_range_bps(
    history: Deque[PriceObservation],
    *,
    window: timedelta,
) -> Decimal | None:
    observations = _window_observations(history, window=window)
    if len(observations) < 2:
        return None
    low = min(observation.price for observation in observations)
    high = max(observation.price for observation in observations)
    latest = observations[-1].price
    if latest <= 0:
        raise BiasEngineError("Latest price must be greater than zero.")
    return ((high - low) / latest * BASIS_POINTS_MULTIPLIER).quantize(Decimal("0.001"))


def _distance_to_recent_extremes_bps(
    history: Deque[PriceObservation],
    *,
    window: timedelta,
) -> tuple[Decimal | None, Decimal | None]:
    observations = _window_observations(history, window=window)
    if len(observations) < 2:
        return None, None
    latest = observations[-1].price
    if latest <= 0:
        raise BiasEngineError("Latest price must be greater than zero.")
    low = min(observation.price for observation in observations)
    high = max(observation.price for observation in observations)
    distance_to_high = ((high - latest) / latest * BASIS_POINTS_MULTIPLIER).quantize(
        Decimal("0.001")
    )
    distance_to_low = ((latest - low) / latest * BASIS_POINTS_MULTIPLIER).quantize(
        Decimal("0.001")
    )
    return distance_to_high, distance_to_low


def _absolute_return_bps(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return abs(value).quantize(Decimal("0.001"))


def _threshold_gap_bps(
    value: Decimal | None,
    *,
    threshold_bps: Decimal,
) -> Decimal | None:
    if value is None:
        return None
    return (abs(value) - threshold_bps).quantize(Decimal("0.001"))
