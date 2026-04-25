"""Pure simulation exit-decision helpers for Phase 8."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from kalshi_bot.contracts.contract_scanner import ScannedContract


PROFIT_CAPTURE_DELTA = Decimal("0.030")
LOSS_PROTECTION_DELTA = Decimal("-0.020")
MAX_HOLD_UPDATES = 12


@dataclass(frozen=True)
class SimulationExitDecision:
    """Deterministic close instruction for one simulated position."""

    position_id: str
    product_id: str
    market_ticker: str
    exit_reason: str
    exit_price: Decimal
    closed_at: str | None


@dataclass(frozen=True)
class ClosedSimulatedPosition:
    """Closed simulated position history record."""

    position_id: str
    product_id: str
    market_ticker: str
    direction: str
    structure: str
    confidence: int
    entry_price: Decimal
    exit_price: Decimal
    stake_dollars: Decimal | None
    status: str
    opened_at: str | None
    closed_at: str | None
    updated_at: str | None
    update_count: int
    exit_reason: str


def determine_exit_decisions(
    *,
    open_positions: Mapping[str, Any],
    ranked_contracts: tuple[ScannedContract, ...],
) -> tuple[SimulationExitDecision, ...]:
    """Return pure, deterministic exit decisions for the current simulation pass."""

    ranked_by_market = {contract.market_ticker: contract for contract in ranked_contracts}
    top_ranked_by_product: dict[str, ScannedContract] = {}
    for contract in ranked_contracts:
        top_ranked_by_product.setdefault(contract.product_id, contract)

    decisions: list[SimulationExitDecision] = []
    for position_id in sorted(open_positions):
        position = open_positions[position_id]
        current_market_contract = ranked_by_market.get(position.market_ticker)
        top_ranked_for_product = top_ranked_by_product.get(position.product_id)

        direction_conflict = (
            top_ranked_for_product is not None
            and top_ranked_for_product.direction != position.direction
        )
        exit_price = _current_price(current_market_contract, position)
        price_delta = exit_price - position.entry_price
        exit_reason = None

        if direction_conflict:
            exit_reason = "direction_conflict"
        elif position.update_count > 0 and price_delta >= PROFIT_CAPTURE_DELTA:
            exit_reason = "profit_capture"
        elif position.update_count > 0 and price_delta <= LOSS_PROTECTION_DELTA:
            exit_reason = "loss_protection"
        elif position.update_count >= MAX_HOLD_UPDATES:
            exit_reason = "max_hold_updates"

        if exit_reason is None:
            continue

        closed_at = _closed_at(current_market_contract, position)
        decisions.append(
            SimulationExitDecision(
                position_id=position.position_id,
                product_id=position.product_id,
                market_ticker=position.market_ticker,
                exit_reason=exit_reason,
                exit_price=exit_price,
                closed_at=closed_at,
            )
        )
    return tuple(decisions)


def _current_price(
    current_market_contract: ScannedContract | None,
    position: Any,
) -> Decimal:
    if current_market_contract is not None:
        return current_market_contract.midpoint
    return position.latest_price


def _closed_at(
    current_market_contract: ScannedContract | None,
    position: Any,
) -> str | None:
    if current_market_contract is not None:
        if current_market_contract.market_as_of:
            return current_market_contract.market_as_of
        return current_market_contract.bias_as_of
    if position.updated_at:
        return position.updated_at
    return position.opened_at
