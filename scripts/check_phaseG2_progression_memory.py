"""Phase G2 checks for progression memory and retry degradation."""

import sys
from decimal import Decimal
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi_bot.forecast.progression_memory import (  # noqa: E402
    ProgressionMemory,
    observation_from_payload,
)


def main() -> None:
    memory = ProgressionMemory(
        window_cycles=4,
        max_age_seconds=3600,
        retry_score_decay=Decimal("0.20"),
    )
    memory.update(
        observation_from_payload(
            product_id="BTC-USD",
            market_ticker="TEST",
            direction="up",
            structure="trend",
            return_range_ratio=Decimal("1.00"),
            near_extreme=False,
            near_extreme_distance_bps=Decimal("8"),
            deceleration_status="not_bursting",
            range_expansion_status="normal",
            side_currently_itm=True,
            side_needs_cross=False,
            distance_to_target_bps=Decimal("-3"),
            required_bps_per_minute=Decimal("0"),
            accepted=True,
        )
    )
    memory.update(
        observation_from_payload(
            product_id="BTC-USD",
            market_ticker="TEST",
            direction="up",
            structure="trend",
            return_range_ratio=Decimal("0.40"),
            near_extreme=True,
            near_extreme_distance_bps=Decimal("2"),
            deceleration_status="decelerating_after_burst",
            range_expansion_status="expanding",
            side_currently_itm=False,
            side_needs_cross=False,
            distance_to_target_bps=Decimal("1"),
            required_bps_per_minute=Decimal("0.20"),
            accepted=False,
            reason="exhaustion_guard_blocked",
        )
    )
    state = memory.state("BTC-USD")
    assert state.sample_count == 2
    assert state.trend_age_seconds >= 0
    assert state.ratio_decay == Decimal("0.6000")
    assert state.failed_continuation_count == 1
    assert state.deceleration_persistence_count == 1
    assert state.range_expansion_persistence_count == 1
    assert state.retry_degradation_factor == Decimal("0.8000")
    assert state.reversal_buildup_score > Decimal("0")
    payload = state.as_payload()
    assert "trend_age_seconds" in payload
    assert "deceleration_persistence_count" in payload
    assert "range_expansion_persistence_count" in payload
    print("phaseG2 progression memory checks passed")


if __name__ == "__main__":
    main()
