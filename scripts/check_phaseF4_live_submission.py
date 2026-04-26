"""Validate Phase F4 guarded live submission behavior with offline fixtures."""

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

from kalshi_bot.clients.kalshi_client import KalshiOrderSummary  # noqa: E402
from kalshi_bot.execution.execution_engine import LiveOrderIntent  # noqa: E402
from kalshi_bot.execution.live_execution_coordinator import LiveExecutionCoordinator  # noqa: E402
from kalshi_bot.risk.risk_manager import RiskManager  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate Phase F4 guarded live submission behavior."
    )
    parser.parse_args()

    failures: list[str] = []
    failures.extend(_validate_live_disabled_blocks_submission())
    failures.extend(_validate_unapproved_intent_blocks_submission())
    failures.extend(_validate_kill_switch_blocks_submission())
    failures.extend(_validate_non_prod_blocks_submission())
    failures.extend(_validate_count_cap_blocks_submission())
    failures.extend(_validate_allowed_fake_flow())

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1

    print("Phase F4 guarded live submission checks succeeded.")
    return 0


def _validate_live_disabled_blocks_submission() -> list[str]:
    result, state = _run_submission(
        intent=_intent(count=1, risk_approved=True),
        risk_manager=_risk_manager(live_trading_enabled=False),
    )
    return _assert_blocked(
        result=result,
        state=state,
        expected_reason="live_trading_not_enabled",
    )


def _validate_unapproved_intent_blocks_submission() -> list[str]:
    result, state = _run_submission(
        intent=_intent(count=1),
        risk_manager=_risk_manager(),
    )
    return _assert_blocked(
        result=result,
        state=state,
        expected_reason="live_intent_not_risk_approved",
    )


def _validate_kill_switch_blocks_submission() -> list[str]:
    result, state = _run_submission(
        intent=_intent(count=1, risk_approved=True),
        risk_manager=_risk_manager(live_kill_switch_active=True),
    )
    return _assert_blocked(
        result=result,
        state=state,
        expected_reason="kill_switch_active",
    )


def _validate_non_prod_blocks_submission() -> list[str]:
    result, state = _run_submission(
        intent=_intent(count=1, risk_approved=True),
        risk_manager=_risk_manager(env="demo"),
    )
    return _assert_blocked(
        result=result,
        state=state,
        expected_reason="live_env_not_prod",
    )


def _validate_count_cap_blocks_submission() -> list[str]:
    result, state = _run_submission(
        intent=_intent(count=2, risk_approved=True),
        risk_manager=_risk_manager(),
    )
    return _assert_blocked(
        result=result,
        state=state,
        expected_reason="order_count_exceeds_phase10_cap",
    )


def _validate_allowed_fake_flow() -> list[str]:
    result, state = _run_submission(
        intent=_intent(
            count=1,
            client_order_id="sim-live-allowed",
            risk_approved=True,
        ),
        risk_manager=_risk_manager(),
        created_order=_order_summary(
            order_id="ord-live-allowed",
            client_order_id="sim-live-allowed",
            status="resting",
            fill_count_fp="0.00",
            remaining_count_fp="1.00",
            initial_count_fp="1.00",
        ),
        polled_orders=[
            _order_summary(
                order_id="ord-live-allowed",
                client_order_id="sim-live-allowed",
                status="resting",
                fill_count_fp="0.00",
                remaining_count_fp="1.00",
                initial_count_fp="1.00",
            ),
            _order_summary(
                order_id="ord-live-allowed",
                client_order_id="sim-live-allowed",
                status="executed",
                fill_count_fp="1.00",
                remaining_count_fp="0.00",
                initial_count_fp="1.00",
            ),
        ],
    )

    failures: list[str] = []
    if result.classification != "filled":
        failures.append(f"allowed classification={result.classification}")
    if not result.order_placed:
        failures.append("allowed flow did not place order")
    if state.create_order_calls != 1:
        failures.append(f"allowed create_order_calls={state.create_order_calls}")
    if state.get_order_calls != 2:
        failures.append(f"allowed get_order_calls={state.get_order_calls}")
    if not _has_event(state.runtime_records, "live_order_submitted"):
        failures.append("allowed live_order_submitted log missing")
    if not _has_event(state.runtime_records, "live_order_final_state"):
        failures.append("allowed live_order_final_state log missing")
    if not state.replay_written:
        failures.append("allowed flow did not write replay artifact")
    return failures


