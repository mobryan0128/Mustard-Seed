"""Validate Phase E2 simulation-entry risk gating behavior."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi_bot.contracts.contract_scanner import ContractScanSnapshot, ScannedContract  # noqa: E402
from kalshi_bot.contracts.contract_scorer import ContractScore  # noqa: E402
from kalshi_bot.execution.execution_engine import SimulationExecutionEngine  # noqa: E402
from kalshi_bot.risk.risk_manager import RiskManager  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate Phase E2 simulation risk gating behavior."
    )
    parser.parse_args()

    failures: list[str] = []
    failures.extend(_validate_allowed_entry_stores_stake())
    failures.extend(_validate_kill_switch_denial())
    failures.extend(_validate_max_open_positions_denial())
    failures.extend(_validate_max_exposure_denial())
    failures.extend(_validate_simulation_uses_base_exposure_cap())
    failures.extend(_validate_daily_loss_denial())
    failures.extend(_validate_day_scoped_daily_loss())
    failures.extend(_validate_denied_candidate_continues_to_next())

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1

    print("Phase E2 simulation risk checks succeeded.")
    return 0


def _validate_allowed_entry_stores_stake() -> list[str]:
    engine = _engine()
    snapshot = engine.evaluate(
        _snapshot(
            _contract(
                product_id="BTC-USD",
                market_ticker="KXBTC-1",
                confidence=60,
                midpoint=Decimal("0.500"),
            )
        )
    )
    position = snapshot.open_positions.get("sim-0001")
    if position is None:
        return ["allowed entry did not open"]
    if position.stake_dollars != Decimal("0.20"):
        return [f"allowed entry stake={position.stake_dollars} expected=0.20"]
    if snapshot.decisions[-1].action != "open_position":
        return [f"allowed entry action={snapshot.decisions[-1].action}"]
    return []


def _validate_kill_switch_denial() -> list[str]:
    engine = _engine(risk_kill_switch_active=True)
    snapshot = engine.evaluate(
        _snapshot(
            _contract(
                product_id="BTC-USD",
                market_ticker="KXBTC-1",
                confidence=80,
                midpoint=Decimal("0.500"),
            )
        )
    )
    return _expect_single_skip(
        snapshot,
        scenario="kill switch",
        reason="risk_kill_switch_active",
    )


def _validate_max_open_positions_denial() -> list[str]:
    engine = _engine(max_open_positions=1)
    engine.evaluate(
        _snapshot(
            _contract(
                product_id="BTC-USD",
                market_ticker="KXBTC-1",
                confidence=60,
                midpoint=Decimal("0.500"),
            )
        )
    )
    snapshot = engine.evaluate(
        _snapshot(
            _contract(
                product_id="ETH-USD",
                market_ticker="KXETH-1",
                confidence=60,
                midpoint=Decimal("0.500"),
            )
        )
    )
    failures: list[str] = []
    actions = tuple(decision.action for decision in snapshot.decisions)
    if actions != ("skip_entry",):
        failures.append(f"max open positions actions={actions}")
    if snapshot.decisions[-1].reason != "risk_max_open_positions":
        failures.append(f"max open positions reason={snapshot.decisions[-1].reason}")
    if tuple(snapshot.open_positions) != ("sim-0001",):
        failures.append(f"max open positions open_positions={tuple(snapshot.open_positions)}")
    if "sim-0002" in snapshot.open_positions:
        failures.append("max open positions created sim-0002")
    return failures


def _validate_max_exposure_denial() -> list[str]:
    engine = _engine(max_total_exposure_dollars=Decimal("0.15"))
    snapshot = engine.evaluate(
        _snapshot(
            _contract(
                product_id="BTC-USD",
                market_ticker="KXBTC-1",
                confidence=60,
                midpoint=Decimal("0.500"),
            )
        )
    )
    return _expect_single_skip(
        snapshot,
        scenario="max exposure",
        reason="risk_max_total_exposure",
    )


def _validate_simulation_uses_base_exposure_cap() -> list[str]:
    engine = _engine(max_total_exposure_dollars=Decimal("0.15"))
    snapshot = engine.evaluate(
        _snapshot(
            _contract(
                product_id="BTC-USD",
                market_ticker="KXBTC-BASE-RISK",
                confidence=60,
                midpoint=Decimal("0.500"),
            )
        )
    )
    return _expect_single_skip(
        snapshot,
        scenario="simulation base exposure cap",
        reason="risk_max_total_exposure",
    )


def _validate_daily_loss_denial() -> list[str]:
    engine = _engine(daily_loss_limit_dollars=Decimal("0.001"))
    engine.evaluate(
        _snapshot(
            _contract(
                product_id="BTC-USD",
                market_ticker="KXBTC-1",
                confidence=40,
                midpoint=Decimal("0.500"),
                market_as_of=_today_timestamp(),
            )
        )
    )
    engine.evaluate(
        _snapshot(
            _contract(
                product_id="BTC-USD",
                market_ticker="KXBTC-1",
                confidence=40,
                midpoint=Decimal("0.480"),
                market_as_of=_today_timestamp(),
            )
        )
    )
    engine.evaluate(
        _snapshot(
            _contract(
                product_id="BTC-USD",
                market_ticker="KXBTC-1",
                confidence=40,
                midpoint=Decimal("0.480"),
                market_as_of=_today_timestamp(),
            )
        )
    )
    snapshot = engine.evaluate(
        _snapshot(
            _contract(
                product_id="ETH-USD",
                market_ticker="KXETH-1",
                confidence=60,
                midpoint=Decimal("0.500"),
                market_as_of=_today_timestamp(),
            )
        )
    )
    failures = _expect_single_skip(
        snapshot,
        scenario="daily loss",
        reason="risk_daily_loss_limit",
    )
    if not snapshot.closed_positions:
        failures.append("daily loss fixture did not create closed position")
    return failures


def _validate_day_scoped_daily_loss() -> list[str]:
    engine = _engine(daily_loss_limit_dollars=Decimal("0.001"))
    yesterday = _date_timestamp(datetime.now(timezone.utc) - timedelta(days=1))
    today = _today_timestamp()

    engine.evaluate(
        _snapshot(
            _contract(
                product_id="BTC-USD",
                market_ticker="KXBTC-OLD",
                confidence=40,
                midpoint=Decimal("0.500"),
                market_as_of=yesterday,
            )
        )
    )
    engine.evaluate(
        _snapshot(
            _contract(
                product_id="BTC-USD",
                market_ticker="KXBTC-OLD",
                confidence=40,
                midpoint=Decimal("0.480"),
                market_as_of=yesterday,
            )
        )
    )
    engine.evaluate(
        _snapshot(
            _contract(
                product_id="BTC-USD",
                market_ticker="KXBTC-OLD",
                confidence=40,
                midpoint=Decimal("0.480"),
                market_as_of=yesterday,
            )
        )
    )

    today_entry = engine.evaluate(
        _snapshot(
            _contract(
                product_id="ETH-USD",
                market_ticker="KXETH-TODAY",
                confidence=40,
                midpoint=Decimal("0.500"),
                market_as_of=today,
            )
        )
    )
    failures: list[str] = []
    if today_entry.decisions[-1].action != "open_position":
        failures.append(
            f"day scoped old loss blocked entry reason={today_entry.decisions[-1].reason}"
        )

    engine.evaluate(
        _snapshot(
            _contract(
                product_id="ETH-USD",
                market_ticker="KXETH-TODAY",
                confidence=40,
                midpoint=Decimal("0.480"),
                market_as_of=today,
            )
        )
    )
    engine.evaluate(
        _snapshot(
            _contract(
                product_id="ETH-USD",
                market_ticker="KXETH-TODAY",
                confidence=40,
                midpoint=Decimal("0.480"),
                market_as_of=today,
            )
        )
    )
    blocked_snapshot = engine.evaluate(
        _snapshot(
            _contract(
                product_id="SOL-USD",
                market_ticker="KXSOL-TODAY",
                confidence=60,
                midpoint=Decimal("0.500"),
                market_as_of=today,
            )
        )
    )
    if blocked_snapshot.decisions[-1].reason != "risk_daily_loss_limit":
        failures.append(
            f"day scoped today loss reason={blocked_snapshot.decisions[-1].reason}"
        )
    return failures


def _validate_denied_candidate_continues_to_next() -> list[str]:
    engine = _engine(max_total_exposure_dollars=Decimal("0.25"))
    snapshot = engine.evaluate(
        _snapshot(
            _contract(
                product_id="BTC-USD",
                market_ticker="KXBTC-HIGH-STAKE",
                confidence=80,
                midpoint=Decimal("0.500"),
            ),
            _contract(
                product_id="ETH-USD",
                market_ticker="KXETH-LOW-STAKE",
                confidence=40,
                midpoint=Decimal("0.500"),
            ),
        )
    )
    failures: list[str] = []
    actions = tuple(decision.action for decision in snapshot.decisions)
    reasons = tuple(decision.reason for decision in snapshot.decisions)
    if actions != ("skip_entry", "open_position"):
        failures.append(f"continue to next actions={actions}")
    if reasons[0] != "risk_max_total_exposure":
        failures.append(f"continue to next first reason={reasons[0]}")
    position = snapshot.open_positions.get("sim-0001")
    if position is None:
        failures.append("continue to next did not open fallback candidate")
    elif position.product_id != "ETH-USD" or position.stake_dollars != Decimal("0.10"):
        failures.append(
            f"continue to next opened {position.product_id}/{position.stake_dollars}"
        )
    return failures


def _expect_single_skip(snapshot, *, scenario: str, reason: str) -> list[str]:  # noqa: ANN001
    failures: list[str] = []
    if snapshot.open_positions:
        failures.append(f"{scenario} opened positions={tuple(snapshot.open_positions)}")
    actions = tuple(decision.action for decision in snapshot.decisions)
    if actions != ("skip_entry",):
        failures.append(f"{scenario} actions={actions}")
    if snapshot.decisions[-1].reason != reason:
        failures.append(f"{scenario} reason={snapshot.decisions[-1].reason}")
    return failures


def _engine(
    *,
    max_open_positions: int = 2,
    max_total_exposure_dollars: Decimal = Decimal("10"),
    daily_loss_limit_dollars: Decimal = Decimal("5"),
    risk_kill_switch_active: bool = False,
) -> SimulationExecutionEngine:
    return SimulationExecutionEngine(
        enabled=True,
        max_new_positions_per_evaluation=1,
        position_id_prefix="sim",
        exit_enabled=True,
        allow_same_pass_reentry=False,
        risk_manager=RiskManager(
            live_validation_enabled=False,
            live_trading_enabled=False,
            live_kill_switch_active=False,
            env="demo",
            live_validation_env="prod",
            account_balance_dollars=Decimal("10"),
            min_percent_per_trade=Decimal("0.01"),
            max_percent_per_trade=Decimal("0.03"),
            min_stake_dollars=Decimal("0.10"),
            max_stake_dollars=Decimal("3"),
            max_open_positions=max_open_positions,
            max_total_exposure_dollars=max_total_exposure_dollars,
            daily_loss_limit_dollars=daily_loss_limit_dollars,
            risk_kill_switch_active=risk_kill_switch_active,
        ),
    )


def _snapshot(*contracts: ScannedContract) -> ContractScanSnapshot:
    return ContractScanSnapshot(ranked_contracts=contracts, skipped_contracts=())


def _contract(
    *,
    product_id: str,
    market_ticker: str,
    confidence: int,
    midpoint: Decimal,
    market_as_of: str = "2026-04-23T12:00:03+00:00",
) -> ScannedContract:
    score = ContractScore(
        confidence=confidence,
        spread_width=Decimal("0.040"),
        top_of_book_liquidity=Decimal("200"),
        dollar_volume=Decimal("1000"),
    )
    return ScannedContract(
        product_id=product_id,
        market_ticker=market_ticker,
        direction="up",
        structure="trend",
        confidence=confidence,
        best_bid=midpoint - Decimal("0.020"),
        best_ask=midpoint + Decimal("0.020"),
        midpoint=midpoint,
        bias_as_of="2026-04-23T12:00:00+00:00",
        market_as_of=market_as_of,
        score=score,
    )


def _today_timestamp() -> str:
    return _date_timestamp(datetime.now(timezone.utc))


def _date_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(
        hour=12,
        minute=0,
        second=3,
        microsecond=0,
    ).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
