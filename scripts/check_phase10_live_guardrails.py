"""Validate Phase 10 live-trading guardrails with deterministic fixtures."""

from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi_bot.clients.kalshi_client import KalshiClientError, KalshiOrderSummary  # noqa: E402
from kalshi_bot.execution.execution_engine import (  # noqa: E402
    LiveExecutionSmokeTester,
    LiveValidationOrder,
)
from kalshi_bot.observability.logger import StructuredLogger  # noqa: E402
from kalshi_bot.observability.replay_engine import ReplayEngine  # noqa: E402
from kalshi_bot.risk.risk_manager import RiskManager  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Phase 10 live guardrails.")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run the actual live guardrail smoke path instead of offline fixtures.",
    )
    parser.add_argument(
        "--env-file",
        default=".env.example",
        help="Environment file used only for the optional live smoke path.",
    )
    args = parser.parse_args()

    if args.live:
        return _run_live(args.env_file)
    return _run_offline()


def _run_offline() -> int:
    failures: list[str] = []
    failures.extend(_validate_kill_switch_denial())
    failures.extend(_validate_live_trading_disabled_denial())
    failures.extend(_validate_non_prod_denial())
    failures.extend(_validate_count_cap_denial())
    failures.extend(_validate_ioc_denial())
    failures.extend(_validate_allowed_flow())
    failures.extend(_validate_live_risk_settings_fallback_to_risk_defaults())
    failures.extend(_validate_live_risk_settings_parse())
    failures.extend(_validate_invalid_live_stake_bounds())
    failures.extend(_validate_live_contract_count_cap_from_settings())

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1

    print("Phase 10 live guardrail offline fixtures succeeded.")
    return 0


def _validate_kill_switch_denial() -> list[str]:
    snapshot, state = _run_guardrail_fixture(
        risk_manager=_risk_manager(live_kill_switch_active=True),
        order=_order(),
    )
    return _assert_denied(
        snapshot=snapshot,
        state=state,
        expected_reason="kill_switch_active",
    )


def _validate_live_trading_disabled_denial() -> list[str]:
    snapshot, state = _run_guardrail_fixture(
        risk_manager=_risk_manager(live_trading_enabled=False),
        order=_order(),
    )
    return _assert_denied(
        snapshot=snapshot,
        state=state,
        expected_reason="live_trading_not_enabled",
    )


def _validate_non_prod_denial() -> list[str]:
    snapshot, state = _run_guardrail_fixture(
        risk_manager=_risk_manager(env="demo"),
        order=_order(),
    )
    return _assert_denied(
        snapshot=snapshot,
        state=state,
        expected_reason="live_env_not_prod",
    )


def _validate_count_cap_denial() -> list[str]:
    snapshot, state = _run_guardrail_fixture(
        risk_manager=_risk_manager(),
        order=_order(count=2),
    )
    return _assert_denied(
        snapshot=snapshot,
        state=state,
        expected_reason="order_count_exceeds_phase10_cap",
    )


def _validate_ioc_denial() -> list[str]:
    snapshot, state = _run_guardrail_fixture(
        risk_manager=_risk_manager(),
        order=_order(time_in_force="fill_or_kill"),
    )
    return _assert_denied(
        snapshot=snapshot,
        state=state,
        expected_reason="unsupported_time_in_force",
    )


def _validate_allowed_flow() -> list[str]:
    created_order = _order_summary(
        order_id="ord-allowed",
        client_order_id="live-allowed",
        status="resting",
        fill_count_fp="0.00",
        remaining_count_fp="1.00",
        initial_count_fp="1.00",
    )
    executed_order = _order_summary(
        order_id="ord-allowed",
        client_order_id="live-allowed",
        status="executed",
        fill_count_fp="1.00",
        remaining_count_fp="0.00",
        initial_count_fp="1.00",
    )
    snapshot, state = _run_guardrail_fixture(
        risk_manager=_risk_manager(),
        order=_order(client_order_id="live-allowed"),
        created_order=created_order,
        polled_orders=[created_order, executed_order],
    )

    failures: list[str] = []
    if snapshot.result.classification != "filled":
        failures.append(f"allowed flow classification={snapshot.result.classification}")
    if snapshot.result.decision_reason is not None:
        failures.append(f"allowed flow decision_reason={snapshot.result.decision_reason}")
    if not snapshot.result.order_placed:
        failures.append("allowed flow did not place order")
    if state.create_order_calls != 1:
        failures.append(f"allowed flow create_order_calls={state.create_order_calls}")
    if state.get_order_calls != 2:
        failures.append(f"allowed flow get_order_calls={state.get_order_calls}")
    if not snapshot.result.balance_fetched:
        failures.append("allowed flow did not fetch balance")
    if not state.log_written or not state.replay_written:
        failures.append("allowed flow did not write log/replay artifacts")
    return failures


