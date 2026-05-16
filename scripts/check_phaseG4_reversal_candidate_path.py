"""Phase G4 checks for deterministic reversal probability and EV gating."""

import sys
from decimal import Decimal
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi_bot.contracts.reversal_classifier import (  # noqa: E402
    classify_reversal_probability,
    reversal_expected_value,
)


def main() -> None:
    classification = classify_reversal_probability(
        return_range_ratio=Decimal("0.20"),
        ratio_floor=Decimal("0.50"),
        near_extreme_distance_bps=Decimal("2"),
        near_extreme_threshold_bps=Decimal("6"),
        deceleration_status="decelerating_after_burst",
        range_expansion_status="expanding",
        trend_confirmation_status="weak_recent_return",
        required_bps_per_minute=Decimal("0.30"),
        memory_state=None,
    )
    ev = reversal_expected_value(
        reversal_probability=classification.reversal_probability,
        executable_price=Decimal("0.55"),
    )
    assert classification.reversal_probability >= Decimal("0.55")
    assert ev is not None
    assert ev == classification.reversal_probability - Decimal("0.55")
    assert ev >= Decimal("0.00")
    invalid_price = Decimal("0.99")
    assert invalid_price > classification.reversal_probability
    invalid_ev = reversal_expected_value(
        reversal_probability=classification.reversal_probability,
        executable_price=invalid_price,
    )
    assert invalid_ev is not None
    assert invalid_ev < Decimal("0.00")
    print("phaseG4 reversal candidate checks passed")


if __name__ == "__main__":
    main()
