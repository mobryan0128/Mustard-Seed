"""Supervised simulation-first runner over the existing component graph."""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from kalshi_bot.clients.crypto_feed_client import CryptoFeedClient, CryptoFeedClientError
from kalshi_bot.clients.websocket_client import KalshiWebSocketClient, KalshiWebSocketError
from kalshi_bot.config.settings import KalshiSettings
from kalshi_bot.contracts.contract_scanner import (
    ContractScanSnapshot,
    ContractScanner,
    ContractScannerError,
)
from kalshi_bot.execution.execution_engine import (
    SimulationExecutionEngine,
    SimulationExecutionError,
    SimulationSnapshot,
)
from kalshi_bot.forecast.bias_engine import BiasEngine, BiasEngineError, BiasSnapshot
from kalshi_bot.market.market_state_cache import MarketStateCache, MarketStateSnapshot
from kalshi_bot.observability.logger import StructuredLogger
from kalshi_bot.observability.replay_engine import ReplayEngine


class RunnerError(RuntimeError):
    """Raised when runner configuration or lifecycle handling fails."""


@dataclass(frozen=True)
class SkipReasonDiagnostic:
    """Aggregated skipped-contract reason for runner diagnostics."""

    reason: str
    count: int


@dataclass(frozen=True)
class BiasDiagnostic:
    """Per-product bias visibility for runner diagnostics."""

    product_id: str
    state_present: bool
    direction: str | None
    confidence: int | None
    structure: str | None
    risk_flags: tuple[tuple[str, bool], ...]


@dataclass(frozen=True)
class MappedMarketDiagnostic:
    """Mapped market visibility for runner diagnostics."""

    product_id: str
    market_ticker: str
    market_ticker_present: bool
    bid_present: bool
    ask_present: bool


@dataclass(frozen=True)
class RunnerStatus:
    """Inspectable high-level runner status."""

    cycle_count: int
    mode: str
    stopped: bool
    last_successful_cycle_at: str | None
    last_error: str | None
    kalshi_feed_connected: bool
    crypto_feed_connected: bool
    tracked_market_count: int
    tracked_crypto_product_count: int
    ranked_contract_count: int
    skipped_contract_count: int
    top_skip_reasons: tuple[SkipReasonDiagnostic, ...]
    bias_diagnostics: tuple[BiasDiagnostic, ...]
    mapped_market_diagnostics: tuple[MappedMarketDiagnostic, ...]
    open_position_count: int
    closed_position_count: int
    live_flags_present: bool


@dataclass(frozen=True)
class RunnerCycleResult:
    """One completed coordination cycle."""

    cycle_number: int
    bias_snapshot: BiasSnapshot
    contract_scan_snapshot: ContractScanSnapshot
    simulation_snapshot: SimulationSnapshot
    status: RunnerStatus


