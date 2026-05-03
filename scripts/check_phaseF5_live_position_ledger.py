"""Validate Phase F5 live position ledger behavior with offline fixtures."""

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

from kalshi_bot.clients.kalshi_client import (  # noqa: E402
    KalshiMarketPosition,
    KalshiOrderSummary,
    KalshiPositionPage,
)
from kalshi_bot.execution.execution_engine import LiveOrderIntent  # noqa: E402
from kalshi_bot.execution.live_execution_coordinator import LiveExecutionCoordinator  # noqa: E402
from kalshi_bot.risk.risk_manager import RiskManager  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate Phase F5 live position ledger behavior."
    )
    parser.parse_args()

    failures: list[str] = []
    failures.extend(_validate_filled_order_opens_ledger_position())
    failures.extend(_validate_partial_fill_opens_partial_position())
    failures.extend(_validate_rejected_order_records_no_open_position())
    failures.extend(_validate_canceled_partial_fill_preserves_partial_position())
    failures.extend(_validate_unknown_state_records_only())
    failures.extend(_validate_reconciliation_removes_stale_position())
    failures.extend(_validate_reconciliation_recalculates_active_exposure())

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1

    print("Phase F5 live position ledger checks succeeded.")
    return 0


def _validate_filled_order_opens_ledger_position() -> list[str]:
    state = _run_submission(
        client_order_id="sim-live-filled",
        polled_orders=[
            _order_summary(
                order_id="ord-filled",
                client_order_id="sim-live-filled",
                status="executed",
                fill_count_fp="1.00",
                remaining_count_fp="0.00",
                initial_count_fp="1.00",
            ),
        ],
    )
    failures = _assert_record(
        state=state,
        client_order_id="sim-live-filled",
        classification="filled",
        filled_count=Decimal("1.00"),
    )
    if not _has_event(state.runtime_records, "live_position_opened"):
        failures.append("filled live_position_opened log missing")
    return failures


def _validate_partial_fill_opens_partial_position() -> list[str]:
    state = _run_submission(
        client_order_id="sim-live-partial",
        polled_orders=[
            _order_summary(
                order_id="ord-partial",
                client_order_id="sim-live-partial",
                status="executed",
                fill_count_fp="0.50",
                remaining_count_fp="0.50",
                initial_count_fp="1.00",
            ),
        ],
    )
    failures = _assert_record(
        state=state,
        client_order_id="sim-live-partial",
        classification="partially_filled",
        filled_count=Decimal("0.50"),
    )
    if not _has_event(state.runtime_records, "live_position_opened"):
        failures.append("partial live_position_opened log missing")
    return failures


def _validate_rejected_order_records_no_open_position() -> list[str]:
    state = _run_submission(
        client_order_id="sim-live-rejected",
        polled_orders=[
            _order_summary(
                order_id="ord-rejected",
                client_order_id="sim-live-rejected",
                status="rejected",
                fill_count_fp="0.00",
                remaining_count_fp="1.00",
                initial_count_fp="1.00",
            ),
        ],
    )
    failures = _assert_record(
        state=state,
        client_order_id="sim-live-rejected",
        classification="rejected",
        filled_count=Decimal("0.00"),
    )
    if _has_event(state.runtime_records, "live_position_opened"):
        failures.append("rejected order wrote live_position_opened")
    if not _has_event(state.runtime_records, "live_order_rejected"):
        failures.append("rejected live_order_rejected log missing")
    return failures


def _validate_canceled_partial_fill_preserves_partial_position() -> list[str]:
    state = _run_submission(
        client_order_id="sim-live-canceled-partial",
        polled_orders=[
            _order_summary(
                order_id="ord-canceled-partial",
                client_order_id="sim-live-canceled-partial",
                status="canceled",
                fill_count_fp="0.25",
                remaining_count_fp="0.75",
                initial_count_fp="1.00",
            ),
        ],
    )
    failures = _assert_record(
        state=state,
        client_order_id="sim-live-canceled-partial",
        classification="canceled_or_expired",
        filled_count=Decimal("0.25"),
    )
    if not _has_event(state.runtime_records, "live_position_opened"):
        failures.append("canceled partial live_position_opened log missing")
    if not _has_event(state.runtime_records, "live_order_canceled_or_expired"):
        failures.append("canceled partial live_order_canceled_or_expired log missing")
    return failures


