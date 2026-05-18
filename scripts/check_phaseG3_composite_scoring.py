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
    clean_near_extreme = _score(
        return_range_ratio=Decimal("1.50"),
        near_extreme_distance_bps=Decimal("1"),
        distance_to_target_bps=Decimal("2"),
        progression_memory=_memory("strengthening", decel=0),
    )
    ratio_decay_only = _score(
        ratio_decay=Decimal("0.25"),
        progression_memory=_memory("strengthening", decel=0),
    )
    moderate_strengthening = _score(
        return_range_ratio=Decimal("2.00"),
        progression_memory=_memory("strengthening", decel=0),
    )
    cold_start_only = _score(
        return_range_ratio=Decimal("1.50"),
        progression_memory=None,
        distance_to_target_bps=Decimal("2"),
    )
    high_ratio_strengthening = _score(
        return_range_ratio=Decimal("3.50"),
        progression_memory=_memory("strengthening", decel=0),
        distance_to_target_bps=Decimal("2"),
    )
    cold_high_ratio_overextended = _score(
        return_range_ratio=Decimal("3.50"),
        progression_memory=None,
        distance_to_target_bps=Decimal("8"),
        recent_5m_return_bps=Decimal("14"),
        recent_5m_range_bps=Decimal("15"),
    )
    fake_continuation = _score(
        return_range_ratio=Decimal("3.50"),
        progression_memory=None,
        distance_to_target_bps=Decimal("8"),
        fake_continuation_signature=True,
        reversal_probability=Decimal("0.75"),
    )
    progression_weakening = _score(
        progression_memory=_memory("weakening", decel=0),
    )
    persistent_deceleration = _score(
        progression_memory=_memory("stable", decel=3),
        deceleration_persistence_count=3,
    )
    high_reversal_clean = _score(
        reversal_probability=Decimal("0.75"),
        progression_memory=_memory("strengthening", decel=0),
    )
    quiet_loser_shape = _quiet_conflict_score()
    clean_quiet_winner = _quiet_conflict_score(
        trend_confirmation_status="confirmed",
        signal_conflict_flags=(("impulse_direction_conflict", False),),
        progression_memory=_memory("strengthening", decel=0),
    )
    cold_start_alone = _score(progression_memory=None)
    mismatch_alone = _score(trend_confirmation_status="recent_direction_mismatch")
    impulse_conflict_alone = _score(
        signal_conflict_flags=(("impulse_direction_conflict", True),)
    )
    quiet_ratio_above_band = _quiet_conflict_score(return_range_ratio=Decimal("2.50"))
    quiet_distance_above_band = _quiet_conflict_score(
        distance_to_target_bps=Decimal("1.50")
    )

    assert clean_near_extreme.composite_score >= Decimal("0.60")
    assert "near_extreme_danger_combo" not in clean_near_extreme.downgrade_reasons
    assert ratio_decay_only.composite_score >= Decimal("0.60")
    assert "continuation_major_danger" not in ratio_decay_only.downgrade_reasons
    assert moderate_strengthening.composite_score >= Decimal("0.60")
    assert cold_start_only.composite_score >= Decimal("0.60")
    assert high_ratio_strengthening.composite_score >= Decimal("0.60")
    assert "cold_start_high_ratio_overextension_blocked" not in (
        high_ratio_strengthening.downgrade_reasons
    )
    assert cold_high_ratio_overextended.composite_score <= Decimal("0.49")
    assert "cold_start_high_ratio_overextension_blocked" in (
        cold_high_ratio_overextended.downgrade_reasons
    )
    assert cold_high_ratio_overextended.high_score_danger_cap_applied
    assert cold_high_ratio_overextended.uncapped_composite_score is not None
    assert cold_high_ratio_overextended.capped_composite_score <= Decimal("0.49")
    assert fake_continuation.composite_score <= Decimal("0.49")
    assert "fake_continuation_signature" in fake_continuation.downgrade_reasons
    assert progression_weakening.composite_score <= Decimal("0.49")
    assert "progression_weakening" in progression_weakening.downgrade_reasons
    assert persistent_deceleration.composite_score <= Decimal("0.49")
    assert "persistent_deceleration" in persistent_deceleration.downgrade_reasons
    assert high_reversal_clean.composite_score >= Decimal("0.60")
    assert "continuation_major_danger" not in high_reversal_clean.downgrade_reasons
    assert quiet_loser_shape.composite_score == Decimal("0.49")
    assert "quiet_exhaustion_direction_conflict" in (
        quiet_loser_shape.downgrade_reasons
    )
    assert (
        quiet_loser_shape.hard_gate_statuses.get(
            "quiet_exhaustion_direction_conflict"
        )
        == "blocked"
    )
    assert quiet_loser_shape.quiet_exhaustion_direction_conflict_blocked
    assert quiet_loser_shape.quiet_exhaustion_direction_conflict_cap_applied
    assert clean_quiet_winner.composite_score >= Decimal("0.60")
    assert "quiet_exhaustion_direction_conflict" not in (
        clean_quiet_winner.downgrade_reasons
    )
    for label, score in {
        "cold_start_alone": cold_start_alone,
        "mismatch_alone": mismatch_alone,
        "impulse_conflict_alone": impulse_conflict_alone,
        "quiet_ratio_above_band": quiet_ratio_above_band,
        "quiet_distance_above_band": quiet_distance_above_band,
    }.items():
        assert "quiet_exhaustion_direction_conflict" not in score.downgrade_reasons, (
            label,
            score.downgrade_reasons,
        )
    print("phaseG3 composite scoring checks passed")


