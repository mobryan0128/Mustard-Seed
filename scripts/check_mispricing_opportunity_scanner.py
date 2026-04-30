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
    CryptoFeedSnapshot,
    CryptoPriceState,
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


def _scan(
    *,
    markets: tuple[DiscoveredCryptoMarket, ...],
    external_price: Decimal | None,
    tickers: dict[str, TickerState],
):
    products = {}
    if external_price is not None:
        products["BTC-USD"] = CryptoPriceState(
            product_id="BTC-USD",
            price=external_price,
            source_timestamp="2026-04-23T12:00:01+00:00",
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
    )


def _ticker(
    market_ticker: str,
    *,
    yes_bid: Decimal = Decimal("0.40"),
    yes_ask: Decimal = Decimal("0.45"),
) -> TickerState:
    return TickerState(
        market_ticker=market_ticker,
        yes_bid_dollars=yes_bid,
        yes_ask_dollars=yes_ask,
        yes_bid_size_fp=Decimal("100"),
        yes_ask_size_fp=Decimal("100"),
        dollar_volume=Decimal("1000"),
        exchange_time="2026-04-23T12:00:02+00:00",
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