def _validate_live_risk_settings_fallback_to_risk_defaults() -> list[str]:
    settings = _load_settings_from_text(
        """
KALSHI_ENV=demo
KALSHI_API_KEY_ID=demo-key
KALSHI_PRIVATE_KEY_PEM=pem
RISK_MIN_STAKE_DOLLARS=0.10
RISK_MAX_STAKE_DOLLARS=3
RISK_MAX_TOTAL_EXPOSURE_DOLLARS=10
"""
    )
    failures: list[str] = []
    if settings.live_min_stake_dollars != settings.risk_min_stake_dollars:
        failures.append(
            "live min fallback="
            f"{settings.live_min_stake_dollars}/{settings.risk_min_stake_dollars}"
        )
    if settings.live_max_stake_dollars != settings.risk_max_stake_dollars:
        failures.append(
            "live max fallback="
            f"{settings.live_max_stake_dollars}/{settings.risk_max_stake_dollars}"
        )
    if settings.live_max_exposure_dollars != settings.risk_max_total_exposure_dollars:
        failures.append(
            "live exposure fallback="
            f"{settings.live_max_exposure_dollars}/"
            f"{settings.risk_max_total_exposure_dollars}"
        )
    if settings.live_max_open_positions != settings.risk_max_open_positions:
        failures.append(
            "live max open fallback="
            f"{settings.live_max_open_positions}/{settings.risk_max_open_positions}"
        )
    if settings.live_max_contract_count != 1000:
        failures.append(f"live count fallback={settings.live_max_contract_count}")
    return failures