class KalshiBotRunner:
    """Own and coordinate the existing components in a supervised loop."""

    def __init__(
        self,
        *,
        settings: KalshiSettings,
        market_state_cache: MarketStateCache,
        kalshi_ws_client: Any,
        crypto_feed_client: Any,
        bias_engine: BiasEngine,
        contract_scanner: ContractScanner,
        simulation_engine: SimulationExecutionEngine,
        logger: StructuredLogger,
        replay_engine: ReplayEngine,
        sleep_fn=time.sleep,
    ) -> None:
        if not settings.runner_enabled:
            raise RunnerError("RUNNER_ENABLED must be true.")
        self._settings = settings
        self._market_state_cache = market_state_cache
        self._kalshi_ws_client = kalshi_ws_client
        self._crypto_feed_client = crypto_feed_client
        self._bias_engine = bias_engine
        self._contract_scanner = contract_scanner
        self._simulation_engine = simulation_engine
        self._logger = logger
        self._replay_engine = replay_engine
        self._sleep_fn = sleep_fn
        self._stopped = False
        self._cycle_count = 0
        self._last_successful_cycle_at: str | None = None
        self._last_error: str | None = None
        self._latest_result: RunnerCycleResult | None = None
        self._market_tickers = tuple(
            dict.fromkeys(
                market_ticker
                for tickers in settings.contract_scanner_product_markets.values()
                for market_ticker in tickers
            )
        )

    @classmethod
    def from_settings(cls, settings: KalshiSettings) -> "KalshiBotRunner":
        market_state_cache = MarketStateCache()
        try:
            kalshi_ws_client = KalshiWebSocketClient.from_settings(
                settings,
                market_state_cache=market_state_cache,
            )
            crypto_feed_client = CryptoFeedClient.from_settings(settings)
            bias_engine = BiasEngine.from_settings(settings)
            contract_scanner = ContractScanner.from_settings(settings)
            simulation_engine = SimulationExecutionEngine.from_settings(settings)
        except (
            KalshiWebSocketError,
            CryptoFeedClientError,
            BiasEngineError,
            ContractScannerError,
            SimulationExecutionError,
        ) as exc:
            raise RunnerError(str(exc)) from exc

        return cls(
            settings=settings,
            market_state_cache=market_state_cache,
            kalshi_ws_client=kalshi_ws_client,
            crypto_feed_client=crypto_feed_client,
            bias_engine=bias_engine,
            contract_scanner=contract_scanner,
            simulation_engine=simulation_engine,
            logger=StructuredLogger(
                log_directory=settings.log_directory,
                enabled=settings.log_jsonl_enabled,
            ),
            replay_engine=ReplayEngine(
                replay_directory=settings.replay_directory,
                enabled=settings.replay_write_enabled,
            ),
        )

    def stop(self) -> None:
        self._stopped = True

    def snapshot(self) -> RunnerStatus:
        if self._latest_result is not None:
            return self._latest_result.status
        return self._status(
            kalshi_feed_connected=False,
            crypto_feed_connected=False,
            ranked_contract_count=0,
            contract_scan_snapshot=None,
            bias_snapshot=None,
            market_snapshot=None,
        )

    def run_forever(self) -> list[RunnerCycleResult]:
        return self.run_cycles(max_cycles=self._settings.runner_max_cycles)

    def run_cycles(self, max_cycles: int | None) -> list[RunnerCycleResult]:
        if max_cycles is not None and max_cycles <= 0:
            raise RunnerError("max_cycles must be greater than zero when provided.")

        results: list[RunnerCycleResult] = []
        while not self._stopped:
            if max_cycles is not None and self._cycle_count >= max_cycles:
                break
            try:
                result = self._run_single_cycle()
            except Exception as exc:  # noqa: BLE001
                self._last_error = str(exc)
                self._log_cycle_error()
                if not results and self._settings.runner_fail_fast_on_startup:
                    raise RunnerError(str(exc)) from exc
                self._sleep_fn(self._settings.runner_loop_interval_seconds)
                continue

            results.append(result)
            if self._stopped:
                break
            self._sleep_fn(self._settings.runner_loop_interval_seconds)
        return results

    def _run_single_cycle(self) -> RunnerCycleResult:
        self._cycle_count += 1
        cycle_number = self._cycle_count
        self._log_cycle_event("cycle_start", {"cycle_number": cycle_number})

        kalshi_result, crypto_result = asyncio.run(self._run_ingestion_cycle())
        bias_snapshot = self._bias_engine.ingest(self._crypto_feed_client.snapshot())
        market_snapshot = self._market_state_cache.snapshot()
        contract_scan_snapshot = self._contract_scanner.scan(
            bias_snapshot=bias_snapshot,
            market_snapshot=market_snapshot,
        )
        simulation_snapshot = self._simulation_engine.evaluate(contract_scan_snapshot)
        self._last_successful_cycle_at = _utc_now_iso()
        self._last_error = None

        status = self._status(
            kalshi_feed_connected=kalshi_result.messages_received > 0,
            crypto_feed_connected=crypto_result.messages_received > 0,
            ranked_contract_count=len(contract_scan_snapshot.ranked_contracts),
            contract_scan_snapshot=contract_scan_snapshot,
            bias_snapshot=bias_snapshot,
            market_snapshot=market_snapshot,
        )
        result = RunnerCycleResult(
            cycle_number=cycle_number,
            bias_snapshot=bias_snapshot,
            contract_scan_snapshot=contract_scan_snapshot,
            simulation_snapshot=simulation_snapshot,
            status=status,
        )
        self._latest_result = result
        self._record_cycle_snapshot(result)
        if cycle_number % self._settings.runner_status_log_every_n_cycles == 0:
            self._log_cycle_event(
                "cycle_completed",
                {
                    "cycle_number": cycle_number,
                    "tracked_market_count": status.tracked_market_count,
                    "tracked_crypto_product_count": status.tracked_crypto_product_count,
                    "ranked_contract_count": status.ranked_contract_count,
                    "skipped_contract_count": status.skipped_contract_count,
                    "top_skip_reasons": _skip_reason_payloads(status.top_skip_reasons),
                    "bias_diagnostics": _bias_diagnostic_payloads(status.bias_diagnostics),
                    "mapped_market_diagnostics": _mapped_market_diagnostic_payloads(
                        status.mapped_market_diagnostics
                    ),
                    "open_position_count": status.open_position_count,
                    "closed_position_count": status.closed_position_count,
                    "kalshi_feed_connected": status.kalshi_feed_connected,
                    "crypto_feed_connected": status.crypto_feed_connected,
                    "live_flags_present": status.live_flags_present,
                },
            )
        return result

    async def _run_ingestion_cycle(self):
        return await asyncio.gather(
            self._kalshi_ws_client.run(
                market_tickers=self._market_tickers,
                message_limit=self._settings.ws_message_limit,
            ),
            self._crypto_feed_client.run(
                message_limit=self._settings.crypto_feed_message_limit,
            ),
        )

    def _status(
        self,
        *,
        kalshi_feed_connected: bool,
        crypto_feed_connected: bool,
        ranked_contract_count: int,
        contract_scan_snapshot: ContractScanSnapshot | None,
        bias_snapshot: BiasSnapshot | None,
        market_snapshot: MarketStateSnapshot | None,
    ) -> RunnerStatus:
        market_snapshot = market_snapshot or self._market_state_cache.snapshot()
        bias_snapshot = bias_snapshot or self._bias_engine.snapshot()
        crypto_snapshot = self._crypto_feed_client.snapshot()
        simulation_snapshot = self._simulation_engine.snapshot()
        return RunnerStatus(
            cycle_count=self._cycle_count,
            mode="simulation",
            stopped=self._stopped,
            last_successful_cycle_at=self._last_successful_cycle_at,
            last_error=self._last_error,
            kalshi_feed_connected=kalshi_feed_connected,
            crypto_feed_connected=crypto_feed_connected,
            tracked_market_count=len(market_snapshot.tickers),
            tracked_crypto_product_count=len(crypto_snapshot.products),
            ranked_contract_count=ranked_contract_count,
            skipped_contract_count=(
                len(contract_scan_snapshot.skipped_contracts)
                if contract_scan_snapshot is not None
                else 0
            ),
            top_skip_reasons=_top_skip_reasons(contract_scan_snapshot),
            bias_diagnostics=_bias_diagnostics(bias_snapshot),
            mapped_market_diagnostics=_mapped_market_diagnostics(
                product_markets=self._settings.contract_scanner_product_markets,
                market_snapshot=market_snapshot,
            ),
            open_position_count=len(simulation_snapshot.open_positions),
            closed_position_count=len(simulation_snapshot.closed_positions),
            live_flags_present=(
                self._settings.live_validation_enabled
                or self._settings.live_trading_enabled
                or self._settings.live_kill_switch_active
            ),
        )

    def _record_cycle_snapshot(self, result: RunnerCycleResult) -> None:
        payload = {
            "cycle_number": result.cycle_number,
            "status": {
                "mode": result.status.mode,
                "cycle_count": result.status.cycle_count,
                "kalshi_feed_connected": result.status.kalshi_feed_connected,
                "crypto_feed_connected": result.status.crypto_feed_connected,
                "tracked_market_count": result.status.tracked_market_count,
                "tracked_crypto_product_count": result.status.tracked_crypto_product_count,
                "ranked_contract_count": result.status.ranked_contract_count,
                "skipped_contract_count": result.status.skipped_contract_count,
                "top_skip_reasons": _skip_reason_payloads(result.status.top_skip_reasons),
                "bias_diagnostics": _bias_diagnostic_payloads(result.status.bias_diagnostics),
                "mapped_market_diagnostics": _mapped_market_diagnostic_payloads(
                    result.status.mapped_market_diagnostics
                ),
                "open_position_count": result.status.open_position_count,
                "closed_position_count": result.status.closed_position_count,
                "last_successful_cycle_at": result.status.last_successful_cycle_at,
                "last_error": result.status.last_error,
                "live_flags_present": result.status.live_flags_present,
            },
        }
        self._replay_engine.record_snapshot(
            source="runner",
            snapshot_name="cycle_snapshot",
            snapshot=payload,
        )

    def _log_cycle_event(self, event_type: str, payload: dict[str, object]) -> None:
        self._logger.log_event(
            category="runner",
            event_type=event_type,
            source="kalshi_bot_runner",
            identifier="simulation_runner",
            payload=payload,
        )

    def _log_cycle_error(self) -> None:
        self._log_cycle_event(
            "cycle_failed",
            {
                "cycle_number": self._cycle_count,
                "last_error": self._last_error,
            },
        )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _top_skip_reasons(
    contract_scan_snapshot: ContractScanSnapshot | None,
) -> tuple[SkipReasonDiagnostic, ...]:
    if contract_scan_snapshot is None:
        return ()
    counts = Counter(contract.reason for contract in contract_scan_snapshot.skipped_contracts)
    return tuple(
        SkipReasonDiagnostic(reason=reason, count=count)
        for reason, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    )


