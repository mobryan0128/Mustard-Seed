"""Read-only contract scanning over current Kalshi market state and bias output."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Mapping

from kalshi_bot.config.settings import KalshiSettings
from kalshi_bot.contracts.contract_scorer import ContractScore, score_contract
from kalshi_bot.forecast.bias_engine import BiasSnapshot
from kalshi_bot.market.market_state_cache import MarketStateSnapshot, TickerState


TWO_DECIMAL = Decimal("2")
BASIS_POINTS_MULTIPLIER = Decimal("10000")
SECONDS_PER_MINUTE = Decimal("60")
LATE_EXPANSION_IMPULSE_RETURN_BPS = Decimal("6.000")
IMPULSE_CONFIRMATION_RETURN_BPS = Decimal("3.000")
REVERSAL_MIN_RECENT_RETURN_BPS = Decimal("15.000")
TREND_MIN_RECENT_RETURN_BPS = Decimal("15.000")
UNREALISTIC_LATE_CROSS_SECONDS = 60
UNREALISTIC_LATE_CROSS_DISTANCE_BPS = Decimal("15.000")
NEEDS_CROSS_SOFT_DISTANCE_BPS = Decimal("5.000")
NEEDS_CROSS_HARD_DISTANCE_BPS = Decimal("10.000")
NEEDS_CROSS_TIGHT_REQUIRED_BPS_PER_MINUTE = Decimal("1.000")
NEEDS_CROSS_HARD_REQUIRED_BPS_PER_MINUTE = Decimal("2.000")
SCORE_DOWNGRADE_CONFLICT_CONFIDENCE = 30
SCORE_DOWNGRADE_NEEDS_CROSS_CONFIDENCE = 40
SCORE_DOWNGRADE_SOFT_NEEDS_CROSS_CONFIDENCE = 30
SCORE_DOWNGRADE_REVERSAL_NEAR_TARGET_CONFIDENCE = 30
SCORE_BONUS_CONFIRMED_TREND_CONFIDENCE = 10
SCORE_MAX_CONFIDENCE = 90
REVERSAL_NOISE_ZONE_DISTANCE_BPS = Decimal("5.000")


class ContractScannerError(ValueError):
    """Raised when scanner configuration is missing or invalid."""


@dataclass(frozen=True)
class TargetFeasibility:
    current_spot_price: Decimal | None
    target_price: Decimal | None
    target_price_source: str | None
    distance_to_target: Decimal | None
    distance_to_target_bps: Decimal | None
    time_remaining_seconds: int | None
    required_bps_per_minute: Decimal | None
    side_currently_itm: bool | None
    side_needs_cross: bool | None
    feasibility_status: str


@dataclass(frozen=True)
class ScannedContract:
    """Normalized ranked contract candidate."""

    product_id: str
    market_ticker: str
    direction: str
    structure: str
    confidence: int
    best_bid: Decimal
    best_ask: Decimal
    midpoint: Decimal
    bias_as_of: str | None
    market_as_of: str | None
    score: ContractScore
    latest_price: Decimal | None = None
    observation_count: int | None = None
    recent_return_bps: Decimal | None = None
    lookback_return_bps: Decimal | None = None
    impulse_direction: str | None = None
    impulse_return_bps: Decimal | None = None
    impulse_detected: bool | None = None
    risk_flags: tuple[tuple[str, bool], ...] = ()
    target_price: Decimal | None = None
    target_price_source: str | None = None
    distance_to_target: Decimal | None = None
    distance_to_target_bps: Decimal | None = None
    required_bps_per_minute: Decimal | None = None
    side_currently_itm: bool | None = None
    side_needs_cross: bool | None = None
    feasibility_status: str | None = None
    reversal_confirmation_status: str | None = None
    trend_confirmation_status: str | None = None
    signal_conflict_flags: tuple[tuple[str, bool], ...] = ()
    scanner_score_confidence: int | None = None
    scanner_score_downgrade_reasons: tuple[str, ...] = ()
    scanner_score_bonus_reasons: tuple[str, ...] = ()
    contract_open_time: str | None = None
    contract_close_time: str | None = None
    contract_time_remaining_seconds: int | None = None
    end_window_allowed: bool | None = None
    end_window_reason: str | None = None


@dataclass(frozen=True)
class SkippedContract:
    """Normalized skipped contract record."""

    product_id: str
    market_ticker: str
    reason: str
    contract_close_time: str | None = None
    target_price: Decimal | None = None
    target_price_source: str | None = None
    distance_to_target_bps: Decimal | None = None
    time_remaining_seconds: int | None = None
    required_bps_per_minute: Decimal | None = None
    side_currently_itm: bool | None = None
    side_needs_cross: bool | None = None
    feasibility_status: str | None = None
    reversal_confirmation_status: str | None = None
    trend_confirmation_status: str | None = None
    signal_conflict_flags: tuple[tuple[str, bool], ...] = ()
    scanner_score_downgrade_reasons: tuple[str, ...] = ()
    scanner_score_bonus_reasons: tuple[str, ...] = ()
    contract_open_time: str | None = None
    contract_time_remaining_seconds: int | None = None
    end_window_allowed: bool | None = None
    end_window_reason: str | None = None


@dataclass(frozen=True)
class ContractScanSnapshot:
    """Ranked and skipped contract results for one scan pass."""

    ranked_contracts: tuple[ScannedContract, ...]
    skipped_contracts: tuple[SkippedContract, ...]


class ContractScanner:
    """Read-only scanner over mapped Kalshi markets already present in local state."""

    def __init__(
        self,
        *,
        product_markets: Mapping[str, tuple[str, ...]],
        market_metadata_by_ticker: Mapping[str, Mapping[str, object]] | None = None,
    ) -> None:
        normalized = {
            product_id.strip(): tuple(
                dict.fromkeys(market_ticker.strip() for market_ticker in market_tickers if market_ticker.strip())
            )
            for product_id, market_tickers in product_markets.items()
            if product_id.strip()
        }
        if not normalized:
            raise ContractScannerError("Contract scanner product mapping is required.")
        if any(not market_tickers for market_tickers in normalized.values()):
            raise ContractScannerError("Each contract scanner product must map to at least one market.")
        self._product_markets = normalized
        self._market_metadata_by_ticker = {
            market_ticker: dict(metadata)
            for market_ticker, metadata in (market_metadata_by_ticker or {}).items()
        }

    @classmethod
    def from_settings(cls, settings: KalshiSettings) -> "ContractScanner":
        if not settings.contract_scanner_product_markets:
            raise ContractScannerError("CONTRACT_SCANNER_PRODUCT_MARKETS_JSON is required.")
        return cls(product_markets=settings.contract_scanner_product_markets)

    def scan(
        self,
        *,
        bias_snapshot: BiasSnapshot,
        market_snapshot: MarketStateSnapshot,
    ) -> ContractScanSnapshot:
        ranked_contracts: list[ScannedContract] = []
        skipped_contracts: list[SkippedContract] = []

        for product_id, market_tickers in self._product_markets.items():
            bias_state = bias_snapshot.products.get(product_id)
            for market_ticker in market_tickers:
                ticker_state = market_snapshot.tickers.get(market_ticker)
                if ticker_state is None:
                    continue
                metadata = self._market_metadata_by_ticker.get(market_ticker, {})
                stale_skip_reason = _stale_ticker_skip_reason(metadata)
                if stale_skip_reason is not None:
                    skipped_contracts.append(
                        SkippedContract(
                            product_id=product_id,
                            market_ticker=market_ticker,
                            reason=stale_skip_reason,
                            contract_open_time=_optional_str_metadata(metadata, "open_time"),
                            contract_close_time=_optional_str_metadata(metadata, "close_time"),
                            time_remaining_seconds=_market_time_remaining_seconds(
                                metadata
                            ),
                            feasibility_status="time_remaining_elapsed",
                            end_window_allowed=False,
                            end_window_reason=stale_skip_reason,
                        )
                    )
                    continue
                skip_reason = _skip_reason(bias_state, ticker_state)
                if skip_reason is not None:
                    skipped_contracts.append(
                        SkippedContract(
                            product_id=product_id,
                            market_ticker=market_ticker,
                            reason=skip_reason,
                            contract_open_time=_optional_str_metadata(metadata, "open_time"),
                            contract_close_time=_optional_str_metadata(metadata, "close_time"),
                        )
                    )
                    continue

                assert bias_state is not None
                assert ticker_state.yes_bid_dollars is not None
                assert ticker_state.yes_ask_dollars is not None
                feasibility = _target_feasibility(
                    direction=bias_state.direction,
                    current_spot_price=bias_state.latest_price,
                    target_price=_optional_decimal_metadata(metadata, "target_price"),
                    target_price_source=_optional_str_metadata(metadata, "target_price_source"),
                    close_time=_optional_str_metadata(metadata, "close_time"),
                )
                signal_conflict_flags = _signal_conflict_flags(
                    direction=bias_state.direction,
                    impulse_return_bps=getattr(bias_state, "impulse_return_bps", None),
                )
                reversal_confirmation_status = _reversal_confirmation_status(
                    bias_state=bias_state,
                    signal_conflict_flags=signal_conflict_flags,
                )
                trend_confirmation_status = _trend_confirmation_status(
                    bias_state=bias_state,
                    feasibility=feasibility,
                )
                feasibility_skip_reason = _feasibility_skip_reason(
                    bias_state=bias_state,
                    feasibility=feasibility,
                    signal_conflict_flags=signal_conflict_flags,
                )
                if feasibility_skip_reason is not None:
                    skipped_contracts.append(
                        SkippedContract(
                            product_id=product_id,
                            market_ticker=market_ticker,
                            reason=feasibility_skip_reason,
                            contract_open_time=_optional_str_metadata(metadata, "open_time"),
                            contract_close_time=_optional_str_metadata(metadata, "close_time"),
                            target_price=feasibility.target_price,
                            target_price_source=feasibility.target_price_source,
                            distance_to_target_bps=feasibility.distance_to_target_bps,
                            time_remaining_seconds=feasibility.time_remaining_seconds,
                            required_bps_per_minute=feasibility.required_bps_per_minute,
                            side_currently_itm=feasibility.side_currently_itm,
                            side_needs_cross=feasibility.side_needs_cross,
                            feasibility_status=feasibility.feasibility_status,
                            reversal_confirmation_status=reversal_confirmation_status,
                            trend_confirmation_status=trend_confirmation_status,
                            signal_conflict_flags=signal_conflict_flags,
                            scanner_score_downgrade_reasons=(),
                        )
                    )
                    continue
                midpoint = ((ticker_state.yes_bid_dollars + ticker_state.yes_ask_dollars) / TWO_DECIMAL).quantize(
                    Decimal("0.001")
                )
                (
                    score_confidence,
                    score_downgrade_reasons,
                    score_bonus_reasons,
                ) = _scanner_score_confidence(
                    product_id=product_id,
                    bias_state=bias_state,
                    feasibility=feasibility,
                    reversal_confirmation_status=reversal_confirmation_status,
                    trend_confirmation_status=trend_confirmation_status,
                    signal_conflict_flags=signal_conflict_flags,
                )
                score = score_contract(
                    confidence=score_confidence,
                    best_bid=ticker_state.yes_bid_dollars,
                    best_ask=ticker_state.yes_ask_dollars,
                    yes_bid_size_fp=ticker_state.yes_bid_size_fp,
                    yes_ask_size_fp=ticker_state.yes_ask_size_fp,
                    dollar_volume=ticker_state.dollar_volume,
                )
                ranked_contracts.append(
                    ScannedContract(
                        product_id=product_id,
                        market_ticker=market_ticker,
                        direction=bias_state.direction,
                        structure=bias_state.structure,
                        confidence=bias_state.confidence,
                        best_bid=ticker_state.yes_bid_dollars,
                        best_ask=ticker_state.yes_ask_dollars,
                        midpoint=midpoint,
                        bias_as_of=bias_state.as_of,
                        market_as_of=_market_as_of(ticker_state),
                        score=score,
                        latest_price=bias_state.latest_price,
                        observation_count=bias_state.observation_count,
                        recent_return_bps=bias_state.recent_return_bps,
                        lookback_return_bps=bias_state.lookback_return_bps,
                        impulse_direction=bias_state.impulse_direction,
                        impulse_return_bps=bias_state.impulse_return_bps,
                        impulse_detected=bias_state.impulse_detected,
                        risk_flags=_risk_flags(bias_state.risk_flags),
                        target_price=feasibility.target_price,
                        target_price_source=feasibility.target_price_source,
                        distance_to_target=feasibility.distance_to_target,
                        distance_to_target_bps=feasibility.distance_to_target_bps,
                        required_bps_per_minute=feasibility.required_bps_per_minute,
                        side_currently_itm=feasibility.side_currently_itm,
                        side_needs_cross=feasibility.side_needs_cross,
                        feasibility_status=feasibility.feasibility_status,
                        reversal_confirmation_status=reversal_confirmation_status,
                        trend_confirmation_status=trend_confirmation_status,
                        signal_conflict_flags=signal_conflict_flags,
                        scanner_score_confidence=score_confidence,
                        scanner_score_downgrade_reasons=score_downgrade_reasons,
                        scanner_score_bonus_reasons=score_bonus_reasons,
                        contract_open_time=_optional_str_metadata(metadata, "open_time"),
                        contract_close_time=_optional_str_metadata(metadata, "close_time"),
                        contract_time_remaining_seconds=feasibility.time_remaining_seconds,
                    )
                )

        ranked_contracts.sort(key=lambda contract: contract.score.ranking_key() + (contract.market_ticker,))
        skipped_contracts.sort(key=lambda contract: (contract.product_id, contract.market_ticker, contract.reason))
        return ContractScanSnapshot(
            ranked_contracts=tuple(ranked_contracts),
            skipped_contracts=tuple(skipped_contracts),
        )


def _skip_reason(bias_state, ticker_state: TickerState) -> str | None:
    if bias_state is None:
        return "missing_bias_state"
    if bias_state.direction == "neutral":
        return "neutral_bias"
    if bias_state.confidence <= 0:
        return "zero_confidence"
    if _is_late_expansion_bias(bias_state):
        return "too_late_after_expansion"
    if _is_unconfirmed_impulse_bias(bias_state):
        return "impulse_unconfirmed"
    if ticker_state.yes_bid_dollars is None or ticker_state.yes_ask_dollars is None:
        return "missing_best_quote"
    return None


def _stale_ticker_skip_reason(metadata: Mapping[str, object]) -> str | None:
    elapsed_at = _market_elapsed_at(metadata)
    if elapsed_at is None:
        return None
    if elapsed_at <= datetime.now(timezone.utc):
        return "stale_ticker_blocked"
    return None


def _market_time_remaining_seconds(metadata: Mapping[str, object]) -> int | None:
    elapsed_at = _market_elapsed_at(metadata)
    if elapsed_at is None:
        return None
    return int((elapsed_at - datetime.now(timezone.utc)).total_seconds())


def _market_elapsed_at(metadata: Mapping[str, object]) -> datetime | None:
    candidates = (
        _optional_str_metadata(metadata, "close_time"),
        _optional_str_metadata(metadata, "expiration_time"),
    )
    parsed = tuple(
        parsed_at
        for value in candidates
        for parsed_at in (_try_parse_iso_datetime(value),)
        if parsed_at is not None
    )
    if not parsed:
        return None
    return min(parsed)


def _try_parse_iso_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return _parse_iso_datetime(value)
    except ValueError:
        return None


def _is_late_expansion_bias(bias_state) -> bool:  # noqa: ANN001
    impulse_return_bps = getattr(bias_state, "impulse_return_bps", None)
    if impulse_return_bps is None:
        return False
    return (
        bias_state.direction in {"up", "down"}
        and bias_state.structure == "trend"
        and bias_state.confidence <= 40
        and getattr(bias_state, "impulse_detected", False)
        and getattr(bias_state, "impulse_direction", None) == bias_state.direction
        and abs(Decimal(str(impulse_return_bps))) >= LATE_EXPANSION_IMPULSE_RETURN_BPS
    )


def _is_unconfirmed_impulse_bias(bias_state) -> bool:  # noqa: ANN001
    if not (
        bias_state.direction in {"up", "down"}
        and bias_state.structure == "trend"
        and bias_state.confidence == 40
        and getattr(bias_state, "impulse_detected", False)
        and getattr(bias_state, "impulse_direction", None) == bias_state.direction
    ):
        return False

    recent_return_bps = getattr(bias_state, "recent_return_bps", None)
    lookback_return_bps = getattr(bias_state, "lookback_return_bps", None)
    if recent_return_bps is None or lookback_return_bps is None:
        return True

    recent_return = Decimal(str(recent_return_bps))
    lookback_return = Decimal(str(lookback_return_bps))
    if abs(recent_return) < IMPULSE_CONFIRMATION_RETURN_BPS:
        return True
    if abs(lookback_return) < IMPULSE_CONFIRMATION_RETURN_BPS:
        return True
    if bias_state.direction == "up":
        return recent_return <= 0 or lookback_return <= 0
    return recent_return >= 0 or lookback_return >= 0


def _market_as_of(ticker_state: TickerState) -> str | None:
    if ticker_state.exchange_time:
        return ticker_state.exchange_time
    if ticker_state.exchange_ts is not None:
        return str(ticker_state.exchange_ts)
    return None


def _risk_flags(risk_flags) -> tuple[tuple[str, bool], ...]:  # noqa: ANN001
    return (
        ("insufficient_history", bool(risk_flags.insufficient_history)),
        ("stale_data", bool(risk_flags.stale_data)),
        ("time_sync_failed", bool(risk_flags.time_sync_failed)),
    )


def _target_feasibility(
    *,
    direction: str,
    current_spot_price: Decimal | None,
    target_price: Decimal | None,
    target_price_source: str | None,
    close_time: str | None,
) -> TargetFeasibility:
    time_remaining_seconds = _time_remaining_seconds(close_time)
    if current_spot_price is None:
        return TargetFeasibility(
            current_spot_price=None,
            target_price=target_price,
            target_price_source=target_price_source,
            distance_to_target=None,
            distance_to_target_bps=None,
            time_remaining_seconds=time_remaining_seconds,
            required_bps_per_minute=None,
            side_currently_itm=None,
            side_needs_cross=None,
            feasibility_status="current_spot_missing",
        )
    if target_price is None:
        return TargetFeasibility(
            current_spot_price=current_spot_price,
            target_price=None,
            target_price_source=target_price_source,
            distance_to_target=None,
            distance_to_target_bps=None,
            time_remaining_seconds=time_remaining_seconds,
            required_bps_per_minute=None,
            side_currently_itm=None,
            side_needs_cross=None,
            feasibility_status="target_price_missing",
        )
    if current_spot_price <= Decimal("0"):
        return TargetFeasibility(
            current_spot_price=current_spot_price,
            target_price=target_price,
            target_price_source=target_price_source,
            distance_to_target=None,
            distance_to_target_bps=None,
            time_remaining_seconds=time_remaining_seconds,
            required_bps_per_minute=None,
            side_currently_itm=None,
            side_needs_cross=None,
            feasibility_status="current_spot_invalid",
        )

    distance_to_target = _directional_distance_to_target(
        direction=direction,
        current_spot_price=current_spot_price,
        target_price=target_price,
    )
    if distance_to_target is None:
        return TargetFeasibility(
            current_spot_price=current_spot_price,
            target_price=target_price,
            target_price_source=target_price_source,
            distance_to_target=None,
            distance_to_target_bps=None,
            time_remaining_seconds=time_remaining_seconds,
            required_bps_per_minute=None,
            side_currently_itm=None,
            side_needs_cross=None,
            feasibility_status="invalid_direction",
        )

    distance_to_target_bps = (
        distance_to_target / current_spot_price * BASIS_POINTS_MULTIPLIER
    ).quantize(Decimal("0.001"))
    side_needs_cross = distance_to_target > Decimal("0")
    required_bps_per_minute = _required_bps_per_minute(
        distance_to_target_bps=distance_to_target_bps,
        time_remaining_seconds=time_remaining_seconds,
    )
    if time_remaining_seconds is None:
        feasibility_status = "time_remaining_missing"
    elif time_remaining_seconds <= 0:
        feasibility_status = "time_remaining_elapsed"
    elif (
        side_needs_cross
        and time_remaining_seconds <= UNREALISTIC_LATE_CROSS_SECONDS
        and distance_to_target_bps >= UNREALISTIC_LATE_CROSS_DISTANCE_BPS
    ):
        feasibility_status = "unrealistic_late_cross"
    elif side_needs_cross:
        feasibility_status = "needs_cross"
    else:
        feasibility_status = "currently_itm"

    return TargetFeasibility(
        current_spot_price=current_spot_price,
        target_price=target_price,
        target_price_source=target_price_source,
        distance_to_target=distance_to_target,
        distance_to_target_bps=distance_to_target_bps,
        time_remaining_seconds=time_remaining_seconds,
        required_bps_per_minute=required_bps_per_minute,
        side_currently_itm=not side_needs_cross,
        side_needs_cross=side_needs_cross,
        feasibility_status=feasibility_status,
    )


def _directional_distance_to_target(
    *,
    direction: str,
    current_spot_price: Decimal,
    target_price: Decimal,
) -> Decimal | None:
    if direction == "up":
        return target_price - current_spot_price
    if direction == "down":
        return current_spot_price - target_price
    return None


def _required_bps_per_minute(
    *,
    distance_to_target_bps: Decimal,
    time_remaining_seconds: int | None,
) -> Decimal | None:
    if time_remaining_seconds is None or time_remaining_seconds <= 0:
        return None
    remaining_minutes = Decimal(time_remaining_seconds) / SECONDS_PER_MINUTE
    if distance_to_target_bps <= Decimal("0"):
        return Decimal("0.000")
    return (distance_to_target_bps / remaining_minutes).quantize(Decimal("0.001"))


def _time_remaining_seconds(close_time: str | None) -> int | None:
    if close_time is None:
        return None
    try:
        close_at = _parse_iso_datetime(close_time)
    except ValueError:
        return None
    return int((close_at - datetime.now(timezone.utc)).total_seconds())


def _parse_iso_datetime(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _signal_conflict_flags(
    *,
    direction: str,
    impulse_return_bps: Decimal | None,
) -> tuple[tuple[str, bool], ...]:
    impulse_conflict = False
    if impulse_return_bps is not None and abs(Decimal(str(impulse_return_bps))) >= IMPULSE_CONFIRMATION_RETURN_BPS:
        impulse_sign = _sign(Decimal(str(impulse_return_bps)))
        direction_sign = _direction_sign(direction)
        impulse_conflict = direction_sign != 0 and impulse_sign != 0 and impulse_sign != direction_sign
    return (("impulse_direction_conflict", impulse_conflict),)


def _reversal_confirmation_status(
    *,
    bias_state,
    signal_conflict_flags: tuple[tuple[str, bool], ...],
) -> str:
    if bias_state.structure != "reversal":
        return "not_reversal"
    recent_return_bps = getattr(bias_state, "recent_return_bps", None)
    if recent_return_bps is None:
        return "recent_return_missing"
    recent_return = Decimal(str(recent_return_bps))
    if _sign(recent_return) != _direction_sign(bias_state.direction):
        return "recent_direction_mismatch"
    if abs(recent_return) < REVERSAL_MIN_RECENT_RETURN_BPS:
        return "weak_recent_return"
    if dict(signal_conflict_flags).get("impulse_direction_conflict"):
        return "impulse_direction_conflict"
    return "confirmed"


def _trend_confirmation_status(
    *,
    bias_state,
    feasibility: TargetFeasibility,
) -> str:
    if bias_state.structure != "trend":
        return "not_trend"
    recent_return_bps = getattr(bias_state, "recent_return_bps", None)
    if recent_return_bps is None:
        return "recent_return_missing"
    lookback_return_bps = getattr(bias_state, "lookback_return_bps", None)
    if lookback_return_bps is None:
        return "lookback_return_missing"
    recent_return = Decimal(str(recent_return_bps))
    lookback_return = Decimal(str(lookback_return_bps))
    direction_sign = _direction_sign(bias_state.direction)
    if _sign(recent_return) != direction_sign:
        return "recent_direction_mismatch"
    if _sign(lookback_return) != direction_sign:
        return "lookback_direction_mismatch"
    if abs(recent_return) < TREND_MIN_RECENT_RETURN_BPS:
        return "weak_recent_return"
    if (
        feasibility.side_needs_cross
        and feasibility.distance_to_target_bps is not None
        and feasibility.distance_to_target_bps > NEEDS_CROSS_SOFT_DISTANCE_BPS
    ):
        return "large_cross_required"
    return "confirmed"


def _feasibility_skip_reason(
    *,
    bias_state,
    feasibility: TargetFeasibility,
    signal_conflict_flags: tuple[tuple[str, bool], ...],
) -> str | None:
    if not feasibility.side_needs_cross:
        return None
    if feasibility.feasibility_status == "unrealistic_late_cross":
        if (
            bias_state.structure == "reversal"
            and dict(signal_conflict_flags).get("impulse_direction_conflict")
        ):
            return "signal_conflict_unrealistic_reversal"
        return "target_feasibility_unrealistic_late_cross"
    if (
        feasibility.distance_to_target_bps is not None
        and feasibility.distance_to_target_bps > NEEDS_CROSS_HARD_DISTANCE_BPS
    ):
        return "target_feasibility_distance_too_far"
    if (
        feasibility.required_bps_per_minute is not None
        and feasibility.required_bps_per_minute
        > NEEDS_CROSS_HARD_REQUIRED_BPS_PER_MINUTE
    ):
        return "target_feasibility_required_move_too_fast"
    if (
        feasibility.distance_to_target_bps is not None
        and feasibility.distance_to_target_bps > Decimal("0")
        and feasibility.required_bps_per_minute is not None
        and feasibility.required_bps_per_minute
        > NEEDS_CROSS_TIGHT_REQUIRED_BPS_PER_MINUTE
    ):
        return "target_feasibility_required_move_too_fast_tight"
    return None


def _scanner_score_confidence(
    *,
    product_id: str,
    bias_state,
    feasibility: TargetFeasibility,
    reversal_confirmation_status: str,
    trend_confirmation_status: str,
    signal_conflict_flags: tuple[tuple[str, bool], ...],
) -> tuple[int, tuple[str, ...], tuple[str, ...]]:
    confidence = int(bias_state.confidence)
    downgrade_reasons: list[str] = []
    bonus_reasons: list[str] = []
    if dict(signal_conflict_flags).get("impulse_direction_conflict"):
        confidence = min(confidence, SCORE_DOWNGRADE_NEEDS_CROSS_CONFIDENCE)
        downgrade_reasons.append("impulse_direction_conflict")
    if (
        feasibility.side_needs_cross
        and feasibility.distance_to_target_bps is not None
        and feasibility.distance_to_target_bps > NEEDS_CROSS_SOFT_DISTANCE_BPS
    ):
        confidence = min(confidence, SCORE_DOWNGRADE_SOFT_NEEDS_CROSS_CONFIDENCE)
        downgrade_reasons.append("needs_cross_distance_over_soft_limit")
    elif feasibility.side_needs_cross:
        confidence = min(confidence, SCORE_DOWNGRADE_NEEDS_CROSS_CONFIDENCE)
        downgrade_reasons.append("needs_cross")
    if product_id == "HYPE-USD" and feasibility.side_needs_cross:
        confidence = min(confidence, SCORE_DOWNGRADE_SOFT_NEEDS_CROSS_CONFIDENCE)
        downgrade_reasons.append("hype_needs_cross_caution")
    if bias_state.structure == "reversal" and feasibility.feasibility_status == "target_price_missing":
        confidence = min(confidence, SCORE_DOWNGRADE_NEEDS_CROSS_CONFIDENCE)
        downgrade_reasons.append("reversal_target_price_missing")
    if (
        bias_state.structure == "reversal"
        and feasibility.distance_to_target_bps is not None
        and abs(Decimal(str(feasibility.distance_to_target_bps)))
        <= REVERSAL_NOISE_ZONE_DISTANCE_BPS
    ):
        confidence = min(confidence, SCORE_DOWNGRADE_REVERSAL_NEAR_TARGET_CONFIDENCE)
        if feasibility.side_currently_itm:
            downgrade_reasons.append("reversal_fresh_cross_near_target")
        else:
            downgrade_reasons.append("reversal_noise_zone_near_target")
    if reversal_confirmation_status in {
        "recent_return_missing",
        "recent_direction_mismatch",
        "weak_recent_return",
        "impulse_direction_conflict",
    }:
        confidence = min(confidence, SCORE_DOWNGRADE_CONFLICT_CONFIDENCE)
        downgrade_reasons.append(f"reversal_{reversal_confirmation_status}")
    if trend_confirmation_status in {
        "recent_return_missing",
        "lookback_return_missing",
        "recent_direction_mismatch",
        "lookback_direction_mismatch",
        "weak_recent_return",
        "large_cross_required",
    }:
        confidence = min(confidence, SCORE_DOWNGRADE_CONFLICT_CONFIDENCE)
        downgrade_reasons.append(f"trend_{trend_confirmation_status}")
    if trend_confirmation_status == "confirmed" and not downgrade_reasons:
        confidence = min(
            SCORE_MAX_CONFIDENCE,
            confidence + SCORE_BONUS_CONFIRMED_TREND_CONFIDENCE,
        )
        bonus_reasons.append("confirmed_trend")
    return (
        confidence,
        tuple(dict.fromkeys(downgrade_reasons)),
        tuple(dict.fromkeys(bonus_reasons)),
    )


def _direction_sign(direction: str) -> int:
    if direction == "up":
        return 1
    if direction == "down":
        return -1
    return 0


def _sign(value: Decimal) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _optional_str_metadata(
    metadata: Mapping[str, object],
    key: str,
) -> str | None:
    value = metadata.get(key)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _optional_decimal_metadata(
    metadata: Mapping[str, object],
    key: str,
) -> Decimal | None:
    value = metadata.get(key)
    if value is None:
        return None
    return Decimal(str(value))
