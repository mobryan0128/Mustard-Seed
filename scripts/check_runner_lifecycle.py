"""Validate continuous runner lifecycle with offline fake components."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi_bot.config.settings import KalshiSettings  # noqa: E402
from kalshi_bot.clients.kalshi_client import (  # noqa: E402
    KalshiMarketPage,
    KalshiMarketSummary,
    KalshiOrderRequest,
)
from kalshi_bot.execution.execution_engine import (  # noqa: E402
    LiveOrderIntent,
    SimulatedPosition,
    SimulationDecision,
    SimulationSnapshot,
)
from kalshi_bot.execution.exit_manager import ClosedSimulatedPosition  # noqa: E402
from kalshi_bot.execution.live_execution_coordinator import LiveExecutionCoordinator  # noqa: E402
from kalshi_bot.forecast.bias_engine import BiasRiskFlags, BiasSnapshot, BiasState  # noqa: E402
from kalshi_bot.market.crypto_market_discovery import (  # noqa: E402
    CryptoMarketDiscovery,
    CryptoMarketDiscoverySnapshot,
    DiscoveredCryptoMarket,
)
from kalshi_bot.market.market_state_cache import MarketStateCache  # noqa: E402
from kalshi_bot.observability.logger import StructuredLogger  # noqa: E402
from kalshi_bot.observability.replay_engine import ReplayEngine  # noqa: E402
from kalshi_bot.runner.orchestrator import (  # noqa: E402
    KalshiBotRunner,
    RunnerError,
    _live_runner_risk_manager_from_settings,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate runner lifecycle with offline fixtures.")
    parser.parse_args()

    failures: list[str] = []
    failures.extend(_validate_single_cycle())
    failures.extend(_validate_multiple_cycles())
    failures.extend(_validate_clean_stop())
    failures.extend(_validate_live_flags_do_not_enable_live_actions())
    failures.extend(_validate_startup_fail_closed())
    failures.extend(_validate_market_discovery_tradable_filter())
    failures.extend(_validate_subscription_ack_without_market_data_is_not_connected())
    failures.extend(_validate_expired_market_forces_rollover_discovery())
    failures.extend(_validate_feed_timeout_forces_market_discovery_resubscribe())
    failures.extend(_validate_simulation_trade_events_persisted())
    failures.extend(_validate_simulation_risk_denied_event_persisted())
    failures.extend(_validate_live_order_candidate_logged())
    failures.extend(_validate_live_order_intent_skip_logged())
    failures.extend(_validate_live_runner_no_intents_logged())
    failures.extend(_validate_live_runner_disabled_does_not_submit())
    failures.extend(_validate_live_runner_enabled_submits_one_intent())
    failures.extend(_validate_live_fast_scan_uses_cache_only_path())
    failures.extend(_validate_live_runner_blocked_submission_logged())
    failures.extend(_validate_live_runner_starts_without_simulation())
    failures.extend(_validate_live_runner_risk_does_not_require_live_validation())
    failures.extend(_validate_live_runner_uses_live_risk_overrides())

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1

    print("Runner lifecycle offline fixtures succeeded.")
    return 0


def _validate_single_cycle() -> list[str]:
    runner, state = _build_runner()
    results = runner.run_cycles(1)
    failures: list[str] = []
    if len(results) != 1:
        failures.append(f"single-cycle count={len(results)}")
        return failures
    result = results[0]
    if result.cycle_number != 1:
        failures.append(f"single-cycle number={result.cycle_number}")
    if result.status.mode != "simulation":
        failures.append(f"single-cycle mode={result.status.mode}")
    if not result.status.kalshi_feed_connected or not result.status.crypto_feed_connected:
        failures.append("single-cycle feed status did not report connected")
    if result.status.kalshi_market_data_message_count != 1:
        failures.append(
            f"single-cycle market data messages={result.status.kalshi_market_data_message_count}"
        )
    if result.status.kalshi_subscribed_market_tickers != ("KXBTC15M-OLD",):
        failures.append(
            f"single-cycle ws requested={result.status.kalshi_subscribed_market_tickers}"
        )
    if result.status.ranked_contract_count != 1:
        failures.append(f"single-cycle ranked={result.status.ranked_contract_count}")
    if result.status.active_market_tickers != ("KXBTC15M-OLD",):
        failures.append(f"single-cycle active tickers={result.status.active_market_tickers}")
    if result.status.last_market_discovery_cycle != 1:
        failures.append(f"single-cycle discovery cycle={result.status.last_market_discovery_cycle}")
    if result.status.skipped_contract_count != 0:
        failures.append(f"single-cycle skipped={result.status.skipped_contract_count}")
    skip_reasons = tuple((item.reason, item.count) for item in result.status.top_skip_reasons)
    if skip_reasons != ():
        failures.append(f"single-cycle skip reasons={skip_reasons}")
    bias_by_product = {item.product_id: item for item in result.status.bias_diagnostics}
    btc_bias = bias_by_product.get("BTC-USD")
    eth_bias = bias_by_product.get("ETH-USD")
    if btc_bias is None or not btc_bias.state_present:
        failures.append("single-cycle BTC-USD bias diagnostic missing")
    elif (
        btc_bias.direction != "up"
        or btc_bias.confidence != 70
        or btc_bias.structure != "trend"
        or dict(btc_bias.risk_flags).get("stale_data")
        or btc_bias.latest_price != Decimal("70000")
        or btc_bias.bias_as_of != "2026-04-23T12:00:00+00:00"
        or btc_bias.stale_age_seconds is None
        or btc_bias.observation_count != 25
        or btc_bias.recent_return_bps != Decimal("20")
        or btc_bias.lookback_return_bps != Decimal("100")
    ):
        failures.append(f"single-cycle BTC-USD bias diagnostic={btc_bias}")
    if eth_bias is None or not eth_bias.state_present:
        failures.append(f"single-cycle ETH-USD bias diagnostic={eth_bias}")
    markets = {
        (item.product_id, item.market_ticker): item
        for item in result.status.mapped_market_diagnostics
    }
    if not _market_diagnostic_matches(
        markets.get(("BTC-USD", "KXBTC15M-OLD")),
        market_ticker_present=True,
        bid_present=True,
        ask_present=True,
    ):
        failures.append(
            f"single-cycle KXBTC15M-OLD diagnostic={markets.get(('BTC-USD', 'KXBTC15M-OLD'))}"
        )
    if state.discovery_calls != 1:
        failures.append(f"single-cycle discovery calls={state.discovery_calls}")
    if state.kalshi_run_calls != 1 or state.crypto_run_calls != 1:
        failures.append(
            f"single-cycle run calls kalshi={state.kalshi_run_calls} crypto={state.crypto_run_calls}"
        )
    if not state.log_written or not state.replay_written:
        failures.append("single-cycle did not write log/replay artifacts")
    return failures


def _validate_multiple_cycles() -> list[str]:
    runner, state = _build_runner()
    results = runner.run_cycles(3)
    failures: list[str] = []
    if len(results) != 3:
        failures.append(f"multi-cycle count={len(results)}")
        return failures
    if state.kalshi_run_calls != 3 or state.crypto_run_calls != 3:
        failures.append(
            f"multi-cycle run calls kalshi={state.kalshi_run_calls} crypto={state.crypto_run_calls}"
        )
    if results[-1].status.cycle_count != 3:
        failures.append(f"multi-cycle final cycle_count={results[-1].status.cycle_count}")
    if state.discovery_calls != 2:
        failures.append(f"multi-cycle discovery calls={state.discovery_calls}")
    if state.subscribed_tickers_by_call != (
        ("KXBTC15M-OLD",),
        ("KXBTC15M-OLD",),
        ("KXBTC15M-NEW", "KXETH15M-NEW"),
    ):
        failures.append(f"multi-cycle subscriptions={state.subscribed_tickers_by_call}")
    if results[1].status.active_market_tickers != ("KXBTC15M-OLD",):
        failures.append(f"multi-cycle second active={results[1].status.active_market_tickers}")
    if results[-1].status.active_market_tickers != ("KXBTC15M-NEW", "KXETH15M-NEW"):
        failures.append(f"multi-cycle final active={results[-1].status.active_market_tickers}")
    if "KXBTC15M-OLD" in state.cache.snapshot().tickers:
        failures.append("multi-cycle stale ticker was not pruned")
    return failures


def _validate_clean_stop() -> list[str]:
    runner, state = _build_runner(stop_after_first_cycle=True)
    results = runner.run_forever()
    failures: list[str] = []
    if len(results) != 1:
        failures.append(f"clean-stop count={len(results)}")
    if not runner.snapshot().stopped:
        failures.append("clean-stop runner did not report stopped state")
    if state.kalshi_run_calls != 1 or state.crypto_run_calls != 1:
        failures.append(
            f"clean-stop run calls kalshi={state.kalshi_run_calls} crypto={state.crypto_run_calls}"
        )
    return failures


def _validate_live_flags_do_not_enable_live_actions() -> list[str]:
    runner, _ = _build_runner(live_flags_present=True)
    results = runner.run_cycles(1)
    failures: list[str] = []
    if len(results) != 1:
        failures.append("live-flags fixture did not complete one cycle")
        return failures
    if not results[0].status.live_flags_present:
        failures.append("live-flags fixture did not preserve live_flags_present")
    if results[0].status.mode != "simulation":
        failures.append(f"live-flags mode={results[0].status.mode}")
    return failures


def _validate_startup_fail_closed() -> list[str]:
    runner, _ = _build_runner(kalshi_error="boom", fail_fast_on_startup=True)
    try:
        runner.run_cycles(1)
    except RunnerError:
        return []
    return ["startup failure did not fail closed"]


def _validate_market_discovery_tradable_filter() -> list[str]:
    discovery = CryptoMarketDiscovery(
        kalshi_client=_FakeDiscoveryKalshiClient(),
        product_series={"BTC-USD": ("KXBTC15M",)},
        products=("BTC-USD",),
    )
    snapshot = discovery.discover()
    failures: list[str] = []
    expected = {"BTC-USD": ("KXBTC15M-TEST",)}
    if snapshot.product_markets != expected:
        failures.append(f"tradable discovery mapping={snapshot.product_markets}")
    discovered_tickers = tuple(market.market_ticker for market in snapshot.discovered_markets)
    if discovered_tickers != ("KXBTC15M-TEST",):
        failures.append(f"tradable discovery tickers={discovered_tickers}")
    if snapshot.discovered_markets[0].target_price != Decimal("70000"):
        failures.append(
            "tradable discovery target_price="
            f"{snapshot.discovered_markets[0].target_price}"
        )
    return failures


def _validate_subscription_ack_without_market_data_is_not_connected() -> list[str]:
    runner, state = _build_runner(kalshi_market_data=False)
    results = runner.run_cycles(1)
    failures: list[str] = []
    if len(results) != 1:
        failures.append(f"ack-only count={len(results)}")
        return failures
    status = results[0].status
    if status.kalshi_feed_connected:
        failures.append("ack-only fixture reported Kalshi feed connected")
    if status.tracked_market_count != 0:
        failures.append(f"ack-only tracked markets={status.tracked_market_count}")
    if status.active_market_tickers != ("KXBTC15M-OLD",):
        failures.append(f"ack-only active tickers={status.active_market_tickers}")
    if status.kalshi_market_data_message_count != 0:
        failures.append(f"ack-only data messages={status.kalshi_market_data_message_count}")
    if status.kalshi_subscription_message_count != 1:
        failures.append(
            f"ack-only subscription messages={status.kalshi_subscription_message_count}"
        )
    markets = {
        (item.product_id, item.market_ticker): item
        for item in status.mapped_market_diagnostics
    }
    if not _market_diagnostic_matches(
        markets.get(("BTC-USD", "KXBTC15M-OLD")),
        market_ticker_present=False,
        bid_present=False,
        ask_present=False,
    ):
        failures.append(
            f"ack-only KXBTC15M-OLD diagnostic={markets.get(('BTC-USD', 'KXBTC15M-OLD'))}"
        )
    if state.subscribed_tickers_by_call != (("KXBTC15M-OLD",),):
        failures.append(f"ack-only subscriptions={state.subscribed_tickers_by_call}")
    return failures


def _validate_expired_market_forces_rollover_discovery() -> list[str]:
    runner, state = _build_runner(expired_initial_market=True)
    results = runner.run_cycles(2)
    failures: list[str] = []
    if len(results) != 2:
        failures.append(f"rollover recovery count={len(results)}")
        return failures
    if state.discovery_calls != 2:
        failures.append(f"rollover recovery discovery calls={state.discovery_calls}")
    if state.subscribed_tickers_by_call != (
        ("KXBTC15M-OLD",),
        ("KXBTC15M-NEW", "KXETH15M-NEW"),
    ):
        failures.append(f"rollover recovery subscriptions={state.subscribed_tickers_by_call}")
    if results[-1].status.active_market_tickers != ("KXBTC15M-NEW", "KXETH15M-NEW"):
        failures.append(f"rollover recovery active={results[-1].status.active_market_tickers}")
    if "KXBTC15M-OLD" in state.cache.snapshot().tickers:
        failures.append("rollover recovery stale ticker was not pruned")
    if state.log_written_ref is None:
        return failures + ["rollover recovery missing runtime path"]
    records = _jsonl_records(state.log_written_ref)
    for event_type in (
        "market_rollover_detected",
        "market_discovery_forced",
        "old_ticker_expired",
        "new_ticker_selected",
    ):
        if _first_event_payload(records, key="event_type", value=event_type) is None:
            failures.append(f"rollover recovery {event_type} log missing")
    forced = _first_event_payload(records, key="event_type", value="market_discovery_forced")
    if (
        forced is not None
        and forced.get("subscription_refresh_reason") != "market_rollover_expired_ticker"
    ):
        failures.append(
            "rollover recovery reason="
            f"{forced.get('subscription_refresh_reason')}"
        )
    return failures


def _validate_feed_timeout_forces_market_discovery_resubscribe() -> list[str]:
    runner, state = _build_runner(kalshi_market_data=False)
    state.cache.replace_orderbook(
        market_ticker="KXBTC15M-OLD",
        yes_levels=(("0.44", "100"),),
        no_levels=(("0.52", "100"),),
        sid=1,
        seq=1,
    )
    results = runner.run_cycles(3)
    failures: list[str] = []
    if len(results) != 3:
        failures.append(f"timeout recovery count={len(results)}")
        return failures
    if state.discovery_calls != 2:
        failures.append(f"timeout recovery discovery calls={state.discovery_calls}")
    expected_subscriptions = (
        ("KXBTC15M-OLD",),
        ("KXBTC15M-OLD",),
        ("KXBTC15M-NEW", "KXETH15M-NEW"),
    )
    if state.subscribed_tickers_by_call != expected_subscriptions:
        failures.append(
            "timeout recovery subscriptions="
            f"{state.subscribed_tickers_by_call} expected={expected_subscriptions}"
        )
    final_status = results[-1].status
    if final_status.last_market_discovery_cycle != 3:
        failures.append(
            f"timeout recovery discovery cycle={final_status.last_market_discovery_cycle}"
        )
    if final_status.active_market_tickers != ("KXBTC15M-NEW", "KXETH15M-NEW"):
        failures.append(f"timeout recovery active={final_status.active_market_tickers}")
    if "KXBTC15M-OLD" in state.cache.snapshot().tickers:
        failures.append("timeout recovery stale ticker was not pruned")
    if state.log_written_ref is None:
        return failures + ["timeout recovery missing runtime path"]

    records = _jsonl_records(state.log_written_ref)
    recovery_payload = next(
        (
            payload
            for payload in _event_payloads(
                records,
                key="event_type",
                value="kalshi_feed_timeout_recovery",
            )
            if payload.get("kalshi_feed_recovery_attempted") is True
        ),
        None,
    )
    if recovery_payload is None:
        failures.append("timeout recovery attempted log missing")
    else:
        expected = {
            "kalshi_feed_timeout_count": 2,
            "kalshi_feed_recovery_attempted": True,
            "kalshi_feed_recovery_result": "market_discovery_forced",
        }
        for key, value in expected.items():
            if recovery_payload.get(key) != value:
                failures.append(
                    f"timeout recovery {key}={recovery_payload.get(key)}"
                )

    completed = _first_event_payload(
        records,
        key="event_type",
        value="kalshi_feed_resubscribe_completed",
    )
    if completed is None:
        failures.append("timeout recovery resubscribe completed log missing")
    elif completed.get("kalshi_feed_recovery_result") != "resubscribe_completed":
        failures.append(
            "timeout recovery completed result="
            f"{completed.get('kalshi_feed_recovery_result')}"
        )
    return failures


def _validate_simulation_trade_events_persisted() -> list[str]:
    runner, state = _build_runner(simulation_trade_events=True)
    results = runner.run_cycles(2)
    failures: list[str] = []
    if len(results) != 2:
        failures.append(f"simulation trade events cycle count={len(results)}")
        return failures
    if state.log_written_ref is None or state.replay_written_ref is None:
        return ["simulation trade events missing log/replay paths"]

    runtime_records = _jsonl_records(state.log_written_ref)
    replay_records = _jsonl_records(state.replay_written_ref)

    runtime_opened = _first_event_payload(
        runtime_records,
        key="event_type",
        value="simulation_position_opened",
    )
    runtime_closed = _first_event_payload(
        runtime_records,
        key="event_type",
        value="simulation_position_closed",
    )
    replay_opened = _first_event_payload(
        replay_records,
        key="record_type",
        value="simulation_position_opened",
    )
    replay_closed = _first_event_payload(
        replay_records,
        key="record_type",
        value="simulation_position_closed",
    )

    if runtime_opened is None:
        failures.append("runtime opened simulation trade event missing")
    if replay_opened is None:
        failures.append("replay opened simulation trade event missing")
    if runtime_closed is None:
        failures.append("runtime closed simulation trade event missing")
    if replay_closed is None:
        failures.append("replay closed simulation trade event missing")

    for label, payload in (
        ("runtime", runtime_closed),
        ("replay", replay_closed),
    ):
        if payload is None:
            continue
        expected = {
            "entry_price": "0.460",
            "exit_price": "0.490",
            "stake_dollars": "0.20",
            "exit_reason": "direction_conflict",
            "pnl": "0.030",
            "pnl_dollars": "0.00600",
        }
        for key, value in expected.items():
            if payload.get(key) != value:
                failures.append(f"{label} closed {key}={payload.get(key)} expected={value}")
    return failures


def _validate_simulation_risk_denied_event_persisted() -> list[str]:
    runner, state = _build_runner(simulation_risk_denied_events=True)
    results = runner.run_cycles(1)
    failures: list[str] = []
    if len(results) != 1:
        failures.append(f"risk denied events cycle count={len(results)}")
        return failures
    if state.log_written_ref is None or state.replay_written_ref is None:
        return ["risk denied events missing log/replay paths"]

    runtime_records = _jsonl_records(state.log_written_ref)
    replay_records = _jsonl_records(state.replay_written_ref)
    runtime_denied = _first_event_payload(
        runtime_records,
        key="event_type",
        value="simulation_entry_risk_denied",
    )
    replay_denied = _first_event_payload(
        replay_records,
        key="record_type",
        value="simulation_entry_risk_denied",
    )
    for label, payload in (("runtime", runtime_denied), ("replay", replay_denied)):
        if payload is None:
            failures.append(f"{label} risk denied event missing")
            continue
        expected = {
            "product_id": "BTC-USD",
            "market_ticker": "KXBTC15M-OLD",
            "direction": "up",
            "confidence": 70,
            "reason": "risk_kill_switch_active",
            "entry_price": "0.460",
            "current_exposure_dollars": "0",
            "realized_daily_pnl_dollars": "0",
        }
        for key, value in expected.items():
            if payload.get(key) != value:
                failures.append(f"{label} risk denied {key}={payload.get(key)} expected={value}")
    return failures


def _validate_live_order_candidate_logged() -> list[str]:
    runner, state = _build_runner(live_order_candidate_events=True)
    results = runner.run_cycles(1)
    failures: list[str] = []
    if len(results) != 1:
        failures.append(f"live order candidate cycle count={len(results)}")
        return failures
    if results[0].status.mode != "simulation":
        failures.append(f"live order candidate mode={results[0].status.mode}")
    if state.log_written_ref is None:
        return ["live order candidate missing runtime path"]
    payload = _first_event_payload(
        _jsonl_records(state.log_written_ref),
        key="event_type",
        value="live_order_candidate",
    )
    if payload is None:
        return ["live order candidate log missing"]
    expected = {
        "ticker": "KXBTC15M-OLD",
        "side": "yes",
        "price_dollars": "0.460",
        "count": 6,
        "stake_dollars": "3.00",
        "confidence": 70,
        "simulation_position_id": "sim-0001",
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            failures.append(f"live order candidate {key}={payload.get(key)} expected={value}")
    return failures


def _validate_live_order_intent_skip_logged() -> list[str]:
    runner, state = _build_runner(live_order_intent_skip_events=True)
    results = runner.run_cycles(1)
    failures: list[str] = []
    if len(results) != 1:
        failures.append(f"live order skip cycle count={len(results)}")
        return failures
    if results[0].status.mode != "simulation":
        failures.append(f"live order skip mode={results[0].status.mode}")
    if state.log_written_ref is None:
        return ["live order skip missing runtime path"]
    payload = _first_event_payload(
        _jsonl_records(state.log_written_ref),
        key="event_type",
        value="live_order_intent_skipped",
    )
    if payload is None:
        return ["live order intent skipped log missing"]
    expected = {
        "reason": "intent_unavailable",
        "product_id": "BTC-USD",
        "market_ticker": "KXBTC15M-OLD",
        "simulation_position_id": "sim-0001",
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            failures.append(f"live order skip {key}={payload.get(key)} expected={value}")
    return failures


def _validate_live_runner_disabled_does_not_submit() -> list[str]:
    coordinator = _FakeLiveExecutionCoordinator(intents=(_approved_intent("sim-0001"),))
    runner, _ = _build_runner(
        live_order_candidate_events=True,
        live_execution_coordinator=coordinator,
    )
    results = runner.run_cycles(1)
    failures: list[str] = []
    if len(results) != 1:
        failures.append(f"live runner disabled cycle count={len(results)}")
    if coordinator.submit_calls:
        failures.append(f"live runner disabled submit calls={len(coordinator.submit_calls)}")
    if results and results[0].status.mode != "simulation":
        failures.append(f"live runner disabled mode={results[0].status.mode}")
    return failures


def _validate_live_runner_no_intents_logged() -> list[str]:
    coordinator = _FakeLiveExecutionCoordinator(intents=())
    runner, state = _build_runner(
        live_flags_present=True,
        live_runner_execution_enabled=True,
        live_execution_coordinator=coordinator,
    )
    results = runner.run_cycles(1)
    failures: list[str] = []
    if len(results) != 1:
        failures.append(f"live runner no intents cycle count={len(results)}")
        return failures
    if coordinator.submit_calls:
        failures.append(f"live runner no intents submit calls={len(coordinator.submit_calls)}")
    if state.log_written_ref is None:
        return failures + ["live runner no intents missing runtime path"]
    if _first_event_payload(
        _jsonl_records(state.log_written_ref),
        key="event_type",
        value="live_runner_no_intents",
    ) is None:
        failures.append("live runner no intents log missing")
    return failures


def _validate_live_runner_enabled_submits_one_intent() -> list[str]:
    intents = (_approved_intent("sim-0001"), _approved_intent("sim-0002"))
    coordinator = _FakeLiveExecutionCoordinator(intents=intents)
    runner, state = _build_runner(
        live_flags_present=True,
        live_runner_execution_enabled=True,
        live_order_candidate_events=True,
        live_execution_coordinator=coordinator,
    )
    results = runner.run_cycles(1)
    failures: list[str] = []
    if len(results) != 1:
        failures.append(f"live runner enabled cycle count={len(results)}")
        return failures
    if len(coordinator.submit_calls) != 1:
        failures.append(f"live runner enabled submit calls={len(coordinator.submit_calls)}")
    elif coordinator.submit_calls[0].simulation_position_id != "sim-0001":
        failures.append(
            "live runner enabled submitted "
            f"{coordinator.submit_calls[0].simulation_position_id}"
        )
    if not results[0].status.live_flags_present:
        failures.append("live runner enabled did not report live_flags_present")
    if coordinator.contract_process_calls != 1:
        failures.append(
            "live runner enabled contract process calls="
            f"{coordinator.contract_process_calls}"
        )
    if state.log_written_ref is None:
        return failures + ["live runner enabled missing runtime path"]
    records = _jsonl_records(state.log_written_ref)
    if _first_event_payload(
        records,
        key="event_type",
        value="live_runner_submission_attempted",
    ) is None:
        failures.append("live runner submission attempted log missing")
    if _first_event_payload(
        records,
        key="event_type",
        value="live_runner_submission_completed",
    ) is None:
        failures.append("live runner submission completed log missing")
    return failures


def _validate_live_fast_scan_uses_cache_only_path() -> list[str]:
    coordinator = _FakeLiveExecutionCoordinator(intents=(_approved_intent("sim-0001"),))
    runner, state = _build_runner(
        live_flags_present=True,
        live_runner_execution_enabled=True,
        live_fast_scan_enabled=True,
        live_execution_coordinator=coordinator,
        time_fn=lambda: 100.0,
    )
    results = runner.run_cycles(1)
    failures: list[str] = []
    if len(results) != 1:
        failures.append(f"live fast scan cycle count={len(results)}")
        return failures
    if state.kalshi_run_calls != 1 or state.crypto_run_calls != 1:
        failures.append(
            "live fast scan ingestion calls="
            f"{state.kalshi_run_calls}/{state.crypto_run_calls}"
        )
    if coordinator.contract_process_calls != 2:
        failures.append(
            "live fast scan contract process calls="
            f"{coordinator.contract_process_calls}"
        )
    if len(coordinator.submit_calls) != 2:
        failures.append(f"live fast scan submit calls={len(coordinator.submit_calls)}")
    if coordinator.reconcile_calls != 1:
        failures.append(f"live fast scan reconcile calls={coordinator.reconcile_calls}")
    if coordinator.allow_reconciliation_values != [True, False]:
        failures.append(
            "live fast scan reconciliation flags="
            f"{coordinator.allow_reconciliation_values}"
        )
    if coordinator.scan_sources != ["normal_cycle", "fast_scan"]:
        failures.append(f"live fast scan sources={coordinator.scan_sources}")
    if state.log_written_ref is None:
        return failures + ["live fast scan missing runtime path"]
    records = _jsonl_records(state.log_written_ref)
    if _first_event_payload(
        records,
        key="event_type",
        value="live_fast_scan_started",
    ) is None:
        failures.append("live fast scan started log missing")
    skipped = _first_event_payload(
        records,
        key="event_type",
        value="live_fast_scan_skipped",
    )
    if skipped is None or skipped.get("reason") != "cooldown_active":
        failures.append(f"live fast scan cooldown log={skipped}")
    return failures


def _validate_live_runner_blocked_submission_logged() -> list[str]:
    coordinator = _FakeLiveExecutionCoordinator(
        intents=(_approved_intent("sim-0001"),),
        result_classification="blocked_by_safeguard",
        decision_reason="live_intent_not_risk_approved",
    )
    runner, state = _build_runner(
        live_flags_present=True,
        live_runner_execution_enabled=True,
        live_order_candidate_events=True,
        live_execution_coordinator=coordinator,
    )
    results = runner.run_cycles(1)
    failures: list[str] = []
    if len(results) != 1:
        failures.append(f"live runner blocked cycle count={len(results)}")
        return failures
    if len(coordinator.submit_calls) != 1:
        failures.append(f"live runner blocked submit calls={len(coordinator.submit_calls)}")
    if state.log_written_ref is None:
        return failures + ["live runner blocked missing runtime path"]
    payload = _first_event_payload(
        _jsonl_records(state.log_written_ref),
        key="event_type",
        value="live_runner_submission_blocked",
    )
    if payload is None:
        failures.append("live runner submission blocked log missing")
    elif payload.get("decision_reason") != "live_intent_not_risk_approved":
        failures.append(
            "live runner blocked reason="
            f"{payload.get('decision_reason')} expected=live_intent_not_risk_approved"
        )
    return failures


def _validate_live_runner_starts_without_simulation() -> list[str]:
    coordinator = _FakeLiveExecutionCoordinator(intents=(_approved_intent("live-0001"),))
    runner, state = _build_runner(
        live_flags_present=True,
        live_runner_execution_enabled=True,
        simulation_enabled=False,
        live_execution_coordinator=coordinator,
    )
    results = runner.run_cycles(1)
    failures: list[str] = []
    if len(results) != 1:
        failures.append(f"live runner no simulation cycle count={len(results)}")
        return failures
    if state.log_written_ref is None:
        return failures + ["live runner no simulation missing runtime path"]
    records = _jsonl_records(state.log_written_ref)
    if _first_event_payload(
        records,
        key="event_type",
        value="simulation_position_opened",
    ) is not None:
        failures.append("live runner no simulation wrote simulation trade event")
    if len(coordinator.submit_calls) != 1:
        failures.append(
            f"live runner no simulation submit calls={len(coordinator.submit_calls)}"
        )
    if coordinator.simulation_process_calls:
        failures.append(
            "live runner no simulation process_simulation calls="
            f"{coordinator.simulation_process_calls}"
        )
    if coordinator.contract_process_calls != 1:
        failures.append(
            "live runner no simulation process_contract calls="
            f"{coordinator.contract_process_calls}"
        )
    if results[0].status.open_position_count != 0:
        failures.append(
            "live runner no simulation open positions="
            f"{results[0].status.open_position_count}"
        )
    return failures


def _validate_live_runner_risk_does_not_require_live_validation() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        settings = replace(
            _settings(
                Path(temp_dir),
                live_flags_present=False,
                live_runner_execution_enabled=True,
                simulation_enabled=False,
                fail_fast_on_startup=True,
            ),
            env="prod",
            live_validation_enabled=False,
            live_trading_enabled=True,
            live_kill_switch_active=False,
        )
        risk_manager = _live_runner_risk_manager_from_settings(settings)
        decision = risk_manager.evaluate_live_order(
            KalshiOrderRequest(
                ticker="KXBTC15M-TEST",
                action="buy",
                side="yes",
                count=1,
                price_dollars=Decimal("0.50"),
                time_in_force="immediate_or_cancel",
                client_order_id="live-runner-test",
            )
        )
    if not decision.allow:
        return [f"live runner risk decision={decision.reason}"]
    return []


def _validate_live_runner_uses_live_risk_overrides() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        settings = replace(
            _settings(
                Path(temp_dir),
                live_flags_present=False,
                live_runner_execution_enabled=True,
                simulation_enabled=False,
                fail_fast_on_startup=True,
            ),
            env="prod",
            live_validation_enabled=False,
            live_trading_enabled=True,
            live_kill_switch_active=False,
            live_min_stake_dollars=Decimal("2"),
            live_max_stake_dollars=Decimal("4"),
            live_max_exposure_dollars=Decimal("2.50"),
            live_max_open_positions=1,
            live_max_contract_count=2,
        )
        risk_manager = _live_runner_risk_manager_from_settings(settings)
        entry_decision = risk_manager.evaluate_entry_risk(
            product_id="BTC-USD",
            confidence=40,
            open_position_count=0,
            current_exposure_dollars=Decimal("1"),
            realized_daily_pnl_dollars=Decimal("0"),
        )
        count_decision = risk_manager.evaluate_live_order(
            KalshiOrderRequest(
                ticker="KXBTC15M-TEST",
                action="buy",
                side="yes",
                count=3,
                price_dollars=Decimal("0.50"),
                time_in_force="immediate_or_cancel",
                client_order_id="live-runner-count-cap",
            )
        )
        open_position_decision = risk_manager.evaluate_entry_risk(
            product_id="BTC-USD",
            confidence=40,
            open_position_count=1,
            current_exposure_dollars=Decimal("0"),
            realized_daily_pnl_dollars=Decimal("0"),
        )
    failures: list[str] = []
    if entry_decision.allowed or entry_decision.reason != "risk_max_total_exposure":
        failures.append(f"live override entry decision={entry_decision}")
    if (
        open_position_decision.allowed
        or open_position_decision.reason != "risk_max_open_positions"
    ):
        failures.append(f"live override max open decision={open_position_decision}")
    if count_decision.allow or count_decision.reason != "order_count_exceeds_phase10_cap":
        failures.append(f"live override count decision={count_decision}")
    return failures


def _build_runner(
    *,
    stop_after_first_cycle: bool = False,
    live_flags_present: bool = False,
    live_runner_execution_enabled: bool = False,
    kalshi_error: str | None = None,
    kalshi_market_data: bool = True,
    fail_fast_on_startup: bool = True,
    simulation_trade_events: bool = False,
    simulation_risk_denied_events: bool = False,
    live_order_candidate_events: bool = False,
    live_order_intent_skip_events: bool = False,
    simulation_enabled: bool = True,
    live_fast_scan_enabled: bool = False,
    time_fn=None,  # noqa: ANN001
    live_execution_coordinator=None,  # noqa: ANN001
    expired_initial_market: bool = False,
):
    temp_dir = TemporaryDirectory()
    tmp_path = Path(temp_dir.name)
    cache = MarketStateCache()
    state = _FixtureState(
        temp_dir=temp_dir,
        cache=cache,
        expired_initial_market=expired_initial_market,
    )
    logger = StructuredLogger(log_directory=tmp_path / "logs", enabled=True)
    replay_engine = ReplayEngine(replay_directory=tmp_path / "replay", enabled=True)
    runner = KalshiBotRunner(
        settings=_settings(
            tmp_path,
            live_flags_present=live_flags_present,
            live_runner_execution_enabled=live_runner_execution_enabled,
            simulation_enabled=simulation_enabled,
            fail_fast_on_startup=fail_fast_on_startup,
            live_fast_scan_enabled=live_fast_scan_enabled,
        ),
        market_state_cache=cache,
        kalshi_ws_client=_FakeKalshiClient(
            state=state,
            error=kalshi_error,
            emit_market_data=kalshi_market_data,
        ),
        crypto_feed_client=_FakeCryptoFeedClient(state=state),
        bias_engine=_FakeBiasEngine(),
        contract_scanner=None,
        market_discovery=_FakeMarketDiscovery(state=state),
        simulation_engine=(
            _FakeSimulationEngine(
                stop_after_first_cycle=stop_after_first_cycle,
                runner_ref=None,
                trade_events=simulation_trade_events,
                risk_denied_events=simulation_risk_denied_events,
                live_order_candidate_events=live_order_candidate_events,
                live_order_intent_skip_events=live_order_intent_skip_events,
            )
            if simulation_enabled
            else None
        ),
        live_execution_coordinator=live_execution_coordinator or LiveExecutionCoordinator(
            settings=_settings(
                tmp_path,
                live_flags_present=live_flags_present,
                live_runner_execution_enabled=live_runner_execution_enabled,
                simulation_enabled=simulation_enabled,
                fail_fast_on_startup=fail_fast_on_startup,
                live_fast_scan_enabled=live_fast_scan_enabled,
            )
        ),
        logger=logger,
        replay_engine=replay_engine,
        sleep_fn=lambda _: None,
        time_fn=time_fn or (lambda: 100.0),
    )
    if runner._simulation_engine is not None:  # type: ignore[attr-defined]
        runner._simulation_engine._runner_ref = runner  # type: ignore[attr-defined]
    state.log_written_ref = logger.path
    state.replay_written_ref = replay_engine.path
    return runner, state


def _settings(
    tmp_path: Path,
    *,
    live_flags_present: bool,
    fail_fast_on_startup: bool,
    live_runner_execution_enabled: bool = False,
    simulation_enabled: bool = True,
    live_fast_scan_enabled: bool = False,
) -> KalshiSettings:
    return KalshiSettings(
        env="demo",
        api_base_url="https://demo-api.kalshi.co/trade-api/v2",
        ws_url="wss://demo-api.kalshi.co/trade-api/ws/v2",
        api_key_id="demo-key",
        private_key_pem="pem",
        private_key_path=None,
        private_key_passphrase=None,
        request_timeout_seconds=10.0,
        ws_market_tickers=(),
        ws_message_limit=1,
        ws_receive_timeout_seconds=30.0,
        ws_max_reconnect_attempts=1,
        ws_reconnect_initial_delay_seconds=1.0,
        ws_reconnect_max_delay_seconds=1.0,
        crypto_feed_ws_url="wss://advanced-trade-ws.coinbase.com",
        crypto_feed_products=("BTC-USD", "ETH-USD"),
        crypto_feed_message_limit=1,
        crypto_feed_receive_timeout_seconds=30.0,
        crypto_feed_max_reconnect_attempts=1,
        crypto_feed_reconnect_initial_delay_seconds=1.0,
        crypto_feed_reconnect_max_delay_seconds=1.0,
        log_directory=tmp_path / "logs",
        log_jsonl_enabled=True,
        replay_directory=tmp_path / "replay",
        replay_write_enabled=True,
        time_sync_max_drift_ms=1500,
        time_sync_log_results=True,
        latency_diagnostics_enabled=False,
        latency_diagnostics_sample_interval_ms=1000,
        latency_diagnostics_min_spot_move_bps=Decimal("5"),
        latency_diagnostics_max_depth_levels=3,
        bias_products=("BTC-USD", "ETH-USD"),
        bias_lookback_seconds=1800,
        bias_recent_window_seconds=60,
        bias_min_samples=20,
        bias_stale_data_seconds=15,
        bias_chop_threshold_bps=10,
        bias_impulse_min_abs_bps=Decimal("15"),
        contract_scanner_product_markets={},
        auto_market_discovery_enabled=True,
        crypto_market_series={
            "BTC-USD": ("KXBTC15M", "KXBTC30M"),
            "ETH-USD": ("KXETH15M", "KXETH30M"),
        },
        market_discovery_refresh_cycles=2,
        simulation_enabled=simulation_enabled,
        simulation_max_new_positions_per_evaluation=1,
        simulation_position_id_prefix="sim",
        simulation_exit_enabled=True,
        simulation_allow_same_pass_reentry=False,
        risk_account_balance_dollars=Decimal("10"),
        risk_min_percent_per_trade=Decimal("0.01"),
        risk_max_percent_per_trade=Decimal("0.03"),
        risk_min_stake_dollars=Decimal("0.10"),
        risk_max_stake_dollars=Decimal("3"),
        risk_max_open_positions=2,
        risk_max_total_exposure_dollars=Decimal("10"),
        risk_daily_loss_limit_dollars=Decimal("5"),
        risk_kill_switch_active=False,
        live_validation_enabled=live_flags_present,
        live_validation_env="prod" if live_flags_present else "demo",
        live_validation_ticker=None,
        live_validation_action=None,
        live_validation_side=None,
        live_validation_count=1,
        live_validation_price_dollars=None,
        live_validation_time_in_force="immediate_or_cancel",
        live_validation_poll_attempts=1,
        live_validation_poll_interval_seconds=1.0,
        live_validation_client_order_id_prefix="live-smoke",
        live_trading_enabled=live_flags_present,
        live_kill_switch_active=False,
        live_runner_execution_enabled=live_runner_execution_enabled,
        live_max_exposure_dollars=Decimal("10"),
        live_min_stake_dollars=Decimal("0.10"),
        live_max_stake_dollars=Decimal("3"),
        live_max_open_positions=2,
        live_max_contract_count=1000,
        live_profit_capture_enabled=False,
        live_profit_capture_price=Decimal("0.99"),
        live_trailing_stop_enabled=False,
        live_trailing_stop_distance=Decimal("0.05"),
        live_entry_end_window_only=False,
        live_entry_end_window_minutes=5,
        live_entry_min_remaining_seconds=0,
        live_entry_segment_pacing_enabled=False,
        live_entry_segment_max_10_to_5=1,
        live_entry_segment_max_5_to_3=1,
        live_entry_segment_max_3_to_1=1,
        live_entry_segment_max_final_1=1,
        live_fast_scan_enabled=live_fast_scan_enabled,
        live_fast_scan_interval_seconds=2.0,
        live_fast_scan_cooldown_seconds=5.0,
        live_reversal_cross_hold_enabled=True,
        live_reversal_cross_hold_seconds=60,
        live_mid_price_tightening_enabled=True,
        live_mid_price_min=Decimal("0.50"),
        live_mid_price_max=Decimal("0.70"),
        live_max_open_positions_per_product=2,
        live_max_entries_per_product_per_session=2,
        live_composite_quality_filter_enabled=True,
        live_composite_max_entry_price=Decimal("0.70"),
        live_composite_low_price_max=Decimal("0.30"),
        live_composite_allowed_segments=("10_to_5", "5_to_3"),
        live_composite_require_trend=True,
        live_composite_require_itm=True,
        live_composite_block_needs_cross=True,
        live_reversal_max_entry_price=Decimal("0.10"),
        live_block_needs_cross=True,
        live_max_required_bps_per_minute=Decimal("0.25"),
        live_outside_end_window_exception_enabled=False,
        live_outside_end_window_max_price=Decimal("0.30"),
        live_ev_filter_enabled=True,
        live_min_expected_value=Decimal("0.00"),
        live_ev_price_max_itm_no_cross=Decimal("0.70"),
        live_ev_price_max_needs_cross=Decimal("0.30"),
        live_ev_required_bps_max=Decimal("0.25"),
        live_ev_allowed_segments=("10_to_5", "5_to_3"),
        live_ev_conservative_allowed_segments=("10_to_5", "5_to_3", "3_to_1"),
        live_ev_allow_reversal=False,
        live_ev_candidate_a_win_probability=Decimal("0.87"),
        live_ev_candidate_b_win_probability=Decimal("0.92"),
        live_product_blocklist=(),
        live_conditional_high_price_pass_enabled=True,
        live_conditional_max_premium_over_midpoint=Decimal("0.08"),
        live_conditional_max_spread=Decimal("0.15"),
        live_conditional_max_scanner_premium=Decimal("0.12"),
        live_conditional_allow_extreme_asymmetry=False,
        live_conditional_allow_high_price_ceiling_bypass=False,
        live_conditional_high_price_ceiling_max=Decimal("0.70"),
        live_ev_timing_bypass_enabled=True,
        live_ev_extra_entries_per_product_per_session=0,
        live_ev_extra_open_positions_per_product=0,
        live_quiet_continuation_enabled=False,
        runner_enabled=True,
        runner_loop_interval_seconds=5.0 if live_fast_scan_enabled else 0.001,
        runner_status_log_every_n_cycles=1,
        runner_fail_fast_on_startup=fail_fast_on_startup,
        runner_max_cycles=None,
    )


class _FakeKalshiClient:
    def __init__(
        self,
        *,
        state: "_FixtureState",
        error: str | None = None,
        emit_market_data: bool = True,
    ) -> None:
        self._state = state
        self._error = error
        self._emit_market_data = emit_market_data

    async def run(self, *, market_tickers, message_limit):  # noqa: ANN001
        self._state.kalshi_run_calls += 1
        subscribed_tickers = tuple(dict.fromkeys(market_tickers))
        self._state.subscribed_tickers.append(subscribed_tickers)
        if self._error is not None:
            raise RuntimeError(self._error)
        if self._emit_market_data:
            for index, market_ticker in enumerate(subscribed_tickers, start=1):
                self._state.cache.replace_orderbook(
                    market_ticker=market_ticker,
                    yes_levels=(("0.44", "100"),),
                    no_levels=(("0.52", "100"),),
                    sid=1,
                    seq=index,
                )
            return _RunResult(
                messages_received=message_limit + 1,
                market_data_messages=message_limit,
                subscription_messages=1,
                subscribed_market_tickers=subscribed_tickers,
            )
        return _RunResult(
            messages_received=1,
            market_data_messages=0,
            subscription_messages=1,
            timed_out=True,
            subscribed_market_tickers=subscribed_tickers,
        )


class _FakeCryptoFeedClient:
    def __init__(self, *, state: "_FixtureState") -> None:
        self._state = state

    async def run(self, *, message_limit):  # noqa: ANN001
        self._state.crypto_run_calls += 1
        return _RunResult(messages_received=message_limit)

    def snapshot(self):
        return _FakeCryptoSnapshot()


class _FakeBiasEngine:
    def snapshot(self):
        return BiasSnapshot(products={})

    def ingest(self, snapshot):  # noqa: ANN001
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
                    lookback_return_bps=Decimal("100"),
                    recent_return_bps=Decimal("20"),
                    observation_count=25,
                    as_of="2026-04-23T12:00:00+00:00",
                ),
                "ETH-USD": BiasState(
                    product_id="ETH-USD",
                    direction="up",
                    confidence=70,
                    structure="trend",
                    risk_flags=BiasRiskFlags(
                        insufficient_history=False,
                        stale_data=False,
                        time_sync_failed=False,
                    ),
                    latest_price=Decimal("2000"),
                    lookback_return_bps=Decimal("100"),
                    recent_return_bps=Decimal("20"),
                    observation_count=25,
                    as_of="2026-04-23T12:00:00+00:00",
                ),
            }
        )


class _FakeMarketDiscovery:
    def __init__(self, *, state: "_FixtureState") -> None:
        self._state = state

    def discover(self) -> CryptoMarketDiscoverySnapshot:
        self._state.discovery_calls += 1
        now = datetime.now(timezone.utc)
        first_close_time = (
            _iso(now - timedelta(minutes=1))
            if self._state.expired_initial_market
            else _iso(now + timedelta(minutes=5))
        )
        if self._state.discovery_calls == 1:
            return _discovery_snapshot(
                {"BTC-USD": ("KXBTC15M-OLD",)},
                close_time=first_close_time,
            )
        return _discovery_snapshot(
            {
                "BTC-USD": ("KXBTC15M-NEW",),
                "ETH-USD": ("KXETH15M-NEW",),
            },
            close_time=_iso(now + timedelta(minutes=10)),
        )


class _FakeSimulationEngine:
    def __init__(
        self,
        *,
        stop_after_first_cycle: bool,
        runner_ref,  # noqa: ANN001
        trade_events: bool,
        risk_denied_events: bool,
        live_order_candidate_events: bool,
        live_order_intent_skip_events: bool,
    ) -> None:
        self._cycle = 0
        self._runner_ref = runner_ref
        self._stop_after_first_cycle = stop_after_first_cycle
        self._trade_events = trade_events
        self._risk_denied_events = risk_denied_events
        self._live_order_candidate_events = live_order_candidate_events
        self._live_order_intent_skip_events = live_order_intent_skip_events
        self._latest = SimulationSnapshot(
            open_positions={},
            closed_positions=(),
            decisions=(),
            evaluation_count=0,
        )

    def evaluate(self, scan_snapshot):  # noqa: ANN001
        self._cycle += 1
        if self._trade_events:
            self._latest = self._trade_event_snapshot()
        elif self._risk_denied_events:
            self._latest = self._risk_denied_event_snapshot()
        elif self._live_order_candidate_events:
            self._latest = self._live_order_candidate_snapshot()
        elif self._live_order_intent_skip_events:
            self._latest = self._live_order_intent_skip_snapshot()
        else:
            self._latest = SimulationSnapshot(
                open_positions={"sim-0001": object()} if self._cycle >= 1 else {},
                closed_positions=(),
                decisions=(),
                evaluation_count=self._cycle,
            )
        if self._stop_after_first_cycle and self._cycle == 1 and self._runner_ref is not None:
            self._runner_ref.stop()
        return self._latest

    def snapshot(self) -> SimulationSnapshot:
        return self._latest

    def _trade_event_snapshot(self) -> SimulationSnapshot:
        opened = SimulatedPosition(
            position_id="sim-0001",
            product_id="BTC-USD",
            market_ticker="KXBTC15M-OLD",
            direction="up",
            structure="trend",
            confidence=70,
            entry_price=Decimal("0.460"),
            latest_price=Decimal("0.460"),
            stake_dollars=Decimal("0.20"),
            status="open",
            opened_at="2026-04-23T12:00:03+00:00",
            updated_at="2026-04-23T12:00:03+00:00",
            update_count=0,
        )
        if self._cycle == 1:
            return SimulationSnapshot(
                open_positions={opened.position_id: opened},
                closed_positions=(),
                decisions=(
                    SimulationDecision(
                        action="open_position",
                        position_id=opened.position_id,
                        product_id=opened.product_id,
                        market_ticker=opened.market_ticker,
                        reason=None,
                    ),
                ),
                evaluation_count=self._cycle,
            )

        closed = ClosedSimulatedPosition(
            position_id=opened.position_id,
            product_id=opened.product_id,
            market_ticker=opened.market_ticker,
            direction=opened.direction,
            structure=opened.structure,
            confidence=opened.confidence,
            entry_price=opened.entry_price,
            exit_price=Decimal("0.490"),
            stake_dollars=opened.stake_dollars,
            status="closed",
            opened_at=opened.opened_at,
            closed_at="2026-04-23T12:01:03+00:00",
            updated_at=opened.updated_at,
            update_count=opened.update_count,
            exit_reason="direction_conflict",
        )
        return SimulationSnapshot(
            open_positions={},
            closed_positions=(closed,),
            decisions=(
                SimulationDecision(
                    action="close_position",
                    position_id=closed.position_id,
                    product_id=closed.product_id,
                    market_ticker=closed.market_ticker,
                    reason=closed.exit_reason,
                ),
            ),
            evaluation_count=self._cycle,
        )


    def _live_order_candidate_snapshot(self) -> SimulationSnapshot:
        opened = self._opened_position(stake_dollars=Decimal("3.00"))
        return SimulationSnapshot(
            open_positions={opened.position_id: opened},
            closed_positions=(),
            decisions=(
                SimulationDecision(
                    action="open_position",
                    position_id=opened.position_id,
                    product_id=opened.product_id,
                    market_ticker=opened.market_ticker,
                    reason=None,
                ),
            ),
            evaluation_count=self._cycle,
        )


    def _live_order_intent_skip_snapshot(self) -> SimulationSnapshot:
        opened = self._opened_position(stake_dollars=Decimal("0.20"))
        return SimulationSnapshot(
            open_positions={opened.position_id: opened},
            closed_positions=(),
            decisions=(
                SimulationDecision(
                    action="open_position",
                    position_id=opened.position_id,
                    product_id=opened.product_id,
                    market_ticker=opened.market_ticker,
                    reason=None,
                ),
            ),
            evaluation_count=self._cycle,
        )


    def _opened_position(self, *, stake_dollars: Decimal) -> SimulatedPosition:
        return SimulatedPosition(
            position_id="sim-0001",
            product_id="BTC-USD",
            market_ticker="KXBTC15M-OLD",
            direction="up",
            structure="trend",
            confidence=70,
            entry_price=Decimal("0.460"),
            latest_price=Decimal("0.460"),
            stake_dollars=stake_dollars,
            status="open",
            opened_at="2026-04-23T12:00:03+00:00",
            updated_at="2026-04-23T12:00:03+00:00",
            update_count=0,
        )


    def _risk_denied_event_snapshot(self) -> SimulationSnapshot:
        return SimulationSnapshot(
            open_positions={},
            closed_positions=(),
            decisions=(
                SimulationDecision(
                    action="skip_entry",
                    position_id=None,
                    product_id="BTC-USD",
                    market_ticker="KXBTC15M-OLD",
                    reason="risk_kill_switch_active",
                    details={
                        "direction": "up",
                        "confidence": 70,
                        "entry_price": Decimal("0.460"),
                        "current_exposure_dollars": Decimal("0"),
                        "realized_daily_pnl_dollars": Decimal("0"),
                    },
                ),
            ),
            evaluation_count=self._cycle,
        )


def _approved_intent(position_id: str) -> LiveOrderIntent:
    return LiveOrderIntent(
        product_id="BTC-USD",
        ticker="KXBTC15M-OLD",
        action="buy",
        side="yes",
        price_dollars=Decimal("0.460"),
        count=1,
        client_order_id=f"sim-live-{position_id}",
        stake_dollars=Decimal("0.46"),
        direction="up",
        confidence=70,
        simulation_position_id=position_id,
        risk_approved=True,
        risk_approval_source="simulation_entry_risk_gate",
    )


class _FakeLiveExecutionCoordinator:
    def __init__(
        self,
        *,
        intents: tuple[LiveOrderIntent, ...],
        result_classification: str = "submitted",
        decision_reason: str | None = None,
    ) -> None:
        self._intents = intents
        self._result_classification = result_classification
        self._decision_reason = decision_reason
        self.process_calls = 0
        self.simulation_process_calls = 0
        self.contract_process_calls = 0
        self.exit_process_calls = 0
        self.reconcile_calls = 0
        self.allow_reconciliation_values: list[bool] = []
        self.scan_sources: list[str] = []
        self.submit_calls: list[LiveOrderIntent] = []

    def process_simulation_snapshot(self, simulation_snapshot):  # noqa: ANN001
        self.process_calls += 1
        self.simulation_process_calls += 1
        return self._intents

    def process_contract_scan_snapshot(
        self,
        contract_scan_snapshot,  # noqa: ANN001
        *,
        cycle_number=None,
        market_snapshot=None,  # noqa: ANN001,ARG002
        allow_reconciliation=True,  # noqa: ANN001,ARG002
        scan_source="normal_cycle",  # noqa: ANN001,ARG002
    ):
        self.process_calls += 1
        self.contract_process_calls += 1
        self.allow_reconciliation_values.append(bool(allow_reconciliation))
        self.scan_sources.append(scan_source)
        return self._intents

    def process_profit_capture_exits(
        self,
        market_snapshot,  # noqa: ANN001,ARG002
        *,
        cycle_number=None,  # noqa: ANN001,ARG002
    ):
        self.exit_process_calls += 1
        return ()

    def reconcile_live_positions(
        self,
        *,
        cycle_number=None,  # noqa: ANN001,ARG002
        reason="normal_cycle",  # noqa: ANN001,ARG002
    ):
        self.reconcile_calls += 1
        return False

    def submit_live_order(self, intent: LiveOrderIntent):
        self.submit_calls.append(intent)
        blocked = self._result_classification == "blocked_by_safeguard"
        return _FakeLiveSubmissionResult(
            classification=self._result_classification,
            decision_reason=self._decision_reason,
            order_placed=not blocked,
            order_id=None if blocked else "order-1",
            poll_attempts_used=0 if blocked else 1,
        )


@dataclass(frozen=True)
class _FakeLiveSubmissionResult:
    classification: str
    decision_reason: str | None
    order_placed: bool
    order_id: str | None
    poll_attempts_used: int


@dataclass(frozen=True)
class _RunResult:
    messages_received: int
    market_data_messages: int = 0
    subscription_messages: int = 0
    timed_out: bool = False
    subscribed_market_tickers: tuple[str, ...] = ()


class _FakeDiscoveryKalshiClient:
    def get_markets(self, **kwargs):  # noqa: ANN003
        now = datetime.now(timezone.utc)
        return KalshiMarketPage(
            markets=(
                _market_summary(
                    ticker="KXBTC15M-TEST",
                    status="active",
                    open_time=_iso(now - timedelta(minutes=5)),
                    close_time=_iso(now + timedelta(minutes=5)),
                    expiration_time=_iso(now + timedelta(minutes=5)),
                    target_price=Decimal("70000"),
                    target_price_source="target_price",
                ),
                _market_summary(
                    ticker="KXBTC15M-EXPIRED",
                    status="active",
                    open_time=_iso(now - timedelta(minutes=20)),
                    close_time=_iso(now - timedelta(minutes=5)),
                    expiration_time=_iso(now - timedelta(minutes=5)),
                ),
            ),
            cursor=None,
        )


class _FakeCryptoSnapshot:
    def __init__(self) -> None:
        self.products = {"BTC-USD": object(), "ETH-USD": object()}


class _FixtureState:
    def __init__(
        self,
        *,
        temp_dir: TemporaryDirectory,
        cache: MarketStateCache,
        expired_initial_market: bool = False,
    ) -> None:
        self._temp_dir = temp_dir
        self.cache = cache
        self.expired_initial_market = expired_initial_market
        self.kalshi_run_calls = 0
        self.crypto_run_calls = 0
        self.discovery_calls = 0
        self.subscribed_tickers: list[tuple[str, ...]] = []
        self.log_written_ref: Path | None = None
        self.replay_written_ref: Path | None = None

    @property
    def subscribed_tickers_by_call(self) -> tuple[tuple[str, ...], ...]:
        return tuple(self.subscribed_tickers)

    @property
    def log_written(self) -> bool:
        return self.log_written_ref is not None and self.log_written_ref.exists()

    @property
    def replay_written(self) -> bool:
        return self.replay_written_ref is not None and self.replay_written_ref.exists()


def _market_diagnostic_matches(
    diagnostic,  # noqa: ANN001
    *,
    market_ticker_present: bool,
    bid_present: bool,
    ask_present: bool,
) -> bool:
    return (
        diagnostic is not None
        and diagnostic.market_ticker_present is market_ticker_present
        and diagnostic.bid_present is bid_present
        and diagnostic.ask_present is ask_present
    )


def _jsonl_records(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _first_event_payload(
    records: list[dict[str, object]],
    *,
    key: str,
    value: str,
) -> dict[str, object] | None:
    for record in records:
        if record.get(key) != value:
            continue
        payload = record.get("payload")
        if isinstance(payload, dict):
            return payload
    return None


def _event_payloads(
    records: list[dict[str, object]],
    *,
    key: str,
    value: str,
) -> tuple[dict[str, object], ...]:
    payloads: list[dict[str, object]] = []
    for record in records:
        if record.get(key) != value:
            continue
        payload = record.get("payload")
        if isinstance(payload, dict):
            payloads.append(payload)
    return tuple(payloads)


def _discovery_snapshot(
    product_markets: dict[str, tuple[str, ...]],
    *,
    close_time: str,
) -> CryptoMarketDiscoverySnapshot:
    discovered = tuple(
        DiscoveredCryptoMarket(
            product_id=product_id,
            series_ticker=market_ticker.split("-", 1)[0],
            market_ticker=market_ticker,
            close_time=close_time,
            open_time="2026-04-23T12:00:00+00:00",
            expiration_time=close_time,
        )
        for product_id, market_tickers in product_markets.items()
        for market_ticker in market_tickers
    )
    return CryptoMarketDiscoverySnapshot(
        product_markets=product_markets,
        discovered_markets=discovered,
    )


def _market_summary(
    *,
    ticker: str,
    status: str | None,
    open_time: str,
    close_time: str,
    expiration_time: str,
    target_price: Decimal | None = None,
    target_price_source: str | None = None,
) -> KalshiMarketSummary:
    return KalshiMarketSummary(
        ticker=ticker,
        event_ticker=None,
        status=status,
        open_time=open_time,
        close_time=close_time,
        expiration_time=expiration_time,
        latest_expiration_time=expiration_time,
        yes_bid_dollars=Decimal("0.44"),
        yes_ask_dollars=Decimal("0.48"),
        target_price=target_price,
        target_price_source=target_price_source,
    )


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