def _bias_diagnostics(bias_snapshot: BiasSnapshot) -> tuple[BiasDiagnostic, ...]:
    diagnostics: list[BiasDiagnostic] = []
    for product_id in ("BTC-USD", "ETH-USD"):
        state = bias_snapshot.products.get(product_id)
        diagnostics.append(
            BiasDiagnostic(
                product_id=product_id,
                state_present=state is not None,
                direction=state.direction if state is not None else None,
                confidence=state.confidence if state is not None else None,
                structure=state.structure if state is not None else None,
                risk_flags=_risk_flags(state.risk_flags) if state is not None else (),
            )
        )
    return tuple(diagnostics)


def _risk_flags(risk_flags: Any) -> tuple[tuple[str, bool], ...]:
    return (
        ("insufficient_history", bool(risk_flags.insufficient_history)),
        ("stale_data", bool(risk_flags.stale_data)),
        ("time_sync_failed", bool(risk_flags.time_sync_failed)),
    )


def _mapped_market_diagnostics(
    *,
    product_markets: dict[str, tuple[str, ...]],
    market_snapshot: MarketStateSnapshot,
) -> tuple[MappedMarketDiagnostic, ...]:
    diagnostics: list[MappedMarketDiagnostic] = []
    for product_id, market_tickers in product_markets.items():
        for market_ticker in market_tickers:
            ticker_state = market_snapshot.tickers.get(market_ticker)
            diagnostics.append(
                MappedMarketDiagnostic(
                    product_id=product_id,
                    market_ticker=market_ticker,
                    market_ticker_present=ticker_state is not None,
                    bid_present=(
                        ticker_state is not None
                        and ticker_state.yes_bid_dollars is not None
                    ),
                    ask_present=(
                        ticker_state is not None
                        and ticker_state.yes_ask_dollars is not None
                    ),
                )
            )
    return tuple(diagnostics)


def _skip_reason_payloads(
    diagnostics: tuple[SkipReasonDiagnostic, ...],
) -> tuple[dict[str, object], ...]:
    return tuple({"reason": item.reason, "count": item.count} for item in diagnostics)


def _bias_diagnostic_payloads(
    diagnostics: tuple[BiasDiagnostic, ...],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "product_id": item.product_id,
            "state_present": item.state_present,
            "direction": item.direction,
            "confidence": item.confidence,
            "structure": item.structure,
            "risk_flags": dict(item.risk_flags),
        }
        for item in diagnostics
    )


def _mapped_market_diagnostic_payloads(
    diagnostics: tuple[MappedMarketDiagnostic, ...],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "product_id": item.product_id,
            "market_ticker": item.market_ticker,
            "market_ticker_present": item.market_ticker_present,
            "bid_present": item.bid_present,
            "ask_present": item.ask_present,
        }
        for item in diagnostics
    )
