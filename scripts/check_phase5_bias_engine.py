"""Validate Phase 5 bias engine behavior with offline fixtures."""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi_bot.config.settings import SettingsError, load_settings  # noqa: E402
from kalshi_bot.forecast.bias_engine import BiasEngine, BiasEngineError  # noqa: E402
from kalshi_bot.timing.time_sync_checker import TimeSyncObservation  # noqa: E402


@dataclass(frozen=True)
class FixturePriceState:
    product_id: str
    price: Decimal | None
    source_timestamp: str | None


@dataclass(frozen=True)
class FixtureFeedSnapshot:
    products: dict[str, FixturePriceState]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate bias engine state outputs.")
    parser.add_argument(
        "--env-file",
        default=".env.example",
        help="Environment file used to load Phase 5 defaults. Defaults to .env.example.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Optionally stream live crypto feed updates into the bias engine.",
    )
    parser.add_argument(
        "--message-limit",
        type=int,
        default=None,
        help="Maximum live crypto feed messages to process when --live is set.",
    )
    args = parser.parse_args()

    try:
        settings = load_settings(args.env_file)
        failures = run_offline_fixtures(settings)
        if failures:
            for failure in failures:
                print(f"FAIL {failure}", file=sys.stderr)
            return 1

        print("Phase 5 bias engine offline fixtures succeeded.")
        if args.live:
            return asyncio.run(run_live_smoke(settings, args.message_limit))
        return 0
    except (SettingsError, BiasEngineError) as exc:
        print(f"Phase 5 bias engine check failed: {exc}", file=sys.stderr)
        return 1


def run_offline_fixtures(settings) -> list[str]:
    now = datetime.now(timezone.utc)
    failures: list[str] = []

    failures.extend(
        _run_case(
            settings,
            case_name="trend_up",
            observations=_series(now, count=25, step_seconds=5, prices=_linear_prices("100", "124")),
            expected_direction="up",
            expected_structure="trend",
            expected_confidence=80,
        )
    )
    failures.extend(
        _run_case(
            settings,
            case_name="trend_down",
            observations=_series(now, count=25, step_seconds=5, prices=_linear_prices("124", "100")),
            expected_direction="down",
            expected_structure="trend",
            expected_confidence=80,
        )
    )
    failures.extend(
        _run_case(
            settings,
            case_name="reversal",
            observations=_series(
                now,
                count=25,
                step_seconds=5,
                prices=(
                    _linear_prices("100", "80", count=13)
                    + _linear_prices("80", "90", count=12, include_start=False)
                ),
            ),
            expected_direction="up",
            expected_structure="reversal",
            expected_confidence=80,
        )
    )
    failures.extend(
        _run_case(
            settings,
            case_name="chop",
            observations=_series(
                now,
                count=25,
                step_seconds=5,
                prices=tuple(Decimal("100.000") + Decimal("0.001") * Decimal(index % 3) for index in range(25)),
            ),
            expected_direction="neutral",
            expected_structure="chop",
            expected_confidence=10,
        )
    )
    failures.extend(
        _run_case(
            settings,
            case_name="exhaustion",
            observations=_series(
                now,
                count=25,
                step_seconds=5,
                prices=(
                    _linear_prices("100", "120", count=13)
                    + _linear_prices("120", "120.02", count=12, include_start=False)
                ),
            ),
            expected_direction="neutral",
            expected_structure="exhaustion",
            expected_confidence=30,
        )
    )
    failures.extend(
        _run_case(
            settings,
            case_name="stale_data",
            observations=_series(
                now - timedelta(seconds=settings.bias_stale_data_seconds + 60),
                count=25,
                step_seconds=5,
                prices=_linear_prices("100", "124"),
            ),
            expected_direction="neutral",
            expected_structure="chop",
            expected_confidence=0,
            expect_stale=True,
        )
    )
    failures.extend(
        _run_case(
            settings,
            case_name="time_sync_failure",
            observations=_series(now, count=25, step_seconds=5, prices=_linear_prices("100", "124")),
            expected_direction="neutral",
            expected_structure="chop",
            expected_confidence=0,
            time_sync_observation=TimeSyncObservation(
                source="BTC-USD",
                source_timestamp=now.isoformat(),
                local_timestamp=now.isoformat(),
                absolute_drift_ms=Decimal("5000"),
                within_threshold=False,
            ),
        )
    )
    failures.extend(_run_pruning_case(settings, now))
    failures.extend(_run_weak_impulse_below_absolute_threshold_case(settings, now))
    failures.extend(_run_absolute_threshold_impulse_case(settings, now, direction="up"))
    failures.extend(_run_absolute_threshold_impulse_case(settings, now, direction="down"))
    failures.extend(_run_impulse_detection_case(settings, now))
    failures.extend(_run_slow_move_no_impulse_case(settings, now))
    failures.extend(_run_impulse_override_case(settings, now, direction="up"))
    failures.extend(_run_impulse_override_case(settings, now, direction="down"))
    failures.extend(_run_stale_impulse_no_override_case(settings, now))
    failures.extend(_run_insufficient_history_impulse_no_override_case(settings, now))
    failures.extend(_run_exhaustion_impulse_no_override_case(settings, now))
    return failures


def _run_case(
    settings,
    *,
    case_name: str,
    observations: tuple[tuple[datetime, Decimal], ...],
    expected_direction: str,
    expected_structure: str,
    expected_confidence: int,
    expect_stale: bool = False,
    time_sync_observation: TimeSyncObservation | None = None,
) -> list[str]:
    engine = BiasEngine.from_settings(settings)
    product_id = settings.bias_products[0]
    sync_map = {product_id: time_sync_observation} if time_sync_observation is not None else None
    snapshot = None
    for observed_at, price in observations:
        snapshot = engine.ingest(
            FixtureFeedSnapshot(
                products={
                    product_id: FixturePriceState(
                        product_id=product_id,
                        price=price,
                        source_timestamp=observed_at.isoformat(),
                    )
                }
            ),
            time_sync_observations=sync_map,
        )

    assert snapshot is not None
    state = snapshot.products[product_id]
    failures: list[str] = []
    if set(snapshot.products) != set(settings.bias_products):
        failures.append(f"{case_name}: snapshot products did not match configured bias products")
    if state.direction != expected_direction:
        failures.append(f"{case_name}: direction={state.direction} expected={expected_direction}")
    if state.structure != expected_structure:
        failures.append(f"{case_name}: structure={state.structure} expected={expected_structure}")
    if state.confidence != expected_confidence:
        failures.append(f"{case_name}: confidence={state.confidence} expected={expected_confidence}")
    if state.latest_price is None or not isinstance(state.latest_price, Decimal):
        failures.append(f"{case_name}: latest_price missing or not Decimal")
    if state.observation_count < min(settings.bias_min_samples, len(observations)):
        failures.append(f"{case_name}: observation_count={state.observation_count} too small")
    if expect_stale and not state.risk_flags.stale_data:
        failures.append(f"{case_name}: stale_data flag was not set")
    if time_sync_observation is not None and not state.risk_flags.time_sync_failed:
        failures.append(f"{case_name}: time_sync_failed flag was not set")
    if state.confidence == 0 and state.direction != "neutral":
        failures.append(f"{case_name}: zero confidence must force neutral direction")
    return failures


