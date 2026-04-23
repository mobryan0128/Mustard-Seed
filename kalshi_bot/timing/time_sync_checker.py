"""Source timestamp drift checks for Kalshi and crypto feed data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any


class TimeSyncError(ValueError):
    """Raised when a source timestamp cannot be normalized."""


@dataclass(frozen=True)
class TimeSyncObservation:
    """Observed drift between source time and local receive time."""

    source: str
    source_timestamp: str
    local_timestamp: str
    absolute_drift_ms: Decimal
    within_threshold: bool


class TimeSyncChecker:
    """Compare incoming source timestamps with local receive time."""

    def __init__(self, *, max_drift_ms: int) -> None:
        if max_drift_ms < 0:
            raise TimeSyncError("max_drift_ms must be greater than or equal to zero.")
        self._max_drift_ms = Decimal(max_drift_ms)

    @property
    def max_drift_ms(self) -> Decimal:
        return self._max_drift_ms

    def observe(
        self,
        *,
        source: str,
        source_timestamp: Any,
        local_timestamp: datetime | None = None,
    ) -> TimeSyncObservation:
        normalized_source = _normalize_source_timestamp(source_timestamp)
        normalized_local = _normalize_local_timestamp(local_timestamp)
        absolute_drift_ms = abs(
            Decimal((normalized_local - normalized_source).total_seconds()) * Decimal("1000")
        )
        return TimeSyncObservation(
            source=_require_text(source, "source"),
            source_timestamp=normalized_source.isoformat(),
            local_timestamp=normalized_local.isoformat(),
            absolute_drift_ms=absolute_drift_ms.quantize(Decimal("0.001")),
            within_threshold=absolute_drift_ms <= self._max_drift_ms,
        )


def _normalize_source_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _ensure_utc(value)
    if isinstance(value, (int, float, Decimal)):
        return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise TimeSyncError("source_timestamp is required.")
        if stripped.isdigit():
            return datetime.fromtimestamp(int(stripped) / 1000.0, tz=timezone.utc)
        return _parse_iso_datetime(stripped)
    raise TimeSyncError("Unsupported source timestamp type.")


def _normalize_local_timestamp(value: datetime | None) -> datetime:
    return _ensure_utc(value or datetime.now(timezone.utc))


def _parse_iso_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise TimeSyncError("source_timestamp must be ISO-8601 or epoch milliseconds.") from exc
    return _ensure_utc(parsed)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _require_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise TimeSyncError(f"{field_name} is required.")
    return normalized
