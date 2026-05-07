"""Validate Phase E1 percentage-based risk model behavior."""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi_bot.risk.risk_manager import (  # noqa: E402
    RiskManager,
    compute_stake_from_confidence,
)

FIXTURE_MIN_STAKE_DOLLARS = Decimal("0.10")
FIXTURE_MAX_STAKE_DOLLARS = Decimal("3")
FIXTURE_MIN_PERCENT_PER_TRADE = Decimal("0.01")
FIXTURE_MAX_PERCENT_PER_TRADE = Decimal("0.03")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Phase E1 risk model behavior.")
    parser.parse_args()

    failures: list[str] = []
    failures.extend(_validate_stake_calculation())
    failures.extend(_validate_stake_clamps())
    failures.extend(_validate_kill_switch_denial())
    failures.extend(_validate_max_open_positions_denial())
    failures.extend(_validate_exposure_denial())
    failures.extend(_validate_daily_loss_denial())
    failures.extend(_validate_allowed_decision())

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1

    print("Phase E1 risk model checks succeeded.")
    return 0


def _validate_stake_calculation() -> list[str]:
    failures: list[str] = []
    expectations = (
        (40, Decimal("0.10")),
        (59, Decimal("0.10")),
        (60, Decimal("0.20")),
        (79, Decimal("0.20")),
        (80, Decimal("0.30")),
    )
    for confidence, expected in expectations:
        actual = _fixture_stake_from_confidence(confidence, Decimal("10"))
        if actual != expected:
            failures.append(f"confidence {confidence} stake={actual} expected={expected}")
    return failures


def _validate_stake_clamps() -> list[str]:
    failures: list[str] = []
    min_clamped = _fixture_stake_from_confidence(40, Decimal("1"))
    if min_clamped != Decimal("0.10"):
        failures.append(f"min clamp stake={min_clamped} expected=0.10")

    max_clamped = _fixture_stake_from_confidence(80, Decimal("1000"))
    if max_clamped != Decimal("3"):
        failures.append(f"max clamp stake={max_clamped} expected=3")
    return failures


def _fixture_stake_from_confidence(confidence: int, account_balance: Decimal) -> Decimal:
    return compute_stake_from_confidence(
        confidence,
        account_balance,
        min_percent_per_trade=FIXTURE_MIN_PERCENT_PER_TRADE,
        max_percent_per_trade=FIXTURE_MAX_PERCENT_PER_TRADE,
        min_stake_dollars=FIXTURE_MIN_STAKE_DOLLARS,
        max_stake_dollars=FIXTURE_MAX_STAKE_DOLLARS,
    )


def _validate_kill_switch_denial() -> list[str]:
    manager = _risk_manager(risk_kill_switch_active=True)
    decision = manager.evaluate_entry_risk(
        product_id="BTC-USD",
        confidence=80,
        open_position_count=0,
        current_exposure_dollars=Decimal("0"),
        realized_daily_pnl_dollars=Decimal("0"),
    )
    if decision.allowed or decision.reason != "risk_kill_switch_active" or decision.stake_dollars is not None:
        return [f"kill switch decision={decision}"]
    return []


def _validate_max_open_positions_denial() -> list[str]:
    manager = _risk_manager(max_open_positions=2)
    decision = manager.evaluate_entry_risk(
        product_id="BTC-USD",
        confidence=80,
        open_position_count=2,
        current_exposure_dollars=Decimal("0"),
        realized_daily_pnl_dollars=Decimal("0"),
    )
    if decision.allowed or decision.reason != "risk_max_open_positions" or decision.stake_dollars is not None:
        return [f"max open positions decision={decision}"]
    return []


def _validate_exposure_denial() -> list[str]:
    manager = _risk_manager()
    decision = manager.evaluate_entry_risk(
        product_id="BTC-USD",
        confidence=80,
        open_position_count=0,
        current_exposure_dollars=Decimal("9.80"),
        realized_daily_pnl_dollars=Decimal("0"),
    )
    if decision.allowed or decision.reason != "risk_max_total_exposure" or decision.stake_dollars is not None:
        return [f"exposure decision={decision}"]
    return []


def _validate_daily_loss_denial() -> list[str]:
    manager = _risk_manager()
    decision = manager.evaluate_entry_risk(
        product_id="BTC-USD",
        confidence=80,
        open_position_count=0,
        current_exposure_dollars=Decimal("0"),
        realized_daily_pnl_dollars=Decimal("-5"),
    )
    if decision.allowed or decision.reason != "risk_daily_loss_limit" or decision.stake_dollars is not None:
        return [f"daily loss decision={decision}"]
    return []


def _validate_allowed_decision() -> list[str]:
    manager = _risk_manager()
    decision = manager.evaluate_entry_risk(
        product_id="BTC-USD",
        confidence=60,
        open_position_count=0,
        current_exposure_dollars=Decimal("0"),
        realized_daily_pnl_dollars=Decimal("0"),
    )
    if not decision.allowed or decision.reason != "allowed" or decision.stake_dollars != Decimal("0.20"):
        return [f"allowed decision={decision}"]
    return []


def _risk_manager(
    *,
    max_open_positions: int = 2,
    risk_kill_switch_active: bool = False,
) -> RiskManager:
    return RiskManager(
        live_validation_enabled=False,
        live_trading_enabled=False,
        live_kill_switch_active=False,
        env="demo",
        live_validation_env="prod",
        account_balance_dollars=Decimal("10"),
        min_percent_per_trade=FIXTURE_MIN_PERCENT_PER_TRADE,
        max_percent_per_trade=FIXTURE_MAX_PERCENT_PER_TRADE,
        min_stake_dollars=FIXTURE_MIN_STAKE_DOLLARS,
        max_stake_dollars=FIXTURE_MAX_STAKE_DOLLARS,
        max_open_positions=max_open_positions,
        max_total_exposure_dollars=Decimal("10"),
        daily_loss_limit_dollars=Decimal("5"),
        risk_kill_switch_active=risk_kill_switch_active,
    )


if __name__ == "__main__":
    raise SystemExit(main())
