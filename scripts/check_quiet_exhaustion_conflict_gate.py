"""Validate the quiet-exhaustion directional-conflict gate."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi_bot.contracts.contract_scorer import score_candidate_quality  # noqa: E402
from kalshi_bot.execution.live_execution_coordinator import (  # noqa: E402
    _ev_filter_status,
    _roadmap_continuation_decision,
)
from kalshi_bot.forecast.progression_memory import ProgressionMemoryState  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check quiet-exhaustion conflict fixtures and optional May 18 replay files.",
    )
    for label in ("may18_0730_0915", "may18_0915_1200"):
        option = label.replace("_", "-")
        parser.add_argument(f"--{option}-roadmap-telemetry")
        parser.add_argument(f"--{option}-execution-events")
        parser.add_argument(f"--{option}-outcomes")
        parser.add_argument(f"--{option}-env-snapshot")
    parser.add_argument("--output")
    args = parser.parse_args()

    failures = _fixture_failures()
    replay_inputs = _replay_inputs(args)
    replay_summary: dict[str, object] = {}
    if replay_inputs:
        replay_summary = {
            label: _summarize_window(
                telemetry_path=paths["roadmap_telemetry"],
                execution_path=paths["execution_events"],
                outcomes_path=paths["outcomes"],
            )
            for label, paths in replay_inputs.items()
        }
        if args.output is None:
            failures.append("May 18 replay requested but --output was not provided")
        else:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(replay_summary, indent=2, sort_keys=True, default=str)
                + "\n",
                encoding="utf-8",
            )

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1
    if replay_summary:
        print(f"quiet exhaustion replay checks passed: {args.output}")
    else:
        print("quiet exhaustion conflict fixture checks passed")
    return 0


def _fixture_failures() -> list[str]:
    failures: list[str] = []
    btc_loser = _quiet_score()
    xrp_loser = _quiet_score(product_id="XRP-USD")
    clean_winner = _quiet_score(
        trend_confirmation_status="confirmed",
        signal_conflict_flags=(("impulse_direction_conflict", False),),
        progression_memory=_memory("strengthening", product_id="BTC-USD"),
    )
    single_conditions = {
        "cold_start_alone": _score(progression_memory=None),
        "recent_direction_mismatch_alone": _score(
            trend_confirmation_status="recent_direction_mismatch"
        ),
        "impulse_conflict_alone": _score(
            signal_conflict_flags=(("impulse_direction_conflict", True),)
        ),
        "ratio_band_alone": _score(return_range_ratio=Decimal("1.25")),
        "tiny_distance_alone": _score(distance_to_target_bps=Decimal("0.426")),
        "high_composite_alone": _score(ev=Decimal("0.25")),
    }
    ratio_above_band = _quiet_score(return_range_ratio=Decimal("2.50"))
    distance_above_band = _quiet_score(distance_to_target_bps=Decimal("1.50"))
    old_high_ratio = _score(
        return_range_ratio=Decimal("3.50"),
        progression_memory=None,
        distance_to_target_bps=Decimal("8"),
        recent_5m_return_bps=Decimal("14"),
        recent_5m_range_bps=Decimal("15"),
    )

    for label, score in {"btc": btc_loser, "xrp": xrp_loser}.items():
        if not score.quiet_exhaustion_direction_conflict_blocked:
            failures.append(f"{label} loser-shaped fixture did not block")
        if score.composite_score != Decimal("0.49"):
            failures.append(f"{label} cap score={score.composite_score}")
        if "quiet_exhaustion_direction_conflict" not in score.downgrade_reasons:
            failures.append(f"{label} downgrade missing")
        if (
            score.hard_gate_statuses.get("quiet_exhaustion_direction_conflict")
            != "blocked"
        ):
            failures.append(f"{label} hard gate missing")
    if clean_winner.quiet_exhaustion_direction_conflict_blocked:
        failures.append("clean quiet continuation winner blocked")
    for label, score in single_conditions.items():
        if score.quiet_exhaustion_direction_conflict_blocked:
            failures.append(f"{label} incorrectly blocked")
    if ratio_above_band.quiet_exhaustion_direction_conflict_blocked:
        failures.append("ratio >2 triggered quiet conflict")
    if distance_above_band.quiet_exhaustion_direction_conflict_blocked:
        failures.append("distance >1 triggered quiet conflict")
    if "cold_start_high_ratio_overextension_blocked" not in old_high_ratio.downgrade_reasons:
        failures.append("old high-ratio gate no longer fires")
    if _score_aware_ev_cap_allows_quiet_conflict():
        failures.append("score-aware EV cap allowed quiet conflict")
    if not _reversal_shadow_only_unchanged():
        failures.append("reversal shadow-only fixture changed")
    if _roadmap_quiet_conflict_allowed():
        failures.append("roadmap continuation decision allowed quiet conflict")
    return failures


def _quiet_score(**overrides: object):
    values: dict[str, object] = {
        "return_range_ratio": Decimal("1.246"),
        "distance_to_target_bps": Decimal("0.426"),
        "trend_confirmation_status": "recent_direction_mismatch",
        "classification_reason": "quiet_continuation_from_exhaustion",
        "signal_conflict_flags": (("impulse_direction_conflict", True),),
        "progression_memory": None,
        "price": Decimal("0.61"),
    }
    values.update(overrides)
    return _score(**values)


def _score(
    *,
    product_id: str = "BTC-USD",
    return_range_ratio: Decimal = Decimal("1.50"),
    ratio_decay: Decimal = Decimal("0.00"),
    near_extreme_distance_bps: Decimal = Decimal("10"),
    distance_to_target_bps: Decimal = Decimal("2"),
    recent_3m_return_bps: Decimal = Decimal("6"),
    recent_3m_range_bps: Decimal = Decimal("12"),
    recent_5m_return_bps: Decimal = Decimal("8"),
    recent_5m_range_bps: Decimal = Decimal("12"),
    trend_confirmation_status: str = "confirmed",
    range_expansion_status: str = "normal",
    ev: Decimal = Decimal("0.10"),
    price: Decimal = Decimal("0.45"),
    progression_memory: ProgressionMemoryState | None = None,
    classification_reason: str | None = None,
    signal_conflict_flags: tuple[tuple[str, bool], ...] = (),
):
    if progression_memory is not None and progression_memory.product_id != product_id:
        progression_memory = _memory(
            progression_memory.progression_continuation_quality,
            product_id=product_id,
        )
    return score_candidate_quality(
        return_range_ratio=return_range_ratio,
        ratio_floor=Decimal("0.50"),
        ratio_decay=ratio_decay,
        near_extreme_distance_bps=near_extreme_distance_bps,
        near_extreme_threshold_bps=Decimal("6"),
        distance_to_target_bps=distance_to_target_bps,
        recent_3m_return_bps=recent_3m_return_bps,
        recent_3m_range_bps=recent_3m_range_bps,
        recent_5m_range_bps=recent_5m_range_bps,
        recent_5m_return_bps=recent_5m_return_bps,
        lookback_return_bps=Decimal("18"),
        trend_confirmation_status=trend_confirmation_status,
        deceleration_persistence_count=0,
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
        reversal_probability=Decimal("0.20"),
        classification_reason=classification_reason,
        signal_conflict_flags=signal_conflict_flags,
    )


def _memory(quality: str, *, product_id: str) -> ProgressionMemoryState:
    return ProgressionMemoryState(
        product_id=product_id,
        sample_count=3,
        trend_age_cycles=3,
        trend_age_seconds=180,
        consecutive_same_side_intents=1,
        failed_continuation_count=0,
        near_extreme_retest_count=1,
        deceleration_persistence_count=0,
        range_expansion_persistence_count=0,
        ratio_decay=Decimal("0.0000"),
        retry_degradation_factor=Decimal("1.0000"),
        itm_strengthening_status="strengthening",
        distance_to_target_worsening=False,
        progression_continuation_quality=quality,
        reversal_buildup_score=Decimal("0.0000"),
        last_direction="up",
        last_market_ticker="KXBTC15M-TEST",
        memory_cold_start=False,
    )


def _score_aware_ev_cap_allows_quiet_conflict() -> bool:
    from scripts.check_phaseF2_live_execution_coordinator import (  # noqa: PLC0415
        _Settings,
        _contract,
        _entry_segment,
        _pricing,
    )

    status = _ev_filter_status(
        contract=_contract(
            midpoint=Decimal("0.72"),
            required_bps_per_minute=Decimal("0.000"),
            composite_score=Decimal("0.75"),
            progression_continuation_quality="cold_start",
            hard_gate_results=(("quiet_exhaustion_direction_conflict", "blocked"),),
        ),
        pricing=_pricing(intent_price=Decimal("0.72")),
        entry_segment=_entry_segment(),
        settings=_Settings(
            log_directory=Path("."),
            log_jsonl_enabled=False,
            live_ev_filter_enabled=True,
            live_ev_max_actual_cost=Decimal("0.80"),
            live_ev_min_reward_dollars=Decimal("0.20"),
            live_score_aware_ev_cap_enabled=True,
            live_score_aware_ev_cap_max_by_product={"BTC-USD": Decimal("0.75")},
        ),
    )
    return status.score_aware_ev_cap_status != "blocked_by_danger"


def _roadmap_quiet_conflict_allowed() -> bool:
    from scripts.check_phaseF2_live_execution_coordinator import (  # noqa: PLC0415
        _Settings,
        _allowed_ev_status,
        _allowed_weak_progression,
        _contract,
    )

    status = _roadmap_continuation_decision(
        contract=_contract(
            hard_gate_results=(("quiet_exhaustion_direction_conflict", "blocked"),),
        ),
        ev_filter=_allowed_ev_status(),
        settings=_Settings(log_directory=Path("."), log_jsonl_enabled=False),
        weak_progression=_allowed_weak_progression(),
    )
    return status.continuation_allowed


def _reversal_shadow_only_unchanged() -> bool:
    from scripts.check_phaseF2_live_execution_coordinator import (  # noqa: PLC0415
        _Settings,
        _allowed_ev_status,
        _allowed_weak_progression,
        _contract,
    )

    status = _roadmap_continuation_decision(
        contract=_contract(
            structure="reversal",
            reversal_candidate_status="shadow_candidate",
        ),
        ev_filter=_allowed_ev_status(),
        settings=_Settings(
            log_directory=Path("."),
            log_jsonl_enabled=False,
            live_reversal_shadow_only=True,
        ),
        weak_progression=_allowed_weak_progression(),
    )
    return status.continuation_allowed and status.reversal_candidate_generated


def _replay_inputs(args: argparse.Namespace) -> dict[str, dict[str, Path]]:
    result: dict[str, dict[str, Path]] = {}
    for label in ("may18_0730_0915", "may18_0915_1200"):
        paths = {
            "roadmap_telemetry": getattr(args, f"{label}_roadmap_telemetry"),
            "execution_events": getattr(args, f"{label}_execution_events"),
            "outcomes": getattr(args, f"{label}_outcomes"),
            "env_snapshot": getattr(args, f"{label}_env_snapshot"),
        }
        provided = {key: value for key, value in paths.items() if value}
        if not provided:
            continue
        if len(provided) != len(paths):
            missing = sorted(set(paths) - set(provided))
            raise SystemExit(f"{label} replay missing explicit paths: {missing}")
        result[label] = {
            key: _required_file(Path(value), f"{label}:{key}")
            for key, value in paths.items()
            if value is not None
        }
    return result


def _summarize_window(
    *,
    telemetry_path: Path,
    execution_path: Path,
    outcomes_path: Path,
) -> dict[str, object]:
    telemetry = _joined_rows(_load_records(telemetry_path), _load_outcomes(outcomes_path))
    execution = _joined_rows(_load_records(execution_path), _load_outcomes(outcomes_path))
    conflict_rows = [row for row in telemetry if _quiet_conflict(row)]
    conflict_winners = [row for row in conflict_rows if row["win"]]
    conflict_losers = [row for row in conflict_rows if not row["win"]]
    execution_conflict_blocks = [
        row for row in execution if _blocking_reason(row) == "quiet_exhaustion_direction_conflict"
    ]
    by_product_side: dict[str, int] = {}
    for row in conflict_rows:
        key = f"{row.get('product_id') or 'unknown'}:{_side(row) or 'unknown'}"
        by_product_side[key] = by_product_side.get(key, 0) + 1
    return {
        "telemetry_rows_matched_to_outcome": len(telemetry),
        "execution_rows_matched_to_outcome": len(execution),
        "quiet_conflict_count": len(conflict_rows),
        "quiet_conflict_losers": len(conflict_losers),
        "quiet_conflict_winners": len(conflict_winners),
        "quiet_conflict_blocks_in_execution": len(execution_conflict_blocks),
        "quiet_conflict_count_by_product_side": by_product_side,
        "estimated_pnl_effect": _estimated_pnl_effect(execution_conflict_blocks),
    }


def _quiet_conflict(row: dict[str, Any]) -> bool:
    return (
        _truthy(row.get("quiet_exhaustion_direction_conflict_blocked"))
        or "quiet_exhaustion_direction_conflict" in _reason_set(row)
        or _blocking_reason(row) == "quiet_exhaustion_direction_conflict"
    )


def _blocking_reason(row: dict[str, Any]) -> str:
    return str(
        row.get("continuation_blocked_reason")
        or row.get("final_blocking_gate")
        or row.get("new_decision")
        or ""
    )


def _estimated_pnl_effect(rows: list[dict[str, Any]]) -> Decimal:
    return sum((row["joined_ev"] for row in rows), Decimal("0")).quantize(
        Decimal("0.0001")
    )


def _joined_rows(
    rows: list[dict[str, Any]],
    outcomes: dict[str, str],
) -> list[dict[str, Any]]:
    joined: list[dict[str, Any]] = []
    for row in rows:
        ticker = _ticker(row)
        side = _side(row)
        outcome = outcomes.get(ticker)
        if not ticker or side not in {"yes", "no"} or outcome not in {"yes", "no"}:
            continue
        price = _decimal(row.get("entry_price") or row.get("price_dollars"))
        win = side == outcome
        ev = Decimal("1") - price if win and price is not None else -(price or Decimal("0"))
        joined.append({**row, "win": win, "joined_ev": ev})
    return joined


def _load_outcomes(path: Path) -> dict[str, str]:
    outcomes: dict[str, str] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            ticker = _normalize(row.get("market_ticker"))
            result = str(row.get("official_result") or "").strip().lower()
            if ticker and result in {"yes", "no"}:
                outcomes[ticker] = result
    return outcomes


def _load_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            payload = row.get("payload") if isinstance(row, dict) else None
            rows.append({**row, **payload} if isinstance(payload, dict) else row)
    return rows


def _ticker(row: dict[str, Any]) -> str:
    for key in ("market_ticker", "contract_ticker", "ticker", "identifier"):
        ticker = _normalize(row.get(key))
        if ticker.startswith("KX"):
            return ticker
    return ""


def _side(row: dict[str, Any]) -> str:
    return str(row.get("side") or row.get("intent_side") or "").strip().lower()


def _reason_set(row: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for key in (
        "candidate_downgrade_reasons",
        "downgrade_reasons",
        "quiet_exhaustion_direction_conflict_reasons",
    ):
        raw = row.get(key)
        if isinstance(raw, str):
            values.update(part.strip(" '\"[]") for part in raw.split(","))
        elif isinstance(raw, list | tuple):
            values.update(str(part) for part in raw)
    return {value for value in values if value}


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _normalize(value: Any) -> str:
    return str(value or "").strip().upper()


def _required_file(path: Path, label: str) -> Path:
    if not path.exists():
        raise SystemExit(f"{label} file does not exist: {path}")
    if not path.is_file():
        raise SystemExit(f"{label} must be a file: {path}")
    return path


if __name__ == "__main__":
    raise SystemExit(main())
