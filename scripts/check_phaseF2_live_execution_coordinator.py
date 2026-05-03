"""Validate Phase F2 dry-run live execution coordinator behavior."""

from __future__ import annotations

import argparse
import json
import sys
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
    failures.extend(_validate_midpoint_fallback_price_below_minimum_skip())
    failures.extend(_validate_midpoint_fallback_price_above_maximum_skip())
    failures.extend(_validate_end_window_blocks_early_contract())
    failures.extend(_validate_end_window_allows_late_contract())
    failures.extend(_validate_end_window_skips_missing_close_time())
    failures.extend(_validate_direct_contract_scan_count_below_one_skip())

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
        expected_reason="executable_price_above_maximum",
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
                yes_bid_size=Decimal("50"),
                yes_ask_size=Decimal("10"),
                orderbook_seq=123,
            )
            if market_snapshot is True
            else market_snapshot
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(
                _contract(
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


def _coordinator(
    temp_path: Path,
    settings: "_Settings | None" = None,
    risk_manager=None,  # noqa: ANN001
) -> LiveExecutionCoordinator:
    return LiveExecutionCoordinator(
        settings=settings
        or _Settings(
            log_directory=temp_path,
            log_jsonl_enabled=True,
        ),
        risk_manager=risk_manager,
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
) -> ScannedContract:
    return ScannedContract(
        product_id=product_id,
        market_ticker=market_ticker,
        direction=direction,
        structure="trend",
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
        contract_close_time=contract_close_time,
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


def _future_time(*, minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


@dataclass(frozen=True)
class _Settings:
    log_directory: Path
    log_jsonl_enabled: bool
    live_entry_end_window_only: bool = False
    live_entry_end_window_minutes: int = 5


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
