"""Validate Phase F2 dry-run live execution coordinator behavior."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi_bot.contracts.contract_scorer import ContractScore  # noqa: E402
from kalshi_bot.contracts.contract_scanner import (  # noqa: E402
    ContractScanSnapshot,
    ScannedContract,
    SkippedContract,
)
from kalshi_bot.execution.execution_engine import (  # noqa: E402
    SimulatedPosition,
    SimulationDecision,
    SimulationSnapshot,
)
from kalshi_bot.execution.live_execution_coordinator import LiveExecutionCoordinator  # noqa: E402
from kalshi_bot.market.market_state_cache import (  # noqa: E402
    MarketStateSnapshot,
    OrderBookState,
    TickerState,
)
from kalshi_bot.risk.risk_manager import RiskDecision  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate Phase F2 live execution coordinator behavior."
    )
    parser.parse_args()

    failures: list[str] = []
    failures.extend(_validate_open_position_produces_intent())
    failures.extend(_validate_up_down_mapping())
    failures.extend(_validate_count_below_one_logs_skip())
    failures.extend(_validate_candidate_log_payload())
    failures.extend(_validate_direct_contract_scan_creates_live_intent())
    failures.extend(_validate_direct_contract_scan_midpoint_fallback())
    failures.extend(_validate_executable_price_below_minimum_skip())
    failures.extend(_validate_executable_price_above_maximum_skip())
    failures.extend(_validate_executable_price_above_premium_skip())
    failures.extend(_validate_contextual_high_price_sustained_itm_allows())
    failures.extend(_validate_contextual_high_price_needs_cross_blocks())
    failures.extend(_validate_extreme_high_price_blocks())
    failures.extend(_validate_contextual_high_price_premium_blocks())
    failures.extend(_validate_reversal_cross_hold_blocks_fresh_cross())
    failures.extend(_validate_reversal_cross_hold_allows_after_hold())
    failures.extend(_validate_mid_price_weak_reversal_blocks())
    failures.extend(_validate_mid_price_confirmed_trend_allows())
    failures.extend(_validate_composite_candidate_a_allows())
    failures.extend(_validate_ev_candidate_a_allows_five_to_three())
    failures.extend(_validate_ev_no_candidate_a_side_aware_allows())
    failures.extend(_validate_ev_no_candidate_a_needs_cross_blocks())
    failures.extend(_validate_ev_no_candidate_a_required_bps_blocks())
    failures.extend(_validate_ev_no_candidate_a_missing_liquidity_blocks())
    failures.extend(_validate_ev_no_candidate_a_hard_cost_ceiling_blocks())
    failures.extend(_validate_ev_candidate_a_blocks_needs_cross())
    failures.extend(_validate_ev_conditional_scanner_premium_bypass())
    failures.extend(_validate_composite_low_price_candidate_allows())
    failures.extend(_validate_reversal_price_blocks_confirmed_hold())
    failures.extend(_validate_needs_cross_blocks_by_default())
    failures.extend(_validate_required_bps_per_minute_blocks())
    failures.extend(_validate_far_itm_trend_not_distance_blocked())
    failures.extend(_validate_outside_end_window_blocks_by_default())
    failures.extend(_validate_outside_end_window_exception_allows_low_price_trend())
    failures.extend(_validate_zero_visible_liquidity_blocks())
    failures.extend(_validate_midpoint_fallback_price_below_minimum_skip())
    failures.extend(_validate_midpoint_fallback_price_above_maximum_skip())
    failures.extend(_validate_end_window_blocks_early_contract())
    failures.extend(_validate_end_window_allows_late_contract())
    failures.extend(_validate_end_window_skips_missing_close_time())
    failures.extend(_validate_stale_contract_close_time_blocks())
    failures.extend(_validate_direct_contract_scan_count_below_one_skip())
    failures.extend(_validate_flip_persistence_allows_same_direction())
    failures.extend(_validate_flip_persistence_blocks_recent_opposite_direction())
    failures.extend(_validate_flip_persistence_allows_itm_persistent_opposite_direction())
    failures.extend(_validate_same_side_retry_blocks_without_improvement())
    failures.extend(_validate_same_side_retry_allows_improved_feasibility())
    failures.extend(_validate_entry_segment_budget_blocks_overuse())
    failures.extend(_validate_product_session_cap_blocks_overuse())
    failures.extend(_validate_candidate_funnel_summary_logs_scanner_and_live_counts())

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1

    print("Phase F2 live execution coordinator checks succeeded.")
    return 0


def _validate_open_position_produces_intent() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        coordinator = _coordinator(Path(temp_dir))
        snapshot = _snapshot(
            _position(
                position_id="sim-0001",
                direction="up",
                stake_dollars=Decimal("3.00"),
                entry_price=Decimal("0.50"),
            )
        )
        intents = coordinator.process_simulation_snapshot(snapshot)
        if len(intents) != 1:
            return [f"intent count={len(intents)} expected=1"]
        intent = intents[0]
        if intent.ticker != "KXBTC15M-TEST" or intent.count != 6:
            return [f"intent ticker/count={intent.ticker}/{intent.count}"]
    return []


def _validate_up_down_mapping() -> list[str]:
    failures: list[str] = []
    with TemporaryDirectory() as temp_dir:
        coordinator = _coordinator(Path(temp_dir))
        up_intents = coordinator.process_simulation_snapshot(
            _snapshot(_position(position_id="sim-up", direction="up"))
        )
        down_intents = coordinator.process_simulation_snapshot(
            _snapshot(_position(position_id="sim-down", direction="down"))
        )
    if up_intents[0].side != "yes" or up_intents[0].action != "buy":
        failures.append(f"up mapping={up_intents[0].action}/{up_intents[0].side}")
    if down_intents[0].side != "no" or down_intents[0].action != "buy":
        failures.append(f"down mapping={down_intents[0].action}/{down_intents[0].side}")
    return failures


def _validate_count_below_one_logs_skip() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(temp_path)
        snapshot = _snapshot(
            _position(
                position_id="sim-small",
                stake_dollars=Decimal("0.20"),
                entry_price=Decimal("0.46"),
            )
        )
        intents = coordinator.process_simulation_snapshot(snapshot)
        if intents:
            return [f"small stake intents={intents} expected empty"]
        skipped = _first_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_order_intent_skipped",
        )
        if skipped is None:
            return ["small stake skip log missing"]
        if skipped.get("reason") != "intent_unavailable":
            return [f"small stake skip reason={skipped.get('reason')}"]
    return []


def _validate_candidate_log_payload() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(temp_path)
        snapshot = _snapshot(
            _position(
                position_id="sim-log",
                product_id="ETH-USD",
                market_ticker="KXETH15M-TEST",
                direction="down",
                confidence=82,
                stake_dollars=Decimal("4.00"),
                entry_price=Decimal("0.50"),
            )
        )
        coordinator.process_simulation_snapshot(snapshot)
        payload = _first_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_order_candidate",
        )
        if payload is None:
            return ["candidate log missing"]
        expected = {
            "ticker": "KXETH15M-TEST",
            "side": "no",
            "price_dollars": "0.50",
            "count": 8,
            "stake_dollars": "4.00",
            "confidence": 82,
            "simulation_position_id": "sim-log",
        }
        failures: list[str] = []
        for key, value in expected.items():
            if payload.get(key) != value:
                failures.append(f"candidate {key}={payload.get(key)} expected={value}")
        return failures


def _validate_direct_contract_scan_creates_live_intent() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            settings=_Settings(
                log_directory=temp_path,
                log_jsonl_enabled=True,
                live_composite_quality_filter_enabled=False,
            ),
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        market_snapshot = _market_snapshot(
            market_ticker="KXBTC15M-DIRECT",
            yes_bid=Decimal("0.09"),
            yes_ask=Decimal("0.10"),
            yes_bid_size=Decimal("50"),
            yes_ask_size=Decimal("10"),
            orderbook_seq=123,
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(
                _contract(
                    market_ticker="KXBTC15M-DIRECT",
                    midpoint=Decimal("0.10"),
                )
            ),
            cycle_number=42,
            market_snapshot=market_snapshot,
        )
        failures: list[str] = []
        if len(intents) != 1:
            failures.append(f"direct intent count={len(intents)} expected=1")
            return failures
        intent = intents[0]
        if intent.risk_approval_source != "live_entry_risk_gate":
            failures.append(f"direct risk source={intent.risk_approval_source}")
        if intent.price_dollars != Decimal("0.10"):
            failures.append(f"direct price={intent.price_dollars} expected=0.10")
        if intent.count != 30:
            failures.append(f"direct count={intent.count} expected=30")
        payload = _first_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_intent_created",
        )
        if payload is None:
            failures.append("direct live_intent_created log missing")
        else:
            expected = {
                "ticker": "KXBTC15M-DIRECT",
                "pricing_source": "executable_side_ask",
                "scanner_midpoint": "0.10",
                "intent_price_dollars": "0.10",
                "intent_count": 30,
                "intent_side": "yes",
                "structure": "trend",
                "impulse_detected": True,
                "impulse_direction": "up",
                "impulse_return_bps": "18.000",
                "recent_return_bps": "20.000",
                "lookback_return_bps": "25.000",
                "risk_flags": {
                    "insufficient_history": False,
                    "stale_data": False,
                    "time_sync_failed": False,
                },
                "bias_as_of": "2026-04-23T12:00:00+00:00",
                "target_price": "99.00",
                "target_price_source": "target_price",
                "current_spot_price": "100.00",
                "distance_to_target_bps": "-100.000",
                "time_remaining_seconds": 120,
                "required_bps_per_minute": "0.000",
                "side_currently_itm": True,
                "side_needs_cross": False,
                "feasibility_status": "currently_itm",
                "reversal_confirmation_status": "not_reversal",
                "trend_confirmation_status": "confirmed",
                "signal_conflict_flags": {"impulse_direction_conflict": False},
                "scanner_score_confidence": 70,
                "scanner_score_downgrade_reasons": [],
                "flip_persistence_status": "no_recent_entry",
                "contract_open_time": "2026-04-23T11:45:00+00:00",
                "yes_bid": "0.09",
                "yes_ask": "0.10",
                "executable_side_ask": "0.10",
                "executable_side_ask_size_fp": "10",
                "available_count_at_intent_price": "10",
                "orderbook_present": True,
                "orderbook_seq": 123,
            }
            for key, value in expected.items():
                if payload.get(key) != value:
                    failures.append(f"direct log {key}={payload.get(key)} expected={value}")
        return failures


def _validate_direct_contract_scan_midpoint_fallback() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            settings=_Settings(
                log_directory=temp_path,
                log_jsonl_enabled=True,
                live_composite_quality_filter_enabled=False,
                live_block_needs_cross=False,
                live_max_required_bps_per_minute=Decimal("1.00"),
            ),
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(
                _contract(
                    market_ticker="KXBTC15M-FALLBACK",
                    midpoint=Decimal("0.10"),
                )
            ),
            cycle_number=43,
        )
        failures: list[str] = []
        if len(intents) != 1:
            failures.append(f"fallback intent count={len(intents)} expected=1")
            return failures
        intent = intents[0]
        if intent.price_dollars != Decimal("0.10"):
            failures.append(f"fallback price={intent.price_dollars} expected=0.10")
        if intent.count != 30:
            failures.append(f"fallback count={intent.count} expected=30")
        payload = _first_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_intent_created",
        )
        if payload is None:
            failures.append("fallback live_intent_created log missing")
        elif payload.get("pricing_source") != "midpoint_fallback":
            failures.append(f"fallback pricing_source={payload.get('pricing_source')}")
        return failures


def _validate_executable_price_below_minimum_skip() -> list[str]:
    return _validate_execution_price_safety_skip(
        market_ticker="KXBTC15M-BELOW-MIN",
        midpoint=Decimal("0.10"),
        yes_bid=Decimal("0.08"),
        yes_ask=Decimal("0.09"),
        expected_reason="executable_price_below_minimum",
        expected_count=33,
        expected_intent_side="yes",
        expected_executable_side_ask="0.09",
    )


def _validate_executable_price_above_maximum_skip() -> list[str]:
    return _validate_execution_price_safety_skip(
        market_ticker="KXBTC15M-ABOVE-MAX",
        midpoint=Decimal("0.75"),
        yes_bid=Decimal("0.79"),
        yes_ask=Decimal("0.81"),
        expected_reason="contextual_high_price_requires_sustained_itm",
        expected_count=3,
        expected_intent_side="yes",
        expected_executable_side_ask="0.81",
    )


def _validate_executable_price_above_premium_skip() -> list[str]:
    return _validate_execution_price_safety_skip(
        market_ticker="KXBTC15M-PREMIUM",
        midpoint=Decimal("0.30"),
        yes_bid=Decimal("0.39"),
        yes_ask=Decimal("0.41"),
        expected_reason="executable_price_above_scanner_premium",
        expected_count=7,
        expected_intent_side="yes",
        expected_executable_side_ask="0.41",
    )


def _validate_contextual_high_price_sustained_itm_allows() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            settings=_Settings(
                log_directory=temp_path,
                log_jsonl_enabled=True,
                live_composite_quality_filter_enabled=False,
                live_block_needs_cross=False,
                live_max_required_bps_per_minute=Decimal("1.00"),
            ),
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        market_snapshot = _market_snapshot(
            market_ticker="KXBTC15M-HIGH-ALLOW",
            yes_bid=Decimal("0.82"),
            yes_ask=Decimal("0.85"),
            yes_bid_size=Decimal("10"),
            yes_ask_size=Decimal("10"),
            orderbook_seq=124,
        )
        contract = _contract(
            market_ticker="KXBTC15M-HIGH-ALLOW",
            midpoint=Decimal("0.83"),
            distance_to_target_bps=Decimal("-25.000"),
            required_bps_per_minute=Decimal("0.000"),
            side_currently_itm=True,
            side_needs_cross=False,
        )
        first = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(contract),
            cycle_number=60,
            market_snapshot=market_snapshot,
        )
        second = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(contract),
            cycle_number=61,
            market_snapshot=market_snapshot,
        )
        failures: list[str] = []
        if first:
            failures.append(f"first high-price intents={first} expected empty")
        if len(second) != 1:
            failures.append(f"second high-price intents={len(second)} expected=1")
            return failures
        if second[0].price_dollars != Decimal("0.85"):
            failures.append(f"high-price intent price={second[0].price_dollars}")
        payload = _last_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_intent_created",
        )
        if payload is None:
            failures.append("high-price allow intent log missing")
            return failures
        expected = {
            "contextual_high_price_status": "allowed_contextual_itm_high_price",
            "itm_persistence_status": "sustained_itm",
            "available_count_at_intent_price": "10",
            "spread_dollars": "0.03",
            "execution_premium_over_midpoint_dollars": "0.02",
        }
        for key, value in expected.items():
            if payload.get(key) != value:
                failures.append(f"high-price allow {key}={payload.get(key)} expected={value}")
        return failures


def _validate_contextual_high_price_needs_cross_blocks() -> list[str]:
    return _validate_execution_price_safety_skip(
        market_ticker="KXBTC15M-HIGH-NEEDS-CROSS",
        midpoint=Decimal("0.83"),
        yes_bid=Decimal("0.82"),
        yes_ask=Decimal("0.85"),
        expected_reason="contextual_high_price_needs_cross_blocked",
        expected_count=3,
        expected_intent_side="yes",
        expected_executable_side_ask="0.85",
        contract=_contract(
            market_ticker="KXBTC15M-HIGH-NEEDS-CROSS",
            midpoint=Decimal("0.83"),
            side_currently_itm=False,
            side_needs_cross=True,
            distance_to_target_bps=Decimal("4.000"),
            required_bps_per_minute=Decimal("0.800"),
            feasibility_status="needs_cross",
        ),
    )


def _validate_extreme_high_price_blocks() -> list[str]:
    return _validate_execution_price_safety_skip(
        market_ticker="KXBTC15M-EXTREME",
        midpoint=Decimal("0.94"),
        yes_bid=Decimal("0.94"),
        yes_ask=Decimal("0.95"),
        expected_reason="executable_price_extreme_asymmetry",
        expected_count=3,
        expected_intent_side="yes",
        expected_executable_side_ask="0.95",
    )


def _validate_contextual_high_price_premium_blocks() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        market_snapshot = _market_snapshot(
            market_ticker="KXBTC15M-HIGH-PREMIUM",
            yes_bid=Decimal("0.77"),
            yes_ask=Decimal("0.85"),
            yes_bid_size=Decimal("10"),
            yes_ask_size=Decimal("10"),
            orderbook_seq=125,
        )
        contract = _contract(
            market_ticker="KXBTC15M-HIGH-PREMIUM",
            midpoint=Decimal("0.79"),
            distance_to_target_bps=Decimal("-25.000"),
            required_bps_per_minute=Decimal("0.000"),
        )
        coordinator.process_contract_scan_snapshot(
            _contract_snapshot(contract),
            cycle_number=62,
            market_snapshot=market_snapshot,
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(contract),
            cycle_number=63,
            market_snapshot=market_snapshot,
        )
        failures: list[str] = []
        if intents:
            failures.append(f"premium block intents={intents} expected empty")
        payload = _last_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_order_intent_skipped",
        )
        if payload is None:
            failures.append("premium block skip log missing")
        elif payload.get("reason") != "contextual_high_price_premium_too_high":
            failures.append(f"premium block reason={payload.get('reason')}")
        return failures


def _validate_zero_visible_liquidity_blocks() -> list[str]:
    return _validate_execution_price_safety_skip(
        market_ticker="KXBTC15M-NO-LIQUIDITY",
        midpoint=Decimal("0.40"),
        yes_bid=Decimal("0.39"),
        yes_ask=Decimal("0.40"),
        yes_ask_size=Decimal("0"),
        expected_reason="executable_price_no_visible_liquidity",
        expected_count=7,
        expected_intent_side="yes",
        expected_executable_side_ask="0.40",
    )


def _validate_reversal_cross_hold_blocks_fresh_cross() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
            time_fn=lambda: 1000.0,
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(
                _contract(
                    market_ticker="KXBTC15M-REV-HOLD-BLOCK",
                    structure="reversal",
                    reversal_confirmation_status="confirmed",
                    trend_confirmation_status="not_trend",
                    side_currently_itm=True,
                    side_needs_cross=False,
                    distance_to_target_bps=Decimal("-2.000"),
                    required_bps_per_minute=Decimal("0.000"),
                    midpoint=Decimal("0.40"),
                )
            ),
            cycle_number=64,
        )
        failures: list[str] = []
        if intents:
            failures.append(f"reversal hold block intents={len(intents)} expected=0")
        payload = _last_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_order_intent_skipped",
        )
        if payload is None:
            failures.append("reversal hold block skip log missing")
            return failures
        if payload.get("reason") != "reversal_cross_hold_blocked":
            failures.append(f"reversal hold block reason={payload.get('reason')}")
        if payload.get("reversal_cross_hold_block_reason") != "reversal_cross_hold_waiting":
            failures.append(
                "reversal hold block detail="
                f"{payload.get('reversal_cross_hold_block_reason')}"
            )
        return failures


def _validate_reversal_cross_hold_allows_after_hold() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        now = {"value": 1000.0}
        coordinator = _coordinator(
            temp_path,
            settings=_Settings(
                log_directory=temp_path,
                log_jsonl_enabled=True,
                live_composite_quality_filter_enabled=False,
                live_reversal_max_entry_price=Decimal("0.99"),
            ),
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
            time_fn=lambda: now["value"],
        )
        contract = _contract(
            market_ticker="KXBTC15M-REV-HOLD-ALLOW",
            structure="reversal",
            reversal_confirmation_status="confirmed",
            trend_confirmation_status="not_trend",
            side_currently_itm=True,
            side_needs_cross=False,
            distance_to_target_bps=Decimal("-3.000"),
            required_bps_per_minute=Decimal("0.000"),
            midpoint=Decimal("0.40"),
        )
        coordinator.process_contract_scan_snapshot(
            _contract_snapshot(contract),
            cycle_number=65,
        )
        now["value"] = 1061.0
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(contract),
            cycle_number=66,
        )
        failures: list[str] = []
        if len(intents) != 1:
            failures.append(f"reversal hold allow intents={len(intents)} expected=1")
            return failures
        payload = _last_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_intent_created",
        )
        if payload is None:
            failures.append("reversal hold allow intent log missing")
            return failures
        if payload.get("reversal_cross_hold_status") != "confirmed":
            failures.append(
                "reversal hold allow status="
                f"{payload.get('reversal_cross_hold_status')}"
            )
        return failures


def _validate_mid_price_weak_reversal_blocks() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            settings=_Settings(
                log_directory=temp_path,
                log_jsonl_enabled=True,
                live_reversal_cross_hold_enabled=False,
            ),
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(
                _contract(
                    market_ticker="KXBTC15M-MID-REV-BLOCK",
                    structure="reversal",
                    reversal_confirmation_status="confirmed",
                    trend_confirmation_status="not_trend",
                    midpoint=Decimal("0.60"),
                )
            ),
            cycle_number=67,
            market_snapshot=None,
        )
        failures: list[str] = []
        if intents:
            failures.append(f"mid weak reversal intents={len(intents)} expected=0")
        payload = _last_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_order_intent_skipped",
        )
        if payload is None:
            failures.append("mid weak reversal skip log missing")
            return failures
        if payload.get("reason") != "mid_price_confirmation_required":
            failures.append(f"mid weak reversal reason={payload.get('reason')}")
        return failures


def _validate_mid_price_confirmed_trend_allows() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            settings=_Settings(
                log_directory=temp_path,
                log_jsonl_enabled=True,
                live_composite_max_entry_price=Decimal("0.70"),
                live_composite_quality_filter_enabled=False,
            ),
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(
                _contract(
                    market_ticker="KXBTC15M-MID-TREND-ALLOW",
                    midpoint=Decimal("0.60"),
                    structure="trend",
                    trend_confirmation_status="confirmed",
                )
            ),
            cycle_number=68,
            market_snapshot=None,
        )
        if len(intents) != 1:
            return [f"mid confirmed trend intents={len(intents)} expected=1"]
        payload = _last_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_intent_created",
        )
        if payload is None:
            return ["mid confirmed trend intent log missing"]
        if payload.get("mid_price_confirmation_status") != "allowed_confirmed_trend":
            return [
                "mid confirmed trend status="
                f"{payload.get('mid_price_confirmation_status')}"
            ]
        return []


def _validate_composite_candidate_a_allows() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            settings=_Settings(
                log_directory=temp_path,
                log_jsonl_enabled=True,
                live_ev_filter_enabled=True,
            ),
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        market_snapshot = _market_snapshot(
            market_ticker="KXBTC15M-COMP-A",
            yes_bid=Decimal("0.49"),
            yes_ask=Decimal("0.50"),
            yes_bid_size=Decimal("100"),
            yes_ask_size=Decimal("100"),
            orderbook_seq=700,
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(
                _contract(
                    market_ticker="KXBTC15M-COMP-A",
                    midpoint=Decimal("0.50"),
                    contract_close_time=_future_time(minutes=7),
                    contract_time_remaining_seconds=420,
                )
            ),
            cycle_number=69,
            market_snapshot=market_snapshot,
        )
        failures: list[str] = []
        if len(intents) != 1:
            return [f"composite candidate A intents={len(intents)} expected=1"]
        payload = _last_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_intent_created",
        )
        if payload is None:
            return ["composite candidate A intent log missing"]
        if payload.get("composite_quality_status") != "allowed_composite_quality":
            failures.append(
                "composite candidate A status="
                f"{payload.get('composite_quality_status')}"
            )
        if payload.get("entry_segment") != "10_to_5":
            failures.append(f"composite candidate A segment={payload.get('entry_segment')}")
        return failures


def _validate_ev_candidate_a_allows_five_to_three() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            settings=_Settings(
                log_directory=temp_path,
                log_jsonl_enabled=True,
                live_ev_filter_enabled=True,
            ),
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        market_snapshot = _market_snapshot(
            market_ticker="KXBTC15M-EV-A-5-3",
            yes_bid=Decimal("0.59"),
            yes_ask=Decimal("0.60"),
            yes_bid_size=Decimal("100"),
            yes_ask_size=Decimal("100"),
            orderbook_seq=701,
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(
                _contract(
                    market_ticker="KXBTC15M-EV-A-5-3",
                    midpoint=Decimal("0.58"),
                    contract_close_time=_future_time(minutes=4),
                    contract_time_remaining_seconds=240,
                )
            ),
            cycle_number=700,
            market_snapshot=market_snapshot,
        )
        if len(intents) != 1:
            return [f"ev candidate A intents={len(intents)} expected=1"]
        payload = _last_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_intent_created",
        )
        if payload is None:
            return ["ev candidate A intent log missing"]
        failures: list[str] = []
        if payload.get("ev_matched_candidate") != "candidate_a":
            failures.append(f"ev candidate A match={payload.get('ev_matched_candidate')}")
        if payload.get("entry_segment") != "5_to_3":
            failures.append(f"ev candidate A segment={payload.get('entry_segment')}")
        if payload.get("ev_filter_status") != "allowed":
            failures.append(f"ev candidate A status={payload.get('ev_filter_status')}")
        return failures


def _validate_ev_no_candidate_a_side_aware_allows() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            settings=_Settings(
                log_directory=temp_path,
                log_jsonl_enabled=True,
                live_ev_filter_enabled=True,
                live_composite_low_price_max=Decimal("0.05"),
                live_conditional_allow_high_price_ceiling_bypass=True,
                live_conditional_high_price_ceiling_max=Decimal("0.92"),
                live_conditional_max_premium_over_midpoint=Decimal("0.90"),
                live_conditional_max_scanner_premium=Decimal("0.90"),
            ),
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        market_snapshot = _market_snapshot(
            market_ticker="KXBTC15M-EV-NO-A",
            yes_bid=Decimal("0.09"),
            yes_ask=Decimal("0.15"),
            yes_bid_size=Decimal("100"),
            yes_ask_size=Decimal("100"),
            orderbook_seq=704,
        )
        contract = _contract(
            market_ticker="KXBTC15M-EV-NO-A",
            direction="down",
            midpoint=Decimal("0.12"),
            recent_return_bps=Decimal("-20.000"),
            lookback_return_bps=Decimal("-25.000"),
            impulse_direction="down",
            impulse_return_bps=Decimal("-18.000"),
            contract_close_time=_future_time(minutes=7),
            contract_time_remaining_seconds=420,
        )
        coordinator.process_contract_scan_snapshot(
            _contract_snapshot(contract),
            cycle_number=703,
            market_snapshot=market_snapshot,
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(contract),
            cycle_number=704,
            market_snapshot=market_snapshot,
        )
        if len(intents) != 1:
            return [f"ev NO candidate A intents={len(intents)} expected=1"]
        payload = _last_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_intent_created",
        )
        if payload is None:
            return ["ev NO candidate A intent log missing"]
        failures: list[str] = []
        expected = {
            "intent_side": "no",
            "ev_filter_status": "allowed",
            "ev_matched_candidate": "candidate_a",
            "ev_cost_price": "0.91",
            "ev_market_probability_price": "0.09",
            "ev_price_limit_basis": "market_probability_price",
            "ev_side_price_basis": "opposite_yes_bid",
            "ev_opposite_price": "0.09",
            "ev_entry_price_within_limit_status": "within_limit",
            "ev_side_adjusted_price_within_limit": True,
            "ev_no_side_price_interpretation_applied": True,
            "ev_estimated_reward": "0.0900",
            "ev_estimated_risk": "0.91",
            "ev_score": "0.7800",
            "ev_score_basis": "market_probability_price",
        }
        for key, value in expected.items():
            if payload.get(key) != value:
                failures.append(f"ev NO {key}={payload.get(key)} expected={value}")
        return failures


def _validate_ev_no_candidate_a_needs_cross_blocks() -> list[str]:
    return _expect_ev_no_skip(
        market_ticker="KXBTC15M-EV-NO-CROSS",
        side_currently_itm=False,
        side_needs_cross=True,
        distance_to_target_bps=Decimal("1.000"),
        required_bps_per_minute=Decimal("0.100"),
        expected_reason="needs_cross_blocked",
    )


def _validate_ev_no_candidate_a_required_bps_blocks() -> list[str]:
    return _expect_ev_no_skip(
        market_ticker="KXBTC15M-EV-NO-BPS",
        required_bps_per_minute=Decimal("0.500"),
        expected_reason="required_bps_per_minute_too_high",
    )


def _validate_ev_no_candidate_a_missing_liquidity_blocks() -> list[str]:
    return _expect_ev_no_skip(
        market_ticker="KXBTC15M-EV-NO-LIQ",
        yes_bid_size=Decimal("0"),
        expected_reason="executable_price_no_visible_liquidity",
        expected_ev_block_reason="missing_liquidity_present",
    )


def _validate_ev_no_candidate_a_hard_cost_ceiling_blocks() -> list[str]:
    return _expect_ev_no_skip(
        market_ticker="KXBTC15M-EV-NO-CEILING",
        expected_reason="contextual_high_price_above_ceiling",
        expected_ev_status="allowed",
    )


def _expect_ev_no_skip(
    *,
    market_ticker: str,
    expected_reason: str,
    side_currently_itm: bool = True,
    side_needs_cross: bool = False,
    distance_to_target_bps: Decimal = Decimal("-100.000"),
    required_bps_per_minute: Decimal = Decimal("0.000"),
    yes_bid_size: Decimal = Decimal("100"),
    expected_ev_block_reason: str | None = None,
    expected_ev_status: str | None = None,
) -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            settings=_Settings(
                log_directory=temp_path,
                log_jsonl_enabled=True,
                live_ev_filter_enabled=True,
            ),
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        market_snapshot = _market_snapshot(
            market_ticker=market_ticker,
            yes_bid=Decimal("0.09"),
            yes_ask=Decimal("0.15"),
            yes_bid_size=yes_bid_size,
            yes_ask_size=Decimal("100"),
            orderbook_seq=705,
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(
                _contract(
                    market_ticker=market_ticker,
                    direction="down",
                    midpoint=Decimal("0.12"),
                    side_currently_itm=side_currently_itm,
                    side_needs_cross=side_needs_cross,
                    distance_to_target_bps=distance_to_target_bps,
                    required_bps_per_minute=required_bps_per_minute,
                    feasibility_status=(
                        "needs_cross" if side_needs_cross else "currently_itm"
                    ),
                    recent_return_bps=Decimal("-20.000"),
                    lookback_return_bps=Decimal("-25.000"),
                    impulse_direction="down",
                    impulse_return_bps=Decimal("-18.000"),
                    contract_close_time=_future_time(minutes=7),
                    contract_time_remaining_seconds=420,
                )
            ),
            cycle_number=705,
            market_snapshot=market_snapshot,
        )
        if intents:
            return [f"{market_ticker} intents={len(intents)} expected=0"]
        payload = _last_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_order_intent_skipped",
        )
        if payload is None:
            return [f"{market_ticker} skip log missing"]
        failures: list[str] = []
        if payload.get("reason") != expected_reason:
            failures.append(f"{market_ticker} reason={payload.get('reason')}")
        if payload.get("ev_cost_price") != "0.91":
            failures.append(f"{market_ticker} ev_cost={payload.get('ev_cost_price')}")
        if payload.get("ev_market_probability_price") != "0.09":
            failures.append(
                f"{market_ticker} ev_market={payload.get('ev_market_probability_price')}"
            )
        if payload.get("ev_no_side_price_interpretation_applied") is not True:
            failures.append(
                f"{market_ticker} no-side={payload.get('ev_no_side_price_interpretation_applied')}"
            )
        if expected_ev_block_reason is not None and payload.get("ev_block_reason") != expected_ev_block_reason:
            failures.append(
                f"{market_ticker} ev_block={payload.get('ev_block_reason')}"
            )
        if expected_ev_status is not None and payload.get("ev_filter_status") != expected_ev_status:
            failures.append(
                f"{market_ticker} ev_status={payload.get('ev_filter_status')}"
            )
        return failures


def _validate_ev_candidate_a_blocks_needs_cross() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            settings=_Settings(
                log_directory=temp_path,
                log_jsonl_enabled=True,
                live_ev_filter_enabled=True,
            ),
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        market_snapshot = _market_snapshot(
            market_ticker="KXBTC15M-EV-A-CROSS",
            yes_bid=Decimal("0.29"),
            yes_ask=Decimal("0.30"),
            yes_bid_size=Decimal("100"),
            yes_ask_size=Decimal("100"),
            orderbook_seq=702,
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(
                _contract(
                    market_ticker="KXBTC15M-EV-A-CROSS",
                    midpoint=Decimal("0.30"),
                    side_currently_itm=False,
                    side_needs_cross=True,
                    distance_to_target_bps=Decimal("1.000"),
                    required_bps_per_minute=Decimal("0.100"),
                    feasibility_status="needs_cross",
                    contract_close_time=_future_time(minutes=4),
                    contract_time_remaining_seconds=240,
                )
            ),
            cycle_number=701,
            market_snapshot=market_snapshot,
        )
        if intents:
            return [f"ev needs-cross intents={len(intents)} expected=0"]
        payload = _last_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_order_intent_skipped",
        )
        if payload is None:
            return ["ev needs-cross skip log missing"]
        if payload.get("reason") != "needs_cross_blocked":
            return [f"ev needs-cross reason={payload.get('reason')}"]
        if payload.get("ev_block_reason") != "missing_side_currently_itm":
            return [f"ev needs-cross block={payload.get('ev_block_reason')}"]
        return []


def _validate_ev_conditional_scanner_premium_bypass() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            settings=_Settings(
                log_directory=temp_path,
                log_jsonl_enabled=True,
                live_ev_filter_enabled=True,
            ),
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        market_snapshot = _market_snapshot(
            market_ticker="KXBTC15M-EV-PREMIUM",
            yes_bid=Decimal("0.60"),
            yes_ask=Decimal("0.62"),
            yes_bid_size=Decimal("100"),
            yes_ask_size=Decimal("100"),
            orderbook_seq=703,
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(
                _contract(
                    market_ticker="KXBTC15M-EV-PREMIUM",
                    midpoint=Decimal("0.50"),
                    contract_close_time=_future_time(minutes=6),
                    contract_time_remaining_seconds=360,
                )
            ),
            cycle_number=702,
            market_snapshot=market_snapshot,
        )
        if len(intents) != 1:
            return [f"ev premium bypass intents={len(intents)} expected=1"]
        payload = _last_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_intent_created",
        )
        if payload is None:
            return ["ev premium bypass intent log missing"]
        failures: list[str] = []
        if not payload.get("conditional_override_applied"):
            failures.append("ev premium bypass override not applied")
        if payload.get("original_blocker_reason") != "executable_price_above_scanner_premium":
            failures.append(
                "ev premium bypass original="
                f"{payload.get('original_blocker_reason')}"
            )
        return failures


def _validate_composite_low_price_candidate_allows() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            settings=_Settings(
                log_directory=temp_path,
                log_jsonl_enabled=True,
                live_ev_filter_enabled=True,
            ),
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        market_snapshot = _market_snapshot(
            market_ticker="KXBTC15M-COMP-B",
            yes_bid=Decimal("0.29"),
            yes_ask=Decimal("0.30"),
            yes_bid_size=Decimal("100"),
            yes_ask_size=Decimal("100"),
            orderbook_seq=700,
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(
                _contract(
                    market_ticker="KXBTC15M-COMP-B",
                    midpoint=Decimal("0.30"),
                    contract_close_time=_future_time(minutes=2),
                    contract_time_remaining_seconds=120,
                )
            ),
            cycle_number=70,
            market_snapshot=market_snapshot,
        )
        if len(intents) != 1:
            return [f"composite low-price intents={len(intents)} expected=1"]
        payload = _last_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_intent_created",
        )
        if payload is None:
            return ["composite low-price intent log missing"]
        if payload.get("composite_quality_status") != "allowed_ev_composite_override":
            return [
                "composite low-price status="
                f"{payload.get('composite_quality_status')}"
            ]
        if payload.get("ev_matched_candidate") != "candidate_b":
            return [
                "composite low-price ev candidate="
                f"{payload.get('ev_matched_candidate')}"
            ]
        if payload.get("entry_segment") != "3_to_1":
            return [f"composite low-price segment={payload.get('entry_segment')}"]
        return []


def _validate_reversal_price_blocks_confirmed_hold() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        now = {"value": 1000.0}
        coordinator = _coordinator(
            temp_path,
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
            time_fn=lambda: now["value"],
        )
        contract = _contract(
            market_ticker="KXBTC15M-REV-PRICE-BLOCK",
            structure="reversal",
            reversal_confirmation_status="confirmed",
            trend_confirmation_status="not_trend",
            side_currently_itm=True,
            side_needs_cross=False,
            distance_to_target_bps=Decimal("-3.000"),
            required_bps_per_minute=Decimal("0.000"),
            midpoint=Decimal("0.10"),
            contract_close_time=_future_time(minutes=2),
        )
        coordinator.process_contract_scan_snapshot(_contract_snapshot(contract), cycle_number=71)
        now["value"] = 1061.0
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(contract),
            cycle_number=72,
        )
        if intents:
            return [f"reversal price block intents={len(intents)} expected=0"]
        payload = _last_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_order_intent_skipped",
        )
        if payload is None:
            return ["reversal price block skip log missing"]
        if payload.get("reason") != "reversal_price_blocked":
            return [f"reversal price block reason={payload.get('reason')}"]
        if payload.get("reversal_price_block_reason") != "reversal_entry_price_too_high":
            return [
                "reversal price block detail="
                f"{payload.get('reversal_price_block_reason')}"
            ]
        return []


def _validate_needs_cross_blocks_by_default() -> list[str]:
    return _expect_composite_skip(
        contract=_contract(
            market_ticker="KXBTC15M-NEEDS-CROSS-BLOCK",
            midpoint=Decimal("0.30"),
            side_currently_itm=False,
            side_needs_cross=True,
            distance_to_target_bps=Decimal("1.000"),
            required_bps_per_minute=Decimal("0.100"),
            feasibility_status="needs_cross",
            contract_close_time=_future_time(minutes=2),
        ),
        expected_reason="needs_cross_blocked",
        cycle_number=73,
    )


def _validate_required_bps_per_minute_blocks() -> list[str]:
    return _expect_composite_skip(
        contract=_contract(
            market_ticker="KXBTC15M-REQ-BPS-BLOCK",
            midpoint=Decimal("0.30"),
            side_currently_itm=True,
            side_needs_cross=False,
            distance_to_target_bps=Decimal("-1.000"),
            required_bps_per_minute=Decimal("0.500"),
            contract_close_time=_future_time(minutes=2),
        ),
        expected_reason="required_bps_per_minute_too_high",
        cycle_number=74,
    )


def _validate_far_itm_trend_not_distance_blocked() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        coordinator = _coordinator(
            Path(temp_dir),
            settings=_Settings(
                log_directory=Path(temp_dir),
                log_jsonl_enabled=True,
                live_composite_quality_filter_enabled=False,
            ),
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(
                _contract(
                    market_ticker="KXBTC15M-FAR-ITM",
                    midpoint=Decimal("0.30"),
                    side_currently_itm=True,
                    side_needs_cross=False,
                    distance_to_target_bps=Decimal("-50.000"),
                    required_bps_per_minute=Decimal("0.000"),
                    contract_close_time=_future_time(minutes=2),
                )
            ),
            cycle_number=75,
        )
        if len(intents) != 1:
            return [f"far ITM intents={len(intents)} expected=1"]
        return []


def _validate_outside_end_window_blocks_by_default() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            settings=_Settings(
                log_directory=temp_path,
                log_jsonl_enabled=True,
                live_entry_end_window_only=True,
                live_entry_end_window_minutes=10,
            ),
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(
                _contract(
                    market_ticker="KXBTC15M-OUTSIDE-BLOCK",
                    midpoint=Decimal("0.30"),
                    contract_close_time=_future_time(minutes=12),
                )
            ),
            cycle_number=76,
        )
        if intents:
            return [f"outside window intents={len(intents)} expected=0"]
        payload = _last_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_order_intent_skipped",
        )
        if payload is None:
            return ["outside window skip log missing"]
        if payload.get("reason") != "outside_end_window_blocked":
            return [f"outside window reason={payload.get('reason')}"]
        return []


def _validate_outside_end_window_exception_allows_low_price_trend() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            settings=_Settings(
                log_directory=temp_path,
                log_jsonl_enabled=True,
                live_entry_end_window_only=True,
                live_entry_end_window_minutes=10,
                live_outside_end_window_exception_enabled=True,
            ),
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(
                _contract(
                    market_ticker="KXBTC15M-OUTSIDE-ALLOW",
                    midpoint=Decimal("0.30"),
                    contract_close_time=_future_time(minutes=12),
                )
            ),
            cycle_number=77,
        )
        if len(intents) != 1:
            return [f"outside exception intents={len(intents)} expected=1"]
        payload = _last_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_intent_created",
        )
        if payload is None:
            return ["outside exception intent log missing"]
        if (
            payload.get("outside_end_window_exception_status")
            != "allowed_low_price_trend_exception"
        ):
            return [
                "outside exception status="
                f"{payload.get('outside_end_window_exception_status')}"
            ]
        return []


def _expect_composite_skip(
    *,
    contract: ScannedContract,
    expected_reason: str,
    cycle_number: int,
) -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(contract),
            cycle_number=cycle_number,
        )
        if intents:
            return [f"{contract.market_ticker} intents={len(intents)} expected=0"]
        payload = _last_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_order_intent_skipped",
        )
        if payload is None:
            return [f"{contract.market_ticker} skip log missing"]
        failures: list[str] = []
        if payload.get("reason") != expected_reason:
            failures.append(
                f"{contract.market_ticker} reason={payload.get('reason')}"
            )
        required_fields = (
            "market_ticker",
            "product_id",
            "direction",
            "intent_side",
            "entry_price",
            "structure",
            "entry_segment",
            "side_currently_itm",
            "side_needs_cross",
            "distance_to_target",
            "distance_to_target_bps",
            "required_bps_per_minute",
            "trend_confirmation_status",
            "reversal_confirmation_status",
            "composite_quality_block_reason",
        )
        missing = tuple(field for field in required_fields if field not in payload)
        if missing:
            failures.append(f"{contract.market_ticker} missing fields={missing}")
        return failures


def _validate_midpoint_fallback_price_below_minimum_skip() -> list[str]:
    return _validate_execution_price_safety_skip(
        market_ticker="KXBTC15M-FALLBACK-BELOW-MIN",
        midpoint=Decimal("0.09"),
        expected_reason="executable_price_below_minimum",
        expected_count=33,
        expected_intent_side="yes",
        expected_executable_side_ask=None,
        market_snapshot=None,
    )


def _validate_midpoint_fallback_price_above_maximum_skip() -> list[str]:
    return _validate_execution_price_safety_skip(
        market_ticker="KXBTC15M-FALLBACK-ABOVE-MAX",
        midpoint=Decimal("0.81"),
        expected_reason="executable_price_above_maximum",
        expected_count=3,
        expected_intent_side="yes",
        expected_executable_side_ask=None,
        market_snapshot=None,
    )


def _validate_execution_price_safety_skip(
    *,
    market_ticker: str,
    midpoint: Decimal,
    expected_reason: str,
    expected_count: int,
    expected_intent_side: str,
    expected_executable_side_ask: str | None,
    yes_bid: Decimal = Decimal("0.09"),
    yes_ask: Decimal = Decimal("0.10"),
    yes_bid_size: Decimal = Decimal("50"),
    yes_ask_size: Decimal = Decimal("10"),
    contract: ScannedContract | None = None,
    market_snapshot: MarketStateSnapshot | None | bool = True,
) -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        snapshot = (
            _market_snapshot(
                market_ticker=market_ticker,
                yes_bid=yes_bid,
                yes_ask=yes_ask,
                yes_bid_size=yes_bid_size,
                yes_ask_size=yes_ask_size,
                orderbook_seq=123,
            )
            if market_snapshot is True
            else market_snapshot
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(
                contract
                or _contract(
                    market_ticker=market_ticker,
                    midpoint=midpoint,
                )
            ),
            cycle_number=45,
            market_snapshot=snapshot,
        )
        failures: list[str] = []
        if intents:
            failures.append(f"{market_ticker} intents={intents} expected empty")
        payload = _first_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_order_intent_skipped",
        )
        if payload is None:
            failures.append(f"{market_ticker} skip log missing")
            return failures
        expected = {
            "reason": expected_reason,
            "ticker": market_ticker,
            "market_ticker": market_ticker,
            "product_id": "BTC-USD",
            "scanner_midpoint": str(midpoint),
            "intent_price_dollars": (
                expected_executable_side_ask
                if expected_executable_side_ask is not None
                else str(midpoint)
            ),
            "intent_side": expected_intent_side,
            "executable_side_ask": expected_executable_side_ask,
            "count": expected_count,
            "stake_dollars": "3.00",
        }
        for key, value in expected.items():
            if payload.get(key) != value:
                failures.append(
                    f"{market_ticker} {key}={payload.get(key)} expected={value}"
                )
        return failures


def _validate_direct_contract_scan_count_below_one_skip() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("0.20")),
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(_contract(midpoint=Decimal("0.46"))),
            cycle_number=44,
        )
        if intents:
            return [f"direct small-count intents={intents} expected empty"]
        payload = _first_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_order_intent_skipped",
        )
        if payload is None:
            return ["direct small-count skip log missing"]
        if payload.get("reason") != "count_below_one":
            return [f"direct small-count reason={payload.get('reason')}"]
        return []


def _validate_stale_contract_close_time_blocks() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(
                _contract(contract_close_time=_past_time(minutes=1))
            ),
            cycle_number=45,
        )
        if intents:
            return [f"stale contract intents={intents} expected empty"]
        payload = _first_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_order_intent_skipped",
        )
        if payload is None:
            return ["stale contract skip log missing"]
        if payload.get("reason") != "stale_ticker_blocked":
            return [f"stale contract reason={payload.get('reason')}"]
        if payload.get("stale_ticker_block_reason") != "close_time_elapsed":
            return [
                "stale contract block reason="
                f"{payload.get('stale_ticker_block_reason')}"
            ]
        return []


def _validate_end_window_blocks_early_contract() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            settings=_Settings(
                log_directory=temp_path,
                log_jsonl_enabled=True,
                live_entry_end_window_only=True,
                live_entry_end_window_minutes=5,
                live_composite_quality_filter_enabled=False,
            ),
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(
                _contract(contract_close_time=_future_time(minutes=8))
            ),
            cycle_number=46,
        )
        failures: list[str] = []
        if intents:
            failures.append(f"end-window early intents={intents} expected empty")
        payload = _first_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_order_intent_skipped",
        )
        if payload is None:
            failures.append("end-window early skip log missing")
            return failures
        expected = {
            "reason": "end_window_not_open",
            "end_window_allowed": False,
            "end_window_reason": "end_window_not_open",
        }
        for key, value in expected.items():
            if payload.get(key) != value:
                failures.append(f"end-window early {key}={payload.get(key)}")
        if not isinstance(payload.get("contract_time_remaining_seconds"), int):
            failures.append("end-window early remaining seconds missing")
        return failures


def _validate_end_window_allows_late_contract() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            settings=_Settings(
                log_directory=temp_path,
                log_jsonl_enabled=True,
                live_entry_end_window_only=True,
                live_entry_end_window_minutes=5,
                live_composite_quality_filter_enabled=False,
            ),
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(
                _contract(contract_close_time=_future_time(minutes=3))
            ),
            cycle_number=47,
        )
        failures: list[str] = []
        if len(intents) != 1:
            failures.append(f"end-window late count={len(intents)} expected=1")
            return failures
        payload = _first_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_intent_created",
        )
        if payload is None:
            failures.append("end-window late intent log missing")
            return failures
        expected = {
            "end_window_allowed": True,
            "end_window_reason": "end_window_open",
        }
        for key, value in expected.items():
            if payload.get(key) != value:
                failures.append(f"end-window late {key}={payload.get(key)}")
        if not isinstance(payload.get("contract_time_remaining_seconds"), int):
            failures.append("end-window late remaining seconds missing")
        return failures


def _validate_end_window_skips_missing_close_time() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            settings=_Settings(
                log_directory=temp_path,
                log_jsonl_enabled=True,
                live_entry_end_window_only=True,
                live_entry_end_window_minutes=5,
            ),
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(_contract()),
            cycle_number=48,
        )
        failures: list[str] = []
        if intents:
            failures.append(f"end-window missing intents={intents} expected empty")
        payload = _first_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_order_intent_skipped",
        )
        if payload is None:
            failures.append("end-window missing skip log missing")
            return failures
        expected = {
            "reason": "end_window_close_time_missing",
            "end_window_allowed": False,
            "end_window_reason": "end_window_close_time_missing",
        }
        for key, value in expected.items():
            if payload.get(key) != value:
                failures.append(f"end-window missing {key}={payload.get(key)}")
        return failures


def _validate_flip_persistence_allows_same_direction() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        coordinator = _coordinator(
            Path(temp_dir),
            settings=_Settings(
                log_directory=Path(temp_dir),
                log_jsonl_enabled=True,
                live_composite_quality_filter_enabled=False,
            ),
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        first = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(_contract(market_ticker="KXBTC15M-FLIP-1")),
            cycle_number=49,
        )
        second = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(_contract(market_ticker="KXBTC15M-FLIP-1")),
            cycle_number=50,
        )
        failures: list[str] = []
        if len(first) != 1 or len(second) != 1:
            failures.append(f"same-direction intent counts={len(first)}/{len(second)}")
        payloads = _event_payloads(
            _jsonl_records(Path(temp_dir) / "runtime.jsonl"),
            event_type="live_intent_created",
        )
        if len(payloads) < 2:
            failures.append("same-direction intent logs missing")
        elif payloads[-1].get("flip_persistence_status") != "same_direction":
            failures.append(
                "same-direction flip status="
                f"{payloads[-1].get('flip_persistence_status')}"
            )
        return failures


def _validate_flip_persistence_blocks_recent_opposite_direction() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            settings=_Settings(
                log_directory=temp_path,
                log_jsonl_enabled=True,
                live_composite_quality_filter_enabled=False,
            ),
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        coordinator.process_contract_scan_snapshot(
            _contract_snapshot(_contract(market_ticker="KXBTC15M-FLIP-UP")),
            cycle_number=51,
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(
                _contract(
                    market_ticker="KXBTC15M-FLIP-DOWN",
                    direction="down",
                    side_currently_itm=False,
                    side_needs_cross=False,
                    recent_return_bps=Decimal("-20.000"),
                    impulse_return_bps=Decimal("-18.000"),
                )
            ),
            cycle_number=52,
        )
        failures: list[str] = []
        if intents:
            failures.append(f"opposite blocked intents={intents} expected empty")
        payload = _last_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_order_intent_skipped",
        )
        if payload is None:
            failures.append("opposite blocked skip log missing")
            return failures
        if payload.get("reason") != "flip_persistence_blocked":
            failures.append(f"opposite blocked reason={payload.get('reason')}")
        if payload.get("flip_persistence_status") != "blocked_recent_flip_not_itm":
            failures.append(
                "opposite blocked status="
                f"{payload.get('flip_persistence_status')}"
            )
        return failures


def _validate_flip_persistence_allows_itm_persistent_opposite_direction() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            settings=_Settings(
                log_directory=temp_path,
                log_jsonl_enabled=True,
                live_composite_quality_filter_enabled=False,
            ),
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        coordinator.process_contract_scan_snapshot(
            _contract_snapshot(_contract(market_ticker="KXBTC15M-FLIP-UP-ALLOW")),
            cycle_number=53,
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(
                _contract(
                    market_ticker="KXBTC15M-FLIP-DOWN-ALLOW",
                    direction="down",
                    side_currently_itm=True,
                    side_needs_cross=False,
                    recent_return_bps=Decimal("-20.000"),
                    lookback_return_bps=Decimal("-25.000"),
                    impulse_direction="down",
                    impulse_return_bps=Decimal("-18.000"),
                )
            ),
            cycle_number=54,
        )
        failures: list[str] = []
        if len(intents) != 1:
            failures.append(f"opposite allow intents={len(intents)} expected=1")
            return failures
        payload = _last_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_intent_created",
        )
        if payload is None:
            failures.append("opposite allow intent log missing")
            return failures
        expected_status = "opposite_direction_allowed_crossed_and_persistent"
        if payload.get("flip_persistence_status") != expected_status:
            failures.append(
                "opposite allow status="
                f"{payload.get('flip_persistence_status')} expected={expected_status}"
            )
        return failures


def _validate_same_side_retry_blocks_without_improvement() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            settings=_Settings(
                log_directory=temp_path,
                log_jsonl_enabled=True,
                live_composite_quality_filter_enabled=False,
                live_block_needs_cross=False,
                live_max_required_bps_per_minute=Decimal("1.00"),
            ),
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        first_contract = _contract(
            market_ticker="KXBTC15M-RETRY-BLOCK-1",
            side_currently_itm=False,
            side_needs_cross=True,
            distance_to_target_bps=Decimal("4.000"),
            required_bps_per_minute=Decimal("0.800"),
            feasibility_status="needs_cross",
        )
        second_contract = _contract(
            market_ticker="KXBTC15M-RETRY-BLOCK-2",
            side_currently_itm=False,
            side_needs_cross=True,
            distance_to_target_bps=Decimal("4.000"),
            required_bps_per_minute=Decimal("0.800"),
            feasibility_status="needs_cross",
        )
        coordinator.process_contract_scan_snapshot(
            _contract_snapshot(first_contract),
            cycle_number=55,
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(second_contract),
            cycle_number=56,
        )
        failures: list[str] = []
        if intents:
            failures.append(f"retry block intents={intents} expected empty")
        payload = _last_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_order_intent_skipped",
        )
        if payload is None:
            failures.append("retry block skip log missing")
            return failures
        if payload.get("reason") != "retry_persistence_blocked":
            failures.append(f"retry block reason={payload.get('reason')}")
        expected_status = "blocked_same_direction_feasibility_not_improved"
        if payload.get("retry_persistence_status") != expected_status:
            failures.append(
                "retry block status="
                f"{payload.get('retry_persistence_status')} expected={expected_status}"
            )
        return failures


def _validate_same_side_retry_allows_improved_feasibility() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            settings=_Settings(
                log_directory=temp_path,
                log_jsonl_enabled=True,
                live_composite_quality_filter_enabled=False,
                live_block_needs_cross=False,
                live_max_required_bps_per_minute=Decimal("1.00"),
            ),
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        first_contract = _contract(
            market_ticker="KXBTC15M-RETRY-ALLOW-1",
            side_currently_itm=False,
            side_needs_cross=True,
            distance_to_target_bps=Decimal("4.000"),
            required_bps_per_minute=Decimal("0.800"),
            feasibility_status="needs_cross",
        )
        second_contract = _contract(
            market_ticker="KXBTC15M-RETRY-ALLOW-2",
            side_currently_itm=False,
            side_needs_cross=True,
            distance_to_target_bps=Decimal("2.000"),
            required_bps_per_minute=Decimal("0.400"),
            feasibility_status="needs_cross",
        )
        coordinator.process_contract_scan_snapshot(
            _contract_snapshot(first_contract),
            cycle_number=57,
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(second_contract),
            cycle_number=58,
        )
        failures: list[str] = []
        if len(intents) != 1:
            failures.append(f"retry allow intents={len(intents)} expected=1")
            return failures
        payload = _last_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_intent_created",
        )
        if payload is None:
            failures.append("retry allow intent log missing")
            return failures
        expected_status = "same_direction_allowed_feasibility_improved"
        if payload.get("retry_persistence_status") != expected_status:
            failures.append(
                "retry allow status="
                f"{payload.get('retry_persistence_status')} expected={expected_status}"
            )
        return failures


def _validate_entry_segment_budget_blocks_overuse() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            settings=_Settings(
                log_directory=temp_path,
                log_jsonl_enabled=True,
                live_entry_end_window_only=True,
                live_entry_end_window_minutes=10,
                live_entry_segment_pacing_enabled=True,
                live_entry_segment_max_10_to_5=1,
            ),
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        contract = _contract(
            market_ticker="KXBTC15M-SEGMENT",
            contract_close_time=_future_time(minutes=7),
        )
        first = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(contract),
            cycle_number=70,
        )
        second = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(contract),
            cycle_number=71,
        )
        failures: list[str] = []
        if len(first) != 1:
            failures.append(f"segment first intents={len(first)} expected=1")
        if second:
            failures.append(f"segment second intents={len(second)} expected=0")
        payload = _last_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_order_intent_skipped",
        )
        if payload is None:
            failures.append("segment budget skip log missing")
            return failures
        if payload.get("reason") != "entry_segment_budget_exhausted":
            failures.append(f"segment budget reason={payload.get('reason')}")
        if payload.get("entry_segment") != "10_to_5":
            failures.append(f"segment budget segment={payload.get('entry_segment')}")
        return failures


def _validate_product_session_cap_blocks_overuse() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            settings=_Settings(
                log_directory=temp_path,
                log_jsonl_enabled=True,
                live_max_entries_per_product_per_session=2,
                live_composite_quality_filter_enabled=False,
            ),
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("3.00")),
        )
        contract = _contract(market_ticker="KXBTC15M-PRODUCT-CAP")
        first = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(contract),
            cycle_number=72,
        )
        second = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(contract),
            cycle_number=73,
        )
        third = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(contract),
            cycle_number=74,
        )
        failures: list[str] = []
        if len(first) != 1:
            failures.append(f"product cap first intents={len(first)} expected=1")
        if len(second) != 1:
            failures.append(f"product cap second intents={len(second)} expected=1")
        if third:
            failures.append(f"product cap third intents={len(third)} expected=0")
        payload = _last_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_order_intent_skipped",
        )
        if payload is None:
            failures.append("product cap skip log missing")
            return failures
        if payload.get("reason") != "product_session_pacing_blocked":
            failures.append(f"product cap reason={payload.get('reason')}")
        expected_status = "max_entries_per_product_session_reached"
        if payload.get("product_session_pacing_status") != expected_status:
            failures.append(
                "product cap status="
                f"{payload.get('product_session_pacing_status')} expected={expected_status}"
            )
    return failures


def _validate_candidate_funnel_summary_logs_scanner_and_live_counts() -> list[str]:
    failures: list[str] = []
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            settings=_Settings(
                log_directory=temp_path,
                log_jsonl_enabled=True,
                live_candidate_funnel_diagnostics_enabled=True,
            ),
        )
        skipped_snapshot = ContractScanSnapshot(
            ranked_contracts=(),
            skipped_contracts=(
                SkippedContract(
                    product_id="BTC-USD",
                    market_ticker="KXBTC15M-TEST",
                    reason="neutral_bias",
                    direction="neutral",
                    structure="exhaustion",
                    confidence=30,
                    classification_reason="recent_below_chop_exhaustion",
                    recent_return_bps=Decimal("5.000"),
                    lookback_return_bps=Decimal("30.000"),
                ),
                SkippedContract(
                    product_id="ETH-USD",
                    market_ticker="KXETH15M-TEST",
                    reason="quiet_continuation_needs_cross_blocked",
                    direction="up",
                    structure="trend",
                    confidence=30,
                    classification_reason="quiet_continuation_from_exhaustion",
                    side_currently_itm=False,
                    side_needs_cross=True,
                    required_bps_per_minute=Decimal("0.500"),
                ),
            ),
        )
        coordinator.process_contract_scan_snapshot(skipped_snapshot, cycle_number=10)
        payload = _last_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="candidate_funnel_summary",
        )
        if payload is None:
            failures.append("candidate funnel no-ranked summary missing")
        else:
            if payload.get("neutral_bias_count") != 1:
                failures.append(
                    f"candidate funnel neutral={payload.get('neutral_bias_count')}"
                )
            if payload.get("quiet_continuation_failed_count") != 1:
                failures.append(
                    "candidate funnel quiet failed="
                    f"{payload.get('quiet_continuation_failed_count')}"
                )
            diagnostics = payload.get("scanner_candidate_funnel_diagnostics")
            if not isinstance(diagnostics, list) or not diagnostics:
                failures.append("candidate funnel scanner diagnostics missing")

    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            settings=_Settings(
                log_directory=temp_path,
                log_jsonl_enabled=True,
                live_ev_filter_enabled=True,
                live_composite_quality_filter_enabled=True,
                live_candidate_funnel_diagnostics_enabled=True,
            ),
            risk_manager=_FixedEntryRiskManager(stake_dollars=Decimal("2.00")),
        )
        contract = _contract(
            midpoint=Decimal("0.40"),
            contract_close_time=_future_time(minutes=6),
            contract_time_remaining_seconds=360,
        )
        coordinator.process_contract_scan_snapshot(
            _contract_snapshot(contract),
            cycle_number=11,
            market_snapshot=None,
        )
        payload = _last_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="candidate_funnel_summary",
        )
        if payload is None:
            failures.append("candidate funnel live summary missing")
        else:
            live_reasons = {
                item.get("reason"): item.get("count")
                for item in payload.get("live_reason_counts", [])
                if isinstance(item, dict)
            }
            if live_reasons.get("executable_price_no_visible_liquidity") != 1:
                failures.append(f"candidate funnel live reasons={live_reasons}")
            if payload.get("ranked_contract_count") != 1:
                failures.append(
                    f"candidate funnel ranked={payload.get('ranked_contract_count')}"
                )
            live_diagnostics = payload.get("live_candidate_funnel_diagnostics")
            if not isinstance(live_diagnostics, list) or not live_diagnostics:
                failures.append("candidate funnel live diagnostics missing")
    return failures


def _coordinator(
    temp_path: Path,
    settings: "_Settings | None" = None,
    risk_manager=None,  # noqa: ANN001
    time_fn=None,  # noqa: ANN001
) -> LiveExecutionCoordinator:
    return LiveExecutionCoordinator(
        settings=settings
        or _Settings(
            log_directory=temp_path,
            log_jsonl_enabled=True,
        ),
        risk_manager=risk_manager,
        time_fn=time_fn or time.monotonic,
    )


def _contract_snapshot(*contracts: ScannedContract) -> ContractScanSnapshot:
    return ContractScanSnapshot(
        ranked_contracts=contracts,
        skipped_contracts=(),
    )


def _contract(
    *,
    product_id: str = "BTC-USD",
    market_ticker: str = "KXBTC15M-TEST",
    direction: str = "up",
    confidence: int = 70,
    midpoint: Decimal = Decimal("0.10"),
    contract_close_time: str | None = None,
    side_currently_itm: bool = True,
    side_needs_cross: bool = False,
    distance_to_target_bps: Decimal = Decimal("-100.000"),
    required_bps_per_minute: Decimal = Decimal("0.000"),
    feasibility_status: str = "currently_itm",
    recent_return_bps: Decimal = Decimal("20.000"),
    lookback_return_bps: Decimal = Decimal("25.000"),
    impulse_direction: str | None = "up",
    impulse_return_bps: Decimal | None = Decimal("18.000"),
    structure: str = "trend",
    reversal_confirmation_status: str = "not_reversal",
    trend_confirmation_status: str = "confirmed",
    contract_time_remaining_seconds: int | None = 120,
) -> ScannedContract:
    return ScannedContract(
        product_id=product_id,
        market_ticker=market_ticker,
        direction=direction,
        structure=structure,
        confidence=confidence,
        best_bid=midpoint - Decimal("0.01"),
        best_ask=midpoint + Decimal("0.01"),
        midpoint=midpoint,
        bias_as_of="2026-04-23T12:00:00+00:00",
        market_as_of="2026-04-23T12:00:03+00:00",
        score=ContractScore(
            confidence=confidence,
            spread_width=Decimal("0.02"),
            top_of_book_liquidity=Decimal("100"),
            dollar_volume=Decimal("1000"),
        ),
        latest_price=Decimal("100.00"),
        observation_count=25,
        recent_return_bps=recent_return_bps,
        lookback_return_bps=lookback_return_bps,
        impulse_direction=impulse_direction,
        impulse_return_bps=impulse_return_bps,
        impulse_detected=True,
        risk_flags=(
            ("insufficient_history", False),
            ("stale_data", False),
            ("time_sync_failed", False),
        ),
        target_price=Decimal("99.00"),
        target_price_source="target_price",
        distance_to_target=Decimal("-1.00"),
        distance_to_target_bps=distance_to_target_bps,
        required_bps_per_minute=required_bps_per_minute,
        side_currently_itm=side_currently_itm,
        side_needs_cross=side_needs_cross,
        feasibility_status=feasibility_status,
        reversal_confirmation_status=reversal_confirmation_status,
        trend_confirmation_status=trend_confirmation_status,
        signal_conflict_flags=(("impulse_direction_conflict", False),),
        scanner_score_confidence=confidence,
        scanner_score_downgrade_reasons=(),
        contract_open_time="2026-04-23T11:45:00+00:00",
        contract_close_time=contract_close_time,
        contract_time_remaining_seconds=contract_time_remaining_seconds,
    )


def _market_snapshot(
    *,
    market_ticker: str,
    yes_bid: Decimal,
    yes_ask: Decimal,
    yes_bid_size: Decimal,
    yes_ask_size: Decimal,
    orderbook_seq: int,
) -> MarketStateSnapshot:
    no_bid = Decimal("1") - yes_ask
    return MarketStateSnapshot(
        tickers={
            market_ticker: TickerState(
                market_ticker=market_ticker,
                yes_bid_dollars=yes_bid,
                yes_ask_dollars=yes_ask,
                yes_bid_size_fp=yes_bid_size,
                yes_ask_size_fp=yes_ask_size,
                seq=orderbook_seq,
            )
        },
        orderbooks={
            market_ticker: OrderBookState(
                market_ticker=market_ticker,
                yes={yes_bid: yes_bid_size},
                no={
                    no_bid: yes_ask_size,
                    no_bid - Decimal("0.01"): Decimal("2"),
                },
                seq=orderbook_seq,
            )
        },
        last_sequence_by_sid={},
    )


def _snapshot(position: SimulatedPosition) -> SimulationSnapshot:
    return SimulationSnapshot(
        open_positions={position.position_id: position},
        closed_positions=(),
        decisions=(
            SimulationDecision(
                action="open_position",
                position_id=position.position_id,
                product_id=position.product_id,
                market_ticker=position.market_ticker,
                reason=None,
            ),
        ),
        evaluation_count=1,
    )


def _position(
    *,
    position_id: str,
    product_id: str = "BTC-USD",
    market_ticker: str = "KXBTC15M-TEST",
    direction: str = "up",
    confidence: int = 70,
    stake_dollars: Decimal | None = Decimal("3.00"),
    entry_price: Decimal = Decimal("0.50"),
) -> SimulatedPosition:
    return SimulatedPosition(
        position_id=position_id,
        product_id=product_id,
        market_ticker=market_ticker,
        direction=direction,
        structure="trend",
        confidence=confidence,
        entry_price=entry_price,
        latest_price=entry_price,
        stake_dollars=stake_dollars,
        status="open",
        opened_at="2026-04-23T12:00:03+00:00",
        updated_at="2026-04-23T12:00:03+00:00",
        update_count=0,
    )


def _jsonl_records(path: Path) -> tuple[dict[str, object], ...]:
    if not path.exists():
        return ()
    records: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        records.append(json.loads(line))
    return tuple(records)


def _first_event_payload(
    records: tuple[dict[str, object], ...],
    *,
    event_type: str,
) -> dict[str, object] | None:
    for record in records:
        if record.get("event_type") != event_type:
            continue
        payload = record.get("payload")
        if isinstance(payload, dict):
            return payload
    return None


def _last_event_payload(
    records: tuple[dict[str, object], ...],
    *,
    event_type: str,
) -> dict[str, object] | None:
    for record in reversed(records):
        if record.get("event_type") != event_type:
            continue
        payload = record.get("payload")
        if isinstance(payload, dict):
            return payload
    return None


def _event_payloads(
    records: tuple[dict[str, object], ...],
    *,
    event_type: str,
) -> tuple[dict[str, object], ...]:
    payloads: list[dict[str, object]] = []
    for record in records:
        if record.get("event_type") != event_type:
            continue
        payload = record.get("payload")
        if isinstance(payload, dict):
            payloads.append(payload)
    return tuple(payloads)


def _future_time(*, minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def _past_time(*, minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


@dataclass(frozen=True)
class _Settings:
    log_directory: Path
    log_jsonl_enabled: bool
    live_entry_end_window_only: bool = False
    live_entry_end_window_minutes: int = 5
    live_entry_min_remaining_seconds: int = 0
    live_entry_segment_pacing_enabled: bool = False
    live_entry_segment_max_10_to_5: int = 1
    live_entry_segment_max_5_to_3: int = 1
    live_entry_segment_max_3_to_1: int = 1
    live_entry_segment_max_final_1: int = 1
    live_reversal_cross_hold_enabled: bool = True
    live_reversal_cross_hold_seconds: int = 60
    live_mid_price_tightening_enabled: bool = True
    live_mid_price_min: Decimal = Decimal("0.50")
    live_mid_price_max: Decimal = Decimal("0.70")
    live_max_open_positions_per_product: int = 2
    live_max_entries_per_product_per_session: int = 2
    live_composite_quality_filter_enabled: bool = True
    live_composite_max_entry_price: Decimal = Decimal("0.70")
    live_composite_low_price_max: Decimal = Decimal("0.30")
    live_composite_allowed_segments: tuple[str, ...] = ("10_to_5", "5_to_3")
    live_composite_require_trend: bool = True
    live_composite_require_itm: bool = True
    live_composite_block_needs_cross: bool = True
    live_reversal_max_entry_price: Decimal = Decimal("0.10")
    live_block_needs_cross: bool = True
    live_max_required_bps_per_minute: Decimal = Decimal("0.25")
    live_outside_end_window_exception_enabled: bool = False
    live_outside_end_window_max_price: Decimal = Decimal("0.30")
    live_ev_filter_enabled: bool = False
    live_min_expected_value: Decimal = Decimal("0.00")
    live_ev_price_max_itm_no_cross: Decimal = Decimal("0.70")
    live_ev_price_max_needs_cross: Decimal = Decimal("0.30")
    live_ev_required_bps_max: Decimal = Decimal("0.25")
    live_ev_allowed_segments: tuple[str, ...] = ("10_to_5", "5_to_3")
    live_ev_conservative_allowed_segments: tuple[str, ...] = (
        "10_to_5",
        "5_to_3",
        "3_to_1",
    )
    live_ev_allow_reversal: bool = False
    live_ev_candidate_a_win_probability: Decimal = Decimal("0.87")
    live_ev_candidate_b_win_probability: Decimal = Decimal("0.92")
    live_product_blocklist: tuple[str, ...] = ()
    live_conditional_high_price_pass_enabled: bool = True
    live_conditional_max_premium_over_midpoint: Decimal = Decimal("0.08")
    live_conditional_max_spread: Decimal = Decimal("0.15")
    live_conditional_max_scanner_premium: Decimal = Decimal("0.12")
    live_conditional_allow_extreme_asymmetry: bool = False
    live_conditional_allow_high_price_ceiling_bypass: bool = False
    live_conditional_high_price_ceiling_max: Decimal = Decimal("0.70")
    live_ev_timing_bypass_enabled: bool = True
    live_ev_extra_entries_per_product_per_session: int = 0
    live_ev_extra_open_positions_per_product: int = 0
    live_candidate_funnel_diagnostics_enabled: bool = False


class _FixedEntryRiskManager:
    def __init__(self, *, stake_dollars: Decimal) -> None:
        self._stake_dollars = stake_dollars

    def evaluate_entry_risk(self, **kwargs):  # noqa: ANN003,ARG002
        return RiskDecision(
            allowed=True,
            reason="allowed",
            stake_dollars=self._stake_dollars,
        )


if __name__ == "__main__":
    raise SystemExit(main())
