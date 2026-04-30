"""Validate CEX-vs-Kalshi mispricing opportunity scanning."""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi_bot.clients.crypto_feed_client import (  # noqa: E402
    CryptoFeedClient,
    CryptoFeedSnapshot,
    CryptoPriceState,
    parse_crypto_feed_message,
)
from kalshi_bot.market.crypto_market_discovery import (  # noqa: E402
    DiscoveredCryptoMarket,
)
from kalshi_bot.market.market_state_cache import (  # noqa: E402
    MarketStateSnapshot,
    TickerState,
)
from kalshi_bot.opportunity.mispricing_scanner import (  # noqa: E402
    scan_mispricing_opportunities,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate CEX-vs-Kalshi mispricing opportunity scanning."
    )
    parser.parse_args()

    failures: list[str] = []
    failures.extend(_validate_candidate_without_bias_state())
    failures.extend(_validate_missing_target_skips())
    failures.extend(_validate_missing_external_price_skips())
    failures.extend(_validate_yes_and_no_executable_prices())
    failures.extend(_validate_ranking_prefers_edge_then_price_then_spread())
    failures.extend(_validate_min_edge_gate_skips_when_configured())
    failures.extend(_validate_external_freshness_gate_skips_stale_price())
    failures.extend(_validate_kalshi_freshness_gate_skips_missing_quote_time())
    failures.extend(_validate_kalshi_epoch_timestamp_age_ms())
    failures.extend(_validate_heartbeat_does_not_refresh_price_timestamp())

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1

    print("Mispricing opportunity scanner checks succeeded.")
    return 0


def _validate_candidate_without_bias_state() -> list[str]:
    snapshot = _scan(
        markets=(_market("KXBTC15M-YES", target=Decimal("100")),),
        external_price=Decimal("101"),
        tickers={
            "KXBTC15M-YES": _ticker(
                "KXBTC15M-YES",
                yes_bid=Decimal("0.40"),
                yes_ask=Decimal("0.45"),
            ),
        },
    )
    if len(snapshot.ranked_contracts) != 1:
        return [f"neutral-independent ranked={len(snapshot.ranked_contracts)}"]
    contract = snapshot.ranked_contracts[0]
    failures: list[str] = []
    expected = {
        "opportunity_source": "mispricing",
        "structure": "mispricing",
        "direction": "up",
        "implied_side": "yes",
        "executable_price": Decimal("0.45"),
        "edge_bps": Decimal("100.000"),
        "target_source_field": "subtitle",
        "external_price_age_ms": 1000,
        "kalshi_quote_age_ms": 0,
        "cycle_started_at": "2026-04-23T12:00:02+00:00",
    }
    for key, value in expected.items():
        if getattr(contract, key) != value:
            failures.append(
                f"candidate {key}={getattr(contract, key)} expected={value}"
            )
    return failures


def _validate_missing_target_skips() -> list[str]:
    snapshot = _scan(
        markets=(_market("KXBTC15M-NOTARGET", target=None),),
        external_price=Decimal("101"),
        tickers={"KXBTC15M-NOTARGET": _ticker("KXBTC15M-NOTARGET")},
    )
    return _assert_skip(snapshot, "missing_contract_target_price")


def _validate_missing_external_price_skips() -> list[str]:
    snapshot = _scan(
        markets=(_market("KXBTC15M-NOEXT", target=Decimal("100")),),
        external_price=None,
        tickers={"KXBTC15M-NOEXT": _ticker("KXBTC15M-NOEXT")},
    )
    return _assert_skip(snapshot, "missing_external_price")


def _validate_yes_and_no_executable_prices() -> list[str]:
    yes_snapshot = _scan(
        markets=(_market("KXBTC15M-YES", target=Decimal("100")),),
        external_price=Decimal("101"),
        tickers={
            "KXBTC15M-YES": _ticker(
                "KXBTC15M-YES",
                yes_bid=Decimal("0.40"),
                yes_ask=Decimal("0.45"),
            ),
        },
    )
    no_snapshot = _scan(
        markets=(_market("KXBTC15M-NO", target=Decimal("100")),),
        external_price=Decimal("99"),
        tickers={
            "KXBTC15M-NO": _ticker(
                "KXBTC15M-NO",
                yes_bid=Decimal("0.40"),
                yes_ask=Decimal("0.45"),
            ),
        },
    )
    failures: list[str] = []
    yes_contract = yes_snapshot.ranked_contracts[0]
    if (
        yes_contract.implied_side != "yes"
        or yes_contract.executable_price != Decimal("0.45")
    ):
        failures.append(f"yes executable={yes_contract}")
    no_contract = no_snapshot.ranked_contracts[0]
    if (
        no_contract.implied_side != "no"
        or no_contract.executable_price != Decimal("0.60")
    ):
        failures.append(f"no executable={no_contract}")
    if no_contract.direction != "down":
        failures.append(f"no direction={no_contract.direction}")
    return failures


