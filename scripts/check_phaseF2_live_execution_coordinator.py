"""Validate Phase F2 dry-run live execution coordinator behavior."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
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
        coordinator = _coordinator(temp_path)
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(
                _contract(
                    market_ticker="KXBTC15M-DIRECT",
                    midpoint=Decimal("0.10"),
                )
            ),
            cycle_number=42,
        )
        failures: list[str] = []
        if len(intents) != 1:
            failures.append(f"direct intent count={len(intents)} expected=1")
            return failures
        intent = intents[0]
        if intent.risk_approval_source != "live_entry_risk_gate":
            failures.append(f"direct risk source={intent.risk_approval_source}")
        if intent.count != 2:
            failures.append(f"direct count={intent.count} expected=2")
        payload = _first_event_payload(
            _jsonl_records(temp_path / "runtime.jsonl"),
            event_type="live_intent_created",
        )
        if payload is None:
            failures.append("direct live_intent_created log missing")
        elif payload.get("ticker") != "KXBTC15M-DIRECT":
            failures.append(f"direct log ticker={payload.get('ticker')}")
        return failures


def _validate_direct_contract_scan_count_below_one_skip() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(temp_path)
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(_contract(midpoint=Decimal("0.46"))),
            cycle_number=43,
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


def _coordinator(temp_path: Path) -> LiveExecutionCoordinator:
    return LiveExecutionCoordinator(
        settings=_Settings(
            log_directory=temp_path,
            log_jsonl_enabled=True,
        )
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


@dataclass(frozen=True)
class _Settings:
    log_directory: Path
    log_jsonl_enabled: bool


if __name__ == "__main__":
    raise SystemExit(main())
