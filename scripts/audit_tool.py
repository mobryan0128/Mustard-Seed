"""Read-only historical audit helper for runtime logs.

Validation commands:

    python scripts/audit_tool.py inspect-repo
    python scripts/audit_tool.py inspect-logs
    python scripts/audit_tool.py field-presence --start <small window> --end <small window>
    python scripts/audit_tool.py build-dataset --start <small window> --end <small window> --out export_logs/test_agent_dataset --package
    python scripts/audit_tool.py raw-around --timestamp <known timestamp> --seconds 300 --out export_logs/test_raw_around.jsonl

This tool is read-only with respect to trading behavior. It does not submit
orders, restart services, edit .env, or change strategy/scoring/gating logic.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
PRODUCT_IDS = ("BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "DOGE-USD", "BNB-USD", "HYPE-USD")
SESSION_SECONDS = 15 * 60
TICKER_RE = re.compile(
    r"^(?P<series>KX[A-Z0-9]+)-"
    r"(?P<year>\d{2})(?P<month>[A-Z]{3})(?P<day>\d{2})(?P<hour>\d{2})(?P<minute>\d{2})-"
)
MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}

KEY_FILES = (
    "kalshi_bot/config/settings.py",
    "kalshi_bot/contracts/contract_scanner.py",
    "kalshi_bot/contracts/contract_scorer.py",
    "kalshi_bot/execution/live_execution_coordinator.py",
    "kalshi_bot/runner/orchestrator.py",
    "kalshi_bot/risk/risk_manager.py",
    "kalshi_bot/forecast/bias_engine.py",
    "kalshi_bot/forecast/progression_memory.py",
    "kalshi_bot/forecast/adaptive_thresholds.py",
    "scripts/export_official_kalshi_outcomes.py",
)
IMPORTANT_FIELDS = (
    "market_ticker",
    "product_id",
    "live_order_intent_skipped",
    "live_position_opened",
    "live_intent_created",
    "order_filled",
    "profit_capture_exit_triggered",
    "classification_reason",
    "progression_continuation_quality",
    "return_range_ratio",
    "distance_to_target_abs_bps",
    "side_currently_itm",
    "side_needs_cross",
    "required_bps_per_minute",
    "trend_confirmation_status",
    "signal_conflict_flags",
    "reversal_probability",
    "reversal_expected_value",
    "reversal_shadow_only",
    "opposite_side_price",
    "opposite_side_ev",
    "ev_filter_status",
    "ev_filter_reason",
    "score_aware_ev_cap_status",
    "score_aware_ev_cap_reason",
    "final_blocking_gate",
    "hard_gate_results",
    "cold_start_high_ratio_overextension_reasons",
    "quiet_exhaustion_direction_conflict",
    "quiet_exhaustion_direction_conflict_blocked",
    "high_score_danger_cap_applied",
    "continuation_major_danger_combo_blocked",
    "repricing_gap",
    "stale_side_available",
    "time_since_last_spot_update_ms",
    "time_since_last_kalshi_update_ms",
    "time_since_spot_move_bps_threshold_ms",
    "max_favorable_price_since_entry",
    "profit_capture_trigger_price",
    "profit_capture_trigger_time",
)
REASON_FIELDS = (
    "reason",
    "final_blocking_gate",
    "ev_filter_reason",
    "ev_block_reason",
    "continuation_blocked_reason",
    "entry_segment_status",
    "product_session_pacing_status",
    "mid_price_confirmation_status",
    "execution_safety_reason",
    "quiet_continuation_block_reason",
    "quiet_continuation_allowed_reason",
    "hard_gate_results",
    "candidate_downgrade_reasons",
    "candidate_upgrade_reasons",
    "top_skip_reasons",
    "reversal_rejected_reason",
    "reversal_rejection_reason",
    "required_bps_rejection_reason",
)
IMPORTANT_REPRESENTATIVE_REASONS = (
    "ev_filter_blocked",
    "ev_actual_cost_above_limit",
    "ev_reward_below_limit",
    "ev_negative_cost_expected_value",
    "needs_cross_blocked",
    "required_bps_missing",
    "required_bps_per_minute_too_high",
    "entry_segment_budget_exhausted",
    "product_session_pacing_blocked",
    "mid_price_confirmation_required",
    "composite_quality_blocked",
    "cold_start_high_ratio_overextension",
    "quiet_exhaustion_direction_conflict",
    "fake_continuation_signature",
    "persistent_deceleration_blocked",
    "flip_persistence_blocked",
    "no_ranked_contracts",
    "neutral_bias",
    "execution_safety_blocked",
    "executable_price_above_scanner_premium",
    "reversal_price_blocked",
    "reversal_probability_blocked",
)
EXECUTED_EVENTS = {"live_position_opened", "order_filled", "live_order_submitted", "live_intent_created"}
SKIP_EVENTS = {"live_order_intent_skipped", "live_submission_blocked", "cycle_completed", "candidate_funnel_summary"}
SENSITIVE_TOKENS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PRIVATE", "API")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only audit tool for historical Kalshi bot logs.")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect_repo = sub.add_parser("inspect-repo")
    inspect_repo.set_defaults(func=cmd_inspect_repo)

    inspect_logs = sub.add_parser("inspect-logs")
    inspect_logs.add_argument("--logs-dir", type=Path, default=Path("logs"))
    inspect_logs.set_defaults(func=cmd_inspect_logs)

    build = sub.add_parser("build-dataset")
    build.add_argument("--start", required=True)
    build.add_argument("--end", required=True)
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--package", action="store_true")
    build.add_argument("--logs-dir", type=Path, default=Path("logs"))
    build.add_argument("--env-file", type=Path, default=Path(".env"))
    build.add_argument("--charts-dir", type=Path)
    build.add_argument("--around-seconds", type=int, default=240)
    build.add_argument("--max-representative-per-reason", type=int, default=40)
    build.add_argument("--write-raw-window", action="store_true")
    build.add_argument("--write-full-scanner", action="store_true")
    build.add_argument("--write-full-ev", action="store_true")
    build.add_argument("--write-full-feed", action="store_true")
    build.set_defaults(func=cmd_build_dataset)

    field_presence = sub.add_parser("field-presence")
    _add_window_args(field_presence)
    field_presence.add_argument("--out", type=Path)
    field_presence.set_defaults(func=cmd_field_presence)

    rows_event = sub.add_parser("rows-by-event")
    _add_window_args(rows_event)
    rows_event.add_argument("--event-type", required=True)
    rows_event.add_argument("--limit", type=int, default=100)
    rows_event.add_argument("--out", type=Path)
    rows_event.set_defaults(func=cmd_rows_by_event)

    rows_reason = sub.add_parser("rows-by-reason")
    _add_window_args(rows_reason)
    rows_reason.add_argument("--reason", required=True)
    rows_reason.add_argument("--limit", type=int, default=100)
    rows_reason.add_argument("--out", type=Path)
    rows_reason.set_defaults(func=cmd_rows_by_reason)

    rows_field = sub.add_parser("rows-by-field")
    _add_window_args(rows_field)
    rows_field.add_argument("--field", required=True)
    rows_field.add_argument("--limit", type=int, default=100)
    rows_field.add_argument("--out", type=Path)
    rows_field.set_defaults(func=cmd_rows_by_field)

    raw = sub.add_parser("raw-around")
    raw.add_argument("--timestamp", required=True)
    raw.add_argument("--seconds", type=int, default=300)
    raw.add_argument("--product")
    raw.add_argument("--ticker")
    raw.add_argument("--out", type=Path, required=True)
    raw.add_argument("--logs-dir", type=Path, default=Path("logs"))
    raw.set_defaults(func=cmd_raw_around)

    official = sub.add_parser("official-outcomes")
    official.add_argument("--start", required=True)
    official.add_argument("--end", required=True)
    official.add_argument("--out", type=Path, required=True)
    official.add_argument("--env-file", type=Path, default=Path(".env"))
    official.add_argument("--logs-dir", type=Path, default=Path("logs"))
    official.set_defaults(func=cmd_official_outcomes)

    charts = sub.add_parser("charts-status")
    charts.add_argument("--start", required=True)
    charts.add_argument("--end", required=True)
    charts.add_argument("--charts-dir", type=Path)
    charts.set_defaults(func=cmd_charts_status)

    rows_ticker = sub.add_parser("rows-by-ticker")
    _add_window_args(rows_ticker)
    rows_ticker.add_argument("--ticker", required=True)
    rows_ticker.add_argument("--limit", type=int, default=100)
    rows_ticker.add_argument("--out", type=Path)
    rows_ticker.set_defaults(func=cmd_rows_by_ticker)

    rows_product = sub.add_parser("rows-by-product")
    _add_window_args(rows_product)
    rows_product.add_argument("--product", required=True)
    rows_product.add_argument("--limit", type=int, default=100)
    rows_product.add_argument("--out", type=Path)
    rows_product.set_defaults(func=cmd_rows_by_product)

    around_market = sub.add_parser("rows-around-market")
    around_market.add_argument("--ticker", required=True)
    around_market.add_argument("--seconds-before-open", type=int, default=300)
    around_market.add_argument("--seconds-after-close", type=int, default=300)
    around_market.add_argument("--out", type=Path, required=True)
    around_market.add_argument("--logs-dir", type=Path, default=Path("logs"))
    around_market.set_defaults(func=cmd_rows_around_market)

    args = parser.parse_args()
    return int(args.func(args) or 0)


def _add_window_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--logs-dir", type=Path, default=Path("logs"))


def cmd_inspect_repo(_args: argparse.Namespace) -> int:
    print(f"git_commit={_git_output(['rev-parse', 'HEAD']) or 'unknown'}")
    print("git_status_short:")
    status = _git_output(["status", "--short"])
    print(status if status else "(clean)")
    print("key_files:")
    for path in KEY_FILES:
        print(f"{path}\t{'present' if (REPO_ROOT / path).exists() else 'missing'}")
    chart_dirs = _chart_directories(None)
    print("chart_or_candle_directories:")
    if not chart_dirs:
        print("(none found)")
    for item in chart_dirs:
        print(item)
    return 0


def cmd_inspect_logs(args: argparse.Namespace) -> int:
    paths = _runtime_log_paths(args.logs_dir)
    if not paths:
        print(f"no runtime logs found under {args.logs_dir}")
        return 0
    for path in paths:
        summary = _log_file_summary(path)
        print(json.dumps(_json_safe(summary), sort_keys=True))
    return 0


def cmd_field_presence(args: argparse.Namespace) -> int:
    start, end = _window(args.start, args.end)
    rows = list(_iter_records(args.logs_dir, start=start, end=end))
    payload = {
        "event_type_counts": dict(_event_counts(rows)),
        "important_field_hits": _field_hits(rows),
    }
    text = json.dumps(_json_safe(payload), indent=2, sort_keys=True)
    if args.out:
        _write_text(args.out, text + "\n")
    print(text)
    return 0


def cmd_rows_by_event(args: argparse.Namespace) -> int:
    start, end = _window(args.start, args.end)
    rows = (
        item.record
        for item in _iter_records(args.logs_dir, start=start, end=end)
        if _event_type(item.record) == args.event_type
    )
    _emit_rows(rows, limit=args.limit, out=args.out)
    return 0


def cmd_rows_by_reason(args: argparse.Namespace) -> int:
    start, end = _window(args.start, args.end)
    needle = args.reason.strip().lower()
    rows = (
        item.record
        for item in _iter_records(args.logs_dir, start=start, end=end)
        if _record_has_reason(item.record, needle)
    )
    _emit_rows(rows, limit=args.limit, out=args.out)
    return 0


def cmd_rows_by_field(args: argparse.Namespace) -> int:
    start, end = _window(args.start, args.end)
    rows = (
        item.record
        for item in _iter_records(args.logs_dir, start=start, end=end)
        if _has_field(item.record, args.field)
    )
    _emit_rows(rows, limit=args.limit, out=args.out)
    return 0


def cmd_rows_by_ticker(args: argparse.Namespace) -> int:
    start, end = _window(args.start, args.end)
    ticker = args.ticker.strip().upper()
    rows = (
        item.record
        for item in _iter_records(args.logs_dir, start=start, end=end)
        if _extract_ticker(item.record).upper() == ticker or _contains_text(item.record, ticker)
    )
    _emit_rows(rows, limit=args.limit, out=args.out)
    return 0


def cmd_rows_by_product(args: argparse.Namespace) -> int:
    start, end = _window(args.start, args.end)
    product = args.product.strip().upper()
    rows = (
        item.record
        for item in _iter_records(args.logs_dir, start=start, end=end)
        if _extract_product(item.record).upper() == product or _contains_text(item.record, product)
    )
    _emit_rows(rows, limit=args.limit, out=args.out)
    return 0


def cmd_raw_around(args: argparse.Namespace) -> int:
    center = _parse_ts(args.timestamp, "--timestamp")
    start = center - timedelta(seconds=args.seconds)
    end = center + timedelta(seconds=args.seconds)
    rows = (
        item.record
        for item in _iter_records(args.logs_dir, start=start, end=end)
        if _matches_optional_filters(item.record, product=args.product, ticker=args.ticker)
    )
    _write_jsonl(args.out, rows)
    print(f"wrote={args.out}")
    return 0


def cmd_rows_around_market(args: argparse.Namespace) -> int:
    ticker = args.ticker.strip().upper()
    open_time, close_time, source = _market_window_from_ticker_or_logs(ticker, args.logs_dir)
    if open_time is None or close_time is None:
        raise SystemExit(
            "Cannot infer open/close time for "
            f"{ticker}: missing parseable ticker timestamp or log fields "
            "market_open_time/open_time and market_close_time/close_time/"
            "expiration_time/latest_expiration_time."
        )
    start = open_time - timedelta(seconds=args.seconds_before_open)
    end = close_time + timedelta(seconds=args.seconds_after_close)
    rows = (
        item.record
        for item in _iter_records(args.logs_dir, start=start, end=end)
        if _extract_ticker(item.record).upper() == ticker or _contains_text(item.record, ticker)
    )
    _write_jsonl(args.out, rows)
    print(f"ticker={ticker}")
    print(f"window_source={source}")
    print(f"start={start.isoformat()}")
    print(f"end={end.isoformat()}")
    print(f"wrote={args.out}")
    return 0


def cmd_charts_status(args: argparse.Namespace) -> int:
    start, end = _window(args.start, args.end)
    rows = _chart_status_rows(start=start, end=end, charts_dir=args.charts_dir)
    _write_csv_stdout(rows)
    return 0


def cmd_official_outcomes(args: argparse.Namespace) -> int:
    start, end = _window(args.start, args.end)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    source_log = args.out.parent / "OUTCOME_SOURCE_LOG.jsonl"
    _write_jsonl(source_log, (item.record for item in _iter_records(args.logs_dir, start=start, end=end) if _extract_ticker(item.record)))
    ok, error = _run_official_export(
        start=start,
        end=end,
        env_file=args.env_file,
        log_file=source_log,
        out=args.out,
    )
    if not ok:
        raise SystemExit(error)
    return 0


def cmd_build_dataset(args: argparse.Namespace) -> int:
    start, end = _window(args.start, args.end)
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    records = list(_iter_records(args.logs_dir, start=start, end=end))
    raw_records = [item.record for item in records]
    _write_text(out_dir / "EXPORT_WINDOW.txt", f"start_utc={start.isoformat()}\nend_utc={end.isoformat()}\n")
    _write_text(out_dir / "EVENT_TYPE_COUNTS_RECOMPUTED.txt", _counter_text(_event_counts(records)))
    _write_text(out_dir / "IMPORTANT_FIELD_HITS.txt", _counter_text(Counter(_field_hits(records))))
    _write_jsonl(out_dir / "EVENT_TYPE_SAMPLES.jsonl", _event_samples(records))
    _write_jsonl(out_dir / "LIFECYCLE_FULL.jsonl", raw_records)
    _write_jsonl(out_dir / "RUNTIME_ERRORS_AND_FAILURES_FULL.jsonl", _error_rows(raw_records))
    _write_text(out_dir / "LOG_SCHEMA_FIELD_PATHS_BY_EVENT_TYPE.txt", _schema_paths_text(records))
    _write_text(out_dir / "GIT_HEAD.txt", (_git_output(["rev-parse", "HEAD"]) or "unknown") + "\n")
    _write_text(out_dir / "GIT_STATUS_SHORT.txt", (_git_output(["status", "--short"]) or "(clean)") + "\n")
    _write_safe_env_snapshot(out_dir / "ENV_SNAPSHOT_SAFE_EXPORT_TIME.txt", args.env_file)
    _copy_code_snapshot(out_dir / "code_snapshot")

    source_log = out_dir / "OUTCOME_SOURCE_LOG.jsonl"
    source_rows = [row for row in raw_records if _extract_ticker(row)]
    _write_jsonl(source_log, source_rows)
    official_out = out_dir / "OFFICIAL_KALSHI_OUTCOMES.json"
    official_unavailable = False
    ok, error = _run_official_export(
        start=start,
        end=end,
        env_file=args.env_file,
        log_file=source_log,
        out=official_out,
    )
    if not ok:
        official_unavailable = True
        _write_text(out_dir / "OUTCOME_EXPORT_ERROR.txt", error + "\n")
    outcomes = {} if official_unavailable else _load_official_outcomes(official_out)

    executed = [_summary_row(row, outcomes, official_unavailable) for row in raw_records if _is_executed(row)]
    skipped = [_summary_row(row, outcomes, official_unavailable) for row in raw_records if _is_skip_like(row)]
    _write_csv(out_dir / "EXECUTED_TRADE_SUMMARY.csv", executed, EXECUTED_COLUMNS)
    _write_text(out_dir / "EXECUTED_MARKET_TICKERS.txt", "\n".join(sorted({_clean(row.get("market_ticker")) for row in executed if row.get("market_ticker")})) + "\n")
    _write_csv(out_dir / "SKIP_REASON_OUTCOME_MATRIX.csv", _skip_reason_matrix(skipped), None)
    _write_csv(out_dir / "SKIP_REASON_PRODUCT_MATRIX.csv", _skip_product_matrix(skipped), None)
    _write_jsonl(out_dir / "REPRESENTATIVE_SKIPS_BY_REASON.jsonl", _representative_skips(skipped, args.max_representative_per_reason))
    _write_csv(out_dir / "SCANNER_5MIN_PRODUCT_STATE_SUMMARY.csv", _scanner_summary(raw_records), None)
    _write_jsonl(out_dir / "SCANNER_REPRESENTATIVE_CONTEXT.jsonl", _scanner_representatives(raw_records))
    _write_csv(out_dir / "EV_PRICE_RISK_REASON_SUMMARY.csv", _ev_summary(raw_records), None)
    _write_csv(out_dir / "LATENCY_REPRICING_SUMMARY.csv", _latency_summary(raw_records), None)
    _write_jsonl(out_dir / "REPRESENTATIVE_LATENCY_REPRICING_ROWS.jsonl", _latency_representatives(raw_records))
    _write_csv(out_dir / "PROFIT_CAPTURE_SUMMARY.csv", _profit_capture_summary(raw_records), None)
    _write_csv(out_dir / "LIFECYCLE_EVENT_COUNTS.csv", [{"event_type": key, "count": value} for key, value in _event_counts(records).items()], None)
    _write_csv(out_dir / "ENV_SYSTEM_MATRIX_TEMPLATE.csv", _env_system_matrix_rows(args.env_file), None)
    if args.charts_dir:
        _write_csv(out_dir / "CHART_FILE_STATUS.csv", _chart_status_rows(start=start, end=end, charts_dir=args.charts_dir), None)

    around_path = out_dir / f"RAW_RUNTIME_AROUND_EXECUTIONS_{args.around_seconds}S.jsonl.gz"
    _write_jsonl(
        around_path,
        _around_execution_rows(records, seconds=args.around_seconds),
    )
    optional_raw_paths: list[Path] = []
    if args.write_raw_window:
        optional_raw_paths.append(out_dir / "RAW_RUNTIME_WINDOW_FULL.jsonl.gz")
        _write_jsonl(optional_raw_paths[-1], raw_records)
    if args.write_full_scanner:
        optional_raw_paths.append(out_dir / "FULL_SCANNER_ROWS.jsonl.gz")
        _write_jsonl(optional_raw_paths[-1], (row for row in raw_records if _is_scanner_like(row)))
    if args.write_full_ev:
        optional_raw_paths.append(out_dir / "FULL_EV_ROWS.jsonl.gz")
        _write_jsonl(optional_raw_paths[-1], (row for row in raw_records if _is_ev_like(row)))
    if args.write_full_feed:
        optional_raw_paths.append(out_dir / "FULL_FEED_ROWS.jsonl.gz")
        _write_jsonl(optional_raw_paths[-1], (row for row in raw_records if _is_feed_like(row)))

    _write_file_size_reports(out_dir)
    _write_readme(
        out_dir / "README_FOR_AGENT.txt",
        start=start,
        end=end,
        optional_raw_paths=optional_raw_paths,
        official_unavailable=official_unavailable,
        charts_supplied=bool(args.charts_dir),
    )
    if args.package:
        package_path = out_dir.with_suffix(".tar.gz")
        with tarfile.open(package_path, "w:gz") as archive:
            archive.add(out_dir, arcname=out_dir.name)
        print(f"package={package_path}")
    print(f"dataset={out_dir}")
    return 0


class LogItem:
    def __init__(self, *, path: Path, line_number: int, record: dict[str, Any], recorded_at: datetime | None) -> None:
        self.path = path
        self.line_number = line_number
        self.record = record
        self.recorded_at = recorded_at


def _runtime_log_paths(logs_dir: Path) -> list[Path]:
    if not logs_dir.exists():
        return []
    paths = list(logs_dir.glob("runtime*.jsonl")) + list(logs_dir.glob("runtime*.jsonl.gz"))
    return sorted(path for path in paths if path.is_file())


def _iter_records(
    logs_dir: Path,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> Iterable[LogItem]:
    for path in _runtime_log_paths(logs_dir):
        opener = gzip.open if path.suffix == ".gz" else open
        try:
            with opener(path, "rt", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(record, dict):
                        continue
                    recorded_at = _parse_optional_ts(record.get("recorded_at"))
                    if start is not None and (recorded_at is None or recorded_at < start):
                        continue
                    if end is not None and (recorded_at is None or recorded_at >= end):
                        continue
                    yield LogItem(path=path, line_number=line_number, record=record, recorded_at=recorded_at)
        except OSError:
            continue


def _log_file_summary(path: Path) -> dict[str, Any]:
    event_counts: Counter[str] = Counter()
    field_counts: Counter[str] = Counter()
    first: str | None = None
    last: str | None = None
    rows = 0
    for item in _iter_records(path.parent, start=None, end=None):
        if item.path != path:
            continue
        rows += 1
        ts = item.record.get("recorded_at")
        first = str(ts) if first is None and ts else first
        last = str(ts) if ts else last
        event_counts[_event_type(item.record)] += 1
        for field, count in _field_hits([item]).items():
            if count:
                field_counts[field] += count
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "rows": rows,
        "first_recorded_at": first,
        "last_recorded_at": last,
        "top_event_types": dict(event_counts.most_common(20)),
        "important_field_presence_counts": dict(field_counts),
    }


def _event_counts(items: Iterable[LogItem]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for item in items:
        counter[_event_type(item.record)] += 1
    return counter


def _field_hits(items: Iterable[LogItem]) -> dict[str, int]:
    counts = {field: 0 for field in IMPORTANT_FIELDS}
    for item in items:
        for field in IMPORTANT_FIELDS:
            if _has_field(item.record, field):
                counts[field] += 1
    return counts


def _has_field(record: dict[str, Any], field: str) -> bool:
    if _event_type(record) == field:
        return True
    return any(path.rsplit(".", 1)[-1] == field for path, _value in _walk_paths(record.get("payload", {})))


def _walk_paths(value: Any, prefix: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield path, item
            yield from _walk_paths(item, path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            path = f"{prefix}[{index}]"
            yield path, item
            yield from _walk_paths(item, path)


def _event_type(record: dict[str, Any]) -> str:
    return str(record.get("event_type") or record.get("message_type") or record.get("record_type") or "unknown")


def _payload(record: dict[str, Any]) -> dict[str, Any]:
    payload = record.get("payload")
    return payload if isinstance(payload, dict) else {}


def _record_has_reason(record: dict[str, Any], needle: str) -> bool:
    for field in REASON_FIELDS:
        for value in _values_for_key(record, field):
            if _value_contains(value, needle):
                return True
    return False


def _values_for_key(value: Any, key: str) -> Iterable[Any]:
    if isinstance(value, dict):
        for item_key, item in value.items():
            if item_key == key:
                yield item
            yield from _values_for_key(item, key)
    elif isinstance(value, list):
        for item in value:
            yield from _values_for_key(item, key)


def _value_contains(value: Any, needle: str) -> bool:
    if isinstance(value, dict):
        return any(_value_contains(key, needle) or _value_contains(item, needle) for key, item in value.items())
    if isinstance(value, list):
        return any(_value_contains(item, needle) for item in value)
    return needle in str(value).strip().lower()


def _contains_text(value: Any, needle: str) -> bool:
    return _value_contains(value, needle.strip().lower())


def _emit_rows(rows: Iterable[dict[str, Any]], *, limit: int, out: Path | None) -> None:
    limited = []
    for row in rows:
        limited.append(row)
        if len(limited) >= limit:
            break
    if out:
        _write_jsonl(out, limited)
        print(f"wrote={out}")
        return
    for row in limited:
        print(json.dumps(_json_safe(row), sort_keys=True))


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(_json_safe(row), sort_keys=True) + "\n")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: tuple[str, ...] | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if columns is None:
        keys: list[str] = []
        for row in rows:
            for key in row:
                if key not in keys:
                    keys.append(key)
        columns = tuple(keys)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(_json_safe(row))


def _write_csv_stdout(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]))
    writer.writeheader()
    for row in rows:
        writer.writerow(_json_safe(row))


def _window(start_raw: str, end_raw: str) -> tuple[datetime, datetime]:
    start = _parse_ts(start_raw, "--start")
    end = _parse_ts(end_raw, "--end")
    if end <= start:
        raise SystemExit("--end must be after --start")
    return start, end


def _parse_ts(raw: str, label: str) -> datetime:
    value = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit(f"{label} must be an ISO timestamp: {raw}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_optional_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return _parse_ts(str(value), "timestamp")
    except SystemExit:
        return None


def _extract_ticker(record: dict[str, Any]) -> str:
    for key in ("market_ticker", "contract_ticker", "ticker", "identifier"):
        for value in _values_for_key(record, key):
            text = _clean(value)
            if text.upper().startswith("KX"):
                return text
    ident = _clean(record.get("identifier"))
    return ident if ident.upper().startswith("KX") else ""


def _extract_product(record: dict[str, Any]) -> str:
    for value in _values_for_key(record, "product_id"):
        text = _clean(value)
        if text:
            return text
    return ""


def _extract_side(record: dict[str, Any]) -> str:
    for key in ("side", "intent_side", "selected_side"):
        for value in _values_for_key(record, key):
            text = _clean(value).lower()
            if text in {"yes", "no"}:
                return text
    return ""


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _matches_optional_filters(record: dict[str, Any], *, product: str | None, ticker: str | None) -> bool:
    if product and _extract_product(record).upper() != product.upper() and not _contains_text(record, product.upper()):
        return False
    if ticker and _extract_ticker(record).upper() != ticker.upper() and not _contains_text(record, ticker.upper()):
        return False
    return True


def _market_window_from_ticker_or_logs(ticker: str, logs_dir: Path) -> tuple[datetime | None, datetime | None, str]:
    session_start = _session_start_from_ticker(ticker)
    if session_start is not None:
        return session_start, session_start + timedelta(seconds=SESSION_SECONDS), "ticker"
    for item in _iter_records(logs_dir):
        if not (_extract_ticker(item.record).upper() == ticker or _contains_text(item.record, ticker)):
            continue
        payload = _payload(item.record)
        open_time = _first_timestamp(payload, ("market_open_time", "open_time"))
        close_time = _first_timestamp(
            payload,
            ("market_close_time", "close_time", "expiration_time", "latest_expiration_time"),
        )
        if open_time is not None and close_time is not None:
            return open_time, close_time, "logs"
    return None, None, "missing"


def _first_timestamp(value: Any, keys: tuple[str, ...]) -> datetime | None:
    for key in keys:
        for item in _values_for_key(value, key):
            parsed = _parse_optional_ts(item)
            if parsed is not None:
                return parsed
    return None


def _session_start_from_ticker(ticker: str) -> datetime | None:
    match = TICKER_RE.match(ticker)
    if match is None:
        return None
    month = MONTHS.get(match.group("month"))
    if month is None:
        return None
    try:
        return datetime(
            year=2000 + int(match.group("year")),
            month=month,
            day=int(match.group("day")),
            hour=int(match.group("hour")),
            minute=int(match.group("minute")),
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def _is_executed(record: dict[str, Any]) -> bool:
    return _event_type(record) in EXECUTED_EVENTS


def _is_skip_like(record: dict[str, Any]) -> bool:
    event = _event_type(record)
    return event in SKIP_EVENTS or bool(_reason(record))


def _reason(record: dict[str, Any]) -> str:
    payload = _payload(record)
    for key in ("reason", "final_blocking_gate", "ev_filter_reason", "continuation_blocked_reason"):
        for value in _values_for_key(payload, key):
            text = _clean(value)
            if text:
                return text
    return ""


EXECUTED_COLUMNS = (
    "recorded_at",
    "product_id",
    "market_ticker",
    "side",
    "official_result",
    "result",
    "outcome_status",
    "entry_price",
    "count",
    "classification_reason",
    "state_classification",
    "structure",
    "direction",
    "confidence",
    "progression_continuation_quality",
    "return_range_ratio",
    "distance_to_target_bps",
    "distance_to_target_abs_bps",
    "side_currently_itm",
    "side_needs_cross",
    "required_bps_per_minute",
    "trend_confirmation_status",
    "signal_conflict_flags",
    "reversal_probability",
    "reversal_expected_value",
    "reversal_shadow_only",
    "opposite_side_price",
    "opposite_side_ev",
    "fake_continuation_signature",
    "ev_filter_status",
    "ev_filter_reason",
    "score_aware_ev_cap_status",
    "score_aware_ev_cap_reason",
    "final_blocking_gate",
    "hard_gate_results",
    "profit_capture_trigger_price",
    "profit_capture_trigger_time",
    "max_favorable_price_since_entry",
)


def _summary_row(record: dict[str, Any], outcomes: dict[str, str], official_unavailable: bool) -> dict[str, Any]:
    payload = _payload(record)
    ticker = _extract_ticker(record)
    side = _extract_side(record)
    official, status, result = _outcome_status(ticker=ticker, side=side, outcomes=outcomes, official_unavailable=official_unavailable)
    row = {
        "recorded_at": record.get("recorded_at"),
        "event_type": _event_type(record),
        "product_id": _extract_product(record),
        "market_ticker": ticker,
        "side": side,
        "official_result": official,
        "result": result,
        "outcome_status": status,
        "attempted_result": result,
        "reason": _reason(record),
    }
    for key in EXECUTED_COLUMNS:
        row.setdefault(key, _first_value(payload, key))
    for key in REASON_FIELDS + IMPORTANT_FIELDS:
        row.setdefault(key, _first_value(payload, key))
    row["price"] = _first_value(payload, "price") or _first_value(payload, "price_dollars")
    row["intended_price"] = _first_value(payload, "intent_price") or _first_value(payload, "entry_price")
    return row


def _outcome_status(*, ticker: str, side: str, outcomes: dict[str, str], official_unavailable: bool) -> tuple[str, str, str]:
    if official_unavailable:
        return "UNKNOWN", "official_outcome_unavailable", "unknown"
    if not ticker:
        return "UNKNOWN", "unknown_no_ticker", "unknown"
    official = outcomes.get(ticker.upper())
    if not official:
        return "UNKNOWN", "ticker_no_official_match", "unknown"
    normalized = official.lower()
    if normalized not in {"yes", "no"}:
        return official, "unknown_ambiguous", "unknown"
    if side not in {"yes", "no"}:
        return official, "unknown_missing_side", "unknown"
    return official, "direct_mapped", "win" if side == normalized else "loss"


def _first_value(value: Any, key: str) -> Any:
    for item in _values_for_key(value, key):
        return _json_safe(item)
    return None


def _skip_reason_matrix(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_clean(row.get("reason")) or "unknown"].append(row)
    result = []
    for reason, items in sorted(grouped.items()):
        result.append({
            "reason": reason,
            "total": len(items),
            "direct_mapped": _count_status(items, "direct_mapped"),
            "ticker_no_official_match": _count_status(items, "ticker_no_official_match"),
            "unknown_no_ticker": _count_status(items, "unknown_no_ticker"),
            "unknown_missing_side": _count_status(items, "unknown_missing_side"),
            "unknown_ambiguous": _count_status(items, "unknown_ambiguous"),
            "official_outcome_unavailable": _count_status(items, "official_outcome_unavailable"),
            "attempted_wins": sum(1 for item in items if item.get("result") == "win"),
            "attempted_losses": sum(1 for item in items if item.get("result") == "loss"),
            "mapped_attempted_win_rate": _win_rate(items),
            "avg_return_range_ratio": _avg(items, "return_range_ratio"),
            "median_return_range_ratio": _median(items, "return_range_ratio"),
            "avg_distance_to_target_abs_bps": _avg(items, "distance_to_target_abs_bps"),
            "median_distance_to_target_abs_bps": _median(items, "distance_to_target_abs_bps"),
            "avg_required_bps_per_minute": _avg(items, "required_bps_per_minute"),
            "median_required_bps_per_minute": _median(items, "required_bps_per_minute"),
            "avg_intent_entry_price": _avg_any(items, ("intended_price", "entry_price", "price")),
            "median_intent_entry_price": _median_any(items, ("intended_price", "entry_price", "price")),
            "avg_reversal_probability": _avg(items, "reversal_probability"),
            "avg_reversal_expected_value": _avg(items, "reversal_expected_value"),
            "side_needs_cross_distribution": _distribution(items, "side_needs_cross"),
            "side_currently_itm_distribution": _distribution(items, "side_currently_itm"),
            "top_products": _top_values(items, "product_id"),
            "top_classifications": _top_values(items, "classification_reason"),
        })
    return result


def _skip_product_matrix(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(_clean(row.get("reason")) or "unknown", _clean(row.get("product_id")) or "unknown")].append(row)
    return [{"reason": key[0], "product_id": key[1], "total": len(items)} for key, items in sorted(grouped.items())]


def _representative_skips(rows: list[dict[str, Any]], max_per_reason: int) -> Iterable[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for reason in IMPORTANT_REPRESENTATIVE_REASONS:
        for row in rows:
            if counts[reason] >= max_per_reason:
                break
            if reason in json.dumps(_json_safe(row), sort_keys=True):
                counts[reason] += 1
                yield {key: row.get(key) for key in (
                    "recorded_at", "product_id", "market_ticker", "side", "official_result",
                    "outcome_status", "attempted_result", "reason", "price", "intended_price",
                    "classification_reason", "state_classification", "progression_continuation_quality",
                    "return_range_ratio", "distance_to_target_abs_bps", "side_currently_itm",
                    "side_needs_cross", "required_bps_per_minute", "trend_confirmation_status",
                    "signal_conflict_flags", "reversal_probability", "reversal_expected_value",
                    "opposite_side_price", "opposite_side_ev", "ev_filter_status", "ev_filter_reason",
                    "score_aware_ev_cap_status", "score_aware_ev_cap_reason", "final_blocking_gate",
                    "hard_gate_results",
                )}


def _scanner_summary(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for row in records:
        if not _is_scanner_like(row):
            continue
        ts = _parse_optional_ts(row.get("recorded_at"))
        bucket = _bucket5(ts)
        payload = _payload(row)
        key = (
            bucket,
            _extract_product(row) or "unknown",
            _event_type(row),
            _clean(_first_value(payload, "classification_reason")) or "unknown",
            _reason(row) or "none",
        )
        current = grouped.setdefault(key, {
            "bucket_utc": bucket,
            "product_id": key[1],
            "event_type": key[2],
            "classification_reason": key[3],
            "reason": key[4],
            "count": 0,
            "ranked_contract_count": None,
            "skipped_contract_count": None,
            "top_skip_reasons": None,
            "direction": None,
            "confidence": None,
            "structure": None,
        })
        current["count"] += 1
        for field in ("ranked_contract_count", "skipped_contract_count", "top_skip_reasons", "direction", "confidence", "structure"):
            current[field] = current[field] or _first_value(payload, field)
    return list(grouped.values())


def _scanner_representatives(records: list[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    seen: set[str] = set()
    for row in records:
        if not _is_scanner_like(row):
            continue
        event = _event_type(row)
        if event in seen:
            continue
        seen.add(event)
        yield row


def _ev_summary(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: Counter[tuple[str, str, str]] = Counter()
    for row in records:
        if _is_ev_like(row):
            payload = _payload(row)
            grouped[(
                _clean(_first_value(payload, "ev_filter_status")) or "unknown",
                _clean(_first_value(payload, "ev_filter_reason")) or _reason(row) or "unknown",
                _clean(_first_value(payload, "score_aware_ev_cap_status")) or "unknown",
            )] += 1
    return [{"ev_filter_status": key[0], "ev_filter_reason": key[1], "score_aware_ev_cap_status": key[2], "count": count} for key, count in grouped.items()]


def _latency_summary(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = [row for row in records if _is_feed_like(row)]
    return [{
        "total_rows": len(items),
        "repricing_gap_rows": sum(1 for row in items if _first_value(_payload(row), "repricing_gap") is not None),
        "stale_side_available_true": sum(1 for row in items if str(_first_value(_payload(row), "stale_side_available")).lower() == "true"),
        "avg_repricing_gap": _avg_payload(items, "repricing_gap"),
        "median_repricing_gap": _median_payload(items, "repricing_gap"),
        "avg_time_since_last_spot_update_ms": _avg_payload(items, "time_since_last_spot_update_ms"),
        "avg_time_since_last_kalshi_update_ms": _avg_payload(items, "time_since_last_kalshi_update_ms"),
        "avg_time_since_spot_move_bps_threshold_ms": _avg_payload(items, "time_since_spot_move_bps_threshold_ms"),
    }]


def _latency_representatives(records: list[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    count = 0
    for row in records:
        payload = _payload(row)
        if _is_feed_like(row) and (
            _first_value(payload, "repricing_gap") is not None
            or str(_first_value(payload, "stale_side_available")).lower() == "true"
        ):
            yield row
            count += 1
            if count >= 100:
                break


def _profit_capture_summary(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in records:
        if "profit_capture" not in _event_type(row):
            continue
        payload = _payload(row)
        rows.append({
            "recorded_at": row.get("recorded_at"),
            "event_type": _event_type(row),
            "ticker": _extract_ticker(row),
            "side": _extract_side(row),
            "entry_price": _first_value(payload, "entry_price"),
            "current_executable_exit_bid": _first_value(payload, "current_executable_exit_bid"),
            "max_favorable_price_since_entry": _first_value(payload, "max_favorable_price_since_entry"),
            "max_adverse_price_since_entry": _first_value(payload, "max_adverse_price_since_entry"),
            "profit_capture_trigger_price": _first_value(payload, "profit_capture_trigger_price"),
            "profit_capture_trigger_time": _first_value(payload, "profit_capture_trigger_time"),
            "exit_submitted_price": _first_value(payload, "exit_submitted_price"),
            "exit_filled_price": _first_value(payload, "exit_filled_price"),
            "estimated_realized_pnl": _first_value(payload, "estimated_realized_pnl"),
            "skipped_reason": _first_value(payload, "reason"),
            "missing_max_favorable_price_since_entry": _first_value(payload, "max_favorable_price_since_entry") is None,
        })
    if not rows:
        return [{"event_type": "profit_capture", "count": 0, "missing_max_favorable_price_since_entry": True}]
    return rows


def _is_scanner_like(row: dict[str, Any]) -> bool:
    event = _event_type(row)
    return event in {"cycle_completed", "candidate_funnel_summary", "live_order_candidate", "live_order_intent_skipped"} or "scanner" in event


def _is_ev_like(row: dict[str, Any]) -> bool:
    return any(_has_field(row, field) for field in ("ev_filter_status", "ev_filter_reason", "score_aware_ev_cap_status", "ev_actual_cost_status"))


def _is_feed_like(row: dict[str, Any]) -> bool:
    event = _event_type(row)
    return event in {"spot_update_received", "kalshi_market_update_received"} or row.get("category") == "latency_diagnostics"


def _error_rows(records: Iterable[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    for row in records:
        text = _event_type(row).lower() + " " + json.dumps(_json_safe(_payload(row)), sort_keys=True).lower()
        if any(token in text for token in ("error", "failed", "failure", "exception")):
            yield row


def _event_samples(items: list[LogItem]) -> Iterable[dict[str, Any]]:
    seen: set[str] = set()
    for item in items:
        event = _event_type(item.record)
        if event in seen:
            continue
        seen.add(event)
        yield item.record


def _schema_paths_text(items: list[LogItem]) -> str:
    paths_by_event: dict[str, set[str]] = defaultdict(set)
    for item in items:
        for path, _value in _walk_paths(_payload(item.record)):
            paths_by_event[_event_type(item.record)].add(path)
    lines = []
    for event in sorted(paths_by_event):
        lines.append(f"[{event}]")
        lines.extend(f"  {path}" for path in sorted(paths_by_event[event]))
    return "\n".join(lines) + "\n"


def _around_execution_rows(items: list[LogItem], *, seconds: int) -> Iterable[dict[str, Any]]:
    execution_times = [item.recorded_at for item in items if item.recorded_at and _is_executed(item.record)]
    for item in items:
        if item.recorded_at is None:
            continue
        if any(abs((item.recorded_at - ts).total_seconds()) <= seconds for ts in execution_times):
            yield item.record


def _run_official_export(*, start: datetime, end: datetime, env_file: Path, log_file: Path, out: Path) -> tuple[bool, str]:
    script = REPO_ROOT / "scripts" / "export_official_kalshi_outcomes.py"
    if not script.exists():
        return False, f"missing exporter: {script}"
    command = [
        sys.executable,
        str(script),
        "--env-file",
        str(env_file),
        "--log-file",
        str(log_file),
        "--start",
        start.isoformat(),
        "--end",
        end.isoformat(),
        "--out",
        str(out),
    ]
    try:
        completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    except OSError as exc:
        return False, str(exc)
    if completed.returncode != 0:
        return False, (completed.stderr or completed.stdout or f"exit_code={completed.returncode}").strip()
    return True, completed.stdout.strip()


def _load_official_outcomes(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    outcomes = {}
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            ticker = _clean(row.get("market_ticker")).upper()
            result = _normalize_result(row.get("official_result"))
            if ticker and result:
                outcomes[ticker] = result
    return outcomes


def _normalize_result(value: Any) -> str:
    text = _clean(value).lower()
    if text in {"yes", "y"}:
        return "yes"
    if text in {"no", "n"}:
        return "no"
    return _clean(value)


def _write_safe_env_snapshot(path: Path, env_file: Path) -> None:
    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "env_file": str(env_file),
        "safe_raw_env": _safe_env_file_values(env_file),
        "git_commit": _git_output(["rev-parse", "HEAD"]),
        "git_status_short": _git_output(["status", "--short"]),
    }
    payload["env_hash"] = hashlib.sha256(json.dumps(payload["safe_raw_env"], sort_keys=True).encode("utf-8")).hexdigest()
    _write_text(path, json.dumps(_json_safe(payload), indent=2, sort_keys=True) + "\n")


def _safe_env_file_values(env_file: Path) -> dict[str, str]:
    if not env_file.exists():
        return {}
    result = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if _is_sensitive_key(key):
            continue
        result[key] = value.strip()
    return result


def _is_sensitive_key(key: str) -> bool:
    upper = key.upper()
    return any(token in upper for token in SENSITIVE_TOKENS)


def _copy_code_snapshot(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for rel in KEY_FILES:
        src = REPO_ROOT / rel
        if not src.exists() or _is_sensitive_key(src.name):
            continue
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def _chart_directories(charts_dir: Path | None) -> list[str]:
    candidates = []
    if charts_dir is not None:
        candidates.append(charts_dir)
    candidates.extend(path for path in REPO_ROOT.iterdir() if path.is_dir() and re.search(r"(chart|candle|ohlc|price)", path.name, re.I))
    return [str(path) for path in candidates if path.exists()]


def _chart_status_rows(*, start: datetime, end: datetime, charts_dir: Path | None) -> list[dict[str, Any]]:
    rows = []
    for product in PRODUCT_IDS:
        files: list[Path] = []
        if charts_dir and charts_dir.exists():
            symbol = product.split("-", 1)[0].lower()
            files = [path for path in charts_dir.rglob("*") if path.is_file() and symbol in path.name.lower() and path.suffix.lower() in {".csv", ".json", ".jsonl", ".gz"}]
        rows.append({
            "product_id": product,
            "start_utc": start.isoformat(),
            "end_utc": end.isoformat(),
            "charts_dir": str(charts_dir) if charts_dir else None,
            "status": "present" if files else "missing",
            "file_count": len(files),
            "example_files": ";".join(str(path) for path in files[:5]),
        })
    return rows


def _env_system_matrix_rows(env_file: Path) -> list[dict[str, Any]]:
    safe = _safe_env_file_values(env_file)
    return [{"name": key, "safe_value": value, "source": str(env_file)} for key, value in sorted(safe.items())]


def _write_file_size_reports(out_dir: Path) -> None:
    lines = []
    total = 0
    for path in sorted(item for item in out_dir.rglob("*") if item.is_file()):
        size = path.stat().st_size
        total += size
        lines.append(f"{path.relative_to(out_dir)}\t{size}")
    _write_text(out_dir / "FILE_SIZES.txt", "\n".join(lines) + "\n")
    _write_text(out_dir / "DIRECTORY_SIZE.txt", f"{total}\n")


def _write_readme(
    path: Path,
    *,
    start: datetime,
    end: datetime,
    optional_raw_paths: list[Path],
    official_unavailable: bool,
    charts_supplied: bool,
) -> None:
    raw_lines = "\n".join(f"- {item.name}: {item.stat().st_size} bytes" for item in optional_raw_paths if item.exists()) or "- None"
    text = f"""Historical Audit Dataset

UTC window:
- start: {start.isoformat()}
- end: {end.isoformat()}

Included files:
- Core lifecycle, event counts, field hits, schema paths, event samples, safe env/git snapshots, code_snapshot, summaries, representative drilldowns, official outcome exports when available, and raw rows around executions.

Intentionally excluded by default:
- Full raw runtime windows.
- Full raw scanner rows.
- Full raw EV rows.
- Full raw feed rows.

Optional full raw files written for this export:
{raw_lines}

Charts:
- Chart files may be separate from this package.
- If charts are missing, do not make chart-alignment claims.
- CHART_FILE_STATUS.csv is written only when --charts-dir is supplied.

Official outcomes:
- Outcomes are exported with scripts/export_official_kalshi_outcomes.py when available.
- If official export failed, outcome fields are marked official_outcome_unavailable.
- Unknown outcomes must stay separate from attempted wins/losses.
- Outcome categories include direct_mapped, ticker_no_official_match, unknown_no_ticker, unknown_missing_side, unknown_ambiguous, and official_outcome_unavailable.
- official_outcome_unavailable: {official_unavailable}

Drilldowns:
- Use rows-by-event, rows-by-reason, rows-by-field, rows-by-ticker, rows-by-product, raw-around, and rows-around-market when a conclusion cannot be proven from summaries.
- If a conclusion cannot be proven, state exactly which full raw file or field is needed.

Chart directory supplied: {charts_supplied}
"""
    _write_text(path, text)


def _git_output(args: list[str]) -> str:
    try:
        completed = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    except OSError:
        return ""
    return (completed.stdout or completed.stderr).strip()


def _counter_text(counter: Counter[Any] | dict[str, int]) -> str:
    items = counter.items() if isinstance(counter, dict) else counter.most_common()
    return "".join(f"{key}\t{value}\n" for key, value in items)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _numeric_values(rows: list[dict[str, Any]], key: str) -> list[Decimal]:
    return [value for value in (_decimal(row.get(key)) for row in rows) if value is not None]


def _numeric_values_any(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> list[Decimal]:
    values = []
    for row in rows:
        for key in keys:
            value = _decimal(row.get(key))
            if value is not None:
                values.append(value)
                break
    return values


def _avg(rows: list[dict[str, Any]], key: str) -> str | None:
    values = _numeric_values(rows, key)
    return str((sum(values) / Decimal(len(values))).quantize(Decimal("0.0001"))) if values else None


def _median(rows: list[dict[str, Any]], key: str) -> str | None:
    values = _numeric_values(rows, key)
    return str(median(values)) if values else None


def _avg_any(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> str | None:
    values = _numeric_values_any(rows, keys)
    return str((sum(values) / Decimal(len(values))).quantize(Decimal("0.0001"))) if values else None


def _median_any(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> str | None:
    values = _numeric_values_any(rows, keys)
    return str(median(values)) if values else None


def _avg_payload(rows: list[dict[str, Any]], key: str) -> str | None:
    values = [_decimal(_first_value(_payload(row), key)) for row in rows]
    clean = [value for value in values if value is not None]
    return str((sum(clean) / Decimal(len(clean))).quantize(Decimal("0.0001"))) if clean else None


def _median_payload(rows: list[dict[str, Any]], key: str) -> str | None:
    clean = [value for value in (_decimal(_first_value(_payload(row), key)) for row in rows) if value is not None]
    return str(median(clean)) if clean else None


def _count_status(rows: list[dict[str, Any]], status: str) -> int:
    return sum(1 for row in rows if row.get("outcome_status") == status)


def _win_rate(rows: list[dict[str, Any]]) -> str | None:
    mapped = [row for row in rows if row.get("outcome_status") == "direct_mapped"]
    if not mapped:
        return None
    wins = sum(1 for row in mapped if row.get("result") == "win")
    return str((Decimal(wins) / Decimal(len(mapped))).quantize(Decimal("0.0001")))


def _distribution(rows: list[dict[str, Any]], key: str) -> str:
    return json.dumps(dict(Counter(_clean(row.get(key)) or "missing" for row in rows).most_common()), sort_keys=True)


def _top_values(rows: list[dict[str, Any]], key: str) -> str:
    return json.dumps(dict(Counter(_clean(row.get(key)) or "missing" for row in rows).most_common(5)), sort_keys=True)


def _bucket5(ts: datetime | None) -> str:
    if ts is None:
        return "unknown"
    return ts.replace(minute=(ts.minute // 5) * 5, second=0, microsecond=0).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
