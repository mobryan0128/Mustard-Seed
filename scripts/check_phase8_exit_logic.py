"""Validate Phase 8 simulation exit behavior with offline fixtures."""

from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi_bot.config.settings import SettingsError, load_settings  # noqa: E402
from kalshi_bot.contracts.contract_scanner import ContractScanSnapshot, ScannedContract  # noqa: E402
from kalshi_bot.contracts.contract_scorer import ContractScore  # noqa: E402
from kalshi_bot.execution.execution_engine import (  # noqa: E402
    SimulationExecutionEngine,
    SimulationExecutionError,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Phase 8 simulation exit behavior.")
    parser.add_argument(
        "--env-file",
        default=".env.example",
        help="Environment file used to load Phase 8 defaults. Defaults to .env.example.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Optionally run a bounded live scan-plus-simulate smoke path.",
    )
    parser.add_argument(
        "--message-limit",
        type=int,
        default=None,
        help="Maximum live messages to process per feed when --live is set.",
    )
    args = parser.parse_args()

    try:
        settings = load_settings(args.env_file)
        engine = SimulationExecutionEngine.from_settings(settings)
        failures = _run_fixtures(engine)
    except (SettingsError, SimulationExecutionError) as exc:
        print(f"Phase 8 exit logic check failed: {exc}", file=sys.stderr)
        return 1

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1

    print("Phase 8 simulation exit offline fixtures succeeded.")
    if args.live:
        return asyncio.run(_run_live_exit_smoke(settings, args.message_limit))
    return 0


def _run_fixtures(engine: SimulationExecutionEngine) -> list[str]:
    failures: list[str] = []

    first_snapshot = engine.evaluate(_entry_snapshot())
    failures.extend(_validate_first_entry(first_snapshot))

    second_snapshot = engine.evaluate(_direction_conflict_snapshot())
    failures.extend(_validate_direction_conflict_exit(second_snapshot))

    third_snapshot = engine.evaluate(_market_disappearance_snapshot())
    failures.extend(_validate_market_disappearance_exit(third_snapshot))

    fourth_snapshot = engine.evaluate(_steady_state_snapshot())
    failures.extend(_validate_steady_state_update(fourth_snapshot))

    return failures


def _validate_first_entry(snapshot) -> list[str]:
    failures: list[str] = []
    if tuple(snapshot.open_positions) != ("sim-0001",):
        failures.append(f"first pass open positions={tuple(snapshot.open_positions)}")
        return failures
    position = snapshot.open_positions["sim-0001"]
    if position.product_id != "BTC-USD" or position.market_ticker != "KXBTC-1":
        failures.append(
            f"first pass wrong open identity {position.product_id}/{position.market_ticker}"
        )
    if position.entry_price != Decimal("0.460") or position.latest_price != Decimal("0.460"):
        failures.append(
            f"first pass wrong prices entry={position.entry_price} latest={position.latest_price}"
        )
    if snapshot.closed_positions:
        failures.append("first pass expected no closed positions")
    actions = tuple(decision.action for decision in snapshot.decisions)
    if actions != ("open_position",):
        failures.append(f"first pass actions={actions}")
    return failures


def _validate_direction_conflict_exit(snapshot) -> list[str]:
    failures: list[str] = []
    if "sim-0001" in snapshot.open_positions:
        failures.append("direction conflict pass left sim-0001 open")
    if tuple(snapshot.open_positions) != ("sim-0002",):
        failures.append(f"direction conflict pass open positions={tuple(snapshot.open_positions)}")
    if len(snapshot.closed_positions) != 1:
        failures.append(
            f"direction conflict pass closed positions={len(snapshot.closed_positions)} expected=1"
        )
        return failures

    closed_position = snapshot.closed_positions[0]
    if closed_position.exit_reason != "direction_conflict":
        failures.append(f"direction conflict reason={closed_position.exit_reason}")
    if closed_position.exit_price != Decimal("0.490"):
        failures.append(f"direction conflict exit_price={closed_position.exit_price}")
    if closed_position.market_ticker != "KXBTC-1":
        failures.append(f"direction conflict closed ticker={closed_position.market_ticker}")

    open_position = snapshot.open_positions["sim-0002"]
    if open_position.product_id != "ETH-USD":
        failures.append(f"direction conflict opened wrong product={open_position.product_id}")

    actions = tuple(decision.action for decision in snapshot.decisions)
    if actions != ("close_position", "skip_entry", "open_position"):
        failures.append(f"direction conflict actions={actions}")
    reasons = tuple(decision.reason for decision in snapshot.decisions)
    if reasons[1] != "same_pass_reentry_disallowed":
        failures.append(f"direction conflict skip reason={reasons[1]}")
    return failures


def _validate_market_disappearance_exit(snapshot) -> list[str]:
    failures: list[str] = []
    if snapshot.evaluation_count != 3:
        failures.append(f"market disappearance evaluation_count={snapshot.evaluation_count}")
    if tuple(snapshot.open_positions) != ("sim-0003",):
        failures.append(f"market disappearance open positions={tuple(snapshot.open_positions)}")
    if len(snapshot.closed_positions) != 2:
        failures.append(
            f"market disappearance closed positions={len(snapshot.closed_positions)} expected=2"
        )
        return failures

    closed_position = snapshot.closed_positions[-1]
    if closed_position.position_id != "sim-0002":
        failures.append(f"market disappearance closed id={closed_position.position_id}")
    if closed_position.exit_reason != "market_not_ranked":
        failures.append(f"market disappearance reason={closed_position.exit_reason}")
    if closed_position.exit_price != Decimal("0.430"):
        failures.append(f"market disappearance exit_price={closed_position.exit_price}")

    open_position = snapshot.open_positions["sim-0003"]
    if open_position.product_id != "BTC-USD" or open_position.entry_price != Decimal("0.510"):
        failures.append(
            f"market disappearance opened wrong replacement {open_position.product_id}/{open_position.entry_price}"
        )

    actions = tuple(decision.action for decision in snapshot.decisions)
    if actions != ("close_position", "open_position"):
        failures.append(f"market disappearance actions={actions}")
    return failures


def _validate_steady_state_update(snapshot) -> list[str]:
    failures: list[str] = []
    if tuple(snapshot.open_positions) != ("sim-0003",):
        failures.append(f"steady state open positions={tuple(snapshot.open_positions)}")
        return failures
    if len(snapshot.closed_positions) != 2:
        failures.append(f"steady state closed positions={len(snapshot.closed_positions)} expected=2")
    open_position = snapshot.open_positions["sim-0003"]
    if open_position.latest_price != Decimal("0.520"):
        failures.append(f"steady state latest_price={open_position.latest_price}")
    if open_position.update_count != 1:
        failures.append(f"steady state update_count={open_position.update_count}")
    if not isinstance(open_position.entry_price, Decimal) or not isinstance(
        open_position.latest_price, Decimal
    ):
        failures.append("steady state prices are not Decimal")
    actions = tuple(decision.action for decision in snapshot.decisions)
    if actions != ("update_position", "skip_entry"):
        failures.append(f"steady state actions={actions}")
    if snapshot.decisions[-1].reason != "open_position_for_product":
        failures.append(f"steady state skip reason={snapshot.decisions[-1].reason}")
    return failures


def _entry_snapshot() -> ContractScanSnapshot:
    return ContractScanSnapshot(
        ranked_contracts=(
            _scanned_contract(
                product_id="BTC-USD",
                market_ticker="KXBTC-1",
                direction="up",
                structure="trend",
                confidence=75,
                midpoint=Decimal("0.460"),
                bias_as_of="2026-04-23T12:00:00+00:00",
                market_as_of="2026-04-23T12:00:03+00:00",
            ),
        ),
        skipped_contracts=(),
    )


def _direction_conflict_snapshot() -> ContractScanSnapshot:
    return ContractScanSnapshot(
        ranked_contracts=(
            _scanned_contract(
                product_id="BTC-USD",
                market_ticker="KXBTC-2",
                direction="down",
                structure="reversal",
                confidence=82,
                midpoint=Decimal("0.520"),
                bias_as_of="2026-04-23T12:01:00+00:00",
                market_as_of="2026-04-23T12:01:01+00:00",
            ),
            _scanned_contract(
                product_id="ETH-USD",
                market_ticker="KXETH-1",
                direction="up",
                structure="trend",
                confidence=70,
                midpoint=Decimal("0.430"),
                bias_as_of="2026-04-23T12:01:02+00:00",
                market_as_of="2026-04-23T12:01:03+00:00",
            ),
            _scanned_contract(
                product_id="BTC-USD",
                market_ticker="KXBTC-1",
                direction="up",
                structure="trend",
                confidence=65,
                midpoint=Decimal("0.490"),
                bias_as_of="2026-04-23T12:01:04+00:00",
                market_as_of="2026-04-23T12:01:05+00:00",
            ),
        ),
        skipped_contracts=(),
    )


def _market_disappearance_snapshot() -> ContractScanSnapshot:
    return ContractScanSnapshot(
        ranked_contracts=(
            _scanned_contract(
                product_id="BTC-USD",
                market_ticker="KXBTC-2",
                direction="up",
                structure="trend",
                confidence=77,
                midpoint=Decimal("0.510"),
                bias_as_of="2026-04-23T12:02:00+00:00",
                market_as_of="2026-04-23T12:02:02+00:00",
            ),
        ),
        skipped_contracts=(),
    )


def _steady_state_snapshot() -> ContractScanSnapshot:
    return ContractScanSnapshot(
        ranked_contracts=(
            _scanned_contract(
                product_id="BTC-USD",
                market_ticker="KXBTC-2",
                direction="up",
                structure="trend",
                confidence=79,
                midpoint=Decimal("0.520"),
                bias_as_of="2026-04-23T12:03:00+00:00",
                market_as_of="2026-04-23T12:03:04+00:00",
            ),
        ),
        skipped_contracts=(),
    )


def _scanned_contract(
    *,
    product_id: str,
    market_ticker: str,
    direction: str,
    structure: str,
    confidence: int,
    midpoint: Decimal,
    bias_as_of: str,
    market_as_of: str,
) -> ScannedContract:
    score = ContractScore(
        confidence=confidence,
        spread_width=Decimal("0.040"),
        top_of_book_liquidity=Decimal("200"),
        dollar_volume=Decimal("1000"),
    )
    return ScannedContract(
        product_id=product_id,
        market_ticker=market_ticker,
        direction=direction,
        structure=structure,
        confidence=confidence,
        best_bid=midpoint - Decimal("0.020"),
        best_ask=midpoint + Decimal("0.020"),
        midpoint=midpoint,
        bias_as_of=bias_as_of,
        market_as_of=market_as_of,
        score=score,
    )


async def _run_live_exit_smoke(settings, message_limit: int | None) -> int:
    try:
        from kalshi_bot.clients.crypto_feed_client import CryptoFeedClient, CryptoFeedClientError
        from kalshi_bot.clients.websocket_client import KalshiWebSocketClient, KalshiWebSocketError
        from kalshi_bot.contracts.contract_scanner import ContractScanner, ContractScannerError
        from kalshi_bot.execution.execution_engine import SimulationExecutionEngine
        from kalshi_bot.forecast.bias_engine import BiasEngine
        from kalshi_bot.market.market_state_cache import MarketStateCache
        from websockets.exceptions import WebSocketException
    except ImportError as exc:
        print(f"Phase 8 live exit smoke unavailable: {exc}", file=sys.stderr)
        return 1

    try:
        scanner = ContractScanner.from_settings(settings)
        engine = SimulationExecutionEngine.from_settings(settings)
    except (ContractScannerError, SimulationExecutionError) as exc:
        print(f"Phase 8 live exit smoke failed: {exc}", file=sys.stderr)
        return 1

    market_tickers = tuple(
        dict.fromkeys(
            market_ticker
            for tickers in settings.contract_scanner_product_markets.values()
            for market_ticker in tickers
        )
    )
    cache = MarketStateCache()
    bias_engine = BiasEngine.from_settings(settings)

    try:
        kalshi_client = KalshiWebSocketClient.from_settings(settings, market_state_cache=cache)
        crypto_client = CryptoFeedClient.from_settings(settings)
        await asyncio.gather(
            kalshi_client.run(
                market_tickers=market_tickers,
                message_limit=message_limit or settings.ws_message_limit,
            ),
            crypto_client.run(
                message_limit=message_limit or settings.crypto_feed_message_limit,
            ),
        )
    except (KalshiWebSocketError, CryptoFeedClientError, WebSocketException) as exc:
        print(f"Phase 8 live exit smoke failed: {exc}", file=sys.stderr)
        return 1

    bias_snapshot = bias_engine.ingest(crypto_client.snapshot())
    scan_snapshot = scanner.scan(
        bias_snapshot=bias_snapshot,
        market_snapshot=cache.snapshot(),
    )
    engine.evaluate(scan_snapshot)
    second_snapshot = engine.evaluate(scan_snapshot)
    close_decisions = sum(
        1 for decision in second_snapshot.decisions if decision.action == "close_position"
    )
    print("Phase 8 live exit smoke succeeded.")
    print(f"open_positions={len(second_snapshot.open_positions)}")
    print(f"closed_positions={len(second_snapshot.closed_positions)}")
    print(f"close_decisions={close_decisions}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
