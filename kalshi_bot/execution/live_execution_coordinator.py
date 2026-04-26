"""Dry-run live execution coordination for Phase F2."""

from __future__ import annotations

from typing import Any

from kalshi_bot.config.settings import KalshiSettings
from kalshi_bot.execution.execution_engine import (
    LiveOrderIntent,
    SimulationSnapshot,
    build_live_order_intent,
)
from kalshi_bot.observability.logger import StructuredLogger


class LiveExecutionCoordinator:
    """Convert simulated entries into live order intents without submitting orders."""

    def __init__(
        self,
        *,
        settings: KalshiSettings,
        risk_manager: Any | None = None,
    ) -> None:
        self._settings = settings
        self._risk_manager = risk_manager
        self._logger = StructuredLogger(
            log_directory=settings.log_directory,
            enabled=settings.log_jsonl_enabled,
        )

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

    def _log_intent_skipped(
        self,
        *,
        reason: str,
        product_id: str,
        market_ticker: str | None,
        simulation_position_id: str,
    ) -> None:
        self._logger.log_event(
            category="live_execution",
            event_type="live_order_intent_skipped",
            source="live_execution_coordinator",
            identifier=simulation_position_id,
            payload={
                "reason": reason,
                "product_id": product_id,
                "market_ticker": market_ticker,
                "simulation_position_id": simulation_position_id,
            },
        )
