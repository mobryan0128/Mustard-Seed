"""Validate optional live profit capture and trailing exit behavior."""

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
from kalshi_bot.execution.live_execution_coordinator import LiveExecutionCoordinator  # noqa: E402
from kalshi_bot.market.market_state_cache import MarketStateSnapshot, TickerState  # noqa: E402
from kalshi_bot.risk.risk_manager import LiveSafetyDecision  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate live profit capture and trailing exit behavior."
    )
    parser.parse_args()

    failures: list[str] = []
    failures.extend(_validate_default_off_does_nothing())
    failures.extend(_validate_profit_capture_sells_yes())
    failures.extend(_validate_profit_capture_sells_no())
    failures.extend(_validate_trailing_stop_sells_after_drop())
    failures.extend(_validate_missing_quote_skips())
    failures.extend(_validate_live_safety_blocks_exit())

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1

    print("Live profit capture exit checks succeeded.")
    return 0


def _validate_default_off_does_nothing() -> list[str]:
    state = _run_exit_cycles(
        settings=_Settings(),
        positions=[_position("1.00")],
        yes_bids=[Decimal("0.99")],
    )
    failures: list[str] = []
    if state.client.get_positions_calls != 0:
        failures.append("default-off fetched positions")
    if state.client.submitted_orders:
        failures.append("default-off submitted order")
    if _has_event(state.runtime_records, "profit_capture_exit_triggered"):
        failures.append("default-off wrote trigger log")
    return failures


def _validate_profit_capture_sells_yes() -> list[str]:
    state = _run_exit_cycles(
        settings=_Settings(live_profit_capture_enabled=True),
        positions=[_position("1.00")],
        yes_bids=[Decimal("0.99")],
    )
    failures: list[str] = []
    order = state.client.submitted_orders[0] if state.client.submitted_orders else None
    if order is None:
        failures.append("profit-capture submitted order missing")
    else:
        if order.action != "sell":
            failures.append(f"profit-capture action={order.action}")
        if order.side != "yes":
            failures.append(f"profit-capture side={order.side}")
        if order.price_dollars != Decimal("0.99"):
            failures.append(f"profit-capture price={order.price_dollars}")
        if order.count != 1:
            failures.append(f"profit-capture count={order.count}")
    if not _has_event(state.runtime_records, "profit_capture_exit_triggered"):
        failures.append("profit-capture trigger log missing")
    if not _has_event(state.runtime_records, "profit_capture_exit_order_response"):
        failures.append("profit-capture response log missing")
    return failures


def _validate_profit_capture_sells_no() -> list[str]:
    state = _run_exit_cycles(
        settings=_Settings(live_profit_capture_enabled=True),
        positions=[_position("-1.00")],
        yes_bids=[Decimal("0.01")],
        yes_asks=[Decimal("0.01")],
    )
    failures: list[str] = []
    order = state.client.submitted_orders[0] if state.client.submitted_orders else None
    if order is None:
        failures.append("no profit-capture submitted order missing")
    else:
        if order.side != "no":
            failures.append(f"no profit-capture side={order.side}")
        if order.price_dollars != Decimal("0.99"):
            failures.append(f"no profit-capture price={order.price_dollars}")
    return failures


def _validate_trailing_stop_sells_after_drop() -> list[str]:
    state = _run_exit_cycles(
        settings=_Settings(live_trailing_stop_enabled=True),
        positions=[_position("1.00"), _position("1.00"), _position("1.00")],
        yes_bids=[Decimal("0.99"), Decimal("1.00"), Decimal("0.95")],
    )
    failures: list[str] = []
    if len(state.client.submitted_orders) != 1:
        failures.append(f"trailing submitted={len(state.client.submitted_orders)}")
    order = state.client.submitted_orders[0] if state.client.submitted_orders else None
    if order is not None and order.price_dollars != Decimal("0.95"):
        failures.append(f"trailing price={order.price_dollars}")
    if not _has_event(state.runtime_records, "trailing_exit_armed"):
        failures.append("trailing armed log missing")
    if not _has_event(state.runtime_records, "trailing_exit_peak_updated"):
        failures.append("trailing peak log missing")
    if not _has_event(state.runtime_records, "trailing_exit_triggered"):
        failures.append("trailing trigger log missing")
    return failures


def _validate_missing_quote_skips() -> list[str]:
    state = _run_exit_cycles(
        settings=_Settings(live_profit_capture_enabled=True),
        positions=[_position("1.00")],
        yes_bids=[None],
    )
    failures: list[str] = []
    if state.client.submitted_orders:
        failures.append("missing quote submitted order")
    payload = _first_event_payload(state.runtime_records, "profit_capture_exit_skipped")
    if payload is None:
        failures.append("missing quote skip log missing")
    elif payload.get("reason") != "executable_exit_bid_missing":
        failures.append(f"missing quote reason={payload.get('reason')}")
    return failures


