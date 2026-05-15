"""Export reversal candidates from roadmap replay output."""

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
    "reversal_candidate_status",
    "reversal_probability",
    "opposite_executable_price",
    "reversal_expected_value",
    "reversal_rejection_reason",
    "return_range_ratio",
    "near_extreme_distance_bps",
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export generated reversal candidates from roadmap replay output.",
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
            if row.get("new_decision") == "generate_reversal" or row.get(
                "reversal_candidate_status"
            ) == "shadow_candidate":
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
