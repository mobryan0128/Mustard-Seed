"""Supervised simulation-first runner over the existing component graph."""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from kalshi_bot.clients.crypto_feed_client import CryptoFeedClient, CryptoFeedClientError
from kalshi_bot.clients.kalshi_client import KalshiClient, KalshiClientError
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
from kalshi_bot.execution.live_execution_coordinator import LiveExecutionCoordinator
from kalshi_bot.forecast.bias_engine import BiasEngine, BiasEngineError, BiasSnapshot
from kalshi_bot.market.crypto_market_discovery import (
    CryptoMarketDiscovery,
    CryptoMarketDiscoveryError,
    CryptoMarketDiscoverySnapshot,
)
from kalshi_bot.market.market_state_cache import MarketStateCache, MarketStateSnapshot
from kalshi_bot.observability.logger import StructuredLogger
from kalshi_bot.observability.replay_engine import ReplayEngine
from kalshi_bot.risk.risk_manager import RiskManager


class RunnerError(RuntimeError):
    """Raised when runner configuration or lifecycle handling fails."""


KALSHI_FEED_TIMEOUT_RECOVERY_THRESHOLD = 2


@dataclass(frozen=True)
class SkipReasonDiagnostic:
    """Aggregated skipped-contract reason for runner diagnostics."""

    reason: str
    count: int


@dataclass(frozen=True)
class SkippedContractDiagnostic:
    """Sampled skipped-contract details for settlement audit diagnostics."""

    product_id: str
    market_ticker: str
    reason: str
    target_price: Decimal | None
    time_remaining_seconds: int | None
    feasibility_status: str | None
    distance_to_target_bps: Decimal | None
    required_bps_per_minute: Decimal | None
    side_currently_itm: bool | None
    side_needs_cross: bool | None
    trend_confirmation_status: str | None
    reversal_confirmation_status: str | None
    scanner_score_downgrade_reasons: tuple[str, ...]


