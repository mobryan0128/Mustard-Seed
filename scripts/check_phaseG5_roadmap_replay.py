"""Phase G5 checks for roadmap replay output shape."""

import json
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.replay_roadmap_decisions import replay_events  # noqa: E402


def main() -> None:
    event = {
        "record_type": "live_order_intent_skipped",
        "payload": {
            "product_id": "BTC-USD",
            "market_ticker": "TEST",
            "reason": "ev_filter_blocked",
            "lookback_return_bps": "12",
            "recent_5m_range_bps": "10",
            "recent_3m_return_bps": "6",
            "recent_3m_range_bps": "8",
            "distance_to_target_bps": "2",
            "distance_to_recent_high_bps": "8",
            "momentum_deceleration_status": "not_bursting",
            "range_expansion_status": "normal",
            "entry_price": "0.45",
            "side_needs_cross": False,
            "required_bps_per_minute": "0",
            "classification_reason": "trend_continuation",
            "signal_conflict_flags": {"impulse_direction_conflict": False},
        },
    }
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "events.jsonl"
        out = Path(directory) / "out.jsonl"
        path.write_text(json.dumps(event) + "\n", encoding="utf-8")
        replay_events(events_path=path, output_path=out)
        rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert rows
    assert "new_decision" in rows[0]
    assert "composite_score" in rows[0]
    assert "uncapped_composite_score" in rows[0]
    assert "high_score_danger_cap_applied" in rows[0]
    assert "distance_to_target_abs_bps" in rows[0]
    assert "burst_context_status" in rows[0]
    assert "quiet_exhaustion_direction_conflict_blocked" in rows[0]
    assert "quiet_exhaustion_direction_conflict_reasons" in rows[0]
    assert "reversal_signal_source" in rows[0]
    assert "opposite_side_ev" in rows[0]
    print("phaseG5 roadmap replay checks passed")


if __name__ == "__main__":
    main()