def _run_pruning_case(settings, now: datetime) -> list[str]:
    engine = BiasEngine.from_settings(settings)
    product_id = settings.bias_products[0]
    start = now - timedelta(seconds=settings.bias_lookback_seconds + 600)
    observations = _series(
        start,
        count=40,
        step_seconds=60,
        prices=_linear_prices("100", "140", count=40),
    )
    snapshot = None
    for observed_at, price in observations:
        snapshot = engine.ingest(
            FixtureFeedSnapshot(
                products={
                    product_id: FixturePriceState(
                        product_id=product_id,
                        price=price,
                        source_timestamp=observed_at.isoformat(),
                    )
                }
            )
        )

    assert snapshot is not None
    state = snapshot.products[product_id]
    failures: list[str] = []
    if state.observation_count >= len(observations):
        failures.append("pruning: history was not pruned to the lookback window")
    if state.lookback_return_bps is None or state.recent_return_bps is None:
        failures.append("pruning: expected returns were not computed after pruning")
    return failures


def _run_weak_impulse_below_absolute_threshold_case(settings, now: datetime) -> list[str]:
    engine = BiasEngine.from_settings(settings)
    product_id = settings.bias_products[0]
    prices = (Decimal("100"),) * 20 + (Decimal("99.96"),) + (Decimal("100"),) * 4
    snapshot = _ingest_series(
        engine=engine,
        product_id=product_id,
        observations=_series(now, count=25, step_seconds=5, prices=prices),
    )

    state = snapshot.products[product_id]
    failures: list[str] = []
    if state.impulse_detected:
        failures.append("weak impulse: sub-threshold move was detected")
    if state.impulse_direction is not None:
        failures.append(
            f"weak impulse: direction={state.impulse_direction} expected=None"
        )
    if state.direction != "neutral" or state.structure != "chop":
        failures.append(
            "weak impulse: classification="
            f"{state.direction}/{state.structure} expected neutral/chop"
        )
    return failures


def _run_absolute_threshold_impulse_case(
    settings,
    now: datetime,
    *,
    direction: str,
) -> list[str]:
    engine = BiasEngine.from_settings(settings)
    product_id = settings.bias_products[0]
    impulse_anchor = Decimal("99.84") if direction == "up" else Decimal("100.16")
    prices = (Decimal("100"),) * 20 + (impulse_anchor,) + (Decimal("100"),) * 4
    snapshot = _ingest_series(
        engine=engine,
        product_id=product_id,
        observations=_series(now, count=25, step_seconds=5, prices=prices),
    )

    state = snapshot.products[product_id]
    failures: list[str] = []
    if not state.impulse_detected:
        failures.append(f"threshold impulse {direction}: impulse was not detected")
    if state.impulse_direction != direction:
        failures.append(
            f"threshold impulse {direction}: direction={state.impulse_direction}"
        )
    if direction == "up" and (
        state.impulse_return_bps is None or state.impulse_return_bps <= 0
    ):
        failures.append(
            f"threshold impulse up: return_bps={state.impulse_return_bps}"
        )
    if direction == "down" and (
        state.impulse_return_bps is None or state.impulse_return_bps >= 0
    ):
        failures.append(
            f"threshold impulse down: return_bps={state.impulse_return_bps}"
        )
    if state.confidence != 30:
        failures.append(
            f"threshold impulse {direction}: confidence={state.confidence} expected=30"
        )
    return failures


def _run_impulse_detection_case(settings, now: datetime) -> list[str]:
    engine = BiasEngine.from_settings(settings)
    product_id = settings.bias_products[0]
    prices = (Decimal("100"),) * 21 + (Decimal("102"),) * 4
    snapshot = None
    for observed_at, price in _series(now, count=25, step_seconds=5, prices=prices):
        snapshot = engine.ingest(
            FixtureFeedSnapshot(
                products={
                    product_id: FixturePriceState(
                        product_id=product_id,
                        price=price,
                        source_timestamp=observed_at.isoformat(),
                    )
                }
            )
        )

    assert snapshot is not None
    state = snapshot.products[product_id]
    failures: list[str] = []
    if not state.impulse_detected:
        failures.append("impulse: fast move was not detected")
    if state.impulse_direction != "up":
        failures.append(f"impulse: direction={state.impulse_direction} expected=up")
    if state.impulse_return_bps is None or state.impulse_return_bps <= 0:
        failures.append(f"impulse: return_bps={state.impulse_return_bps} expected positive")
    return failures


