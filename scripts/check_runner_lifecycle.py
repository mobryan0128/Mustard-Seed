"""Validate continuous runner lifecycle with offline fake components."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi_bot.config.settings import KalshiSettings  # noqa: E402
from kalshi_bot.clients.kalshi_client import KalshiMarketPage, KalshiMarketSummary  # noqa: E402
from kalshi_bot.execution.execution_engine import (  # noqa: E402
    SimulatedPosition,
    SimulationDecision,
    SimulationSnapshot,
)
from kalshi_bot.execution.exit_manager import ClosedSimulatedPosition  # noqa: E402
from kalshi_bot.forecast.bias_engine import BiasRiskFlags, BiasSnapshot, BiasState  # noqa: E402
from kalshi_bot.market.crypto_market_discovery import (  # noqa: E402
    CryptoMarketDiscovery,
    CryptoMarketDiscoverySnapshot,
    DiscoveredCryptoMarket,
)
from kalshi_bot.market.market_state_cache import MarketStateCache  # noqa: E402
from kalshi_bot.observability.logger import StructuredLogger  # noqa: E402
from kalshi_bot.observability.replay_engine import ReplayEngine  # noqa: E402
from kalshi_bot.runner.orchestrator import KalshiBotRunner, RunnerError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate runner lifecycle with offline fixtures.")
    parser.parse_args()

    failures: list[str] = []
    failures.extend(_validate_single_cycle())
    failures.extend(_validate_multiple_cycles())
    failures.extend(_validate_clean_stop())
    failures.extend(_validate_live_flags_do_not_enable_live_actions())
    failures.extend(_validate_startup_fail_closed())
    failures.extend(_validate_market_discovery_tradable_filter())
    failures.extend(_validate_subscription_ack_without_market_data_is_not_connected())
    failures.extend(_validate_simulation_trade_events_persisted())

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1

    print("Runner lifecycle offline fixtures succeeded.")
    return 0


def _validate_single_cycle() -> list[str]:
    runner, state = _build_runner()
    results = runner.run_cycles(1)
    failures: list[str] = []
    if len(results) != 1:
        failures.append(f"single-cycle count={len(results)}")
        return failures
    result = results[0]
    if result.cycle_number != 1:
        failures.append(f"single-cycle number={result.cycle_number}")
    if result.status.mode != "simulation":
        failures.append(f"single-cycle mode={result.status.mode}")
    if not result.status.kalshi_feed_connected or not result.status.crypto_feed_connected:
        failures.append("single-cycle feed status did not report connected")
    if result.status.kalshi_market_data_message_count != 1:
        failures.append(
            f"single-cycle market data messages={result.status.kalshi_market_data_message_count}"
        )
    if result.status.kalshi_subscribed_market_tickers != ("KXBTC15M-OLD",):
        failures.append(
            f"single-cycle ws requested={result.status.kalshi_subscribed_market_tickers}"
        )
    if result.status.ranked_contract_count != 1:
        failures.append(f"single-cycle ranked={result.status.ranked_contract_count}")
    if result.status.active_market_tickers != ("KXBTC15M-OLD",):
        failures.append(f"single-cycle active tickers={result.status.active_market_tickers}")
    if result.status.last_market_discovery_cycle != 1:
        failures.append(f"single-cycle discovery cycle={result.status.last_market_discovery_cycle}")
    if result.status.skipped_contract_count != 0:
        failures.append(f"single-cycle skipped={result.status.skipped_contract_count}")
    skip_reasons = tuple((item.reason, item.count) for item in result.status.top_skip_reasons)
    if skip_reasons != ():
        failures.append(f"single-cycle skip reasons={skip_reasons}")
    bias_by_product = {item.product_id: item for item in result.status.bias_diagnostics}
    btc_bias = bias_by_product.get("BTC-USD")
    eth_bias = bias_by_product.get("ETH-USD")
    if btc_bias is None or not btc_bias.state_present:
        failures.append("single-cycle BTC-USD bias diagnostic missing")
    elif (
        btc_bias.direction != "up"
        or btc_bias.confidence != 70
        or btc_bias.structure != "trend"
        or dict(btc_bias.risk_flags).get("stale_data")
    ):
        failures.append(f"single-cycle BTC-USD bias diagnostic={btc_bias}")
    if eth_bias is None or not eth_bias.state_present:
        failures.append(f"single-cycle ETH-USD bias diagnostic={eth_bias}")
    markets = {
        (item.product_id, item.market_ticker): item
        for item in result.status.mapped_market_diagnostics
    }
    if not _market_diagnostic_matches(
        markets.get(("BTC-USD", "KXBTC15M-OLD")),
        market_ticker_present=True,
        bid_present=True,
        ask_present=True,
    ):
        failures.append(
            f"single-cycle KXBTC15M-OLD diagnostic={markets.get(('BTC-USD', 'KXBTC15M-OLD'))}"
        )
    if state.discovery_calls != 1:
        failures.append(f"single-cycle discovery calls={state.discovery_calls}")
    if state.kalshi_run_calls != 1 or state.crypto_run_calls != 1:
        failures.append(
            f"single-cycle run calls kalshi={state.kalshi_run_calls} crypto={state.crypto_run_calls}"
        )
    if not state.log_written or not state.replay_written:
        failures.append("single-cycle did not write log/replay artifacts")
    return failures


def _validate_multiple_cycles() -> list[str]:
    runner, state = _build_runner()
    results = runner.run_cycles(3)
    failures: list[str] = []
    if len(results) != 3:
        failures.append(f"multi-cycle count={len(results)}")
        return failures
    if state.kalshi_run_calls != 3 or state.crypto_run_calls != 3:
        failures.append(
            f"multi-cycle run calls kalshi={state.kalshi_run_calls} crypto={state.crypto_run_calls}"
        )
    if results[-1].status.cycle_count != 3:
        failures.append(f"multi-cycle final cycle_count={results[-1].status.cycle_count}")
    if state.discovery_calls != 2:
        failures.append(f"multi-cycle discovery calls={state.discovery_calls}")
    if state.subscribed_tickers_by_call != (
        ("KXBTC15M-OLD",),
        ("KXBTC15M-OLD",),
        ("KXBTC15M-NEW", "KXETH15M-NEW"),
    ):
        failures.append(f"multi-cycle subscriptions={state.subscribed_tickers_by_call}")
    if results[1].status.active_market_tickers != ("KXBTC15M-OLD",):
        failures.append(f"multi-cycle second active={results[1].status.active_market_tickers}")
    if results[-1].status.active_market_tickers != ("KXBTC15M-NEW", "KXETH15M-NEW"):
        failures.append(f"multi-cycle final active={results[-1].status.active_market_tickers}")
    if "KXBTC15M-OLD" in state.cache.snapshot().tickers:
        failures.append("multi-cycle stale ticker was not pruned")
    return failures


def _validate_clean_stop() -> list[str]:
    runner, state = _build_runner(stop_after_first_cycle=True)
    results = runner.run_forever()
    failures: list[str] = []
    if len(results) != 1:
        failures.append(f"clean-stop count={len(results)}")
    if not runner.snapshot().stopped:
        failures.append("clean-stop runner did not report stopped state")
    if state.kalshi_run_calls != 1 or state.crypto_run_calls != 1:
        failures.append(
            f"clean-stop run calls kalshi={state.kalshi_run_calls} crypto={state.crypto_run_calls}"
        )
    return failures


def _validate_live_flags_do_not_enable_live_actions() -> list[str]:
    runner, _ = _build_runner(live_flags_present=True)
    results = runner.run_cycles(1)
    failures: list[str] = []
    if len(results) != 1:
        failures.append("live-flags fixture did not complete one cycle")
        return failures
    if not results[0].status.live_flags_present:
        failures.append("live-flags fixture did not preserve live_flags_present")
    if results[0].status.mode != "simulation":
        failures.append(f"live-flags mode={results[0].status.mode}")
    return failures


def _validate_startup_fail_closed() -> list[str]:
    runner, _ = _build_runner(kalshi_error="boom", fail_fast_on_startup=True)
    try:
        runner.run_cycles(1)
    except RunnerError:
        return []
    return ["startup failure did not fail closed"]


def _validate_market_discovery_tradable_filter() -> list[str]:
    discovery = CryptoMarketDiscovery(
        kalshi_client=_FakeDiscoveryKalshiClient(),
        product_series={"BTC-USD": ("KXBTC15M",)},
        products=("BTC-USD",),
    )
    snapshot = discovery.discover()
    failures: list[str] = []
    expected = {"BTC-USD": ("KXBTC15M-TEST",)}
    if snapshot.product_markets != expected:
        failures.append(f"tradable discovery mapping={snapshot.product_markets}")
    discovered_tickers = tuple(market.market_ticker for market in snapshot.discovered_markets)
    if discovered_tickers != ("KXBTC15M-TEST",):
        failures.append(f"tradable discovery tickers={discovered_tickers}")
    return failures


def _validate_subscription_ack_without_market_data_is_not_connected() -> list[str]:
    runner, state = _build_runner(kalshi_market_data=False)
    results = runner.run_cycles(1)
    failures: list[str] = []
    if len(results) != 1:
        failures.append(f"ack-only count={len(results)}")
        return failures
    status = results[0].status
    if status.kalshi_feed_connected:
        failures.append("ack-only fixture reported Kalshi feed connected")
    if status.tracked_market_count != 0:
        failures.append(f"ack-only tracked markets={status.tracked_market_count}")
    if status.active_market_tickers != ("KXBTC15M-OLD",):
        failures.append(f"ack-only active tickers={status.active_market_tickers}")
    if status.kalshi_market_data_message_count != 0:
        failures.append(f"ack-only data messages={status.kalshi_market_data_message_count}")
    if status.kalshi_subscription_message_count != 1:
        failures.append(
            f"ack-only subscription messages={status.kalshi_subscription_message_count}"
        )
    markets = {
        (item.product_id, item.market_ticker): item
        for item in status.mapped_market_diagnostics
    }
    if not _market_diagnostic_matches(
        markets.get(("BTC-USD", "KXBTC15M-OLD")),
        market_ticker_present=False,
        bid_present=False,
        ask_present=False,
    ):
        failures.append(
            f"ack-only KXBTC15M-OLD diagnostic={markets.get(('BTC-USD', 'KXBTC15M-OLD'))}"
        )
    if state.subscribed_tickers_by_call != (("KXBTC15M-OLD",),):
        failures.append(f"ack-only subscriptions={state.subscribed_tickers_by_call}")
    return failures


def _validate_simulation_trade_events_persisted() -> list[str]:
    runner, state = _build_runner(simulation_trade_events=True)
    results = runner.run_cycles(2)
    failures: list[str] = []
    if len(results) != 2:
        failures.append(f"simulation trade events cycle count={len(results)}")
        return failures
    if state.log_written_ref is None or state.replay_written_ref is None:
        return ["simulation trade events missing log/replay paths"]

    runtime_records = _jsonl_records(state.log_written_ref)
    replay_records = _jsonl_records(state.replay_written_ref)

    runtime_opened = _first_event_payload(
        runtime_records,
        key="event_type",
        value="simulation_position_opened",
    )
    runtime_closed = _first_event_payload(
        runtime_records,
        key="event_type",
        value="simulation_position_closed",
    )
    replay_opened = _first_event_payload(
        replay_records,
        key="record_type",
        value="simulation_position_opened",
    )
    replay_closed = _first_event_payload(
        replay_records,
        key="record_type",
        value="simulation_position_closed",
    )

    if runtime_opened is None:
        failures.append("runtime opened simulation trade event missing")
    if replay_opened is None:
        failures.append("replay opened simulation trade event missing")
    if runtime_closed is None:
        failures.append("runtime closed simulation trade event missing")
    if replay_closed is None:
        failures.append("replay closed simulation trade event missing")

    for label, payload in (
        ("runtime", runtime_closed),
        ("replay", replay_closed),
    ):
        if payload is None:
            continue
        expected = {
            "entry_price": "0.460",
            "exit_price": "0.490",
            "stake_dollars": "0.20",
            "exit_reason": "direction_conflict",
            "pnl": "0.030",
        }
        for key, value in expected.items():
            if payload.get(key) != value:
                failures.append(f"{label} closed {key}={payload.get(key)} expected={value}")
    return failures


def _build_runner(
    *,
    stop_after_first_cycle: bool = False,
    live_flags_present: bool = False,
    kalshi_error: str | None = None,
    kalshi_market_data: bool = True,
    fail_fast_on_startup: bool = True,
    simulation_trade_events: bool = False,
):
    temp_dir = TemporaryDirectory()
    tmp_path = Path(temp_dir.name)
    cache = MarketStateCache()
    state = _FixtureState(temp_dir=temp_dir, cache=cache)
    logger = StructuredLogger(log_directory=tmp_path / "logs", enabled=True)
    replay_engine = ReplayEngine(replay_directory=tmp_path / "replay", enabled=True)
    runner = KalshiBotRunner(
        settings=_settings(
            tmp_path,
            live_flags_present=live_flags_present,
            fail_fast_on_startup=fail_fast_on_startup,
        ),
        market_state_cache=cache,
        kalshi_ws_client=_FakeKalshiClient(
            state=state,
            error=kalshi_error,
            emit_market_data=kalshi_market_data,
        ),
        crypto_feed_client=_FakeCryptoFeedClient(state=state),
        bias_engine=_FakeBiasEngine(),
        contract_scanner=None,
        market_discovery=_FakeMarketDiscovery(state=state),
        simulation_engine=_FakeSimulationEngine(
            stop_after_first_cycle=stop_after_first_cycle,
            runner_ref=None,
            trade_events=simulation_trade_events,
        ),
        logger=logger,
        replay_engine=replay_engine,
        sleep_fn=lambda _: None,
    )
    runner._simulation_engine._runner_ref = runner  # type: ignore[attr-defined]
    state.log_written_ref = logger.path
    state.replay_written_ref = replay_engine.path
    return runner, state


def _settings(
    tmp_path: Path,
    *,
    live_flags_present: bool,
    fail_fast_on_startup: bool,
) -> KalshiSettings:
    return KalshiSettings(
        env="demo",
        api_base_url="https://demo-api.kalshi.co/trade-api/v2",
        ws_url="wss://demo-api.kalshi.co/trade-api/ws/v2",
        api_key_id="demo-key",
        private_key_pem="pem",
        private_key_path=None,
        private_key_passphrase=None,
        request_timeout_seconds=10.0,
        ws_market_tickers=(),
        ws_message_limit=1,
        ws_receive_timeout_seconds=30.0,
        ws_max_reconnect_attempts=1,
        ws_reconnect_initial_delay_seconds=1.0,
        ws_reconnect_max_delay_seconds=1.0,
        crypto_feed_ws_url="wss://advanced-trade-ws.coinbase.com",
        crypto_feed_products=("BTC-USD", "ETH-USD"),
        crypto_feed_message_limit=1,
        crypto_feed_receive_timeout_seconds=30.0,
        crypto_feed_max_reconnect_attempts=1,
        crypto_feed_reconnect_initial_delay_seconds=1.0,
        crypto_feed_reconnect_max_delay_seconds=1.0,
        log_directory=tmp_path / "logs",
        log_jsonl_enabled=True,
        replay_directory=tmp_path / "replay",
        replay_write_enabled=True,
        time_sync_max_drift_ms=1500,
        time_sync_log_results=True,
        bias_products=("BTC-USD", "ETH-USD"),
        bias_lookback_seconds=1800,
        bias_recent_window_seconds=60,
        bias_min_samples=20,
        bias_stale_data_seconds=15,
        bias_chop_threshold_bps=10,
        contract_scanner_product_markets={},
        auto_market_discovery_enabled=True,
        crypto_market_series={
            "BTC-USD": ("KXBTC15M", "KXBTC30M"),
            "ETH-USD": ("KXETH15M", "KXETH30M"),
        },
        market_discovery_refresh_cycles=2,
        simulation_enabled=True,
        simulation_max_new_positions_per_evaluation=1,
        simulation_position_id_prefix="sim",
        simulation_exit_enabled=True,
        simulation_allow_same_pass_reentry=False,
        risk_account_balance_dollars=Decimal("10"),
        risk_min_percent_per_trade=Decimal("0.01"),
        risk_max_percent_per_trade=Decimal("0.03"),
        risk_min_stake_dollars=Decimal("0.10"),
        risk_max_stake_dollars=Decimal("3"),
        risk_max_open_positions=2,
        risk_max_total_exposure_dollars=Decimal("10"),
        risk_daily_loss_limit_dollars=Decimal("5"),
        risk_kill_switch_active=False,
        live_validation_enabled=live_flags_present,
        live_validation_env="prod" if live_flags_present else "demo",
        live_validation_ticker=None,
        live_validation_action=None,
        live_validation_side=None,
        live_validation_count=1,
        live_validation_price_dollars=None,
        live_validation_time_in_force="immediate_or_cancel",
        live_validation_poll_attempts=1,
        live_validation_poll_interval_seconds=1.0,
        live_validation_client_order_id_prefix="live-smoke",
        live_trading_enabled=live_flags_present,
        live_kill_switch_active=False,
        runner_enabled=True,
        runner_loop_interval_seconds=0.001,
        runner_status_log_every_n_cycles=1,
        runner_fail_fast_on_startup=fail_fast_on_startup,
        runner_max_cycles=None,
    )


class _FakeKalshiClient:
    def __init__(
        self,
        *,
        state: "_FixtureState",
        error: str | None = None,
        emit_market_data: bool = True,
    ) -> None:
        self._state = state
        self._error = error
        self._emit_market_data = emit_market_data

    async def run(self, *, market_tickers, message_limit):  # noqa: ANN001
        self._state.kalshi_run_calls += 1
        subscribed_tickers = tuple(dict.fromkeys(market_tickers))
        self._state.subscribed_tickers.append(subscribed_tickers)
        if self._error is not None:
            raise RuntimeError(self._error)
        if self._emit_market_data:
            for index, market_ticker in enumerate(subscribed_tickers, start=1):
                self._state.cache.replace_orderbook(
                    market_ticker=market_ticker,
                    yes_levels=(("0.44", "100"),),
                    no_levels=(("0.52", "100"),),
                    sid=1,
                    seq=index,
                )
            return _RunResult(
                messages_received=message_limit + 1,
                market_data_messages=message_limit,
                subscription_messages=1,
                subscribed_market_tickers=subscribed_tickers,
            )
        return _RunResult(
            messages_received=1,
            market_data_messages=0,
            subscription_messages=1,
            timed_out=True,
            subscribed_market_tickers=subscribed_tickers,
        )


class _FakeCryptoFeedClient:
    def __init__(self, *, state: "_FixtureState") -> None:
        self._state = state

    async def run(self, *, message_limit):  # noqa: ANN001
        self._state.crypto_run_calls += 1
        return _RunResult(messages_received=message_limit)

    def snapshot(self):
        return _FakeCryptoSnapshot()


class _FakeBiasEngine:
    def snapshot(self):
        return BiasSnapshot(products={})

    def ingest(self, snapshot):  # noqa: ANN001
        return BiasSnapshot(
            products={
                "BTC-USD": BiasState(
                    product_id="BTC-USD",
                    direction="up",
                    confidence=70,
                    structure="trend",
                    risk_flags=BiasRiskFlags(
                        insufficient_history=False,
                        stale_data=False,
                        time_sync_failed=False,
                    ),
                    latest_price=Decimal("70000"),
                    lookback_return_bps=Decimal("100"),
                    recent_return_bps=Decimal("20"),
                    observation_count=25,
                    as_of="2026-04-23T12:00:00+00:00",
                ),
                "ETH-USD": BiasState(
                    product_id="ETH-USD",
                    direction="up",
                    confidence=70,
                    structure="trend",
                    risk_flags=BiasRiskFlags(
                        insufficient_history=False,
                        stale_data=False,
                        time_sync_failed=False,
                    ),
                    latest_price=Decimal("2000"),
                    lookback_return_bps=Decimal("100"),
                    recent_return_bps=Decimal("20"),
                    observation_count=25,
                    as_of="2026-04-23T12:00:00+00:00",
                ),
            }
        )


class _FakeMarketDiscovery:
    def __init__(self, *, state: "_FixtureState") -> None:
        self._state = state

    def discover(self) -> CryptoMarketDiscoverySnapshot:
        self._state.discovery_calls += 1
        if self._state.discovery_calls == 1:
            return _discovery_snapshot(
                {"BTC-USD": ("KXBTC15M-OLD",)},
                close_time="2026-04-23T12:15:00+00:00",
            )
        return _discovery_snapshot(
            {
                "BTC-USD": ("KXBTC15M-NEW",),
                "ETH-USD": ("KXETH15M-NEW",),
            },
            close_time="2026-04-23T12:30:00+00:00",
        )


class _FakeSimulationEngine:
    def __init__(
        self,
        *,
        stop_after_first_cycle: bool,
        runner_ref,  # noqa: ANN001
        trade_events: bool,
    ) -> None:
        self._cycle = 0
        self._runner_ref = runner_ref
        self._stop_after_first_cycle = stop_after_first_cycle
        self._trade_events = trade_events
        self._latest = SimulationSnapshot(
            open_positions={},
            closed_positions=(),
            decisions=(),
            evaluation_count=0,
        )

    def evaluate(self, scan_snapshot):  # noqa: ANN001
        self._cycle += 1
        if self._trade_events:
            self._latest = self._trade_event_snapshot()
        else:
            self._latest = SimulationSnapshot(
                open_positions={"sim-0001": object()} if self._cycle >= 1 else {},
                closed_positions=(),
                decisions=(),
                evaluation_count=self._cycle,
            )
        if self._stop_after_first_cycle and self._cycle == 1 and self._runner_ref is not None:
            self._runner_ref.stop()
        return self._latest

    def snapshot(self) -> SimulationSnapshot:
        return self._latest

    def _trade_event_snapshot(self) -> SimulationSnapshot:
        opened = SimulatedPosition(
            position_id="sim-0001",
            product_id="BTC-USD",
            market_ticker="KXBTC15M-OLD",
            direction="up",
            structure="trend",
            confidence=70,
            entry_price=Decimal("0.460"),
            latest_price=Decimal("0.460"),
            stake_dollars=Decimal("0.20"),
            status="open",
            opened_at="2026-04-23T12:00:03+00:00",
            updated_at="2026-04-23T12:00:03+00:00",
            update_count=0,
        )
        if self._cycle == 1:
            return SimulationSnapshot(
                open_positions={opened.position_id: opened},
                closed_positions=(),
                decisions=(
                    SimulationDecision(
                        action="open_position",
                        position_id=opened.position_id,
                        product_id=opened.product_id,
                        market_ticker=opened.market_ticker,
                        reason=None,
                    ),
                ),
                evaluation_count=self._cycle,
            )

        closed = ClosedSimulatedPosition(
            position_id=opened.position_id,
            product_id=opened.product_id,
            market_ticker=opened.market_ticker,
            direction=opened.direction,
            structure=opened.structure,
            confidence=opened.confidence,
            entry_price=opened.entry_price,
            exit_price=Decimal("0.490"),
            stake_dollars=opened.stake_dollars,
            status="closed",
            opened_at=opened.opened_at,
            closed_at="2026-04-23T12:01:03+00:00",
            updated_at=opened.updated_at,
            update_count=opened.update_count,
            exit_reason="direction_conflict",
        )
        return SimulationSnapshot(
            open_positions={},
            closed_positions=(closed,),
            decisions=(
                SimulationDecision(
                    action="close_position",
                    position_id=closed.position_id,
                    product_id=closed.product_id,
                    market_ticker=closed.market_ticker,
                    reason=closed.exit_reason,
                ),
            ),
            evaluation_count=self._cycle,
        )


@dataclass(frozen=True)
class _RunResult:
    messages_received: int
    market_data_messages: int = 0
    subscription_messages: int = 0
    timed_out: bool = False
    subscribed_market_tickers: tuple[str, ...] = ()


class _FakeDiscoveryKalshiClient:
    def get_markets(self, **kwargs):  # noqa: ANN003
        now = datetime.now(timezone.utc)
        return KalshiMarketPage(
            markets=(
                _market_summary(
                    ticker="KXBTC15M-TEST",
                    status="active",
                    open_time=_iso(now - timedelta(minutes=5)),
                    close_time=_iso(now + timedelta(minutes=5)),
                    expiration_time=_iso(now + timedelta(minutes=5)),
                ),
                _market_summary(
                    ticker="KXBTC15M-EXPIRED",
                    status="active",
                    open_time=_iso(now - timedelta(minutes=20)),
                    close_time=_iso(now - timedelta(minutes=5)),
                    expiration_time=_iso(now - timedelta(minutes=5)),
                ),
            ),
            cursor=None,
        )


class _FakeCryptoSnapshot:
    def __init__(self) -> None:
        self.products = {"BTC-USD": object(), "ETH-USD": object()}


class _FixtureState:
    def __init__(self, *, temp_dir: TemporaryDirectory, cache: MarketStateCache) -> None:
        self._temp_dir = temp_dir
        self.cache = cache
        self.kalshi_run_calls = 0
        self.crypto_run_calls = 0
        self.discovery_calls = 0
        self.subscribed_tickers: list[tuple[str, ...]] = []
        self.log_written_ref: Path | None = None
        self.replay_written_ref: Path | None = None

    @property
    def subscribed_tickers_by_call(self) -> tuple[tuple[str, ...], ...]:
        return tuple(self.subscribed_tickers)

    @property
    def log_written(self) -> bool:
        return self.log_written_ref is not None and self.log_written_ref.exists()

    @property
    def replay_written(self) -> bool:
        return self.replay_written_ref is not None and self.replay_written_ref.exists()


def _market_diagnostic_matches(
    diagnostic,  # noqa: ANN001
    *,
    market_ticker_present: bool,
    bid_present: bool,
    ask_present: bool,
) -> bool:
    return (
        diagnostic is not None
        and diagnostic.market_ticker_present is market_ticker_present
        and diagnostic.bid_present is bid_present
        and diagnostic.ask_present is ask_present
    )


def _jsonl_records(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _first_event_payload(
    records: list[dict[str, object]],
    *,
    key: str,
    value: str,
) -> dict[str, object] | None:
    for record in records:
        if record.get(key) != value:
            continue
        payload = record.get("payload")
        if isinstance(payload, dict):
            return payload
    return None


def _discovery_snapshot(
    product_markets: dict[str, tuple[str, ...]],
    *,
    close_time: str,
) -> CryptoMarketDiscoverySnapshot:
    discovered = tuple(
        DiscoveredCryptoMarket(
            product_id=product_id,
            series_ticker=market_ticker.split("-", 1)[0],
            market_ticker=market_ticker,
            close_time=close_time,
            open_time="2026-04-23T12:00:00+00:00",
            expiration_time=close_time,
        )
        for product_id, market_tickers in product_markets.items()
        for market_ticker in market_tickers
    )
    return CryptoMarketDiscoverySnapshot(
        product_markets=product_markets,
        discovered_markets=discovered,
    )


def _market_summary(
    *,
    ticker: str,
    status: str | None,
    open_time: str,
    close_time: str,
    expiration_time: str,
) -> KalshiMarketSummary:
    return KalshiMarketSummary(
        ticker=ticker,
        event_ticker=None,
        status=status,
        open_time=open_time,
        close_time=close_time,
        expiration_time=expiration_time,
        latest_expiration_time=expiration_time,
        yes_bid_dollars=Decimal("0.44"),
        yes_ask_dollars=Decimal("0.48"),
    )


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
