"""Deterministic adaptive thresholds for continuation and reversal scoring."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping


ZERO = Decimal("0")
ONE = Decimal("1")
DEFAULT_CHOP_BASE_BPS = Decimal("3")
DEFAULT_CHOP_RANGE_MULTIPLIER = Decimal("0.50")
DEFAULT_NEAR_EXTREME_BPS = Decimal("6")
DEFAULT_RATIO_FLOOR = Decimal("0.50")
DEFAULT_CONTINUATION_SCORE_MIN = Decimal("0.60")
DEFAULT_REQUIRED_BPS_LIMIT = Decimal("0.25")
DEFAULT_VOLATILITY_BASELINE_BPS = Decimal("10")


@dataclass(frozen=True)
class AdaptiveThresholds:
    """Per-product thresholds used by scoring and diagnostics."""

    product_id: str
    volatility_baseline_bps: Decimal
    product_volatility_scale: Decimal
    adaptive_chop_threshold_bps: Decimal
    adaptive_near_extreme_bps: Decimal
    adaptive_ratio_floor: Decimal
    adaptive_continuation_score_min: Decimal
    adaptive_required_bps_per_minute_limit: Decimal
    adaptive_pacing_multiplier: Decimal

    def as_payload(self) -> dict[str, object]:
        return {
            "adaptive_product_id": self.product_id,
            "adaptive_volatility_baseline_bps": self.volatility_baseline_bps,
            "adaptive_product_volatility_scale": self.product_volatility_scale,
            "adaptive_chop_threshold_bps": self.adaptive_chop_threshold_bps,
            "adaptive_near_extreme_bps": self.adaptive_near_extreme_bps,
            "adaptive_ratio_floor": self.adaptive_ratio_floor,
            "adaptive_continuation_score_min": self.adaptive_continuation_score_min,
            "adaptive_required_bps_per_minute_limit": (
                self.adaptive_required_bps_per_minute_limit
            ),
            "adaptive_pacing_multiplier": self.adaptive_pacing_multiplier,
        }


def adaptive_thresholds_for_product(
    *,
    product_id: str,
    recent_5m_range_bps: Decimal | None,
    base_near_extreme_bps_by_product: Mapping[str, Decimal] | None = None,
    ratio_floor_by_product: Mapping[str, Decimal] | None = None,
    volatility_scale_by_product: Mapping[str, Decimal] | None = None,
    continuation_score_min: Decimal = DEFAULT_CONTINUATION_SCORE_MIN,
    max_required_bps_per_minute: Decimal = DEFAULT_REQUIRED_BPS_LIMIT,
    adaptive_enabled: bool = True,
    adaptive_chop_enabled: bool = True,
    adaptive_pacing_enabled: bool = True,
) -> AdaptiveThresholds:
    """Return deterministic thresholds from product identity and recent range."""

    product_key = product_id.upper()
    range_bps = _non_negative_decimal(
        recent_5m_range_bps,
        default=DEFAULT_VOLATILITY_BASELINE_BPS,
    )
    volatility_scale = _product_decimal(
        volatility_scale_by_product,
        product_key,
        default=ONE,
    )
    base_near_extreme = _product_decimal(
        base_near_extreme_bps_by_product,
        product_key,
        default=_default_near_extreme(product_key),
    )
    ratio_floor = _product_decimal(
        ratio_floor_by_product,
        product_key,
        default=_default_ratio_floor(product_key),
    )
    if not adaptive_enabled:
        return AdaptiveThresholds(
            product_id=product_key,
            volatility_baseline_bps=range_bps,
            product_volatility_scale=volatility_scale,
            adaptive_chop_threshold_bps=DEFAULT_CHOP_BASE_BPS,
            adaptive_near_extreme_bps=base_near_extreme,
            adaptive_ratio_floor=ratio_floor,
            adaptive_continuation_score_min=continuation_score_min,
            adaptive_required_bps_per_minute_limit=max_required_bps_per_minute,
            adaptive_pacing_multiplier=ONE,
        )

    chop_threshold = (
        max(DEFAULT_CHOP_BASE_BPS, range_bps * DEFAULT_CHOP_RANGE_MULTIPLIER)
        if adaptive_chop_enabled
        else DEFAULT_CHOP_BASE_BPS
    )
    volatility_factor = _bounded(
        range_bps / DEFAULT_VOLATILITY_BASELINE_BPS,
        minimum=Decimal("0.75"),
        maximum=Decimal("2.00"),
    )
    near_extreme = base_near_extreme * volatility_factor * volatility_scale
    required_bps_limit = max_required_bps_per_minute * volatility_factor
    pacing_multiplier = (
        _bounded(volatility_factor * volatility_scale, minimum=ONE, maximum=Decimal("2.00"))
        if adaptive_pacing_enabled
        else ONE
    )
    return AdaptiveThresholds(
        product_id=product_key,
        volatility_baseline_bps=range_bps.quantize(Decimal("0.0001")),
        product_volatility_scale=volatility_scale,
        adaptive_chop_threshold_bps=chop_threshold.quantize(Decimal("0.0001")),
        adaptive_near_extreme_bps=near_extreme.quantize(Decimal("0.0001")),
        adaptive_ratio_floor=ratio_floor,
        adaptive_continuation_score_min=continuation_score_min,
        adaptive_required_bps_per_minute_limit=required_bps_limit.quantize(
            Decimal("0.0001")
        ),
        adaptive_pacing_multiplier=pacing_multiplier.quantize(Decimal("0.0001")),
    )


def _product_decimal(
    values: Mapping[str, Decimal] | None,
    product_key: str,
    *,
    default: Decimal,
) -> Decimal:
    if not values:
        return default
    return Decimal(str(values.get(product_key, default)))


def _non_negative_decimal(value: Decimal | None, *, default: Decimal) -> Decimal:
    if value is None:
        return default
    parsed = Decimal(str(value))
    if parsed <= ZERO:
        return default
    return parsed


def _bounded(value: Decimal, *, minimum: Decimal, maximum: Decimal) -> Decimal:
    return min(max(value, minimum), maximum)


def _default_near_extreme(product_key: str) -> Decimal:
    if product_key in {"BTC-USD", "ETH-USD"}:
        return Decimal("6")
    if product_key in {"SOL-USD", "BNB-USD"}:
        return Decimal("4")
    return Decimal("2")


def _default_ratio_floor(product_key: str) -> Decimal:
    if product_key in {"DOGE-USD", "XRP-USD", "HYPE-USD"}:
        return Decimal("0.80")
    return DEFAULT_RATIO_FLOOR
