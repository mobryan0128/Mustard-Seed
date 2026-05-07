"""Validate default-off, rate-limited latency diagnostics locally."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi_bot.market.market_state_cache import MarketStateCache  # noqa: E402
from kalshi_bot.observability.latency_diagnostics import LatencyDiagnostics  # noqa: E402
from kalshi_bot.observability.logger import StructuredLogger  # noqa: E402
from kalshi_bot.observability.replay_engine import ReplayEngine  # noqa: E402


def main() -> int:
    failures: list[str] = []
    with TemporaryDirectory() as directory:
        root = Path(directory)
        logger = StructuredLogger(log_directory=root / "logs", enabled=True)
        replay_engine = ReplayEngine(replay_directory=root / "replay", enabled=True)
        clock = _Clock()
        diagnostics = LatencyDiagnostics(
            enabled=True,
            sample_interval_ms=1000,
            min_spot_move_bps=Decimal("5"),
            max_depth_levels=1,
            logger=logger,
            replay_engine=replay_engine,
            monotonic=clock.now,
        )

        base_time = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)
        diagnostics.record_spot_update(
            product_id="BTC-USD",
            price=Decimal("100"),
            best_bid=Decimal("99.9"),
            best_ask=Decimal("100.1"),
            best_bid_quantity=Decimal("1.5"),
            best_ask_quantity=Decimal("2.5"),
            source_timestamp="2026-05-07T12:00:00+00:00",
            sequence_num=1,
            local_receive_timestamp=base_time,
        )
        clock.value = 0.5
        diagnostics.record_spot_update(
            product_id="BTC-USD",
            price=Decimal("100.1"),
            best_bid=Decimal("100"),
            best_ask=Decimal("100.2"),
            best_bid_quantity=Decimal("1"),
            best_ask_quantity=Decimal("2"),
            source_timestamp="2026-05-07T12:00:00.500000+00:00",
            sequence_num=2,
            local_receive_timestamp=base_time + timedelta(milliseconds=500),
        )
        clock.value = 1.1
        diagnostics.record_spot_update(
            product_id="BTC-USD",
            price=Decimal("101"),
            best_bid=Decimal("100.9"),
            best_ask=Decimal("101.1"),
            best_bid_quantity=Decimal("1"),
            best_ask_quantity=Decimal("2"),
            source_timestamp="2026-05-07T12:00:01.100000+00:00",
            sequence_num=3,
            local_receive_timestamp=base_time + timedelta(milliseconds=1100),
        )

        cache = MarketStateCache()
        cache.replace_orderbook(
            market_ticker="KXBTC15M-TEST",
            market_id="market-1",
            yes_levels=(("0.44", "100"), ("0.43", "80")),
            no_levels=(("0.52", "70"), ("0.51", "60")),
            sid=12,
            seq=7,
        )
        diagnostics.record_kalshi_market_update(
            message_type="orderbook_snapshot",
            market_ticker="KXBTC15M-TEST",
            market_id="market-1",
            sid=12,
            seq=7,
            local_receive_timestamp=base_time,
            ticker_state=cache.ticker("KXBTC15M-TEST"),
            orderbook=cache.orderbook("KXBTC15M-TEST"),
        )

        disabled_logger = StructuredLogger(log_directory=root / "disabled", enabled=True)
        disabled = LatencyDiagnostics(
            enabled=False,
            sample_interval_ms=1000,
            min_spot_move_bps=Decimal("5"),
            max_depth_levels=1,
            logger=disabled_logger,
            monotonic=clock.now,
        )
        disabled.record_spot_update(
            product_id="ETH-USD",
            price=Decimal("200"),
            best_bid=None,
            best_ask=None,
            best_bid_quantity=None,
            best_ask_quantity=None,
            source_timestamp=None,
            sequence_num=None,
            local_receive_timestamp=base_time,
        )

        records = _read_jsonl(logger.path)
        replay_records = _read_jsonl(replay_engine.path)
        spot_records = [
            item for item in records if item["event_type"] == "spot_update_received"
        ]
        kalshi_records = [
            item
            for item in records
            if item["event_type"] == "kalshi_market_update_received"
        ]

        if len(spot_records) != 2:
            failures.append(f"spot diagnostics count={len(spot_records)} expected=2")
        elif spot_records[-1]["payload"].get("spot_move_bps_1s") != "100.000":
            failures.append(
                f"spot 1s move={spot_records[-1]['payload'].get('spot_move_bps_1s')} expected=100.000"
            )
        elif spot_records[-1]["payload"].get("spot_move_threshold_met") is not True:
            failures.append("spot threshold flag was not set")

        if len(kalshi_records) != 1:
            failures.append(f"kalshi diagnostics count={len(kalshi_records)} expected=1")
        else:
            payload = kalshi_records[0]["payload"]
            if payload.get("yes_bid") != "0.44":
                failures.append(f"yes_bid={payload.get('yes_bid')} expected=0.44")
            if payload.get("yes_ask") != "0.48":
                failures.append(f"yes_ask={payload.get('yes_ask')} expected=0.48")
            if payload.get("no_bid") != "0.52":
                failures.append(f"no_bid={payload.get('no_bid')} expected=0.52")
            if payload.get("no_ask") != "0.56":
                failures.append(f"no_ask={payload.get('no_ask')} expected=0.56")
            if len(payload.get("yes_depth_levels", ())) != 1:
                failures.append("yes depth was not capped to one level")

        if len(replay_records) != len(records):
            failures.append("replay diagnostics record count did not match runtime logs")
        if disabled_logger.path.exists():
            failures.append("disabled diagnostics wrote a runtime log")

    if failures:
        print("Latency diagnostics check failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print("Latency diagnostics check succeeded.")
    print("spot_records=2")
    print("kalshi_records=1")
    print("disabled_records=0")
    return 0


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        return self.value


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    raise SystemExit(main())