def _run_slow_move_no_impulse_case(settings, now: datetime) -> list[str]:
    engine = BiasEngine.from_settings(settings)
    product_id = settings.bias_products[0]
    snapshot = None
    for observed_at, price in _series(
        now,
        count=25,
        step_seconds=5,
        prices=_linear_prices("100", "102"),
    ):
        snapshot = engine.ingest(
            FixtureFeedSnapshot(
                products={
                    product_id: FixturePriceState(
                        product_id=product_id,
                        price=price,
                        source_timestamp=observed_at.isoformat(),
                    )
                }
            )
        )

    assert snapshot is not None
    state = snapshot.products[product_id]
    failures: list[str] = []
    if state.impulse_detected:
        failures.append("slow impulse: slow move was incorrectly detected")
    if state.impulse_direction is not None:
        failures.append(f"slow impulse: direction={state.impulse_direction} expected=None")
    if state.impulse_return_bps is None:
        failures.append("slow impulse: expected diagnostic return_bps")
    return failures


def _run_impulse_override_case(settings, now: datetime, *, direction: str) -> list[str]:
    engine = BiasEngine.from_settings(settings)
    product_id = settings.bias_products[0]
    prices = _neutral_chop_impulse_prices(direction=direction)
    snapshot = _ingest_series(
        engine=engine,
        product_id=product_id,
        observations=_series(now, count=25, step_seconds=5, prices=prices),
    )

    state = snapshot.products[product_id]
    failures: list[str] = []
    if not state.impulse_detected:
        failures.append(f"impulse override {direction}: impulse was not detected")
    if state.direction != direction:
        failures.append(
            f"impulse override {direction}: direction={state.direction} expected={direction}"
        )
    if state.structure != "trend":
        failures.append(
            f"impulse override {direction}: structure={state.structure} expected=trend"
        )
    if state.confidence != 40:
        failures.append(
            f"impulse override {direction}: confidence={state.confidence} expected=40"
        )
    return failures


def _run_stale_impulse_no_override_case(settings, now: datetime) -> list[str]:
    engine = BiasEngine.from_settings(settings)
    product_id = settings.bias_products[0]
    stale_now = now - timedelta(seconds=settings.bias_stale_data_seconds + 60)
    snapshot = _ingest_series(
        engine=engine,
        product_id=product_id,
        observations=_series(
            stale_now,
            count=25,
            step_seconds=5,
            prices=_neutral_chop_impulse_prices(direction="down"),
        ),
    )

    state = snapshot.products[product_id]
    failures: list[str] = []
    if not state.risk_flags.stale_data:
        failures.append("stale impulse: stale_data flag was not set")
    if state.direction != "neutral" or state.structure != "chop" or state.confidence != 0:
        failures.append(
            "stale impulse: classification="
            f"{state.direction}/{state.structure}/{state.confidence} expected neutral/chop/0"
        )
    return failures


def _run_insufficient_history_impulse_no_override_case(
    settings,
    now: datetime,
) -> list[str]:
    engine = BiasEngine.from_settings(settings)
    product_id = settings.bias_products[0]
    prices = (Decimal("100"),) * 5 + (Decimal("102"),) * 4
    snapshot = _ingest_series(
        engine=engine,
        product_id=product_id,
        observations=_series(now, count=9, step_seconds=5, prices=prices),
    )

    state = snapshot.products[product_id]
    failures: list[str] = []
    if not state.risk_flags.insufficient_history:
        failures.append("insufficient impulse: insufficient_history flag was not set")
    if state.direction != "neutral" or state.structure != "chop" or state.confidence != 0:
        failures.append(
            "insufficient impulse: classification="
            f"{state.direction}/{state.structure}/{state.confidence} expected neutral/chop/0"
        )
    return failures