def _validate_ranking_prefers_edge_then_price_then_spread() -> list[str]:
    snapshot = _scan(
        markets=(
            _market("KXBTC15M-HIGHEDGE", target=Decimal("100")),
            _market("KXBTC15M-CHEAPER", target=Decimal("101")),
            _market("KXBTC15M-PRICEY", target=Decimal("101")),
        ),
        external_price=Decimal("102"),
        tickers={
            "KXBTC15M-HIGHEDGE": _ticker(
                "KXBTC15M-HIGHEDGE",
                yes_bid=Decimal("0.65"),
                yes_ask=Decimal("0.70"),
            ),
            "KXBTC15M-CHEAPER": _ticker(
                "KXBTC15M-CHEAPER",
                yes_bid=Decimal("0.37"),
                yes_ask=Decimal("0.40"),
            ),
            "KXBTC15M-PRICEY": _ticker(
                "KXBTC15M-PRICEY",
                yes_bid=Decimal("0.40"),
                yes_ask=Decimal("0.45"),
            ),
        },
    )
    ranked = tuple(contract.market_ticker for contract in snapshot.ranked_contracts)
    expected = (
        "KXBTC15M-HIGHEDGE",
        "KXBTC15M-CHEAPER",
        "KXBTC15M-PRICEY",
    )
    if ranked != expected:
        return [f"ranking={ranked} expected={expected}"]
    return []


def _validate_min_edge_gate_skips_when_configured() -> list[str]:
    snapshot = _scan(
        markets=(_market("KXBTC15M-WEAK", target=Decimal("100")),),
        external_price=Decimal("100.010"),
        tickers={"KXBTC15M-WEAK": _ticker("KXBTC15M-WEAK")},
        min_edge_bps=Decimal("2"),
    )
    return _assert_skip(snapshot, "mispricing_edge_below_minimum")


def _validate_external_freshness_gate_skips_stale_price() -> list[str]:
    snapshot = _scan(
        markets=(_market("KXBTC15M-STALEEXT", target=Decimal("100")),),
        external_price=Decimal("101"),
        external_price_timestamp="2026-04-23T11:59:59+00:00",
        tickers={"KXBTC15M-STALEEXT": _ticker("KXBTC15M-STALEEXT")},
        max_external_price_age_ms=500,
    )
    return _assert_skip(snapshot, "mispricing_external_price_stale")


def _validate_kalshi_freshness_gate_skips_missing_quote_time() -> list[str]:
    snapshot = _scan(
        markets=(_market("KXBTC15M-NOQUOTEAGE", target=Decimal("100")),),
        external_price=Decimal("101"),
        tickers={
            "KXBTC15M-NOQUOTEAGE": _ticker(
                "KXBTC15M-NOQUOTEAGE",
                exchange_time=None,
            ),
        },
        max_kalshi_quote_age_ms=500,
    )
    return _assert_skip(snapshot, "missing_kalshi_timestamp")


def _validate_kalshi_epoch_timestamp_age_ms() -> list[str]:
    snapshot = _scan(
        markets=(_market("KXBTC15M-EPOCHQUOTE", target=Decimal("100")),),
        external_price=Decimal("101"),
        tickers={
            "KXBTC15M-EPOCHQUOTE": _ticker(
                "KXBTC15M-EPOCHQUOTE",
                exchange_time=None,
                exchange_ts=1776945601000,
            ),
        },
        max_kalshi_quote_age_ms=150000,
    )
    if len(snapshot.ranked_contracts) != 1:
        return [f"epoch quote ranked={len(snapshot.ranked_contracts)}"]
    contract = snapshot.ranked_contracts[0]
    if contract.kalshi_quote_age_ms != 1000:
        return [f"epoch quote age={contract.kalshi_quote_age_ms} expected=1000"]
    return []


