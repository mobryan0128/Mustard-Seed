"""Summarize roadmap replay decisions."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


UNKNOWN_VALUE = "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize roadmap replay decisions.")
    parser.add_argument("--roadmap", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    roadmap_path = Path(args.roadmap)
    _validate_existing_file(roadmap_path, "--roadmap")
    counts: Counter[tuple[str, str]] = Counter()
    with roadmap_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            counts[
                (
                    _report_value(row.get("new_decision")),
                    _report_value(row.get("old_reason")),
                )
            ] += 1
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["new_decision", "old_reason", "count"])
        for (decision, old_reason), count in sorted(
            counts.items(),
            key=lambda item: (item[0][0], item[0][1]),
        ):
            writer.writerow([decision, old_reason, count])


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