def _run_exhaustion_impulse_no_override_case(settings, now: datetime) -> list[str]:
    engine = BiasEngine.from_settings(settings)
    product_id = settings.bias_products[0]
    prices = (
        (Decimal("98"),) * 12
        + (Decimal("100"),) * 8
        + (Decimal("98"),)
        + (Decimal("100"),) * 4
    )
    snapshot = _ingest_series(
        engine=engine,
        product_id=product_id,
        observations=_series(now, count=25, step_seconds=5, prices=prices),
    )

    state = snapshot.products[product_id]
    failures: list[str] = []
    if state.structure != "exhaustion":
        failures.append(f"exhaustion impulse: structure={state.structure} expected=exhaustion")
    if state.direction != "neutral":
        failures.append(f"exhaustion impulse: direction={state.direction} expected=neutral")
    if state.confidence != 30:
        failures.append(f"exhaustion impulse: confidence={state.confidence} expected=30")
    return failures


async def run_live_smoke(settings, message_limit: int | None) -> int:
    try:
        from kalshi_bot.clients.crypto_feed_client import CryptoFeedClient, CryptoFeedClientError
    except ImportError as exc:
        print(f"Phase 5 live smoke unavailable: {exc}", file=sys.stderr)
        return 1

    engine = BiasEngine.from_settings(settings)
    try:
        client = CryptoFeedClient.from_settings(settings)
        result = await client.run(message_limit=message_limit or settings.crypto_feed_message_limit)
    except CryptoFeedClientError as exc:
        print(f"Phase 5 live smoke failed: {exc}", file=sys.stderr)
        return 1

    snapshot = engine.ingest(client.snapshot())
    print("Phase 5 live smoke succeeded.")
    print(f"messages_received={result.messages_received}")
    print(f"products_classified={len(snapshot.products)}")
    for product_id in sorted(snapshot.products):
        state = snapshot.products[product_id]
        print(
            f"{product_id} direction={state.direction} "
            f"structure={state.structure} confidence={state.confidence}"
        )
    return 0


def _series(
    end_time: datetime,
    *,
    count: int,
    step_seconds: int,
    prices: tuple[Decimal, ...],
) -> tuple[tuple[datetime, Decimal], ...]:
    if len(prices) != count:
        raise ValueError("prices length must match count")
    start_time = end_time - timedelta(seconds=(count - 1) * step_seconds)
    return tuple(
        (start_time + timedelta(seconds=index * step_seconds), prices[index])
        for index in range(count)
    )


def _ingest_series(
    *,
    engine: BiasEngine,
    product_id: str,
    observations: tuple[tuple[datetime, Decimal], ...],
):
    snapshot = None
    for observed_at, price in observations:
        snapshot = engine.ingest(
            FixtureFeedSnapshot(
                products={
                    product_id: FixturePriceState(
                        product_id=product_id,
                        price=price,
                        source_timestamp=observed_at.isoformat(),
                    )
                }
            )
        )
    assert snapshot is not None
    return snapshot


def _neutral_chop_impulse_prices(*, direction: str) -> tuple[Decimal, ...]:
    impulse_anchor = Decimal("98") if direction == "up" else Decimal("102")
    return (Decimal("100"),) * 20 + (impulse_anchor,) + (Decimal("100"),) * 4


def _linear_prices(
    start: str,
    end: str,
    *,
    count: int = 25,
    include_start: bool = True,
) -> tuple[Decimal, ...]:
    start_value = Decimal(start)
    end_value = Decimal(end)
    if count <= 0:
        return ()
    if count == 1:
        return (end_value,)
    step = (end_value - start_value) / Decimal(count - 1 if include_start else count)
    values = tuple(start_value + step * Decimal(index) for index in range(count))
    if include_start:
        return values
    return tuple(start_value + step * Decimal(index + 1) for index in range(count))


if __name__ == "__main__":
    raise SystemExit(main())
