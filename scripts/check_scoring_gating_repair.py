"""Validate scoring/gating repair against explicit May 15/16 audit exports."""

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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate scoring/gating repair with explicit audit files.",
    )
    parser.add_argument("--may15-roadmap-telemetry", required=True)
    parser.add_argument("--may15-execution-events", required=True)
    parser.add_argument("--may15-outcomes", required=True)
    parser.add_argument("--may15-env-snapshot", required=True)
    parser.add_argument("--may15-chart-dir", required=True)
    parser.add_argument("--may16-roadmap-telemetry", required=True)
    parser.add_argument("--may16-execution-events", required=True)
    parser.add_argument("--may16-outcomes", required=True)
    parser.add_argument("--may16-env-snapshot", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    may15 = _load_audit(
        label="may15",
        roadmap_path=_required_file(args.may15_roadmap_telemetry, "--may15-roadmap-telemetry"),
        execution_path=_required_file(args.may15_execution_events, "--may15-execution-events"),
        outcomes_path=_required_file(args.may15_outcomes, "--may15-outcomes"),
        env_path=_required_file(args.may15_env_snapshot, "--may15-env-snapshot"),
        chart_dir=_required_dir(args.may15_chart_dir, "--may15-chart-dir"),
    )
    may16 = _load_audit(
        label="may16",
        roadmap_path=_required_file(args.may16_roadmap_telemetry, "--may16-roadmap-telemetry"),
        execution_path=_required_file(args.may16_execution_events, "--may16-execution-events"),
        outcomes_path=_required_file(args.may16_outcomes, "--may16-outcomes"),
        env_path=_required_file(args.may16_env_snapshot, "--may16-env-snapshot"),
        chart_dir=None,
    )
    summary = {"may15": may15, "may16": may16}
    failures = tuple(may15["failures"]) + tuple(may16["failures"])
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1
    print(f"Scoring/gating repair checks passed: {output_path}")
    return 0


def _load_audit(
    *,
    label: str,
    roadmap_path: Path,
    execution_path: Path,
    outcomes_path: Path,
    env_path: Path,
    chart_dir: Path | None,
) -> dict[str, object]:
    roadmap = _load_records(roadmap_path)
    execution = _load_records(execution_path)
    outcomes = _outcomes_by_market(_load_records(outcomes_path))
    env_snapshot = _load_records(env_path)
    chart_csv_count = (
        len(tuple(chart_dir.glob("*.csv"))) if chart_dir is not None else None
    )
    failures: list[str] = []
    if not roadmap:
        failures.append(f"{label}: roadmap telemetry empty")
    if not execution:
        failures.append(f"{label}: execution events empty")
    if not outcomes:
        failures.append(f"{label}: official outcomes unmapped")
    if not env_snapshot:
        failures.append(f"{label}: env snapshot empty")
    if chart_dir is not None and not chart_csv_count:
        failures.append(f"{label}: chart directory has no csv files")

    mapping_debug = _mapping_debug(
        telemetry=roadmap,
        execution=execution,
        outcomes=outcomes,
    )
    joined_attempts = _joined_attempts(execution, outcomes)
    danger_high_scores = [
        row
        for row in roadmap
        if (_decimal(row.get("composite_score")) or Decimal("0")) > Decimal("0.90")
        and _has_danger_flag(row)
    ]
    if danger_high_scores:
        failures.append(
            f"{label}: danger-flag rows above 0.90={len(danger_high_scores)}"
        )
    danger_allows = [
        row
        for row in roadmap
        if _has_decisive_danger(row) and _continuation_allowed(row)
    ]
    if danger_allows:
        failures.append(
            f"{label}: decisive danger continuations allowed={len(danger_allows)}"
        )
    high = [row for row in joined_attempts if row["score"] >= Decimal("0.60")]
    low = [row for row in joined_attempts if row["score"] < Decimal("0.60")]
    high_wr = _win_rate(high)
    low_wr = _win_rate(low)
    if high and low and high_wr < low_wr:
        failures.append(
            f"{label}: score inversion high_wr={high_wr} low_wr={low_wr}"
        )
    return {
        "roadmap_rows": len(roadmap),
        "execution_rows": len(execution),
        "outcome_markets": len(outcomes),
        "outcomes_loaded_count": mapping_debug["outcomes_loaded_count"],
        "telemetry_rows_with_market_ticker": mapping_debug[
            "telemetry_rows_with_market_ticker"
        ],
        "telemetry_rows_matched_to_outcome": mapping_debug[
            "telemetry_rows_matched_to_outcome"
        ],
        "execution_rows_with_ticker": mapping_debug["execution_rows_with_ticker"],
        "execution_rows_matched_to_outcome": mapping_debug[
            "execution_rows_matched_to_outcome"
        ],
        "telemetry_unmatched_tickers_first5": mapping_debug[
            "telemetry_unmatched_tickers_first5"
        ],
        "execution_unmatched_tickers_first5": mapping_debug[
            "execution_unmatched_tickers_first5"
        ],
        "env_rows": len(env_snapshot),
        "chart_csv_count": chart_csv_count,
        "attempted_side_win_rate": _win_rate(joined_attempts),
        "opposite_side_win_rate": _opposite_win_rate(joined_attempts),
        "attempted_side_ev": _average_ev(joined_attempts),
        "high_score_attempted_side_win_rate": high_wr,
        "low_score_attempted_side_win_rate": low_wr,
        "danger_high_score_count": len(danger_high_scores),
        "danger_allowed_count": len(danger_allows),
        "cold_start_high_ratio_overextension_count": sum(
            1
            for row in roadmap
            if "cold_start_high_ratio_overextension_blocked"
            in _reason_set(row)
        ),
        "high_score_danger_cap_count": sum(
            1 for row in roadmap if _truthy(row.get("high_score_danger_cap_applied"))
        ),
        "failures": failures,
    }


def _joined_attempts(
    execution: list[dict[str, Any]],
    outcomes: dict[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in execution:
        event_type = str(row.get("event_type") or row.get("message_type") or "")
        if event_type and event_type not in {
            "live_intent_created",
            "live_order_submitted",
            "order_filled",
            "live_position_opened",
        }:
            continue
        market = _execution_ticker(row)
        side = _side(row)
        outcome = outcomes.get(market)
        if not market or side not in {"yes", "no"} or outcome not in {"yes", "no"}:
            continue
        price = _decimal(
            row.get("entry_price")
            or row.get("price_dollars")
            or row.get("intent_price_dollars")
        )
        score = _decimal(row.get("composite_score")) or Decimal("0")
        win = side == outcome
        ev = None
        if price is not None:
            ev = (Decimal("1") - price) if win else -price
        rows.append({"score": score, "win": win, "price": price, "ev": ev})
    return rows


def _outcomes_by_market(records: list[dict[str, Any]]) -> dict[str, str]:
    outcomes: dict[str, str] = {}
    for row in records:
        market = _normalize_ticker(row.get("market_ticker"))
        side = str(row.get("official_result") or "").strip().lower()
        if side not in {"yes", "no"}:
            side = _outcome_side(row)
        if market and side in {"yes", "no"}:
            outcomes[market] = side
    return outcomes


def _mapping_debug(
    *,
    telemetry: list[dict[str, Any]],
    execution: list[dict[str, Any]],
    outcomes: dict[str, str],
) -> dict[str, object]:
    telemetry_tickers = [_telemetry_ticker(row) for row in telemetry]
    execution_tickers = [_execution_ticker(row) for row in execution]
    telemetry_present = [ticker for ticker in telemetry_tickers if ticker]
    execution_present = [ticker for ticker in execution_tickers if ticker]
    telemetry_unmatched = [
        ticker for ticker in telemetry_present if ticker not in outcomes
    ]
    execution_unmatched = [
        ticker for ticker in execution_present if ticker not in outcomes
    ]
    return {
        "outcomes_loaded_count": len(outcomes),
        "telemetry_rows_with_market_ticker": len(telemetry_present),
        "telemetry_rows_matched_to_outcome": sum(
            1 for ticker in telemetry_present if ticker in outcomes
        ),
        "execution_rows_with_ticker": len(execution_present),
        "execution_rows_matched_to_outcome": sum(
            1 for ticker in execution_present if ticker in outcomes
        ),
        "telemetry_unmatched_tickers_first5": _first_unique(telemetry_unmatched, 5),
        "execution_unmatched_tickers_first5": _first_unique(execution_unmatched, 5),
    }


def _has_danger_flag(row: dict[str, Any]) -> bool:
    reasons = _reason_set(row)
    return bool(
        reasons
        & {
            "progression_weakening",
            "persistent_deceleration",
            "fake_continuation_signature",
            "weak_recent_return",
            "high_reversal_probability",
            "near_extreme_danger_combo",
            "cold_start_high_ratio_overextension_blocked",
            "high_reversal_probability_with_danger",
        }
    ) or bool(row.get("fake_continuation_signature"))


def _has_decisive_danger(row: dict[str, Any]) -> bool:
    reasons = _reason_set(row)
    return bool(
        reasons
        & {
            "progression_weakening",
            "persistent_deceleration",
            "continuation_major_danger",
            "near_extreme_danger_combo",
            "cold_start_high_ratio_overextension_blocked",
        }
    )


def _reason_set(row: dict[str, Any]) -> set[str]:
    return {
        str(item)
        for item in (
            row.get("candidate_downgrade_reasons")
            or row.get("downgrade_reasons")
            or []
        )
    }


def _continuation_allowed(row: dict[str, Any]) -> bool:
    if row.get("continuation_allowed") is True:
        return True
    decision = str(row.get("new_decision") or row.get("decision") or "")
    return decision == "allow_continuation"


def _win_rate(rows: list[dict[str, Any]]) -> Decimal | None:
    if not rows:
        return None
    wins = sum(1 for row in rows if row["win"])
    return (Decimal(wins) / Decimal(len(rows))).quantize(Decimal("0.0001"))


def _opposite_win_rate(rows: list[dict[str, Any]]) -> Decimal | None:
    if not rows:
        return None
    losses = sum(1 for row in rows if not row["win"])
    return (Decimal(losses) / Decimal(len(rows))).quantize(Decimal("0.0001"))


def _average_ev(rows: list[dict[str, Any]]) -> Decimal | None:
    values = [row["ev"] for row in rows if row["ev"] is not None]
    if not values:
        return None
    return (sum(values, Decimal("0")) / Decimal(len(values))).quantize(
        Decimal("0.0001")
    )


def _load_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        if isinstance(data, dict):
            for key in ("records", "rows", "outcomes", "events"):
                nested = data.get(key)
                if isinstance(nested, list):
                    return [row for row in nested if isinstance(row, dict)]
            if all(isinstance(value, dict) for value in data.values()):
                return [
                    {"market_ticker": key, **value}
                    for key, value in data.items()
                    if isinstance(value, dict)
                ]
            return [data]
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                if "=" in line:
                    key, value = line.strip().split("=", 1)
                    records.append({key: value})
                    continue
                raise
            payload = row.get("payload") if isinstance(row, dict) else None
            if isinstance(payload, dict):
                records.append({**row, **payload})
            elif isinstance(row, dict):
                records.append(row)
    return records


def _required_file(value: str, label: str) -> Path:
    path = Path(value)
    if not path.exists():
        raise SystemExit(f"{label} does not exist: {path}")
    if not path.is_file():
        raise SystemExit(f"{label} must be a file: {path}")
    return path


def _required_dir(value: str, label: str) -> Path:
    path = Path(value)
    if not path.exists():
        raise SystemExit(f"{label} does not exist: {path}")
    if not path.is_dir():
        raise SystemExit(f"{label} must be a directory: {path}")
    return path


def _market(row: dict[str, Any]) -> str:
    return _telemetry_ticker(row)


def _telemetry_ticker(row: dict[str, Any]) -> str:
    ticker = _direct_payload_ticker(row)
    if ticker:
        return ticker
    return _identifier_ticker(row)


def _execution_ticker(row: dict[str, Any]) -> str:
    ticker = _direct_payload_ticker(row)
    if ticker:
        return ticker
    for path in (
        ("order", "market_ticker"),
        ("response", "market_ticker"),
        ("position", "market_ticker"),
        ("payload", "order", "market_ticker"),
        ("payload", "response", "market_ticker"),
        ("payload", "position", "market_ticker"),
    ):
        ticker = _normalize_ticker(_nested_value(row, path))
        if ticker:
            return ticker
    return _identifier_ticker(row)


def _direct_payload_ticker(row: dict[str, Any]) -> str:
    for key in ("market_ticker", "contract_ticker", "ticker"):
        ticker = _normalize_ticker(row.get(key))
        if ticker:
            return ticker
    payload = row.get("payload")
    if isinstance(payload, dict):
        for key in ("market_ticker", "contract_ticker", "ticker"):
            ticker = _normalize_ticker(payload.get(key))
            if ticker:
                return ticker
    return ""


def _identifier_ticker(row: dict[str, Any]) -> str:
    for key in ("identifier", "market_identifier", "contract_identifier"):
        ticker = _normalize_ticker(row.get(key))
        if ticker and _ticker_like(ticker):
            return ticker
    payload = row.get("payload")
    if isinstance(payload, dict):
        for key in ("identifier", "market_identifier", "contract_identifier"):
            ticker = _normalize_ticker(payload.get(key))
            if ticker and _ticker_like(ticker):
                return ticker
    return ""


def _normalize_ticker(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()


def _ticker_like(value: str) -> bool:
    return bool(value and value.startswith("KX") and "-" in value and " " not in value)


def _nested_value(row: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = row
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _first_unique(values: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
        if len(unique) >= limit:
            break
    return unique


def _side(row: dict[str, Any]) -> str:
    return str(row.get("side") or row.get("intent_side") or "").strip().lower()


def _outcome_side(row: dict[str, Any]) -> str:
    for key in (
        "official_result",
        "winning_side",
        "result_side",
        "official_outcome",
        "outcome",
        "settlement",
    ):
        value = str(row.get(key) or "").strip().lower()
        if value in {"yes", "no"}:
            return value
    yes_won = str(row.get("yes_won") or "").strip().lower()
    no_won = str(row.get("no_won") or "").strip().lower()
    if yes_won in {"1", "true", "yes"}:
        return "yes"
    if no_won in {"1", "true", "yes"}:
        return "no"
    return ""


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
    return str(value).strip().lower() in {"1", "true", "yes"}


if __name__ == "__main__":
    raise SystemExit(main())
