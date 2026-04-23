"""Pure simulation exit-decision helpers for Phase 8."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from kalshi_bot.contracts.contract_scanner import ScannedContract


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

        market_not_ranked = current_market_contract is None
        direction_conflict = (
            top_ranked_for_product is not None
            and top_ranked_for_product.direction != position.direction
        )
        if not market_not_ranked and not direction_conflict:
            continue

        exit_reason = "direction_conflict" if direction_conflict else "market_not_ranked"
        exit_price = (
            current_market_contract.midpoint
            if current_market_contract is not None
            else position.latest_price
        )
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
