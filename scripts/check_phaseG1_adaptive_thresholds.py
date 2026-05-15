"""Phase G1 checks for deterministic adaptive thresholds."""

import sys
from decimal import Decimal
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi_bot.forecast.adaptive_thresholds import adaptive_thresholds_for_product  # noqa: E402


def main() -> None:
    thresholds = adaptive_thresholds_for_product(
        product_id="BTC-USD",
        recent_5m_range_bps=Decimal("20"),
        adaptive_enabled=True,
        adaptive_chop_enabled=True,
        adaptive_pacing_enabled=True,
    )
    assert thresholds.adaptive_chop_threshold_bps == Decimal("10.0000")
    assert thresholds.adaptive_near_extreme_bps > Decimal("6")
    assert thresholds.adaptive_ratio_floor == Decimal("0.50")
    assert thresholds.adaptive_pacing_multiplier >= Decimal("1")

    doge = adaptive_thresholds_for_product(
        product_id="DOGE-USD",
        recent_5m_range_bps=Decimal("5"),
        adaptive_enabled=True,
    )
    assert doge.adaptive_ratio_floor == Decimal("0.80")
    assert doge.adaptive_near_extreme_bps >= Decimal("1.5")
    print("phaseG1 adaptive threshold checks passed")


if __name__ == "__main__":
    main()
