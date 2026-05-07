"""Validate Phase 6 contract scanning and ranking with offline fixtures."""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
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
    failures.extend(_validate_low_confidence_down_impulse_ranks(scanner))
    failures.extend(_validate_low_confidence_impulse_weak_recent_skips(scanner))
    failures.extend(_validate_low_confidence_impulse_opposite_lookback_skips(scanner))
    failures.extend(_validate_low_confidence_down_impulse_opposite_recent_skips(scanner))
    failures.extend(_validate_low_confidence_impulse_missing_return_skips(scanner))
    failures.extend(_validate_late_expansion_precedes_unconfirmed_impulse(scanner))
    failures.extend(_validate_high_confidence_mature_impulse_ranks(scanner))
    failures.extend(_validate_reversal_mature_impulse_ranks(scanner))
    failures.extend(_validate_exhaustion_impulse_unchanged(scanner))
    failures.extend(_validate_target_feasibility_diagnostics())
    failures.extend(_validate_unrealistic_late_cross_skips())
    failures.extend(_validate_needs_cross_soft_distance_downgrades())
    failures.extend(_validate_needs_cross_hard_distance_skips())
    failures.extend(_validate_required_bps_per_minute_skips())
    failures.extend(_validate_currently_itm_not_feasibility_downgraded())
    failures.extend(_validate_trend_confirmation_downgrades_without_reclassification())
    failures.extend(_validate_confirmed_trend_keeps_score_confidence())
    failures.extend(_validate_hype_needs_cross_caution_downgrades())
    failures.extend(_validate_weak_reversal_score_downgrade(scanner))
    failures.extend(_validate_impulse_direction_conflict_downgrade(scanner))
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


def _validate_low_confidence_down_impulse_ranks(scanner: ContractScanner) -> list[str]:
    bias_snapshot = _base_bias_snapshot()
    bias_snapshot.products["BTC-USD"] = replace(
        bias_snapshot.products["BTC-USD"],
        direction="down",
        confidence=40,
        structure="trend",
        recent_return_bps=Decimal("-4.000"),
        lookback_return_bps=Decimal("-12.000"),
        impulse_detected=True,
        impulse_direction="down",
        impulse_return_bps=Decimal("-5.000"),
    )
    snapshot = scanner.scan(
        bias_snapshot=bias_snapshot,
        market_snapshot=_base_market_snapshot(),
    )
    ranked_tickers = {contract.market_ticker for contract in snapshot.ranked_contracts}
    if not {"KXBTC-1", "KXBTC-2"}.issubset(ranked_tickers):
        return [f"down impulse ranked mismatch: {ranked_tickers}"]
    return []


def _validate_low_confidence_impulse_weak_recent_skips(scanner: ContractScanner) -> list[str]:
    bias_snapshot = _base_bias_snapshot()
    bias_snapshot.products["BTC-USD"] = replace(
        bias_snapshot.products["BTC-USD"],
        confidence=40,
        structure="trend",
        recent_return_bps=Decimal("2.999"),
        lookback_return_bps=Decimal("12.000"),
        impulse_detected=True,
        impulse_direction="up",
        impulse_return_bps=Decimal("5.000"),
    )
    snapshot = scanner.scan(
        bias_snapshot=bias_snapshot,
        market_snapshot=_base_market_snapshot(),
    )
    reasons = {(item.market_ticker, item.reason) for item in snapshot.skipped_contracts}
    expected = {
        ("KXBTC-1", "impulse_unconfirmed"),
        ("KXBTC-2", "impulse_unconfirmed"),
    }
    if not expected.issubset(reasons):
        return [f"weak recent impulse skip mismatch: {reasons}"]
    return []