def _validate_unknown_state_records_only() -> list[str]:
    state = _run_submission(
        client_order_id="sim-live-unknown",
        polled_orders=[
            _order_summary(
                order_id="ord-unknown",
                client_order_id="sim-live-unknown",
                status="resting",
                fill_count_fp="0.00",
                remaining_count_fp="1.00",
                initial_count_fp="1.00",
            ),
        ],
    )
    failures = _assert_record(
        state=state,
        client_order_id="sim-live-unknown",
        classification="unknown_final_state",
        filled_count=Decimal("0.00"),
    )
    if _has_event(state.runtime_records, "live_position_opened"):
        failures.append("unknown state wrote live_position_opened")
    if not _has_event(state.runtime_records, "live_order_unknown_final_state"):
        failures.append("unknown live_order_unknown_final_state log missing")
    return failures


def _validate_reconciliation_removes_stale_position() -> list[str]:
    state = _run_submission(
        client_order_id="sim-live-stale",
        polled_orders=[
            _order_summary(
                order_id="ord-stale",
                client_order_id="sim-live-stale",
                status="executed",
                fill_count_fp="1.00",
                remaining_count_fp="0.00",
                initial_count_fp="1.00",
            ),
        ],
        positions_after_submit=[],
        reconcile=True,
    )
    failures: list[str] = []
    if state.ledger:
        failures.append(f"stale reconciliation ledger={state.ledger}")
    for event_type in (
        "live_position_reconciliation_started",
        "stale_position_removed",
        "exposure_recalculated",
        "live_position_reconciliation_completed",
    ):
        if not _has_event(state.runtime_records, event_type):
            failures.append(f"stale reconciliation {event_type} log missing")
    return failures


def _validate_reconciliation_recalculates_active_exposure() -> list[str]:
    state = _run_submission(
        client_order_id="sim-live-active",
        polled_orders=[
            _order_summary(
                order_id="ord-active",
                client_order_id="sim-live-active",
                status="executed",
                fill_count_fp="1.00",
                remaining_count_fp="0.00",
                initial_count_fp="1.00",
            ),
        ],
        positions_after_submit=[
            KalshiMarketPosition(
                ticker="KXBTC15M-TEST",
                position_fp=Decimal("1"),
                market_exposure_dollars=Decimal("0.25"),
                resting_orders_count=None,
                last_updated_ts=None,
            )
        ],
        reconcile=True,
    )
    failures: list[str] = []
    if "sim-live-active" not in state.ledger:
        failures.append("active reconciliation removed active ledger record")
    if state.live_exposure_dollars != Decimal("0.25"):
        failures.append(
            f"active reconciliation exposure={state.live_exposure_dollars}"
        )
    payload = _first_event_payload(state.runtime_records, "exposure_recalculated")
    if payload is None:
        failures.append("active reconciliation exposure_recalculated log missing")
    elif payload.get("current_exposure_dollars_after") != "0.25":
        failures.append(
            "active reconciliation logged exposure="
            f"{payload.get('current_exposure_dollars_after')}"
        )
    return failures


def _assert_record(
    *,
    state: "_FixtureState",
    client_order_id: str,
    classification: str,
    filled_count: Decimal,
) -> list[str]:
    record = state.ledger.get(client_order_id)
    if record is None:
        return [f"{client_order_id} ledger record missing"]
    failures: list[str] = []
    if record.classification != classification:
        failures.append(f"{client_order_id} classification={record.classification}")
    if record.filled_count != filled_count:
        failures.append(f"{client_order_id} filled_count={record.filled_count}")
    if record.product_id != "BTC-USD":
        failures.append(f"{client_order_id} product_id={record.product_id}")
    if record.simulation_position_id != "sim-0001":
        failures.append(
            f"{client_order_id} simulation_position_id={record.simulation_position_id}"
        )
    if not _has_event(state.runtime_records, "live_position_ledger_updated"):
        failures.append(f"{client_order_id} live_position_ledger_updated log missing")
    if not state.replay_written:
        failures.append(f"{client_order_id} replay artifact missing")
    return failures


