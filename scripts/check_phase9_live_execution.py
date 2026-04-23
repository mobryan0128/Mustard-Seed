"""Validate Phase 9 live execution plumbing with offline fixtures or a live smoke path."""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi_bot.clients.kalshi_client import (  # noqa: E402
    KalshiClientError,
    KalshiOrderSummary,
    _normalize_order_payload,
)
from kalshi_bot.config.settings import SettingsError, load_settings  # noqa: E402
from kalshi_bot.execution.execution_engine import (  # noqa: E402
    LiveExecutionSmokeError,
    LiveExecutionSmokeTester,
    LiveValidationOrder,
)
from kalshi_bot.observability.logger import StructuredLogger  # noqa: E402
from kalshi_bot.observability.replay_engine import ReplayEngine  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Phase 9 live execution plumbing.")
    parser.add_argument(
        "--env-file",
        default=".env.example",
        help="Environment file used to load Phase 9 settings. Defaults to .env.example.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run the actual live execution smoke path instead of offline fixtures.",
    )
    args = parser.parse_args()

    if args.live:
        return _run_live(args.env_file)
    return _run_offline()


def _run_offline() -> int:
    failures: list[str] = []
    failures.extend(_validate_order_normalization())
    failures.extend(_validate_settings_gating())
    failures.extend(_validate_filled_flow())
    failures.extend(_validate_rejected_flow())
    failures.extend(_validate_unknown_final_state())

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1

    print("Phase 9 live execution offline fixtures succeeded.")
    return 0


def _validate_order_normalization() -> list[str]:
    failures: list[str] = []
    created_order = _normalize_order_payload(
        {
            "order_id": "ord-created",
            "client_order_id": "client-created",
            "ticker": "KXBTC-1",
            "side": "yes",
            "action": "buy",
            "type": "limit",
            "status": "resting",
            "yes_price_dollars": "0.0100",
            "fill_count_fp": "0.00",
            "remaining_count_fp": "1.00",
            "initial_count_fp": "1.00",
            "created_time": "2026-04-23T12:00:00Z",
            "last_update_time": "2026-04-23T12:00:01Z",
        }
    )
    if created_order.yes_price_dollars != Decimal("0.0100"):
        failures.append("create-order normalization did not preserve price_dollars")
    if created_order.initial_count_fp != Decimal("1.00"):
        failures.append("create-order normalization did not preserve initial_count_fp")

    polled_order = _normalize_order_payload(
        {
            "order_id": "ord-polled",
            "client_order_id": "client-polled",
            "ticker": "KXBTC-1",
            "side": "yes",
            "action": "buy",
            "type": "limit",
            "status": "executed",
            "yes_price_dollars": "0.0100",
            "fill_count_fp": "1.00",
            "remaining_count_fp": "0.00",
            "initial_count_fp": "1.00",
            "created_time": "2026-04-23T12:00:00Z",
            "last_update_time": "2026-04-23T12:00:02Z",
        }
    )
    if polled_order.status != "executed" or polled_order.fill_count_fp != Decimal("1.00"):
        failures.append("get-order normalization did not preserve execution state")
    return failures


def _validate_settings_gating() -> list[str]:
    failures: list[str] = []
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        missing_price_env = tmp_path / "missing_price.env"
        missing_price_env.write_text(
            _env_text(
                live_validation_enabled="true",
                live_validation_ticker="KXBTC-1",
                live_validation_action="buy",
                live_validation_side="yes",
            ),
            encoding="utf-8",
        )
        try:
            load_settings(missing_price_env)
            failures.append("settings gating allowed missing LIVE_VALIDATION_PRICE_DOLLARS")
        except SettingsError:
            pass

        forced_ioc_env = tmp_path / "forced_ioc.env"
        forced_ioc_env.write_text(
            _env_text(
                live_validation_enabled="true",
                live_validation_ticker="KXBTC-1",
                live_validation_action="buy",
                live_validation_side="yes",
                live_validation_price_dollars="0.0100",
                live_validation_time_in_force="fill_or_kill",
            ),
            encoding="utf-8",
        )
        settings = load_settings(forced_ioc_env)
        if settings.live_validation_time_in_force != "immediate_or_cancel":
            failures.append("settings did not force IOC time_in_force")
    return failures