def _validate_low_confidence_impulse_opposite_lookback_skips(scanner: ContractScanner) -> list[str]:
    bias_snapshot = _base_bias_snapshot()
    bias_snapshot.products["BTC-USD"] = replace(
        bias_snapshot.products["BTC-USD"],
        confidence=40,
        structure="trend",
        recent_return_bps=Decimal("6.000"),
        lookback_return_bps=Decimal("-4.000"),
        impulse_detected=True,
        impulse_direction="up",
        impulse_return_bps=Decimal("5.000"),
    )
    snapshot = scanner.scan(
        bias_snapshot=bias_snapshot,
        market_snapshot=_base_market_snapshot(),
    )
    reasons = {(item.market_ticker, item.reason) for item in snapshot.skipped_contracts}
    expected = {
        ("KXBTC-1", "impulse_unconfirmed"),
        ("KXBTC-2", "impulse_unconfirmed"),
    }
    if not expected.issubset(reasons):
        return [f"opposite lookback impulse skip mismatch: {reasons}"]
    return []


def _validate_low_confidence_down_impulse_opposite_recent_skips(scanner: ContractScanner) -> list[str]:
    bias_snapshot = _base_bias_snapshot()
    bias_snapshot.products["BTC-USD"] = replace(
        bias_snapshot.products["BTC-USD"],
        direction="down",
        confidence=40,
        structure="trend",
        recent_return_bps=Decimal("4.000"),
        lookback_return_bps=Decimal("-12.000"),
        impulse_detected=True,
        impulse_direction="down",
        impulse_return_bps=Decimal("-5.000"),
    )
    snapshot = scanner.scan(
        bias_snapshot=bias_snapshot,
        market_snapshot=_base_market_snapshot(),
    )
    reasons = {(item.market_ticker, item.reason) for item in snapshot.skipped_contracts}
    expected = {
        ("KXBTC-1", "impulse_unconfirmed"),
        ("KXBTC-2", "impulse_unconfirmed"),
    }
    if not expected.issubset(reasons):
        return [f"opposite recent down impulse skip mismatch: {reasons}"]
    return []


def _validate_low_confidence_impulse_missing_return_skips(scanner: ContractScanner) -> list[str]:
    bias_snapshot = _base_bias_snapshot()
    bias_snapshot.products["BTC-USD"] = replace(
        bias_snapshot.products["BTC-USD"],
        confidence=40,
        structure="trend",
        recent_return_bps=None,
        lookback_return_bps=Decimal("12.000"),
        impulse_detected=True,
        impulse_direction="up",
        impulse_return_bps=Decimal("5.000"),
    )
    snapshot = scanner.scan(
        bias_snapshot=bias_snapshot,
        market_snapshot=_base_market_snapshot(),
    )
    reasons = {(item.market_ticker, item.reason) for item in snapshot.skipped_contracts}
    expected = {
        ("KXBTC-1", "impulse_unconfirmed"),
        ("KXBTC-2", "impulse_unconfirmed"),
    }
    if not expected.issubset(reasons):
        return [f"missing return impulse skip mismatch: {reasons}"]
    return []