@dataclass(frozen=True)
class BiasDiagnostic:
    """Per-product bias visibility for runner diagnostics."""

    product_id: str
    state_present: bool
    direction: str | None
    confidence: int | None
    structure: str | None
    risk_flags: tuple[tuple[str, bool], ...]
    latest_price: Decimal | None
    bias_as_of: str | None
    stale_age_seconds: int | None
    observation_count: int | None
    recent_return_bps: Decimal | None
    lookback_return_bps: Decimal | None
    impulse_direction: str | None
    impulse_return_bps: Decimal | None
    impulse_detected: bool


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
    active_market_tickers: tuple[str, ...]
    market_discovery_enabled: bool
    last_market_discovery_cycle: int | None
    kalshi_market_data_message_count: int
    kalshi_subscription_message_count: int
    kalshi_subscribed_market_tickers: tuple[str, ...]
    kalshi_feed_timed_out: bool
    skipped_contract_count: int
    top_skip_reasons: tuple[SkipReasonDiagnostic, ...]
    skipped_contract_diagnostics: tuple[SkippedContractDiagnostic, ...]
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
        contract_scanner: ContractScanner | None,
        market_discovery: CryptoMarketDiscovery | None,
        simulation_engine: SimulationExecutionEngine | None,
        logger: StructuredLogger,
        replay_engine: ReplayEngine,
        live_execution_coordinator: LiveExecutionCoordinator | None = None,
        sleep_fn=time.sleep,
        time_fn=time.monotonic,
    ) -> None:
        if not settings.runner_enabled:
            raise RunnerError("RUNNER_ENABLED must be true.")
        self._settings = settings
        self._market_state_cache = market_state_cache
        self._kalshi_ws_client = kalshi_ws_client
        self._crypto_feed_client = crypto_feed_client
        self._bias_engine = bias_engine
        self._contract_scanner = contract_scanner
        self._market_discovery = market_discovery
        self._simulation_engine = simulation_engine
        self._live_execution_coordinator = live_execution_coordinator
        self._logger = logger
        self._replay_engine = replay_engine
        self._sleep_fn = sleep_fn
        self._time_fn = time_fn
        self._stopped = False
        self._cycle_count = 0
        self._last_successful_cycle_at: str | None = None
        self._last_error: str | None = None
        self._latest_result: RunnerCycleResult | None = None
        self._last_market_discovery_cycle: int | None = None
        self._consecutive_kalshi_feed_timeouts = 0
        self._force_market_discovery_next_cycle = False
        self._last_fast_scan_submission_at: float | None = None
        self._active_product_markets = (
            {}
            if settings.auto_market_discovery_enabled
            else dict(settings.contract_scanner_product_markets)
        )
        self._market_tickers = _flatten_product_markets(self._active_product_markets)

    @classmethod
    def from_settings(cls, settings: KalshiSettings) -> "KalshiBotRunner":
        market_state_cache = MarketStateCache()
        logger = StructuredLogger(
            log_directory=settings.log_directory,
            enabled=settings.log_jsonl_enabled,
        )
        replay_engine = ReplayEngine(
            replay_directory=settings.replay_directory,
            enabled=settings.replay_write_enabled,
        )
        try:
            kalshi_ws_client = KalshiWebSocketClient.from_settings(
                settings,
                market_state_cache=market_state_cache,
            )
            crypto_feed_client = CryptoFeedClient.from_settings(settings)
            bias_engine = BiasEngine.from_settings(settings)
            if settings.auto_market_discovery_enabled:
                kalshi_client = KalshiClient.from_settings(settings, logger=logger)
                market_discovery = CryptoMarketDiscovery.from_settings(
                    settings,
                    kalshi_client,
                    logger=logger,
                )
                contract_scanner = None
            else:
                market_discovery = None
                contract_scanner = ContractScanner.from_settings(settings)
            simulation_engine = (
                SimulationExecutionEngine.from_settings(settings)
                if settings.simulation_enabled
                else None
            )
            live_execution_client = (
                KalshiClient.from_settings(settings, logger=logger)
                if settings.live_runner_execution_enabled
                else None
            )
            live_execution_risk_manager = (
                _live_runner_risk_manager_from_settings(settings)
                if settings.live_runner_execution_enabled
                else None
            )
            live_execution_coordinator = LiveExecutionCoordinator(
                settings=settings,
                client=live_execution_client,
                risk_manager=live_execution_risk_manager,
            )
        except (
            KalshiWebSocketError,
            CryptoFeedClientError,
            KalshiClientError,
            BiasEngineError,
            ContractScannerError,
            CryptoMarketDiscoveryError,
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
            market_discovery=market_discovery,
            simulation_engine=simulation_engine,
            logger=logger,
            replay_engine=replay_engine,
            live_execution_coordinator=live_execution_coordinator,
        )

    def stop(self) -> None:
        self._stopped = True

    def snapshot(self) -> RunnerStatus:
        if self._latest_result is not None:
            return self._latest_result.status
        return self._status(
            kalshi_feed_connected=False,
            crypto_feed_connected=False,
            kalshi_market_data_message_count=0,
            kalshi_subscription_message_count=0,
            kalshi_subscribed_market_tickers=(),
            kalshi_feed_timed_out=False,
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
            self._sleep_between_cycles()
        return results

    def _sleep_between_cycles(self) -> None:
        loop_interval = self._settings.runner_loop_interval_seconds
        if not self._fast_scan_available():
            self._sleep_fn(loop_interval)
            return

        fast_interval = self._settings.live_fast_scan_interval_seconds
        remaining = loop_interval
        while remaining > 0 and not self._stopped:
            sleep_for = min(fast_interval, remaining)
            self._sleep_fn(sleep_for)
            remaining -= sleep_for
            if self._stopped or remaining <= 0:
                break
            self._run_fast_scan_pass()

    def _fast_scan_available(self) -> bool:
        return (
            bool(getattr(self._settings, "live_fast_scan_enabled", False))
            and self._settings.live_runner_execution_enabled
            and self._live_execution_coordinator is not None
        )

    def _run_fast_scan_pass(self) -> None:
        if not self._fast_scan_available():
            return
        now = self._time_fn()
        cooldown_seconds = self._settings.live_fast_scan_cooldown_seconds
        if (
            self._last_fast_scan_submission_at is not None
            and now - self._last_fast_scan_submission_at < cooldown_seconds
        ):
            self._log_cycle_event(
                "live_fast_scan_skipped",
                {
                    "cycle_number": self._cycle_count,
                    "scan_source": "fast_scan",
                    "reason": "cooldown_active",
                    "cooldown_seconds": cooldown_seconds,
                },
            )
            return

        self._log_cycle_event(
            "live_fast_scan_started",
            {
                "cycle_number": self._cycle_count,
                "scan_source": "fast_scan",
            },
        )
        bias_snapshot = self._bias_engine.ingest(self._crypto_feed_client.snapshot())
        market_snapshot = self._market_state_cache.snapshot()
        contract_scan_snapshot = self._scan_contracts(
            bias_snapshot=bias_snapshot,
            market_snapshot=market_snapshot,
        )
        live_intents = (
            self._live_execution_coordinator.process_contract_scan_snapshot(
                contract_scan_snapshot,
                cycle_number=self._cycle_count,
                market_snapshot=market_snapshot,
                allow_reconciliation=False,
                scan_source="fast_scan",
            )
        )
        if live_intents:
            self._last_fast_scan_submission_at = now
        self._submit_live_runner_intents(
            cycle_number=self._cycle_count,
            intents=live_intents,
            scan_source="fast_scan",
        )
        self._log_cycle_event(
            "live_fast_scan_completed",
            {
                "cycle_number": self._cycle_count,
                "scan_source": "fast_scan",
                "ranked_contract_count": len(contract_scan_snapshot.ranked_contracts),
                "intent_count": len(live_intents),
            },
        )

    def _run_single_cycle(self) -> RunnerCycleResult:
        self._cycle_count += 1
        cycle_number = self._cycle_count
        self._log_cycle_event("cycle_start", {"cycle_number": cycle_number})
        self._refresh_market_discovery_if_due(cycle_number)

        kalshi_result, crypto_result = asyncio.run(self._run_ingestion_cycle())
        self._update_kalshi_feed_timeout_recovery(
            cycle_number=cycle_number,
            kalshi_result=kalshi_result,
        )
        bias_snapshot = self._bias_engine.ingest(self._crypto_feed_client.snapshot())
        market_snapshot = self._market_state_cache.snapshot()
        contract_scan_snapshot = self._scan_contracts(
            bias_snapshot=bias_snapshot,
            market_snapshot=market_snapshot,
        )
        simulation_snapshot = _empty_simulation_snapshot()
        if self._simulation_engine is not None:
            simulation_snapshot = self._simulation_engine.evaluate(contract_scan_snapshot)
            self._record_simulation_trade_events(
                cycle_number=cycle_number,
                simulation_snapshot=simulation_snapshot,
            )
        live_intents = ()
        if self._live_execution_coordinator is not None:
            if self._settings.live_runner_execution_enabled:
                live_intents = (
                    self._live_execution_coordinator.process_contract_scan_snapshot(
                        contract_scan_snapshot,
                        cycle_number=cycle_number,
                        market_snapshot=market_snapshot,
                        scan_source="normal_cycle",
                    )
                )
                self._submit_live_runner_intents(
                    cycle_number=cycle_number,
                    intents=live_intents,
                    scan_source="normal_cycle",
                )
            elif self._simulation_engine is not None:
                live_intents = (
                    self._live_execution_coordinator.process_simulation_snapshot(
                        simulation_snapshot
                    )
                )
        if (
            self._live_execution_coordinator is not None
            and self._settings.live_runner_execution_enabled
        ):
            self._live_execution_coordinator.process_profit_capture_exits(
                market_snapshot,
                cycle_number=cycle_number,
            )
            self._live_execution_coordinator.reconcile_live_positions(
                cycle_number=cycle_number,
                reason="normal_cycle",
            )
        self._last_successful_cycle_at = _utc_now_iso()
        self._last_error = None

        status = self._status(
            kalshi_feed_connected=_market_data_message_count(kalshi_result) > 0,
            crypto_feed_connected=crypto_result.messages_received > 0,
            kalshi_market_data_message_count=_market_data_message_count(kalshi_result),
            kalshi_subscription_message_count=_subscription_message_count(kalshi_result),
            kalshi_subscribed_market_tickers=_subscribed_market_tickers(kalshi_result),
            kalshi_feed_timed_out=bool(getattr(kalshi_result, "timed_out", False)),
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
                    "active_market_tickers": list(status.active_market_tickers),
                    "market_discovery_enabled": status.market_discovery_enabled,
                    "last_market_discovery_cycle": status.last_market_discovery_cycle,
                    "kalshi_market_data_message_count": status.kalshi_market_data_message_count,
                    "kalshi_subscription_message_count": status.kalshi_subscription_message_count,
                    "kalshi_subscribed_market_tickers": list(
                        status.kalshi_subscribed_market_tickers
                    ),
                    "kalshi_feed_timed_out": status.kalshi_feed_timed_out,
                    "skipped_contract_count": status.skipped_contract_count,
                    "top_skip_reasons": _skip_reason_payloads(status.top_skip_reasons),
                    "skipped_contract_diagnostics": (
                        _skipped_contract_diagnostic_payloads(
                            status.skipped_contract_diagnostics
                        )
                    ),
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
        if not self._market_tickers:
            crypto_result = await self._crypto_feed_client.run(
                message_limit=self._settings.crypto_feed_message_limit,
            )
            return _FeedRunResult(messages_received=0), crypto_result
        return await asyncio.gather(
            self._kalshi_ws_client.run(
                market_tickers=self._market_tickers,
                message_limit=self._settings.ws_message_limit,
            ),
            self._crypto_feed_client.run(
                message_limit=self._settings.crypto_feed_message_limit,
            ),
        )

    def _update_kalshi_feed_timeout_recovery(
        self,
        *,
        cycle_number: int,
        kalshi_result: Any,
    ) -> None:
        market_data_messages = _market_data_message_count(kalshi_result)
        timed_out = bool(getattr(kalshi_result, "timed_out", False))
        if market_data_messages > 0 or not self._market_tickers or not timed_out:
            self._consecutive_kalshi_feed_timeouts = 0
            return

        self._consecutive_kalshi_feed_timeouts += 1
        recovery_result = "threshold_not_met"
        recovery_attempted = False
        if (
            self._consecutive_kalshi_feed_timeouts
            >= KALSHI_FEED_TIMEOUT_RECOVERY_THRESHOLD
            and not self._force_market_discovery_next_cycle
        ):
            recovery_attempted = True
            if self._market_discovery is None:
                recovery_result = "market_discovery_unavailable"
            else:
                self._force_market_discovery_next_cycle = True
                recovery_result = "market_discovery_forced"

        self._log_cycle_event(
            "kalshi_feed_timeout_recovery",
            {
                "cycle_number": cycle_number,
                "kalshi_feed_timeout_count": self._consecutive_kalshi_feed_timeouts,
                "kalshi_feed_recovery_attempted": recovery_attempted,
                "kalshi_feed_recovery_result": recovery_result,
                "active_market_tickers": list(self._market_tickers),
                "kalshi_subscribed_market_tickers": list(
                    _subscribed_market_tickers(kalshi_result)
                ),
                "kalshi_market_data_message_count": market_data_messages,
                "kalshi_subscription_message_count": _subscription_message_count(
                    kalshi_result
                ),
            },
        )

    def _refresh_market_discovery_if_due(self, cycle_number: int) -> None:
        if self._market_discovery is None:
            return
        force_refresh = self._force_market_discovery_next_cycle
        if (
            not force_refresh
            and self._last_market_discovery_cycle is not None
            and cycle_number - self._last_market_discovery_cycle
            < self._settings.market_discovery_refresh_cycles
        ):
            return

        snapshot = self._market_discovery.discover()
        self._last_market_discovery_cycle = cycle_number
        self._apply_market_discovery(snapshot, force_refresh=force_refresh)
        if force_refresh:
            self._force_market_discovery_next_cycle = False
            self._consecutive_kalshi_feed_timeouts = 0

    def _apply_market_discovery(
        self,
        snapshot: CryptoMarketDiscoverySnapshot,
        *,
        force_refresh: bool = False,
    ) -> None:
        previous_ticker_list = self._market_tickers
        previous_tickers = set(previous_ticker_list)
        next_product_markets = dict(snapshot.product_markets)
        next_tickers = _flatten_product_markets(next_product_markets)
        next_ticker_set = set(next_tickers)
        added_tickers = sorted(next_ticker_set - previous_tickers)
        dropped_tickers = sorted(previous_tickers - next_ticker_set)

        if force_refresh:
            self._log_cycle_event(
                "kalshi_feed_resubscribe_started",
                {
                    "cycle_number": self._cycle_count,
                    "force_refresh": force_refresh,
                    "previous_active_market_tickers": list(previous_ticker_list),
                    "next_active_market_tickers": list(next_tickers),
                    "added_market_tickers": added_tickers,
                    "dropped_market_tickers": dropped_tickers,
                    "kalshi_feed_timeout_count": self._consecutive_kalshi_feed_timeouts,
                    "kalshi_feed_recovery_attempted": True,
                    "kalshi_feed_recovery_result": "market_discovery_forced",
                },
            )

        self._active_product_markets = next_product_markets
        self._market_tickers = next_tickers
        self._contract_scanner = (
            ContractScanner(
                product_markets=next_product_markets,
                market_metadata_by_ticker=_market_metadata_by_ticker(
                    snapshot.discovered_markets
                ),
            )
            if next_product_markets
            else None
        )
        self._market_state_cache.retain_markets(next_tickers)
        if dropped_tickers:
            self._log_cycle_event(
                "stale_market_tickers_dropped",
                {
                    "cycle_number": self._cycle_count,
                    "dropped_market_tickers": dropped_tickers,
                },
            )
        if force_refresh:
            self._log_cycle_event(
                "kalshi_feed_resubscribe_completed",
                {
                    "cycle_number": self._cycle_count,
                    "force_refresh": force_refresh,
                    "previous_active_market_tickers": list(previous_ticker_list),
                    "active_market_tickers": list(next_tickers),
                    "added_market_tickers": added_tickers,
                    "dropped_market_tickers": dropped_tickers,
                    "kalshi_feed_timeout_count": self._consecutive_kalshi_feed_timeouts,
                    "kalshi_feed_recovery_attempted": True,
                    "kalshi_feed_recovery_result": "resubscribe_completed",
                },
            )

        payload = {
            "cycle_number": self._cycle_count,
            "force_refresh": force_refresh,
            "added_market_tickers": added_tickers,
            "dropped_market_tickers": dropped_tickers,
            "active_product_markets": _product_markets_payload(next_product_markets),
            "discovered_markets": tuple(
                {
                    "product_id": market.product_id,
                    "series_ticker": market.series_ticker,
                    "market_ticker": market.market_ticker,
                    "open_time": market.open_time,
                    "close_time": market.close_time,
                    "expiration_time": market.expiration_time,
                    "target_price": market.target_price,
                    "target_price_source": market.target_price_source,
                }
                for market in snapshot.discovered_markets
            ),
        }
        self._log_cycle_event("market_discovery_refreshed", payload)
        self._replay_engine.record_snapshot(
            source="runner",
            snapshot_name="market_discovery",
            snapshot=payload,
        )

    def _scan_contracts(
        self,
        *,
        bias_snapshot: BiasSnapshot,
        market_snapshot: MarketStateSnapshot,
    ) -> ContractScanSnapshot:
        if self._contract_scanner is None:
            return ContractScanSnapshot(ranked_contracts=(), skipped_contracts=())
        return self._contract_scanner.scan(
            bias_snapshot=bias_snapshot,
            market_snapshot=market_snapshot,
        )

    def _status(
        self,
        *,
        kalshi_feed_connected: bool,
        crypto_feed_connected: bool,
        kalshi_market_data_message_count: int,
        kalshi_subscription_message_count: int,
        kalshi_subscribed_market_tickers: tuple[str, ...],
        kalshi_feed_timed_out: bool,
        ranked_contract_count: int,
        contract_scan_snapshot: ContractScanSnapshot | None,
        bias_snapshot: BiasSnapshot | None,
        market_snapshot: MarketStateSnapshot | None,
    ) -> RunnerStatus:
        market_snapshot = market_snapshot or self._market_state_cache.snapshot()
        bias_snapshot = bias_snapshot or self._bias_engine.snapshot()
        crypto_snapshot = self._crypto_feed_client.snapshot()
        simulation_snapshot = (
            self._simulation_engine.snapshot()
            if self._simulation_engine is not None
            else _empty_simulation_snapshot()
        )
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
            active_market_tickers=self._market_tickers,
            market_discovery_enabled=self._market_discovery is not None,
            last_market_discovery_cycle=self._last_market_discovery_cycle,
            kalshi_market_data_message_count=kalshi_market_data_message_count,
            kalshi_subscription_message_count=kalshi_subscription_message_count,
            kalshi_subscribed_market_tickers=kalshi_subscribed_market_tickers,
            kalshi_feed_timed_out=kalshi_feed_timed_out,
            skipped_contract_count=(
                len(contract_scan_snapshot.skipped_contracts)
                if contract_scan_snapshot is not None
                else 0
            ),
            top_skip_reasons=_top_skip_reasons(contract_scan_snapshot),
            skipped_contract_diagnostics=_skipped_contract_diagnostics(
                contract_scan_snapshot,
            ),
            bias_diagnostics=_bias_diagnostics(
                bias_snapshot,
                product_ids=self._settings.bias_products,
            ),
            mapped_market_diagnostics=_mapped_market_diagnostics(
                product_markets=self._active_product_markets,
                market_snapshot=market_snapshot,
            ),
            open_position_count=len(simulation_snapshot.open_positions),
            closed_position_count=len(simulation_snapshot.closed_positions),
            live_flags_present=(
                self._settings.live_validation_enabled
                or self._settings.live_trading_enabled
                or self._settings.live_kill_switch_active
                or self._settings.live_runner_execution_enabled
            ),
        )

    def _submit_live_runner_intents(
        self,
        *,
        cycle_number: int,
        intents: tuple[Any, ...],
        scan_source: str = "normal_cycle",
    ) -> None:
        if self._live_execution_coordinator is None:
            return
        if not intents:
            self._log_cycle_event(
                "live_runner_no_intents",
                {"cycle_number": cycle_number, "scan_source": scan_source},
            )
            return

        for intent in intents[:1]:
            self._log_cycle_event(
                "live_runner_submission_attempted",
                {
                    "cycle_number": cycle_number,
                    "scan_source": scan_source,
                    "client_order_id": getattr(intent, "client_order_id", None),
                    "ticker": getattr(intent, "ticker", None),
                    "side": getattr(intent, "side", None),
                    "count": getattr(intent, "count", None),
                    "simulation_position_id": getattr(
                        intent,
                        "simulation_position_id",
                        None,
                    ),
                },
            )
            result = self._live_execution_coordinator.submit_live_order(intent)
            payload = {
                "cycle_number": cycle_number,
                "scan_source": scan_source,
                "client_order_id": getattr(intent, "client_order_id", None),
                "ticker": getattr(intent, "ticker", None),
                "classification": getattr(result, "classification", None),
                "decision_reason": getattr(result, "decision_reason", None),
                "order_placed": getattr(result, "order_placed", None),
                "order_id": getattr(result, "order_id", None),
                "poll_attempts_used": getattr(result, "poll_attempts_used", None),
            }
            if getattr(result, "classification", None) == "blocked_by_safeguard":
                self._log_cycle_event("live_runner_submission_blocked", payload)
                continue
            self._log_cycle_event("live_runner_submission_completed", payload)

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
                "active_market_tickers": list(result.status.active_market_tickers),
                "market_discovery_enabled": result.status.market_discovery_enabled,
                "last_market_discovery_cycle": result.status.last_market_discovery_cycle,
                "kalshi_market_data_message_count": (
                    result.status.kalshi_market_data_message_count
                ),
                "kalshi_subscription_message_count": (
                    result.status.kalshi_subscription_message_count
                ),
                "kalshi_subscribed_market_tickers": list(
                    result.status.kalshi_subscribed_market_tickers
                ),
                "kalshi_feed_timed_out": result.status.kalshi_feed_timed_out,
                "skipped_contract_count": result.status.skipped_contract_count,
                "top_skip_reasons": _skip_reason_payloads(result.status.top_skip_reasons),
                "skipped_contract_diagnostics": (
                    _skipped_contract_diagnostic_payloads(
                        result.status.skipped_contract_diagnostics
                    )
                ),
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

    def _record_simulation_trade_events(
        self,
        *,
        cycle_number: int,
        simulation_snapshot: SimulationSnapshot,
    ) -> None:
        closed_positions = {
            position.position_id: position
            for position in simulation_snapshot.closed_positions
        }
        for decision in simulation_snapshot.decisions:
            if (
                decision.action == "skip_entry"
                and decision.reason is not None
                and decision.reason.startswith("risk_")
            ):
                details = decision.details or {}
                identifier = decision.market_ticker or decision.product_id
                self._write_simulation_trade_event(
                    event_type="simulation_entry_risk_denied",
                    position_id=identifier,
                    payload={
                        "cycle_number": cycle_number,
                        "product_id": decision.product_id,
                        "market_ticker": decision.market_ticker,
                        "direction": details.get("direction"),
                        "confidence": details.get("confidence"),
                        "reason": decision.reason,
                        "entry_price": details.get("entry_price"),
                        "current_exposure_dollars": details.get(
                            "current_exposure_dollars"
                        ),
                        "realized_daily_pnl_dollars": details.get(
                            "realized_daily_pnl_dollars"
                        ),
                    },
                )
                continue
            if decision.position_id is None:
                continue
            if decision.action == "open_position":
                position = simulation_snapshot.open_positions.get(decision.position_id)
                if position is None:
                    continue
                self._write_simulation_trade_event(
                    event_type="simulation_position_opened",
                    position_id=position.position_id,
                    payload={
                        "cycle_number": cycle_number,
                        "position_id": position.position_id,
                        "product_id": position.product_id,
                        "market_ticker": position.market_ticker,
                        "direction": position.direction,
                        "structure": position.structure,
                        "confidence": position.confidence,
                        "entry_price": position.entry_price,
                        "stake_dollars": position.stake_dollars,
                        "opened_at": position.opened_at,
                    },
                )
            elif decision.action == "close_position":
                position = closed_positions.get(decision.position_id)
                if position is None:
                    continue
                self._write_simulation_trade_event(
                    event_type="simulation_position_closed",
                    position_id=position.position_id,
                    payload={
                        "cycle_number": cycle_number,
                        "position_id": position.position_id,
                        "product_id": position.product_id,
                        "market_ticker": position.market_ticker,
                        "direction": position.direction,
                        "structure": position.structure,
                        "confidence": position.confidence,
                        "entry_price": position.entry_price,
                        "exit_price": position.exit_price,
                        "stake_dollars": position.stake_dollars,
                        "opened_at": position.opened_at,
                        "closed_at": position.closed_at,
                        "exit_reason": position.exit_reason,
                        "pnl": position.exit_price - position.entry_price,
                        "pnl_dollars": (position.exit_price - position.entry_price)
                        * (position.stake_dollars or Decimal("0")),
                    },
                )

    def _write_simulation_trade_event(
        self,
        *,
        event_type: str,
        position_id: str,
        payload: dict[str, object],
    ) -> None:
        self._logger.log_event(
            category="simulation",
            event_type=event_type,
            source="simulation_execution_engine",
            identifier=position_id,
            payload=payload,
        )
        self._replay_engine.record_message(
            source="simulation_execution_engine",
            message_type=event_type,
            identifier=position_id,
            payload=payload,
        )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_simulation_snapshot() -> SimulationSnapshot:
    return SimulationSnapshot(
        open_positions={},
        closed_positions=(),
        decisions=(),
        evaluation_count=0,
    )


def _live_runner_risk_manager_from_settings(settings: KalshiSettings) -> RiskManager:
    return RiskManager(
        live_validation_enabled=True,
        live_trading_enabled=settings.live_trading_enabled,
        live_kill_switch_active=settings.live_kill_switch_active,
        env=settings.env,
        live_validation_env="prod",
        max_live_order_count=1000,
        required_time_in_force=settings.live_validation_time_in_force,
        account_balance_dollars=settings.risk_account_balance_dollars,
        min_percent_per_trade=settings.risk_min_percent_per_trade,
        max_percent_per_trade=settings.risk_max_percent_per_trade,
        min_stake_dollars=settings.risk_min_stake_dollars,
        max_stake_dollars=settings.risk_max_stake_dollars,
        max_open_positions=settings.risk_max_open_positions,
        max_total_exposure_dollars=settings.risk_max_total_exposure_dollars,
        daily_loss_limit_dollars=settings.risk_daily_loss_limit_dollars,
        risk_kill_switch_active=settings.risk_kill_switch_active,
    )


@dataclass(frozen=True)
class _FeedRunResult:
    messages_received: int
    market_data_messages: int = 0
    subscription_messages: int = 0
    timed_out: bool = False
    subscribed_market_tickers: tuple[str, ...] = ()


def _flatten_product_markets(product_markets: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            market_ticker
            for tickers in product_markets.values()
            for market_ticker in tickers
        )
    )


