"""Dry-run and guarded live execution coordination."""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from kalshi_bot.clients.kalshi_client import (
    KalshiClientError,
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
from kalshi_bot.observability.logger import StructuredLogger
from kalshi_bot.observability.replay_engine import ReplayEngine
from kalshi_bot.risk.risk_manager import RiskManager


RISK_APPROVAL_SOURCES = frozenset(
    {"simulation_entry_risk_gate", "live_entry_risk_gate"}
)
LIVE_RUNNER_REALIZED_DAILY_PNL_DOLLARS = Decimal("0")


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

        intents: list[LiveOrderIntent] = []
        for contract in contract_scan_snapshot.ranked_contracts:
            if contract.direction not in {"up", "down"}:
                self._log_contract_intent_skipped(
                    reason="invalid_direction",
                    contract=contract,
                    cycle_number=cycle_number,
                )
                continue
            if contract.midpoint <= Decimal("0"):
                self._log_contract_intent_skipped(
                    reason="invalid_entry_price",
                    contract=contract,
                    cycle_number=cycle_number,
                )
                continue
            if contract.midpoint > MAX_ENTRY_PRICE:
                self._log_contract_intent_skipped(
                    reason="entry_price_too_high",
                    contract=contract,
                    cycle_number=cycle_number,
                )
                continue

            current_exposure_dollars = self._live_current_exposure_dollars()
            risk_decision = entry_risk_manager.evaluate_entry_risk(
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
                    "current_exposure_dollars": current_exposure_dollars,
                    "entry_price": contract.midpoint,
                },
            )
            if int(stake_dollars // contract.midpoint) < 1:
                self._log_contract_intent_skipped(
                    reason="count_below_one",
                    contract=contract,
                    cycle_number=cycle_number,
                    details={"stake_dollars": stake_dollars},
                )
                continue

            intent = build_live_order_intent_from_contract(
                contract,
                stake_dollars=stake_dollars,
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
                },
                )
        return tuple(intents)

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
            max_live_order_count=1,
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
            max_open_positions=getattr(self._settings, "risk_max_open_positions", 2),
            max_total_exposure_dollars=getattr(
                self._settings,
                "risk_max_total_exposure_dollars",
                Decimal("10"),
            ),
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