def _validate_live_safety_blocks_exit() -> list[str]:
    state = _run_exit_cycles(
        settings=_Settings(live_profit_capture_enabled=True),
        positions=[_position("1.00")],
        yes_bids=[Decimal("0.99")],
        risk_manager=_FakeRiskManager(allow=False, reason="kill_switch_active"),
    )
    failures: list[str] = []
    if state.client.submitted_orders:
        failures.append("safety-block submitted order")
    payload = _first_event_payload(state.runtime_records, "profit_capture_exit_skipped")
    if payload is None:
        failures.append("safety-block skip log missing")
    elif payload.get("live_safety_reason") != "kill_switch_active":
        failures.append(f"safety-block reason={payload.get('live_safety_reason')}")
    return failures


def _run_exit_cycles(
    *,
    settings: "_Settings",
    positions: list[KalshiMarketPosition],
    yes_bids: list[Decimal | None],
    yes_asks: list[Decimal | None] | None = None,
    risk_manager: "_FakeRiskManager | None" = None,
) -> "_RunState":
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        settings.log_directory = temp_path
        client = _FakeKalshiClient(positions=positions)
        coordinator = LiveExecutionCoordinator(
            settings=settings,
            client=client,
            risk_manager=risk_manager or _FakeRiskManager(),
        )
        asks = yes_asks or [Decimal("1") - bid if bid is not None else None for bid in yes_bids]
        for index, bid in enumerate(yes_bids):
            position = positions[min(index, len(positions) - 1)]
            coordinator.process_profit_capture_exits(
                _market_snapshot(
                    ticker=position.ticker,
                    yes_bid=bid,
                    yes_ask=asks[min(index, len(asks) - 1)],
                ),
                cycle_number=index + 1,
            )
        return _RunState(
            client=client,
            runtime_records=_jsonl_records(temp_path / "runtime.jsonl"),
        )


def _position(position_fp: str) -> KalshiMarketPosition:
    return KalshiMarketPosition(
        ticker="KXBTC15M-TEST",
        position_fp=Decimal(position_fp),
        market_exposure_dollars=Decimal("1.00"),
        resting_orders_count=0,
        last_updated_ts=None,
    )


def _market_snapshot(
    *,
    ticker: str,
    yes_bid: Decimal | None,
    yes_ask: Decimal | None,
) -> MarketStateSnapshot:
    return MarketStateSnapshot(
        tickers={
            ticker: TickerState(
                market_ticker=ticker,
                yes_bid_dollars=yes_bid,
                yes_ask_dollars=yes_ask,
                yes_bid_size_fp=Decimal("10") if yes_bid is not None else None,
                yes_ask_size_fp=Decimal("10") if yes_ask is not None else None,
            )
        },
        orderbooks={},
        last_sequence_by_sid={},
    )


def _order_summary(order, *, status: str = "executed") -> KalshiOrderSummary:  # noqa: ANN001
    return KalshiOrderSummary(
        order_id=f"exit-order-{len(order.client_order_id)}",
        client_order_id=order.client_order_id,
        ticker=order.ticker,
        side=order.side,
        action=order.action,
        order_type="limit",
        status=status,
        yes_price_dollars=order.price_dollars if order.side == "yes" else None,
        no_price_dollars=order.price_dollars if order.side == "no" else None,
        fill_count_fp=Decimal(str(order.count)),
        remaining_count_fp=Decimal("0"),
        initial_count_fp=Decimal(str(order.count)),
        created_time=None,
        last_update_time=None,
    )


def _jsonl_records(path: Path) -> tuple[dict[str, object], ...]:
    if not path.exists():
        return ()
    records: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return tuple(records)


def _has_event(records: tuple[dict[str, object], ...], event_type: str) -> bool:
    return _first_event_payload(records, event_type) is not None


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


@dataclass
class _Settings:
    log_directory: Path = Path("logs")
    log_jsonl_enabled: bool = True
    replay_directory: Path | None = None
    replay_write_enabled: bool = False
    live_profit_capture_enabled: bool = False
    live_profit_capture_price: Decimal = Decimal("0.99")
    live_trailing_stop_enabled: bool = False
    live_trailing_stop_distance: Decimal = Decimal("0.05")
    live_validation_time_in_force: str = "immediate_or_cancel"
    live_validation_poll_attempts: int = 1
    live_validation_poll_interval_seconds: float = 0.001


@dataclass(frozen=True)
class _RunState:
    client: "_FakeKalshiClient"
    runtime_records: tuple[dict[str, object], ...]


class _FakeKalshiClient:
    def __init__(self, *, positions: list[KalshiMarketPosition]) -> None:
        self._positions = positions
        self.get_positions_calls = 0
        self.submitted_orders = []

    def get_positions(self, **kwargs):  # noqa: ANN003,ARG002
        self.get_positions_calls += 1
        index = min(self.get_positions_calls - 1, len(self._positions) - 1)
        return KalshiPositionPage(
            market_positions=(self._positions[index],),
            cursor=None,
        )

    def create_order(self, order):  # noqa: ANN001
        self.submitted_orders.append(order)
        return _order_summary(order)

    def get_order(self, order_id: str):  # noqa: ARG002
        return _order_summary(self.submitted_orders[-1])


class _FakeRiskManager:
    def __init__(self, *, allow: bool = True, reason: str = "allowed") -> None:
        self._allow = allow
        self._reason = reason

    def evaluate_live_order(self, order):  # noqa: ANN001,ARG002
        return LiveSafetyDecision(allow=self._allow, reason=self._reason)


if __name__ == "__main__":
    raise SystemExit(main())
