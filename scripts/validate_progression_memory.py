"""Inspect progression-relevant fields from roadmap replay output."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


UNKNOWN_VALUE = "unknown"


FIELDS = [
    "line_number",
    "product_id",
    "market_ticker",
    "new_decision",
    "return_range_ratio",
    "composite_score",
    "continuation_score",
    "reversal_score",
    "downgrade_reasons",
    "upgrade_reasons",
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export progression-memory validation fields from replay output.",
    )
    parser.add_argument("--roadmap", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    roadmap_path = Path(args.roadmap)
    _validate_existing_file(roadmap_path, "--roadmap")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with roadmap_path.open("r", encoding="utf-8") as source, output.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as sink:
        writer = csv.DictWriter(sink, fieldnames=FIELDS)
        writer.writeheader()
        for line in source:
            if not line.strip():
                continue
            row = json.loads(line)
            writer.writerow({field: _report_value(row.get(field)) for field in FIELDS})


def _validate_existing_file(path: Path, label: str) -> None:
    if not path.exists():
        raise SystemExit(f"{label} file does not exist: {path}")
    if not path.is_file():
        raise SystemExit(f"{label} must be a file: {path}")


def _report_value(value: object) -> str:
    if value is None:
        return UNKNOWN_VALUE
    text = str(value).strip()
    return text if text else UNKNOWN_VALUE


if __name__ == "__main__":
    main()
