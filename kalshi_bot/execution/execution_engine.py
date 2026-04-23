"""Simulation-only execution engine for Phase 8."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from kalshi_bot.config.settings import KalshiSettings
from kalshi_bot.contracts.contract_scanner import ContractScanSnapshot, ScannedContract
from kalshi_bot.execution.exit_manager import (
    ClosedSimulatedPosition,
    determine_exit_decisions,
)


class SimulationExecutionError(ValueError):
    """Raised when simulation execution configuration is invalid."""


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
    def from_settings(cls, settings: KalshiSettings) -> "SimulationExecutionEngine":
        return cls(
            enabled=settings.simulation_enabled,
            max_new_positions_per_evaluation=settings.simulation_max_new_positions_per_evaluation,
            position_id_prefix=settings.simulation_position_id_prefix,
            exit_enabled=settings.simulation_exit_enabled,
            allow_same_pass_reentry=settings.simulation_allow_same_pass_reentry,
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

            position = self._open_position_from_contract(ranked_contract)
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

    def _open_position_from_contract(self, contract: ScannedContract) -> SimulatedPosition:
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
            status="open",
            opened_at=reference_timestamp,
            updated_at=reference_timestamp,
            update_count=0,
        )


def _reference_timestamp(contract: ScannedContract) -> str | None:
    if contract.market_as_of:
        return contract.market_as_of
    return contract.bias_as_of