def _market_data_message_count(result: Any) -> int:
    return int(getattr(result, "market_data_messages", result.messages_received))


def _subscription_message_count(result: Any) -> int:
    return int(getattr(result, "subscription_messages", 0))


def _subscribed_market_tickers(result: Any) -> tuple[str, ...]:
    return tuple(getattr(result, "subscribed_market_tickers", ()))


def _product_markets_payload(
    product_markets: dict[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    return {product_id: tuple(tickers) for product_id, tickers in product_markets.items()}


def _market_metadata_by_ticker(markets) -> dict[str, dict[str, object]]:  # noqa: ANN001
    return {
        market.market_ticker: {
            "open_time": market.open_time,
            "close_time": market.close_time,
            "expiration_time": market.expiration_time,
            "target_price": market.target_price,
            "target_price_source": market.target_price_source,
        }
        for market in markets
    }


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


def _skipped_contract_diagnostics(
    contract_scan_snapshot: ContractScanSnapshot | None,
) -> tuple[SkippedContractDiagnostic, ...]:
    if contract_scan_snapshot is None:
        return ()
    return tuple(
        SkippedContractDiagnostic(
            product_id=contract.product_id,
            market_ticker=contract.market_ticker,
            reason=contract.reason,
            target_price=contract.target_price,
            time_remaining_seconds=contract.time_remaining_seconds,
            feasibility_status=contract.feasibility_status,
            distance_to_target_bps=contract.distance_to_target_bps,
            required_bps_per_minute=contract.required_bps_per_minute,
            side_currently_itm=contract.side_currently_itm,
            side_needs_cross=contract.side_needs_cross,
            trend_confirmation_status=contract.trend_confirmation_status,
            reversal_confirmation_status=contract.reversal_confirmation_status,
            scanner_score_downgrade_reasons=contract.scanner_score_downgrade_reasons,
        )
        for contract in contract_scan_snapshot.skipped_contracts[:10]
    )


def _bias_diagnostics(
    bias_snapshot: BiasSnapshot,
    *,
    product_ids: tuple[str, ...],
) -> tuple[BiasDiagnostic, ...]:
    diagnostics: list[BiasDiagnostic] = []
    diagnostic_product_ids = tuple(
        dict.fromkeys(
            product_id
            for product_id in (*product_ids, *bias_snapshot.products)
            if product_id.strip()
        )
    )
    for product_id in diagnostic_product_ids:
        state = bias_snapshot.products.get(product_id)
        diagnostics.append(
            BiasDiagnostic(
                product_id=product_id,
                state_present=state is not None,
                direction=state.direction if state is not None else None,
                confidence=state.confidence if state is not None else None,
                structure=state.structure if state is not None else None,
                risk_flags=_risk_flags(state.risk_flags) if state is not None else (),
                latest_price=state.latest_price if state is not None else None,
                bias_as_of=state.as_of if state is not None else None,
                stale_age_seconds=_stale_age_seconds(state),
                observation_count=state.observation_count if state is not None else None,
                recent_return_bps=(
                    state.recent_return_bps if state is not None else None
                ),
                lookback_return_bps=(
                    state.lookback_return_bps if state is not None else None
                ),
                impulse_direction=(
                    state.impulse_direction if state is not None else None
                ),
                impulse_return_bps=(
                    state.impulse_return_bps if state is not None else None
                ),
                impulse_detected=(
                    state.impulse_detected if state is not None else False
                ),
            )
        )
    return tuple(diagnostics)


def _risk_flags(risk_flags: Any) -> tuple[tuple[str, bool], ...]:
    return (
        ("insufficient_history", bool(risk_flags.insufficient_history)),
        ("stale_data", bool(risk_flags.stale_data)),
        ("time_sync_failed", bool(risk_flags.time_sync_failed)),
    )


def _stale_age_seconds(state: Any) -> int | None:
    if state is None or state.as_of is None:
        return None
    try:
        parsed = datetime.fromisoformat(state.as_of.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return max(int((datetime.now(timezone.utc) - parsed).total_seconds()), 0)


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


def _skipped_contract_diagnostic_payloads(
    diagnostics: tuple[SkippedContractDiagnostic, ...],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "product_id": item.product_id,
            "market_ticker": item.market_ticker,
            "reason": item.reason,
            "target_price": item.target_price,
            "time_remaining_seconds": item.time_remaining_seconds,
            "feasibility_status": item.feasibility_status,
            "distance_to_target_bps": item.distance_to_target_bps,
            "required_bps_per_minute": item.required_bps_per_minute,
            "side_currently_itm": item.side_currently_itm,
            "side_needs_cross": item.side_needs_cross,
            "trend_confirmation_status": item.trend_confirmation_status,
            "reversal_confirmation_status": item.reversal_confirmation_status,
            "scanner_score_downgrade_reasons": list(
                item.scanner_score_downgrade_reasons
            ),
        }
        for item in diagnostics
    )


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
            "latest_price": item.latest_price,
            "bias_as_of": item.bias_as_of,
            "stale_age_seconds": item.stale_age_seconds,
            "observation_count": item.observation_count,
            "recent_return_bps": item.recent_return_bps,
            "lookback_return_bps": item.lookback_return_bps,
            "impulse_direction": item.impulse_direction,
            "impulse_return_bps": item.impulse_return_bps,
            "impulse_detected": item.impulse_detected,
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
