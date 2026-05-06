"""Dry-run and guarded live execution coordination."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
from typing import Any

from kalshi_bot.clients.kalshi_client import (
    KalshiClientError,
    KalshiMarketPosition,
    KalshiOrderRequest,
    KalshiOrderSummary,
)
from kalshi_bot.config.settings import KalshiSettings
from kalshi_bot.contracts.contract_scanner import ContractScanSnapshot, ScannedContract
from kalshi_bot.execution.execution_engine import (
    LiveOrderIntent,
    MAX_ENTRY_PRICE,
    SimulationSnapshot,
    build_live_order_intent,
    build_live_order_intent_from_contract,
)
from kalshi_bot.market.market_state_cache import MarketStateSnapshot
from kalshi_bot.observability.logger import StructuredLogger
from kalshi_bot.observability.replay_engine import ReplayEngine
from kalshi_bot.risk.risk_manager import RiskManager


RISK_APPROVAL_SOURCES = frozenset(
    {"simulation_entry_risk_gate", "live_entry_risk_gate"}
)
LIVE_RUNNER_REALIZED_DAILY_PNL_DOLLARS = Decimal("0")
MIN_LIVE_EXECUTION_PRICE_DOLLARS = Decimal("0.10")
MAX_LIVE_EXECUTION_PRICE_DOLLARS = Decimal("0.80")
MAX_EXECUTION_PREMIUM_OVER_SCANNER_DOLLARS = Decimal("0.10")


@dataclass(frozen=True)
class ExecutionPricing:
    pricing_source: str
    intent_price_dollars: Decimal
    scanner_midpoint: Decimal
    intent_side: str
    yes_bid: Decimal | None
    yes_ask: Decimal | None
    executable_side_ask: Decimal | None
    executable_side_ask_size_fp: Decimal | None
    available_count_at_intent_price: Decimal | None
    orderbook_present: bool
    orderbook_seq: int | None


@dataclass(frozen=True)
class EntryEndWindowStatus:
    allowed: bool | None
    reason: str | None
    remaining_seconds: int | None


@dataclass(frozen=True)
class LiveSubmissionResult:
    """Outcome from one guarded live submission attempt."""

    classification: str
    decision_reason: str | None
    order_placed: bool
    order_id: str | None
    final_order: KalshiOrderSummary | None
    poll_attempts_used: int
    error_message: str | None


@dataclass(frozen=True)
class LivePositionRecord:
    """Latest reconciled state for one submitted live order."""

    client_order_id: str
    order_id: str
    product_id: str
    simulation_position_id: str
    ticker: str
    side: str
    action: str
    direction: str
    confidence: int
    requested_count: Decimal
    filled_count: Decimal
    remaining_count: Decimal
    price_dollars: Decimal
    average_fill_price_dollars: Decimal | None
    stake_dollars: Decimal
    status: str
    classification: str
    opened_at: str | None
    updated_at: str | None


@dataclass(frozen=True)
class LiveTrailingStopState:
    """Per live position trailing-stop state."""

    armed: bool
    peak_exit_bid: Decimal | None
    last_position_count: Decimal
    exit_pending: bool


class LiveExecutionCoordinator:
    """Convert simulated entries into intents and optionally submit guarded live orders."""

    def __init__(
        self,
        *,
        settings: KalshiSettings,
        client: Any | None = None,
        risk_manager: Any | None = None,
        logger: StructuredLogger | None = None,
        replay_engine: ReplayEngine | None = None,
        sleep_fn=time.sleep,
    ) -> None:
        self._settings = settings
        self._client = client
        self._risk_manager = risk_manager or _risk_manager_from_settings(settings)
        self._logger = logger or StructuredLogger(
            log_directory=settings.log_directory,
            enabled=settings.log_jsonl_enabled,
        )
        self._replay_engine = replay_engine or _replay_engine_from_settings(settings)
        self._sleep_fn = sleep_fn
        self._live_position_ledger: dict[str, LivePositionRecord] = {}
        self._client_order_id_by_order_id: dict[str, str] = {}
        self._trailing_stop_states: dict[str, LiveTrailingStopState] = {}
        self._reconciled_live_exposure_by_key: dict[str, Decimal] = {}
        self._live_positions_reconciled = False

    @property
    def live_position_ledger(self) -> dict[str, LivePositionRecord]:
        """Latest in-memory live order ledger keyed by client order id."""

        return dict(self._live_position_ledger)

    def process_simulation_snapshot(
        self,
        simulation_snapshot: SimulationSnapshot,
    ) -> tuple[LiveOrderIntent, ...]:
        intents: list[LiveOrderIntent] = []
        for decision in simulation_snapshot.decisions:
            if decision.action != "open_position" or decision.position_id is None:
                continue

            position = simulation_snapshot.open_positions.get(decision.position_id)
            if position is None:
                self._log_intent_skipped(
                    reason="missing_simulated_position",
                    product_id=decision.product_id,
                    market_ticker=decision.market_ticker,
                    simulation_position_id=decision.position_id,
                )
                continue

            intent = build_live_order_intent(position)
            if intent is None:
                self._log_intent_skipped(
                    reason="intent_unavailable",
                    product_id=position.product_id,
                    market_ticker=position.market_ticker,
                    simulation_position_id=position.position_id,
                )
                continue

            intents.append(intent)
            self._logger.log_event(
                category="live_execution",
                event_type="live_order_candidate",
                source="live_execution_coordinator",
                identifier=intent.client_order_id,
                payload={
                    "ticker": intent.ticker,
                    "side": intent.side,
                    "price_dollars": intent.price_dollars,
                    "count": intent.count,
                    "stake_dollars": intent.stake_dollars,
                    "confidence": intent.confidence,
                    "simulation_position_id": intent.simulation_position_id,
                },
            )
        return tuple(intents)

    def process_contract_scan_snapshot(
        self,
        contract_scan_snapshot: ContractScanSnapshot,
        *,
        cycle_number: int | None = None,
        market_snapshot: MarketStateSnapshot | None = None,
        allow_reconciliation: bool = True,
        scan_source: str = "normal_cycle",
    ) -> tuple[LiveOrderIntent, ...]:
        """Create live intents directly from ranked contracts after entry risk approval."""

        if not contract_scan_snapshot.ranked_contracts:
            self._log_intent_skipped(
                reason="no_ranked_contracts",
                product_id="",
                market_ticker=None,
                simulation_position_id=None,
                details={"cycle_number": cycle_number, "scan_source": scan_source},
            )
            return ()

        if allow_reconciliation and self._should_reconcile_before_entry_risk(
            market_snapshot=market_snapshot,
        ):
            self.reconcile_live_positions(
                cycle_number=cycle_number,
                reason="pre_risk",
            )

        intents: list[LiveOrderIntent] = []
        for contract in contract_scan_snapshot.ranked_contracts:
            if contract.direction not in {"up", "down"}:
                self._log_contract_intent_skipped(
                    reason="invalid_direction",
                    contract=contract,
                    cycle_number=cycle_number,
                    scan_source=scan_source,
                )
                continue
            if contract.midpoint <= Decimal("0"):
                self._log_contract_intent_skipped(
                    reason="invalid_entry_price",
                    contract=contract,
                    cycle_number=cycle_number,
                    scan_source=scan_source,
                )
                continue
            end_window = _entry_end_window_status(contract, settings=self._settings)
            if end_window.reason is not None and not end_window.allowed:
                self._log_contract_intent_skipped(
                    reason=end_window.reason,
                    contract=contract,
                    cycle_number=cycle_number,
                    scan_source=scan_source,
                    details=_end_window_payload(end_window),
                )
                continue
            current_exposure_dollars = self._live_current_exposure_dollars()
            risk_decision = self._risk_manager.evaluate_entry_risk(
                product_id=contract.product_id,
                confidence=contract.confidence,
                open_position_count=self._live_open_position_count(),
                current_exposure_dollars=current_exposure_dollars,
                realized_daily_pnl_dollars=LIVE_RUNNER_REALIZED_DAILY_PNL_DOLLARS,
            )
            if not risk_decision.allowed:
                self._log_contract_intent_skipped(
                    reason=risk_decision.reason,
                    contract=contract,
                    cycle_number=cycle_number,
                    scan_source=scan_source,
                    details={
                        "current_exposure_dollars": current_exposure_dollars,
                        "realized_daily_pnl_dollars": (
                            LIVE_RUNNER_REALIZED_DAILY_PNL_DOLLARS
                        ),
                    },
                )
                continue

            stake_dollars = risk_decision.stake_dollars
            if stake_dollars is None:
                self._log_contract_intent_skipped(
                    reason="risk_stake_unavailable",
                    contract=contract,
                    cycle_number=cycle_number,
                    scan_source=scan_source,
                )
                continue

            pricing = _execution_pricing(
                contract=contract,
                market_snapshot=market_snapshot,
            )
            execution_safety_reason = _execution_safety_rejection_reason(pricing)
            if execution_safety_reason is not None:
                self._log_contract_intent_skipped(
                    reason=execution_safety_reason,
                    contract=contract,
                    cycle_number=cycle_number,
                    scan_source=scan_source,
                    details={
                        "ticker": contract.market_ticker,
                        "stake_dollars": stake_dollars,
                        "count": _candidate_count(
                            stake_dollars=stake_dollars,
                            price_dollars=pricing.intent_price_dollars,
                        ),
                        **_execution_pricing_payload(pricing),
                    },
                )
                continue
            if contract.midpoint > MAX_ENTRY_PRICE:
                self._log_contract_intent_skipped(
                    reason="entry_price_too_high",
                    contract=contract,
                    cycle_number=cycle_number,
                    scan_source=scan_source,
                )
                continue
            if int(stake_dollars // pricing.intent_price_dollars) < 1:
                self._log_contract_intent_skipped(
                    reason="count_below_one",
                    contract=contract,
                    cycle_number=cycle_number,
                    scan_source=scan_source,
                    details={
                        "stake_dollars": stake_dollars,
                        **_execution_pricing_payload(pricing),
                    },
                )
                continue

            intent = build_live_order_intent_from_contract(
                contract,
                stake_dollars=stake_dollars,
                price_dollars=pricing.intent_price_dollars,
                source_id=_live_intent_source_id(
                    cycle_number=cycle_number,
                    product_id=contract.product_id,
                    market_ticker=contract.market_ticker,
                    scan_source=scan_source,
                )
                if cycle_number is not None
                else None,
            )
            if intent is None:
                self._log_contract_intent_skipped(
                    reason="intent_unavailable",
                    contract=contract,
                    cycle_number=cycle_number,
                    scan_source=scan_source,
                    details={"stake_dollars": stake_dollars},
                )
                continue

            intents.append(intent)
            self._log_and_record(
                event_type="live_intent_created",
                identifier=intent.client_order_id,
                payload={
                    "cycle_number": cycle_number,
                    "scan_source": scan_source,
                    "product_id": intent.product_id,
                    "ticker": intent.ticker,
                    "side": intent.side,
                    "action": intent.action,
                    "price_dollars": intent.price_dollars,
                    "count": intent.count,
                    "stake_dollars": intent.stake_dollars,
                    "direction": intent.direction,
                    "structure": contract.structure,
                    "confidence": intent.confidence,
                    "risk_approval_source": intent.risk_approval_source,
                    "impulse_detected": getattr(contract, "impulse_detected", None),
                    "impulse_direction": getattr(contract, "impulse_direction", None),
                    "impulse_return_bps": getattr(contract, "impulse_return_bps", None),
                    "recent_return_bps": getattr(contract, "recent_return_bps", None),
                    "lookback_return_bps": getattr(contract, "lookback_return_bps", None),
                    "risk_flags": dict(getattr(contract, "risk_flags", ()) or ()),
                    "bias_as_of": getattr(contract, "bias_as_of", None),
                    **_target_feasibility_payload(contract),
                    **_signal_diagnostic_payload(contract),
                    "contract_open_time": getattr(contract, "contract_open_time", None),
                    "contract_close_time": getattr(contract, "contract_close_time", None),
                    **_end_window_payload(end_window),
                    **_execution_pricing_payload(pricing),
                    "intent_count": intent.count,
                },
            )
        return tuple(intents)

    def reconcile_live_positions(
        self,
        *,
        cycle_number: int | None = None,
        reason: str = "normal_cycle",
    ) -> bool:
        """Refresh live exposure from Kalshi unsettled positions."""

        if not self._has_live_position_exposure_state():
            return False
        started_payload = {
            "cycle_number": cycle_number,
            "reason": reason,
            "open_position_count_before": self._live_open_position_count(),
            "current_exposure_dollars_before": self._live_current_exposure_dollars(),
            "ledger_record_count": len(self._live_position_ledger),
        }
        self._log_and_record(
            event_type="live_position_reconciliation_started",
            identifier="live_position_reconciliation",
            payload=started_payload,
        )
        if self._client is None or not hasattr(self._client, "get_positions"):
            self._log_and_record(
                event_type="reconciliation_failed",
                identifier="live_position_reconciliation",
                payload={
                    **started_payload,
                    "failure_reason": "positions_client_unavailable",
                },
            )
            return False

        try:
            position_page = self._client.get_positions(
                count_filter="position",
                settlement_status="unsettled",
                limit=1000,
            )
        except KalshiClientError as exc:
            self._log_and_record(
                event_type="reconciliation_failed",
                identifier="live_position_reconciliation",
                payload={
                    **started_payload,
                    "failure_reason": "positions_fetch_failed",
                    "message": str(exc),
                },
            )
            return False

        active_exposure_by_key = _active_position_exposure_by_key(
            position_page.market_positions,
            self._live_position_ledger.values(),
        )
        stale_client_order_ids = tuple(
            client_order_id
            for client_order_id, record in self._live_position_ledger.items()
            if _record_has_live_exposure(record)
            and _live_position_key(record.ticker, record.side) not in active_exposure_by_key
        )
        for client_order_id in stale_client_order_ids:
            record = self._live_position_ledger.pop(client_order_id)
            self._client_order_id_by_order_id.pop(record.order_id, None)
            self._log_and_record(
                event_type="stale_position_removed",
                identifier=record.client_order_id,
                payload={
                    "cycle_number": cycle_number,
                    "reason": reason,
                    **_live_position_record_payload(record),
                },
            )

        exposure_before = started_payload["current_exposure_dollars_before"]
        count_before = started_payload["open_position_count_before"]
        self._reconciled_live_exposure_by_key = active_exposure_by_key
        self._live_positions_reconciled = True
        exposure_after = self._live_current_exposure_dollars()
        count_after = self._live_open_position_count()
        recalculated_payload = {
            "cycle_number": cycle_number,
            "reason": reason,
            "open_position_count_before": count_before,
            "open_position_count_after": count_after,
            "current_exposure_dollars_before": exposure_before,
            "current_exposure_dollars_after": exposure_after,
            "stale_position_count": len(stale_client_order_ids),
            "actual_active_position_count": len(active_exposure_by_key),
        }
        self._log_and_record(
            event_type="exposure_recalculated",
            identifier="live_position_reconciliation",
            payload=recalculated_payload,
        )
        self._log_and_record(
            event_type="live_position_reconciliation_completed",
            identifier="live_position_reconciliation",
            payload=recalculated_payload,
        )
        return True

    def process_profit_capture_exits(
        self,
        market_snapshot: MarketStateSnapshot,
        *,
        cycle_number: int | None = None,
    ) -> tuple[LiveSubmissionResult, ...]:
        """Evaluate optional live-only profit capture and trailing exits."""

        profit_enabled = getattr(
            self._settings,
            "live_profit_capture_enabled",
            False,
        )
        trailing_enabled = getattr(
            self._settings,
            "live_trailing_stop_enabled",
            False,
        )
        if not profit_enabled and not trailing_enabled:
            return ()
        if self._client is None or not hasattr(self._client, "get_positions"):
            self._log_exit_skipped(
                event_type="profit_capture_exit_skipped",
                reason="positions_client_unavailable",
                cycle_number=cycle_number,
            )
            return ()

        try:
            position_page = self._client.get_positions(
                count_filter="position",
                settlement_status="unsettled",
                limit=1000,
            )
        except KalshiClientError as exc:
            self._log_exit_skipped(
                event_type="profit_capture_exit_skipped",
                reason="positions_fetch_failed",
                cycle_number=cycle_number,
                details={"message": str(exc)},
            )
            return ()

        active_positions = tuple(
            position
            for position in position_page.market_positions
            if abs(position.position_fp) > Decimal("0")
        )
        active_keys = {
            _exit_state_key(position.ticker, _position_side(position))
            for position in active_positions
            if _position_side(position) is not None
        }
        for key in tuple(self._trailing_stop_states):
            if key not in active_keys:
                self._trailing_stop_states.pop(key, None)

        results: list[LiveSubmissionResult] = []
        for position in active_positions:
            result = self._process_live_exit_position(
                position=position,
                market_snapshot=market_snapshot,
                cycle_number=cycle_number,
                profit_enabled=profit_enabled,
                trailing_enabled=trailing_enabled,
            )
            if result is not None:
                results.append(result)
        return tuple(results)

    def _process_live_exit_position(
        self,
        *,
        position: KalshiMarketPosition,
        market_snapshot: MarketStateSnapshot,
        cycle_number: int | None,
        profit_enabled: bool,
        trailing_enabled: bool,
    ) -> LiveSubmissionResult | None:
        side = _position_side(position)
        if side is None:
            self._log_exit_skipped(
                event_type="profit_capture_exit_skipped",
                reason="invalid_position_side",
                cycle_number=cycle_number,
                details={
                    "ticker": position.ticker,
                    "position_count": abs(position.position_fp),
                },
            )
            return None

        ticker_state = market_snapshot.tickers.get(position.ticker)
        if ticker_state is None:
            self._log_exit_skipped(
                event_type="profit_capture_exit_skipped",
                reason="market_state_missing",
                cycle_number=cycle_number,
                details={
                    "ticker": position.ticker,
                    "side": side,
                    "position_count": abs(position.position_fp),
                },
            )
            return None

        executable_bid, liquidity_size, skip_reason = _select_executable_exit_bid(
            ticker_state,
            side=side,
        )
        base_payload = _live_exit_payload(
            settings=self._settings,
            cycle_number=cycle_number,
            ticker=position.ticker,
            side=side,
            position_count=abs(position.position_fp),
            executable_exit_bid=executable_bid,
            liquidity_size=liquidity_size,
            peak_exit_bid=None,
            sell_count=None,
        )
        if skip_reason is not None or executable_bid is None:
            self._log_exit_skipped(
                event_type="profit_capture_exit_skipped",
                reason=skip_reason or "executable_exit_bid_missing",
                cycle_number=cycle_number,
                details=base_payload,
            )
            return None

        if profit_enabled and executable_bid >= getattr(
            self._settings,
            "live_profit_capture_price",
            Decimal("0.99"),
        ):
            sell_count = _live_sell_count(position_count=abs(position.position_fp))
            trigger_payload = {**base_payload, "sell_count": sell_count}
            if sell_count < 1:
                self._log_exit_skipped(
                    event_type="profit_capture_exit_skipped",
                    reason="sell_count_unavailable",
                    cycle_number=cycle_number,
                    details=trigger_payload,
                )
                return None
            self._log_and_record(
                event_type="profit_capture_exit_triggered",
                identifier=position.ticker,
                payload=trigger_payload,
            )
            return self._submit_live_exit_order(
                ticker=position.ticker,
                side=side,
                price_dollars=executable_bid,
                count=sell_count,
                reason="profit_capture",
                cycle_number=cycle_number,
                trigger_payload=trigger_payload,
            )

        if not trailing_enabled:
            return None
        return self._process_trailing_exit(
            position=position,
            side=side,
            executable_bid=executable_bid,
            base_payload=base_payload,
            cycle_number=cycle_number,
        )

    def _process_trailing_exit(
        self,
        *,
        position: KalshiMarketPosition,
        side: str,
        executable_bid: Decimal,
        base_payload: dict[str, object],
        cycle_number: int | None,
    ) -> LiveSubmissionResult | None:
        key = _exit_state_key(position.ticker, side)
        position_count = abs(position.position_fp)
        state = self._trailing_stop_states.get(key)
        if (
            state is None
            or state.exit_pending
            or state.last_position_count != position_count
        ):
            state = LiveTrailingStopState(
                armed=False,
                peak_exit_bid=None,
                last_position_count=position_count,
                exit_pending=False,
            )
            self._trailing_stop_states[key] = state

        activation_price = getattr(
            self._settings,
            "live_profit_capture_price",
            Decimal("0.99"),
        )
        if not state.armed:
            if executable_bid < activation_price:
                return None
            state = LiveTrailingStopState(
                armed=True,
                peak_exit_bid=executable_bid,
                last_position_count=position_count,
                exit_pending=False,
            )
            self._trailing_stop_states[key] = state
            self._log_and_record(
                event_type="trailing_exit_armed",
                identifier=position.ticker,
                payload={**base_payload, "peak_exit_bid": executable_bid},
            )
            return None

        peak_exit_bid = state.peak_exit_bid or executable_bid
        if executable_bid > peak_exit_bid:
            state = LiveTrailingStopState(
                armed=True,
                peak_exit_bid=executable_bid,
                last_position_count=position_count,
                exit_pending=False,
            )
            self._trailing_stop_states[key] = state
            self._log_and_record(
                event_type="trailing_exit_peak_updated",
                identifier=position.ticker,
                payload={**base_payload, "peak_exit_bid": executable_bid},
            )
            return None

        trailing_distance = getattr(
            self._settings,
            "live_trailing_stop_distance",
            Decimal("0.05"),
        )
        if peak_exit_bid - executable_bid < trailing_distance:
            return None

        sell_count = _live_sell_count(position_count=position_count)
        trigger_payload = {
            **base_payload,
            "peak_exit_bid": peak_exit_bid,
            "sell_count": sell_count,
        }
        if sell_count < 1:
            self._log_exit_skipped(
                event_type="trailing_exit_skipped",
                reason="sell_count_unavailable",
                cycle_number=cycle_number,
                details=trigger_payload,
            )
            return None

        self._log_and_record(
            event_type="trailing_exit_triggered",
            identifier=position.ticker,
            payload=trigger_payload,
        )
        result = self._submit_live_exit_order(
            ticker=position.ticker,
            side=side,
            price_dollars=executable_bid,
            count=sell_count,
            reason="trailing_stop",
            cycle_number=cycle_number,
            trigger_payload=trigger_payload,
        )
        self._trailing_stop_states[key] = LiveTrailingStopState(
            armed=True,
            peak_exit_bid=peak_exit_bid,
            last_position_count=position_count,
            exit_pending=True,
        )
        return result

    def _submit_live_exit_order(
        self,
        *,
        ticker: str,
        side: str,
        price_dollars: Decimal,
        count: int,
        reason: str,
        cycle_number: int | None,
        trigger_payload: dict[str, object],
    ) -> LiveSubmissionResult:
        order_request = KalshiOrderRequest(
            ticker=ticker,
            action="sell",
            side=side,
            count=count,
            price_dollars=price_dollars,
            time_in_force=getattr(
                self._settings,
                "live_validation_time_in_force",
                "immediate_or_cancel",
            ),
            client_order_id=(
                f"{reason}-{cycle_number}-{ticker}-{side}"
                if cycle_number is not None
                else f"{reason}-manual-{ticker}-{side}"
            ),
        )
        blocked_event = (
            "trailing_exit_skipped"
            if reason == "trailing_stop"
            else "profit_capture_exit_skipped"
        )
        response_event = (
            "trailing_exit_order_response"
            if reason == "trailing_stop"
            else "profit_capture_exit_order_response"
        )
        safety_decision = self._risk_manager.evaluate_live_order(order_request)
        if not safety_decision.allow:
            self._log_exit_skipped(
                event_type=blocked_event,
                reason="live_safety_blocked",
                cycle_number=cycle_number,
                details={
                    **trigger_payload,
                    "live_safety_reason": safety_decision.reason,
                    **_order_request_payload(order_request),
                },
            )
            return LiveSubmissionResult(
                classification="blocked_by_safeguard",
                decision_reason=safety_decision.reason,
                order_placed=False,
                order_id=None,
                final_order=None,
                poll_attempts_used=0,
                error_message=None,
            )

        if self._client is None:
            self._log_exit_skipped(
                event_type=blocked_event,
                reason="live_client_unavailable",
                cycle_number=cycle_number,
                details={**trigger_payload, **_order_request_payload(order_request)},
            )
            return LiveSubmissionResult(
                classification="blocked_by_safeguard",
                decision_reason="live_client_unavailable",
                order_placed=False,
                order_id=None,
                final_order=None,
                poll_attempts_used=0,
                error_message=None,
            )

        final_order: KalshiOrderSummary | None = None
        order_placed = False
        poll_attempts_used = 0
        try:
            created_order = self._client.create_order(order_request)
            order_placed = True
            final_order = created_order
            if not _is_terminal_order(created_order):
                final_order, poll_attempts_used = self._poll_order(
                    created_order.order_id,
                )
            classification = _classify_order_result(final_order)
        except KalshiClientError as exc:
            error_message = str(exc)
            failure_reason = "order_poll_failed" if order_placed else "order_submit_failed"
            self._log_exit_skipped(
                event_type=blocked_event,
                reason=failure_reason,
                cycle_number=cycle_number,
                details={
                    **trigger_payload,
                    "message": error_message,
                    **_order_request_payload(order_request),
                },
            )
            return LiveSubmissionResult(
                classification="unknown_final_state" if order_placed else "rejected",
                decision_reason=failure_reason,
                order_placed=order_placed,
                order_id=final_order.order_id if final_order is not None else None,
                final_order=final_order,
                poll_attempts_used=0,
                error_message=error_message,
            )

        self._log_and_record(
            event_type=response_event,
            identifier=final_order.order_id,
            payload={
                **trigger_payload,
                "classification": classification,
                **_order_request_payload(order_request),
                **_order_summary_payload(final_order),
            },
        )
        return LiveSubmissionResult(
            classification=classification,
            decision_reason=None,
            order_placed=True,
            order_id=final_order.order_id,
            final_order=final_order,
            poll_attempts_used=poll_attempts_used,
            error_message=None,
        )

    def _log_exit_skipped(
        self,
        *,
        event_type: str,
        reason: str,
        cycle_number: int | None,
        details: dict[str, object] | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "cycle_number": cycle_number,
            "reason": reason,
        }
        if details:
            payload.update(details)
        self._log_and_record(
            event_type=event_type,
            identifier=str(payload.get("ticker") or event_type),
            payload=payload,
        )

    def submit_live_order(self, intent: LiveOrderIntent) -> LiveSubmissionResult:
        """Submit one intent only after all live guardrails allow it."""

        order_request = _order_request_from_intent(
            intent,
            time_in_force=getattr(
                self._settings,
                "live_validation_time_in_force",
                "immediate_or_cancel",
            ),
        )
        if not _intent_is_risk_approved(intent):
            reason = "live_intent_not_risk_approved"
            self._log_and_record(
                event_type="live_submission_blocked",
                identifier=order_request.client_order_id,
                payload={
                    "reason": reason,
                    **_order_request_payload(order_request),
                },
            )
            return LiveSubmissionResult(
                classification="blocked_by_safeguard",
                decision_reason=reason,
                order_placed=False,
                order_id=None,
                final_order=None,
                poll_attempts_used=0,
                error_message=None,
            )

        safety_decision = self._risk_manager.evaluate_live_order(order_request)
        if not safety_decision.allow:
            self._log_and_record(
                event_type="live_submission_blocked",
                identifier=order_request.client_order_id,
                payload={
                    "reason": safety_decision.reason,
                    **_order_request_payload(order_request),
                },
            )
            return LiveSubmissionResult(
                classification="blocked_by_safeguard",
                decision_reason=safety_decision.reason,
                order_placed=False,
                order_id=None,
                final_order=None,
                poll_attempts_used=0,
                error_message=None,
            )

        if self._client is None:
            reason = "live_client_unavailable"
            self._log_and_record(
                event_type="live_submission_blocked",
                identifier=order_request.client_order_id,
                payload={
                    "reason": reason,
                    **_order_request_payload(order_request),
                },
            )
            return LiveSubmissionResult(
                classification="blocked_by_safeguard",
                decision_reason=reason,
                order_placed=False,
                order_id=None,
                final_order=None,
                poll_attempts_used=0,
                error_message=None,
            )

        final_order: KalshiOrderSummary | None = None
        order_placed = False
        poll_attempts_used = 0
        try:
            self._log_and_record(
                event_type="live_order_submit_attempt",
                identifier=order_request.client_order_id,
                payload=_order_request_payload(order_request),
            )
            created_order = self._client.create_order(order_request)
            order_placed = True
            final_order = created_order
            self._log_and_record(
                event_type="kalshi_order_response",
                identifier=created_order.order_id,
                payload=_order_summary_payload(created_order),
            )
            self._log_and_record(
                event_type="live_order_submitted",
                identifier=created_order.order_id,
                payload=_order_summary_payload(created_order),
            )
            self._update_live_position_ledger(
                intent=intent,
                order=created_order,
            )
            final_order, poll_attempts_used = self._poll_order(
                created_order.order_id,
                intent=intent,
            )
            classification = _classify_order_result(final_order)
        except KalshiClientError as exc:
            error_message = str(exc)
            event_type = "live_order_poll_failed" if order_placed else "live_order_submit_failed"
            decision_reason = "order_poll_failed" if order_placed else "order_submit_failed"
            self._log_and_record(
                event_type=event_type,
                identifier=order_request.client_order_id,
                payload={
                    "message": error_message,
                    **_order_request_payload(order_request),
                },
            )
            return LiveSubmissionResult(
                classification="unknown_final_state" if order_placed else "rejected",
                decision_reason=decision_reason,
                order_placed=order_placed,
                order_id=final_order.order_id if final_order is not None else None,
                final_order=final_order,
                poll_attempts_used=0,
                error_message=error_message,
            )

        self._log_and_record(
            event_type="live_order_final_state",
            identifier=final_order.order_id,
            payload={
                "classification": classification,
                **_order_summary_payload(final_order),
            },
        )
        final_record = self._live_position_ledger.get(
            final_order.client_order_id or intent.client_order_id
        )
        if final_record is not None:
            self._log_order_outcome(final_record)
        if classification == "filled":
            self._log_and_record(
                event_type="order_filled",
                identifier=final_order.order_id,
                payload={
                    "classification": classification,
                    **_order_summary_payload(final_order),
                },
            )
        return LiveSubmissionResult(
            classification=classification,
            decision_reason=None,
            order_placed=True,
            order_id=final_order.order_id,
            final_order=final_order,
            poll_attempts_used=poll_attempts_used,
            error_message=None,
        )

    def _log_intent_skipped(
        self,
        *,
        reason: str,
        product_id: str,
        market_ticker: str | None,
        simulation_position_id: str | None,
        details: dict[str, object] | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "reason": reason,
            "product_id": product_id,
            "market_ticker": market_ticker,
            "simulation_position_id": simulation_position_id,
        }
        if details:
            payload.update(details)
        self._logger.log_event(
            category="live_execution",
            event_type="live_order_intent_skipped",
            source="live_execution_coordinator",
            identifier=simulation_position_id,
            payload=payload,
        )

    def _log_contract_intent_skipped(
        self,
        *,
        reason: str,
        contract: ScannedContract,
        cycle_number: int | None,
        scan_source: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        payload = {
            "cycle_number": cycle_number,
            "scan_source": scan_source,
            "direction": contract.direction,
            "structure": contract.structure,
            "confidence": contract.confidence,
            "entry_price": contract.midpoint,
            "contract_open_time": getattr(contract, "contract_open_time", None),
            "contract_close_time": getattr(contract, "contract_close_time", None),
            **_target_feasibility_payload(contract),
            **_signal_diagnostic_payload(contract),
        }
        if details:
            payload.update(details)
        self._log_intent_skipped(
            reason=reason,
            product_id=contract.product_id,
            market_ticker=contract.market_ticker,
            simulation_position_id=None,
            details=payload,
        )

    def _live_open_position_count(self) -> int:
        if self._live_positions_reconciled:
            return len(self._reconciled_live_exposure_by_key)
        return len(_ledger_exposure_by_key(self._live_position_ledger.values()))

    def _live_current_exposure_dollars(self) -> Decimal:
        if self._live_positions_reconciled:
            return sum(
                self._reconciled_live_exposure_by_key.values(),
                Decimal("0"),
            )
        return sum(
            _ledger_exposure_by_key(self._live_position_ledger.values()).values(),
            Decimal("0"),
        )

    def _has_live_position_exposure_state(self) -> bool:
        return any(
            _record_has_live_exposure(record)
            for record in self._live_position_ledger.values()
        ) or bool(self._reconciled_live_exposure_by_key)

    def _should_reconcile_before_entry_risk(
        self,
        *,
        market_snapshot: MarketStateSnapshot | None,
    ) -> bool:
        if not self._has_live_position_exposure_state():
            return False
        if self._live_open_position_count() >= self._settings.risk_max_open_positions:
            return True
        if (
            self._live_current_exposure_dollars()
            >= self._settings.risk_max_total_exposure_dollars
        ):
            return True
        if market_snapshot is None:
            return False
        active_tickers = set(market_snapshot.tickers)
        return any(
            _record_has_live_exposure(record)
            and record.ticker not in active_tickers
            for record in self._live_position_ledger.values()
        )

    def _poll_order(
        self,
        order_id: str,
        *,
        intent: LiveOrderIntent | None = None,
    ) -> tuple[KalshiOrderSummary, int]:
        poll_attempts = getattr(self._settings, "live_validation_poll_attempts", 1)
        poll_interval_seconds = getattr(
            self._settings,
            "live_validation_poll_interval_seconds",
            1.0,
        )
        last_order = self._client.get_order(order_id)
        attempts_used = 1
        self._log_and_record(
            event_type="live_order_polled",
            identifier=order_id,
            payload={"attempt": attempts_used, "status": last_order.status},
        )
        if intent is not None:
            self._update_live_position_ledger(intent=intent, order=last_order)
        if _is_terminal_order(last_order):
            return last_order, attempts_used

        while attempts_used < poll_attempts:
            self._sleep_fn(poll_interval_seconds)
            attempts_used += 1
            try:
                last_order = self._client.get_order(order_id)
            except KalshiClientError as exc:
                self._log_and_record(
                    event_type="live_order_poll_failed",
                    identifier=order_id,
                    payload={"attempt": attempts_used, "message": str(exc)},
                )
                break
            self._log_and_record(
                event_type="live_order_polled",
                identifier=order_id,
                payload={"attempt": attempts_used, "status": last_order.status},
            )
            if intent is not None:
                self._update_live_position_ledger(intent=intent, order=last_order)
            if _is_terminal_order(last_order):
                break
        return last_order, attempts_used

    def _update_live_position_ledger(
        self,
        *,
        intent: LiveOrderIntent,
        order: KalshiOrderSummary,
    ) -> LivePositionRecord:
        classification = _classify_order_result(order)
        client_order_id = order.client_order_id or intent.client_order_id
        previous = self._live_position_ledger.get(client_order_id)
        record = _live_position_record_from_order(
            intent=intent,
            order=order,
            classification=classification,
        )
        self._live_position_ledger[client_order_id] = record
        self._client_order_id_by_order_id[record.order_id] = client_order_id
        if self._live_positions_reconciled:
            position_key = _live_position_key(record.ticker, record.side)
            if _record_has_live_exposure(record):
                self._reconciled_live_exposure_by_key[position_key] = (
                    record.filled_count * record.price_dollars
                )
            else:
                self._reconciled_live_exposure_by_key.pop(position_key, None)
        self._log_and_record(
            event_type="live_position_ledger_updated",
            identifier=record.client_order_id,
            payload=_live_position_record_payload(record),
        )

        previous_filled_count = previous.filled_count if previous is not None else Decimal("0")
        if record.filled_count > 0 and previous_filled_count <= 0:
            self._log_and_record(
                event_type="live_position_opened",
                identifier=record.client_order_id,
                payload=_live_position_record_payload(record),
            )
        return record

    def _log_order_outcome(self, record: LivePositionRecord) -> None:
        if record.classification == "rejected":
            event_type = "live_order_rejected"
        elif record.classification == "canceled_or_expired":
            event_type = "live_order_canceled_or_expired"
        elif record.classification == "unknown_final_state":
            event_type = "live_order_unknown_final_state"
        else:
            return
        self._log_and_record(
            event_type=event_type,
            identifier=record.client_order_id,
            payload=_live_position_record_payload(record),
        )

    def _log_and_record(
        self,
        *,
        event_type: str,
        identifier: str | None,
        payload: dict[str, object],
    ) -> None:
        self._logger.log_event(
            category="live_execution",
            event_type=event_type,
            source="live_execution_coordinator",
            identifier=identifier,
            payload=payload,
        )
        if self._replay_engine is None:
            return
        self._replay_engine.record_message(
            source="live_execution_coordinator",
            message_type=event_type,
            identifier=identifier,
            payload=payload,
        )


def _risk_manager_from_settings(settings: KalshiSettings) -> RiskManager:
    if hasattr(settings, "live_validation_enabled"):
        return RiskManager.from_settings(settings)
    return RiskManager(
        live_validation_enabled=False,
        live_trading_enabled=False,
        live_kill_switch_active=True,
        env="demo",
        live_validation_env="demo",
    )


def _replay_engine_from_settings(settings: KalshiSettings) -> ReplayEngine | None:
    replay_directory = getattr(settings, "replay_directory", None)
    if replay_directory is None:
        return None
    return ReplayEngine(
        replay_directory=replay_directory,
        enabled=getattr(settings, "replay_write_enabled", False),
    )


def _order_request_from_intent(
    intent: LiveOrderIntent,
    *,
    time_in_force: str,
) -> KalshiOrderRequest:
    return KalshiOrderRequest(
        ticker=intent.ticker,
        action=intent.action,
        side=intent.side,
        count=intent.count,
        price_dollars=intent.price_dollars,
        time_in_force=time_in_force,
        client_order_id=intent.client_order_id,
    )


def _intent_is_risk_approved(intent: LiveOrderIntent) -> bool:
    return (
        intent.risk_approved
        and intent.risk_approval_source in RISK_APPROVAL_SOURCES
    )


def _order_request_payload(order: KalshiOrderRequest) -> dict[str, object]:
    return {
        "ticker": order.ticker,
        "side": order.side,
        "action": order.action,
        "price_dollars": order.price_dollars,
        "count": order.count,
        "client_order_id": order.client_order_id,
    }


def _order_summary_payload(order: KalshiOrderSummary) -> dict[str, object]:
    return {
        "order_id": order.order_id,
        "client_order_id": order.client_order_id,
        "ticker": order.ticker,
        "side": order.side,
        "action": order.action,
        "status": order.status,
        "fill_count_fp": order.fill_count_fp,
        "remaining_count_fp": order.remaining_count_fp,
        "initial_count_fp": order.initial_count_fp,
        "last_update_time": order.last_update_time,
    }


def _select_executable_exit_bid(
    ticker_state,
    *,
    side: str,
) -> tuple[Decimal | None, Decimal | None, str | None]:
    if side == "yes":
        executable_bid = ticker_state.yes_bid_dollars
        liquidity_size = ticker_state.yes_bid_size_fp
    elif side == "no":
        if ticker_state.yes_ask_dollars is None:
            return None, ticker_state.yes_ask_size_fp, "executable_exit_bid_missing"
        executable_bid = Decimal("1") - ticker_state.yes_ask_dollars
        liquidity_size = ticker_state.yes_ask_size_fp
    else:
        return None, None, "invalid_position_side"

    if executable_bid is None or executable_bid <= Decimal("0"):
        return executable_bid, liquidity_size, "executable_exit_bid_missing"
    if executable_bid > Decimal("1"):
        return executable_bid, liquidity_size, "executable_exit_bid_missing"
    if liquidity_size is None or liquidity_size <= Decimal("0"):
        return executable_bid, liquidity_size, "exit_liquidity_missing"
    return executable_bid, liquidity_size, None


def _position_side(position: KalshiMarketPosition) -> str | None:
    if position.position_fp > Decimal("0"):
        return "yes"
    if position.position_fp < Decimal("0"):
        return "no"
    return None


def _exit_state_key(ticker: str, side: str | None) -> str:
    return f"{ticker}:{side or 'unknown'}"


def _live_sell_count(*, position_count: Decimal) -> int:
    return max(int(position_count.to_integral_value(rounding=ROUND_FLOOR)), 0)


def _live_exit_payload(
    *,
    settings: KalshiSettings,
    cycle_number: int | None,
    ticker: str,
    side: str,
    position_count: Decimal,
    executable_exit_bid: Decimal | None,
    liquidity_size: Decimal | None,
    peak_exit_bid: Decimal | None,
    sell_count: int | None,
) -> dict[str, object]:
    return {
        "cycle_number": cycle_number,
        "ticker": ticker,
        "side": side,
        "position_count": position_count,
        "executable_exit_bid": executable_exit_bid,
        "liquidity_size": liquidity_size,
        "profit_capture_price": getattr(
            settings,
            "live_profit_capture_price",
            Decimal("0.99"),
        ),
        "trailing_stop_distance": getattr(
            settings,
            "live_trailing_stop_distance",
            Decimal("0.05"),
        ),
        "peak_exit_bid": peak_exit_bid,
        "sell_count": sell_count,
    }


def _execution_pricing(
    *,
    contract: ScannedContract,
    market_snapshot: MarketStateSnapshot | None,
) -> ExecutionPricing:
    intent_side = _intent_side_from_direction(contract.direction)
    ticker_state = (
        market_snapshot.tickers.get(contract.market_ticker)
        if market_snapshot is not None
        else None
    )
    orderbook = (
        market_snapshot.orderbooks.get(contract.market_ticker)
        if market_snapshot is not None
        else None
    )
    yes_bid = ticker_state.yes_bid_dollars if ticker_state is not None else None
    yes_ask = ticker_state.yes_ask_dollars if ticker_state is not None else None
    executable_side_ask: Decimal | None = None
    executable_side_ask_size_fp: Decimal | None = None
    if intent_side == "yes":
        executable_side_ask = yes_ask
        executable_side_ask_size_fp = (
            ticker_state.yes_ask_size_fp if ticker_state is not None else None
        )
    elif yes_bid is not None:
        executable_side_ask = Decimal("1") - yes_bid
        executable_side_ask_size_fp = ticker_state.yes_bid_size_fp

    intent_price_dollars = (
        executable_side_ask
        if executable_side_ask is not None
        else contract.midpoint
    )
    return ExecutionPricing(
        pricing_source=(
            "executable_side_ask"
            if executable_side_ask is not None
            else "midpoint_fallback"
        ),
        intent_price_dollars=intent_price_dollars,
        scanner_midpoint=contract.midpoint,
        intent_side=intent_side,
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        executable_side_ask=executable_side_ask,
        executable_side_ask_size_fp=executable_side_ask_size_fp,
        available_count_at_intent_price=_available_count_at_intent_price(
            orderbook=orderbook,
            intent_side=intent_side,
            intent_price_dollars=intent_price_dollars,
        ),
        orderbook_present=orderbook is not None,
        orderbook_seq=orderbook.seq if orderbook is not None else None,
    )


def _intent_side_from_direction(direction: str) -> str:
    if direction == "up":
        return "yes"
    if direction == "down":
        return "no"
    return ""


def _entry_end_window_status(
    contract: ScannedContract,
    *,
    settings: KalshiSettings,
) -> EntryEndWindowStatus:
    if not getattr(settings, "live_entry_end_window_only", False):
        return EntryEndWindowStatus(
            allowed=None,
            reason=None,
            remaining_seconds=None,
        )
    close_time = getattr(contract, "contract_close_time", None)
    if not close_time:
        return EntryEndWindowStatus(
            allowed=False,
            reason="end_window_close_time_missing",
            remaining_seconds=None,
        )
    try:
        close_at = _parse_iso_datetime(close_time)
    except ValueError:
        return EntryEndWindowStatus(
            allowed=False,
            reason="end_window_close_time_invalid",
            remaining_seconds=None,
        )

    remaining_seconds = int((close_at - datetime.now(timezone.utc)).total_seconds())
    window_seconds = getattr(settings, "live_entry_end_window_minutes", 5) * 60
    if remaining_seconds <= window_seconds:
        return EntryEndWindowStatus(
            allowed=True,
            reason="end_window_open",
            remaining_seconds=remaining_seconds,
        )
    return EntryEndWindowStatus(
        allowed=False,
        reason="end_window_not_open",
        remaining_seconds=remaining_seconds,
    )


def _parse_iso_datetime(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _end_window_payload(status: EntryEndWindowStatus) -> dict[str, object]:
    return {
        "contract_time_remaining_seconds": status.remaining_seconds,
        "end_window_allowed": status.allowed,
        "end_window_reason": status.reason,
    }


def _execution_safety_rejection_reason(pricing: ExecutionPricing) -> str | None:
    if pricing.intent_price_dollars < MIN_LIVE_EXECUTION_PRICE_DOLLARS:
        return "executable_price_below_minimum"
    if pricing.intent_price_dollars > MAX_LIVE_EXECUTION_PRICE_DOLLARS:
        return "executable_price_above_maximum"
    if (
        pricing.pricing_source == "executable_side_ask"
        and pricing.executable_side_ask is not None
        and pricing.executable_side_ask
        > pricing.scanner_midpoint + MAX_EXECUTION_PREMIUM_OVER_SCANNER_DOLLARS
    ):
        return "executable_price_above_scanner_premium"
    return None


def _candidate_count(*, stake_dollars: Decimal, price_dollars: Decimal) -> int:
    if stake_dollars <= Decimal("0") or price_dollars <= Decimal("0"):
        return 0
    return int(stake_dollars // price_dollars)


def _available_count_at_intent_price(
    *,
    orderbook,
    intent_side: str,
    intent_price_dollars: Decimal,
) -> Decimal | None:
    if orderbook is None:
        return None
    if intent_side == "yes":
        return sum(
            (
                quantity
                for no_bid_price, quantity in orderbook.no.items()
                if Decimal("1") - no_bid_price <= intent_price_dollars
            ),
            Decimal("0"),
        )
    if intent_side == "no":
        return sum(
            (
                quantity
                for yes_bid_price, quantity in orderbook.yes.items()
                if Decimal("1") - yes_bid_price <= intent_price_dollars
            ),
            Decimal("0"),
        )
    return None


def _execution_pricing_payload(pricing: ExecutionPricing) -> dict[str, object]:
    return {
        "pricing_source": pricing.pricing_source,
        "scanner_midpoint": pricing.scanner_midpoint,
        "intent_price_dollars": pricing.intent_price_dollars,
        "intent_side": pricing.intent_side,
        "yes_bid": pricing.yes_bid,
        "yes_ask": pricing.yes_ask,
        "executable_side_ask": pricing.executable_side_ask,
        "executable_side_ask_size_fp": pricing.executable_side_ask_size_fp,
        "available_count_at_intent_price": pricing.available_count_at_intent_price,
        "orderbook_present": pricing.orderbook_present,
        "orderbook_seq": pricing.orderbook_seq,
    }


def _target_feasibility_payload(contract: ScannedContract) -> dict[str, object]:
    return {
        "target_price": getattr(contract, "target_price", None),
        "target_price_source": getattr(contract, "target_price_source", None),
        "current_spot_price": getattr(contract, "latest_price", None),
        "distance_to_target": getattr(contract, "distance_to_target", None),
        "distance_to_target_bps": getattr(contract, "distance_to_target_bps", None),
        "time_remaining_seconds": getattr(
            contract,
            "contract_time_remaining_seconds",
            None,
        ),
        "required_bps_per_minute": getattr(
            contract,
            "required_bps_per_minute",
            None,
        ),
        "side_currently_itm": getattr(contract, "side_currently_itm", None),
        "side_needs_cross": getattr(contract, "side_needs_cross", None),
        "feasibility_status": getattr(contract, "feasibility_status", None),
    }


def _signal_diagnostic_payload(contract: ScannedContract) -> dict[str, object]:
    return {
        "reversal_confirmation_status": getattr(
            contract,
            "reversal_confirmation_status",
            None,
        ),
        "signal_conflict_flags": dict(
            getattr(contract, "signal_conflict_flags", ()) or ()
        ),
        "scanner_score_confidence": getattr(
            contract,
            "scanner_score_confidence",
            None,
        ),
    }


def _live_intent_source_id(
    *,
    cycle_number: int,
    product_id: str,
    market_ticker: str,
    scan_source: str,
) -> str:
    if scan_source == "normal_cycle":
        return f"cycle-{cycle_number}-{product_id}-{market_ticker}"
    return f"{scan_source}-cycle-{cycle_number}-{product_id}-{market_ticker}"


def _live_position_record_from_order(
    *,
    intent: LiveOrderIntent,
    order: KalshiOrderSummary,
    classification: str,
) -> LivePositionRecord:
    requested_count = order.initial_count_fp or Decimal(str(intent.count))
    filled_count = order.fill_count_fp or Decimal("0")
    remaining_count = order.remaining_count_fp
    if remaining_count is None:
        remaining_count = max(requested_count - filled_count, Decimal("0"))
    updated_at = order.last_update_time or order.created_time
    return LivePositionRecord(
        client_order_id=order.client_order_id or intent.client_order_id,
        order_id=order.order_id,
        product_id=intent.product_id,
        simulation_position_id=intent.simulation_position_id,
        ticker=order.ticker,
        side=order.side,
        action=order.action,
        direction=intent.direction,
        confidence=intent.confidence,
        requested_count=requested_count,
        filled_count=filled_count,
        remaining_count=remaining_count,
        price_dollars=_order_price_dollars(order, intent),
        average_fill_price_dollars=None,
        stake_dollars=intent.stake_dollars,
        status=order.status,
        classification=classification,
        opened_at=order.created_time if filled_count > 0 else None,
        updated_at=updated_at,
    )


def _order_price_dollars(
    order: KalshiOrderSummary,
    intent: LiveOrderIntent,
) -> Decimal:
    if order.side == "yes" and order.yes_price_dollars is not None:
        return order.yes_price_dollars
    if order.side == "no" and order.no_price_dollars is not None:
        return order.no_price_dollars
    return intent.price_dollars


def _live_position_record_payload(record: LivePositionRecord) -> dict[str, object]:
    return {
        "client_order_id": record.client_order_id,
        "order_id": record.order_id,
        "product_id": record.product_id,
        "simulation_position_id": record.simulation_position_id,
        "ticker": record.ticker,
        "side": record.side,
        "action": record.action,
        "direction": record.direction,
        "confidence": record.confidence,
        "requested_count": record.requested_count,
        "filled_count": record.filled_count,
        "remaining_count": record.remaining_count,
        "price_dollars": record.price_dollars,
        "average_fill_price_dollars": record.average_fill_price_dollars,
        "stake_dollars": record.stake_dollars,
        "status": record.status,
        "classification": record.classification,
        "opened_at": record.opened_at,
        "updated_at": record.updated_at,
    }


def _ledger_exposure_by_key(
    records: Any,
) -> dict[str, Decimal]:
    exposure_by_key: dict[str, Decimal] = {}
    for record in records:
        if not _record_has_live_exposure(record):
            continue
        position_key = _live_position_key(record.ticker, record.side)
        exposure_by_key[position_key] = exposure_by_key.get(
            position_key,
            Decimal("0"),
        ) + (record.filled_count * record.price_dollars)
    return exposure_by_key


def _active_position_exposure_by_key(
    positions: tuple[KalshiMarketPosition, ...],
    records: Any,
) -> dict[str, Decimal]:
    fallback_exposure_by_key = _ledger_exposure_by_key(records)
    exposure_by_key: dict[str, Decimal] = {}
    for position in positions:
        if abs(position.position_fp) <= Decimal("0"):
            continue
        side = _position_side(position)
        if side is None:
            continue
        position_key = _live_position_key(position.ticker, side)
        exposure = abs(position.market_exposure_dollars)
        if exposure <= Decimal("0"):
            exposure = fallback_exposure_by_key.get(position_key, Decimal("0"))
        exposure_by_key[position_key] = exposure
    return exposure_by_key


def _live_position_key(ticker: str, side: str) -> str:
    return f"{ticker}:{side}"


def _record_has_live_exposure(record: LivePositionRecord) -> bool:
    return (
        record.filled_count > Decimal("0")
        and record.classification not in {"rejected", "unknown_final_state"}
    )


def _classify_order_result(order: KalshiOrderSummary) -> str:
    if order.status == "rejected":
        return "rejected"
    fill_count = order.fill_count_fp or Decimal("0")
    initial_count = order.initial_count_fp or Decimal("0")
    if fill_count > 0 and initial_count > 0 and fill_count >= initial_count:
        return "filled"
    if order.status in {"canceled", "cancelled", "expired"}:
        return "canceled_or_expired"
    if fill_count > 0:
        return "partially_filled"
    return "unknown_final_state"


def _is_terminal_order(order: KalshiOrderSummary) -> bool:
    return _classify_order_result(order) != "unknown_final_state"
