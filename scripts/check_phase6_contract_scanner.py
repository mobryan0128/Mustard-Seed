"""Validate Phase 6 contract scanning and ranking with offline fixtures."""

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
from kalshi_bot.contracts.contract_scanner import (  # noqa: E402
    ContractScanner,
    ContractScannerError,
)
from kalshi_bot.forecast.bias_engine import BiasRiskFlags, BiasSnapshot, BiasState  # noqa: E402
from kalshi_bot.market.market_state_cache import MarketStateSnapshot, TickerState  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Phase 6 contract scanner behavior.")
    parser.add_argument(
        "--env-file",
        default=".env.example",
        help="Environment file used to load Phase 6 defaults. Defaults to .env.example.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Optionally run one live scan against current Kalshi and crypto feed state.",
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
        scanner = ContractScanner(
            product_markets={
                "BTC-USD": ("KXBTC-1", "KXBTC-2", "KXBTC-MISSING"),
                "ETH-USD": ("KXETH-1",),
            }
        )
        failures = _run_fixtures(scanner)
    except (SettingsError, ContractScannerError) as exc:
        print(f"Phase 6 contract scanner check failed: {exc}", file=sys.stderr)
        return 1

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1

    print("Phase 6 contract scanner offline fixtures succeeded.")
    if args.live:
        return asyncio.run(_run_live_scan(settings, args.message_limit))
    return 0


def _run_fixtures(scanner: ContractScanner) -> list[str]:
    failures: list[str] = []
    failures.extend(_validate_multi_market_ranking(scanner))
    failures.extend(_validate_btc_eth_resolution(scanner))
    failures.extend(_validate_neutral_skip(scanner))
    failures.extend(_validate_zero_confidence_skip(scanner))
    failures.extend(_validate_missing_quote_skip(scanner))
    failures.extend(_validate_ranking_tiebreak(scanner))
    failures.extend(_validate_low_confidence_mature_impulse_skip(scanner))
    failures.extend(_validate_low_confidence_small_impulse_ranks(scanner))
    failures.extend(_validate_high_confidence_mature_impulse_ranks(scanner))
    failures.extend(_validate_reversal_mature_impulse_ranks(scanner))
    failures.extend(_validate_exhaustion_impulse_unchanged(scanner))
    return failures


def _validate_multi_market_ranking(scanner: ContractScanner) -> list[str]:
    snapshot = scanner.scan(
        bias_snapshot=_base_bias_snapshot(),
        market_snapshot=_base_market_snapshot(),
    )
    failures: list[str] = []
    ranked_tickers = tuple(contract.market_ticker for contract in snapshot.ranked_contracts)
    if ranked_tickers != ("KXBTC-1", "KXBTC-2", "KXETH-1"):
        failures.append(f"ranking order mismatch: {ranked_tickers}")
    midpoint = snapshot.ranked_contracts[0].midpoint
    if midpoint != Decimal("0.460"):
        failures.append(f"midpoint mismatch: {midpoint}")
    if not isinstance(midpoint, Decimal):
        failures.append("midpoint is not Decimal")
    return failures


def _validate_btc_eth_resolution(scanner: ContractScanner) -> list[str]:
    snapshot = scanner.scan(
        bias_snapshot=_base_bias_snapshot(),
        market_snapshot=_base_market_snapshot(),
    )
    seen_products = {contract.product_id for contract in snapshot.ranked_contracts}
    if seen_products != {"BTC-USD", "ETH-USD"}:
        return [f"product mapping mismatch: {seen_products}"]
    return []


def _validate_neutral_skip(scanner: ContractScanner) -> list[str]:
    bias_snapshot = _base_bias_snapshot()
    bias_snapshot.products["BTC-USD"] = replace(
        bias_snapshot.products["BTC-USD"],
        direction="neutral",
    )
    snapshot = scanner.scan(
        bias_snapshot=bias_snapshot,
        market_snapshot=_base_market_snapshot(),
    )
    reasons = {(item.market_ticker, item.reason) for item in snapshot.skipped_contracts}
    expected = {("KXBTC-1", "neutral_bias"), ("KXBTC-2", "neutral_bias")}
    if not expected.issubset(reasons):
        return [f"neutral skip mismatch: {reasons}"]
    return []


def _validate_zero_confidence_skip(scanner: ContractScanner) -> list[str]:
    bias_snapshot = _base_bias_snapshot()
    bias_snapshot.products["ETH-USD"] = replace(
        bias_snapshot.products["ETH-USD"],
        confidence=0,
    )
    snapshot = scanner.scan(
        bias_snapshot=bias_snapshot,
        market_snapshot=_base_market_snapshot(),
    )
    reasons = {(item.market_ticker, item.reason) for item in snapshot.skipped_contracts}
    if ("KXETH-1", "zero_confidence") not in reasons:
        return [f"zero confidence skip mismatch: {reasons}"]
    return []


def _validate_missing_quote_skip(scanner: ContractScanner) -> list[str]:
    market_snapshot = _base_market_snapshot()
    market_snapshot.tickers["KXBTC-2"] = replace(
        market_snapshot.tickers["KXBTC-2"],
        yes_ask_dollars=None,
    )
    snapshot = scanner.scan(
        bias_snapshot=_base_bias_snapshot(),
        market_snapshot=market_snapshot,
    )
    reasons = {(item.market_ticker, item.reason) for item in snapshot.skipped_contracts}
    if ("KXBTC-2", "missing_best_quote") not in reasons:
        return [f"missing quote skip mismatch: {reasons}"]
    return []


def _validate_ranking_tiebreak(scanner: ContractScanner) -> list[str]:
    market_snapshot = _base_market_snapshot()
    market_snapshot.tickers["KXBTC-2"] = replace(
        market_snapshot.tickers["KXBTC-2"],
        yes_bid_dollars=Decimal("0.44"),
        yes_ask_dollars=Decimal("0.48"),
        yes_bid_size_fp=Decimal("100"),
        yes_ask_size_fp=Decimal("100"),
        dollar_volume=Decimal("1000"),
    )
    snapshot = scanner.scan(
        bias_snapshot=_base_bias_snapshot(),
        market_snapshot=market_snapshot,
    )
    ranked_tickers = tuple(contract.market_ticker for contract in snapshot.ranked_contracts)
    if ranked_tickers[:2] != ("KXBTC-1", "KXBTC-2"):
        return [f"lexical tiebreak mismatch: {ranked_tickers}"]
    return []


def _validate_low_confidence_mature_impulse_skip(scanner: ContractScanner) -> list[str]:
    bias_snapshot = _base_bias_snapshot()
    bias_snapshot.products["BTC-USD"] = replace(
        bias_snapshot.products["BTC-USD"],
        confidence=40,
        structure="trend",
        impulse_detected=True,
        impulse_direction="up",
        impulse_return_bps=Decimal("6.000"),
    )
    snapshot = scanner.scan(
        bias_snapshot=bias_snapshot,
        market_snapshot=_base_market_snapshot(),
    )
    reasons = {(item.market_ticker, item.reason) for item in snapshot.skipped_contracts}
    expected = {
        ("KXBTC-1", "too_late_after_expansion"),
        ("KXBTC-2", "too_late_after_expansion"),
    }
    if not expected.issubset(reasons):
        return [f"late expansion skip mismatch: {reasons}"]
    return []


def _validate_low_confidence_small_impulse_ranks(scanner: ContractScanner) -> list[str]:
    bias_snapshot = _base_bias_snapshot()
    bias_snapshot.products["BTC-USD"] = replace(
        bias_snapshot.products["BTC-USD"],
        confidence=40,
        structure="trend",
        impulse_detected=True,
        impulse_direction="up",
        impulse_return_bps=Decimal("5.999"),
    )
    snapshot = scanner.scan(
        bias_snapshot=bias_snapshot,
        market_snapshot=_base_market_snapshot(),
    )
    ranked_tickers = {contract.market_ticker for contract in snapshot.ranked_contracts}
    if not {"KXBTC-1", "KXBTC-2"}.issubset(ranked_tickers):
        return [f"small impulse ranked mismatch: {ranked_tickers}"]
    return []


def _validate_high_confidence_mature_impulse_ranks(scanner: ContractScanner) -> list[str]:
    bias_snapshot = _base_bias_snapshot()
    bias_snapshot.products["BTC-USD"] = replace(
        bias_snapshot.products["BTC-USD"],
        confidence=60,
        structure="trend",
        impulse_detected=True,
        impulse_direction="up",
        impulse_return_bps=Decimal("9.000"),
    )
    snapshot = scanner.scan(
        bias_snapshot=bias_snapshot,
        market_snapshot=_base_market_snapshot(),
    )
    ranked_tickers = {contract.market_ticker for contract in snapshot.ranked_contracts}
    if not {"KXBTC-1", "KXBTC-2"}.issubset(ranked_tickers):
        return [f"high confidence impulse ranked mismatch: {ranked_tickers}"]
    return []


def _validate_reversal_mature_impulse_ranks(scanner: ContractScanner) -> list[str]:
    bias_snapshot = _base_bias_snapshot()
    bias_snapshot.products["BTC-USD"] = replace(
        bias_snapshot.products["BTC-USD"],
        confidence=40,
        structure="reversal",
        impulse_detected=True,
        impulse_direction="up",
        impulse_return_bps=Decimal("9.000"),
    )
    snapshot = scanner.scan(
        bias_snapshot=bias_snapshot,
        market_snapshot=_base_market_snapshot(),
    )
    ranked_tickers = {contract.market_ticker for contract in snapshot.ranked_contracts}
    if not {"KXBTC-1", "KXBTC-2"}.issubset(ranked_tickers):
        return [f"reversal mature impulse ranked mismatch: {ranked_tickers}"]
    return []


def _validate_exhaustion_impulse_unchanged(scanner: ContractScanner) -> list[str]:
    bias_snapshot = _base_bias_snapshot()
    bias_snapshot.products["BTC-USD"] = replace(
        bias_snapshot.products["BTC-USD"],
        direction="neutral",
        confidence=30,
        structure="exhaustion",
        impulse_detected=True,
        impulse_direction="up",
        impulse_return_bps=Decimal("9.000"),
    )
    snapshot = scanner.scan(
        bias_snapshot=bias_snapshot,
        market_snapshot=_base_market_snapshot(),
    )
    reasons = {(item.market_ticker, item.reason) for item in snapshot.skipped_contracts}
    expected = {("KXBTC-1", "neutral_bias"), ("KXBTC-2", "neutral_bias")}
    if not expected.issubset(reasons):
        return [f"exhaustion impulse skip mismatch: {reasons}"]
    return []


def _base_bias_snapshot() -> BiasSnapshot:
    return BiasSnapshot(
        products={
            "BTC-USD": BiasState(
                product_id="BTC-USD",
                direction="up",
                confidence=70,
                structure="trend",
                risk_flags=BiasRiskFlags(
                    insufficient_history=False,
                    stale_data=False,
                    time_sync_failed=False,
                ),
                latest_price=Decimal("70000"),
                lookback_return_bps=Decimal("125"),
                recent_return_bps=Decimal("30"),
                observation_count=50,
                as_of="2026-04-23T12:00:00+00:00",
            ),
            "ETH-USD": BiasState(
                product_id="ETH-USD",
                direction="down",
                confidence=60,
                structure="reversal",
                risk_flags=BiasRiskFlags(
                    insufficient_history=False,
                    stale_data=False,
                    time_sync_failed=False,
                ),
                latest_price=Decimal("3200"),
                lookback_return_bps=Decimal("-90"),
                recent_return_bps=Decimal("-20"),
                observation_count=45,
                as_of="2026-04-23T12:00:05+00:00",
            ),
        }
    )


def _base_market_snapshot() -> MarketStateSnapshot:
    return MarketStateSnapshot(
        tickers={
            "KXBTC-1": TickerState(
                market_ticker="KXBTC-1",
                yes_bid_dollars=Decimal("0.44"),
                yes_ask_dollars=Decimal("0.48"),
                yes_bid_size_fp=Decimal("100"),
                yes_ask_size_fp=Decimal("100"),
                dollar_volume=Decimal("1000"),
                exchange_time="2026-04-23T12:00:03+00:00",
            ),
            "KXBTC-2": TickerState(
                market_ticker="KXBTC-2",
                yes_bid_dollars=Decimal("0.43"),
                yes_ask_dollars=Decimal("0.49"),
                yes_bid_size_fp=Decimal("90"),
                yes_ask_size_fp=Decimal("80"),
                dollar_volume=Decimal("900"),
                exchange_time="2026-04-23T12:00:04+00:00",
            ),
            "KXETH-1": TickerState(
                market_ticker="KXETH-1",
                yes_bid_dollars=Decimal("0.40"),
                yes_ask_dollars=Decimal("0.46"),
                yes_bid_size_fp=Decimal("110"),
                yes_ask_size_fp=Decimal("95"),
                dollar_volume=Decimal("850"),
                exchange_time="2026-04-23T12:00:06+00:00",
            ),
        },
        orderbooks={},
        last_sequence_by_sid={},
    )


async def _run_live_scan(settings, message_limit: int | None) -> int:
    try:
        from kalshi_bot.clients.crypto_feed_client import CryptoFeedClient, CryptoFeedClientError
        from kalshi_bot.clients.websocket_client import KalshiWebSocketClient, KalshiWebSocketError
        from kalshi_bot.forecast.bias_engine import BiasEngine
        from kalshi_bot.market.market_state_cache import MarketStateCache
        from websockets.exceptions import WebSocketException
    except ImportError as exc:
        print(f"Phase 6 live scan unavailable: {exc}", file=sys.stderr)
        return 1

    try:
        scanner = ContractScanner.from_settings(settings)
    except ContractScannerError as exc:
        print(f"Phase 6 live scan failed: {exc}", file=sys.stderr)
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
            crypto_client.run(message_limit=message_limit or settings.crypto_feed_message_limit),
        )
    except (KalshiWebSocketError, CryptoFeedClientError, WebSocketException) as exc:
        print(f"Phase 6 live scan failed: {exc}", file=sys.stderr)
        return 1

    bias_snapshot = bias_engine.ingest(crypto_client.snapshot())
    scan_snapshot = scanner.scan(
        bias_snapshot=bias_snapshot,
        market_snapshot=cache.snapshot(),
    )
    print("Phase 6 live scan succeeded.")
    print(f"ranked_contracts={len(scan_snapshot.ranked_contracts)}")
    print(f"skipped_contracts={len(scan_snapshot.skipped_contracts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
