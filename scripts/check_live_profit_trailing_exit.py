"""Validate optional live profit trailing exit behavior with offline fixtures."""

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
from kalshi_bot.execution.live_execution_coordinator import (  # noqa: E402
    LiveExecutionCoordinator,
)
from kalshi_bot.market.market_state_cache import (  # noqa: E402
    MarketStateSnapshot,
    TickerState,
)
from kalshi_bot.risk.risk_manager import RiskManager  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate optional live profit trailing exit behavior."
    )
    parser.parse_args()

    failures: list[str] = []
    failures.extend(_validate_default_off_does_nothing())
    failures.extend(_validate_activation_requires_threshold())
    failures.extend(_validate_peak_updates())
    failures.extend(_validate_drop_triggers_sell_ioc())
    failures.extend(_validate_no_position_uses_derived_no_bid())
    failures.extend(_validate_missing_bid_skips())
    failures.extend(_validate_partial_sell_sets_pending_until_reconciliation())
    failures.extend(_validate_position_size_is_never_oversold())
    failures.extend(_validate_live_max_order_count_caps_sell_count())
    failures.extend(_validate_live_safety_blocks_sell_order())

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1

    print("Live profit trailing exit checks succeeded.")
    return 0


def _validate_default_off_does_nothing() -> list[str]:
    state = _run_cycles(
        settings=_Settings(live_profit_trailing_exit_enabled=False),
        positions=[_position("1.00")],
        bids=[Decimal("0.95")],
    )
    failures: list[str] = []
    if state.create_order_calls != 0:
        failures.append("default-off created sell order")
    if _has_event(state.runtime_records, "profit_trailing_exit_armed"):
        failures.append("default-off wrote trailing logs")
    return failures


def _validate_activation_requires_threshold() -> list[str]:
    state = _run_cycles(
        settings=_Settings(live_profit_trailing_exit_enabled=True),
        positions=[_position("1.00"), _position("1.00")],
        bids=[Decimal("0.89"), Decimal("0.90")],
    )
    failures: list[str] = []
    if state.create_order_calls != 0:
        failures.append("activation-threshold created order")
    if _event_count(state.runtime_records, "profit_trailing_exit_armed") != 1:
        failures.append("activation-threshold armed count incorrect")
    return failures


def _validate_peak_updates() -> list[str]:
    state = _run_cycles(
        settings=_Settings(live_profit_trailing_exit_enabled=True),
        positions=[_position("1.00"), _position("1.00")],
        bids=[Decimal("0.90"), Decimal("0.95")],
    )
    failures: list[str] = []
    payload = _first_event_payload(state.runtime_records, "profit_trailing_peak_updated")
    if payload is None:
        failures.append("peak update log missing")
    elif Decimal(str(payload.get("peak_exit_bid"))) != Decimal("0.95"):
        failures.append(f"peak update value={payload.get('peak_exit_bid')}")
    if state.create_order_calls != 0:
        failures.append("peak update submitted order")
    return failures


def _validate_drop_triggers_sell_ioc() -> list[str]:
    state = _run_cycles(
        settings=_Settings(live_profit_trailing_exit_enabled=True),
        positions=[_position("1.00"), _position("1.00"), _position("1.00")],
        bids=[Decimal("0.90"), Decimal("0.95"), Decimal("0.94")],
        created_order=_order_summary(
            order_id="profit-order-1",
            client_order_id="profit-trail-3-KXBTC15M-TEST-yes",
            status="executed",
            fill_count_fp="1.00",
            remaining_count_fp="0.00",
            initial_count_fp="1.00",
        ),
    )
    failures: list[str] = []
    if state.create_order_calls != 1:
        failures.append(f"trigger create_order_calls={state.create_order_calls}")
    order = state.submitted_orders[0] if state.submitted_orders else None
    if order is None:
        failures.append("trigger submitted order missing")
    else:
        if order.action != "sell":
            failures.append(f"trigger action={order.action}")
        if order.side != "yes":
            failures.append(f"trigger side={order.side}")
        if order.price_dollars != Decimal("0.94"):
            failures.append(f"trigger price={order.price_dollars}")
        if order.count != 1:
            failures.append(f"trigger count={order.count}")
        if order.time_in_force != "immediate_or_cancel":
            failures.append(f"trigger tif={order.time_in_force}")
    if not _has_event(state.runtime_records, "profit_trailing_exit_triggered"):
        failures.append("trigger log missing")
    response = _first_event_payload(
        state.runtime_records,
        "profit_trailing_exit_order_response",
    )
    if response is None:
        failures.append("trigger order response log missing")
    elif response.get("classification") != "filled":
        failures.append(f"trigger classification={response.get('classification')}")
    return failures