def _score(
    *,
    return_range_ratio: Decimal = Decimal("1.50"),
    ratio_decay: Decimal = Decimal("0.00"),
    near_extreme_distance_bps: Decimal = Decimal("10"),
    distance_to_target_bps: Decimal = Decimal("2"),
    recent_3m_return_bps: Decimal = Decimal("6"),
    recent_3m_range_bps: Decimal = Decimal("12"),
    recent_5m_return_bps: Decimal = Decimal("8"),
    recent_5m_range_bps: Decimal = Decimal("12"),
    trend_confirmation_status: str = "confirmed",
    deceleration_persistence_count: int = 0,
    range_expansion_status: str = "normal",
    ev: Decimal = Decimal("0.10"),
    price: Decimal = Decimal("0.45"),
    progression_memory: ProgressionMemoryState | None = None,
    reversal_probability: Decimal = Decimal("0.20"),
    fake_continuation_signature: bool = False,
    classification_reason: str | None = None,
    signal_conflict_flags: tuple[tuple[str, bool], ...] = (),
):
    return score_candidate_quality(
        return_range_ratio=return_range_ratio,
        ratio_floor=Decimal("0.50"),
        ratio_decay=ratio_decay,
        near_extreme_distance_bps=near_extreme_distance_bps,
        near_extreme_threshold_bps=Decimal("6"),
        recent_5m_range_bps=recent_5m_range_bps,
        recent_5m_return_bps=recent_5m_return_bps,
        lookback_return_bps=Decimal("18"),
        trend_confirmation_status=trend_confirmation_status,
        deceleration_persistence_count=deceleration_persistence_count,
        range_expansion_status=range_expansion_status,
        ev=ev,
        price=price,
        side_needs_cross=False,
        required_bps_per_minute=Decimal("0"),
        required_bps_per_minute_limit=Decimal("0.25"),
        product_volatility_scale=Decimal("1"),
        trend_age_cycles=1,
        failed_attempts=0,
        progression_memory=progression_memory,
        reversal_probability=reversal_probability,
        fake_continuation_signature=fake_continuation_signature,
        classification_reason=classification_reason,
        signal_conflict_flags=signal_conflict_flags,
        distance_to_target_bps=distance_to_target_bps,
        recent_3m_return_bps=recent_3m_return_bps,
        recent_3m_range_bps=recent_3m_range_bps,
    )


def _quiet_conflict_score(**overrides):
    values = {
        "return_range_ratio": Decimal("1.246"),
        "near_extreme_distance_bps": Decimal("10"),
        "distance_to_target_bps": Decimal("0.426"),
        "trend_confirmation_status": "recent_direction_mismatch",
        "progression_memory": None,
        "classification_reason": "quiet_continuation_from_exhaustion",
        "signal_conflict_flags": (("impulse_direction_conflict", True),),
        "price": Decimal("0.61"),
        "ev": Decimal("0.10"),
    }
    values.update(overrides)
    return _score(**values)


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