def _validate_filled_flow() -> list[str]:
    created_order = _order_summary(
        order_id="ord-filled",
        client_order_id="live-filled",
        status="resting",
        fill_count_fp="0.00",
        remaining_count_fp="1.00",
        initial_count_fp="1.00",
    )
    executed_order = _order_summary(
        order_id="ord-filled",
        client_order_id="live-filled",
        status="executed",
        fill_count_fp="1.00",
        remaining_count_fp="0.00",
        initial_count_fp="1.00",
    )
    snapshot, logger_written, replay_written = _run_fake_smoke(
        fake_client=_FakeKalshiClient(
            created_order=created_order,
            polled_orders=[created_order, executed_order],
            balance_payload={"balance": "10.00"},
        ),
        order=_validation_order("live-filled"),
        poll_attempts=3,
    )

    failures: list[str] = []
    if snapshot.result.classification != "filled":
        failures.append(f"filled flow classification={snapshot.result.classification}")
    if not snapshot.result.order_placed:
        failures.append("filled flow did not mark order_placed")
    if snapshot.result.poll_attempts_used != 2:
        failures.append(f"filled flow poll_attempts={snapshot.result.poll_attempts_used}")
    if not snapshot.result.balance_fetched:
        failures.append("filled flow did not fetch balance")
    if not logger_written or not replay_written:
        failures.append("filled flow did not write log/replay artifacts")
    return failures


def _validate_rejected_flow() -> list[str]:
    snapshot, _, _ = _run_fake_smoke(
        fake_client=_FakeKalshiClient(
            create_error=KalshiClientError("Kalshi request failed with status 409."),
            balance_payload={"balance": "10.00"},
        ),
        order=_validation_order("live-rejected"),
        poll_attempts=2,
    )
    failures: list[str] = []
    if snapshot.result.classification != "rejected":
        failures.append(f"rejected flow classification={snapshot.result.classification}")
    if snapshot.result.order_placed:
        failures.append("rejected flow marked order_placed")
    if snapshot.result.error_message is None:
        failures.append("rejected flow did not preserve error message")
    if not snapshot.result.balance_fetched:
        failures.append("rejected flow did not fetch balance")
    return failures


def _validate_unknown_final_state() -> list[str]:
    resting_order = _order_summary(
        order_id="ord-resting",
        client_order_id="live-unknown",
        status="resting",
        fill_count_fp="0.00",
        remaining_count_fp="1.00",
        initial_count_fp="1.00",
    )
    snapshot, _, _ = _run_fake_smoke(
        fake_client=_FakeKalshiClient(
            created_order=resting_order,
            polled_orders=[resting_order, resting_order, resting_order],
            balance_payload={"balance": "10.00"},
        ),
        order=_validation_order("live-unknown"),
        poll_attempts=3,
    )
    failures: list[str] = []
    if snapshot.result.classification != "unknown_final_state":
        failures.append(
            f"unknown-final-state classification={snapshot.result.classification}"
        )
    if snapshot.result.poll_attempts_used != 3:
        failures.append(
            f"unknown-final-state poll_attempts={snapshot.result.poll_attempts_used}"
        )
    return failures


def _run_fake_smoke(
    *,
    fake_client: "_FakeKalshiClient",
    order: LiveValidationOrder,
    poll_attempts: int,
):
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        logger = StructuredLogger(log_directory=tmp_path / "logs", enabled=True)
        replay_engine = ReplayEngine(replay_directory=tmp_path / "replay", enabled=True)
        tester = LiveExecutionSmokeTester(
            client=fake_client,
            logger=logger,
            replay_engine=replay_engine,
            order=order,
            poll_attempts=poll_attempts,
            poll_interval_seconds=0.001,
            sleep_fn=lambda _: None,
        )
        snapshot = tester.run()
        return snapshot, logger.path.exists(), replay_engine.path.exists()


def _run_live(env_file: str) -> int:
    try:
        settings = load_settings(env_file)
        tester = LiveExecutionSmokeTester.from_settings(settings)
    except (SettingsError, LiveExecutionSmokeError) as exc:
        print(f"Phase 9 live execution check failed: {exc}", file=sys.stderr)
        return 1

    print("Phase 9 live execution preflight:")
    print(f"env={settings.env}")
    print(f"ticker={settings.live_validation_ticker}")
    print(f"action={settings.live_validation_action}")
    print(f"side={settings.live_validation_side}")
    print(f"count={settings.live_validation_count}")
    print(f"price_dollars={settings.live_validation_price_dollars}")

    snapshot = tester.run()
    print("Phase 9 live execution smoke completed.")
    print(f"order_placed={snapshot.result.order_placed}")
    print(f"order_id_present={snapshot.result.order_id is not None}")
    print(f"final_status_classification={snapshot.result.classification}")
    print(f"poll_attempts_used={snapshot.result.poll_attempts_used}")
    print(f"balance_fetched={snapshot.result.balance_fetched}")
    return 0


