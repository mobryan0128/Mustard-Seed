"""Validate Phase 7 simulation execution behavior with offline fixtures."""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import replace
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
    parser = argparse.ArgumentParser(description="Validate Phase 7 simulation behavior.")
    parser.add_argument(
        "--env-file",
        default=".env.example",
        help="Environment file used to load Phase 7 defaults. Defaults to .env.example.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Optionally run one live scan-plus-simulate pass against current state.",
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
        print(f"Phase 7 simulation check failed: {exc}", file=sys.stderr)
        return 1

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1

    print("Phase 7 simulation offline fixtures succeeded.")
    if args.live:
        return asyncio.run(_run_live_simulation(settings, args.message_limit))
    return 0


def _run_fixtures(engine: SimulationExecutionEngine) -> list[str]:
    failures: list[str] = []
    first_snapshot = engine.evaluate(_first_scan_snapshot())
    failures.extend(_validate_first_entry(first_snapshot))

    second_snapshot = engine.evaluate(_second_scan_snapshot())
    failures.extend(_validate_update_and_conflict(second_snapshot))

    third_snapshot = engine.evaluate(_third_scan_snapshot())
    failures.extend(_validate_second_product_entry(third_snapshot))
    failures.extend(_validate_snapshot_is_inspectable(third_snapshot))
    return failures


def _validate_first_entry(snapshot) -> list[str]:
    failures: list[str] = []
    if len(snapshot.open_positions) != 1:
        failures.append(f"first entry open_positions={len(snapshot.open_positions)} expected=1")
    position = snapshot.open_positions.get("sim-0001")
    if position is None:
        failures.append("first entry missing sim-0001")
        return failures
    if position.product_id != "BTC-USD" or position.market_ticker != "KXBTC-1":
        failures.append(
            f"first entry wrong identity {position.product_id}/{position.market_ticker}"
        )
    if position.entry_price != Decimal("0.460") or position.latest_price != Decimal("0.460"):
        failures.append(
            f"first entry wrong prices entry={position.entry_price} latest={position.latest_price}"
        )
    if position.update_count != 0:
        failures.append(f"first entry update_count={position.update_count} expected=0")
    if snapshot.decisions[-1].action != "open_position":
        failures.append(f"first entry decision={snapshot.decisions[-1].action} expected=open_position")
    return failures


def _validate_update_and_conflict(snapshot) -> list[str]:
    failures: list[str] = []
    position = snapshot.open_positions.get("sim-0001")
    if position is None:
        failures.append("second snapshot missing sim-0001")
        return failures
    if position.latest_price != Decimal("0.470"):
        failures.append(f"second snapshot latest_price={position.latest_price} expected=0.470")
    if position.update_count != 1:
        failures.append(f"second snapshot update_count={position.update_count} expected=1")
    actions = tuple(decision.action for decision in snapshot.decisions)
    if actions != ("update_position", "skip_entry"):
        failures.append(f"second snapshot actions={actions}")
    if snapshot.decisions[-1].reason != "open_position_for_product":
        failures.append(f"second snapshot skip reason={snapshot.decisions[-1].reason}")
    return failures


def _validate_second_product_entry(snapshot) -> list[str]:
    failures: list[str] = []
    if set(snapshot.open_positions) != {"sim-0001", "sim-0002"}:
        failures.append(f"third snapshot positions={tuple(sorted(snapshot.open_positions))}")
    second_position = snapshot.open_positions.get("sim-0002")
    if second_position is None:
        failures.append("third snapshot missing sim-0002")
        return failures
    if second_position.product_id != "ETH-USD" or second_position.entry_price != Decimal("0.430"):
        failures.append(
            f"third snapshot wrong second position {second_position.product_id}/{second_position.entry_price}"
        )
    if snapshot.decisions[-1].action != "open_position":
        failures.append(f"third snapshot final action={snapshot.decisions[-1].action}")
    return failures


def _validate_snapshot_is_inspectable(snapshot) -> list[str]:
    failures: list[str] = []
    if snapshot.evaluation_count != 3:
        failures.append(f"evaluation_count={snapshot.evaluation_count} expected=3")
    if not all(isinstance(position.entry_price, Decimal) for position in snapshot.open_positions.values()):
        failures.append("entry_price is not Decimal for all open positions")
    if not all(isinstance(position.latest_price, Decimal) for position in snapshot.open_positions.values()):
        failures.append("latest_price is not Decimal for all open positions")
    return failures


def _first_scan_snapshot() -> ContractScanSnapshot:
    return ContractScanSnapshot(
        ranked_contracts=(
            _scanned_contract(
                product_id="BTC-USD",
                market_ticker="KXBTC-1",
                midpoint=Decimal("0.460"),
                confidence=70,
                structure="trend",
                direction="up",
                bias_as_of="2026-04-23T12:00:00+00:00",
                market_as_of="2026-04-23T12:00:03+00:00",
            ),
            _scanned_contract(
                product_id="ETH-USD",
                market_ticker="KXETH-1",
                midpoint=Decimal("0.430"),
                confidence=60,
                structure="reversal",
                direction="down",
                bias_as_of="2026-04-23T12:00:05+00:00",
                market_as_of="2026-04-23T12:00:06+00:00",
            ),
        ),
        skipped_contracts=(),
    )


def _second_scan_snapshot() -> ContractScanSnapshot:
    return ContractScanSnapshot(
        ranked_contracts=(
            _scanned_contract(
                product_id="BTC-USD",
                market_ticker="KXBTC-1",
                midpoint=Decimal("0.470"),
                confidence=72,
                structure="trend",
                direction="up",
                bias_as_of="2026-04-23T12:01:00+00:00",
                market_as_of="2026-04-23T12:01:03+00:00",
            ),
            _scanned_contract(
                product_id="BTC-USD",
                market_ticker="KXBTC-2",
                midpoint=Decimal("0.455"),
                confidence=68,
                structure="trend",
                direction="up",
                bias_as_of="2026-04-23T12:01:00+00:00",
                market_as_of="2026-04-23T12:01:04+00:00",
            ),
        ),
        skipped_contracts=(),
    )


def _third_scan_snapshot() -> ContractScanSnapshot:
    return ContractScanSnapshot(
        ranked_contracts=(
            _scanned_contract(
                product_id="ETH-USD",
                market_ticker="KXETH-1",
                midpoint=Decimal("0.430"),
                confidence=75,
                structure="trend",
                direction="down",
                bias_as_of="2026-04-23T12:02:00+00:00",
                market_as_of="2026-04-23T12:02:02+00:00",
            ),
            _scanned_contract(
                product_id="BTC-USD",
                market_ticker="KXBTC-1",
                midpoint=Decimal("0.468"),
                confidence=70,
                structure="trend",
                direction="up",
                bias_as_of="2026-04-23T12:02:00+00:00",
                market_as_of="2026-04-23T12:02:03+00:00",
            ),
        ),
        skipped_contracts=(),
    )


def _scanned_contract(
    *,
    product_id: str,
    market_ticker: str,
    midpoint: Decimal,
    confidence: int,
    structure: str,
    direction: str,
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


async def _run_live_simulation(settings, message_limit: int | None) -> int:
    try:
        from kalshi_bot.clients.crypto_feed_client import CryptoFeedClient, CryptoFeedClientError
        from kalshi_bot.clients.websocket_client import KalshiWebSocketClient, KalshiWebSocketError
        from kalshi_bot.contracts.contract_scanner import ContractScanner, ContractScannerError
        from kalshi_bot.execution.execution_engine import SimulationExecutionEngine
        from kalshi_bot.forecast.bias_engine import BiasEngine
        from kalshi_bot.market.market_state_cache import MarketStateCache
        from websockets.exceptions import WebSocketException
    except ImportError as exc:
        print(f"Phase 7 live simulation unavailable: {exc}", file=sys.stderr)
        return 1

    try:
        scanner = ContractScanner.from_settings(settings)
        engine = SimulationExecutionEngine.from_settings(settings)
    except (ContractScannerError, SimulationExecutionError) as exc:
        print(f"Phase 7 live simulation failed: {exc}", file=sys.stderr)
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
        print(f"Phase 7 live simulation failed: {exc}", file=sys.stderr)
        return 1

    bias_snapshot = bias_engine.ingest(crypto_client.snapshot())
    scan_snapshot = scanner.scan(
        bias_snapshot=bias_snapshot,
        market_snapshot=cache.snapshot(),
    )
    simulation_snapshot = engine.evaluate(scan_snapshot)
    updated_positions = sum(
        1 for decision in simulation_snapshot.decisions if decision.action == "update_position"
    )
    print("Phase 7 live simulation succeeded.")
    print(f"open_positions={len(simulation_snapshot.open_positions)}")
    print(f"decisions={len(simulation_snapshot.decisions)}")
    print(f"updated_positions={updated_positions}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
