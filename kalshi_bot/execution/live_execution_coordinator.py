"""Dry-run and guarded live execution coordination."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from typing import Any

from kalshi_bot.clients.kalshi_client import (
    KalshiClientError,
    KalshiMarketPosition,
    KalshiOrderRequest,
    KalshiOrderSummary,
)
from kalshi_bot.config.settings import (
    DEFAULT_BIAS_CHOP_THRESHOLD_BPS,
    DEFAULT_LIVE_MAX_ENTRY_PRICE_DOLLARS,
    DEFAULT_LIVE_MAX_EXECUTION_SPREAD_DOLLARS,
    KalshiSettings,
)
from kalshi_bot.contracts.contract_scanner import ContractScanSnapshot, ScannedContract
from kalshi_bot.execution.execution_engine import (
    LiveOrderIntent,
    SimulationSnapshot,
    build_live_order_intent,
    build_live_order_intent_from_contract,
)
from kalshi_bot.forecast.bias_engine import TREND_MOMENTUM_CONFIRMATION_MULTIPLIER
from kalshi_bot.market.market_state_cache import MarketStateSnapshot, TickerState
from kalshi_bot.observability.logger import StructuredLogger
from kalshi_bot.observability.replay_engine import ReplayEngine
from kalshi_bot.risk.risk_manager import RiskManager


RISK_APPROVAL_SOURCES = frozenset(
    {"simulation_entry_risk_gate", "live_entry_risk_gate"}
)
LIVE_RUNNER_REALIZED_DAILY_PNL_DOLLARS = Decimal("0")
IMPULSE_OVERRIDE_CLASSIFICATION_REASON = "impulse_override_from_chop"
IMPULSE_OVERRIDE_RANGE_MIDPOINT = Decimal("0.50")


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
class LiveRiskState:
    """Current live exposure inputs used by the live entry risk gate."""

    open_position_count: int
    current_exposure_dollars: Decimal
    source: str


@dataclass(frozen=True)
class ProfitTrailingExitState:
    """Per-position state for optional live profit trailing exits."""

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
        self._profit_trailing_states: dict[str, ProfitTrailingExitState] = {}

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
    ) -> tuple[LiveOrderIntent, ...]:
        """Create live intents directly from ranked contracts after entry risk approval."""

        if not contract_scan_snapshot.ranked_contracts:
            self._log_intent_skipped(
                reason="no_ranked_contracts",
                product_id="",
                market_ticker=None,
                simulation_position_id=None,
                details={"cycle_number": cycle_number},
            )
            return ()

        balance_dollars = self._fetch_live_balance_for_sizing(cycle_number=cycle_number)
        if balance_dollars is None:
            return ()
        entry_risk_manager = self._entry_risk_manager_for_balance(balance_dollars)
        live_risk_state = self._reconcile_live_risk_state(cycle_number=cycle_number)
        max_total_exposure_dollars, max_total_exposure_source = (
            _live_max_total_exposure_settings(self._settings)
        )

        intents: list[LiveOrderIntent] = []
        for contract in contract_scan_snapshot.ranked_contracts:
            min_entry_price = getattr(
                self._settings,
                "live_min_entry_price_dollars",
                Decimal("0"),
            )
            max_entry_price = getattr(
                self._settings,
                "live_max_entry_price_dollars",
                DEFAULT_LIVE_MAX_ENTRY_PRICE_DOLLARS,
            )
            max_execution_spread_dollars = getattr(
                self._settings,
                "live_max_execution_spread_dollars",
                DEFAULT_LIVE_MAX_EXECUTION_SPREAD_DOLLARS,
            )
            if contract.direction not in {"up", "down"}:
                self._log_contract_intent_skipped(
                    reason="invalid_direction",
                    contract=contract,
                    cycle_number=cycle_number,
                )
                continue

            executable_price, skip_reason = _select_executable_price(
                contract,
                max_entry_price=max_entry_price,
                max_execution_spread_dollars=max_execution_spread_dollars,
            )
            if skip_reason is not None or executable_price is None:
                self._log_contract_intent_skipped(
                    reason=skip_reason or "executable_price_missing",
                    contract=contract,
                    cycle_number=cycle_number,
                    details=_executable_price_details(
                        contract,
                        executable_price=executable_price,
                        min_entry_price=min_entry_price,
                        max_entry_price=max_entry_price,
                        max_execution_spread_dollars=max_execution_spread_dollars,
                    ),
                )
                continue
            if (
                min_entry_price > Decimal("0")
                and executable_price < min_entry_price
            ):
                self._log_contract_intent_skipped(
                    reason="executable_price_below_minimum",
                    contract=contract,
                    cycle_number=cycle_number,
                    details={
                        **_executable_price_details(
                            contract,
                            executable_price=executable_price,
                            min_entry_price=min_entry_price,
                            max_entry_price=max_entry_price,
                            max_execution_spread_dollars=(
                                max_execution_spread_dollars
                            ),
                        ),
                    },
                )
                continue
            self._log_and_record(
                event_type="executable_price_selected",
                identifier=contract.market_ticker,
                payload={
                    "cycle_number": cycle_number,
                    "product_id": contract.product_id,
                    "market_ticker": contract.market_ticker,
                    "direction": contract.direction,
                    "side": "yes" if contract.direction == "up" else "no",
                    **_opportunity_diagnostics_payload(contract),
                    "executable_price": executable_price,
                    "best_bid": contract.best_bid,
                    "best_ask": contract.best_ask,
                    "spread_width": contract.best_ask - contract.best_bid,
                    "min_entry_price": min_entry_price,
                    "max_entry_price": max_entry_price,
                    "max_execution_spread_dollars": max_execution_spread_dollars,
                },
            )
            signal_skip_reason, signal_details = _evaluate_signal_gates(
                contract,
                settings=self._settings,
            )
            if signal_skip_reason is not None:
                self._log_contract_intent_skipped(
                    reason=signal_skip_reason,
                    contract=contract,
                    cycle_number=cycle_number,
                    details=signal_details,
                )
                continue

            risk_decision = entry_risk_manager.evaluate_entry_risk(
                product_id=contract.product_id,
                confidence=contract.confidence,
                open_position_count=live_risk_state.open_position_count,
                current_exposure_dollars=live_risk_state.current_exposure_dollars,
                realized_daily_pnl_dollars=LIVE_RUNNER_REALIZED_DAILY_PNL_DOLLARS,
            )
            if not risk_decision.allowed:
                self._log_contract_intent_skipped(
                    reason=risk_decision.reason,
                    contract=contract,
                    cycle_number=cycle_number,
                    details={
                        "current_exposure_dollars": (
                            live_risk_state.current_exposure_dollars
                        ),
                        "open_position_count": live_risk_state.open_position_count,
                        "live_risk_source": live_risk_state.source,
                        "max_total_exposure_dollars": max_total_exposure_dollars,
                        "max_total_exposure_source": max_total_exposure_source,
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
                )
                continue
            self._log_and_record(
                event_type="live_stake_computed",
                identifier=contract.market_ticker,
                payload={
                    "cycle_number": cycle_number,
                    "product_id": contract.product_id,
                    "market_ticker": contract.market_ticker,
                    "confidence": contract.confidence,
                    "balance_dollars": balance_dollars,
                    "stake_dollars": stake_dollars,
                    "current_exposure_dollars": (
                        live_risk_state.current_exposure_dollars
                    ),
                    "open_position_count": live_risk_state.open_position_count,
                    "live_risk_source": live_risk_state.source,
                    "max_total_exposure_dollars": max_total_exposure_dollars,
                    "max_total_exposure_source": max_total_exposure_source,
                    **_opportunity_diagnostics_payload(contract),
                    "entry_price": executable_price,
                    "executable_price": executable_price,
                },
            )
            if int(stake_dollars // executable_price) < 1:
                self._log_contract_intent_skipped(
                    reason="count_below_one",
                    contract=contract,
                    cycle_number=cycle_number,
                    details={
                        "stake_dollars": stake_dollars,
                        "executable_price": executable_price,
                    },
                )
                continue

            intent = build_live_order_intent_from_contract(
                contract,
                stake_dollars=stake_dollars,
                price_dollars=executable_price,
                source_id=f"cycle-{cycle_number}-{contract.product_id}-{contract.market_ticker}"
                if cycle_number is not None
                else None,
            )
            if intent is None:
                self._log_contract_intent_skipped(
                    reason="intent_unavailable",
                    contract=contract,
                    cycle_number=cycle_number,
                    details={"stake_dollars": stake_dollars},
                )
                continue

            intents.append(intent)
            self._log_and_record(
                event_type="live_intent_created",
                identifier=intent.client_order_id,
                payload={
                    "cycle_number": cycle_number,
                    "product_id": intent.product_id,
                    "ticker": intent.ticker,
                    "side": intent.side,
                    "action": intent.action,
                    "price_dollars": intent.price_dollars,
                    "count": intent.count,
                    "stake_dollars": intent.stake_dollars,
                    "direction": intent.direction,
                    "confidence": intent.confidence,
                    "risk_approval_source": intent.risk_approval_source,
                    "structure_gate_candidate_passed": True,
                    "max_total_exposure_dollars": max_total_exposure_dollars,
                    "max_total_exposure_source": max_total_exposure_source,
                    **_signal_diagnostics_payload(
                        contract,
                        settings=self._settings,
                    ),
                },
            )
        return tuple(intents)

    def process_profit_trailing_exits(
        self,
        market_snapshot: MarketStateSnapshot,
        *,
        cycle_number: int | None = None,
    ) -> tuple[LiveSubmissionResult, ...]:
        """Evaluate optional live-only profit trailing exits for current positions."""

        if not getattr(self._settings, "live_profit_trailing_exit_enabled", False):
            return ()
        if self._client is None or not hasattr(self._client, "get_positions"):
            self._log_profit_trailing_exit_skipped(
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
            self._log_profit_trailing_exit_skipped(
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
            _profit_trailing_key(position.ticker, _position_side(position))
            for position in active_positions
            if _position_side(position) is not None
        }
        for key in tuple(self._profit_trailing_states):
            if key not in active_keys:
                self._profit_trailing_states.pop(key, None)

        results: list[LiveSubmissionResult] = []
        for position in active_positions:
            result = self._process_profit_trailing_position(
                position=position,
                market_snapshot=market_snapshot,
                cycle_number=cycle_number,
            )
            if result is not None:
                results.append(result)
        return tuple(results)

    def _process_profit_trailing_position(
        self,
        *,
        position: KalshiMarketPosition,
        market_snapshot: MarketStateSnapshot,
        cycle_number: int | None,
    ) -> LiveSubmissionResult | None:
        side = _position_side(position)
        if side is None:
            self._log_profit_trailing_exit_skipped(
                reason="invalid_position_side",
                cycle_number=cycle_number,
                details={
                    "ticker": position.ticker,
                    "position_count": position.position_fp,
                },
            )
            return None

        ticker_state = market_snapshot.tickers.get(position.ticker)
        if ticker_state is None:
            self._log_profit_trailing_exit_skipped(
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
        payload = _profit_trailing_payload(
            settings=self._settings,
            cycle_number=cycle_number,
            ticker=position.ticker,
            side=side,
            position_count=abs(position.position_fp),
            executable_exit_bid=executable_bid,
            peak_exit_bid=None,
            sell_count=None,
        )
        payload["liquidity_size"] = liquidity_size
        if skip_reason is not None or executable_bid is None:
            self._log_profit_trailing_exit_skipped(
                reason=skip_reason or "executable_exit_bid_missing",
                cycle_number=cycle_number,
                details=payload,
            )
            return None

        min_exit_bid = getattr(
            self._settings,
            "live_profit_exit_min_bid",
            Decimal("0.90"),
        )
        if executable_bid < min_exit_bid:
            self._log_profit_trailing_exit_skipped(
                reason="exit_bid_below_minimum",
                cycle_number=cycle_number,
                details=payload,
            )
            return None

        key = _profit_trailing_key(position.ticker, side)
        position_count = abs(position.position_fp)
        state = self._profit_trailing_states.get(key)
        if (
            state is None
            or state.exit_pending
            or state.last_position_count != position_count
        ):
            state = ProfitTrailingExitState(
                armed=False,
                peak_exit_bid=None,
                last_position_count=position_count,
                exit_pending=False,
            )
            self._profit_trailing_states[key] = state

        activation_price = getattr(
            self._settings,
            "live_profit_trailing_activation_price",
            Decimal("0.90"),
        )
        if not state.armed:
            if executable_bid < activation_price:
                return None
            state = ProfitTrailingExitState(
                armed=True,
                peak_exit_bid=executable_bid,
                last_position_count=position_count,
                exit_pending=False,
            )
            self._profit_trailing_states[key] = state
            self._log_and_record(
                event_type="profit_trailing_exit_armed",
                identifier=position.ticker,
                payload={
                    **payload,
                    "peak_exit_bid": executable_bid,
                },
            )
            return None

        peak_exit_bid = state.peak_exit_bid or executable_bid
        if executable_bid > peak_exit_bid:
            state = ProfitTrailingExitState(
                armed=True,
                peak_exit_bid=executable_bid,
                last_position_count=position_count,
                exit_pending=False,
            )
            self._profit_trailing_states[key] = state
            self._log_and_record(
                event_type="profit_trailing_peak_updated",
                identifier=position.ticker,
                payload={
                    **payload,
                    "peak_exit_bid": executable_bid,
                },
            )
            return None

        trailing_drop = getattr(
            self._settings,
            "live_profit_trailing_drop_dollars",
            Decimal("0.01"),
        )
        if peak_exit_bid - executable_bid < trailing_drop:
            return None

        sell_count = _live_sell_count(
            position_count=position_count,
            max_live_order_count=getattr(self._settings, "live_max_order_count", 1),
        )
        trigger_payload = {
            **payload,
            "peak_exit_bid": peak_exit_bid,
            "sell_count": sell_count,
        }
        if sell_count < 1:
            self._log_profit_trailing_exit_skipped(
                reason="sell_count_unavailable",
                cycle_number=cycle_number,
                details=trigger_payload,
            )
            return None

        self._log_and_record(
            event_type="profit_trailing_exit_triggered",
            identifier=position.ticker,
            payload=trigger_payload,
        )
        return self._submit_profit_trailing_exit_order(
            ticker=position.ticker,
            side=side,
            price_dollars=executable_bid,
            count=sell_count,
            state_key=key,
            cycle_number=cycle_number,
            trigger_payload=trigger_payload,
        )

    def _submit_profit_trailing_exit_order(
        self,
        *,
        ticker: str,
        side: str,
        price_dollars: Decimal,
        count: int,
        state_key: str,
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
                f"profit-trail-{cycle_number}-{ticker}-{side}"
                if cycle_number is not None
                else f"profit-trail-manual-{ticker}-{side}"
            ),
        )
        safety_decision = self._risk_manager.evaluate_live_order(order_request)
        if not safety_decision.allow:
            self._log_profit_trailing_exit_skipped(
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
            reason = "live_client_unavailable"
            self._log_profit_trailing_exit_skipped(
                reason=reason,
                cycle_number=cycle_number,
                details={
                    **trigger_payload,
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
            reason = "order_poll_failed" if order_placed else "order_submit_failed"
            self._log_profit_trailing_exit_skipped(
                reason=reason,
                cycle_number=cycle_number,
                details={
                    **trigger_payload,
                    "message": error_message,
                    **_order_request_payload(order_request),
                },
            )
            return LiveSubmissionResult(
                classification="unknown_final_state" if order_placed else "rejected",
                decision_reason=reason,
                order_placed=order_placed,
                order_id=final_order.order_id if final_order is not None else None,
                final_order=None,
                poll_attempts_used=0,
                error_message=error_message,
            )

        self._profit_trailing_states[state_key] = ProfitTrailingExitState(
            armed=True,
            peak_exit_bid=trigger_payload.get("peak_exit_bid")
            if isinstance(trigger_payload.get("peak_exit_bid"), Decimal)
            else price_dollars,
            last_position_count=Decimal(str(trigger_payload["position_count"])),
            exit_pending=True,
        )
        self._log_and_record(
            event_type="profit_trailing_exit_order_response",
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

    def _log_profit_trailing_exit_skipped(
        self,
        *,
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
            event_type="profit_trailing_exit_skipped",
            identifier=str(payload.get("ticker") or "profit_trailing_exit"),
            payload=payload,
        )

    def _fetch_live_balance_for_sizing(
        self,
        *,
        cycle_number: int | None,
    ) -> Decimal | None:
        if self._client is None:
            self._log_intent_skipped(
                reason="balance_fetch_failed",
                product_id="",
                market_ticker=None,
                simulation_position_id=None,
                details={
                    "cycle_number": cycle_number,
                    "message": "live_client_unavailable",
                },
            )
            return None
        try:
            payload = self._client.get_balance()
            balance_dollars = _balance_dollars_from_payload(payload)
        except (KalshiClientError, ValueError) as exc:
            self._log_intent_skipped(
                reason="balance_fetch_failed",
                product_id="",
                market_ticker=None,
                simulation_position_id=None,
                details={
                    "cycle_number": cycle_number,
                    "message": str(exc),
                },
            )
            return None

        self._log_and_record(
            event_type="balance_fetched_for_sizing",
            identifier="live_runner_balance",
            payload={
                "cycle_number": cycle_number,
                "balance_dollars": balance_dollars,
                "keys": tuple(sorted(payload.keys())),
            },
        )
        return balance_dollars

    def _entry_risk_manager_for_balance(self, balance_dollars: Decimal) -> RiskManager:
        max_total_exposure_dollars, _source = _live_max_total_exposure_settings(
            self._settings
        )
        return RiskManager(
            live_validation_enabled=True,
            live_trading_enabled=getattr(self._settings, "live_trading_enabled", False),
            live_kill_switch_active=getattr(
                self._settings,
                "live_kill_switch_active",
                True,
            ),
            env=getattr(self._settings, "env", "demo"),
            live_validation_env="prod",
            max_live_order_count=getattr(self._settings, "live_max_order_count", 1),
            required_time_in_force=getattr(
                self._settings,
                "live_validation_time_in_force",
                "immediate_or_cancel",
            ),
            account_balance_dollars=balance_dollars,
            min_percent_per_trade=Decimal("0.01"),
            max_percent_per_trade=Decimal("0.01"),
            min_stake_dollars=getattr(
                self._settings,
                "risk_min_stake_dollars",
                Decimal("0.10"),
            ),
            max_stake_dollars=getattr(
                self._settings,
                "risk_max_stake_dollars",
                Decimal("3"),
            ),
            max_open_positions=getattr(
                self._settings,
                "live_max_open_positions",
                1,
            ),
            max_total_exposure_dollars=max_total_exposure_dollars,
            daily_loss_limit_dollars=getattr(
                self._settings,
                "risk_daily_loss_limit_dollars",
                Decimal("5"),
            ),
            risk_kill_switch_active=getattr(
                self._settings,
                "risk_kill_switch_active",
                False,
            ),
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
            if _is_terminal_order(created_order):
                final_order = created_order
                poll_attempts_used = 0
            else:
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
        details: dict[str, object] | None = None,
    ) -> None:
        payload = {
            "cycle_number": cycle_number,
            "direction": contract.direction,
            "structure": contract.structure,
            "confidence": contract.confidence,
            "entry_price": contract.midpoint,
            **_signal_diagnostics_payload(
                contract,
                settings=self._settings,
            ),
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

    def _reconcile_live_risk_state(
        self,
        *,
        cycle_number: int | None,
    ) -> LiveRiskState:
        ledger_state = self._ledger_live_risk_state()
        if self._client is None or not hasattr(self._client, "get_positions"):
            self._log_live_risk_state(
                cycle_number=cycle_number,
                state=ledger_state,
                position_tickers=(),
                message="positions_client_unavailable",
            )
            return ledger_state

        try:
            position_page = self._client.get_positions(
                count_filter="position",
                settlement_status="unsettled",
                limit=1000,
            )
        except KalshiClientError as exc:
            self._log_live_risk_state(
                cycle_number=cycle_number,
                state=ledger_state,
                position_tickers=(),
                message=f"positions_fetch_failed: {exc}",
            )
            return ledger_state

        active_positions = tuple(
            position
            for position in position_page.market_positions
            if abs(position.position_fp) > Decimal("0")
        )
        exposure_dollars = sum(
            (abs(position.market_exposure_dollars) for position in active_positions),
            Decimal("0"),
        )
        kalshi_state = LiveRiskState(
            open_position_count=len(active_positions),
            current_exposure_dollars=exposure_dollars,
            source="kalshi_positions",
        )
        self._log_live_risk_state(
            cycle_number=cycle_number,
            state=kalshi_state,
            position_tickers=tuple(position.ticker for position in active_positions[:10]),
        )
        if (
            self._raw_ledger_exposure_dollars() > Decimal("0")
            and kalshi_state.open_position_count == 0
            and kalshi_state.current_exposure_dollars == Decimal("0")
        ):
            self._log_and_record(
                event_type="stale_live_exposure_cleared",
                identifier="live_risk_state",
                payload={
                    "cycle_number": cycle_number,
                    "ledger_open_position_count": ledger_state.open_position_count,
                    "ledger_current_exposure_dollars": (
                        ledger_state.current_exposure_dollars
                    ),
                    "raw_ledger_exposure_dollars": (
                        self._raw_ledger_exposure_dollars()
                    ),
                    "kalshi_open_position_count": kalshi_state.open_position_count,
                    "kalshi_current_exposure_dollars": (
                        kalshi_state.current_exposure_dollars
                    ),
                },
            )
        return kalshi_state

    def _ledger_live_risk_state(self) -> LiveRiskState:
        return LiveRiskState(
            open_position_count=self._live_open_position_count(),
            current_exposure_dollars=self._live_current_exposure_dollars(),
            source="ledger_fallback",
        )

    def _log_live_risk_state(
        self,
        *,
        cycle_number: int | None,
        state: LiveRiskState,
        position_tickers: tuple[str, ...],
        message: str | None = None,
    ) -> None:
        payload = {
            "cycle_number": cycle_number,
            "source": state.source,
            "open_position_count": state.open_position_count,
            "current_exposure_dollars": state.current_exposure_dollars,
            "position_ticker_sample": position_tickers,
        }
        if message is not None:
            payload["message"] = message
        self._log_and_record(
            event_type="live_position_reconciled",
            identifier="live_risk_state",
            payload=payload,
        )
        self._log_and_record(
            event_type="live_open_position_count",
            identifier="live_risk_state",
            payload={
                "cycle_number": cycle_number,
                "source": state.source,
                "open_position_count": state.open_position_count,
            },
        )
        self._log_and_record(
            event_type="live_current_exposure_dollars",
            identifier="live_risk_state",
            payload={
                "cycle_number": cycle_number,
                "source": state.source,
                "current_exposure_dollars": state.current_exposure_dollars,
            },
        )

    def _live_open_position_count(self) -> int:
        return sum(
            1
            for record in self._live_position_ledger.values()
            if _record_has_live_exposure(record)
        )

    def _live_current_exposure_dollars(self) -> Decimal:
        return sum(
            (
                record.filled_count * record.price_dollars
                for record in self._live_position_ledger.values()
                if _record_has_live_exposure(record)
            ),
            Decimal("0"),
        )

    def _raw_ledger_exposure_dollars(self) -> Decimal:
        return sum(
            (
                record.filled_count * record.price_dollars
                for record in self._live_position_ledger.values()
                if record.filled_count > Decimal("0")
            ),
            Decimal("0"),
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


def _live_max_total_exposure_settings(
    settings: KalshiSettings,
) -> tuple[Decimal, str]:
    live_override = getattr(settings, "live_max_total_exposure_dollars", None)
    if live_override is not None:
        return Decimal(str(live_override)), "live_override"
    return (
        getattr(settings, "risk_max_total_exposure_dollars", Decimal("10")),
        "base_risk",
    )


def _select_executable_price(
    contract: ScannedContract,
    *,
    max_entry_price: Decimal,
    max_execution_spread_dollars: Decimal,
) -> tuple[Decimal | None, str | None]:
    best_bid = contract.best_bid
    best_ask = contract.best_ask
    if best_bid is None or best_ask is None:
        return None, "executable_price_missing"

    spread_width = best_ask - best_bid
    if spread_width < Decimal("0") or spread_width > max_execution_spread_dollars:
        return None, "unsafe_executable_spread"

    if contract.direction == "up":
        executable_price = best_ask
    elif contract.direction == "down":
        executable_price = Decimal("1") - best_bid
    else:
        return None, "invalid_direction"

    if executable_price <= Decimal("0"):
        return None, "executable_price_missing"
    if executable_price > max_entry_price:
        return executable_price, "executable_price_above_limit"
    return executable_price, None


def _select_executable_exit_bid(
    ticker_state: TickerState,
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


def _profit_trailing_key(ticker: str, side: str | None) -> str:
    return f"{ticker}:{side or 'unknown'}"


def _live_sell_count(
    *,
    position_count: Decimal,
    max_live_order_count: int,
) -> int:
    floored_position_count = int(
        position_count.to_integral_value(rounding=ROUND_FLOOR)
    )
    return max(min(floored_position_count, max_live_order_count), 0)


def _profit_trailing_payload(
    *,
    settings: KalshiSettings,
    cycle_number: int | None,
    ticker: str,
    side: str,
    position_count: Decimal,
    executable_exit_bid: Decimal | None,
    peak_exit_bid: Decimal | None,
    sell_count: int | None,
) -> dict[str, object]:
    return {
        "cycle_number": cycle_number,
        "ticker": ticker,
        "side": side,
        "position_count": position_count,
        "executable_exit_bid": executable_exit_bid,
        "peak_exit_bid": peak_exit_bid,
        "activation_price": getattr(
            settings,
            "live_profit_trailing_activation_price",
            Decimal("0.90"),
        ),
        "trailing_drop_dollars": getattr(
            settings,
            "live_profit_trailing_drop_dollars",
            Decimal("0.01"),
        ),
        "min_exit_bid": getattr(
            settings,
            "live_profit_exit_min_bid",
            Decimal("0.90"),
        ),
        "sell_count": sell_count,
    }


def _executable_price_details(
    contract: ScannedContract,
    *,
    executable_price: Decimal | None,
    min_entry_price: Decimal,
    max_entry_price: Decimal,
    max_execution_spread_dollars: Decimal,
) -> dict[str, object]:
    best_bid = contract.best_bid
    best_ask = contract.best_ask
    spread_width = None
    if best_bid is not None and best_ask is not None:
        spread_width = best_ask - best_bid
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread_width": spread_width,
        "executable_price": executable_price,
        "min_entry_price": min_entry_price,
        "max_entry_price": max_entry_price,
        "max_execution_spread_dollars": max_execution_spread_dollars,
    }


def _evaluate_signal_gates(
    contract: ScannedContract,
    *,
    settings: KalshiSettings,
) -> tuple[str | None, dict[str, object]]:
    details = {
        **_signal_diagnostics_payload(contract, settings=settings),
        "structure_gate_candidate_passed": False,
    }
    if getattr(contract, "opportunity_source", None) == "mispricing":
        return None, details

    impulse_skip_reason = _apply_impulse_override_signal_gate(
        contract,
        settings=settings,
        details=details,
    )
    if impulse_skip_reason is not None:
        return impulse_skip_reason, details

    if getattr(settings, "live_require_momentum_alignment", False):
        aligned = _contract_recent_momentum_aligned(contract)
        details["momentum_aligned_with_direction"] = aligned
        if aligned is None:
            return "signal_gate_data_unavailable", details
        if not aligned:
            return "signal_momentum_not_aligned", details

    if (
        getattr(settings, "live_require_trend_momentum_confirmation", False)
        and contract.structure == "trend"
    ):
        confirmed = _contract_trend_momentum_confirmed(contract, settings=settings)
        if confirmed is None:
            return "signal_gate_data_unavailable", details
        if not confirmed:
            return "trend_momentum_unconfirmed", details

    if (
        getattr(settings, "live_require_reversal_range_position", False)
        and contract.structure in {"reversal", "exhaustion"}
    ):
        range_position = getattr(contract, "range_position_15m", None)
        min_range_position = getattr(
            settings,
            "live_min_reversal_range_position",
            Decimal("0.50"),
        )
        details["min_reversal_range_position"] = min_range_position
        if range_position is None:
            return "signal_gate_data_unavailable", details
        if Decimal(str(range_position)) < min_range_position:
            return "reversal_range_position_below_minimum", details

    return None, details


def _apply_impulse_override_signal_gate(
    contract: ScannedContract,
    *,
    settings: KalshiSettings,
    details: dict[str, object],
) -> str | None:
    if (
        getattr(contract, "classification_reason", None)
        != IMPULSE_OVERRIDE_CLASSIFICATION_REASON
    ):
        return None

    if getattr(settings, "live_block_impulse_override_from_chop", False):
        details["impulse_override_allowed"] = False
        details["impulse_override_block_reason"] = (
            "blocked_by_live_block_impulse_override_from_chop"
        )
        return "impulse_override_from_chop_blocked"

    if getattr(settings, "live_impulse_override_require_momentum_alignment", False):
        aligned = _contract_recent_momentum_aligned(contract)
        details["momentum_aligned_with_direction"] = aligned
        if aligned is None:
            details["impulse_override_allowed"] = False
            details["impulse_override_block_reason"] = "missing_recent_return"
            return "signal_gate_data_unavailable"
        if not aligned:
            details["impulse_override_allowed"] = False
            details["impulse_override_block_reason"] = "momentum_not_aligned"
            return "impulse_override_momentum_not_aligned"

    min_recent_return_bps = getattr(
        settings,
        "live_impulse_override_min_recent_return_bps",
        None,
    )
    if min_recent_return_bps is not None:
        recent_return_bps = getattr(contract, "recent_return_bps", None)
        details["recent_return_required_bps"] = min_recent_return_bps
        if recent_return_bps is None:
            details["impulse_override_allowed"] = False
            details["impulse_override_block_reason"] = "missing_recent_return"
            return "signal_gate_data_unavailable"
        if abs(Decimal(str(recent_return_bps))) < min_recent_return_bps:
            details["impulse_override_allowed"] = False
            details["impulse_override_block_reason"] = "recent_return_below_minimum"
            return "impulse_override_recent_return_below_minimum"

    if getattr(settings, "live_impulse_override_require_range_position", False):
        range_position = getattr(contract, "range_position_15m", None)
        if range_position is None:
            details["impulse_override_allowed"] = False
            details["impulse_override_block_reason"] = "missing_range_position"
            return "signal_gate_data_unavailable"
        range_position_decimal = Decimal(str(range_position))
        if (
            contract.direction == "up"
            and range_position_decimal < IMPULSE_OVERRIDE_RANGE_MIDPOINT
        ):
            details["impulse_override_allowed"] = False
            details["impulse_override_block_reason"] = (
                "range_position_below_midpoint_for_up"
            )
            return "impulse_override_range_position_against_direction"
        if (
            contract.direction == "down"
            and range_position_decimal > IMPULSE_OVERRIDE_RANGE_MIDPOINT
        ):
            details["impulse_override_allowed"] = False
            details["impulse_override_block_reason"] = (
                "range_position_above_midpoint_for_down"
            )
            return "impulse_override_range_position_against_direction"
        if contract.direction not in {"up", "down"}:
            details["impulse_override_allowed"] = False
            details["impulse_override_block_reason"] = "direction_not_actionable"
            return "signal_gate_data_unavailable"

    details["impulse_override_allowed"] = True
    details["impulse_override_block_reason"] = None
    return None


def _contract_trend_momentum_confirmed(
    contract: ScannedContract,
    *,
    settings: KalshiSettings,
) -> bool | None:
    override_threshold = getattr(
        settings,
        "live_trend_momentum_min_recent_return_bps",
        None,
    )
    if override_threshold is None:
        return getattr(contract, "trend_momentum_confirmed", None)
    return _recent_return_meets_directional_threshold(
        contract,
        threshold=override_threshold,
    )


def _recent_return_meets_directional_threshold(
    contract: ScannedContract,
    *,
    threshold: Decimal,
) -> bool | None:
    aligned = _contract_recent_momentum_aligned(contract)
    if aligned is None:
        return None
    recent_return_bps = getattr(contract, "recent_return_bps", None)
    if recent_return_bps is None:
        return None
    return aligned and abs(Decimal(str(recent_return_bps))) >= threshold


def _contract_recent_momentum_aligned(contract: ScannedContract) -> bool | None:
    recent_return_bps = getattr(contract, "recent_return_bps", None)
    if recent_return_bps is None:
        return None
    recent_return = Decimal(str(recent_return_bps))
    if contract.direction == "up":
        return recent_return > 0
    if contract.direction == "down":
        return recent_return < 0
    return None


def _signal_diagnostics_payload(
    contract: ScannedContract,
    *,
    settings: KalshiSettings | None = None,
) -> dict[str, object]:
    trend_momentum_threshold = _trend_momentum_threshold(settings)
    confirmed = (
        _contract_trend_momentum_confirmed(contract, settings=settings)
        if settings is not None
        else getattr(contract, "trend_momentum_confirmed", None)
    )
    trend_confirmed_reason = _trend_momentum_confirmed_reason(
        contract,
        threshold=trend_momentum_threshold,
        confirmed=confirmed,
    )
    impulse_recent_return_required_bps = (
        getattr(settings, "live_impulse_override_min_recent_return_bps", None)
        if settings is not None
        else None
    )
    recent_return_required_bps = (
        impulse_recent_return_required_bps
        if (
            getattr(contract, "classification_reason", None)
            == IMPULSE_OVERRIDE_CLASSIFICATION_REASON
            and impulse_recent_return_required_bps is not None
        )
        else trend_momentum_threshold if contract.structure == "trend" else None
    )
    impulse_override_allowed = None
    impulse_override_block_reason = None
    if (
        getattr(contract, "classification_reason", None)
        == IMPULSE_OVERRIDE_CLASSIFICATION_REASON
    ):
        impulse_override_allowed = True

    return {
        "lookback_return_bps": getattr(contract, "lookback_return_bps", None),
        "recent_return_bps": getattr(contract, "recent_return_bps", None),
        "momentum_aligned_with_direction": getattr(
            contract,
            "momentum_aligned_with_direction",
            None,
        ),
        "trend_momentum_confirmed": getattr(
            contract,
            "trend_momentum_confirmed",
            None,
        ),
        "range_position_15m": getattr(contract, "range_position_15m", None),
        "classification_reason": getattr(contract, "classification_reason", None),
        "confidence_reason": getattr(contract, "confidence_reason", None),
        "utc_hour": getattr(contract, "utc_hour", None),
        "impulse_override_allowed": impulse_override_allowed,
        "impulse_override_block_reason": impulse_override_block_reason,
        "trend_momentum_threshold": trend_momentum_threshold,
        "recent_return_required_bps": recent_return_required_bps,
        "trend_momentum_confirmed_reason": trend_confirmed_reason,
        **_opportunity_diagnostics_payload(contract),
    }


def _opportunity_diagnostics_payload(contract: ScannedContract) -> dict[str, object]:
    opportunity_source = getattr(contract, "opportunity_source", None)
    if opportunity_source != "mispricing":
        if opportunity_source is None:
            return {}
        return {"opportunity_source": opportunity_source}
    external_price_timestamp = getattr(contract, "external_price_timestamp", None)
    market_as_of = getattr(contract, "market_as_of", None)
    return {
        "opportunity_source": opportunity_source,
        "external_price": getattr(contract, "external_price", None),
        "external_price_timestamp": external_price_timestamp,
        "contract_target_price": getattr(contract, "contract_target_price", None),
        "target_source_field": getattr(contract, "target_source_field", None),
        "market_as_of": market_as_of,
        "distance_to_target": getattr(contract, "distance_to_target", None),
        "implied_side": getattr(contract, "implied_side", None),
        "kalshi_yes_bid": getattr(contract, "kalshi_yes_bid", None),
        "kalshi_yes_ask": getattr(contract, "kalshi_yes_ask", None),
        "kalshi_no_bid": getattr(contract, "kalshi_no_bid", None),
        "kalshi_no_ask": getattr(contract, "kalshi_no_ask", None),
        "executable_price": getattr(contract, "executable_price", None),
        "edge_bps": getattr(contract, "edge_bps", None),
        "external_price_age_ms": _timestamp_age_ms(
            external_price_timestamp,
            fallback=getattr(contract, "external_price_age_ms", None),
        ),
        "kalshi_quote_age_ms": _timestamp_age_ms(
            market_as_of,
            fallback=getattr(contract, "kalshi_quote_age_ms", None),
        ),
        "cycle_started_at": getattr(contract, "cycle_started_at", None),
        "intent_latency_ms": _intent_latency_ms(contract),
        "lag_detected": getattr(contract, "lag_detected", None),
        "reason_selected": getattr(contract, "reason_selected", None),
        "reason_skipped": getattr(contract, "reason_skipped", None),
    }


def _intent_latency_ms(contract: ScannedContract) -> int | None:
    existing = getattr(contract, "intent_latency_ms", None)
    if existing is not None:
        return existing
    cycle_started_at = getattr(contract, "cycle_started_at", None)
    parsed = _parse_timestamp(cycle_started_at)
    if parsed is None:
        return None
    return max(
        int((datetime.now(timezone.utc) - parsed).total_seconds() * 1000),
        0,
    )


def _timestamp_age_ms(value: str | None, *, fallback: int | None) -> int | None:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return fallback
    return max(
        int((datetime.now(timezone.utc) - parsed).total_seconds() * 1000),
        0,
    )


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    stripped = str(value).strip()
    if not stripped:
        return None
    if stripped.isdigit():
        return datetime.fromtimestamp(int(stripped) / 1000, tz=timezone.utc)
    try:
        parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _trend_momentum_threshold(settings: KalshiSettings | None) -> Decimal:
    if settings is not None:
        override_threshold = getattr(
            settings,
            "live_trend_momentum_min_recent_return_bps",
            None,
        )
        if override_threshold is not None:
            return override_threshold
        chop_threshold_bps = getattr(
            settings,
            "bias_chop_threshold_bps",
            DEFAULT_BIAS_CHOP_THRESHOLD_BPS,
        )
    else:
        chop_threshold_bps = DEFAULT_BIAS_CHOP_THRESHOLD_BPS
    return (
        Decimal(str(chop_threshold_bps))
        * TREND_MOMENTUM_CONFIRMATION_MULTIPLIER
    )


def _trend_momentum_confirmed_reason(
    contract: ScannedContract,
    *,
    threshold: Decimal,
    confirmed: bool | None,
) -> str | None:
    if contract.structure != "trend":
        return None
    if contract.direction not in {"up", "down"}:
        return "direction_not_actionable"
    recent_return_bps = getattr(contract, "recent_return_bps", None)
    if recent_return_bps is None:
        return "missing_recent_return"
    aligned = _contract_recent_momentum_aligned(contract)
    if aligned is None:
        return "direction_not_actionable"
    if not aligned:
        return "momentum_not_aligned"
    if abs(Decimal(str(recent_return_bps))) < threshold:
        return "recent_return_below_threshold"
    if confirmed is None:
        return "missing_trend_momentum_confirmed"
    if confirmed is False:
        return "provided_confirmation_false"
    return "confirmed"


def _balance_dollars_from_payload(payload: dict[str, object]) -> Decimal:
    if "balance" not in payload:
        raise ValueError("balance missing from Kalshi balance payload.")
    raw_balance = payload["balance"]
    if isinstance(raw_balance, bool):
        raise ValueError("balance is not decimal-compatible.")
    try:
        balance = Decimal(str(raw_balance))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("balance is not decimal-compatible.") from exc

    if balance <= Decimal("0"):
        raise ValueError("balance must be greater than zero.")
    if isinstance(raw_balance, int):
        return balance / Decimal("100")
    if isinstance(raw_balance, str) and raw_balance.strip().isdigit():
        return balance / Decimal("100")
    return balance


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


def _record_has_live_exposure(record: LivePositionRecord) -> bool:
    return (
        record.filled_count > Decimal("0")
        and record.classification == "partially_filled"
        and record.status.lower()
        not in {"canceled", "cancelled", "expired", "settled", "closed", "rejected"}
    )


def _classify_order_result(order: KalshiOrderSummary) -> str:
    status = order.status.lower()
    if status == "rejected":
        return "rejected"
    if status in {"canceled", "cancelled", "expired"}:
        return "canceled_or_expired"
    fill_count = order.fill_count_fp or Decimal("0")
    initial_count = order.initial_count_fp or Decimal("0")
    if fill_count > 0 and initial_count > 0 and fill_count >= initial_count:
        return "filled"
    if fill_count > 0:
        return "partially_filled"
    return "unknown_final_state"


def _is_terminal_order(order: KalshiOrderSummary) -> bool:
    return _classify_order_result(order) != "unknown_final_state"
