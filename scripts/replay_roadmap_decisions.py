"""Replay logged candidates through the roadmap scoring model."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi_bot.contracts.contract_scorer import score_candidate_quality  # noqa: E402
from kalshi_bot.contracts.reversal_classifier import (
    classify_reversal_probability,
    reversal_expected_value,
)  # noqa: E402
from kalshi_bot.forecast.adaptive_thresholds import adaptive_thresholds_for_product  # noqa: E402


def replay_events(
    *,
    events_path: Path,
    output_path: Path,
    context_index_path: Path | None = None,
    outcomes_path: Path | None = None,
    env_snapshot_path: Path | None = None,
) -> None:
    _validate_existing_file(events_path, "--events")
    _validate_optional_file(context_index_path, "--context-index")
    _validate_optional_file(outcomes_path, "--outcomes")
    _validate_optional_file(env_snapshot_path, "--env-snapshot")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("r", encoding="utf-8") as source, output_path.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as sink:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            event = json.loads(line)
            payload = _payload(event)
            decision = _roadmap_decision(payload, line_number=line_number)
            sink.write(json.dumps(decision, sort_keys=True, default=str) + "\n")


def _roadmap_decision(payload: dict[str, Any], *, line_number: int) -> dict[str, Any]:
    product_id = str(payload.get("product_id") or payload.get("product") or "").upper()
    if not product_id:
        product_id = "UNKNOWN"
    ratio = _return_range_ratio(
        _decimal(payload.get("lookback_return_bps")),
        _decimal(payload.get("recent_5m_range_bps")),
    )
    near_distance = _near_extreme_distance(payload)
    thresholds = adaptive_thresholds_for_product(
        product_id=product_id,
        recent_5m_range_bps=_decimal(payload.get("recent_5m_range_bps")),
        adaptive_enabled=True,
        adaptive_chop_enabled=True,
        adaptive_pacing_enabled=True,
    )
    reversal = classify_reversal_probability(
        return_range_ratio=ratio,
        ratio_floor=thresholds.adaptive_ratio_floor,
        near_extreme_distance_bps=near_distance,
        near_extreme_threshold_bps=thresholds.adaptive_near_extreme_bps,
        deceleration_status=str(payload.get("momentum_deceleration_status") or ""),
        range_expansion_status=str(payload.get("range_expansion_status") or ""),
        trend_confirmation_status=str(payload.get("trend_confirmation_status") or ""),
        required_bps_per_minute=_decimal(payload.get("required_bps_per_minute")),
        memory_state=None,
    )
    entry_price = _decimal(
        payload.get("entry_price")
        or payload.get("price_dollars")
        or payload.get("midpoint")
        or payload.get("ev_cost_price")
    )
    opposite_price = _decimal(payload.get("ev_opposite_price"))
    if opposite_price is None and entry_price is not None:
        opposite_price = (Decimal("1") - entry_price).quantize(Decimal("0.0001"))
    reversal_ev = reversal_expected_value(
        reversal_probability=reversal.reversal_probability,
        executable_price=opposite_price,
    )
    score = score_candidate_quality(
        return_range_ratio=ratio,
        ratio_floor=thresholds.adaptive_ratio_floor,
        ratio_decay=None,
        near_extreme_distance_bps=near_distance,
        near_extreme_threshold_bps=thresholds.adaptive_near_extreme_bps,
        distance_to_target_bps=_decimal(payload.get("distance_to_target_bps")),
        recent_3m_return_bps=_decimal(payload.get("recent_3m_return_bps")),
        recent_3m_range_bps=_decimal(payload.get("recent_3m_range_bps")),
        recent_5m_range_bps=_decimal(payload.get("recent_5m_range_bps")),
        recent_5m_return_bps=_decimal(payload.get("recent_5m_return_bps")),
        lookback_return_bps=_decimal(payload.get("lookback_return_bps")),
        trend_confirmation_status=str(payload.get("trend_confirmation_status") or ""),
        deceleration_persistence_count=(
            1
            if str(payload.get("momentum_deceleration_status") or "")
            in {"decelerating_after_burst", "bursting", "still_moving"}
            else 0
        ),
        range_expansion_status=str(payload.get("range_expansion_status") or ""),
        ev=_decimal(payload.get("ev_score")),
        price=entry_price,
        side_needs_cross=bool(payload.get("side_needs_cross")),
        required_bps_per_minute=_decimal(payload.get("required_bps_per_minute")),
        required_bps_per_minute_limit=thresholds.adaptive_required_bps_per_minute_limit,
        product_volatility_scale=thresholds.product_volatility_scale,
        trend_age_cycles=0,
        failed_attempts=0,
        progression_memory=None,
        reversal_probability=reversal.reversal_probability,
        fake_continuation_signature=reversal.fake_continuation_signature,
    )
    reversal_allowed = (
        reversal.reversal_probability >= Decimal("0.55")
        and opposite_price is not None
        and opposite_price <= Decimal("0.60")
        and reversal_ev is not None
        and reversal_ev >= Decimal("0.00")
        and not bool(payload.get("side_needs_cross"))
    )
    high_reversal_invalid = (
        reversal.reversal_probability >= Decimal("0.55")
        and not reversal_allowed
        and (
            reversal.fake_continuation_signature
            or "continuation_major_danger" in score.downgrade_reasons
            or "cold_start_high_ratio_overextension_blocked"
            in score.downgrade_reasons
        )
    )
    if bool(payload.get("side_needs_cross")):
        new_decision = "block_needs_cross"
    elif high_reversal_invalid:
        new_decision = "block_high_reversal_invalid_opposite_ev"
    elif reversal_allowed:
        new_decision = "generate_reversal"
    elif score.composite_score >= Decimal("0.60"):
        new_decision = "allow_continuation"
    else:
        new_decision = "block"
    return {
        "line_number": line_number,
        "product_id": product_id,
        "market_ticker": payload.get("market_ticker") or payload.get("ticker"),
        "old_reason": payload.get("reason"),
        "new_decision": new_decision,
        "composite_score": score.composite_score,
        "continuation_score": score.continuation_score,
        "reversal_score": score.reversal_score,
        "uncapped_composite_score": score.uncapped_composite_score,
        "capped_composite_score": score.capped_composite_score,
        "high_score_danger_cap_applied": score.high_score_danger_cap_applied,
        "high_score_danger_cap_reason": score.high_score_danger_cap_reason,
        "return_range_ratio": ratio,
        "near_extreme_distance_bps": near_distance,
        "distance_to_target_abs_bps": score.distance_to_target_abs_bps,
        "overextension_distance_bps": score.overextension_distance_bps,
        "side_adjusted_distance_status": score.side_adjusted_distance_status,
        "burst_context_status": score.burst_context_status,
        "cold_start_high_ratio_overextension_reasons": (
            score.cold_start_high_ratio_overextension_reasons
        ),
        "continuation_major_danger_combo_blocked": (
            score.continuation_major_danger_combo_blocked
        ),
        "continuation_major_danger_combo_reasons": (
            score.continuation_major_danger_combo_reasons
        ),
        "adaptive_near_extreme_bps": thresholds.adaptive_near_extreme_bps,
        "adaptive_ratio_floor": thresholds.adaptive_ratio_floor,
        "reversal_probability": reversal.reversal_probability,
        "reversal_signal_source": (
            "fake_continuation_classifier"
            if reversal.fake_continuation_signature
            else "probability_context"
            if reversal.reversal_probability >= Decimal("0.55")
            else "low_probability"
        ),
        "reversal_probability_bucket": (
            "high"
            if reversal.reversal_probability >= Decimal("0.65")
            else "qualified"
            if reversal.reversal_probability >= Decimal("0.55")
            else "low"
        ),
        "opposite_executable_price": opposite_price,
        "opposite_side_price": opposite_price,
        "opposite_side_ev": reversal_ev,
        "opposite_side_needs_cross": bool(payload.get("side_needs_cross")),
        "opposite_side_required_bps_ok": (
            _decimal(payload.get("required_bps_per_minute")) is not None
            and _decimal(payload.get("required_bps_per_minute"))
            <= thresholds.adaptive_required_bps_per_minute_limit
        ),
        "reversal_shadow_only": True,
        "reversal_expected_value": reversal_ev,
        "reversal_candidate_status": (
            "shadow_candidate" if reversal_allowed else "rejected"
        ),
        "reversal_rejection_reason": None if reversal_allowed else reversal.rejection_reason,
        "continuation_allowed": new_decision == "allow_continuation",
        "continuation_blocked_reason": (
            None if new_decision == "allow_continuation" else new_decision
        ),
        "reversal_candidate_generated": reversal_allowed,
        "reversal_rejected_reason": None if reversal_allowed else reversal.rejection_reason,
        "final_blocking_gate": (
            None if new_decision in {"allow_continuation", "generate_reversal"} else new_decision
        ),
        "score_components": score.component_scores,
        "downgrade_reasons": score.downgrade_reasons,
        "upgrade_reasons": score.bonus_reasons,
    }


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    if isinstance(payload, dict):
        return payload
    return event


def _return_range_ratio(
    lookback_return_bps: Decimal | None,
    recent_5m_range_bps: Decimal | None,
) -> Decimal | None:
    if lookback_return_bps is None or recent_5m_range_bps is None:
        return None
    if recent_5m_range_bps <= Decimal("0"):
        return None
    return (abs(lookback_return_bps) / recent_5m_range_bps).quantize(Decimal("0.0001"))


def _near_extreme_distance(payload: dict[str, Any]) -> Decimal | None:
    values = [
        _decimal(payload.get("near_extreme_distance_bps")),
        _decimal(payload.get("distance_to_recent_high_bps")),
        _decimal(payload.get("distance_to_recent_low_bps")),
    ]
    values = [value for value in values if value is not None]
    return min(values) if values else None


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay logged candidates through deterministic roadmap scoring.",
    )
    parser.add_argument("--events", required=True)
    parser.add_argument("--context-index")
    parser.add_argument("--outcomes")
    parser.add_argument("--env-snapshot")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    replay_events(
        events_path=Path(args.events),
        context_index_path=Path(args.context_index) if args.context_index else None,
        outcomes_path=Path(args.outcomes) if args.outcomes else None,
        env_snapshot_path=Path(args.env_snapshot) if args.env_snapshot else None,
        output_path=Path(args.output),
    )


def _validate_existing_file(path: Path, label: str) -> None:
    if not path.exists():
        raise SystemExit(f"{label} file does not exist: {path}")
    if not path.is_file():
        raise SystemExit(f"{label} must be a file: {path}")


def _validate_optional_file(path: Path | None, label: str) -> None:
    if path is None:
        return
    _validate_existing_file(path, label)


if __name__ == "__main__":
    main()