def _validate_no_position_uses_derived_no_bid() -> list[str]:
    state = _run_cycles(
        settings=_Settings(live_profit_trailing_exit_enabled=True),
        positions=[_position("-1.00"), _position("-1.00"), _position("-1.00")],
        bids=[Decimal("0.01"), Decimal("0.01"), Decimal("0.01")],
        yes_asks=[Decimal("0.10"), Decimal("0.05"), Decimal("0.06")],
        created_order=_order_summary(
            order_id="profit-order-no",
            client_order_id="profit-trail-3-KXBTC15M-TEST-no",
            status="executed",
            fill_count_fp="1.00",
            remaining_count_fp="0.00",
            initial_count_fp="1.00",
            side="no",
        ),
    )
    failures: list[str] = []
    order = state.submitted_orders[0] if state.submitted_orders else None
    if order is None:
        failures.append("no-side submitted order missing")
    else:
        if order.side != "no":
            failures.append(f"no-side side={order.side}")
        if order.price_dollars != Decimal("0.94"):
            failures.append(f"no-side price={order.price_dollars}")
    return failures


def _validate_missing_bid_skips() -> list[str]:
    state = _run_cycles(
        settings=_Settings(live_profit_trailing_exit_enabled=True),
        positions=[_position("1.00")],
        bids=[None],
    )
    failures: list[str] = []
    if state.create_order_calls != 0:
        failures.append("missing bid created order")
    payload = _first_event_payload(state.runtime_records, "profit_trailing_exit_skipped")
    if payload is None:
        failures.append("missing bid skip log missing")
    elif payload.get("reason") != "executable_exit_bid_missing":
        failures.append(f"missing bid reason={payload.get('reason')}")
    return failures


def _validate_partial_sell_sets_pending_until_reconciliation() -> list[str]:
    state = _run_cycles(
        settings=_Settings(live_profit_trailing_exit_enabled=True),
        positions=[
            _position("1.00"),
            _position("1.00"),
            _position("1.00"),
            _position("0.50"),
        ],
        bids=[
            Decimal("0.90"),
            Decimal("0.95"),
            Decimal("0.94"),
            Decimal("0.95"),
        ],
        created_order=_order_summary(
            order_id="profit-order-partial",
            client_order_id="profit-trail-3-KXBTC15M-TEST-yes",
            status="executed",
            fill_count_fp="0.50",
            remaining_count_fp="0.50",
            initial_count_fp="1.00",
        ),
    )
    failures: list[str] = []
    response = _first_event_payload(
        state.runtime_records,
        "profit_trailing_exit_order_response",
    )
    if response is None:
        failures.append("partial response missing")
    elif response.get("classification") != "partially_filled":
        failures.append(f"partial classification={response.get('classification')}")
    if _event_count(state.runtime_records, "profit_trailing_exit_armed") < 2:
        failures.append("partial remaining position did not re-arm after reconciliation")
    return failures


def _validate_position_size_is_never_oversold() -> list[str]:
    state = _run_cycles(
        settings=_Settings(live_profit_trailing_exit_enabled=True),
        positions=[_position("0.50"), _position("0.50"), _position("0.50")],
        bids=[Decimal("0.90"), Decimal("0.95"), Decimal("0.94")],
    )
    failures: list[str] = []
    if state.create_order_calls != 0:
        failures.append("fractional position created sell order")
    payload = _first_event_payload(state.runtime_records, "profit_trailing_exit_skipped")
    if payload is None:
        failures.append("fractional sell skip missing")
    elif payload.get("reason") != "sell_count_unavailable":
        failures.append(f"fractional sell reason={payload.get('reason')}")
    return failures


