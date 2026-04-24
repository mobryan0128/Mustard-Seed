"""Supervised CLI entrypoint for the continuous simulation-first runner."""

from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi_bot.config.settings import SettingsError, load_settings  # noqa: E402
from kalshi_bot.runner.orchestrator import KalshiBotRunner, RunnerError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the continuous Kalshi bot orchestrator.")
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Environment file to load. Defaults to .env.",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="Run a bounded number of cycles instead of continuous mode.",
    )
    args = parser.parse_args()

    try:
        settings = load_settings(args.env_file)
        runner = KalshiBotRunner.from_settings(settings)
    except (SettingsError, RunnerError) as exc:
        print(f"Runner startup failed: {exc}", file=sys.stderr)
        return 1

    _install_signal_handlers(runner)

    if settings.live_validation_enabled or settings.live_trading_enabled:
        print("Runner note: live flags are present, but the continuous runner remains simulation-only.")

    try:
        results = runner.run_cycles(args.max_cycles) if args.max_cycles else runner.run_forever()
    except RunnerError as exc:
        print(f"Runner failed closed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        runner.stop()
        print("Runner interrupted. Shutting down cleanly.")
        return 130

    for result in results:
        print(
            "cycle="
            f"{result.cycle_number} "
            f"markets={result.status.tracked_market_count} "
            f"products={result.status.tracked_crypto_product_count} "
            f"ranked={result.status.ranked_contract_count} "
            f"skipped={result.status.skipped_contract_count} "
            f"skip_reasons={_format_skip_reasons(result.status.top_skip_reasons)} "
            f"bias={_format_bias_diagnostics(result.status.bias_diagnostics)} "
            f"mapped_markets={_format_mapped_market_diagnostics(result.status.mapped_market_diagnostics)} "
            f"open_positions={result.status.open_position_count} "
            f"closed_positions={result.status.closed_position_count} "
            f"kalshi_feed_connected={result.status.kalshi_feed_connected} "
            f"crypto_feed_connected={result.status.crypto_feed_connected}"
        )
    return 0


def _install_signal_handlers(runner: KalshiBotRunner) -> None:
    def _handle_signal(signum, frame) -> None:  # noqa: ANN001,ARG001
        runner.stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)


def _format_skip_reasons(skip_reasons) -> str:  # noqa: ANN001
    if not skip_reasons:
        return "none"
    return ",".join(f"{item.reason}:{item.count}" for item in skip_reasons)


def _format_bias_diagnostics(bias_diagnostics) -> str:  # noqa: ANN001
    if not bias_diagnostics:
        return "none"
    return ";".join(
        (
            f"{item.product_id}:present={item.state_present},"
            f"direction={_none_text(item.direction)},"
            f"confidence={_none_text(item.confidence)},"
            f"structure={_none_text(item.structure)},"
            f"risk_flags={_format_risk_flags(item.risk_flags)}"
        )
        for item in bias_diagnostics
    )


def _format_mapped_market_diagnostics(mapped_market_diagnostics) -> str:  # noqa: ANN001
    if not mapped_market_diagnostics:
        return "none"
    return ";".join(
        (
            f"{item.product_id}:{item.market_ticker}:"
            f"present={item.market_ticker_present},"
            f"bid={item.bid_present},"
            f"ask={item.ask_present}"
        )
        for item in mapped_market_diagnostics
    )


def _format_risk_flags(risk_flags) -> str:  # noqa: ANN001
    if not risk_flags:
        return "none"
    return ",".join(f"{name}={value}" for name, value in risk_flags)


def _none_text(value) -> str:  # noqa: ANN001
    if value is None:
        return "none"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