def _validate_live_risk_settings_parse() -> list[str]:
    settings = _load_settings_from_text(
        """
KALSHI_ENV=demo
KALSHI_API_KEY_ID=demo-key
KALSHI_PRIVATE_KEY_PEM=pem
RISK_ACCOUNT_BALANCE_DOLLARS=10
RISK_MIN_PERCENT_PER_TRADE=0.01
RISK_MAX_PERCENT_PER_TRADE=0.03
RISK_MIN_STAKE_DOLLARS=0.10
RISK_MAX_STAKE_DOLLARS=3
RISK_MAX_TOTAL_EXPOSURE_DOLLARS=10
LIVE_MIN_STAKE_DOLLARS=2
LIVE_MAX_STAKE_DOLLARS=4
LIVE_MAX_EXPOSURE_DOLLARS=8
LIVE_MAX_OPEN_POSITIONS=1
LIVE_MAX_CONTRACT_COUNT=2
LIVE_REVERSAL_CROSS_HOLD_SECONDS=45
LIVE_MID_PRICE_MIN=0.55
LIVE_MID_PRICE_MAX=0.65
LIVE_ENTRY_SEGMENT_PACING_ENABLED=true
LIVE_ENTRY_SEGMENT_MAX_FINAL_1=1
LIVE_MAX_OPEN_POSITIONS_PER_PRODUCT=2
LIVE_MAX_ENTRIES_PER_PRODUCT_PER_SESSION=2
LIVE_COMPOSITE_QUALITY_FILTER_ENABLED=true
LIVE_COMPOSITE_MAX_ENTRY_PRICE=0.55
LIVE_COMPOSITE_LOW_PRICE_MAX=0.25
LIVE_COMPOSITE_ALLOWED_SEGMENTS=10-to-5,3_to_1
LIVE_COMPOSITE_REQUIRE_TREND=true
LIVE_COMPOSITE_REQUIRE_ITM=true
LIVE_COMPOSITE_BLOCK_NEEDS_CROSS=true
LIVE_REVERSAL_MAX_ENTRY_PRICE=0.09
LIVE_BLOCK_NEEDS_CROSS=true
LIVE_MAX_REQUIRED_BPS_PER_MINUTE=0.20
LIVE_OUTSIDE_END_WINDOW_EXCEPTION_ENABLED=true
LIVE_OUTSIDE_END_WINDOW_MAX_PRICE=0.25
"""
    )
    failures: list[str] = []
    if settings.risk_min_stake_dollars != Decimal("0.10"):
        failures.append(f"generic min stake changed={settings.risk_min_stake_dollars}")
    if settings.live_min_stake_dollars != Decimal("2"):
        failures.append(f"live min stake={settings.live_min_stake_dollars}")
    if settings.live_max_stake_dollars != Decimal("4"):
        failures.append(f"live max stake={settings.live_max_stake_dollars}")
    if settings.live_max_exposure_dollars != Decimal("8"):
        failures.append(f"live max exposure={settings.live_max_exposure_dollars}")
    if settings.live_max_open_positions != 1:
        failures.append(f"live max open={settings.live_max_open_positions}")
    if settings.live_max_contract_count != 2:
        failures.append(f"live max count={settings.live_max_contract_count}")
    if settings.live_reversal_cross_hold_seconds != 45:
        failures.append(
            f"live reversal hold seconds={settings.live_reversal_cross_hold_seconds}"
        )
    if settings.live_mid_price_min != Decimal("0.5500"):
        failures.append(f"live mid min={settings.live_mid_price_min}")
    if settings.live_mid_price_max != Decimal("0.6500"):
        failures.append(f"live mid max={settings.live_mid_price_max}")
    if not settings.live_entry_segment_pacing_enabled:
        failures.append("live segment pacing did not parse true")
    if settings.live_entry_segment_max_final_1 != 1:
        failures.append(f"live final segment max={settings.live_entry_segment_max_final_1}")
    if settings.live_max_open_positions_per_product != 2:
        failures.append(
            "live max open per product="
            f"{settings.live_max_open_positions_per_product}"
        )
    if settings.live_max_entries_per_product_per_session != 2:
        failures.append(
            "live max entries per product session="
            f"{settings.live_max_entries_per_product_per_session}"
        )
    if settings.live_composite_max_entry_price != Decimal("0.5500"):
        failures.append(f"live composite max={settings.live_composite_max_entry_price}")
    if settings.live_composite_low_price_max != Decimal("0.2500"):
        failures.append(f"live composite low={settings.live_composite_low_price_max}")
    if settings.live_composite_allowed_segments != ("10_to_5", "3_to_1"):
        failures.append(
            f"live composite segments={settings.live_composite_allowed_segments}"
        )
    if settings.live_reversal_max_entry_price != Decimal("0.0900"):
        failures.append(f"live reversal max={settings.live_reversal_max_entry_price}")
    if settings.live_max_required_bps_per_minute != Decimal("0.20"):
        failures.append(
            f"live max required bps={settings.live_max_required_bps_per_minute}"
        )
    if not settings.live_outside_end_window_exception_enabled:
        failures.append("live outside exception did not parse true")
    if settings.live_outside_end_window_max_price != Decimal("0.2500"):
        failures.append(
            f"live outside max={settings.live_outside_end_window_max_price}"
        )

    generic_manager = RiskManager.from_settings(settings)
    live_manager = RiskManager.from_live_settings(settings)
    if generic_manager.compute_stake_from_confidence(40) != Decimal("0.10"):
        failures.append("generic manager did not preserve RISK min stake")
    if live_manager.compute_stake_from_confidence(40) != Decimal("2"):
        failures.append("live manager did not use LIVE min stake")
    open_position_decision = live_manager.evaluate_entry_risk(
        product_id="BTC-USD",
        confidence=40,
        open_position_count=1,
        current_exposure_dollars=Decimal("0"),
        realized_daily_pnl_dollars=Decimal("0"),
    )
    if open_position_decision.allowed or open_position_decision.reason != "risk_max_open_positions":
        failures.append(f"live max open decision={open_position_decision}")
    return failures


def _validate_invalid_live_stake_bounds() -> list[str]:
    from kalshi_bot.config.settings import SettingsError

    try:
        _load_settings_from_text(
            """
KALSHI_ENV=demo
KALSHI_API_KEY_ID=demo-key
KALSHI_PRIVATE_KEY_PEM=pem
LIVE_MIN_STAKE_DOLLARS=5
LIVE_MAX_STAKE_DOLLARS=4
"""
        )
    except SettingsError:
        return []
    return ["invalid live stake bounds did not raise SettingsError"]