def _validate_live_max_order_count_caps_sell_count() -> list[str]:
    state = _run_cycles(
        settings=_Settings(
            live_profit_trailing_exit_enabled=True,
            live_max_order_count=2,
        ),
        positions=[_position("5.00"), _position("5.00"), _position("5.00")],
        bids=[Decimal("0.90"), Decimal("0.95"), Decimal("0.94")],
        risk_manager=_risk_manager(max_live_order_count=2),
        created_order=_order_summary(
            order_id="profit-order-cap",
            client_order_id="profit-trail-3-KXBTC15M-TEST-yes",
            status="executed",
            fill_count_fp="2.00",
            remaining_count_fp="0.00",
            initial_count_fp="2.00",
        ),
    )
    failures: list[str] = []
    order = state.submitted_orders[0] if state.submitted_orders else None
    if order is None:
        failures.append("cap submitted order missing")
    elif order.count != 2:
        failures.append(f"cap sell count={order.count}")
    return failures


def _validate_live_safety_blocks_sell_order() -> list[str]:
    state = _run_cycles(
        settings=_Settings(live_profit_trailing_exit_enabled=True),
        positions=[_position("1.00"), _position("1.00"), _position("1.00")],
        bids=[Decimal("0.90"), Decimal("0.95"), Decimal("0.94")],
        risk_manager=_risk_manager(live_kill_switch_active=True),
    )
    failures: list[str] = []
    if state.create_order_calls != 0:
        failures.append("safety-block created order")
    payload = _first_event_payload(state.runtime_records, "profit_trailing_exit_skipped")
    matching = [
        record.get("payload", {})
        for record in state.runtime_records
        if record.get("event_type") == "profit_trailing_exit_skipped"
        and record.get("payload", {}).get("reason") == "live_safety_blocked"
    ]
    if not matching:
        failures.append("safety-block skip log missing")
    elif matching[0].get("live_safety_reason") != "kill_switch_active":
        failures.append(
            f"safety-block reason={matching[0].get('live_safety_reason')}"
        )
    if payload is None:
        failures.append("safety-block no skip logs")
    return failures


def _run_cycles(
    *,
    settings: "_Settings",
    positions: list[KalshiMarketPosition],
    bids: list[Decimal | None],
    yes_asks: list[Decimal | None] | None = None,
    risk_manager: RiskManager | None = None,
    created_order: KalshiOrderSummary | None = None,
) -> "_FixtureState":
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        settings.log_directory = temp_path / "logs"
        settings.replay_directory = temp_path / "replay"
        fake_client = _FakeKalshiClient(created_order=created_order)
        coordinator = LiveExecutionCoordinator(
            settings=settings,
            client=fake_client,
            risk_manager=risk_manager or _risk_manager(),
            sleep_fn=lambda _: None,
        )
        for index, bid in enumerate(bids):
            fake_client.positions = (positions[min(index, len(positions) - 1)],)
            yes_ask = (
                yes_asks[min(index, len(yes_asks) - 1)]
                if yes_asks is not None
                else Decimal("0.96")
            )
            coordinator.process_profit_trailing_exits(
                _market_snapshot(yes_bid=bid, yes_ask=yes_ask),
                cycle_number=index + 1,
            )
        return _FixtureState(
            create_order_calls=fake_client.create_order_calls,
            submitted_orders=tuple(fake_client.submitted_orders),
            runtime_records=_jsonl_records(temp_path / "logs" / "runtime.jsonl"),
        )


def _market_snapshot(
    *,
    yes_bid: Decimal | None,
    yes_ask: Decimal | None,
) -> MarketStateSnapshot:
    return MarketStateSnapshot(
        tickers={
            "KXBTC15M-TEST": TickerState(
                market_ticker="KXBTC15M-TEST",
                yes_bid_dollars=yes_bid,
                yes_ask_dollars=yes_ask,
                yes_bid_size_fp=Decimal("100") if yes_bid is not None else None,
                yes_ask_size_fp=Decimal("100") if yes_ask is not None else None,
            )
        },
        orderbooks={},
        last_sequence_by_sid={},
    )


