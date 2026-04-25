"""Simulation-only execution engine for Phase 8."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import time
import uuid

from kalshi_bot.clients.kalshi_client import (
    KalshiClient,
    KalshiClientError,
    KalshiOrderRequest,
    KalshiOrderSummary,
)
from kalshi_bot.config.settings import KalshiSettings
from kalshi_bot.contracts.contract_scanner import ContractScanSnapshot, ScannedContract
from kalshi_bot.execution.exit_manager import (
    ClosedSimulatedPosition,
    determine_exit_decisions,
)
from kalshi_bot.observability.logger import StructuredLogger
from kalshi_bot.observability.replay_engine import ReplayEngine
from kalshi_bot.risk.risk_manager import RiskManager


MAX_ENTRY_PRICE = Decimal("0.800")


class SimulationExecutionError(ValueError):
    """Raised when simulation execution configuration is invalid."""


class LiveExecutionSmokeError(ValueError):
    """Raised when live validation configuration is invalid."""


@dataclass(frozen=True)
class SimulatedPosition:
    """In-memory open simulated position state."""

    position_id: str
    product_id: str
    market_ticker: str
    direction: str
    structure: str
    confidence: int
    entry_price: Decimal
    latest_price: Decimal
    stake_dollars: Decimal | None
    status: str
    opened_at: str | None
    updated_at: str | None
    update_count: int


@dataclass(frozen=True)
class SimulationDecision:
    """Deterministic per-evaluation simulation decision record."""

    action: str
    position_id: str | None
    product_id: str
    market_ticker: str | None
    reason: str | None


@dataclass(frozen=True)
class SimulationSnapshot:
    """Current simulated execution state."""

    open_positions: dict[str, SimulatedPosition]
    closed_positions: tuple[ClosedSimulatedPosition, ...]
    decisions: tuple[SimulationDecision, ...]
    evaluation_count: int


@dataclass(frozen=True)
class LiveValidationOrder:
    """Explicit tiny live-validation order configuration."""

    ticker: str
    action: str
    side: str
    count: int
    price_dollars: Decimal
    time_in_force: str
    client_order_id: str


@dataclass(frozen=True)
class LiveValidationResult:
    """Outcome of one live execution smoke-test run."""

    classification: str
    decision_reason: str | None
    order_placed: bool
    order_id: str | None
    final_order: KalshiOrderSummary | None
    poll_attempts_used: int
    balance_fetched: bool
    balance_payload: dict[str, object] | None
    error_message: str | None


@dataclass(frozen=True)
class LiveValidationSnapshot:
    """Inspectable snapshot for one live smoke-test invocation."""

    requested_order: LiveValidationOrder
    result: LiveValidationResult


class SimulationExecutionEngine:
    """Simulation-only execution engine over ranked scanner output."""

    def __init__(
        self,
        *,
        enabled: bool,
        max_new_positions_per_evaluation: int,
        position_id_prefix: str,
        exit_enabled: bool,
        allow_same_pass_reentry: bool,
        risk_manager: RiskManager | None = None,
    ) -> None:
        if not enabled:
            raise SimulationExecutionError("Simulation execution is disabled.")
        if max_new_positions_per_evaluation <= 0:
            raise SimulationExecutionError(
                "max_new_positions_per_evaluation must be greater than zero."
            )
        normalized_prefix = position_id_prefix.strip()
        if not normalized_prefix:
            raise SimulationExecutionError("position_id_prefix is required.")

        self._max_new_positions_per_evaluation = max_new_positions_per_evaluation
        self._position_id_prefix = normalized_prefix
        self._exit_enabled = exit_enabled
        self._allow_same_pass_reentry = allow_same_pass_reentry
        self._risk_manager = risk_manager or _default_simulation_risk_manager()
        self._open_positions: dict[str, SimulatedPosition] = {}
        self._position_id_by_product: dict[str, str] = {}
        self._closed_positions: list[ClosedSimulatedPosition] = []
        self._latest_snapshot = SimulationSnapshot(
            open_positions={},
            closed_positions=(),
            decisions=(),
            evaluation_count=0,
        )
        self._next_position_number = 1

    @classmethod
    def from_settings(
        cls,
        settings: KalshiSettings,
        risk_manager: RiskManager | None = None,
    ) -> "SimulationExecutionEngine":
        return cls(
            enabled=settings.simulation_enabled,
            max_new_positions_per_evaluation=settings.simulation_max_new_positions_per_evaluation,
            position_id_prefix=settings.simulation_position_id_prefix,
            exit_enabled=settings.simulation_exit_enabled,
            allow_same_pass_reentry=settings.simulation_allow_same_pass_reentry,
            risk_manager=risk_manager or RiskManager.from_settings(settings),
        )

    def evaluate(self, scan_snapshot: ContractScanSnapshot) -> SimulationSnapshot:
        ranked_by_market = {
            contract.market_ticker: contract for contract in scan_snapshot.ranked_contracts
        }
        decisions: list[SimulationDecision] = []
        closed_product_ids = self._apply_exit_decisions(
            scan_snapshot=scan_snapshot,
            decisions=decisions,
        )
        self._update_open_positions(
            ranked_by_market=ranked_by_market,
            decisions=decisions,
        )
        self._consider_new_entry(
            ranked_contracts=scan_snapshot.ranked_contracts,
            decisions=decisions,
            closed_product_ids=closed_product_ids,
        )

        self._latest_snapshot = SimulationSnapshot(
            open_positions=dict(self._open_positions),
            closed_positions=tuple(self._closed_positions),
            decisions=tuple(decisions),
            evaluation_count=self._latest_snapshot.evaluation_count + 1,
        )
        return self._latest_snapshot

    def snapshot(self) -> SimulationSnapshot:
        return self._latest_snapshot

    def _apply_exit_decisions(
        self,
        *,
        scan_snapshot: ContractScanSnapshot,
        decisions: list[SimulationDecision],
    ) -> set[str]:
        if not self._exit_enabled or not self._open_positions:
            return set()

        exit_decisions = determine_exit_decisions(
            open_positions=self._open_positions,
            ranked_contracts=scan_snapshot.ranked_contracts,
        )
        closed_product_ids: set[str] = set()
        for exit_decision in exit_decisions:
            position = self._open_positions.pop(exit_decision.position_id, None)
            if position is None:
                continue
            self._position_id_by_product.pop(position.product_id, None)
            closed_product_ids.add(position.product_id)
            self._closed_positions.append(
                ClosedSimulatedPosition(
                    position_id=position.position_id,
                    product_id=position.product_id,
                    market_ticker=position.market_ticker,
                    direction=position.direction,
                    structure=position.structure,
                    confidence=position.confidence,
                    entry_price=position.entry_price,
                    exit_price=exit_decision.exit_price,
                    stake_dollars=position.stake_dollars,
                    status="closed",
                    opened_at=position.opened_at,
                    closed_at=exit_decision.closed_at,
                    updated_at=position.updated_at,
                    update_count=position.update_count,
                    exit_reason=exit_decision.exit_reason,
                )
            )
            decisions.append(
                SimulationDecision(
                    action="close_position",
                    position_id=position.position_id,
                    product_id=position.product_id,
                    market_ticker=position.market_ticker,
                    reason=exit_decision.exit_reason,
                )
            )
        return closed_product_ids

    def _update_open_positions(
        self,
        *,
        ranked_by_market: dict[str, ScannedContract],
        decisions: list[SimulationDecision],
    ) -> None:
        for position_id in sorted(self._open_positions):
            position = self._open_positions[position_id]
            ranked_contract = ranked_by_market.get(position.market_ticker)
            if ranked_contract is None:
                continue
            self._open_positions[position_id] = SimulatedPosition(
                position_id=position.position_id,
                product_id=position.product_id,
                market_ticker=position.market_ticker,
                direction=position.direction,
                structure=ranked_contract.structure,
                confidence=ranked_contract.confidence,
                entry_price=position.entry_price,
                latest_price=ranked_contract.midpoint,
                stake_dollars=position.stake_dollars,
                status=position.status,
                opened_at=position.opened_at,
                updated_at=_reference_timestamp(ranked_contract),
                update_count=position.update_count + 1,
            )
            decisions.append(
                SimulationDecision(
                    action="update_position",
                    position_id=position.position_id,
                    product_id=position.product_id,
                    market_ticker=position.market_ticker,
                    reason=None,
                )
            )

    def _consider_new_entry(
        self,
        *,
        ranked_contracts: tuple[ScannedContract, ...],
        decisions: list[SimulationDecision],
        closed_product_ids: set[str],
    ) -> None:
        if not ranked_contracts:
            decisions.append(
                SimulationDecision(
                    action="skip_entry",
                    position_id=None,
                    product_id="",
                    market_ticker=None,
                    reason="no_ranked_contracts",
                )
            )
            return

        if self._max_new_positions_per_evaluation <= 0:
            decisions.append(
                SimulationDecision(
                    action="skip_entry",
                    position_id=None,
                    product_id=ranked_contracts[0].product_id,
                    market_ticker=ranked_contracts[0].market_ticker,
                    reason="max_new_positions_reached",
                )
            )
            return

        initial_decision_count = len(decisions)
        for ranked_contract in ranked_contracts:
            existing_position_id = self._position_id_by_product.get(ranked_contract.product_id)
            if existing_position_id is not None:
                decisions.append(
                    SimulationDecision(
                        action="skip_entry",
                        position_id=existing_position_id,
                        product_id=ranked_contract.product_id,
                        market_ticker=ranked_contract.market_ticker,
                        reason="open_position_for_product",
                    )
                )
                continue
            if (
                not self._allow_same_pass_reentry
                and ranked_contract.product_id in closed_product_ids
            ):
                decisions.append(
                    SimulationDecision(
                        action="skip_entry",
                        position_id=None,
                        product_id=ranked_contract.product_id,
                        market_ticker=ranked_contract.market_ticker,
                        reason="same_pass_reentry_disallowed",
                    )
                )
                continue

            if ranked_contract.midpoint > MAX_ENTRY_PRICE:
                decisions.append(
                    SimulationDecision(
                        action="skip_entry",
                        position_id=None,
                        product_id=ranked_contract.product_id,
                        market_ticker=ranked_contract.market_ticker,
                        reason="entry_price_too_high",
                    )
                )
                continue

            risk_decision = self._risk_manager.evaluate_entry_risk(
                product_id=ranked_contract.product_id,
                confidence=ranked_contract.confidence,
                open_position_count=len(self._open_positions),
                current_exposure_dollars=_current_exposure_dollars(
                    self._open_positions.values()
                ),
                realized_daily_pnl_dollars=_realized_pnl_dollars(
                    self._closed_positions
                ),
            )
            if not risk_decision.allowed:
                decisions.append(
                    SimulationDecision(
                        action="skip_entry",
                        position_id=None,
                        product_id=ranked_contract.product_id,
                        market_ticker=ranked_contract.market_ticker,
                        reason=risk_decision.reason,
                    )
                )
                continue

            position = self._open_position_from_contract(
                ranked_contract,
                stake_dollars=risk_decision.stake_dollars,
            )
            self._open_positions[position.position_id] = position
            self._position_id_by_product[position.product_id] = position.position_id
            decisions.append(
                SimulationDecision(
                    action="open_position",
                    position_id=position.position_id,
                    product_id=position.product_id,
                    market_ticker=position.market_ticker,
                    reason=None,
                )
            )
            return

        if len(decisions) == initial_decision_count:
            decisions.append(
                SimulationDecision(
                    action="skip_entry",
                    position_id=None,
                    product_id=ranked_contracts[0].product_id,
                    market_ticker=ranked_contracts[0].market_ticker,
                    reason="no_eligible_ranked_contract",
                )
            )

    def _open_position_from_contract(
        self,
        contract: ScannedContract,
        *,
        stake_dollars: Decimal | None,
    ) -> SimulatedPosition:
        position_id = f"{self._position_id_prefix}-{self._next_position_number:04d}"
        self._next_position_number += 1
        reference_timestamp = _reference_timestamp(contract)
        return SimulatedPosition(
            position_id=position_id,
            product_id=contract.product_id,
            market_ticker=contract.market_ticker,
            direction=contract.direction,
            structure=contract.structure,
            confidence=contract.confidence,
            entry_price=contract.midpoint,
            latest_price=contract.midpoint,
            stake_dollars=stake_dollars,
            status="open",
            opened_at=reference_timestamp,
            updated_at=reference_timestamp,
            update_count=0,
        )


def _current_exposure_dollars(positions) -> Decimal:
    return sum(
        (position.stake_dollars or Decimal("0") for position in positions),
        Decimal("0"),
    )


def _realized_pnl_dollars(positions) -> Decimal:
    return sum(
        (
            (position.exit_price - position.entry_price)
            * (position.stake_dollars or Decimal("0"))
            for position in positions
        ),
        Decimal("0"),
    )


def _default_simulation_risk_manager() -> RiskManager:
    return RiskManager(
        live_validation_enabled=False,
        live_trading_enabled=False,
        live_kill_switch_active=False,
        env="demo",
        live_validation_env="prod",
    )


def _reference_timestamp(contract: ScannedContract) -> str | None:
    if contract.market_as_of:
        return contract.market_as_of
    return contract.bias_as_of


class LiveExecutionSmokeTester:
    """Submit one tiny live IOC order and inspect the resulting state."""

    def __init__(
        self,
        *,
        client: KalshiClient,
        logger: StructuredLogger,
        replay_engine: ReplayEngine,
        order: LiveValidationOrder,
        poll_attempts: int,
        poll_interval_seconds: float,
        risk_manager: RiskManager,
        sleep_fn=time.sleep,
    ) -> None:
        if poll_attempts <= 0:
            raise LiveExecutionSmokeError("poll_attempts must be greater than zero.")
        if poll_interval_seconds <= 0:
            raise LiveExecutionSmokeError("poll_interval_seconds must be greater than zero.")
        self._client = client
        self._logger = logger
        self._replay_engine = replay_engine
        self._order = order
        self._poll_attempts = poll_attempts
        self._poll_interval_seconds = poll_interval_seconds
        self._risk_manager = risk_manager
        self._sleep_fn = sleep_fn

    @classmethod
    def from_settings(cls, settings: KalshiSettings) -> "LiveExecutionSmokeTester":
        if not settings.live_validation_enabled:
            raise LiveExecutionSmokeError("LIVE_VALIDATION_ENABLED must be true.")
        if settings.env != "prod" or settings.live_validation_env != "prod":
            raise LiveExecutionSmokeError(
                "KALSHI_ENV and LIVE_VALIDATION_ENV must both be 'prod'."
            )
        if settings.live_validation_ticker is None:
            raise LiveExecutionSmokeError("LIVE_VALIDATION_TICKER is required.")
        if settings.live_validation_action is None:
            raise LiveExecutionSmokeError("LIVE_VALIDATION_ACTION is required.")
        if settings.live_validation_side is None:
            raise LiveExecutionSmokeError("LIVE_VALIDATION_SIDE is required.")
        if settings.live_validation_price_dollars is None:
            raise LiveExecutionSmokeError("LIVE_VALIDATION_PRICE_DOLLARS is required.")

        client_order_id = _build_live_client_order_id(
            settings.live_validation_client_order_id_prefix
        )
        order = LiveValidationOrder(
            ticker=settings.live_validation_ticker,
            action=settings.live_validation_action,
            side=settings.live_validation_side,
            count=settings.live_validation_count,
            price_dollars=settings.live_validation_price_dollars,
            time_in_force=settings.live_validation_time_in_force,
            client_order_id=client_order_id,
        )
        return cls(
            client=KalshiClient.from_settings(settings),
            logger=StructuredLogger(
                log_directory=settings.log_directory,
                enabled=settings.log_jsonl_enabled,
            ),
            replay_engine=ReplayEngine(
                replay_directory=settings.replay_directory,
                enabled=settings.replay_write_enabled,
            ),
            order=order,
            poll_attempts=settings.live_validation_poll_attempts,
            poll_interval_seconds=settings.live_validation_poll_interval_seconds,
            risk_manager=RiskManager.from_settings(settings),
        )

    def run(self) -> LiveValidationSnapshot:
        self._log_and_record(
            event_type="validation_start",
            record_type="validation_start",
            identifier=self._order.ticker,
            payload=_requested_order_payload(self._order),
        )

        final_order: KalshiOrderSummary | None = None
        order_placed = False
        poll_attempts_used = 0
        error_message: str | None = None
        classification = "unknown_final_state"
        decision_reason: str | None = None

        safety_decision = self._risk_manager.evaluate_live_order(self._order)
        if not safety_decision.allow:
            classification = "blocked_by_safeguard"
            decision_reason = safety_decision.reason
            self._log_and_record(
                event_type="live_submission_blocked",
                record_type="live_submission_blocked",
                identifier=self._order.client_order_id,
                payload={"reason": decision_reason},
            )
            result = LiveValidationResult(
                classification=classification,
                decision_reason=decision_reason,
                order_placed=False,
                order_id=None,
                final_order=None,
                poll_attempts_used=0,
                balance_fetched=False,
                balance_payload=None,
                error_message=None,
            )
            self._log_and_record(
                event_type="validation_completed",
                record_type="validation_completed",
                identifier=self._order.client_order_id,
                payload={
                    "classification": result.classification,
                    "decision_reason": result.decision_reason,
                    "order_placed": result.order_placed,
                    "poll_attempts_used": result.poll_attempts_used,
                    "balance_fetched": result.balance_fetched,
                    "error_message": result.error_message,
                },
            )
            return LiveValidationSnapshot(
                requested_order=self._order,
                result=result,
            )

        try:
            created_order = self._client.create_order(
                KalshiOrderRequest(
                    ticker=self._order.ticker,
                    action=self._order.action,
                    side=self._order.side,
                    count=self._order.count,
                    price_dollars=self._order.price_dollars,
                    time_in_force=self._order.time_in_force,
                    client_order_id=self._order.client_order_id,
                )
            )
            order_placed = True
            final_order = created_order
            self._log_and_record(
                event_type="order_submitted",
                record_type="order_submitted",
                identifier=created_order.order_id,
                payload=_order_summary_payload(created_order),
            )
            final_order, poll_attempts_used = self._poll_order(created_order.order_id)
            classification = _classify_order_result(final_order)
        except KalshiClientError as exc:
            classification = "rejected"
            error_message = str(exc)
            decision_reason = "order_submit_failed"
            self._log_and_record(
                event_type="order_submit_failed",
                record_type="order_submit_failed",
                identifier=self._order.client_order_id,
                payload={"message": error_message},
            )

        balance_payload, balance_error = self._fetch_balance()
        if balance_error is not None and error_message is None:
            error_message = balance_error

        result = LiveValidationResult(
            classification=classification,
            decision_reason=decision_reason,
            order_placed=order_placed,
            order_id=final_order.order_id if final_order is not None else None,
            final_order=final_order,
            poll_attempts_used=poll_attempts_used,
            balance_fetched=balance_payload is not None,
            balance_payload=balance_payload,
            error_message=error_message,
        )
        self._log_and_record(
            event_type="validation_completed",
            record_type="validation_completed",
            identifier=result.order_id or self._order.client_order_id,
            payload={
                "classification": result.classification,
                "decision_reason": result.decision_reason,
                "order_placed": result.order_placed,
                "poll_attempts_used": result.poll_attempts_used,
                "balance_fetched": result.balance_fetched,
                "error_message": result.error_message,
            },
        )
        return LiveValidationSnapshot(
            requested_order=self._order,
            result=result,
        )

    def _poll_order(self, order_id: str) -> tuple[KalshiOrderSummary, int]:
        last_order = self._client.get_order(order_id)
        attempts_used = 1
        self._log_and_record(
            event_type="order_polled",
            record_type="order_polled",
            identifier=order_id,
            payload={"attempt": attempts_used, "status": last_order.status},
        )
        if _is_terminal_order(last_order):
            return last_order, attempts_used

        while attempts_used < self._poll_attempts:
            self._sleep_fn(self._poll_interval_seconds)
            attempts_used += 1
            try:
                last_order = self._client.get_order(order_id)
            except KalshiClientError as exc:
                self._log_and_record(
                    event_type="order_poll_failed",
                    record_type="order_poll_failed",
                    identifier=order_id,
                    payload={"attempt": attempts_used, "message": str(exc)},
                )
                break
            self._log_and_record(
                event_type="order_polled",
                record_type="order_polled",
                identifier=order_id,
                payload={"attempt": attempts_used, "status": last_order.status},
            )
            if _is_terminal_order(last_order):
                break
        return last_order, attempts_used

    def _fetch_balance(self) -> tuple[dict[str, object] | None, str | None]:
        try:
            payload = self._client.get_balance()
        except KalshiClientError as exc:
            self._log_and_record(
                event_type="balance_fetch_failed",
                record_type="balance_fetch_failed",
                identifier=self._order.client_order_id,
                payload={"message": str(exc)},
            )
            return None, str(exc)
        self._log_and_record(
            event_type="balance_fetched",
            record_type="balance_fetched",
            identifier=self._order.client_order_id,
            payload={"keys": tuple(sorted(payload.keys()))},
            replay_payload=payload,
        )
        return payload, None

    def _log_and_record(
        self,
        *,
        event_type: str,
        record_type: str,
        identifier: str | None,
        payload: dict[str, object],
        replay_payload: dict[str, object] | None = None,
    ) -> None:
        self._logger.log_event(
            category="live_validation",
            event_type=event_type,
            source="kalshi_live_validation",
            identifier=identifier,
            payload=payload,
        )
        self._replay_engine.record_message(
            source="kalshi_live_validation",
            message_type=record_type,
            identifier=identifier,
            payload=replay_payload if replay_payload is not None else payload,
        )


def _build_live_client_order_id(prefix: str) -> str:
    normalized_prefix = prefix.strip()
    if not normalized_prefix:
        raise LiveExecutionSmokeError("LIVE_VALIDATION_CLIENT_ORDER_ID_PREFIX is required.")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{normalized_prefix}-{timestamp}-{uuid.uuid4().hex[:8]}"


def _requested_order_payload(order: LiveValidationOrder) -> dict[str, object]:
    return {
        "ticker": order.ticker,
        "action": order.action,
        "side": order.side,
        "count": order.count,
        "price_dollars": order.price_dollars,
        "time_in_force": order.time_in_force,
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


def _classify_order_result(order: KalshiOrderSummary) -> str:
    if order.status == "rejected":
        return "rejected"
    fill_count = order.fill_count_fp or Decimal("0")
    initial_count = order.initial_count_fp or Decimal("0")
    if fill_count > 0 and initial_count > 0 and fill_count >= initial_count:
        return "filled"
    if fill_count > 0:
        return "partially_filled"
    if order.status in {"canceled", "cancelled", "expired"}:
        return "canceled_or_expired"
    return "unknown_final_state"


def _is_terminal_order(order: KalshiOrderSummary) -> bool:
    return _classify_order_result(order) != "unknown_final_state"