def _assert_blocked(*, result, state, expected_reason: str) -> list[str]:
    failures: list[str] = []
    if result.classification != "blocked_by_safeguard":
        failures.append(f"blocked classification={result.classification}")
    if result.decision_reason != expected_reason:
        failures.append(f"blocked reason={result.decision_reason}")
    if result.order_placed:
        failures.append("blocked flow placed order")
    if state.create_order_calls != 0:
        failures.append(f"blocked create_order_calls={state.create_order_calls}")
    if state.get_order_calls != 0:
        failures.append(f"blocked get_order_calls={state.get_order_calls}")
    payload = _first_event_payload(state.runtime_records, "live_submission_blocked")
    if payload is None:
        failures.append("blocked live_submission_blocked log missing")
    elif payload.get("reason") != expected_reason:
        failures.append(f"blocked log reason={payload.get('reason')}")
    return failures


def _run_submission(
    *,
    intent: LiveOrderIntent,
    risk_manager: RiskManager,
    created_order: KalshiOrderSummary | None = None,
    polled_orders: list[KalshiOrderSummary] | None = None,
):
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        fake_client = _FakeKalshiClient(
            created_order=created_order,
            polled_orders=polled_orders,
        )
        coordinator = LiveExecutionCoordinator(
            settings=_Settings(
                log_directory=temp_path / "logs",
                log_jsonl_enabled=True,
                replay_directory=temp_path / "replay",
                replay_write_enabled=True,
                live_validation_time_in_force="immediate_or_cancel",
                live_validation_poll_attempts=3,
                live_validation_poll_interval_seconds=0.001,
            ),
            client=fake_client,
            risk_manager=risk_manager,
            sleep_fn=lambda _: None,
        )
        result = coordinator.submit_live_order(intent)
        state = _FixtureState(
            create_order_calls=fake_client.create_order_calls,
            get_order_calls=fake_client.get_order_calls,
            runtime_records=_jsonl_records(temp_path / "logs" / "runtime.jsonl"),
            replay_written=(temp_path / "replay" / "replay.jsonl").exists(),
        )
        return result, state


def _intent(
    *,
    count: int,
    client_order_id: str = "sim-live-0001",
    risk_approved: bool = False,
) -> LiveOrderIntent:
    return LiveOrderIntent(
        product_id="BTC-USD",
        ticker="KXBTC15M-TEST",
        action="buy",
        side="yes",
        price_dollars=Decimal("0.50"),
        count=count,
        client_order_id=client_order_id,
        stake_dollars=Decimal("0.50") * count,
        direction="up",
        confidence=70,
        simulation_position_id="sim-0001",
        risk_approved=risk_approved,
        risk_approval_source=(
            "simulation_entry_risk_gate" if risk_approved else None
        ),
    )


def _risk_manager(
    *,
    live_validation_enabled: bool = True,
    live_trading_enabled: bool = True,
    live_kill_switch_active: bool = False,
    env: str = "prod",
    live_validation_env: str = "prod",
) -> RiskManager:
    return RiskManager(
        live_validation_enabled=live_validation_enabled,
        live_trading_enabled=live_trading_enabled,
        live_kill_switch_active=live_kill_switch_active,
        env=env,
        live_validation_env=live_validation_env,
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


def _has_event(records: tuple[dict[str, object], ...], event_type: str) -> bool:
    return any(record.get("event_type") == event_type for record in records)


class _FakeKalshiClient:
    def __init__(
        self,
        *,
        created_order: KalshiOrderSummary | None,
        polled_orders: list[KalshiOrderSummary] | None,
    ) -> None:
        self._created_order = created_order
        self._polled_orders = list(polled_orders or [])
        self.create_order_calls = 0
        self.get_order_calls = 0

    def create_order(self, order_request) -> KalshiOrderSummary:
        self.create_order_calls += 1
        if self._created_order is not None:
            return self._created_order
        return _order_summary(
            order_id="ord-default",
            client_order_id=order_request.client_order_id,
            status="executed",
            fill_count_fp=str(order_request.count),
            remaining_count_fp="0.00",
            initial_count_fp=str(order_request.count),
        )

    def get_order(self, order_id: str) -> KalshiOrderSummary:
        self.get_order_calls += 1
        if self._polled_orders:
            return self._polled_orders.pop(0)
        return _order_summary(
            order_id=order_id,
            client_order_id="sim-live-default",
            status="executed",
            fill_count_fp="1.00",
            remaining_count_fp="0.00",
            initial_count_fp="1.00",
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
    create_order_calls: int
    get_order_calls: int
    runtime_records: tuple[dict[str, object], ...]
    replay_written: bool


if __name__ == "__main__":
    raise SystemExit(main())