def _position(position_fp: str) -> KalshiMarketPosition:
    return KalshiMarketPosition(
        ticker="KXBTC15M-TEST",
        position_fp=Decimal(position_fp),
        market_exposure_dollars=Decimal("1.00"),
        resting_orders_count=0,
        last_updated_ts="2026-04-23T12:00:00Z",
    )


def _order_summary(
    *,
    order_id: str,
    client_order_id: str,
    status: str,
    fill_count_fp: str,
    remaining_count_fp: str,
    initial_count_fp: str,
    side: str = "yes",
) -> KalshiOrderSummary:
    return KalshiOrderSummary(
        order_id=order_id,
        client_order_id=client_order_id,
        ticker="KXBTC15M-TEST",
        side=side,
        action="sell",
        order_type="limit",
        status=status,
        yes_price_dollars=Decimal("0.94") if side == "yes" else None,
        no_price_dollars=Decimal("0.94") if side == "no" else None,
        fill_count_fp=Decimal(fill_count_fp),
        remaining_count_fp=Decimal(remaining_count_fp),
        initial_count_fp=Decimal(initial_count_fp),
        created_time="2026-04-23T12:00:00Z",
        last_update_time="2026-04-23T12:00:01Z",
    )


def _risk_manager(
    *,
    max_live_order_count: int = 1,
    live_kill_switch_active: bool = False,
) -> RiskManager:
    return RiskManager(
        live_validation_enabled=True,
        live_trading_enabled=True,
        live_kill_switch_active=live_kill_switch_active,
        env="prod",
        live_validation_env="prod",
        max_live_order_count=max_live_order_count,
        required_time_in_force="immediate_or_cancel",
    )


def _jsonl_records(path: Path) -> tuple[dict[str, object], ...]:
    if not path.exists():
        return ()
    return tuple(
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    )


def _has_event(records: tuple[dict[str, object], ...], event_type: str) -> bool:
    return any(record.get("event_type") == event_type for record in records)


def _event_count(records: tuple[dict[str, object], ...], event_type: str) -> int:
    return sum(1 for record in records if record.get("event_type") == event_type)


def _first_event_payload(
    records: tuple[dict[str, object], ...],
    event_type: str,
) -> dict[str, object] | None:
    for record in records:
        if record.get("event_type") == event_type:
            payload = record.get("payload")
            if isinstance(payload, dict):
                return payload
    return None


@dataclass(frozen=True)
class _FixtureState:
    create_order_calls: int
    submitted_orders: tuple[object, ...]
    runtime_records: tuple[dict[str, object], ...]


class _FakeKalshiClient:
    def __init__(self, *, created_order: KalshiOrderSummary | None = None) -> None:
        self.positions: tuple[KalshiMarketPosition, ...] = ()
        self._created_order = created_order
        self.create_order_calls = 0
        self.submitted_orders: list[object] = []

    def get_positions(self, **_kwargs) -> KalshiPositionPage:  # noqa: ANN003
        return KalshiPositionPage(market_positions=self.positions, cursor=None)

    def create_order(self, order):  # noqa: ANN001
        self.create_order_calls += 1
        self.submitted_orders.append(order)
        if self._created_order is not None:
            return self._created_order
        return _order_summary(
            order_id=f"profit-order-{self.create_order_calls}",
            client_order_id=order.client_order_id,
            status="executed",
            fill_count_fp=str(order.count),
            remaining_count_fp="0.00",
            initial_count_fp=str(order.count),
        )

    def get_order(self, order_id: str) -> KalshiOrderSummary:
        raise AssertionError(f"unexpected get_order call for {order_id}")


@dataclass
class _Settings:
    live_profit_trailing_exit_enabled: bool = False
    live_profit_trailing_activation_price: Decimal = Decimal("0.90")
    live_profit_trailing_drop_dollars: Decimal = Decimal("0.01")
    live_profit_exit_min_bid: Decimal = Decimal("0.90")
    live_max_order_count: int = 1
    live_validation_time_in_force: str = "immediate_or_cancel"
    live_validation_poll_attempts: int = 1
    live_validation_poll_interval_seconds: float = 0.001
    log_directory: Path = Path("logs")
    log_jsonl_enabled: bool = True
    replay_directory: Path = Path("replay")
    replay_write_enabled: bool = True


if __name__ == "__main__":
    raise SystemExit(main())
