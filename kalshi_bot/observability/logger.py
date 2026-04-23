"""Structured append-only runtime logging."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping


class StructuredLoggerError(RuntimeError):
    """Raised when structured log writing fails."""


@dataclass(frozen=True)
class LogRecord:
    """Normalized structured log record."""

    recorded_at: str
    category: str
    event_type: str
    source: str | None = None
    identifier: str | None = None
    payload: dict[str, Any] | None = None


class StructuredLogger:
    """Write append-only JSONL runtime logs."""

    def __init__(
        self,
        *,
        log_directory: Path,
        enabled: bool = True,
        file_name: str = "runtime.jsonl",
    ) -> None:
        self._log_directory = log_directory
        self._enabled = enabled
        self._path = log_directory / file_name

    @property
    def path(self) -> Path:
        return self._path

    def log_event(
        self,
        *,
        category: str,
        event_type: str,
        source: str | None = None,
        identifier: str | None = None,
        payload: Mapping[str, Any] | None = None,
        recorded_at: datetime | None = None,
    ) -> LogRecord:
        record = LogRecord(
            recorded_at=_utc_isoformat(recorded_at),
            category=_require_text(category, "category"),
            event_type=_require_text(event_type, "event_type"),
            source=_optional_text(source),
            identifier=_optional_text(identifier),
            payload=_normalize_mapping(payload),
        )
        self.write_record(record)
        return record

    def write_record(self, record: LogRecord) -> None:
        if not self._enabled:
            return
        try:
            self._log_directory.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(_json_line(asdict(record)))
        except OSError as exc:
            raise StructuredLoggerError(f"Failed to write structured log: {exc}") from exc


def _json_line(payload: Mapping[str, Any]) -> str:
    return json.dumps(_normalize_value(dict(payload)), sort_keys=True) + "\n"


def _normalize_mapping(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return _normalize_value(dict(value))


def _normalize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return _utc_isoformat(value)
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return _normalize_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _normalize_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_value(item) for item in value]
    return value


def _utc_isoformat(value: datetime | None) -> str:
    timestamp = value or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = timestamp.astimezone(timezone.utc)
    return timestamp.isoformat()


def _require_text(value: str, field_name: str) -> str:
    normalized = _optional_text(value)
    if normalized is None:
        raise StructuredLoggerError(f"{field_name} is required.")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized
