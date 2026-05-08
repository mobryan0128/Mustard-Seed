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
MAX_CONTEXTUAL_ITM_EXECUTION_PRICE_DOLLARS = Decimal("0.90")
EXTREME_EXECUTION_PRICE_DOLLARS = Decimal("0.95")
MAX_CONTEXTUAL_PREMIUM_OVER_MIDPOINT_DOLLARS = Decimal("0.05")
MAX_CONTEXTUAL_SPREAD_DOLLARS = Decimal("0.15")
MIN_CONTEXTUAL_LIQUIDITY_COUNT = Decimal("1")
FLIP_PERSISTENCE_WINDOW_SECONDS = 180
FLIP_PERSISTENCE_MIN_RECENT_RETURN_BPS = Decimal("15.000")
FLIP_PERSISTENCE_IMPULSE_CONFIRMATION_RETURN_BPS = Decimal("3.000")
ENTRY_SEGMENT_10_TO_5 = "10_to_5"
ENTRY_SEGMENT_5_TO_3 = "5_to_3"
ENTRY_SEGMENT_3_TO_1 = "3_to_1"
ENTRY_SEGMENT_FINAL_1 = "final_1"


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
    spread_dollars: Decimal | None
    execution_premium_over_midpoint_dollars: Decimal


@dataclass(frozen=True)
class ExecutionSafetyStatus:
    allowed: bool
    reason: str | None
    contextual_high_price_status: str
    candidate_count: int


@dataclass(frozen=True)
class EntryEndWindowStatus:
    allowed: bool | None
    reason: str | None
    remaining_seconds: int | None


@dataclass(frozen=True)
class FlipPersistenceStatus:
    allowed: bool
    status: str
    previous_direction: str | None
    previous_entry_age_seconds: Decimal | None


@dataclass(frozen=True)
class ItmPersistenceStatus:
    status: str
    consecutive_itm_observations: int
    previous_side_currently_itm: bool | None
    itm_hold_seconds: Decimal


@dataclass(frozen=True)
class ReversalCrossHoldStatus:
    allowed: bool
    status: str
    hold_seconds: Decimal
    required_seconds: int
    block_reason: str | None


@dataclass(frozen=True)
class RetryPersistenceStatus:
    allowed: bool
    status: str
    previous_distance_to_target_bps: Decimal | None
    previous_required_bps_per_minute: Decimal | None


@dataclass(frozen=True)
class MidPriceConfirmationStatus:
    allowed: bool
    status: str
    price_band_min: Decimal
    price_band_max: Decimal
    block_reason: str | None


@dataclass(frozen=True)
class EntrySegmentStatus:
    allowed: bool
    status: str
    segment: str | None
    current_count: int
    max_count: int | None
    remaining_seconds: int | None


@dataclass(frozen=True)
class ProductSessionPacingStatus:
    allowed: bool
    status: str
    product_open_position_count: int
    product_session_entry_count: int
    max_open_positions_per_product: int
    max_entries_per_product_per_session: int


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


@dataclass(frozen=True)
class LiveEntryMemory:
    product_id: str
    direction: str
    market_ticker: str
    distance_to_target_bps: Decimal | None
    required_bps_per_minute: Decimal | None
    side_currently_itm: bool | None
    side_needs_cross: bool | None
    recorded_at_monotonic: float
    recorded_at: str


@dataclass(frozen=True)
class ItmPersistenceMemory:
    side_currently_itm: bool | None
    consecutive_itm_observations: int
    first_itm_recorded_at_monotonic: float | None


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
        time_fn=time.monotonic,
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
        self._time_fn = time_fn
        self._live_position_ledger: dict[str, LivePositionRecord] = {}
        self._client_order_id_by_order_id: dict[str, str] = {}
        self._trailing_stop_states: dict[str, LiveTrailingStopState] = {}
        self._reconciled_live_exposure_by_key: dict[str, Decimal] = {}
        self._live_positions_reconciled = False
        self._last_live_entry_by_product: dict[str, LiveEntryMemory] = {}
        self._itm_persistence_by_market_side: dict[
            tuple[str, str],
            ItmPersistenceMemory,
        ] = {}
        self._entry_segment_counts: dict[tuple[str, str], int] = {}
        self._entry_count_by_product_session: dict[tuple[str, str], int] = {}

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
            itm_persistence = self._itm_persistence_status(contract)
            reversal_cross_hold = _reversal_cross_hold_status(
                contract=contract,
                itm_persistence=itm_persistence,
                settings=self._settings,
            )
            if not reversal_cross_hold.allowed:
                self._log_contract_intent_skipped(
                    reason="reversal_cross_hold_blocked",
                    contract=contract,
                    cycle_number=cycle_number,
                    scan_source=scan_source,
                    details={
                        **_itm_persistence_payload(itm_persistence),
                        **_reversal_cross_hold_payload(reversal_cross_hold),
                    },
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
            entry_segment = self._entry_segment_status(contract, end_window=end_window)
            if not entry_segment.allowed:
                self._log_contract_intent_skipped(
                    reason="entry_segment_budget_exhausted",
                    contract=contract,
                    cycle_number=cycle_number,
                    scan_source=scan_source,
                    details={
                        **_end_window_payload(end_window),
                        **_entry_segment_payload(entry_segment),
                    },
                )
                continue
            flip_persistence = self._flip_persistence_status(contract)
            if not flip_persistence.allowed:
                self._log_contract_intent_skipped(
                    reason="flip_persistence_blocked",
                    contract=contract,
                    cycle_number=cycle_number,
                    scan_source=scan_source,
                    details={
                        **_reversal_cross_hold_payload(reversal_cross_hold),
                        **_entry_segment_payload(entry_segment),
                        **_flip_persistence_payload(flip_persistence),
                    },
                )
                continue
            retry_persistence = self._retry_persistence_status(
                contract,
                itm_persistence=itm_persistence,
            )
            if not retry_persistence.allowed:
                self._log_contract_intent_skipped(
                    reason="retry_persistence_blocked",
                    contract=contract,
                    cycle_number=cycle_number,
                    scan_source=scan_source,
                    details={
                        **_itm_persistence_payload(itm_persistence),
                        **_reversal_cross_hold_payload(reversal_cross_hold),
                        **_entry_segment_payload(entry_segment),
                        **_retry_persistence_payload(retry_persistence),
                    },
                )
                continue
            product_session_pacing = self._product_session_pacing_status(contract)
            if not product_session_pacing.allowed:
                self._log_contract_intent_skipped(
                    reason="product_session_pacing_blocked",
                    contract=contract,
                    cycle_number=cycle_number,
                    scan_source=scan_source,
                    details={
                        **_entry_segment_payload(entry_segment),
                        **_product_session_pacing_payload(product_session_pacing),
                    },
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
                        **_reversal_cross_hold_payload(reversal_cross_hold),
                        **_entry_segment_payload(entry_segment),
                        **_product_session_pacing_payload(product_session_pacing),
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
            mid_price_confirmation = _mid_price_confirmation_status(
                contract=contract,
                pricing=pricing,
                itm_persistence=itm_persistence,
                reversal_cross_hold=reversal_cross_hold,
                settings=self._settings,
            )
            if not mid_price_confirmation.allowed:
                self._log_contract_intent_skipped(
                    reason="mid_price_confirmation_required",
                    contract=contract,
                    cycle_number=cycle_number,
                    scan_source=scan_source,
                    details={
                        "stake_dollars": stake_dollars,
                        **_itm_persistence_payload(itm_persistence),
                        **_reversal_cross_hold_payload(reversal_cross_hold),
                        **_entry_segment_payload(entry_segment),
                        **_product_session_pacing_payload(product_session_pacing),
                        **_execution_pricing_payload(pricing),
                        **_mid_price_confirmation_payload(mid_price_confirmation),
                    },
                )
                continue
            safety = _execution_safety_status(
                contract=contract,
                pricing=pricing,
                candidate_count=_candidate_count(
                    stake_dollars=stake_dollars,
                    price_dollars=pricing.intent_price_dollars,
                ),
                itm_persistence=itm_persistence,
            )
            if not safety.allowed:
                self._log_contract_intent_skipped(
                    reason=safety.reason or "execution_safety_blocked",
                    contract=contract,
                    cycle_number=cycle_number,
                    scan_source=scan_source,
                    details={
                        "ticker": contract.market_ticker,
                        "stake_dollars": stake_dollars,
                        "count": safety.candidate_count,
                        **_itm_persistence_payload(itm_persistence),
                        **_reversal_cross_hold_payload(reversal_cross_hold),
                        **_entry_segment_payload(entry_segment),
                        **_product_session_pacing_payload(product_session_pacing),
                        **_mid_price_confirmation_payload(mid_price_confirmation),
                        **_retry_persistence_payload(retry_persistence),
                        **_execution_pricing_payload(pricing),
                        **_execution_safety_payload(safety),
                    },
                )
                continue
            if (
                contract.midpoint > MAX_ENTRY_PRICE
                and safety.contextual_high_price_status
                != "allowed_contextual_itm_high_price"
            ):
                self._log_contract_intent_skipped(
                    reason="entry_price_too_high",
                    contract=contract,
                    cycle_number=cycle_number,
                    scan_source=scan_source,
                    details={
                        **_itm_persistence_payload(itm_persistence),
                        **_reversal_cross_hold_payload(reversal_cross_hold),
                        **_entry_segment_payload(entry_segment),
                        **_product_session_pacing_payload(product_session_pacing),
                        **_mid_price_confirmation_payload(mid_price_confirmation),
                        **_retry_persistence_payload(retry_persistence),
                        **_execution_pricing_payload(pricing),
                        **_execution_safety_payload(safety),
                    },
                )
                continue
            if safety.candidate_count < 1:
                self._log_contract_intent_skipped(
                    reason="count_below_one",
                    contract=contract,
                    cycle_number=cycle_number,
                    scan_source=scan_source,
                    details={
                        "stake_dollars": stake_dollars,
                        **_itm_persistence_payload(itm_persistence),
                        **_reversal_cross_hold_payload(reversal_cross_hold),
                        **_entry_segment_payload(entry_segment),
                        **_product_session_pacing_payload(product_session_pacing),
                        **_mid_price_confirmation_payload(mid_price_confirmation),
                        **_retry_persistence_payload(retry_persistence),
                        **_execution_pricing_payload(pricing),
                        **_execution_safety_payload(safety),
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
                    **_itm_persistence_payload(itm_persistence),
                    **_reversal_cross_hold_payload(reversal_cross_hold),
                    **_entry_segment_payload(entry_segment),
                    **_flip_persistence_payload(flip_persistence),
                    **_retry_persistence_payload(retry_persistence),
                    **_product_session_pacing_payload(product_session_pacing),
                    **_execution_pricing_payload(pricing),
                    **_mid_price_confirmation_payload(mid_price_confirmation),
                    **_execution_safety_payload(safety),
                    "intent_count": intent.count,
                },
            )
            self._record_live_entry_memory(contract)
            self._record_entry_pacing(contract, entry_segment=entry_segment)
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
        if self._live_open_position_count() >= _live_max_open_positions_from_settings(
            self._settings
        ):
            return True
        if (
            self._live_current_exposure_dollars()
            >= _live_max_exposure_dollars_from_settings(self._settings)
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

    def _flip_persistence_status(self, contract: ScannedContract) -> FlipPersistenceStatus:
        previous = self._last_live_entry_by_product.get(contract.product_id)
        if previous is None:
            return FlipPersistenceStatus(
                allowed=True,
                status="no_recent_entry",
                previous_direction=None,
                previous_entry_age_seconds=None,
            )
        age_seconds = Decimal(str(self._time_fn() - previous.recorded_at_monotonic)).quantize(
            Decimal("0.001")
        )
        if int(age_seconds) >= FLIP_PERSISTENCE_WINDOW_SECONDS:
            return FlipPersistenceStatus(
                allowed=True,
                status="previous_entry_expired",
                previous_direction=previous.direction,
                previous_entry_age_seconds=age_seconds,
            )
        if previous.direction == contract.direction:
            return FlipPersistenceStatus(
                allowed=True,
                status="same_direction",
                previous_direction=previous.direction,
                previous_entry_age_seconds=age_seconds,
            )
        if _contract_side_currently_itm(contract) and _contract_momentum_persists(contract):
            return FlipPersistenceStatus(
                allowed=True,
                status="opposite_direction_allowed_crossed_and_persistent",
                previous_direction=previous.direction,
                previous_entry_age_seconds=age_seconds,
            )
        if not _contract_side_currently_itm(contract):
            status = "blocked_recent_flip_not_itm"
        else:
            status = "blocked_recent_flip_momentum_not_persistent"
        return FlipPersistenceStatus(
            allowed=False,
            status=status,
            previous_direction=previous.direction,
            previous_entry_age_seconds=age_seconds,
        )

    def _itm_persistence_status(self, contract: ScannedContract) -> ItmPersistenceStatus:
        intent_side = _intent_side_from_direction(contract.direction)
        key = (contract.market_ticker, intent_side)
        previous = self._itm_persistence_by_market_side.get(key)
        now = self._time_fn()
        side_currently_itm = getattr(contract, "side_currently_itm", None)
        side_needs_cross = getattr(contract, "side_needs_cross", None)
        first_itm_recorded_at: float | None = None
        if side_currently_itm is None:
            status = "missing_feasibility"
            observations = 0
        elif bool(side_needs_cross):
            status = "needs_cross"
            observations = 0
        elif side_currently_itm:
            previous_observations = (
                previous.consecutive_itm_observations
                if previous is not None and previous.side_currently_itm
                else 0
            )
            observations = previous_observations + 1
            first_itm_recorded_at = (
                previous.first_itm_recorded_at_monotonic
                if previous is not None
                and previous.side_currently_itm
                and previous.first_itm_recorded_at_monotonic is not None
                else now
            )
            status = "sustained_itm" if observations >= 2 else "newly_itm"
        else:
            status = "not_itm"
            observations = 0

        self._itm_persistence_by_market_side[key] = ItmPersistenceMemory(
            side_currently_itm=side_currently_itm,
            consecutive_itm_observations=observations,
            first_itm_recorded_at_monotonic=first_itm_recorded_at,
        )
        hold_seconds = (
            Decimal(str(now - first_itm_recorded_at)).quantize(Decimal("0.001"))
            if first_itm_recorded_at is not None
            else Decimal("0.000")
        )
        return ItmPersistenceStatus(
            status=status,
            consecutive_itm_observations=observations,
            previous_side_currently_itm=(
                previous.side_currently_itm if previous is not None else None
            ),
            itm_hold_seconds=hold_seconds,
        )

    def _retry_persistence_status(
        self,
        contract: ScannedContract,
        *,
        itm_persistence: ItmPersistenceStatus,
    ) -> RetryPersistenceStatus:
        previous = self._last_live_entry_by_product.get(contract.product_id)
        if previous is None:
            return RetryPersistenceStatus(
                allowed=True,
                status="no_recent_entry",
                previous_distance_to_target_bps=None,
                previous_required_bps_per_minute=None,
            )
        age_seconds = int(self._time_fn() - previous.recorded_at_monotonic)
        if age_seconds >= FLIP_PERSISTENCE_WINDOW_SECONDS:
            return RetryPersistenceStatus(
                allowed=True,
                status="previous_entry_expired",
                previous_distance_to_target_bps=previous.distance_to_target_bps,
                previous_required_bps_per_minute=previous.required_bps_per_minute,
            )
        if previous.direction != contract.direction:
            return RetryPersistenceStatus(
                allowed=True,
                status="opposite_direction_not_same_side_retry",
                previous_distance_to_target_bps=previous.distance_to_target_bps,
                previous_required_bps_per_minute=previous.required_bps_per_minute,
            )
        if itm_persistence.status == "sustained_itm":
            return RetryPersistenceStatus(
                allowed=True,
                status="same_direction_allowed_sustained_itm",
                previous_distance_to_target_bps=previous.distance_to_target_bps,
                previous_required_bps_per_minute=previous.required_bps_per_minute,
            )
        if _contract_feasibility_improved(previous, contract):
            return RetryPersistenceStatus(
                allowed=True,
                status="same_direction_allowed_feasibility_improved",
                previous_distance_to_target_bps=previous.distance_to_target_bps,
                previous_required_bps_per_minute=previous.required_bps_per_minute,
            )
        return RetryPersistenceStatus(
            allowed=False,
            status="blocked_same_direction_feasibility_not_improved",
            previous_distance_to_target_bps=previous.distance_to_target_bps,
            previous_required_bps_per_minute=previous.required_bps_per_minute,
        )

    def _record_live_entry_memory(self, contract: ScannedContract) -> None:
        self._last_live_entry_by_product[contract.product_id] = LiveEntryMemory(
            product_id=contract.product_id,
            direction=contract.direction,
            market_ticker=contract.market_ticker,
            distance_to_target_bps=getattr(contract, "distance_to_target_bps", None),
            required_bps_per_minute=getattr(contract, "required_bps_per_minute", None),
            side_currently_itm=getattr(contract, "side_currently_itm", None),
            side_needs_cross=getattr(contract, "side_needs_cross", None),
            recorded_at_monotonic=self._time_fn(),
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )

    def _entry_segment_status(
        self,
        contract: ScannedContract,
        *,
        end_window: EntryEndWindowStatus,
    ) -> EntrySegmentStatus:
        segment = _entry_segment(end_window.remaining_seconds)
        if not getattr(self._settings, "live_entry_segment_pacing_enabled", False):
            return EntrySegmentStatus(
                allowed=True,
                status="disabled",
                segment=segment,
                current_count=0,
                max_count=None,
                remaining_seconds=end_window.remaining_seconds,
            )
        max_count = _entry_segment_max_count(segment, self._settings)
        if segment is None or max_count is None:
            return EntrySegmentStatus(
                allowed=True,
                status="segment_not_applicable",
                segment=segment,
                current_count=0,
                max_count=max_count,
                remaining_seconds=end_window.remaining_seconds,
            )
        key = (contract.market_ticker, segment)
        current_count = self._entry_segment_counts.get(key, 0)
        if current_count >= max_count:
            return EntrySegmentStatus(
                allowed=False,
                status="budget_exhausted",
                segment=segment,
                current_count=current_count,
                max_count=max_count,
                remaining_seconds=end_window.remaining_seconds,
            )
        return EntrySegmentStatus(
            allowed=True,
            status="budget_available",
            segment=segment,
            current_count=current_count,
            max_count=max_count,
            remaining_seconds=end_window.remaining_seconds,
        )

    def _product_session_pacing_status(
        self,
        contract: ScannedContract,
    ) -> ProductSessionPacingStatus:
        max_open = getattr(self._settings, "live_max_open_positions_per_product", 2)
        max_entries = getattr(
            self._settings,
            "live_max_entries_per_product_per_session",
            2,
        )
        open_count = self._live_open_position_count_for_product(contract.product_id)
        session_key = (contract.product_id, contract.market_ticker)
        session_count = self._entry_count_by_product_session.get(session_key, 0)
        if open_count >= max_open:
            status = "max_open_positions_per_product_reached"
            allowed = False
        elif session_count >= max_entries:
            status = "max_entries_per_product_session_reached"
            allowed = False
        else:
            status = "available"
            allowed = True
        return ProductSessionPacingStatus(
            allowed=allowed,
            status=status,
            product_open_position_count=open_count,
            product_session_entry_count=session_count,
            max_open_positions_per_product=max_open,
            max_entries_per_product_per_session=max_entries,
        )

    def _live_open_position_count_for_product(self, product_id: str) -> int:
        return sum(
            1
            for record in self._live_position_ledger.values()
            if record.product_id == product_id and _record_has_live_exposure(record)
        )

    def _record_entry_pacing(
        self,
        contract: ScannedContract,
        *,
        entry_segment: EntrySegmentStatus,
    ) -> None:
        if entry_segment.segment is not None:
            segment_key = (contract.market_ticker, entry_segment.segment)
            self._entry_segment_counts[segment_key] = (
                self._entry_segment_counts.get(segment_key, 0) + 1
            )
        session_key = (contract.product_id, contract.market_ticker)
        self._entry_count_by_product_session[session_key] = (
            self._entry_count_by_product_session.get(session_key, 0) + 1
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
        return RiskManager.from_live_settings(settings)
    return RiskManager(
        live_validation_enabled=False,
        live_trading_enabled=False,
        live_kill_switch_active=True,
        env="demo",
        live_validation_env="demo",
    )


def _live_max_exposure_dollars_from_settings(settings: KalshiSettings) -> Decimal:
    live_value = getattr(settings, "live_max_exposure_dollars", None)
    if live_value is not None:
        return Decimal(str(live_value))
    return Decimal(str(getattr(settings, "risk_max_total_exposure_dollars")))


def _live_max_open_positions_from_settings(settings: KalshiSettings) -> int:
    live_value = getattr(settings, "live_max_open_positions", None)
    if live_value is not None:
        return int(live_value)
    return int(getattr(settings, "risk_max_open_positions"))


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

    spread_dollars = (
        yes_ask - yes_bid
        if yes_bid is not None and yes_ask is not None
        else None
    )
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
        spread_dollars=spread_dollars,
        execution_premium_over_midpoint_dollars=(
            intent_price_dollars - contract.midpoint
        ),
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
    min_remaining_seconds = getattr(settings, "live_entry_min_remaining_seconds", 0)
    if remaining_seconds < min_remaining_seconds:
        return EntryEndWindowStatus(
            allowed=False,
            reason="entry_min_remaining_seconds_not_met",
            remaining_seconds=remaining_seconds,
        )
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


def _entry_segment(remaining_seconds: int | None) -> str | None:
    if remaining_seconds is None or remaining_seconds < 0:
        return None
    if remaining_seconds <= 60:
        return ENTRY_SEGMENT_FINAL_1
    if remaining_seconds <= 180:
        return ENTRY_SEGMENT_3_TO_1
    if remaining_seconds <= 300:
        return ENTRY_SEGMENT_5_TO_3
    if remaining_seconds <= 600:
        return ENTRY_SEGMENT_10_TO_5
    return None


def _entry_segment_max_count(
    segment: str | None,
    settings: KalshiSettings,
) -> int | None:
    if segment == ENTRY_SEGMENT_10_TO_5:
        return getattr(settings, "live_entry_segment_max_10_to_5", 1)
    if segment == ENTRY_SEGMENT_5_TO_3:
        return getattr(settings, "live_entry_segment_max_5_to_3", 1)
    if segment == ENTRY_SEGMENT_3_TO_1:
        return getattr(settings, "live_entry_segment_max_3_to_1", 1)
    if segment == ENTRY_SEGMENT_FINAL_1:
        return getattr(settings, "live_entry_segment_max_final_1", 1)
    return None


def _reversal_cross_hold_status(
    *,
    contract: ScannedContract,
    itm_persistence: ItmPersistenceStatus,
    settings: KalshiSettings,
) -> ReversalCrossHoldStatus:
    required_seconds = getattr(settings, "live_reversal_cross_hold_seconds", 60)
    if not getattr(settings, "live_reversal_cross_hold_enabled", True):
        return ReversalCrossHoldStatus(
            allowed=True,
            status="disabled",
            hold_seconds=itm_persistence.itm_hold_seconds,
            required_seconds=required_seconds,
            block_reason=None,
        )
    if getattr(contract, "structure", None) != "reversal":
        return ReversalCrossHoldStatus(
            allowed=True,
            status="not_reversal",
            hold_seconds=itm_persistence.itm_hold_seconds,
            required_seconds=required_seconds,
            block_reason=None,
        )
    if not bool(getattr(contract, "side_currently_itm", False)):
        return ReversalCrossHoldStatus(
            allowed=False,
            status="not_itm",
            hold_seconds=itm_persistence.itm_hold_seconds,
            required_seconds=required_seconds,
            block_reason="reversal_cross_hold_requires_itm",
        )
    if bool(getattr(contract, "side_needs_cross", False)):
        return ReversalCrossHoldStatus(
            allowed=False,
            status="needs_cross",
            hold_seconds=itm_persistence.itm_hold_seconds,
            required_seconds=required_seconds,
            block_reason="reversal_cross_hold_requires_no_cross_needed",
        )
    if itm_persistence.itm_hold_seconds < Decimal(required_seconds):
        return ReversalCrossHoldStatus(
            allowed=False,
            status="holding",
            hold_seconds=itm_persistence.itm_hold_seconds,
            required_seconds=required_seconds,
            block_reason="reversal_cross_hold_waiting",
        )
    return ReversalCrossHoldStatus(
        allowed=True,
        status="confirmed",
        hold_seconds=itm_persistence.itm_hold_seconds,
        required_seconds=required_seconds,
        block_reason=None,
    )


def _mid_price_confirmation_status(
    *,
    contract: ScannedContract,
    pricing: ExecutionPricing,
    itm_persistence: ItmPersistenceStatus,
    reversal_cross_hold: ReversalCrossHoldStatus,
    settings: KalshiSettings,
) -> MidPriceConfirmationStatus:
    band_min = getattr(settings, "live_mid_price_min", Decimal("0.50"))
    band_max = getattr(settings, "live_mid_price_max", Decimal("0.70"))
    if not getattr(settings, "live_mid_price_tightening_enabled", True):
        return MidPriceConfirmationStatus(
            allowed=True,
            status="disabled",
            price_band_min=band_min,
            price_band_max=band_max,
            block_reason=None,
        )
    if not (band_min <= pricing.intent_price_dollars <= band_max):
        return MidPriceConfirmationStatus(
            allowed=True,
            status="outside_mid_price_band",
            price_band_min=band_min,
            price_band_max=band_max,
            block_reason=None,
        )
    if getattr(contract, "trend_confirmation_status", None) == "confirmed":
        return MidPriceConfirmationStatus(
            allowed=True,
            status="allowed_confirmed_trend",
            price_band_min=band_min,
            price_band_max=band_max,
            block_reason=None,
        )
    if itm_persistence.status == "sustained_itm":
        return MidPriceConfirmationStatus(
            allowed=True,
            status="allowed_sustained_itm",
            price_band_min=band_min,
            price_band_max=band_max,
            block_reason=None,
        )
    if reversal_cross_hold.status == "confirmed":
        return MidPriceConfirmationStatus(
            allowed=True,
            status="allowed_reversal_cross_hold",
            price_band_min=band_min,
            price_band_max=band_max,
            block_reason=None,
        )
    return MidPriceConfirmationStatus(
        allowed=False,
        status="confirmation_required",
        price_band_min=band_min,
        price_band_max=band_max,
        block_reason="mid_price_requires_confirmed_trend_sustained_itm_or_cross_hold",
    )


def _execution_safety_status(
    *,
    contract: ScannedContract,
    pricing: ExecutionPricing,
    candidate_count: int,
    itm_persistence: ItmPersistenceStatus,
) -> ExecutionSafetyStatus:
    if pricing.intent_price_dollars < MIN_LIVE_EXECUTION_PRICE_DOLLARS:
        return ExecutionSafetyStatus(
            allowed=False,
            reason="executable_price_below_minimum",
            contextual_high_price_status="not_high_price",
            candidate_count=candidate_count,
        )
    if pricing.intent_price_dollars >= EXTREME_EXECUTION_PRICE_DOLLARS:
        return ExecutionSafetyStatus(
            allowed=False,
            reason="executable_price_extreme_asymmetry",
            contextual_high_price_status="extreme_price_blocked",
            candidate_count=candidate_count,
        )
    if pricing.intent_price_dollars > MAX_LIVE_EXECUTION_PRICE_DOLLARS:
        if pricing.pricing_source != "executable_side_ask":
            return ExecutionSafetyStatus(
                allowed=False,
                reason="executable_price_above_maximum",
                contextual_high_price_status=(
                    "contextual_high_price_requires_executable_ask"
                ),
                candidate_count=candidate_count,
            )
        contextual_reason = _contextual_high_price_rejection_reason(
            contract=contract,
            pricing=pricing,
            candidate_count=candidate_count,
            itm_persistence=itm_persistence,
        )
        if contextual_reason is not None:
            return ExecutionSafetyStatus(
                allowed=False,
                reason=contextual_reason,
                contextual_high_price_status=contextual_reason,
                candidate_count=candidate_count,
            )
        return ExecutionSafetyStatus(
            allowed=True,
            reason=None,
            contextual_high_price_status="allowed_contextual_itm_high_price",
            candidate_count=candidate_count,
        )
    if (
        pricing.pricing_source == "executable_side_ask"
        and pricing.executable_side_ask is not None
        and pricing.executable_side_ask
        > pricing.scanner_midpoint + MAX_EXECUTION_PREMIUM_OVER_SCANNER_DOLLARS
    ):
        return ExecutionSafetyStatus(
            allowed=False,
            reason="executable_price_above_scanner_premium",
            contextual_high_price_status="not_high_price",
            candidate_count=candidate_count,
        )
    if (
        pricing.orderbook_present
        and pricing.available_count_at_intent_price is not None
        and pricing.available_count_at_intent_price <= Decimal("0")
    ):
        return ExecutionSafetyStatus(
            allowed=False,
            reason="executable_price_no_visible_liquidity",
            contextual_high_price_status="not_high_price",
            candidate_count=candidate_count,
        )
    return ExecutionSafetyStatus(
        allowed=True,
        reason=None,
        contextual_high_price_status="not_high_price",
        candidate_count=candidate_count,
    )


def _contextual_high_price_rejection_reason(
    *,
    contract: ScannedContract,
    pricing: ExecutionPricing,
    candidate_count: int,
    itm_persistence: ItmPersistenceStatus,
) -> str | None:
    if pricing.intent_price_dollars > MAX_CONTEXTUAL_ITM_EXECUTION_PRICE_DOLLARS:
        return "contextual_high_price_above_ceiling"
    if bool(getattr(contract, "side_needs_cross", False)):
        return "contextual_high_price_needs_cross_blocked"
    if not bool(getattr(contract, "side_currently_itm", False)):
        return "contextual_high_price_requires_currently_itm"
    required_bps_per_minute = getattr(contract, "required_bps_per_minute", None)
    if (
        required_bps_per_minute is None
        or Decimal(str(required_bps_per_minute)) > Decimal("0")
    ):
        return "contextual_high_price_requires_zero_required_move"
    distance_to_target_bps = getattr(contract, "distance_to_target_bps", None)
    if distance_to_target_bps is None or Decimal(str(distance_to_target_bps)) > Decimal("0"):
        return "contextual_high_price_requires_itm_distance"
    if getattr(contract, "trend_confirmation_status", None) == "large_cross_required":
        return "contextual_high_price_large_cross_required"
    if itm_persistence.status != "sustained_itm":
        return "contextual_high_price_requires_sustained_itm"
    if pricing.spread_dollars is None:
        return "contextual_high_price_spread_unavailable"
    if pricing.spread_dollars > MAX_CONTEXTUAL_SPREAD_DOLLARS:
        return "contextual_high_price_spread_too_wide"
    if (
        pricing.execution_premium_over_midpoint_dollars
        > MAX_CONTEXTUAL_PREMIUM_OVER_MIDPOINT_DOLLARS
    ):
        return "contextual_high_price_premium_too_high"
    if pricing.available_count_at_intent_price is None:
        return "contextual_high_price_liquidity_unavailable"
    required_liquidity = max(Decimal(candidate_count), MIN_CONTEXTUAL_LIQUIDITY_COUNT)
    if pricing.available_count_at_intent_price < required_liquidity:
        return "contextual_high_price_insufficient_liquidity"
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
        "spread_dollars": pricing.spread_dollars,
        "execution_premium_over_midpoint_dollars": (
            pricing.execution_premium_over_midpoint_dollars
        ),
    }


def _execution_safety_payload(status: ExecutionSafetyStatus) -> dict[str, object]:
    return {
        "execution_safety_reason": status.reason,
        "contextual_high_price_status": status.contextual_high_price_status,
        "candidate_count": status.candidate_count,
        "min_live_execution_price_dollars": MIN_LIVE_EXECUTION_PRICE_DOLLARS,
        "max_live_execution_price_dollars": MAX_LIVE_EXECUTION_PRICE_DOLLARS,
        "max_contextual_itm_execution_price_dollars": (
            MAX_CONTEXTUAL_ITM_EXECUTION_PRICE_DOLLARS
        ),
        "extreme_execution_price_dollars": EXTREME_EXECUTION_PRICE_DOLLARS,
        "max_contextual_premium_over_midpoint_dollars": (
            MAX_CONTEXTUAL_PREMIUM_OVER_MIDPOINT_DOLLARS
        ),
        "max_contextual_spread_dollars": MAX_CONTEXTUAL_SPREAD_DOLLARS,
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
        "trend_confirmation_status": getattr(
            contract,
            "trend_confirmation_status",
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
        "scanner_score_downgrade_reasons": list(
            getattr(contract, "scanner_score_downgrade_reasons", ()) or ()
        ),
        "scanner_score_bonus_reasons": list(
            getattr(contract, "scanner_score_bonus_reasons", ()) or ()
        ),
        "trend_confirmed_bonus": (
            "confirmed_trend"
            in (getattr(contract, "scanner_score_bonus_reasons", ()) or ())
        ),
    }


def _flip_persistence_payload(status: FlipPersistenceStatus) -> dict[str, object]:
    return {
        "flip_persistence_status": status.status,
        "previous_entry_direction": status.previous_direction,
        "previous_entry_age_seconds": status.previous_entry_age_seconds,
    }


def _itm_persistence_payload(status: ItmPersistenceStatus) -> dict[str, object]:
    return {
        "itm_persistence_status": status.status,
        "consecutive_itm_observations": status.consecutive_itm_observations,
        "previous_side_currently_itm": status.previous_side_currently_itm,
        "sustained_itm_min_observations": 2,
        "itm_hold_seconds": status.itm_hold_seconds,
    }


def _reversal_cross_hold_payload(status: ReversalCrossHoldStatus) -> dict[str, object]:
    return {
        "reversal_cross_hold_status": status.status,
        "reversal_cross_hold_seconds": status.hold_seconds,
        "reversal_cross_hold_required": status.required_seconds,
        "reversal_cross_hold_block_reason": status.block_reason,
    }


def _retry_persistence_payload(status: RetryPersistenceStatus) -> dict[str, object]:
    return {
        "retry_persistence_status": status.status,
        "previous_distance_to_target_bps": status.previous_distance_to_target_bps,
        "previous_required_bps_per_minute": status.previous_required_bps_per_minute,
        "retry_persistence_window_seconds": FLIP_PERSISTENCE_WINDOW_SECONDS,
    }


def _mid_price_confirmation_payload(status: MidPriceConfirmationStatus) -> dict[str, object]:
    return {
        "mid_price_confirmation_status": status.status,
        "mid_price_confirmation_block_reason": status.block_reason,
        "mid_price_min": status.price_band_min,
        "mid_price_max": status.price_band_max,
    }


def _entry_segment_payload(status: EntrySegmentStatus) -> dict[str, object]:
    return {
        "entry_segment_status": status.status,
        "entry_segment": status.segment,
        "entry_segment_current_count": status.current_count,
        "entry_segment_max_count": status.max_count,
        "entry_segment_remaining_seconds": status.remaining_seconds,
    }


def _product_session_pacing_payload(status: ProductSessionPacingStatus) -> dict[str, object]:
    return {
        "product_session_pacing_status": status.status,
        "product_open_position_count": status.product_open_position_count,
        "product_session_entry_count": status.product_session_entry_count,
        "max_open_positions_per_product": status.max_open_positions_per_product,
        "max_entries_per_product_per_session": (
            status.max_entries_per_product_per_session
        ),
    }


def _contract_side_currently_itm(contract: ScannedContract) -> bool:
    return bool(getattr(contract, "side_currently_itm", False))


def _contract_feasibility_improved(
    previous: LiveEntryMemory,
    contract: ScannedContract,
) -> bool:
    if bool(getattr(contract, "side_currently_itm", False)) and not bool(
        previous.side_currently_itm
    ):
        return True
    previous_distance = previous.distance_to_target_bps
    current_distance = getattr(contract, "distance_to_target_bps", None)
    if previous_distance is not None and current_distance is not None:
        if Decimal(str(current_distance)) < Decimal(str(previous_distance)):
            return True
    previous_required = previous.required_bps_per_minute
    current_required = getattr(contract, "required_bps_per_minute", None)
    if previous_required is not None and current_required is not None:
        if Decimal(str(current_required)) < Decimal(str(previous_required)):
            return True
    if previous_distance is None and previous_required is None:
        return True
    return False


def _contract_momentum_persists(contract: ScannedContract) -> bool:
    direction_sign = _direction_sign(contract.direction)
    if direction_sign == 0:
        return False
    recent_return_bps = getattr(contract, "recent_return_bps", None)
    if recent_return_bps is None:
        return False
    recent_return = Decimal(str(recent_return_bps))
    if _sign(recent_return) != direction_sign:
        return False
    if abs(recent_return) < FLIP_PERSISTENCE_MIN_RECENT_RETURN_BPS:
        return False
    impulse_return_bps = getattr(contract, "impulse_return_bps", None)
    if impulse_return_bps is None:
        return True
    impulse_return = Decimal(str(impulse_return_bps))
    if abs(impulse_return) < FLIP_PERSISTENCE_IMPULSE_CONFIRMATION_RETURN_BPS:
        return True
    return _sign(impulse_return) == direction_sign


def _direction_sign(direction: str) -> int:
    if direction == "up":
        return 1
    if direction == "down":
        return -1
    return 0


def _sign(value: Decimal) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


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
