"""Export official Kalshi outcomes for crypto 15-minute markets.

Expected VPS usage:

    python scripts/export_official_kalshi_outcomes.py \
      --env-file .env \
      --log-file logs/runtime.jsonl \
      --start 2026-05-07T16:15:00+00:00 \
      --end 2026-05-08T04:00:00+00:00 \
      --out exports/official_kalshi_outcomes_2026-05-07_1215_to_2026-05-08_0000.json

This is a one-off reporting utility. It does not place orders or modify bot
runtime behavior.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi_bot.clients.kalshi_client import (  # noqa: E402
    MARKETS_PATH,
    KalshiClient,
    KalshiClientError,
)
from kalshi_bot.config.settings import (  # noqa: E402
    DEFAULT_CRYPTO_MARKET_SERIES,
    KalshiSettings,
    SettingsError,
    load_settings,
)


PRODUCT_IDS = (
    "BTC-USD",
    "ETH-USD",
    "SOL-USD",
    "XRP-USD",
    "DOGE-USD",
    "BNB-USD",
    "HYPE-USD",
)
SESSION_SECONDS = 15 * 60
MARKET_LIST_STATUSES = ("settled", "closed", "open")
MARKET_LIST_LIMIT = 1000
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
TARGET_PRICE_KEYS = (
    "target_price",
    "strike_price",
    "strike",
    "floor_strike",
    "cap_strike",
    "floor_price",
    "cap_price",
    "start_price",
    "initial_price",
    "reference_price",
)
OFFICIAL_RESULT_KEYS = (
    "result",
    "official_result",
    "settlement_result",
    "settled_result",
    "outcome",
    "winning_side",
)
SETTLEMENT_VALUE_KEYS = (
    "settlement_value",
    "final_value",
    "settlement_price",
    "settlement_index_value",
    "settlement_value_dollars",
)
RAW_DEBUG_KEYS = (
    "status",
    "result",
    "official_result",
    "settlement_result",
    "settlement_status",
    "yes_sub_title",
    "no_sub_title",
    "final_value",
    "settlement_value",
    "settlement_price",
    "settlement_index_value",
    "open_time",
    "close_time",
    "expiration_time",
    "latest_expiration_time",
)


@dataclass(frozen=True)
class ExpectedCell:
    product_id: str
    series_ticker: str
    session_start_utc: datetime
    session_end_utc: datetime


@dataclass(frozen=True)
class LogTicker:
    ticker: str
    first_seen_at: str | None


def main() -> int:
    args = _parse_args()
    start = _parse_aware_timestamp(args.start, "--start")
    end = _parse_aware_timestamp(args.end, "--end")
    if end <= start:
        raise SystemExit("--end must be after --start.")

    try:
        settings = load_settings(args.env_file)
    except SettingsError as exc:
        raise SystemExit(f"Failed to load settings: {exc}") from exc

    client = KalshiClient.from_settings(settings)
    product_series = _product_series(settings)
    series_to_product = {
        series_ticker: product_id
        for product_id, series_tickers in product_series.items()
        for series_ticker in series_tickers
    }
    log_tickers = _extract_log_tickers(
        log_file=args.log_file,
        start=start,
        end=end,
        series_to_product=series_to_product,
    )
    expected_cells = _expected_cells(
        start=start,
        end=end,
        product_series=product_series,
    )
    indexed_markets = _index_markets_by_session(
        client=client,
        product_series=product_series,
        start=start,
        end=end,
    )
    log_ticker_set = frozenset(item.ticker for item in log_tickers)

    rows: list[dict[str, Any]] = []
    seen_tickers: set[str] = set()
    for cell in expected_cells:
        indexed_market = indexed_markets.get(
            (cell.product_id, cell.session_start_utc)
        )
        market_ticker = (
            _optional_text(indexed_market.get("ticker")) if indexed_market else None
        )
        if market_ticker is None:
            market_ticker = _candidate_ticker(
                series_ticker=cell.series_ticker,
                session_start_utc=cell.session_start_utc,
            )
        row = _resolved_row(
            client=client,
            product_id=cell.product_id,
            session_start_utc=cell.session_start_utc,
            session_end_utc=cell.session_end_utc,
            market_ticker=market_ticker,
            derived_from_log_ticker=market_ticker in log_ticker_set,
            fallback_market=indexed_market,
        )
        rows.append(row)
        if market_ticker is not None:
            seen_tickers.add(market_ticker)

    for item in log_tickers:
        if item.ticker in seen_tickers:
            continue
        parsed_session = _session_start_from_ticker(item.ticker)
        product_id = _product_for_ticker(item.ticker, series_to_product)
        row = _resolved_row(
            client=client,
            product_id=product_id,
            session_start_utc=parsed_session,
            session_end_utc=(
                parsed_session + timedelta(seconds=SESSION_SECONDS)
                if parsed_session is not None
                else None
            ),
            market_ticker=item.ticker,
            derived_from_log_ticker=True,
            fallback_market=None,
        )
        rows.append(row)
        seen_tickers.add(item.ticker)

    out_path = args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(_json_safe(rows), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    csv_path = out_path.with_suffix(".csv")
    _write_csv(csv_path, rows)

    expected_matrix_cells = len(expected_cells)
    expected_rows = rows[:expected_matrix_cells]
    unknown_cells = sum(
        1
        for row in expected_rows
        if not row["lookup_success"] or row["official_result"] == "UNKNOWN"
    )
    resolved_cells = expected_matrix_cells - unknown_cells
    print(f"expected_matrix_cells={expected_matrix_cells}")
    print(f"resolved_cells={resolved_cells}")
    print(f"unknown_cells={unknown_cells}")
    print(f"log_tickers_found={len(log_tickers)}")
    print(f"json_out={out_path}")
    print(f"csv_out={csv_path}")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export official Kalshi outcomes for expected crypto 15-minute "
            "sessions and any Kalshi market tickers found in runtime logs."
        )
    )
    parser.add_argument("--env-file", type=Path, required=True, help="Path to .env.")
    parser.add_argument(
        "--log-file",
        type=Path,
        required=True,
        help="Path to runtime.jsonl. Missing files are allowed and reported.",
    )
    parser.add_argument(
        "--start",
        required=True,
        help="Inclusive UTC ISO timestamp, e.g. 2026-05-07T16:15:00+00:00.",
    )
    parser.add_argument(
        "--end",
        required=True,
        help="Exclusive UTC ISO timestamp, e.g. 2026-05-08T04:00:00+00:00.",
    )
    parser.add_argument("--out", type=Path, required=True, help="Output JSON path.")
    return parser.parse_args()


def _product_series(settings: KalshiSettings) -> dict[str, tuple[str, ...]]:
    configured = settings.crypto_market_series or DEFAULT_CRYPTO_MARKET_SERIES
    product_series: dict[str, tuple[str, ...]] = {}
    for product_id in PRODUCT_IDS:
        series = tuple(
            ticker
            for ticker in configured.get(product_id, ())
            if ticker.strip().upper().endswith("15M")
        )
        if not series:
            series = tuple(
                ticker
                for ticker in DEFAULT_CRYPTO_MARKET_SERIES.get(product_id, ())
                if ticker.strip().upper().endswith("15M")
            )
        product_series[product_id] = series
    return product_series


def _expected_cells(
    *,
    start: datetime,
    end: datetime,
    product_series: dict[str, tuple[str, ...]],
) -> list[ExpectedCell]:
    cells: list[ExpectedCell] = []
    session_start = start
    while session_start < end:
        session_end = session_start + timedelta(seconds=SESSION_SECONDS)
        for product_id in PRODUCT_IDS:
            series_tickers = product_series.get(product_id, ())
            series_ticker = series_tickers[0] if series_tickers else ""
            cells.append(
                ExpectedCell(
                    product_id=product_id,
                    series_ticker=series_ticker,
                    session_start_utc=session_start,
                    session_end_utc=session_end,
                )
            )
        session_start = session_end
    return cells


def _index_markets_by_session(
    *,
    client: KalshiClient,
    product_series: dict[str, tuple[str, ...]],
    start: datetime,
    end: datetime,
) -> dict[tuple[str, datetime], dict[str, Any]]:
    indexed: dict[tuple[str, datetime], dict[str, Any]] = {}
    for product_id, series_tickers in product_series.items():
        for series_ticker in series_tickers:
            for market in _list_series_markets(client=client, series_ticker=series_ticker):
                ticker = _optional_text(market.get("ticker"))
                if ticker is None:
                    continue
                session_start = _session_start_from_ticker(ticker)
                if session_start is None:
                    session_start = _session_start_from_market_payload(market)
                if session_start is None or session_start < start or session_start >= end:
                    continue
                indexed.setdefault((product_id, session_start), market)
    return indexed


def _list_series_markets(
    *,
    client: KalshiClient,
    series_ticker: str,
) -> Iterable[dict[str, Any]]:
    if not series_ticker:
        return ()
    markets_by_ticker: dict[str, dict[str, Any]] = {}
    for status in MARKET_LIST_STATUSES:
        cursor: str | None = None
        while True:
            try:
                payload = _request_json(
                    client,
                    MARKETS_PATH,
                    {
                        "series_ticker": series_ticker,
                        "status": status,
                        "limit": str(MARKET_LIST_LIMIT),
                        "cursor": cursor or "",
                        "mve_filter": "exclude",
                    },
                )
            except KalshiClientError:
                break
            raw_markets = payload.get("markets")
            if not isinstance(raw_markets, list):
                break
            for market in raw_markets:
                if not isinstance(market, dict):
                    continue
                ticker = _optional_text(market.get("ticker"))
                if ticker is not None:
                    markets_by_ticker.setdefault(ticker, market)
            cursor = _optional_text(payload.get("cursor"))
            if cursor is None:
                break
    return tuple(markets_by_ticker.values())


def _resolved_row(
    *,
    client: KalshiClient,
    product_id: str | None,
    session_start_utc: datetime | None,
    session_end_utc: datetime | None,
    market_ticker: str | None,
    derived_from_log_ticker: bool,
    fallback_market: dict[str, Any] | None,
) -> dict[str, Any]:
    lookup_success = False
    lookup_error: str | None = None
    source_endpoint: str | None = None
    raw_market = fallback_market

    if market_ticker is None:
        lookup_error = "market_ticker_unavailable"
    else:
        source_endpoint = f"{MARKETS_PATH}/{market_ticker}"
        try:
            payload = _request_json(client, source_endpoint, None)
            raw_market = _market_payload(payload)
            lookup_success = raw_market is not None
            if raw_market is None:
                lookup_error = "market_response_missing_market_payload"
        except KalshiClientError as exc:
            lookup_error = str(exc)
            lookup_success = fallback_market is not None
            if lookup_success:
                source_endpoint = f"{MARKETS_PATH}?series_ticker={market_ticker.split('-', 1)[0]}"
                raw_market = fallback_market

    if raw_market is None:
        raw_market = {}

    return {
        "product_id": product_id,
        "session_start_utc": _format_dt(session_start_utc),
        "session_end_utc": _format_dt(session_end_utc),
        "market_ticker": market_ticker,
        "market_status": _first_text(raw_market, ("status",)),
        "official_result": _official_result(raw_market),
        "settlement_value": _first_value(raw_market, SETTLEMENT_VALUE_KEYS),
        "target_price": _target_price(raw_market),
        "source_endpoint": source_endpoint,
        "lookup_success": lookup_success,
        "lookup_error": lookup_error,
        "derived_from_log_ticker": derived_from_log_ticker,
        "market_open_time": _first_text(raw_market, ("open_time",)),
        "market_close_time": _first_text(raw_market, ("close_time",)),
        "expiration_time": _first_text(raw_market, ("expiration_time",)),
        "latest_expiration_time": _first_text(raw_market, ("latest_expiration_time",)),
        "raw_settlement_metadata": {
            key: raw_market.get(key)
            for key in RAW_DEBUG_KEYS
            if key in raw_market
        },
        "raw_market_payload": raw_market,
    }


def _request_json(
    client: KalshiClient,
    path: str,
    query_params: dict[str, str] | None,
) -> dict[str, Any]:
    # One-off reporting utility: reuse the existing authenticated client instead
    # of adding production client surface area for this export-only endpoint.
    response = client._get(path, query_params=query_params)  # noqa: SLF001
    try:
        payload = response.json()
    except ValueError as exc:
        raise KalshiClientError("Kalshi response was not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise KalshiClientError("Kalshi response was not a JSON object.")
    return payload


def _market_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    market = payload.get("market")
    if isinstance(market, dict):
        return market
    if "ticker" in payload:
        return payload
    return None


def _extract_log_tickers(
    *,
    log_file: Path,
    start: datetime,
    end: datetime,
    series_to_product: dict[str, str],
) -> tuple[LogTicker, ...]:
    if not log_file.exists():
        print(f"log_file_missing={log_file}")
        return ()

    first_seen: dict[str, str | None] = {}
    with log_file.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                print(f"log_line_skipped_invalid_json={line_number}")
                continue
            if not isinstance(record, dict):
                continue
            recorded_at = _parse_optional_timestamp(record.get("recorded_at"))
            if recorded_at is None or recorded_at < start or recorded_at >= end:
                continue
            for ticker in _walk_kalshi_tickers(record):
                if _product_for_ticker(ticker, series_to_product) is None:
                    continue
                first_seen.setdefault(ticker, _format_dt(recorded_at))
    return tuple(
        LogTicker(ticker=ticker, first_seen_at=first_seen[ticker])
        for ticker in sorted(first_seen)
    )


def _walk_kalshi_tickers(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk_kalshi_tickers(item)
        return
    if isinstance(value, list):
        for item in value:
            yield from _walk_kalshi_tickers(item)
        return
    if isinstance(value, str):
        normalized = value.strip()
        if _is_kalshi_market_ticker(normalized):
            yield normalized


def _is_kalshi_market_ticker(value: str) -> bool:
    return value.startswith("KX") and "-" in value


def _product_for_ticker(
    ticker: str,
    series_to_product: dict[str, str],
) -> str | None:
    series_ticker = ticker.split("-", 1)[0]
    return series_to_product.get(series_ticker)


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


def _session_start_from_market_payload(market: dict[str, Any]) -> datetime | None:
    open_time = _parse_optional_timestamp(market.get("open_time"))
    close_time = _parse_optional_timestamp(market.get("close_time"))
    expiration_time = _parse_optional_timestamp(market.get("expiration_time"))
    for candidate in (open_time,):
        if candidate is not None and _is_quarter_hour(candidate):
            return candidate
    for candidate in (close_time, expiration_time):
        if candidate is not None and _is_quarter_hour(candidate):
            return candidate - timedelta(seconds=SESSION_SECONDS)
    return None


def _candidate_ticker(*, series_ticker: str, session_start_utc: datetime) -> str | None:
    if not series_ticker:
        return None
    return (
        f"{series_ticker}-"
        f"{session_start_utc:%y}"
        f"{session_start_utc:%b}".upper()
        f"{session_start_utc:%d%H%M}-00"
    )


def _official_result(raw_market: dict[str, Any]) -> str:
    value = _first_value(raw_market, OFFICIAL_RESULT_KEYS)
    if value is None:
        return "UNKNOWN"
    text = str(value).strip()
    return text if text else "UNKNOWN"


def _target_price(raw_market: dict[str, Any]) -> str | None:
    value = _first_value(raw_market, TARGET_PRICE_KEYS)
    if value is None:
        return None
    try:
        return str(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return str(value)


def _first_text(raw_market: dict[str, Any], keys: Iterable[str]) -> str | None:
    value = _first_value(raw_market, keys)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_value(raw_market: dict[str, Any], keys: Iterable[str]) -> Any | None:
    for key in keys:
        value = raw_market.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _parse_aware_timestamp(value: str, label: str) -> datetime:
    parsed = _parse_optional_timestamp(value)
    if parsed is None:
        raise SystemExit(f"{label} must be an aware ISO timestamp.")
    return parsed


def _parse_optional_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _is_quarter_hour(value: datetime) -> bool:
    return value.second == 0 and value.microsecond == 0 and value.minute % 15 == 0


def _format_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = (
        "product_id",
        "session_start_utc",
        "session_end_utc",
        "market_ticker",
        "market_status",
        "official_result",
        "settlement_value",
        "target_price",
        "source_endpoint",
        "lookup_success",
        "lookup_error",
        "derived_from_log_ticker",
        "market_open_time",
        "market_close_time",
        "expiration_time",
        "latest_expiration_time",
        "raw_settlement_metadata",
        "raw_market_payload",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: _csv_value(row.get(key))
                    for key in fieldnames
                }
            )


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(_json_safe(value), sort_keys=True)
    return value


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return _format_dt(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