def _run_submission(
    *,
    client_order_id: str,
    polled_orders: list[KalshiOrderSummary],
    positions_after_submit: list[KalshiMarketPosition] | None = None,
    reconcile: bool = False,
) -> "_FixtureState":
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        fake_client = _FakeKalshiClient(
            created_order=_order_summary(
                order_id=polled_orders[0].order_id,
                client_order_id=client_order_id,
                status="resting",
                fill_count_fp="0.00",
                remaining_count_fp="1.00",
                initial_count_fp="1.00",
            ),
            polled_orders=polled_orders,
            positions=positions_after_submit or [],
        )
        coordinator = LiveExecutionCoordinator(
            settings=_Settings(
                log_directory=temp_path / "logs",
                log_jsonl_enabled=True,
                replay_directory=temp_path / "replay",
                replay_write_enabled=True,
                live_validation_time_in_force="immediate_or_cancel",
                live_validation_poll_attempts=1,
                live_validation_poll_interval_seconds=0.001,
            ),
            client=fake_client,
            risk_manager=_risk_manager(),
            sleep_fn=lambda _: None,
        )
        coordinator.submit_live_order(_intent(client_order_id=client_order_id))
        if reconcile:
            coordinator.reconcile_live_positions(cycle_number=1, reason="fixture")
        return _FixtureState(
            ledger=coordinator.live_position_ledger,
            live_exposure_dollars=coordinator._live_current_exposure_dollars(),  # noqa: SLF001
            runtime_records=_jsonl_records(temp_path / "logs" / "runtime.jsonl"),
            replay_written=(temp_path / "replay" / "replay.jsonl").exists(),
        )


def _intent(*, client_order_id: str) -> LiveOrderIntent:
    return LiveOrderIntent(
        product_id="BTC-USD",
        ticker="KXBTC15M-TEST",
        action="buy",
        side="yes",
        price_dollars=Decimal("0.50"),
        count=1,
        client_order_id=client_order_id,
        stake_dollars=Decimal("0.50"),
        direction="up",
        confidence=70,
        simulation_position_id="sim-0001",
        risk_approved=True,
        risk_approval_source="simulation_entry_risk_gate",
    )


def _risk_manager() -> RiskManager:
    return RiskManager(
        live_validation_enabled=True,
        live_trading_enabled=True,
        live_kill_switch_active=False,
        env="prod",
        live_validation_env="prod",
        max_live_order_count=1,
        required_time_in_force="immediate_or_cancel",
    )


def _order_summary(
    *,
    order_id: str,
    client_order_id: str,
    status: str,
    fill_count_fp: str,
    remaining_count_fp: str,
    initial_count_fp: str,
) -> KalshiOrderSummary:
    return KalshiOrderSummary(
        order_id=order_id,
        client_order_id=client_order_id,
        ticker="KXBTC15M-TEST",
        side="yes",
        action="buy",
        order_type="limit",
        status=status,
        yes_price_dollars=Decimal("0.50"),
        no_price_dollars=None,
        fill_count_fp=Decimal(fill_count_fp),
        remaining_count_fp=Decimal(remaining_count_fp),
        initial_count_fp=Decimal(initial_count_fp),
        created_time="2026-04-23T12:00:00Z",
        last_update_time="2026-04-23T12:00:01Z",
    )


def _jsonl_records(path: Path) -> tuple[dict[str, object], ...]:
    if not path.exists():
        return ()
    records: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        records.append(json.loads(line))
    return tuple(records)


def _has_event(records: tuple[dict[str, object], ...], event_type: str) -> bool:
    return any(record.get("event_type") == event_type for record in records)


def _first_event_payload(
    records: tuple[dict[str, object], ...],
    event_type: str,
) -> dict[str, object] | None:
    for record in records:
        if record.get("event_type") != event_type:
            continue
        payload = record.get("payload")
        if isinstance(payload, dict):
            return payload
    return None


class _FakeKalshiClient:
    def __init__(
        self,
        *,
        created_order: KalshiOrderSummary,
        polled_orders: list[KalshiOrderSummary],
        positions: list[KalshiMarketPosition],
    ) -> None:
        self._created_order = created_order
        self._polled_orders = list(polled_orders)
        self._positions = positions

    def create_order(self, order_request) -> KalshiOrderSummary:
        return self._created_order

    def get_order(self, order_id: str) -> KalshiOrderSummary:
        if self._polled_orders:
            return self._polled_orders.pop(0)
        return self._created_order

    def get_positions(self, **kwargs):  # noqa: ANN003,ARG002
        return KalshiPositionPage(
            market_positions=tuple(self._positions),
            cursor=None,
        )


@dataclass(frozen=True)
class _Settings:
    log_directory: Path
    log_jsonl_enabled: bool
    replay_directory: Path
    replay_write_enabled: bool
    live_validation_time_in_force: str
    live_validation_poll_attempts: int
    live_validation_poll_interval_seconds: float


@dataclass(frozen=True)
class _FixtureState:
    ledger: dict[str, object]
    live_exposure_dollars: Decimal
    runtime_records: tuple[dict[str, object], ...]
    replay_written: bool


if __name__ == "__main__":
    raise SystemExit(main())
