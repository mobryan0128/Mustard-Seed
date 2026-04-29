"""Validate live caps and live risk reconciliation behavior."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi_bot.clients.kalshi_client import (  # noqa: E402
    KalshiMarketPosition,
    KalshiOrderRequest,
    KalshiPositionPage,
)
from kalshi_bot.config.settings import load_settings  # noqa: E402
from kalshi_bot.contracts.contract_scorer import ContractScore  # noqa: E402
from kalshi_bot.contracts.contract_scanner import (  # noqa: E402
    ContractScanSnapshot,
    ScannedContract,
)
from kalshi_bot.execution.live_execution_coordinator import (  # noqa: E402
    LiveExecutionCoordinator,
    LivePositionRecord,
)
from kalshi_bot.risk.risk_manager import RiskManager  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate live caps and risk reconciliation behavior."
    )
    parser.parse_args()

    failures: list[str] = []
    failures.extend(_validate_settings_defaults())
    failures.extend(_validate_settings_overrides())
    failures.extend(_validate_live_order_count_cap_override())
    failures.extend(_validate_one_live_position_blocks_default_cap())
    failures.extend(_validate_one_live_position_allowed_with_cap_two())
    failures.extend(_validate_two_live_positions_block_cap_two())
    failures.extend(_validate_stale_filled_ledger_cleared_by_empty_positions())
    failures.extend(_validate_terminal_ledger_fallback_does_not_block())
    failures.extend(_validate_unset_live_exposure_override_uses_base_risk())
    failures.extend(_validate_lower_live_exposure_override_blocks())
    failures.extend(_validate_higher_live_exposure_override_allows())

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1

    print("Live risk reconciliation checks succeeded.")
    return 0


def _validate_settings_defaults() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        env_path = Path(temp_dir) / ".env"
        env_path.write_text(_base_env(), encoding="utf-8")
        settings = load_settings(env_path)
    failures: list[str] = []
    if settings.live_max_order_count != 1:
        failures.append(f"default live_max_order_count={settings.live_max_order_count}")
    if settings.live_max_open_positions != 1:
        failures.append(
            f"default live_max_open_positions={settings.live_max_open_positions}"
        )
    if settings.live_min_entry_price_dollars != Decimal("0"):
        failures.append(
            "default live_min_entry_price_dollars="
            f"{settings.live_min_entry_price_dollars}"
        )
    if settings.live_max_entry_price_dollars != Decimal("0.800"):
        failures.append(
            "default live_max_entry_price_dollars="
            f"{settings.live_max_entry_price_dollars}"
        )
    if settings.live_max_execution_spread_dollars != Decimal("0.100"):
        failures.append(
            "default live_max_execution_spread_dollars="
            f"{settings.live_max_execution_spread_dollars}"
        )
    if settings.live_require_momentum_alignment:
        failures.append("default live_require_momentum_alignment=True")
    if settings.live_require_trend_momentum_confirmation:
        failures.append("default live_require_trend_momentum_confirmation=True")
    if settings.live_require_reversal_range_position:
        failures.append("default live_require_reversal_range_position=True")
    if settings.live_min_reversal_range_position != Decimal("0.50"):
        failures.append(
            "default live_min_reversal_range_position="
            f"{settings.live_min_reversal_range_position}"
        )
    if settings.live_block_impulse_override_from_chop:
        failures.append("default live_block_impulse_override_from_chop=True")
    if settings.live_impulse_override_require_momentum_alignment:
        failures.append(
            "default live_impulse_override_require_momentum_alignment=True"
        )
    if settings.live_impulse_override_require_range_position:
        failures.append("default live_impulse_override_require_range_position=True")
    if settings.live_impulse_override_min_recent_return_bps is not None:
        failures.append(
            "default live_impulse_override_min_recent_return_bps="
            f"{settings.live_impulse_override_min_recent_return_bps}"
        )
    if settings.live_trend_momentum_min_recent_return_bps is not None:
        failures.append(
            "default live_trend_momentum_min_recent_return_bps="
            f"{settings.live_trend_momentum_min_recent_return_bps}"
        )
    if settings.live_max_total_exposure_dollars is not None:
        failures.append(
            "default live_max_total_exposure_dollars="
            f"{settings.live_max_total_exposure_dollars}"
        )
    return failures


def _validate_settings_overrides() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        env_path = Path(temp_dir) / ".env"
        env_path.write_text(
            _base_env()
            + "\nLIVE_MAX_ORDER_COUNT=5\n"
            + "LIVE_MAX_OPEN_POSITIONS=2\n"
            + "LIVE_MIN_ENTRY_PRICE_DOLLARS=0.25\n"
            + "LIVE_MAX_ENTRY_PRICE_DOLLARS=0.850\n"
            + "LIVE_MAX_EXECUTION_SPREAD_DOLLARS=0.150\n"
            + "LIVE_REQUIRE_MOMENTUM_ALIGNMENT=true\n"
            + "LIVE_REQUIRE_TREND_MOMENTUM_CONFIRMATION=true\n"
            + "LIVE_REQUIRE_REVERSAL_RANGE_POSITION=true\n"
            + "LIVE_MIN_REVERSAL_RANGE_POSITION=0.60\n"
            + "LIVE_BLOCK_IMPULSE_OVERRIDE_FROM_CHOP=true\n"
            + "LIVE_IMPULSE_OVERRIDE_REQUIRE_MOMENTUM_ALIGNMENT=true\n"
            + "LIVE_IMPULSE_OVERRIDE_REQUIRE_RANGE_POSITION=true\n"
            + "LIVE_IMPULSE_OVERRIDE_MIN_RECENT_RETURN_BPS=4.5\n"
            + "LIVE_TREND_MOMENTUM_MIN_RECENT_RETURN_BPS=12.5\n"
            + "LIVE_MAX_TOTAL_EXPOSURE_DOLLARS=12.34\n",
            encoding="utf-8",
        )
        settings = load_settings(env_path)
    failures: list[str] = []
    if settings.live_max_order_count != 5:
        failures.append(f"override live_max_order_count={settings.live_max_order_count}")
    if settings.live_max_open_positions != 2:
        failures.append(
            f"override live_max_open_positions={settings.live_max_open_positions}"
        )
    if settings.live_min_entry_price_dollars != Decimal("0.25"):
        failures.append(
            "override live_min_entry_price_dollars="
            f"{settings.live_min_entry_price_dollars}"
        )
    if settings.live_max_entry_price_dollars != Decimal("0.850"):
        failures.append(
            "override live_max_entry_price_dollars="
            f"{settings.live_max_entry_price_dollars}"
        )
    if settings.live_max_execution_spread_dollars != Decimal("0.150"):
        failures.append(
            "override live_max_execution_spread_dollars="
            f"{settings.live_max_execution_spread_dollars}"
        )
    if not settings.live_require_momentum_alignment:
        failures.append("override live_require_momentum_alignment=False")
    if not settings.live_require_trend_momentum_confirmation:
        failures.append("override live_require_trend_momentum_confirmation=False")
    if not settings.live_require_reversal_range_position:
        failures.append("override live_require_reversal_range_position=False")
    if settings.live_min_reversal_range_position != Decimal("0.60"):
        failures.append(
            "override live_min_reversal_range_position="
            f"{settings.live_min_reversal_range_position}"
        )
    if not settings.live_block_impulse_override_from_chop:
        failures.append("override live_block_impulse_override_from_chop=False")
    if not settings.live_impulse_override_require_momentum_alignment:
        failures.append(
            "override live_impulse_override_require_momentum_alignment=False"
        )
    if not settings.live_impulse_override_require_range_position:
        failures.append("override live_impulse_override_require_range_position=False")
    if settings.live_impulse_override_min_recent_return_bps != Decimal("4.5"):
        failures.append(
            "override live_impulse_override_min_recent_return_bps="
            f"{settings.live_impulse_override_min_recent_return_bps}"
        )
    if settings.live_trend_momentum_min_recent_return_bps != Decimal("12.5"):
        failures.append(
            "override live_trend_momentum_min_recent_return_bps="
            f"{settings.live_trend_momentum_min_recent_return_bps}"
        )
    if settings.live_max_total_exposure_dollars != Decimal("12.34"):
        failures.append(
            "override live_max_total_exposure_dollars="
            f"{settings.live_max_total_exposure_dollars}"
        )
    return failures


def _validate_live_order_count_cap_override() -> list[str]:
    manager = _risk_manager(max_live_order_count=5)
    allow_five = manager.evaluate_live_order(_order_request(count=5))
    block_six = manager.evaluate_live_order(_order_request(count=6))
    failures: list[str] = []
    if not allow_five.allow:
        failures.append(f"count five decision={allow_five}")
    if block_six.allow or block_six.reason != "order_count_exceeds_phase10_cap":
        failures.append(f"count six decision={block_six}")
    return failures


def _validate_one_live_position_blocks_default_cap() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            live_max_open_positions=1,
            positions=(_position("KXBTC15M-OPEN", Decimal("1.00")),),
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(_contract()),
            cycle_number=1,
        )
        if intents:
            return ["default live max open positions created an intent"]
        return _assert_skip_reason(temp_path, "risk_max_open_positions")


def _validate_one_live_position_allowed_with_cap_two() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            live_max_open_positions=2,
            positions=(_position("KXBTC15M-OPEN", Decimal("1.00")),),
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(_contract()),
            cycle_number=2,
        )
        if len(intents) != 1:
            return [f"cap two intent count={len(intents)} expected=1"]
        return _assert_event_present(temp_path, "live_position_reconciled")


def _validate_two_live_positions_block_cap_two() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            live_max_open_positions=2,
            positions=(
                _position("KXBTC15M-OPEN", Decimal("1.00")),
                _position("KXETH15M-OPEN", Decimal("2.00")),
            ),
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(_contract()),
            cycle_number=3,
        )
        if intents:
            return ["cap two with two live positions created an intent"]
        return _assert_skip_reason(temp_path, "risk_max_open_positions")


def _validate_stale_filled_ledger_cleared_by_empty_positions() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(temp_path, live_max_open_positions=1, positions=())
        coordinator._live_position_ledger["stale-filled"] = _live_record(  # noqa: SLF001
            classification="filled",
            status="executed",
            filled_count=Decimal("1.00"),
            price_dollars=Decimal("0.50"),
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(_contract()),
            cycle_number=4,
        )
        failures: list[str] = []
        if len(intents) != 1:
            failures.append(f"stale ledger intent count={len(intents)} expected=1")
        failures.extend(_assert_event_present(temp_path, "stale_live_exposure_cleared"))
        failures.extend(_assert_event_present(temp_path, "live_open_position_count"))
        failures.extend(_assert_event_present(temp_path, "live_current_exposure_dollars"))
        return failures


def _validate_terminal_ledger_fallback_does_not_block() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            live_max_open_positions=1,
            positions_error=True,
        )
        coordinator._live_position_ledger["terminal-filled"] = _live_record(  # noqa: SLF001
            classification="filled",
            status="executed",
            filled_count=Decimal("1.00"),
            price_dollars=Decimal("0.50"),
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(_contract()),
            cycle_number=5,
        )
        if len(intents) != 1:
            return [f"terminal fallback intent count={len(intents)} expected=1"]
        return _assert_event_present(temp_path, "live_position_reconciled")


def _validate_unset_live_exposure_override_uses_base_risk() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            live_max_open_positions=2,
            risk_max_total_exposure_dollars=Decimal("2.00"),
            positions=(_position("KXBTC15M-OPEN", Decimal("1.00")),),
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(_contract()),
            cycle_number=6,
        )
        failures: list[str] = []
        if intents:
            failures.append("base exposure cap created an intent")
        failures.extend(
            _assert_skip_payload(
                temp_path,
                {
                    "reason": "risk_max_total_exposure",
                    "current_exposure_dollars": "1.00",
                    "max_total_exposure_dollars": "2.00",
                    "max_total_exposure_source": "base_risk",
                },
            )
        )
        return failures


def _validate_lower_live_exposure_override_blocks() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            live_max_open_positions=2,
            risk_max_total_exposure_dollars=Decimal("10.00"),
            live_max_total_exposure_dollars=Decimal("2.00"),
            positions=(_position("KXBTC15M-OPEN", Decimal("1.00")),),
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(_contract()),
            cycle_number=7,
        )
        failures: list[str] = []
        if intents:
            failures.append("live exposure override created an intent")
        failures.extend(
            _assert_skip_payload(
                temp_path,
                {
                    "reason": "risk_max_total_exposure",
                    "current_exposure_dollars": "1.00",
                    "max_total_exposure_dollars": "2.00",
                    "max_total_exposure_source": "live_override",
                },
            )
        )
        return failures


def _validate_higher_live_exposure_override_allows() -> list[str]:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        coordinator = _coordinator(
            temp_path,
            live_max_open_positions=2,
            risk_max_total_exposure_dollars=Decimal("2.00"),
            live_max_total_exposure_dollars=Decimal("10.00"),
            positions=(_position("KXBTC15M-OPEN", Decimal("1.00")),),
        )
        intents = coordinator.process_contract_scan_snapshot(
            _contract_snapshot(_contract()),
            cycle_number=8,
        )
        failures: list[str] = []
        if len(intents) != 1:
            failures.append(f"higher live exposure intent count={len(intents)}")
            return failures
        failures.extend(
            _assert_event_payload(
                temp_path,
                "live_intent_created",
                {
                    "max_total_exposure_dollars": "10.00",
                    "max_total_exposure_source": "live_override",
                },
            )
        )
        failures.extend(
            _assert_event_payload(
                temp_path,
                "live_stake_computed",
                {
                    "max_total_exposure_dollars": "10.00",
                    "max_total_exposure_source": "live_override",
                },
            )
        )
        return failures


def _base_env() -> str:
    return "\n".join(
        (
            "KALSHI_ENV=demo",
            "KALSHI_API_KEY_ID=test-key",
            "KALSHI_PRIVATE_KEY_PEM=test-key-pem",
        )
    )


def _risk_manager(*, max_live_order_count: int) -> RiskManager:
    return RiskManager(
        live_validation_enabled=True,
        live_trading_enabled=True,
        live_kill_switch_active=False,
        env="prod",
        live_validation_env="prod",
        max_live_order_count=max_live_order_count,
        required_time_in_force="immediate_or_cancel",
    )


def _order_request(*, count: int) -> KalshiOrderRequest:
    return KalshiOrderRequest(
        ticker="KXBTC15M-TEST",
        action="buy",
        side="yes",
        count=count,
        price_dollars=Decimal("0.50"),
        time_in_force="immediate_or_cancel",
        client_order_id=f"test-count-{count}",
    )


def _coordinator(
    temp_path: Path,
    *,
    live_max_open_positions: int,
    positions: tuple[KalshiMarketPosition, ...] = (),
    positions_error: bool = False,
    risk_max_total_exposure_dollars: Decimal = Decimal("10"),
    live_max_total_exposure_dollars: Decimal | None = None,
) -> LiveExecutionCoordinator:
    return LiveExecutionCoordinator(
        settings=_Settings(
            log_directory=temp_path,
            log_jsonl_enabled=True,
            live_max_open_positions=live_max_open_positions,
            risk_max_total_exposure_dollars=risk_max_total_exposure_dollars,
            live_max_total_exposure_dollars=live_max_total_exposure_dollars,
        ),
        client=_FakeClient(positions=positions, positions_error=positions_error),
    )


def _position(ticker: str, exposure: Decimal) -> KalshiMarketPosition:
    return KalshiMarketPosition(
        ticker=ticker,
        position_fp=Decimal("1.00"),
        market_exposure_dollars=exposure,
        resting_orders_count=0,
        last_updated_ts="2026-04-23T12:00:00Z",
    )


def _contract_snapshot(*contracts: ScannedContract) -> ContractScanSnapshot:
    return ContractScanSnapshot(ranked_contracts=contracts, skipped_contracts=())


def _contract() -> ScannedContract:
    return ScannedContract(
        product_id="BTC-USD",
        market_ticker="KXBTC15M-TEST",
        direction="up",
        structure="trend",
        confidence=70,
        best_bid=Decimal("0.40"),
        best_ask=Decimal("0.50"),
        midpoint=Decimal("0.45"),
        bias_as_of="2026-04-23T12:00:00+00:00",
        market_as_of="2026-04-23T12:00:03+00:00",
        score=ContractScore(
            confidence=70,
            spread_width=Decimal("0.10"),
            top_of_book_liquidity=Decimal("100"),
            dollar_volume=Decimal("1000"),
        ),
    )


def _live_record(
    *,
    classification: str,
    status: str,
    filled_count: Decimal,
    price_dollars: Decimal,
) -> LivePositionRecord:
    return LivePositionRecord(
        client_order_id="stale-filled",
        order_id="ord-stale-filled",
        product_id="BTC-USD",
        simulation_position_id="cycle-1-BTC-USD-KXBTC15M-TEST",
        ticker="KXBTC15M-TEST",
        side="yes",
        action="buy",
        direction="up",
        confidence=70,
        requested_count=Decimal("1.00"),
        filled_count=filled_count,
        remaining_count=Decimal("0.00"),
        price_dollars=price_dollars,
        average_fill_price_dollars=None,
        stake_dollars=Decimal("0.50"),
        status=status,
        classification=classification,
        opened_at="2026-04-23T12:00:00Z",
        updated_at="2026-04-23T12:00:01Z",
    )


def _jsonl_records(path: Path) -> tuple[dict[str, object], ...]:
    if not path.exists():
        return ()
    return tuple(
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    )


def _first_event_payload(temp_path: Path, event_type: str) -> dict[str, object] | None:
    for record in _jsonl_records(temp_path / "runtime.jsonl"):
        if record.get("event_type") != event_type:
            continue
        payload = record.get("payload")
        if isinstance(payload, dict):
            return payload
    return None


def _assert_skip_reason(temp_path: Path, expected_reason: str) -> list[str]:
    return _assert_skip_payload(temp_path, {"reason": expected_reason})


def _assert_skip_payload(
    temp_path: Path,
    expected: dict[str, object],
) -> list[str]:
    payload = _first_event_payload(temp_path, "live_order_intent_skipped")
    if payload is None:
        return [f"{expected.get('reason')} skip log missing"]
    return _assert_payload_fields(payload, expected, str(expected.get("reason")))


def _assert_event_payload(
    temp_path: Path,
    event_type: str,
    expected: dict[str, object],
) -> list[str]:
    payload = _first_event_payload(temp_path, event_type)
    if payload is None:
        return [f"{event_type} log missing"]
    return _assert_payload_fields(payload, expected, event_type)


def _assert_payload_fields(
    payload: dict[str, object],
    expected: dict[str, object],
    label: str,
) -> list[str]:
    failures: list[str] = []
    for key, value in expected.items():
        if payload.get(key) != value:
            failures.append(f"{label} {key}={payload.get(key)} expected={value}")
    return failures


def _assert_event_present(temp_path: Path, event_type: str) -> list[str]:
    if _first_event_payload(temp_path, event_type) is None:
        return [f"{event_type} log missing"]
    return []


@dataclass(frozen=True)
class _Settings:
    log_directory: Path
    log_jsonl_enabled: bool
    live_max_open_positions: int
    live_trading_enabled: bool = True
    live_kill_switch_active: bool = False
    env: str = "prod"
    live_validation_time_in_force: str = "immediate_or_cancel"
    risk_min_stake_dollars: Decimal = Decimal("0.10")
    risk_max_stake_dollars: Decimal = Decimal("3")
    risk_max_total_exposure_dollars: Decimal = Decimal("10")
    live_max_total_exposure_dollars: Decimal | None = None
    risk_daily_loss_limit_dollars: Decimal = Decimal("5")
    risk_kill_switch_active: bool = False
    live_max_order_count: int = 1


class _FakeClient:
    def __init__(
        self,
        *,
        positions: tuple[KalshiMarketPosition, ...],
        positions_error: bool,
    ) -> None:
        self._positions = positions
        self._positions_error = positions_error

    def get_balance(self) -> dict[str, object]:
        return {"balance": 25000}

    def get_positions(self, **_kwargs) -> KalshiPositionPage:
        if self._positions_error:
            from kalshi_bot.clients.kalshi_client import KalshiClientError

            raise KalshiClientError("positions unavailable")
        return KalshiPositionPage(market_positions=self._positions, cursor=None)


if __name__ == "__main__":
    raise SystemExit(main())
