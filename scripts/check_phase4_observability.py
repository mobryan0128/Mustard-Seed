"""Validate Phase 4 logging, replay, and time sync behavior locally."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi_bot.config.settings import SettingsError, load_settings  # noqa: E402
from kalshi_bot.observability.logger import (  # noqa: E402
    StructuredLogger,
    StructuredLoggerError,
)
from kalshi_bot.observability.replay_engine import ReplayEngine, ReplayEngineError  # noqa: E402
from kalshi_bot.timing.time_sync_checker import (  # noqa: E402
    TimeSyncChecker,
    TimeSyncError,
)


def main() -> int:
    try:
        settings = load_settings()
        logger = StructuredLogger(
            log_directory=settings.log_directory,
            enabled=settings.log_jsonl_enabled,
        )
        replay_engine = ReplayEngine(
            replay_directory=settings.replay_directory,
            enabled=settings.replay_write_enabled,
        )
        checker = TimeSyncChecker(max_drift_ms=settings.time_sync_max_drift_ms)

        log_record = logger.log_event(
            category="connection",
            event_type="phase4_validation",
            source="phase4_check",
            payload={"status": "started"},
        )
        replay_message = replay_engine.record_message(
            source="kalshi_ws",
            message_type="ticker",
            identifier="KXBTCD-TEST",
            payload={
                "market_ticker": "KXBTCD-TEST",
                "price_dollars": "0.54",
                "received": True,
            },
        )
        replay_snapshot = replay_engine.record_snapshot(
            source="crypto_feed",
            snapshot_name="crypto_state_snapshot",
            snapshot={
                "BTC-USD": {"price": "70000.12", "best_bid": "69999.95", "best_ask": "70000.20"},
                "ETH-USD": {"price": "3200.10", "best_bid": "3200.00", "best_ask": "3200.15"},
            },
        )

        base_time = datetime.now(timezone.utc)
        within_threshold = checker.observe(
            source="kalshi_ws",
            source_timestamp=int((base_time - timedelta(milliseconds=250)).timestamp() * 1000),
            local_timestamp=base_time,
        )
        outside_threshold = checker.observe(
            source="crypto_feed",
            source_timestamp=(base_time - timedelta(milliseconds=2500)).isoformat(),
            local_timestamp=base_time,
        )
        if settings.time_sync_log_results:
            logger.log_event(
                category="time_sync",
                event_type="observation",
                source=within_threshold.source,
                payload={
                    "absolute_drift_ms": within_threshold.absolute_drift_ms,
                    "within_threshold": within_threshold.within_threshold,
                },
            )
            logger.log_event(
                category="time_sync",
                event_type="observation",
                source=outside_threshold.source,
                payload={
                    "absolute_drift_ms": outside_threshold.absolute_drift_ms,
                    "within_threshold": outside_threshold.within_threshold,
                },
            )
    except (
        SettingsError,
        StructuredLoggerError,
        ReplayEngineError,
        TimeSyncError,
        OSError,
    ) as exc:
        print(f"Phase 4 observability check failed: {exc}", file=sys.stderr)
        return 1

    print("Phase 4 observability check succeeded.")
    print(f"log_path={logger.path}")
    print(f"log_recorded_at={log_record.recorded_at}")
    print(f"replay_path={replay_engine.path}")
    print(f"replay_records_written=2")
    print(f"replay_message_type={replay_message.record_type}")
    print(f"replay_snapshot_type={replay_snapshot.record_type}")
    print(f"time_sync_within_threshold={within_threshold.within_threshold}")
    print(f"time_sync_within_threshold_drift_ms={within_threshold.absolute_drift_ms}")
    print(f"time_sync_outside_threshold={outside_threshold.within_threshold}")
    print(f"time_sync_outside_threshold_drift_ms={outside_threshold.absolute_drift_ms}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
