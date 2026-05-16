"""Phase G3 checks for composite quality scoring."""

import sys
from decimal import Decimal
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi_bot.contracts.contract_scorer import score_candidate_quality  # noqa: E402
from kalshi_bot.forecast.progression_memory import ProgressionMemoryState  # noqa: E402


def main() -> None:
    strong = score_candidate_quality(
        return_range_ratio=Decimal("1.50"),
        ratio_floor=Decimal("0.50"),
        ratio_decay=Decimal("-0.10"),
        near_extreme_distance_bps=Decimal("10"),
        near_extreme_threshold_bps=Decimal("6"),
        recent_5m_range_bps=Decimal("12"),
        recent_5m_return_bps=Decimal("8"),
        lookback_return_bps=Decimal("18"),
        trend_confirmation_status="confirmed",
        deceleration_persistence_count=0,
        range_expansion_status="normal",
        ev=Decimal("0.10"),
        price=Decimal("0.45"),
        side_needs_cross=False,
        required_bps_per_minute=Decimal("0"),
        required_bps_per_minute_limit=Decimal("0.25"),
        product_volatility_scale=Decimal("1"),
        trend_age_cycles=1,
        failed_attempts=0,
        progression_memory=None,
        reversal_probability=Decimal("0.20"),
    )
    near_only = score_candidate_quality(
        return_range_ratio=Decimal("1.20"),
        ratio_floor=Decimal("0.50"),
        ratio_decay=Decimal("0.00"),
        near_extreme_distance_bps=Decimal("1"),
        near_extreme_threshold_bps=Decimal("6"),
        recent_5m_range_bps=Decimal("12"),
        recent_5m_return_bps=Decimal("8"),
        lookback_return_bps=Decimal("18"),
        trend_confirmation_status="confirmed",
        deceleration_persistence_count=0,
        range_expansion_status="normal",
        ev=Decimal("0.08"),
        price=Decimal("0.45"),
        side_needs_cross=False,
        required_bps_per_minute=Decimal("0"),
        required_bps_per_minute_limit=Decimal("0.25"),
        product_volatility_scale=Decimal("1"),
        trend_age_cycles=1,
        failed_attempts=0,
        progression_memory=_memory("strengthening", decel=0),
        reversal_probability=Decimal("0.20"),
    )
    danger_combo = score_candidate_quality(
        return_range_ratio=Decimal("1.20"),
        ratio_floor=Decimal("0.50"),
        ratio_decay=Decimal("0.20"),
        near_extreme_distance_bps=Decimal("1"),
        near_extreme_threshold_bps=Decimal("6"),
        recent_5m_range_bps=Decimal("12"),
        recent_5m_return_bps=Decimal("8"),
        lookback_return_bps=Decimal("18"),
        trend_confirmation_status="weak_recent_return",
        deceleration_persistence_count=2,
        range_expansion_status="normal",
        ev=Decimal("0.08"),
        price=Decimal("0.45"),
        side_needs_cross=False,
        required_bps_per_minute=Decimal("0"),
        required_bps_per_minute_limit=Decimal("0.25"),
        product_volatility_scale=Decimal("1"),
        trend_age_cycles=1,
        failed_attempts=0,
        progression_memory=_memory("weakening", decel=2),
        reversal_probability=Decimal("0.65"),
        fake_continuation_signature=True,
    )
    weak = score_candidate_quality(
        return_range_ratio=Decimal("0.20"),
        ratio_floor=Decimal("0.50"),
        ratio_decay=Decimal("0.30"),
        near_extreme_distance_bps=Decimal("1"),
        near_extreme_threshold_bps=Decimal("6"),
        recent_5m_range_bps=Decimal("35"),
        recent_5m_return_bps=Decimal("1"),
        lookback_return_bps=Decimal("2"),
        trend_confirmation_status="weak_recent_return",
        deceleration_persistence_count=3,
        range_expansion_status="expanding",
        ev=Decimal("-0.05"),
        price=Decimal("0.70"),
        side_needs_cross=False,
        required_bps_per_minute=Decimal("0.50"),
        required_bps_per_minute_limit=Decimal("0.25"),
        product_volatility_scale=Decimal("1"),
        trend_age_cycles=4,
        failed_attempts=2,
        progression_memory=None,
        reversal_probability=Decimal("0.65"),
        fake_continuation_signature=True,
    )
    assert strong.composite_score > weak.composite_score
    assert near_only.composite_score >= Decimal("0.60")
    assert danger_combo.composite_score < Decimal("0.60")
    assert danger_combo.composite_score <= Decimal("0.55")
    assert "near_extreme_danger_combo" in danger_combo.downgrade_reasons
    assert "continuation_major_danger" in danger_combo.downgrade_reasons
    assert weak.composite_score <= Decimal("0.89")
    assert "return_range_ratio_supportive" in strong.bonus_reasons
    assert "return_range_ratio_below_floor" in weak.downgrade_reasons
    print("phaseG3 composite scoring checks passed")


def _memory(quality: str, *, decel: int) -> ProgressionMemoryState:
    return ProgressionMemoryState(
        product_id="BTC-USD",
        sample_count=3,
        trend_age_cycles=3,
        trend_age_seconds=180,
        consecutive_same_side_intents=1,
        failed_continuation_count=0,
        near_extreme_retest_count=1,
        deceleration_persistence_count=decel,
        range_expansion_persistence_count=0,
        ratio_decay=Decimal("0.0000"),
        retry_degradation_factor=Decimal("1.0000"),
        itm_strengthening_status=(
            "strengthening" if quality == "strengthening" else "weakening"
        ),
        distance_to_target_worsening=quality != "strengthening",
        progression_continuation_quality=quality,
        reversal_buildup_score=Decimal("0.0000"),
        last_direction="up",
        last_market_ticker="KXBTC15M-TEST",
        memory_cold_start=False,
    )


if __name__ == "__main__":
    main()
