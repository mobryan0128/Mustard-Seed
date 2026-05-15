"""File-backed replay recording for market and feed data."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping


class ReplayEngineError(RuntimeError):
    """Raised when replay persistence fails."""


@dataclass(frozen=True)
class ReplayRecord:
    """Normalized replay record."""

    recorded_at: str
    source: str
    record_type: str
    identifier: str | None = None
    payload: dict[str, Any] | None = None


class ReplayEngine:
    """Persist append-only replay records as JSON lines."""

    def __init__(
        self,
        *,
        replay_directory: Path,
        enabled: bool = True,
        file_name: str = "replay.jsonl",
    ) -> None:
        self._replay_directory = replay_directory
        self._enabled = enabled
        self._path = replay_directory / file_name

    @property
    def path(self) -> Path:
        return self._path

    def record_message(
        self,
        *,
        source: str,
        message_type: str,
        payload: Mapping[str, Any] | None,
        identifier: str | None = None,
        recorded_at: datetime | None = None,
    ) -> ReplayRecord:
        record = ReplayRecord(
            recorded_at=_utc_isoformat(recorded_at),
            source=_require_text(source, "source"),
            record_type=_require_text(message_type, "message_type"),
            identifier=_optional_text(identifier),
            payload=_normalize_mapping(payload),
        )
        self.write_record(record)
        return record

    def record_snapshot(
        self,
        *,
        source: str,
        snapshot_name: str,
        snapshot: Mapping[str, Any] | None,
        recorded_at: datetime | None = None,
    ) -> ReplayRecord:
        return self.record_message(
            source=source,
            message_type=snapshot_name,
            payload=snapshot,
            recorded_at=recorded_at,
        )

    def record_roadmap_decision(
        self,
        *,
        identifier: str | None,
        payload: Mapping[str, Any],
        recorded_at: datetime | None = None,
    ) -> ReplayRecord:
        return self.record_message(
            source="roadmap_decision",
            message_type="roadmap_decision",
            identifier=identifier,
            payload=payload,
            recorded_at=recorded_at,
        )

    def write_record(self, record: ReplayRecord) -> None:
        if not self._enabled:
            return
        try:
            self._replay_directory.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(_json_line(asdict(record)))
        except OSError as exc:
            raise ReplayEngineError(f"Failed to write replay record: {exc}") from exc


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
        raise ReplayEngineError(f"{field_name} is required.")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized
