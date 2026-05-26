"""Fetch read-only Coinbase Exchange OHLCV candles for audit chart alignment.

Examples:

    python scripts/fetch_chart_candles.py --start "2026-05-19T10:00:00+00:00" --end "2026-05-19T10:30:00+00:00" --products "BTC-USD,ETH-USD" --granularities "60,300" --out chart_csv/test_fetch

Coinbase Exchange candles are public market data. This script does not use API
credentials, submit orders, modify trading behavior, or read .env.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx


DEFAULT_PRODUCTS = ("BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "DOGE-USD", "BNB-USD", "HYPE-USD")
DEFAULT_GRANULARITIES = (60, 300, 900, 3600)
VALID_GRANULARITIES = {60, 300, 900, 3600, 21600, 86400}
DEFAULT_SOURCE = "coinbase-exchange"
COINBASE_CANDLES_URL = "https://api.exchange.coinbase.com/products/{product_id}/candles"
CSV_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume", "product_id", "granularity", "source")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch read-only Coinbase Exchange OHLCV candles into audit CSV files.")
    parser.add_argument("--start", required=True, help="Inclusive ISO timestamp, e.g. 2026-05-19T10:00:00+00:00")
    parser.add_argument("--end", required=True, help="Exclusive ISO timestamp, e.g. 2026-05-19T10:30:00+00:00")
    parser.add_argument("--products", default=",".join(DEFAULT_PRODUCTS), help="Comma-separated Coinbase product IDs.")
    parser.add_argument("--granularities", default=",".join(str(item) for item in DEFAULT_GRANULARITIES), help="Comma-separated granularities in seconds.")
    parser.add_argument("--out", type=Path, required=True, help="Output directory for CSVs and fetch metadata.")
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--sleep-seconds", type=float, default=0.25)
    parser.add_argument("--max-retries", type=int, default=3)
    args = parser.parse_args()

    result = fetch_chart_candles(
        start_raw=args.start,
        end_raw=args.end,
        products_raw=args.products,
        granularities_raw=args.granularities,
        out_dir=args.out,
        source=args.source,
        sleep_seconds=args.sleep_seconds,
        max_retries=args.max_retries,
    )
    print(f"output_dir={result['output_dir']}")
    print(f"errors={result['errors_count']}")
    print(f"summary={Path(result['output_dir']) / 'FETCH_SUMMARY.json'}")
    return 0


def fetch_chart_candles(
    *,
    start_raw: str,
    end_raw: str,
    products_raw: str | None,
    granularities_raw: str | None,
    out_dir: Path,
    source: str = DEFAULT_SOURCE,
    sleep_seconds: float = 0.25,
    max_retries: int = 3,
) -> dict[str, Any]:
    start = _parse_ts(start_raw, "--start")
    end = _parse_ts(end_raw, "--end")
    if end <= start:
        raise SystemExit("--end must be after --start")

    products = _parse_products(products_raw)
    granularities = _parse_granularities(granularities_raw)
    out_dir.mkdir(parents=True, exist_ok=True)

    errors_path = out_dir / "FETCH_ERRORS.jsonl"
    if errors_path.exists():
        errors_path.unlink()

    per_file: dict[str, int] = {}
    errors_count = 0
    with httpx.Client(timeout=30.0, headers={"User-Agent": "kalshi-bot-audit-chart-fetcher"}) as client:
        for product_id in products:
            for granularity in granularities:
                rows: list[dict[str, Any]] = []
                try:
                    rows = _fetch_product_granularity(
                        client=client,
                        product_id=product_id,
                        granularity=granularity,
                        start=start,
                        end=end,
                        source=source,
                        sleep_seconds=sleep_seconds,
                        max_retries=max_retries,
                    )
                except Exception as exc:  # noqa: BLE001 - keep one failed market from aborting the audit fetch.
                    errors_count += 1
                    _append_error(
                        errors_path,
                        {
                            "level": "error",
                            "product_id": product_id,
                            "granularity": granularity,
                            "error": str(exc),
                            "error_type": type(exc).__name__,
                        },
                    )

                path = out_dir / f"{product_id}_{granularity}.csv"
                _write_candle_csv(path, rows)
                per_file[str(path)] = len(rows)
                if not rows:
                    errors_count += 1
                    _append_error(
                        errors_path,
                        {
                            "level": "warning",
                            "product_id": product_id,
                            "granularity": granularity,
                            "error": "no_rows_fetched",
                        },
                    )

    summary = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "products": products,
        "granularities": granularities,
        "source": source,
        "output_dir": str(out_dir),
        "per_file": per_file,
        "errors_count": errors_count,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (out_dir / "FETCH_SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not errors_path.exists():
        errors_path.write_text("", encoding="utf-8")
    return summary


def _fetch_product_granularity(
    *,
    client: httpx.Client,
    product_id: str,
    granularity: int,
    start: datetime,
    end: datetime,
    source: str,
    sleep_seconds: float,
    max_retries: int,
) -> list[dict[str, Any]]:
    rows_by_timestamp: dict[int, dict[str, Any]] = {}
    chunk_start = start
    chunk_delta = timedelta(seconds=granularity * 300)
    while chunk_start < end:
        chunk_end = min(chunk_start + chunk_delta, end)
        response_rows = _request_chunk(
            client=client,
            product_id=product_id,
            granularity=granularity,
            start=chunk_start,
            end=chunk_end,
            max_retries=max_retries,
        )
        for item in response_rows:
            parsed = _parse_candle_row(
                item,
                product_id=product_id,
                granularity=granularity,
                source=source,
                start=start,
                end=end,
            )
            if parsed is not None:
                rows_by_timestamp[int(item[0])] = parsed
        chunk_start = chunk_end
        if chunk_start < end and sleep_seconds > 0:
            time.sleep(sleep_seconds)
    return [rows_by_timestamp[key] for key in sorted(rows_by_timestamp)]


def _request_chunk(
    *,
    client: httpx.Client,
    product_id: str,
    granularity: int,
    start: datetime,
    end: datetime,
    max_retries: int,
) -> list[Any]:
    url = COINBASE_CANDLES_URL.format(product_id=product_id)
    params = {"start": start.isoformat(), "end": end.isoformat(), "granularity": str(granularity)}
    attempts = max(max_retries, 1)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise ValueError(f"unexpected Coinbase response shape: {payload!r}")
            return payload
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(min(2.0, 0.25 * attempt))
    raise RuntimeError(f"Coinbase request failed for {product_id} {granularity}: {last_error}") from last_error


def _parse_candle_row(
    item: Any,
    *,
    product_id: str,
    granularity: int,
    source: str,
    start: datetime,
    end: datetime,
) -> dict[str, Any] | None:
    if not isinstance(item, list) or len(item) < 6:
        raise ValueError(f"unexpected candle row shape for {product_id} {granularity}: {item!r}")
    candle_ts = datetime.fromtimestamp(int(item[0]), tz=timezone.utc)
    if candle_ts < start or candle_ts >= end:
        return None
    return {
        "timestamp": candle_ts.isoformat(),
        "open": item[3],
        "high": item[2],
        "low": item[1],
        "close": item[4],
        "volume": item[5],
        "product_id": product_id,
        "granularity": granularity,
        "source": source,
    }


def _write_candle_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CSV_COLUMNS), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _append_error(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    enriched = {"generated_at": datetime.now(timezone.utc).isoformat(), **row}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(enriched, sort_keys=True) + "\n")


def _parse_products(raw: str | None) -> list[str]:
    values = _split_csv(raw) if raw else list(DEFAULT_PRODUCTS)
    if not values:
        raise SystemExit("--products must include at least one product")
    return values


def _parse_granularities(raw: str | None) -> list[int]:
    raw_values = _split_csv(raw) if raw else [str(item) for item in DEFAULT_GRANULARITIES]
    values: list[int] = []
    for item in raw_values:
        try:
            value = int(item)
        except ValueError as exc:
            raise SystemExit(f"invalid granularity: {item}") from exc
        if value not in VALID_GRANULARITIES:
            allowed = ",".join(str(item) for item in sorted(VALID_GRANULARITIES))
            raise SystemExit(f"invalid granularity {value}; allowed values: {allowed}")
        values.append(value)
    if not values:
        raise SystemExit("--granularities must include at least one value")
    return values


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _parse_ts(raw: str, label: str) -> datetime:
    value = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit(f"{label} must be an ISO timestamp: {raw}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


if __name__ == "__main__":
    raise SystemExit(main())