def _validate_late_expansion_precedes_unconfirmed_impulse(scanner: ContractScanner) -> list[str]:
    bias_snapshot = _base_bias_snapshot()
    bias_snapshot.products["BTC-USD"] = replace(
        bias_snapshot.products["BTC-USD"],
        confidence=40,
        structure="trend",
        recent_return_bps=Decimal("2.000"),
        lookback_return_bps=Decimal("-4.000"),
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
        return [f"late expansion precedence mismatch: {reasons}"]
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


def _validate_target_feasibility_diagnostics() -> list[str]:
    scanner = ContractScanner(
        product_markets={"BTC-USD": ("KXBTC-1",)},
        market_metadata_by_ticker={
            "KXBTC-1": {
                "close_time": _future_iso(minutes=5),
                "target_price": Decimal("99"),
                "target_price_source": "target_price",
            }
        },
    )
    bias_snapshot = _base_bias_snapshot()
    bias_snapshot.products["BTC-USD"] = replace(
        bias_snapshot.products["BTC-USD"],
        latest_price=Decimal("100"),
    )
    snapshot = scanner.scan(
        bias_snapshot=bias_snapshot,
        market_snapshot=_base_market_snapshot(),
    )
    contract = snapshot.ranked_contracts[0]
    failures: list[str] = []
    if contract.feasibility_status != "currently_itm":
        failures.append(f"target feasibility status={contract.feasibility_status}")
    if contract.side_currently_itm is not True or contract.side_needs_cross is not False:
        failures.append(
            "target feasibility itm flags="
            f"{contract.side_currently_itm}/{contract.side_needs_cross}"
        )
    if contract.distance_to_target_bps != Decimal("-100.000"):
        failures.append(f"target distance bps={contract.distance_to_target_bps}")
    return failures


def _validate_unrealistic_late_cross_skips() -> list[str]:
    scanner = ContractScanner(
        product_markets={"BTC-USD": ("KXBTC-1",)},
        market_metadata_by_ticker={
            "KXBTC-1": {
                "close_time": _future_iso(seconds=30),
                "target_price": Decimal("101"),
                "target_price_source": "target_price",
            }
        },
    )
    bias_snapshot = _base_bias_snapshot()
    bias_snapshot.products["BTC-USD"] = replace(
        bias_snapshot.products["BTC-USD"],
        latest_price=Decimal("100"),
    )
    snapshot = scanner.scan(
        bias_snapshot=bias_snapshot,
        market_snapshot=_base_market_snapshot(),
    )
    reasons = {(item.market_ticker, item.reason) for item in snapshot.skipped_contracts}
    if ("KXBTC-1", "target_feasibility_unrealistic_late_cross") not in reasons:
        return [f"unrealistic late cross skip mismatch: {reasons}"]
    return []


def _validate_needs_cross_soft_distance_downgrades() -> list[str]:
    scanner = ContractScanner(
        product_markets={"BTC-USD": ("KXBTC-1",)},
        market_metadata_by_ticker={
            "KXBTC-1": {
                "close_time": _future_iso(minutes=10),
                "target_price": Decimal("100.06"),
                "target_price_source": "target_price",
            }
        },
    )
    bias_snapshot = _base_bias_snapshot()
    bias_snapshot.products["BTC-USD"] = replace(
        bias_snapshot.products["BTC-USD"],
        latest_price=Decimal("100"),
    )
    snapshot = scanner.scan(
        bias_snapshot=bias_snapshot,
        market_snapshot=_base_market_snapshot(),
    )
    failures: list[str] = []
    if snapshot.skipped_contracts:
        failures.append(f"soft needs-cross skipped={snapshot.skipped_contracts}")
        return failures
    contract = snapshot.ranked_contracts[0]
    if contract.distance_to_target_bps != Decimal("6.000"):
        failures.append(f"soft needs-cross distance={contract.distance_to_target_bps}")
    if contract.score.confidence != 30:
        failures.append(f"soft needs-cross score={contract.score.confidence}")
    if "needs_cross_distance_over_soft_limit" not in contract.scanner_score_downgrade_reasons:
        failures.append(
            "soft needs-cross reasons="
            f"{contract.scanner_score_downgrade_reasons}"
        )
    return failures


def _validate_needs_cross_hard_distance_skips() -> list[str]:
    scanner = ContractScanner(
        product_markets={"BTC-USD": ("KXBTC-1",)},
        market_metadata_by_ticker={
            "KXBTC-1": {
                "close_time": _future_iso(minutes=20),
                "target_price": Decimal("100.11"),
                "target_price_source": "target_price",
            }
        },
    )
    bias_snapshot = _base_bias_snapshot()
    bias_snapshot.products["BTC-USD"] = replace(
        bias_snapshot.products["BTC-USD"],
        latest_price=Decimal("100"),
    )
    snapshot = scanner.scan(
        bias_snapshot=bias_snapshot,
        market_snapshot=_base_market_snapshot(),
    )
    reasons = {(item.market_ticker, item.reason) for item in snapshot.skipped_contracts}
    if ("KXBTC-1", "target_feasibility_distance_too_far") not in reasons:
        return [f"hard distance skip mismatch: {reasons}"]
    skipped = snapshot.skipped_contracts[0]
    if skipped.distance_to_target_bps != Decimal("11.000"):
        return [f"hard distance bps={skipped.distance_to_target_bps}"]
    return []


def _validate_required_bps_per_minute_skips() -> list[str]:
    scanner = ContractScanner(
        product_markets={"BTC-USD": ("KXBTC-1",)},
        market_metadata_by_ticker={
            "KXBTC-1": {
                "close_time": _future_iso(minutes=2),
                "target_price": Decimal("100.05"),
                "target_price_source": "target_price",
            }
        },
    )
    bias_snapshot = _base_bias_snapshot()
    bias_snapshot.products["BTC-USD"] = replace(
        bias_snapshot.products["BTC-USD"],
        latest_price=Decimal("100"),
    )
    snapshot = scanner.scan(
        bias_snapshot=bias_snapshot,
        market_snapshot=_base_market_snapshot(),
    )
    reasons = {(item.market_ticker, item.reason) for item in snapshot.skipped_contracts}
    if ("KXBTC-1", "target_feasibility_required_move_too_fast") not in reasons:
        return [f"required move skip mismatch: {reasons}"]
    return []


def _validate_currently_itm_not_feasibility_downgraded() -> list[str]:
    scanner = ContractScanner(
        product_markets={"BTC-USD": ("KXBTC-1",)},
        market_metadata_by_ticker={
            "KXBTC-1": {
                "close_time": _future_iso(minutes=5),
                "target_price": Decimal("99"),
                "target_price_source": "target_price",
            }
        },
    )
    bias_snapshot = _base_bias_snapshot()
    bias_snapshot.products["BTC-USD"] = replace(
        bias_snapshot.products["BTC-USD"],
        confidence=70,
        latest_price=Decimal("100"),
    )
    snapshot = scanner.scan(
        bias_snapshot=bias_snapshot,
        market_snapshot=_base_market_snapshot(),
    )
    contract = snapshot.ranked_contracts[0]
    if contract.score.confidence != 70:
        return [f"currently-itm score={contract.score.confidence}"]
    if contract.scanner_score_downgrade_reasons:
        return [f"currently-itm downgrade reasons={contract.scanner_score_downgrade_reasons}"]
    return []


def _validate_trend_confirmation_downgrades_without_reclassification() -> list[str]:
    scanner = ContractScanner(
        product_markets={"BTC-USD": ("KXBTC-1",)},
        market_metadata_by_ticker={
            "KXBTC-1": {
                "close_time": _future_iso(minutes=5),
                "target_price": Decimal("99"),
                "target_price_source": "target_price",
            }
        },
    )
    bias_snapshot = _base_bias_snapshot()
    bias_snapshot.products["BTC-USD"] = replace(
        bias_snapshot.products["BTC-USD"],
        confidence=70,
        structure="trend",
        recent_return_bps=Decimal("8.000"),
        lookback_return_bps=Decimal("60.000"),
        latest_price=Decimal("100"),
    )
    snapshot = scanner.scan(
        bias_snapshot=bias_snapshot,
        market_snapshot=_base_market_snapshot(),
    )
    contract = snapshot.ranked_contracts[0]
    failures: list[str] = []
    if contract.structure != "trend":
        failures.append(f"weak trend structure={contract.structure}")
    if contract.confidence != 70:
        failures.append(f"weak trend raw confidence={contract.confidence}")
    if contract.trend_confirmation_status != "weak_recent_return":
        failures.append(f"weak trend status={contract.trend_confirmation_status}")
    if contract.score.confidence != 30:
        failures.append(f"weak trend score={contract.score.confidence}")
    return failures


def _validate_confirmed_trend_keeps_score_confidence() -> list[str]:
    scanner = ContractScanner(
        product_markets={"BTC-USD": ("KXBTC-1",)},
        market_metadata_by_ticker={
            "KXBTC-1": {
                "close_time": _future_iso(minutes=5),
                "target_price": Decimal("99"),
                "target_price_source": "target_price",
            }
        },
    )
    bias_snapshot = _base_bias_snapshot()
    bias_snapshot.products["BTC-USD"] = replace(
        bias_snapshot.products["BTC-USD"],
        confidence=70,
        structure="trend",
        recent_return_bps=Decimal("20.000"),
        lookback_return_bps=Decimal("60.000"),
        latest_price=Decimal("100"),
    )
    snapshot = scanner.scan(
        bias_snapshot=bias_snapshot,
        market_snapshot=_base_market_snapshot(),
    )
    contract = snapshot.ranked_contracts[0]
    if contract.trend_confirmation_status != "confirmed":
        return [f"confirmed trend status={contract.trend_confirmation_status}"]
    if contract.score.confidence != 70:
        return [f"confirmed trend score={contract.score.confidence}"]
    return []


def _validate_hype_needs_cross_caution_downgrades() -> list[str]:
    scanner = ContractScanner(
        product_markets={"HYPE-USD": ("KXHYPE-1",)},
        market_metadata_by_ticker={
            "KXHYPE-1": {
                "close_time": _future_iso(minutes=10),
                "target_price": Decimal("100.04"),
                "target_price_source": "target_price",
            }
        },
    )
    bias_snapshot = BiasSnapshot(
        products={
            "HYPE-USD": replace(
                _base_bias_snapshot().products["BTC-USD"],
                product_id="HYPE-USD",
                latest_price=Decimal("100"),
            )
        }
    )
    market_snapshot = MarketStateSnapshot(
        tickers={
            "KXHYPE-1": replace(
                _base_market_snapshot().tickers["KXBTC-1"],
                market_ticker="KXHYPE-1",
            )
        },
        orderbooks={},
        last_sequence_by_sid={},
    )
    snapshot = scanner.scan(
        bias_snapshot=bias_snapshot,
        market_snapshot=market_snapshot,
    )
    if snapshot.skipped_contracts:
        return [f"HYPE needs-cross skipped={snapshot.skipped_contracts}"]
    contract = snapshot.ranked_contracts[0]
    failures: list[str] = []
    if contract.score.confidence != 30:
        failures.append(f"HYPE needs-cross score={contract.score.confidence}")
    if "hype_needs_cross_caution" not in contract.scanner_score_downgrade_reasons:
        failures.append(
            "HYPE downgrade reasons="
            f"{contract.scanner_score_downgrade_reasons}"
        )
    return failures


def _validate_weak_reversal_score_downgrade(scanner: ContractScanner) -> list[str]:
    bias_snapshot = _base_bias_snapshot()
    bias_snapshot.products["BTC-USD"] = replace(
        bias_snapshot.products["BTC-USD"],
        direction="up",
        confidence=60,
        structure="reversal",
        recent_return_bps=Decimal("5.000"),
        lookback_return_bps=Decimal("-80.000"),
        impulse_detected=False,
        impulse_direction=None,
        impulse_return_bps=Decimal("1.000"),
    )
    snapshot = scanner.scan(
        bias_snapshot=bias_snapshot,
        market_snapshot=_base_market_snapshot(),
    )
    contract = next(
        item for item in snapshot.ranked_contracts if item.market_ticker == "KXBTC-1"
    )
    failures: list[str] = []
    if contract.confidence != 60:
        failures.append(f"weak reversal raw confidence={contract.confidence}")
    if contract.score.confidence != 30:
        failures.append(f"weak reversal score confidence={contract.score.confidence}")
    if contract.reversal_confirmation_status != "weak_recent_return":
        failures.append(
            "weak reversal status="
            f"{contract.reversal_confirmation_status}"
        )
    return failures


def _validate_impulse_direction_conflict_downgrade(scanner: ContractScanner) -> list[str]:
    bias_snapshot = _base_bias_snapshot()
    bias_snapshot.products["BTC-USD"] = replace(
        bias_snapshot.products["BTC-USD"],
        direction="up",
        confidence=60,
        structure="reversal",
        recent_return_bps=Decimal("20.000"),
        lookback_return_bps=Decimal("-80.000"),
        impulse_detected=False,
        impulse_direction=None,
        impulse_return_bps=Decimal("-5.000"),
    )
    snapshot = scanner.scan(
        bias_snapshot=bias_snapshot,
        market_snapshot=_base_market_snapshot(),
    )
    contract = next(
        item for item in snapshot.ranked_contracts if item.market_ticker == "KXBTC-1"
    )
    if contract.score.confidence != 30:
        return [f"conflict score confidence={contract.score.confidence}"]
    if not dict(contract.signal_conflict_flags).get("impulse_direction_conflict"):
        return [f"conflict flags={contract.signal_conflict_flags}"]
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


def _future_iso(*, minutes: int = 0, seconds: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes, seconds=seconds)).isoformat()


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