def _validate_live_contract_count_cap_from_settings() -> list[str]:
    settings = _load_settings_from_text(
        """
KALSHI_ENV=prod
KALSHI_API_KEY_ID=prod-key
KALSHI_PRIVATE_KEY_PEM=pem
LIVE_TRADING_ENABLED=true
LIVE_MAX_CONTRACT_COUNT=2
"""
    )
    manager = RiskManager.from_live_settings(
        settings,
        live_validation_enabled=True,
        live_validation_env="prod",
    )
    decision = manager.evaluate_live_order(_order(count=3))
    if decision.allow or decision.reason != "order_count_exceeds_phase10_cap":
        return [f"live count cap decision={decision}"]
    return []


def _assert_denied(*, snapshot, state, expected_reason: str) -> list[str]:
    failures: list[str] = []
    if snapshot.result.classification != "blocked_by_safeguard":
        failures.append(f"denial classification={snapshot.result.classification}")
    if snapshot.result.decision_reason != expected_reason:
        failures.append(f"denial reason={snapshot.result.decision_reason}")
    if snapshot.result.order_placed:
        failures.append("denied flow placed an order")
    if state.create_order_calls != 0:
        failures.append(f"denied flow create_order_calls={state.create_order_calls}")
    if state.get_order_calls != 0:
        failures.append(f"denied flow get_order_calls={state.get_order_calls}")
    if snapshot.result.balance_fetched:
        failures.append("denied flow fetched balance unexpectedly")
    if not state.log_written or not state.replay_written:
        failures.append("denied flow did not write log/replay artifacts")
    return failures


def _run_guardrail_fixture(
    *,
    risk_manager: RiskManager,
    order: LiveValidationOrder,
    created_order: KalshiOrderSummary | None = None,
    polled_orders: list[KalshiOrderSummary] | None = None,
):
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        logger = StructuredLogger(log_directory=tmp_path / "logs", enabled=True)
        replay_engine = ReplayEngine(replay_directory=tmp_path / "replay", enabled=True)
        fake_client = _FakeKalshiClient(
            created_order=created_order,
            polled_orders=polled_orders,
            balance_payload={"balance": "10.00"},
        )
        tester = LiveExecutionSmokeTester(
            client=fake_client,
            logger=logger,
            replay_engine=replay_engine,
            order=order,
            poll_attempts=3,
            poll_interval_seconds=0.001,
            risk_manager=risk_manager,
            sleep_fn=lambda _: None,
        )
        snapshot = tester.run()
        state = _FixtureState(
            create_order_calls=fake_client.create_order_calls,
            get_order_calls=fake_client.get_order_calls,
            log_written=logger.path.exists(),
            replay_written=replay_engine.path.exists(),
        )
        return snapshot, state


def _risk_manager(
    *,
    live_validation_enabled: bool = True,
    live_trading_enabled: bool = True,
    live_kill_switch_active: bool = False,
    env: str = "prod",
    live_validation_env: str = "prod",
) -> RiskManager:
    return RiskManager(
        live_validation_enabled=live_validation_enabled,
        live_trading_enabled=live_trading_enabled,
        live_kill_switch_active=live_kill_switch_active,
        env=env,
        live_validation_env=live_validation_env,
        max_live_order_count=1,
        required_time_in_force="immediate_or_cancel",
    )


