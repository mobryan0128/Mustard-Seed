"""Validate Phase F1 live order intent construction."""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi_bot.contracts.contract_scorer import ContractScore  # noqa: E402
from kalshi_bot.contracts.contract_scanner import ScannedContract  # noqa: E402
from kalshi_bot.execution.execution_engine import (  # noqa: E402
    SimulatedPosition,
    build_live_order_intent,
    build_live_order_intent_from_contract,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Phase F1 live order intents.")
    parser.parse_args()

    failures: list[str] = []
    failures.extend(_validate_up_maps_to_buy_yes())
    failures.extend(_validate_down_maps_to_buy_no())
    failures.extend(_validate_count_floors())
    failures.extend(_validate_count_below_one_skips())
    failures.extend(_validate_missing_stake_skips())
    failures.extend(_validate_invalid_direction_skips())
    failures.extend(_validate_intent_preserves_trace_fields())
    failures.extend(_validate_contract_intent_uses_live_risk_source())

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1

    print("Phase F1 live order intent checks succeeded.")
    return 0


def _validate_up_maps_to_buy_yes() -> list[str]:
    intent = build_live_order_intent(
        _position(direction="up", stake_dollars=Decimal("3.00"), entry_price=Decimal("0.50"))
    )
    if intent is None:
        return ["up intent was None"]
    if intent.action != "buy" or intent.side != "yes":
        return [f"up intent action/side={intent.action}/{intent.side}"]
    return []


def _validate_down_maps_to_buy_no() -> list[str]:
    intent = build_live_order_intent(
        _position(direction="down", stake_dollars=Decimal("3.00"), entry_price=Decimal("0.50"))
    )
    if intent is None:
        return ["down intent was None"]
    if intent.action != "buy" or intent.side != "no":
        return [f"down intent action/side={intent.action}/{intent.side}"]
    return []


def _validate_count_floors() -> list[str]:
    intent = build_live_order_intent(
        _position(stake_dollars=Decimal("3.00"), entry_price=Decimal("0.46"))
    )
    if intent is None:
        return ["floor intent was None"]
    if intent.count != 6:
        return [f"floor count={intent.count} expected=6"]
    return []


def _validate_count_below_one_skips() -> list[str]:
    intent = build_live_order_intent(
        _position(stake_dollars=Decimal("0.20"), entry_price=Decimal("0.46"))
    )
    if intent is not None:
        return [f"below-one intent={intent} expected None"]
    return []


def _validate_missing_stake_skips() -> list[str]:
    intent = build_live_order_intent(_position(stake_dollars=None))
    if intent is not None:
        return [f"missing-stake intent={intent} expected None"]
    return []


def _validate_invalid_direction_skips() -> list[str]:
    intent = build_live_order_intent(_position(direction="neutral"))
    if intent is not None:
        return [f"invalid-direction intent={intent} expected None"]
    return []


def _validate_intent_preserves_trace_fields() -> list[str]:
    position = _position(
        position_id="sim-0042",
        product_id="ETH-USD",
        market_ticker="KXETH15M-TEST",
        direction="down",
        confidence=82,
        stake_dollars=Decimal("4.00"),
        entry_price=Decimal("0.50"),
    )
    intent = build_live_order_intent(position, client_order_id_prefix="phase-f1")
    if intent is None:
        return ["trace intent was None"]
    failures: list[str] = []
    expectations = {
        "product_id": "ETH-USD",
        "ticker": "KXETH15M-TEST",
        "confidence": 82,
        "stake_dollars": Decimal("4.00"),
        "simulation_position_id": "sim-0042",
        "client_order_id": "phase-f1-sim-0042",
        "price_dollars": Decimal("0.50"),
        "count": 8,
        "risk_approved": True,
        "risk_approval_source": "simulation_entry_risk_gate",
    }
    for field_name, expected in expectations.items():
        actual = getattr(intent, field_name)
        if actual != expected:
            failures.append(f"trace {field_name}={actual} expected={expected}")
    return failures


def _validate_contract_intent_uses_live_risk_source() -> list[str]:
    contract = _contract(
        product_id="SOL-USD",
        market_ticker="KXSOL15M-TEST",
        direction="down",
        confidence=70,
        midpoint=Decimal("0.46"),
    )
    intent = build_live_order_intent_from_contract(
        contract,
        stake_dollars=Decimal("0.92"),
        source_id="cycle-1-SOL",
    )
    if intent is None:
        return ["contract intent was None"]
    failures: list[str] = []
    expectations = {
        "product_id": "SOL-USD",
        "ticker": "KXSOL15M-TEST",
        "action": "buy",
        "side": "no",
        "price_dollars": Decimal("0.46"),
        "count": 2,
        "client_order_id": "live-runner-cycle-1-SOL",
        "stake_dollars": Decimal("0.92"),
        "direction": "down",
        "confidence": 70,
        "simulation_position_id": "cycle-1-SOL",
        "risk_approved": True,
        "risk_approval_source": "live_entry_risk_gate",
    }
    for field_name, expected in expectations.items():
        actual = getattr(intent, field_name)
        if actual != expected:
            failures.append(f"contract {field_name}={actual} expected={expected}")
    return failures


def _position(
    *,
    position_id: str = "sim-0001",
    product_id: str = "BTC-USD",
    market_ticker: str = "KXBTC15M-TEST",
    direction: str = "up",
    confidence: int = 70,
    stake_dollars: Decimal | None = Decimal("3.00"),
    entry_price: Decimal = Decimal("0.50"),
) -> SimulatedPosition:
    return SimulatedPosition(
        position_id=position_id,
        product_id=product_id,
        market_ticker=market_ticker,
        direction=direction,
        structure="trend",
        confidence=confidence,
        entry_price=entry_price,
        latest_price=entry_price,
        stake_dollars=stake_dollars,
        status="open",
        opened_at="2026-04-23T12:00:03+00:00",
        updated_at="2026-04-23T12:00:03+00:00",
        update_count=0,
    )


def _contract(
    *,
    product_id: str = "BTC-USD",
    market_ticker: str = "KXBTC15M-TEST",
    direction: str = "up",
    confidence: int = 70,
    midpoint: Decimal = Decimal("0.50"),
) -> ScannedContract:
    return ScannedContract(
        product_id=product_id,
        market_ticker=market_ticker,
        direction=direction,
        structure="trend",
        confidence=confidence,
        best_bid=midpoint - Decimal("0.01"),
        best_ask=midpoint + Decimal("0.01"),
        midpoint=midpoint,
        bias_as_of="2026-04-23T12:00:00+00:00",
        market_as_of="2026-04-23T12:00:03+00:00",
        score=ContractScore(
            confidence=confidence,
            spread_width=Decimal("0.02"),
            top_of_book_liquidity=Decimal("100"),
            dollar_volume=Decimal("1000"),
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
