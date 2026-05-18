"""Validate final scoring calibration with explicit post-fix audit exports."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate final scoring calibration with explicit audit files.",
    )
    audit_args = (
        ("may16", "may16"),
        ("may17_overnight", "may17-overnight"),
        ("may17_slim", "may17-slim"),
    )
    for dest_prefix, option_prefix in audit_args:
        parser.add_argument(
            f"--{option_prefix}-roadmap-telemetry",
            dest=f"{dest_prefix}_roadmap_telemetry",
            required=True,
        )
        parser.add_argument(
            f"--{option_prefix}-execution-events",
            dest=f"{dest_prefix}_execution_events",
            required=True,
        )
        parser.add_argument(
            f"--{option_prefix}-outcomes",
            dest=f"{dest_prefix}_outcomes",
            required=True,
        )
        parser.add_argument(
            f"--{option_prefix}-env-snapshot",
            dest=f"{dest_prefix}_env_snapshot",
            required=True,
        )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    summaries = {
        label: _summarize_audit(
            label=label,
            telemetry_path=_required_file(
                getattr(args, f"{label}_roadmap_telemetry"),
                f"--{label}-roadmap-telemetry",
            ),
            execution_path=_required_file(
                getattr(args, f"{label}_execution_events"),
                f"--{label}-execution-events",
            ),
            outcomes_path=_required_file(
                getattr(args, f"{label}_outcomes"),
                f"--{label}-outcomes",
            ),
            env_path=_required_file(
                getattr(args, f"{label}_env_snapshot"),
                f"--{label}-env-snapshot",
            ),
        )
        for label, _option_prefix in audit_args
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(summaries, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    failures = [
        f"{label}: {failure}"
        for label, summary in summaries.items()
        for failure in summary["failures"]
    ]
    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1
    print(f"Final scoring calibration checks passed: {output_path}")
    return 0


def _summarize_audit(
    *,
    label: str,
    telemetry_path: Path,
    execution_path: Path,
    outcomes_path: Path,
    env_path: Path,
) -> dict[str, object]:
    telemetry = _load_records(telemetry_path)
    execution = _load_records(execution_path)
    outcomes = _load_outcomes(outcomes_path)
    env_rows = _load_records(env_path)
    execution_attempts = _joined_rows(execution, outcomes)
    telemetry_rows = _joined_rows(telemetry, outcomes)
    losers_removed = [
        row for row in execution_attempts if not row["win"] and _new_blocks(row)
    ]
    winners_lost = [
        row for row in execution_attempts if row["win"] and _new_blocks(row)
    ]
    skipped_winners_admitted = [
        row
        for row in telemetry_rows
        if row["win"]
        and str(row.get("event_type") or row.get("record_type") or "").endswith(
            "skipped"
        )
        and not _new_blocks(row)
    ]
    high_score_rows = [
        row
        for row in telemetry_rows
        if (_decimal(row.get("composite_score")) or Decimal("0"))
        >= Decimal("0.80")
    ]
    high_score_winners = sum(1 for row in high_score_rows if row["win"])
    failures: list[str] = []
    if not telemetry:
        failures.append("roadmap telemetry empty")
    if not outcomes:
        failures.append("official outcomes unmapped")
    if not env_rows:
        failures.append("env snapshot empty")
    return {
        "label": label,
        "telemetry_rows": len(telemetry),
        "execution_rows": len(execution),
        "outcomes_loaded_count": len(outcomes),
        "execution_rows_matched_to_outcome": len(execution_attempts),
        "telemetry_rows_matched_to_outcome": len(telemetry_rows),
        "losers_removed": len(losers_removed),
        "winners_lost": len(winners_lost),
        "skipped_winners_admitted": len(skipped_winners_admitted),
        "estimated_pnl_effect": -_sum_ev(losers_removed) - _sum_ev(winners_lost),
        "high_score_win_rate": (
            (Decimal(high_score_winners) / Decimal(len(high_score_rows))).quantize(
                Decimal("0.0001")
            )
            if high_score_rows
            else None
        ),
        "high_score_rows": len(high_score_rows),
        "high_score_danger_cap_count": sum(
            1 for row in telemetry if _truthy(row.get("high_score_danger_cap_applied"))
        ),
        "cold_start_high_ratio_block_count": sum(
            1
            for row in telemetry
            if "cold_start_high_ratio_overextension_blocked" in _reason_set(row)
        ),
        "failures": failures,
    }


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
        price = _decimal(
            row.get("entry_price")
            or row.get("price_dollars")
            or row.get("intent_price_dollars")
        )
        win = side == outcome
        ev = None
        if price is not None:
            ev = Decimal("1") - price if win else -price
        joined.append({**row, "win": win, "joined_ev": ev})
    return joined


def _new_blocks(row: dict[str, Any]) -> bool:
    reason = str(
        row.get("continuation_blocked_reason")
        or row.get("final_blocking_gate")
        or row.get("new_decision")
        or ""
    )
    if reason and reason not in {"allow_continuation", "generate_reversal"}:
        return True
    score = _decimal(row.get("composite_score"))
    return score is not None and score < Decimal("0.60")


def _sum_ev(rows: list[dict[str, Any]]) -> Decimal:
    values = [row["joined_ev"] for row in rows if row.get("joined_ev") is not None]
    return sum(values, Decimal("0")).quantize(Decimal("0.0001"))


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
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                if "=" in line:
                    key, value = line.strip().split("=", 1)
                    rows.append({key: value})
                continue
            payload = row.get("payload") if isinstance(row, dict) else None
            if isinstance(payload, dict):
                rows.append({**row, **payload})
            elif isinstance(row, dict):
                rows.append(row)
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
    return {
        str(item)
        for item in (
            row.get("candidate_downgrade_reasons")
            or row.get("downgrade_reasons")
            or []
        )
    }


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def _normalize(value: Any) -> str:
    return "" if value is None else str(value).strip().upper()


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _required_file(value: str, label: str) -> Path:
    path = Path(value)
    if not path.exists():
        raise SystemExit(f"{label} does not exist: {path}")
    if not path.is_file():
        raise SystemExit(f"{label} must be a file: {path}")
    return path


if __name__ == "__main__":
    raise SystemExit(main())