def _order(
    *,
    count: int = 1,
    time_in_force: str = "immediate_or_cancel",
    client_order_id: str = "live-check",
) -> LiveValidationOrder:
    return LiveValidationOrder(
        ticker="KXBTC-1",
        action="buy",
        side="yes",
        count=count,
        price_dollars=Decimal("0.0100"),
        time_in_force=time_in_force,
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


def _run_live(env_file: str) -> int:
    from kalshi_bot.config.settings import SettingsError, load_settings
    from kalshi_bot.execution.execution_engine import LiveExecutionSmokeError

    try:
        settings = load_settings(env_file)
        tester = LiveExecutionSmokeTester.from_settings(settings)
    except (SettingsError, LiveExecutionSmokeError, ValueError) as exc:
        print(f"Phase 10 live guardrail check failed: {exc}", file=sys.stderr)
        return 1

    snapshot = tester.run()
    print("Phase 10 live guardrail smoke completed.")
    print(f"classification={snapshot.result.classification}")
    print(f"decision_reason={snapshot.result.decision_reason}")
    print(f"order_placed={snapshot.result.order_placed}")
    print(f"balance_fetched={snapshot.result.balance_fetched}")
    return 0


def _load_settings_from_text(text: str):
    from kalshi_bot.config.settings import load_settings

    keys = {
        "KALSHI_ENV",
        "KALSHI_API_KEY_ID",
        "KALSHI_PRIVATE_KEY_PEM",
        "KALSHI_PRIVATE_KEY_PATH",
        "RISK_ACCOUNT_BALANCE_DOLLARS",
        "RISK_MIN_PERCENT_PER_TRADE",
        "RISK_MAX_PERCENT_PER_TRADE",
        "RISK_MIN_STAKE_DOLLARS",
        "RISK_MAX_STAKE_DOLLARS",
        "RISK_MAX_TOTAL_EXPOSURE_DOLLARS",
        "LIVE_TRADING_ENABLED",
        "LIVE_MAX_EXPOSURE_DOLLARS",
        "LIVE_MIN_STAKE_DOLLARS",
        "LIVE_MAX_STAKE_DOLLARS",
        "LIVE_MAX_OPEN_POSITIONS",
        "LIVE_MAX_CONTRACT_COUNT",
        "LIVE_REVERSAL_CROSS_HOLD_ENABLED",
        "LIVE_REVERSAL_CROSS_HOLD_SECONDS",
        "LIVE_MID_PRICE_TIGHTENING_ENABLED",
        "LIVE_MID_PRICE_MIN",
        "LIVE_MID_PRICE_MAX",
        "LIVE_ENTRY_MIN_REMAINING_SECONDS",
        "LIVE_ENTRY_SEGMENT_PACING_ENABLED",
        "LIVE_ENTRY_SEGMENT_MAX_10_TO_5",
        "LIVE_ENTRY_SEGMENT_MAX_5_TO_3",
        "LIVE_ENTRY_SEGMENT_MAX_3_TO_1",
        "LIVE_ENTRY_SEGMENT_MAX_FINAL_1",
        "LIVE_MAX_OPEN_POSITIONS_PER_PRODUCT",
        "LIVE_MAX_ENTRIES_PER_PRODUCT_PER_SESSION",
    }
    previous = {key: os.environ.get(key) for key in keys}
    for key in keys:
        os.environ.pop(key, None)
    try:
        with TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(text.strip() + "\n", encoding="utf-8")
            return load_settings(env_path)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class _FakeKalshiClient:
    def __init__(
        self,
        *,
        created_order: KalshiOrderSummary | None,
        polled_orders: list[KalshiOrderSummary] | None,
        balance_payload: dict[str, object],
    ) -> None:
        self._created_order = created_order
        self._polled_orders = list(polled_orders or [])
        self._balance_payload = balance_payload
        self._poll_index = 0
        self.create_order_calls = 0
        self.get_order_calls = 0

    def create_order(self, order_request) -> KalshiOrderSummary:
        self.create_order_calls += 1
        if self._created_order is None:
            raise KalshiClientError("No fake create-order result configured.")
        return self._created_order

    def get_order(self, order_id: str) -> KalshiOrderSummary:
        self.get_order_calls += 1
        if not self._polled_orders:
            raise KalshiClientError("No fake get-order result configured.")
        if self._poll_index >= len(self._polled_orders):
            return self._polled_orders[-1]
        result = self._polled_orders[self._poll_index]
        self._poll_index += 1
        return result

    def get_balance(self) -> dict[str, object]:
        return dict(self._balance_payload)


class _FixtureState:
    def __init__(
        self,
        *,
        create_order_calls: int,
        get_order_calls: int,
        log_written: bool,
        replay_written: bool,
    ) -> None:
        self.create_order_calls = create_order_calls
        self.get_order_calls = get_order_calls
        self.log_written = log_written
        self.replay_written = replay_written


if __name__ == "__main__":
    raise SystemExit(main())