def _validation_order(client_order_id: str) -> LiveValidationOrder:
    return LiveValidationOrder(
        ticker="KXBTC-1",
        action="buy",
        side="yes",
        count=1,
        price_dollars=Decimal("0.0100"),
        time_in_force="immediate_or_cancel",
        client_order_id=client_order_id,
    )


def _order_summary(
    *,
    order_id: str,
    client_order_id: str,
    status: str,
    fill_count_fp: str,
    remaining_count_fp: str,
    initial_count_fp: str,
) -> KalshiOrderSummary:
    return KalshiOrderSummary(
        order_id=order_id,
        client_order_id=client_order_id,
        ticker="KXBTC-1",
        side="yes",
        action="buy",
        order_type="limit",
        status=status,
        yes_price_dollars=Decimal("0.0100"),
        no_price_dollars=None,
        fill_count_fp=Decimal(fill_count_fp),
        remaining_count_fp=Decimal(remaining_count_fp),
        initial_count_fp=Decimal(initial_count_fp),
        created_time="2026-04-23T12:00:00Z",
        last_update_time="2026-04-23T12:00:01Z",
    )


def _env_text(
    *,
    live_validation_enabled: str,
    live_validation_ticker: str | None = None,
    live_validation_action: str | None = None,
    live_validation_side: str | None = None,
    live_validation_price_dollars: str | None = None,
    live_validation_time_in_force: str | None = None,
) -> str:
    lines = [
        "KALSHI_ENV=prod",
        "KALSHI_API_KEY_ID=test-key-id",
        'KALSHI_PRIVATE_KEY_PEM="-----BEGIN PRIVATE KEY-----\\nTEST\\n-----END PRIVATE KEY-----"',
        f"LIVE_VALIDATION_ENABLED={live_validation_enabled}",
        "LIVE_VALIDATION_ENV=prod",
        "LIVE_VALIDATION_COUNT=1",
        "LIVE_VALIDATION_POLL_ATTEMPTS=3",
        "LIVE_VALIDATION_POLL_INTERVAL_SECONDS=1",
        "LIVE_VALIDATION_CLIENT_ORDER_ID_PREFIX=live-smoke",
    ]
    if live_validation_ticker is not None:
        lines.append(f"LIVE_VALIDATION_TICKER={live_validation_ticker}")
    if live_validation_action is not None:
        lines.append(f"LIVE_VALIDATION_ACTION={live_validation_action}")
    if live_validation_side is not None:
        lines.append(f"LIVE_VALIDATION_SIDE={live_validation_side}")
    if live_validation_price_dollars is not None:
        lines.append(f"LIVE_VALIDATION_PRICE_DOLLARS={live_validation_price_dollars}")
    if live_validation_time_in_force is not None:
        lines.append(f"LIVE_VALIDATION_TIME_IN_FORCE={live_validation_time_in_force}")
    return "\n".join(lines) + "\n"


class _FakeKalshiClient:
    def __init__(
        self,
        *,
        created_order: KalshiOrderSummary | None = None,
        polled_orders: list[KalshiOrderSummary] | None = None,
        balance_payload: dict[str, object] | None = None,
        create_error: Exception | None = None,
    ) -> None:
        self._created_order = created_order
        self._polled_orders = list(polled_orders or [])
        self._balance_payload = balance_payload or {}
        self._create_error = create_error
        self._poll_index = 0

    def create_order(self, order_request) -> KalshiOrderSummary:
        if self._create_error is not None:
            raise self._create_error
        if self._created_order is None:
            raise KalshiClientError("No fake create-order result configured.")
        return self._created_order

    def get_order(self, order_id: str) -> KalshiOrderSummary:
        if self._poll_index >= len(self._polled_orders):
            return self._polled_orders[-1]
        result = self._polled_orders[self._poll_index]
        self._poll_index += 1
        return result

    def get_balance(self) -> dict[str, object]:
        return dict(self._balance_payload)


if __name__ == "__main__":
    raise SystemExit(main())