def _validate_heartbeat_does_not_refresh_price_timestamp() -> list[str]:
    client = CryptoFeedClient(
        ws_url="wss://example.invalid",
        products=("BTC-USD",),
        message_limit=1,
        receive_timeout_seconds=1.0,
        max_reconnect_attempts=1,
        reconnect_initial_delay_seconds=1.0,
        reconnect_max_delay_seconds=1.0,
    )
    ticker_messages = parse_crypto_feed_message(
        '{"channel":"ticker","timestamp":"2026-04-23T12:00:00Z",'
        '"sequence_num":1,"events":[{"tickers":[{"product_id":"BTC-USD",'
        '"price":"100"}]}]}'
    )
    heartbeat_messages = parse_crypto_feed_message(
        '{"channel":"heartbeats","timestamp":"2026-04-23T12:00:05Z",'
        '"sequence_num":2,"events":[{"current_time":"2026-04-23T12:00:05Z",'
        '"heartbeat_counter":2,"product_id":"BTC-USD"}]}'
    )
    for message in (*ticker_messages, *heartbeat_messages):
        client._apply_message(message)  # noqa: SLF001
    state = client.snapshot().products["BTC-USD"]
    failures: list[str] = []
    if state.source_timestamp != "2026-04-23T12:00:00Z":
        failures.append(f"source_timestamp={state.source_timestamp}")
    if state.price_source_timestamp != "2026-04-23T12:00:00Z":
        failures.append(f"price_source_timestamp={state.price_source_timestamp}")
    if state.last_heartbeat_time != "2026-04-23T12:00:05Z":
        failures.append(f"last_heartbeat_time={state.last_heartbeat_time}")
    return failures


def _scan(
    *,
    markets: tuple[DiscoveredCryptoMarket, ...],
    external_price: Decimal | None,
    tickers: dict[str, TickerState],
    external_price_timestamp: str = "2026-04-23T12:00:01+00:00",
    min_edge_bps: Decimal | None = None,
    max_external_price_age_ms: int | None = None,
    max_kalshi_quote_age_ms: int | None = None,
):
    products = {}
    if external_price is not None:
        products["BTC-USD"] = CryptoPriceState(
            product_id="BTC-USD",
            price=external_price,
            source_timestamp=external_price_timestamp,
            price_source_timestamp=external_price_timestamp,
        )
    return scan_mispricing_opportunities(
        discovered_markets=markets,
        crypto_snapshot=CryptoFeedSnapshot(
            products=products,
            last_heartbeat_time=None,
            last_heartbeat_counter=None,
            subscribed_channels=(),
        ),
        market_snapshot=MarketStateSnapshot(
            tickers=tickers,
            orderbooks={},
            last_sequence_by_sid={},
        ),
        min_entry_price=Decimal("0"),
        max_entry_price=Decimal("0.800"),
        max_execution_spread_dollars=Decimal("0.100"),
        min_edge_bps=min_edge_bps,
        max_external_price_age_ms=max_external_price_age_ms,
        max_kalshi_quote_age_ms=max_kalshi_quote_age_ms,
        cycle_started_at="2026-04-23T12:00:02+00:00",
    )


def _market(
    market_ticker: str,
    *,
    target: Decimal | None,
) -> DiscoveredCryptoMarket:
    return DiscoveredCryptoMarket(
        product_id="BTC-USD",
        series_ticker="KXBTC15M",
        market_ticker=market_ticker,
        close_time="2026-04-23T12:15:00+00:00",
        open_time="2026-04-23T12:00:00+00:00",
        expiration_time="2026-04-23T12:15:00+00:00",
        contract_target_price=target,
        target_source_field="subtitle",
    )


def _ticker(
    market_ticker: str,
    *,
    yes_bid: Decimal = Decimal("0.40"),
    yes_ask: Decimal = Decimal("0.45"),
    exchange_ts: int | None = None,
    exchange_time: str | None = "2026-04-23T12:00:02+00:00",
) -> TickerState:
    return TickerState(
        market_ticker=market_ticker,
        yes_bid_dollars=yes_bid,
        yes_ask_dollars=yes_ask,
        yes_bid_size_fp=Decimal("100"),
        yes_ask_size_fp=Decimal("100"),
        dollar_volume=Decimal("1000"),
        exchange_ts=exchange_ts,
        exchange_time=exchange_time,
    )


def _assert_skip(snapshot, expected_reason: str) -> list[str]:  # noqa: ANN001
    if snapshot.ranked_contracts:
        return [f"{expected_reason} ranked={snapshot.ranked_contracts}"]
    if len(snapshot.skipped_contracts) != 1:
        return [f"{expected_reason} skipped={len(snapshot.skipped_contracts)}"]
    skipped = snapshot.skipped_contracts[0]
    failures: list[str] = []
    if skipped.reason != expected_reason:
        failures.append(f"skip reason={skipped.reason} expected={expected_reason}")
    if skipped.reason_skipped != expected_reason:
        failures.append(
            f"reason_skipped={skipped.reason_skipped} expected={expected_reason}"
        )
    if skipped.opportunity_source != "mispricing":
        failures.append(f"skip source={skipped.opportunity_source}")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
