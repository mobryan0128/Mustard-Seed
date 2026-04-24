"""Validate continuous runner lifecycle with offline fake components."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi_bot.config.settings import KalshiSettings  # noqa: E402
from kalshi_bot.contracts.contract_scanner import (  # noqa: E402
    ContractScanSnapshot,
    ScannedContract,
    SkippedContract,
)
from kalshi_bot.contracts.contract_scorer import ContractScore  # noqa: E402
from kalshi_bot.execution.execution_engine import SimulationSnapshot  # noqa: E402
from kalshi_bot.forecast.bias_engine import BiasRiskFlags, BiasSnapshot, BiasState  # noqa: E402
from kalshi_bot.market.market_state_cache import MarketStateSnapshot, TickerState  # noqa: E402
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
    if result.status.ranked_contract_count != 1:
        failures.append(f"single-cycle ranked={result.status.ranked_contract_count}")
    if result.status.skipped_contract_count != 2:
        failures.append(f"single-cycle skipped={result.status.skipped_contract_count}")
    skip_reasons = tuple((item.reason, item.count) for item in result.status.top_skip_reasons)
    if skip_reasons != (("missing_best_quote", 1), ("missing_bias_state", 1)):
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
    if eth_bias is None or eth_bias.state_present:
        failures.append(f"single-cycle ETH-USD bias diagnostic={eth_bias}")
    markets = {
        (item.product_id, item.market_ticker): item
        for item in result.status.mapped_market_diagnostics
    }
    if not _market_diagnostic_matches(
        markets.get(("BTC-USD", "KXBTC-1")),
        market_ticker_present=True,
        bid_present=True,
        ask_present=True,
    ):
        failures.append(f"single-cycle KXBTC-1 diagnostic={markets.get(('BTC-USD', 'KXBTC-1'))}")
    if not _market_diagnostic_matches(
        markets.get(("BTC-USD", "KXBTC-2")),
        market_ticker_present=True,
        bid_present=True,
        ask_present=False,
    ):
        failures.append(f"single-cycle KXBTC-2 diagnostic={markets.get(('BTC-USD', 'KXBTC-2'))}")
    if not _market_diagnostic_matches(
        markets.get(("ETH-USD", "KXETH-1")),
        market_ticker_present=False,
        bid_present=False,
        ask_present=False,
    ):
        failures.append(f"single-cycle KXETH-1 diagnostic={markets.get(('ETH-USD', 'KXETH-1'))}")
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
    if state.kalshi_run_calls != 3 or state.crypto_run_calls != 3:
        failures.append(
            f"multi-cycle run calls kalshi={state.kalshi_run_calls} crypto={state.crypto_run_calls}"
        )
    if results[-1].status.cycle_count != 3:
        failures.append(f"multi-cycle final cycle_count={results[-1].status.cycle_count}")
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


def _build_runner(
    *,
    stop_after_first_cycle: bool = False,
    live_flags_present: bool = False,
    kalshi_error: str | None = None,
    fail_fast_on_startup: bool = True,
):
    temp_dir = TemporaryDirectory()
    tmp_path = Path(temp_dir.name)
    state = _FixtureState(temp_dir=temp_dir)
    logger = StructuredLogger(log_directory=tmp_path / "logs", enabled=True)
    replay_engine = ReplayEngine(replay_directory=tmp_path / "replay", enabled=True)
    runner = KalshiBotRunner(
        settings=_settings(
            tmp_path,
            live_flags_present=live_flags_present,
            fail_fast_on_startup=fail_fast_on_startup,
        ),
        market_state_cache=_FakeMarketStateCache(),
        kalshi_ws_client=_FakeKalshiClient(state=state, error=kalshi_error),
        crypto_feed_client=_FakeCryptoFeedClient(state=state),
        bias_engine=_FakeBiasEngine(),
        contract_scanner=_FakeContractScanner(),
        simulation_engine=_FakeSimulationEngine(stop_after_first_cycle=stop_after_first_cycle, runner_ref=None),
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
        ws_market_tickers=("KXBTC-1", "KXBTC-2", "KXETH-1"),
        ws_message_limit=1,
        ws_receive_timeout_seconds=30.0,
        ws_max_reconnect_attempts=1,
        ws_reconnect_initial_delay_seconds=1.0,
        ws_reconnect_max_delay_seconds=1.0,
        crypto_feed_ws_url="wss://advanced-trade-ws.coinbase.com",
        crypto_feed_products=("BTC-USD",),
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
        bias_products=("BTC-USD",),
        bias_lookback_seconds=1800,
        bias_recent_window_seconds=60,
        bias_min_samples=20,
        bias_stale_data_seconds=15,
        bias_chop_threshold_bps=10,
        contract_scanner_product_markets={
            "BTC-USD": ("KXBTC-1", "KXBTC-2"),
            "ETH-USD": ("KXETH-1",),
        },
        simulation_enabled=True,
        simulation_max_new_positions_per_evaluation=1,
        simulation_position_id_prefix="sim",
        simulation_exit_enabled=True,
        simulation_allow_same_pass_reentry=False,
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
    def __init__(self, *, state: "_FixtureState", error: str | None = None) -> None:
        self._state = state
        self._error = error

    async def run(self, *, market_tickers, message_limit):  # noqa: ANN001
        self._state.kalshi_run_calls += 1
        if self._error is not None:
            raise RuntimeError(self._error)
        return _RunResult(messages_received=message_limit)


class _FakeCryptoFeedClient:
    def __init__(self, *, state: "_FixtureState") -> None:
        self._state = state

    async def run(self, *, message_limit):  # noqa: ANN001
        self._state.crypto_run_calls += 1
        return _RunResult(messages_received=message_limit)

    def snapshot(self):
        return _FakeCryptoSnapshot()


class _FakeMarketStateCache:
    def snapshot(self) -> MarketStateSnapshot:
        return MarketStateSnapshot(
            tickers={
                "KXBTC-1": TickerState(
                    market_ticker="KXBTC-1",
                    yes_bid_dollars=Decimal("0.44"),
                    yes_ask_dollars=Decimal("0.48"),
                    yes_bid_size_fp=Decimal("100"),
                    yes_ask_size_fp=Decimal("100"),
                    dollar_volume=Decimal("1000"),
                    exchange_time="2026-04-23T12:00:03+00:00",
                ),
                "KXBTC-2": TickerState(
                    market_ticker="KXBTC-2",
                    yes_bid_dollars=Decimal("0.39"),
                    yes_ask_dollars=None,
                    yes_bid_size_fp=Decimal("100"),
                    yes_ask_size_fp=None,
                    dollar_volume=Decimal("1000"),
                    exchange_time="2026-04-23T12:00:03+00:00",
                ),
            },
            orderbooks={},
            last_sequence_by_sid={},
        )


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
                )
            }
        )


class _FakeContractScanner:
    def scan(self, *, bias_snapshot, market_snapshot):  # noqa: ANN001
        return ContractScanSnapshot(
            ranked_contracts=(
                ScannedContract(
                    product_id="BTC-USD",
                    market_ticker="KXBTC-1",
                    direction="up",
                    structure="trend",
                    confidence=70,
                    best_bid=Decimal("0.44"),
                    best_ask=Decimal("0.48"),
                    midpoint=Decimal("0.46"),
                    bias_as_of="2026-04-23T12:00:00+00:00",
                    market_as_of="2026-04-23T12:00:03+00:00",
                    score=ContractScore(
                        confidence=70,
                        spread_width=Decimal("0.04"),
                        top_of_book_liquidity=Decimal("200"),
                        dollar_volume=Decimal("1000"),
                    ),
                ),
            ),
            skipped_contracts=(
                SkippedContract(
                    product_id="BTC-USD",
                    market_ticker="KXBTC-2",
                    reason="missing_best_quote",
                ),
                SkippedContract(
                    product_id="ETH-USD",
                    market_ticker="KXETH-1",
                    reason="missing_bias_state",
                ),
            ),
        )


class _FakeSimulationEngine:
    def __init__(self, *, stop_after_first_cycle: bool, runner_ref) -> None:  # noqa: ANN001
        self._cycle = 0
        self._runner_ref = runner_ref
        self._stop_after_first_cycle = stop_after_first_cycle
        self._latest = SimulationSnapshot(
            open_positions={},
            closed_positions=(),
            decisions=(),
            evaluation_count=0,
        )

    def evaluate(self, scan_snapshot):  # noqa: ANN001
        self._cycle += 1
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


@dataclass(frozen=True)
class _RunResult:
    messages_received: int


class _FakeCryptoSnapshot:
    def __init__(self) -> None:
        self.products = {"BTC-USD": object()}


class _FixtureState:
    def __init__(self, *, temp_dir: TemporaryDirectory) -> None:
        self._temp_dir = temp_dir
        self.kalshi_run_calls = 0
        self.crypto_run_calls = 0
        self.log_written_ref: Path | None = None
        self.replay_written_ref: Path | None = None

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


if __name__ == "__main__":
    raise SystemExit(main())
