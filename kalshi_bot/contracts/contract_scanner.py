"""Read-only contract scanning over current Kalshi market state and bias output."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Mapping

from kalshi_bot.config.settings import KalshiSettings
from kalshi_bot.contracts.contract_scorer import (
    CompositeQualityScore,
    ContractScore,
    score_candidate_quality,
    score_contract,
)
from kalshi_bot.contracts.reversal_classifier import (
    ReversalClassification,
    classify_reversal_probability,
    reversal_expected_value,
)
from kalshi_bot.forecast.bias_engine import BiasSnapshot
from kalshi_bot.forecast.adaptive_thresholds import (
    AdaptiveThresholds,
    adaptive_thresholds_for_product,
)
from kalshi_bot.forecast.progression_memory import ProgressionMemoryState
from kalshi_bot.market.market_state_cache import MarketStateSnapshot, TickerState


TWO_DECIMAL = Decimal("2")
BASIS_POINTS_MULTIPLIER = Decimal("10000")
SECONDS_PER_MINUTE = Decimal("60")
LATE_EXPANSION_IMPULSE_RETURN_BPS = Decimal("6.000")
IMPULSE_CONFIRMATION_RETURN_BPS = Decimal("3.000")
REVERSAL_MIN_RECENT_RETURN_BPS = Decimal("15.000")
TREND_MIN_RECENT_RETURN_BPS = Decimal("15.000")
UNREALISTIC_LATE_CROSS_SECONDS = 60
UNREALISTIC_LATE_CROSS_DISTANCE_BPS = Decimal("15.000")
NEEDS_CROSS_SOFT_DISTANCE_BPS = Decimal("5.000")
NEEDS_CROSS_HARD_DISTANCE_BPS = Decimal("10.000")
NEEDS_CROSS_TIGHT_REQUIRED_BPS_PER_MINUTE = Decimal("1.000")
NEEDS_CROSS_HARD_REQUIRED_BPS_PER_MINUTE = Decimal("2.000")
SCORE_DOWNGRADE_CONFLICT_CONFIDENCE = 30
SCORE_DOWNGRADE_NEEDS_CROSS_CONFIDENCE = 40
SCORE_DOWNGRADE_SOFT_NEEDS_CROSS_CONFIDENCE = 30
SCORE_DOWNGRADE_REVERSAL_NEAR_TARGET_CONFIDENCE = 30
SCORE_BONUS_CONFIRMED_TREND_CONFIDENCE = 10
SCORE_MAX_CONFIDENCE = 90
REVERSAL_NOISE_ZONE_DISTANCE_BPS = Decimal("5.000")
_ROADMAP_MAPPED_QUIET_SIGNAL_BLOCKS = frozenset(
    {
        "quiet_continuation_recent_move_too_large",
        "quiet_continuation_3m_burst_too_large",
        "quiet_continuation_5m_burst_too_large",
        "quiet_continuation_range_expanded",
        "quiet_continuation_decelerating_after_burst",
        "quiet_continuation_near_recent_extreme",
    }
)


class ContractScannerError(ValueError):
    """Raised when scanner configuration is missing or invalid."""


@dataclass(frozen=True)
class TargetFeasibility:
    current_spot_price: Decimal | None
    target_price: Decimal | None
    target_price_source: str | None
    distance_to_target: Decimal | None
    distance_to_target_bps: Decimal | None
    time_remaining_seconds: int | None
    required_bps_per_minute: Decimal | None
    side_currently_itm: bool | None
    side_needs_cross: bool | None
    feasibility_status: str


@dataclass(frozen=True)
class ScannedContract:
    """Normalized ranked contract candidate."""

    product_id: str
    market_ticker: str
    direction: str
    structure: str
    confidence: int
    best_bid: Decimal
    best_ask: Decimal
    midpoint: Decimal
    bias_as_of: str | None
    market_as_of: str | None
    score: ContractScore
    latest_price: Decimal | None = None
    observation_count: int | None = None
    recent_return_bps: Decimal | None = None
    lookback_return_bps: Decimal | None = None
    impulse_direction: str | None = None
    impulse_return_bps: Decimal | None = None
    impulse_detected: bool | None = None
    risk_flags: tuple[tuple[str, bool], ...] = ()
    target_price: Decimal | None = None
    target_price_source: str | None = None
    distance_to_target: Decimal | None = None
    distance_to_target_bps: Decimal | None = None
    required_bps_per_minute: Decimal | None = None
    side_currently_itm: bool | None = None
    side_needs_cross: bool | None = None
    feasibility_status: str | None = None
    reversal_confirmation_status: str | None = None
    trend_confirmation_status: str | None = None
    signal_conflict_flags: tuple[tuple[str, bool], ...] = ()
    scanner_score_confidence: int | None = None
    scanner_score_downgrade_reasons: tuple[str, ...] = ()
    scanner_score_bonus_reasons: tuple[str, ...] = ()
    contract_open_time: str | None = None
    contract_close_time: str | None = None
    contract_time_remaining_seconds: int | None = None
    end_window_allowed: bool | None = None
    end_window_reason: str | None = None
    classification_reason: str | None = None
    chop_threshold_bps: Decimal | None = None
    recent_window_seconds: int | None = None
    lookback_window_seconds: int | None = None
    recent_abs_bps: Decimal | None = None
    lookback_abs_bps: Decimal | None = None
    recent_threshold_gap_bps: Decimal | None = None
    lookback_threshold_gap_bps: Decimal | None = None
    recent_3m_return_bps: Decimal | None = None
    recent_5m_return_bps: Decimal | None = None
    recent_3m_range_bps: Decimal | None = None
    recent_5m_range_bps: Decimal | None = None
    distance_to_recent_high_bps: Decimal | None = None
    distance_to_recent_low_bps: Decimal | None = None
    range_expansion_status: str | None = None
    momentum_deceleration_status: str | None = None
    exhaustion_base_status: str | None = None
    exhaustion_base_reason: str | None = None
    exhaustion_status: str | None = None
    exhaustion_guard_decision: str | None = None
    exhaustion_progression_status: str | None = None
    exhaustion_progression_reason: str | None = None
    exhaustion_progression_sample_count: int | None = None
    exhaustion_progression_aligned_count: int | None = None
    exhaustion_progression_matched_conditions: tuple[str, ...] = ()
    exhaustion_progression_failed_conditions: tuple[str, ...] = ()
    exhaustion_progression_context_source: str | None = None
    exhaustion_progression_override_enabled: bool | None = None
    early_momentum_status: str | None = None
    late_entry_risk_status: str | None = None
    quiet_continuation_enabled: bool | None = None
    quiet_continuation_thresholds_active: bool | None = None
    quiet_continuation_allowed_reason: str | None = None
    quiet_continuation_block_reason: str | None = None
    mean_reversion_candidate_status: str | None = None
    reversal_pullback_vs_true_reversal_status: str | None = None
    reversal_safe_low_price_status: str | None = None
    weak_momentum_stabilization_status: str | None = None
    weak_momentum_stabilization_reason: str | None = None
    weak_momentum_stabilization_config_status: str | None = None
    mini_exhaustion_status: str | None = None
    mini_exhaustion_reason: str | None = None
    mini_exhaustion_enabled: bool | None = None
    mini_exhaustion_thresholds_active: bool | None = None
    decay_ratio: Decimal | None = None
    return_range_ratio: Decimal | None = None
    ratio_decay: Decimal | None = None
    near_extreme_distance_bps: Decimal | None = None
    adaptive_chop_threshold_bps: Decimal | None = None
    adaptive_near_extreme_bps: Decimal | None = None
    adaptive_ratio_floor: Decimal | None = None
    adaptive_required_bps_per_minute_limit: Decimal | None = None
    adaptive_pacing_multiplier: Decimal | None = None
    composite_score: Decimal | None = None
    continuation_score: Decimal | None = None
    reversal_score: Decimal | None = None
    hit_probability_estimate: Decimal | None = None
    quality_band: str | None = None
    score_components: tuple[tuple[str, Decimal], ...] = ()
    hard_gate_results: tuple[tuple[str, str], ...] = ()
    candidate_downgrade_reasons: tuple[str, ...] = ()
    candidate_upgrade_reasons: tuple[str, ...] = ()
    progression_memory_snapshot: tuple[tuple[str, object], ...] = ()
    trend_age_cycles: int | None = None
    trend_age_seconds: int | None = None
    failed_continuation_count: int | None = None
    deceleration_persistence_count: int | None = None
    range_expansion_persistence_count: int | None = None
    retry_degradation_factor: Decimal | None = None
    progression_continuation_quality: str | None = None
    reversal_probability: Decimal | None = None
    reversal_expected_value: Decimal | None = None
    reversal_candidate_status: str | None = None
    reversal_rejection_reason: str | None = None
    fake_continuation_signature: bool | None = None
    reversal_shadow_only: bool | None = None
    roadmap_mode_active: bool | None = None
    legacy_gate_applied: str | None = None
    legacy_gate_mapped_to_score: str | None = None
    legacy_gate_bypassed_due_to_roadmap_mode: str | None = None
    final_blocking_gate: str | None = None
    product_filtered_reason: str | None = None
    product_no_active_market_reason: str | None = None
    product_no_liquidity_reason: str | None = None


@dataclass(frozen=True)
class SkippedContract:
    """Normalized skipped contract record."""

    product_id: str
    market_ticker: str
    reason: str
    contract_close_time: str | None = None
    target_price: Decimal | None = None
    target_price_source: str | None = None
    distance_to_target_bps: Decimal | None = None
    time_remaining_seconds: int | None = None
    required_bps_per_minute: Decimal | None = None
    side_currently_itm: bool | None = None
    side_needs_cross: bool | None = None
    feasibility_status: str | None = None
    reversal_confirmation_status: str | None = None
    trend_confirmation_status: str | None = None
    signal_conflict_flags: tuple[tuple[str, bool], ...] = ()
    scanner_score_downgrade_reasons: tuple[str, ...] = ()
    scanner_score_bonus_reasons: tuple[str, ...] = ()
    contract_open_time: str | None = None
    contract_time_remaining_seconds: int | None = None
    end_window_allowed: bool | None = None
    end_window_reason: str | None = None
    direction: str | None = None
    structure: str | None = None
    confidence: int | None = None
    latest_price: Decimal | None = None
    observation_count: int | None = None
    recent_return_bps: Decimal | None = None
    lookback_return_bps: Decimal | None = None
    impulse_direction: str | None = None
    impulse_return_bps: Decimal | None = None
    impulse_detected: bool | None = None
    risk_flags: tuple[tuple[str, bool], ...] = ()
    classification_reason: str | None = None
    chop_threshold_bps: Decimal | None = None
    recent_window_seconds: int | None = None
    lookback_window_seconds: int | None = None
    recent_abs_bps: Decimal | None = None
    lookback_abs_bps: Decimal | None = None
    recent_threshold_gap_bps: Decimal | None = None
    lookback_threshold_gap_bps: Decimal | None = None
    recent_3m_return_bps: Decimal | None = None
    recent_5m_return_bps: Decimal | None = None
    recent_3m_range_bps: Decimal | None = None
    recent_5m_range_bps: Decimal | None = None
    distance_to_recent_high_bps: Decimal | None = None
    distance_to_recent_low_bps: Decimal | None = None
    range_expansion_status: str | None = None
    momentum_deceleration_status: str | None = None
    exhaustion_base_status: str | None = None
    exhaustion_base_reason: str | None = None
    exhaustion_status: str | None = None
    exhaustion_guard_decision: str | None = None
    exhaustion_progression_status: str | None = None
    exhaustion_progression_reason: str | None = None
    exhaustion_progression_sample_count: int | None = None
    exhaustion_progression_aligned_count: int | None = None
    exhaustion_progression_matched_conditions: tuple[str, ...] = ()
    exhaustion_progression_failed_conditions: tuple[str, ...] = ()
    exhaustion_progression_context_source: str | None = None
    exhaustion_progression_override_enabled: bool | None = None
    early_momentum_status: str | None = None
    late_entry_risk_status: str | None = None
    quiet_continuation_enabled: bool | None = None
    quiet_continuation_thresholds_active: bool | None = None
    quiet_continuation_allowed_reason: str | None = None
    quiet_continuation_block_reason: str | None = None
    mean_reversion_candidate_status: str | None = None
    reversal_pullback_vs_true_reversal_status: str | None = None
    reversal_safe_low_price_status: str | None = None
    weak_momentum_stabilization_status: str | None = None
    weak_momentum_stabilization_reason: str | None = None
    weak_momentum_stabilization_config_status: str | None = None
    mini_exhaustion_status: str | None = None
    mini_exhaustion_reason: str | None = None
    mini_exhaustion_enabled: bool | None = None
    mini_exhaustion_thresholds_active: bool | None = None
    decay_ratio: Decimal | None = None
    return_range_ratio: Decimal | None = None
    ratio_decay: Decimal | None = None
    near_extreme_distance_bps: Decimal | None = None
    adaptive_chop_threshold_bps: Decimal | None = None
    adaptive_near_extreme_bps: Decimal | None = None
    adaptive_ratio_floor: Decimal | None = None
    adaptive_required_bps_per_minute_limit: Decimal | None = None
    adaptive_pacing_multiplier: Decimal | None = None
    composite_score: Decimal | None = None
    continuation_score: Decimal | None = None
    reversal_score: Decimal | None = None
    hit_probability_estimate: Decimal | None = None
    quality_band: str | None = None
    score_components: tuple[tuple[str, Decimal], ...] = ()
    hard_gate_results: tuple[tuple[str, str], ...] = ()
    candidate_downgrade_reasons: tuple[str, ...] = ()
    candidate_upgrade_reasons: tuple[str, ...] = ()
    progression_memory_snapshot: tuple[tuple[str, object], ...] = ()
    trend_age_cycles: int | None = None
    trend_age_seconds: int | None = None
    failed_continuation_count: int | None = None
    deceleration_persistence_count: int | None = None
    range_expansion_persistence_count: int | None = None
    retry_degradation_factor: Decimal | None = None
    progression_continuation_quality: str | None = None
    reversal_probability: Decimal | None = None
    reversal_expected_value: Decimal | None = None
    reversal_candidate_status: str | None = None
    reversal_rejection_reason: str | None = None
    fake_continuation_signature: bool | None = None
    reversal_shadow_only: bool | None = None
    roadmap_mode_active: bool | None = None
    legacy_gate_applied: str | None = None
    legacy_gate_mapped_to_score: str | None = None
    legacy_gate_bypassed_due_to_roadmap_mode: str | None = None
    final_blocking_gate: str | None = None
    product_filtered_reason: str | None = None
    product_no_active_market_reason: str | None = None
    product_no_liquidity_reason: str | None = None


@dataclass(frozen=True)
class ContractScanSnapshot:
    """Ranked and skipped contract results for one scan pass."""

    ranked_contracts: tuple[ScannedContract, ...]
    skipped_contracts: tuple[SkippedContract, ...]


@dataclass(frozen=True)
class ExhaustionProgressionSample:
    """Minimal per-product context used to verify sustained continuation."""

    product_id: str
    direction: str | None
    structure: str | None
    classification_reason: str | None
    recent_return_bps: Decimal | None
    recent_3m_return_bps: Decimal | None
    lookback_return_bps: Decimal | None
    recent_5m_range_bps: Decimal | None
    distance_to_recent_high_bps: Decimal | None
    distance_to_recent_low_bps: Decimal | None
    cycle_number: int | None
    source: str | None


@dataclass(frozen=True)
class ExhaustionProgressionDecision:
    """Decision details for downgrading an exhaustion hard block to caution."""

    status: str
    reason: str | None
    sample_count: int
    aligned_count: int
    matched_conditions: tuple[str, ...]
    failed_conditions: tuple[str, ...]
    context_source: str | None


class ContractScanner:
    """Read-only scanner over mapped Kalshi markets already present in local state."""

    def __init__(
        self,
        *,
        product_markets: Mapping[str, tuple[str, ...]],
        market_metadata_by_ticker: Mapping[str, Mapping[str, object]] | None = None,
        quiet_continuation_enabled: bool = False,
        quiet_continuation_max_required_bps_per_minute: Decimal = Decimal("0.25"),
        quiet_continuation_max_recent_bps: Decimal = Decimal("6"),
        quiet_continuation_max_3m_abs_bps: Decimal = Decimal("12"),
        quiet_continuation_max_5m_abs_bps: Decimal = Decimal("20"),
        quiet_continuation_max_5m_range_bps: Decimal = Decimal("25"),
        quiet_continuation_block_deceleration: bool = True,
        quiet_continuation_block_near_extreme: bool = True,
        quiet_continuation_min_distance_from_extreme_bps: Decimal = Decimal("5"),
        exhaustion_guard_enabled: bool = True,
        exhaustion_burst_3m_bps: Decimal = Decimal("20"),
        exhaustion_burst_5m_bps: Decimal = Decimal("30"),
        exhaustion_near_extreme_bps: Decimal = Decimal("3"),
        exhaustion_deceleration_recent_bps: Decimal = Decimal("8"),
        exhaustion_strict_products: tuple[str, ...] = (
            "HYPE-USD",
            "ETH-USD",
            "XRP-USD",
        ),
        exhaustion_strict_burst_3m_bps: Decimal = Decimal("15"),
        exhaustion_progression_override_enabled: bool = False,
        exhaustion_progression_min_aligned_cycles: int = 2,
        early_momentum_enabled: bool = True,
        early_momentum_min_recent_bps: Decimal = Decimal("15"),
        early_momentum_max_3m_burst_bps: Decimal = Decimal("20"),
        weak_momentum_stabilization_min_distance: Decimal | None = None,
        weak_momentum_max_range: Decimal | None = None,
        weak_momentum_max_price: Decimal | None = None,
        mini_exhaustion_enabled: bool = False,
        mini_exhaustion_3m_bps: Decimal = Decimal("12"),
        mini_exhaustion_range_bps: Decimal = Decimal("25"),
        mini_exhaustion_recent_bps: Decimal = Decimal("6"),
        min_cross_distance_bps: Decimal = Decimal("0"),
        adaptive_thresholds_enabled: bool = False,
        composite_score_enabled: bool = False,
        composite_score_min: Decimal = Decimal("0.60"),
        composite_borderline_min: Decimal = Decimal("0.40"),
        return_range_ratio_enabled: bool = True,
        return_range_ratio_min_by_product: Mapping[str, Decimal] | None = None,
        progression_memory_enabled: bool = False,
        reversal_classifier_enabled: bool = False,
        reversal_shadow_only: bool = True,
        reversal_max_executable_price: Decimal = Decimal("0.60"),
        reversal_min_ev: Decimal = Decimal("0.00"),
        reversal_min_probability: Decimal = Decimal("0.55"),
        unified_near_extreme_enabled: bool = False,
        unified_near_extreme_base_bps_by_product: Mapping[str, Decimal] | None = None,
        adaptive_chop_enabled: bool = False,
        adaptive_pacing_enabled: bool = False,
        product_volatility_scale_by_product: Mapping[str, Decimal] | None = None,
        score_telemetry_enabled: bool = True,
    ) -> None:
        normalized = {
            product_id.strip(): tuple(
                dict.fromkeys(market_ticker.strip() for market_ticker in market_tickers if market_ticker.strip())
            )
            for product_id, market_tickers in product_markets.items()
            if product_id.strip()
        }
        if not normalized:
            raise ContractScannerError("Contract scanner product mapping is required.")
        if any(not market_tickers for market_tickers in normalized.values()):
            raise ContractScannerError("Each contract scanner product must map to at least one market.")
        self._product_markets = normalized
        self._market_metadata_by_ticker = {
            market_ticker: dict(metadata)
            for market_ticker, metadata in (market_metadata_by_ticker or {}).items()
        }
        self._quiet_continuation_enabled = quiet_continuation_enabled
        self._quiet_continuation_max_required_bps_per_minute = Decimal(
            str(quiet_continuation_max_required_bps_per_minute)
        )
        self._quiet_continuation_max_recent_bps = Decimal(
            str(quiet_continuation_max_recent_bps)
        )
        self._quiet_continuation_max_3m_abs_bps = Decimal(
            str(quiet_continuation_max_3m_abs_bps)
        )
        self._quiet_continuation_max_5m_abs_bps = Decimal(
            str(quiet_continuation_max_5m_abs_bps)
        )
        self._quiet_continuation_max_5m_range_bps = Decimal(
            str(quiet_continuation_max_5m_range_bps)
        )
        self._quiet_continuation_block_deceleration = quiet_continuation_block_deceleration
        self._quiet_continuation_block_near_extreme = quiet_continuation_block_near_extreme
        self._quiet_continuation_min_distance_from_extreme_bps = Decimal(
            str(quiet_continuation_min_distance_from_extreme_bps)
        )
        self._exhaustion_guard_enabled = exhaustion_guard_enabled
        self._exhaustion_burst_3m_bps = Decimal(str(exhaustion_burst_3m_bps))
        self._exhaustion_burst_5m_bps = Decimal(str(exhaustion_burst_5m_bps))
        self._exhaustion_near_extreme_bps = Decimal(str(exhaustion_near_extreme_bps))
        self._exhaustion_deceleration_recent_bps = Decimal(
            str(exhaustion_deceleration_recent_bps)
        )
        self._exhaustion_strict_products = tuple(
            dict.fromkeys(product.upper() for product in exhaustion_strict_products)
        )
        self._exhaustion_strict_burst_3m_bps = Decimal(
            str(exhaustion_strict_burst_3m_bps)
        )
        self._exhaustion_progression_override_enabled = (
            exhaustion_progression_override_enabled
        )
        self._exhaustion_progression_min_aligned_cycles = max(
            1,
            int(exhaustion_progression_min_aligned_cycles),
        )
        self._early_momentum_enabled = early_momentum_enabled
        self._early_momentum_min_recent_bps = Decimal(str(early_momentum_min_recent_bps))
        self._early_momentum_max_3m_burst_bps = Decimal(
            str(early_momentum_max_3m_burst_bps)
        )
        self._weak_momentum_stabilization_min_distance = (
            Decimal(str(weak_momentum_stabilization_min_distance))
            if weak_momentum_stabilization_min_distance is not None
            else None
        )
        self._weak_momentum_max_range = (
            Decimal(str(weak_momentum_max_range))
            if weak_momentum_max_range is not None
            else None
        )
        self._weak_momentum_max_price = (
            Decimal(str(weak_momentum_max_price))
            if weak_momentum_max_price is not None
            else None
        )
        self._mini_exhaustion_enabled = mini_exhaustion_enabled
        self._mini_exhaustion_3m_bps = Decimal(str(mini_exhaustion_3m_bps))
        self._mini_exhaustion_range_bps = Decimal(str(mini_exhaustion_range_bps))
        self._mini_exhaustion_recent_bps = Decimal(str(mini_exhaustion_recent_bps))
        self._min_cross_distance_bps = Decimal(str(min_cross_distance_bps))
        self._adaptive_thresholds_enabled = adaptive_thresholds_enabled
        self._composite_score_enabled = composite_score_enabled
        self._composite_score_min = Decimal(str(composite_score_min))
        self._composite_borderline_min = Decimal(str(composite_borderline_min))
        self._return_range_ratio_enabled = return_range_ratio_enabled
        self._progression_memory_enabled = progression_memory_enabled
        self._return_range_ratio_min_by_product = {
            key.upper(): Decimal(str(value))
            for key, value in (return_range_ratio_min_by_product or {}).items()
        }
        self._reversal_classifier_enabled = reversal_classifier_enabled
        self._reversal_shadow_only = reversal_shadow_only
        self._reversal_max_executable_price = Decimal(str(reversal_max_executable_price))
        self._reversal_min_ev = Decimal(str(reversal_min_ev))
        self._reversal_min_probability = Decimal(str(reversal_min_probability))
        self._unified_near_extreme_enabled = unified_near_extreme_enabled
        self._unified_near_extreme_base_bps_by_product = {
            key.upper(): Decimal(str(value))
            for key, value in (unified_near_extreme_base_bps_by_product or {}).items()
        }
        self._adaptive_chop_enabled = adaptive_chop_enabled
        self._adaptive_pacing_enabled = adaptive_pacing_enabled
        self._product_volatility_scale_by_product = {
            key.upper(): Decimal(str(value))
            for key, value in (product_volatility_scale_by_product or {}).items()
        }
        self._score_telemetry_enabled = score_telemetry_enabled
        self._roadmap_mode_active = any(
            (
                self._composite_score_enabled,
                self._adaptive_thresholds_enabled,
                self._unified_near_extreme_enabled,
                self._adaptive_chop_enabled,
                self._progression_memory_enabled,
                self._reversal_classifier_enabled,
                self._adaptive_pacing_enabled,
            )
        )

    @classmethod
    def from_settings(cls, settings: KalshiSettings) -> "ContractScanner":
        if not settings.contract_scanner_product_markets:
            raise ContractScannerError("CONTRACT_SCANNER_PRODUCT_MARKETS_JSON is required.")
        return cls(
            product_markets=settings.contract_scanner_product_markets,
            **scanner_live_settings_kwargs(settings),
        )

    def scan(
        self,
        *,
        bias_snapshot: BiasSnapshot,
        market_snapshot: MarketStateSnapshot,
        progression_context_by_product: (
            Mapping[str, tuple[ExhaustionProgressionSample, ...]] | None
        ) = None,
        progression_memory_by_product: Mapping[str, ProgressionMemoryState] | None = None,
    ) -> ContractScanSnapshot:
        ranked_contracts: list[ScannedContract] = []
        skipped_contracts: list[SkippedContract] = []
        progression_context_by_product = progression_context_by_product or {}
        progression_memory_by_product = progression_memory_by_product or {}

        for product_id, market_tickers in self._product_markets.items():
            bias_state = bias_snapshot.products.get(product_id)
            for market_ticker in market_tickers:
                ticker_state = market_snapshot.tickers.get(market_ticker)
                if ticker_state is None:
                    skipped_contracts.append(
                        SkippedContract(
                            product_id=product_id,
                            market_ticker=market_ticker,
                            reason="missing_ticker_state",
                            product_no_liquidity_reason="ticker_state_missing",
                            final_blocking_gate="missing_ticker_state",
                        )
                    )
                    continue
                metadata = self._market_metadata_by_ticker.get(market_ticker, {})
                stale_skip_reason = _stale_ticker_skip_reason(metadata)
                if stale_skip_reason is not None:
                    skipped_contracts.append(
                        SkippedContract(
                            product_id=product_id,
                            market_ticker=market_ticker,
                            reason=stale_skip_reason,
                            contract_open_time=_optional_str_metadata(metadata, "open_time"),
                            contract_close_time=_optional_str_metadata(metadata, "close_time"),
                            time_remaining_seconds=_market_time_remaining_seconds(
                                metadata
                            ),
                            feasibility_status="time_remaining_elapsed",
                            end_window_allowed=False,
                            end_window_reason=stale_skip_reason,
                        )
                    )
                    continue
                effective_bias_state = bias_state
                skip_reason = _skip_reason(bias_state, ticker_state)
                if skip_reason is not None:
                    quiet_bias_state = _quiet_continuation_bias_state(
                        bias_state,
                        enabled=self._quiet_continuation_enabled,
                    )
                    if (
                        skip_reason == "neutral_bias"
                        and quiet_bias_state is not None
                        and ticker_state.yes_bid_dollars is not None
                        and ticker_state.yes_ask_dollars is not None
                    ):
                        quiet_feasibility = _target_feasibility(
                            direction=quiet_bias_state.direction,
                            current_spot_price=quiet_bias_state.latest_price,
                            target_price=_optional_decimal_metadata(metadata, "target_price"),
                            target_price_source=_optional_str_metadata(metadata, "target_price_source"),
                            close_time=_optional_str_metadata(metadata, "close_time"),
                            min_cross_distance_bps=self._product_min_cross_distance_bps(
                                product_id
                            ),
                        )
                        quiet_midpoint = _quote_midpoint(ticker_state)
                        quiet_skip_reason = _quiet_continuation_skip_reason(
                            quiet_feasibility,
                            max_required_bps_per_minute=(
                                self._quiet_continuation_max_required_bps_per_minute
                            ),
                        )
                        quiet_signal_block_reason = None
                        if quiet_skip_reason is None:
                            quiet_signal_block_reason = self._quiet_continuation_signal_block_reason(
                                product_id=product_id,
                                bias_state=quiet_bias_state,
                            )
                            quiet_skip_reason = quiet_signal_block_reason
                            if (
                                self._roadmap_mode_active
                                and quiet_signal_block_reason
                                in _ROADMAP_MAPPED_QUIET_SIGNAL_BLOCKS
                            ):
                                quiet_skip_reason = None
                        if quiet_skip_reason is None:
                            quiet_weak_status = self._weak_momentum_stabilization_status(
                                product_id=product_id,
                                bias_state=quiet_bias_state,
                                feasibility=quiet_feasibility,
                                entry_price=quiet_midpoint,
                            )
                            if (
                                quiet_weak_status[0] != "disabled"
                                and quiet_weak_status[0] != "allowed"
                            ):
                                quiet_skip_reason = (
                                    f"weak_momentum_stabilization_{quiet_weak_status[1]}"
                                )
                        if quiet_skip_reason is None:
                            effective_bias_state = quiet_bias_state
                            skip_reason = None
                        else:
                            skipped_contracts.append(
                                SkippedContract(
                                    product_id=product_id,
                                    market_ticker=market_ticker,
                                    reason=quiet_skip_reason,
                                    contract_open_time=_optional_str_metadata(metadata, "open_time"),
                                    contract_close_time=_optional_str_metadata(metadata, "close_time"),
                                    target_price=quiet_feasibility.target_price,
                                    target_price_source=quiet_feasibility.target_price_source,
                                    distance_to_target_bps=quiet_feasibility.distance_to_target_bps,
                                    time_remaining_seconds=quiet_feasibility.time_remaining_seconds,
                                    required_bps_per_minute=quiet_feasibility.required_bps_per_minute,
                                    side_currently_itm=quiet_feasibility.side_currently_itm,
                                    side_needs_cross=quiet_feasibility.side_needs_cross,
                                    feasibility_status=quiet_feasibility.feasibility_status,
                                    **self._signal_quality_fields(
                                        product_id=product_id,
                                        bias_state=quiet_bias_state,
                                        feasibility=quiet_feasibility,
                                        entry_price=quiet_midpoint,
                                        quiet_continuation_block_reason=quiet_skip_reason,
                                        progression_context=(
                                            progression_context_by_product.get(
                                                product_id,
                                                (),
                                            )
                                        ),
                                    ),
                                    **_bias_diagnostic_fields(quiet_bias_state),
                                )
                            )
                            continue
                    if skip_reason is None:
                        pass
                    else:
                        skipped_contracts.append(
                            SkippedContract(
                                product_id=product_id,
                                market_ticker=market_ticker,
                                reason=skip_reason,
                                contract_open_time=_optional_str_metadata(metadata, "open_time"),
                                contract_close_time=_optional_str_metadata(metadata, "close_time"),
                                **self._signal_quality_fields(
                                    product_id=product_id,
                                    bias_state=bias_state,
                                    progression_context=(
                                        progression_context_by_product.get(
                                            product_id,
                                            (),
                                        )
                                    ),
                                ),
                                **_bias_diagnostic_fields(bias_state),
                            )
                        )
                        continue

                if effective_bias_state is None:
                    skipped_contracts.append(
                        SkippedContract(
                            product_id=product_id,
                            market_ticker=market_ticker,
                            reason="missing_bias_state",
                            contract_open_time=_optional_str_metadata(metadata, "open_time"),
                            contract_close_time=_optional_str_metadata(metadata, "close_time"),
                        )
                    )
                    continue

                assert effective_bias_state is not None
                assert ticker_state.yes_bid_dollars is not None
                assert ticker_state.yes_ask_dollars is not None
                feasibility = _target_feasibility(
                    direction=effective_bias_state.direction,
                    current_spot_price=effective_bias_state.latest_price,
                    target_price=_optional_decimal_metadata(metadata, "target_price"),
                    target_price_source=_optional_str_metadata(metadata, "target_price_source"),
                    close_time=_optional_str_metadata(metadata, "close_time"),
                    min_cross_distance_bps=self._product_min_cross_distance_bps(
                        product_id
                    ),
                )
                midpoint = _quote_midpoint(ticker_state)
                signal_conflict_flags = _signal_conflict_flags(
                    direction=effective_bias_state.direction,
                    impulse_return_bps=getattr(effective_bias_state, "impulse_return_bps", None),
                )
                reversal_confirmation_status = _reversal_confirmation_status(
                    bias_state=effective_bias_state,
                    signal_conflict_flags=signal_conflict_flags,
                )
                trend_confirmation_status = _trend_confirmation_status(
                    bias_state=effective_bias_state,
                    feasibility=feasibility,
                )
                feasibility_skip_reason = _feasibility_skip_reason(
                    bias_state=effective_bias_state,
                    feasibility=feasibility,
                    signal_conflict_flags=signal_conflict_flags,
                )
                signal_quality_fields = self._signal_quality_fields(
                    product_id=product_id,
                    bias_state=effective_bias_state,
                    feasibility=feasibility,
                    entry_price=midpoint,
                    progression_context=progression_context_by_product.get(
                        product_id,
                        (),
                    ),
                )
                roadmap_quality_fields = self._roadmap_quality_fields(
                    product_id=product_id,
                    bias_state=effective_bias_state,
                    feasibility=feasibility,
                    entry_price=midpoint,
                    trend_confirmation_status=trend_confirmation_status,
                    signal_quality_fields=signal_quality_fields,
                    progression_memory=_progression_memory_for_candidate(
                        progression_memory_by_product,
                        product_id=product_id,
                        direction=effective_bias_state.direction,
                    ),
                )
                signal_quality_fields = {
                    **signal_quality_fields,
                    **roadmap_quality_fields,
                }
                if feasibility_skip_reason is not None:
                    skipped_contracts.append(
                        SkippedContract(
                            product_id=product_id,
                            market_ticker=market_ticker,
                            reason=feasibility_skip_reason,
                            contract_open_time=_optional_str_metadata(metadata, "open_time"),
                            contract_close_time=_optional_str_metadata(metadata, "close_time"),
                            target_price=feasibility.target_price,
                            target_price_source=feasibility.target_price_source,
                            distance_to_target_bps=feasibility.distance_to_target_bps,
                            time_remaining_seconds=feasibility.time_remaining_seconds,
                            required_bps_per_minute=feasibility.required_bps_per_minute,
                            side_currently_itm=feasibility.side_currently_itm,
                            side_needs_cross=feasibility.side_needs_cross,
                            feasibility_status=feasibility.feasibility_status,
                            reversal_confirmation_status=reversal_confirmation_status,
                            trend_confirmation_status=trend_confirmation_status,
                            signal_conflict_flags=signal_conflict_flags,
                            scanner_score_downgrade_reasons=(),
                            **signal_quality_fields,
                            **_bias_diagnostic_fields(effective_bias_state),
                        )
                    )
                    continue
                exhaustion_skip_reason = self._exhaustion_skip_reason(
                    bias_state=effective_bias_state,
                    feasibility=feasibility,
                    signal_quality_fields=signal_quality_fields,
                )
                if exhaustion_skip_reason is not None:
                    skipped_contracts.append(
                        SkippedContract(
                            product_id=product_id,
                            market_ticker=market_ticker,
                            reason=exhaustion_skip_reason,
                            contract_open_time=_optional_str_metadata(metadata, "open_time"),
                            contract_close_time=_optional_str_metadata(metadata, "close_time"),
                            target_price=feasibility.target_price,
                            target_price_source=feasibility.target_price_source,
                            distance_to_target_bps=feasibility.distance_to_target_bps,
                            time_remaining_seconds=feasibility.time_remaining_seconds,
                            required_bps_per_minute=feasibility.required_bps_per_minute,
                            side_currently_itm=feasibility.side_currently_itm,
                            side_needs_cross=feasibility.side_needs_cross,
                            feasibility_status=feasibility.feasibility_status,
                            reversal_confirmation_status=reversal_confirmation_status,
                            trend_confirmation_status=trend_confirmation_status,
                            signal_conflict_flags=signal_conflict_flags,
                            scanner_score_downgrade_reasons=("exhaustion_guard_blocked",),
                            **signal_quality_fields,
                            **_bias_diagnostic_fields(effective_bias_state),
                        )
                    )
                    continue
                (
                    score_confidence,
                    score_downgrade_reasons,
                    score_bonus_reasons,
                ) = _scanner_score_confidence(
                    product_id=product_id,
                    bias_state=effective_bias_state,
                    feasibility=feasibility,
                    reversal_confirmation_status=reversal_confirmation_status,
                    trend_confirmation_status=trend_confirmation_status,
                    signal_conflict_flags=signal_conflict_flags,
                    weak_momentum_stabilization_status=signal_quality_fields.get(
                        "weak_momentum_stabilization_status"
                    ),
                    mini_exhaustion_status=signal_quality_fields.get(
                        "mini_exhaustion_status"
                    ),
                    exhaustion_status=signal_quality_fields.get(
                        "exhaustion_status"
                    ),
                )
                score = score_contract(
                    confidence=score_confidence,
                    best_bid=ticker_state.yes_bid_dollars,
                    best_ask=ticker_state.yes_ask_dollars,
                    yes_bid_size_fp=ticker_state.yes_bid_size_fp,
                    yes_ask_size_fp=ticker_state.yes_ask_size_fp,
                    dollar_volume=ticker_state.dollar_volume,
                    composite_score=signal_quality_fields.get("composite_score"),
                )
                continuation_contract = ScannedContract(
                    product_id=product_id,
                    market_ticker=market_ticker,
                    direction=effective_bias_state.direction,
                    structure=effective_bias_state.structure,
                    confidence=effective_bias_state.confidence,
                    best_bid=ticker_state.yes_bid_dollars,
                    best_ask=ticker_state.yes_ask_dollars,
                    midpoint=midpoint,
                    bias_as_of=effective_bias_state.as_of,
                    market_as_of=_market_as_of(ticker_state),
                    score=score,
                    latest_price=effective_bias_state.latest_price,
                    observation_count=effective_bias_state.observation_count,
                    recent_return_bps=effective_bias_state.recent_return_bps,
                    lookback_return_bps=effective_bias_state.lookback_return_bps,
                    impulse_direction=effective_bias_state.impulse_direction,
                    impulse_return_bps=effective_bias_state.impulse_return_bps,
                    impulse_detected=effective_bias_state.impulse_detected,
                    risk_flags=_risk_flags(effective_bias_state.risk_flags),
                    target_price=feasibility.target_price,
                    target_price_source=feasibility.target_price_source,
                    distance_to_target=feasibility.distance_to_target,
                    distance_to_target_bps=feasibility.distance_to_target_bps,
                    required_bps_per_minute=feasibility.required_bps_per_minute,
                    side_currently_itm=feasibility.side_currently_itm,
                    side_needs_cross=feasibility.side_needs_cross,
                    feasibility_status=feasibility.feasibility_status,
                    reversal_confirmation_status=reversal_confirmation_status,
                    trend_confirmation_status=trend_confirmation_status,
                    signal_conflict_flags=signal_conflict_flags,
                    scanner_score_confidence=score_confidence,
                    scanner_score_downgrade_reasons=score_downgrade_reasons,
                    scanner_score_bonus_reasons=score_bonus_reasons,
                    contract_open_time=_optional_str_metadata(metadata, "open_time"),
                    contract_close_time=_optional_str_metadata(metadata, "close_time"),
                    contract_time_remaining_seconds=feasibility.time_remaining_seconds,
                    **signal_quality_fields,
                    **_bias_threshold_diagnostic_fields(effective_bias_state),
                )
                ranked_contracts.append(continuation_contract)
                reversal_contract = self._reversal_candidate_from_contract(
                    continuation_contract,
                    ticker_state=ticker_state,
                    metadata=metadata,
                    progression_memory=progression_memory_by_product.get(
                        product_id.upper()
                    )
                    or progression_memory_by_product.get(product_id),
                )
                if reversal_contract is not None:
                    ranked_contracts.append(reversal_contract)

        ranked_contracts.sort(key=lambda contract: contract.score.ranking_key() + (contract.market_ticker,))
        skipped_contracts.sort(key=lambda contract: (contract.product_id, contract.market_ticker, contract.reason))
        return ContractScanSnapshot(
            ranked_contracts=tuple(ranked_contracts),
            skipped_contracts=tuple(skipped_contracts),
        )

    def _signal_quality_fields(
        self,
        *,
        product_id: str,
        bias_state,  # noqa: ANN001
        feasibility: TargetFeasibility | None = None,
        entry_price: Decimal | None = None,
        quiet_continuation_block_reason: str | None = None,
        progression_context: tuple[ExhaustionProgressionSample, ...] = (),
    ) -> dict[str, object]:
        if bias_state is None:
            return {}
        direction = getattr(bias_state, "direction", None)
        range_status = _range_expansion_status(
            getattr(bias_state, "recent_5m_range_bps", None),
            threshold_bps=self._exhaustion_burst_5m_bps,
        )
        deceleration_status = _momentum_deceleration_status(
            bias_state=bias_state,
            direction=direction,
            burst_3m_bps=self._product_exhaustion_burst_3m(product_id),
            deceleration_recent_bps=self._exhaustion_deceleration_recent_bps,
        )
        near_extreme = _near_recent_extreme(
            bias_state=bias_state,
            direction=direction,
            threshold_bps=self._exhaustion_near_extreme_bps,
        )
        exhaustion_base_status = _exhaustion_status(
            guard_enabled=self._exhaustion_guard_enabled,
            range_expansion_status=range_status,
            momentum_deceleration_status=deceleration_status,
            near_extreme=near_extreme,
        )
        exhaustion_base_reason = _exhaustion_base_reason(
            range_expansion_status=range_status,
            momentum_deceleration_status=deceleration_status,
            near_extreme=near_extreme,
        )
        quiet_allowed_reason = None
        if str(getattr(bias_state, "classification_reason", "")).startswith(
            "quiet_continuation_"
        ) and quiet_continuation_block_reason is None:
            quiet_allowed_reason = "stable_itm_no_cross"
        weak_status, weak_reason = self._weak_momentum_stabilization_status(
            product_id=product_id,
            bias_state=bias_state,
            feasibility=feasibility,
            entry_price=entry_price,
        )
        mini_status, mini_reason = self._mini_exhaustion_status(
            product_id=product_id,
            bias_state=bias_state,
            feasibility=feasibility,
        )
        progression_decision = _exhaustion_progression_decision(
            enabled=self._exhaustion_progression_override_enabled,
            min_aligned_cycles=self._exhaustion_progression_min_aligned_cycles,
            product_id=product_id,
            bias_state=bias_state,
            feasibility=feasibility,
            base_status=exhaustion_base_status,
            base_reason=exhaustion_base_reason,
            near_extreme=near_extreme,
            mini_exhaustion_status=mini_status,
            progression_context=progression_context,
        )
        exhaustion_status = (
            "progression_caution"
            if progression_decision.status == "allowed"
            else exhaustion_base_status
        )
        early_status = _early_momentum_status(
            enabled=self._early_momentum_enabled,
            bias_state=bias_state,
            direction=direction,
            min_recent_bps=self._early_momentum_min_recent_bps,
            max_3m_burst_bps=self._early_momentum_max_3m_burst_bps,
            exhaustion_status=exhaustion_status,
        )
        late_entry_status = (
            "exhaustion_risk"
            if exhaustion_status == "blocked"
            else "exhaustion_progression_caution"
            if exhaustion_status == "progression_caution"
            else "near_recent_extreme"
            if near_extreme
            else "clear"
        )
        exhaustion_guard_decision = (
            "disabled"
            if exhaustion_base_status == "disabled"
            else "overridden_to_caution"
            if exhaustion_status == "progression_caution"
            else "hard_blocked"
            if exhaustion_status == "blocked"
            else "clear"
        )
        return {
            "range_expansion_status": range_status,
            "momentum_deceleration_status": deceleration_status,
            "exhaustion_base_status": exhaustion_base_status,
            "exhaustion_base_reason": exhaustion_base_reason,
            "exhaustion_status": exhaustion_status,
            "exhaustion_guard_decision": exhaustion_guard_decision,
            "exhaustion_progression_status": progression_decision.status,
            "exhaustion_progression_reason": progression_decision.reason,
            "exhaustion_progression_sample_count": (
                progression_decision.sample_count
            ),
            "exhaustion_progression_aligned_count": (
                progression_decision.aligned_count
            ),
            "exhaustion_progression_matched_conditions": (
                progression_decision.matched_conditions
            ),
            "exhaustion_progression_failed_conditions": (
                progression_decision.failed_conditions
            ),
            "exhaustion_progression_context_source": (
                progression_decision.context_source
            ),
            "exhaustion_progression_override_enabled": (
                self._exhaustion_progression_override_enabled
            ),
            "early_momentum_status": early_status,
            "late_entry_risk_status": late_entry_status,
            "quiet_continuation_enabled": self._quiet_continuation_enabled,
            "quiet_continuation_thresholds_active": (
                self._quiet_continuation_enabled
            ),
            "quiet_continuation_allowed_reason": quiet_allowed_reason,
            "quiet_continuation_block_reason": quiet_continuation_block_reason,
            "mean_reversion_candidate_status": _mean_reversion_candidate_status(
                bias_state
            ),
            "reversal_pullback_vs_true_reversal_status": (
                _reversal_pullback_vs_true_reversal_status(bias_state)
            ),
            "reversal_safe_low_price_status": "not_evaluated",
            "weak_momentum_stabilization_status": weak_status,
            "weak_momentum_stabilization_reason": weak_reason,
            "weak_momentum_stabilization_config_status": (
                "active"
                if self._product_weak_momentum_thresholds(product_id).count(None)
                == 0
                else "disabled"
            ),
            "mini_exhaustion_status": mini_status,
            "mini_exhaustion_reason": mini_reason,
            "mini_exhaustion_enabled": self._mini_exhaustion_enabled,
            "mini_exhaustion_thresholds_active": self._mini_exhaustion_enabled,
            "decay_ratio": _decay_ratio(bias_state, direction=direction),
        }

    def _roadmap_quality_fields(
        self,
        *,
        product_id: str,
        bias_state,  # noqa: ANN001
        feasibility: TargetFeasibility | None,
        entry_price: Decimal | None,
        trend_confirmation_status: str | None,
        signal_quality_fields: Mapping[str, object],
        progression_memory: ProgressionMemoryState | None,
        is_reversal_candidate: bool = False,
        reversal_probability_override: Decimal | None = None,
        reversal_expected_value_override: Decimal | None = None,
        reversal_candidate_status: str | None = None,
        reversal_rejection_reason: str | None = None,
    ) -> dict[str, object]:
        recent_range = _decimal_or_none(getattr(bias_state, "recent_5m_range_bps", None))
        thresholds = adaptive_thresholds_for_product(
            product_id=product_id,
            recent_5m_range_bps=recent_range,
            base_near_extreme_bps_by_product=(
                self._unified_near_extreme_base_bps_by_product
            ),
            ratio_floor_by_product=self._return_range_ratio_min_by_product,
            volatility_scale_by_product=self._product_volatility_scale_by_product,
            continuation_score_min=self._composite_score_min,
            max_required_bps_per_minute=self._quiet_continuation_max_required_bps_per_minute,
            adaptive_enabled=self._adaptive_thresholds_enabled,
            adaptive_chop_enabled=self._adaptive_chop_enabled,
            adaptive_pacing_enabled=self._adaptive_pacing_enabled,
        )
        ratio = (
            _return_range_ratio(
                getattr(bias_state, "lookback_return_bps", None),
                getattr(bias_state, "recent_5m_range_bps", None),
            )
            if self._return_range_ratio_enabled
            else None
        )
        direction = getattr(bias_state, "direction", None)
        near_extreme_distance = _near_extreme_distance_bps(
            bias_state=bias_state,
            direction=direction,
        )
        ratio_decay = (
            progression_memory.ratio_decay
            if progression_memory is not None and not progression_memory.memory_cold_start
            else _decay_ratio(bias_state, direction=direction)
        )
        deceleration_count = (
            progression_memory.deceleration_persistence_count
            if progression_memory is not None
            else (
                1
                if signal_quality_fields.get("momentum_deceleration_status")
                in {"decelerating_after_burst", "bursting", "still_moving"}
                else 0
            )
        )
        failed_attempts = (
            progression_memory.failed_continuation_count
            if progression_memory is not None
            else 0
        )
        trend_age = progression_memory.trend_age_cycles if progression_memory else 0
        trend_age_seconds = (
            progression_memory.trend_age_seconds if progression_memory else 0
        )
        range_expansion_count = (
            progression_memory.range_expansion_persistence_count
            if progression_memory is not None
            else (
                1
                if signal_quality_fields.get("range_expansion_status")
                in {"expanding", "bursting"}
                else 0
            )
        )
        reversal_classification = classify_reversal_probability(
            return_range_ratio=ratio,
            ratio_floor=thresholds.adaptive_ratio_floor,
            near_extreme_distance_bps=near_extreme_distance,
            near_extreme_threshold_bps=thresholds.adaptive_near_extreme_bps,
            deceleration_status=str(
                signal_quality_fields.get("momentum_deceleration_status") or ""
            ),
            range_expansion_status=str(
                signal_quality_fields.get("range_expansion_status") or ""
            ),
            trend_confirmation_status=trend_confirmation_status,
            required_bps_per_minute=(
                feasibility.required_bps_per_minute if feasibility else None
            ),
            memory_state=progression_memory,
        )
        reversal_probability = (
            reversal_probability_override
            if reversal_probability_override is not None
            else reversal_classification.reversal_probability
        )
        quality_score = score_candidate_quality(
            return_range_ratio=ratio,
            ratio_floor=thresholds.adaptive_ratio_floor,
            ratio_decay=ratio_decay,
            near_extreme_distance_bps=near_extreme_distance,
            near_extreme_threshold_bps=thresholds.adaptive_near_extreme_bps,
            recent_5m_range_bps=recent_range,
            recent_5m_return_bps=_decimal_or_none(
                getattr(bias_state, "recent_5m_return_bps", None)
            ),
            lookback_return_bps=_decimal_or_none(
                getattr(bias_state, "lookback_return_bps", None)
            ),
            trend_confirmation_status=trend_confirmation_status,
            deceleration_persistence_count=deceleration_count,
            range_expansion_status=str(
                signal_quality_fields.get("range_expansion_status") or ""
            ),
            ev=reversal_expected_value_override,
            price=entry_price,
            side_needs_cross=feasibility.side_needs_cross if feasibility else None,
            required_bps_per_minute=(
                feasibility.required_bps_per_minute if feasibility else None
            ),
            required_bps_per_minute_limit=(
                thresholds.adaptive_required_bps_per_minute_limit
            ),
            product_volatility_scale=thresholds.product_volatility_scale,
            trend_age_cycles=trend_age,
            failed_attempts=failed_attempts,
            progression_memory=progression_memory,
            reversal_probability=reversal_probability,
            is_reversal_candidate=is_reversal_candidate,
        )
        payload = {
            "adaptive_chop_threshold_bps": thresholds.adaptive_chop_threshold_bps,
            "adaptive_near_extreme_bps": thresholds.adaptive_near_extreme_bps,
            "adaptive_ratio_floor": thresholds.adaptive_ratio_floor,
            "adaptive_required_bps_per_minute_limit": (
                thresholds.adaptive_required_bps_per_minute_limit
            ),
            "adaptive_pacing_multiplier": thresholds.adaptive_pacing_multiplier,
            "composite_score": quality_score.composite_score,
            "continuation_score": quality_score.continuation_score,
            "reversal_score": quality_score.reversal_score,
            "hit_probability_estimate": quality_score.hit_probability_estimate,
            "quality_band": quality_score.quality_band,
            "return_range_ratio": ratio,
            "ratio_decay": ratio_decay,
            "near_extreme_distance_bps": near_extreme_distance,
            "trend_age_cycles": trend_age,
            "failed_continuation_count": failed_attempts,
            "retry_degradation_factor": (
                progression_memory.retry_degradation_factor
                if progression_memory is not None
                else Decimal("1")
            ),
            "progression_continuation_quality": (
                progression_memory.progression_continuation_quality
                if progression_memory is not None
                else "cold_start"
            ),
            "reversal_probability": reversal_probability,
            "reversal_expected_value": reversal_expected_value_override,
            "reversal_candidate_status": reversal_candidate_status,
            "reversal_rejection_reason": (
                reversal_rejection_reason
                or reversal_classification.rejection_reason
            ),
            "fake_continuation_signature": (
                reversal_classification.fake_continuation_signature
            ),
            "reversal_shadow_only": self._reversal_shadow_only,
            "score_components": tuple(quality_score.component_scores.items()),
            "hard_gate_results": tuple(quality_score.hard_gate_statuses.items()),
            "candidate_downgrade_reasons": quality_score.downgrade_reasons,
            "candidate_upgrade_reasons": quality_score.bonus_reasons,
            "progression_memory_snapshot": (
                tuple(progression_memory.as_payload().items())
                if progression_memory is not None
                else ()
            ),
            "trend_age_seconds": trend_age_seconds,
            "deceleration_persistence_count": deceleration_count,
            "range_expansion_persistence_count": range_expansion_count,
            "roadmap_mode_active": self._roadmap_mode_active,
            "legacy_gate_applied": (
                "exhaustion_guard"
                if signal_quality_fields.get("exhaustion_status") == "blocked"
                else None
            ),
            "legacy_gate_mapped_to_score": (
                "exhaustion_or_momentum_component"
                if self._roadmap_mode_active
                else None
            ),
            "legacy_gate_bypassed_due_to_roadmap_mode": (
                "exhaustion_guard_blocked"
                if self._roadmap_mode_active
                and signal_quality_fields.get("exhaustion_status") == "blocked"
                else None
            ),
            "final_blocking_gate": None,
        }
        return payload

    def _reversal_candidate_from_contract(
        self,
        contract: ScannedContract,
        *,
        ticker_state: TickerState,
        metadata: Mapping[str, object],
        progression_memory: ProgressionMemoryState | None,
    ) -> ScannedContract | None:
        if not self._reversal_classifier_enabled:
            return None
        if contract.direction not in {"up", "down"}:
            return None
        opposite_direction = "down" if contract.direction == "up" else "up"
        opposite_price = _opposite_executable_price(
            direction=opposite_direction,
            ticker_state=ticker_state,
        )
        bias_like = _OppositeBiasState(contract, opposite_direction)
        feasibility = _target_feasibility(
            direction=opposite_direction,
            current_spot_price=contract.latest_price,
            target_price=_optional_decimal_metadata(metadata, "target_price"),
            target_price_source=_optional_str_metadata(metadata, "target_price_source"),
            close_time=_optional_str_metadata(metadata, "close_time"),
            min_cross_distance_bps=self._product_min_cross_distance_bps(
                contract.product_id
            ),
        )
        reversal_ev = reversal_expected_value(
            reversal_probability=contract.reversal_probability,
            executable_price=opposite_price,
        )
        rejection_reason = _reversal_candidate_rejection_reason(
            probability=contract.reversal_probability,
            minimum_probability=self._reversal_min_probability,
            executable_price=opposite_price,
            max_executable_price=self._reversal_max_executable_price,
            expected_value=reversal_ev,
            min_expected_value=self._reversal_min_ev,
            side_needs_cross=feasibility.side_needs_cross,
            classifier_enabled=self._reversal_classifier_enabled,
        )
        candidate_status = (
            "shadow_candidate"
            if rejection_reason is None and self._reversal_shadow_only
            else "live_candidate"
            if rejection_reason is None
            else "rejected"
        )
        if rejection_reason is not None and not self._score_telemetry_enabled:
            return None
        signal_quality_fields = {
            "range_expansion_status": contract.range_expansion_status,
            "momentum_deceleration_status": contract.momentum_deceleration_status,
        }
        roadmap_fields = self._roadmap_quality_fields(
            product_id=contract.product_id,
            bias_state=bias_like,
            feasibility=feasibility,
            entry_price=opposite_price,
            trend_confirmation_status=contract.trend_confirmation_status,
            signal_quality_fields=signal_quality_fields,
            progression_memory=progression_memory,
            is_reversal_candidate=True,
            reversal_probability_override=contract.reversal_probability,
            reversal_expected_value_override=reversal_ev,
            reversal_candidate_status=candidate_status,
            reversal_rejection_reason=rejection_reason,
        )
        score = score_contract(
            confidence=max(contract.confidence - 10, 1),
            best_bid=ticker_state.yes_bid_dollars or Decimal("0"),
            best_ask=ticker_state.yes_ask_dollars or Decimal("0"),
            yes_bid_size_fp=ticker_state.yes_bid_size_fp,
            yes_ask_size_fp=ticker_state.yes_ask_size_fp,
            dollar_volume=ticker_state.dollar_volume,
            composite_score=roadmap_fields.get("composite_score"),
        )
        return replace(
            contract,
            direction=opposite_direction,
            structure="reversal",
            confidence=max(contract.confidence - 10, 1),
            score=score,
            midpoint=opposite_price or contract.midpoint,
            target_price=feasibility.target_price,
            target_price_source=feasibility.target_price_source,
            distance_to_target=feasibility.distance_to_target,
            distance_to_target_bps=feasibility.distance_to_target_bps,
            required_bps_per_minute=feasibility.required_bps_per_minute,
            side_currently_itm=feasibility.side_currently_itm,
            side_needs_cross=feasibility.side_needs_cross,
            feasibility_status=feasibility.feasibility_status,
            scanner_score_downgrade_reasons=(
                tuple(contract.scanner_score_downgrade_reasons)
                + (("reversal_candidate_rejected",) if rejection_reason else ())
            ),
            scanner_score_bonus_reasons=(
                tuple(contract.scanner_score_bonus_reasons)
                + (("reversal_candidate_generated",) if rejection_reason is None else ())
            ),
            **roadmap_fields,
        )

    def _quiet_continuation_signal_block_reason(
        self,
        *,
        product_id: str,
        bias_state,  # noqa: ANN001
    ) -> str | None:
        direction = getattr(bias_state, "direction", None)
        recent_return = _decimal_or_none(getattr(bias_state, "recent_return_bps", None))
        recent_3m_return = _decimal_or_none(
            getattr(bias_state, "recent_3m_return_bps", None)
        )
        recent_5m_return = _decimal_or_none(
            getattr(bias_state, "recent_5m_return_bps", None)
        )
        recent_5m_range = _decimal_or_none(
            getattr(bias_state, "recent_5m_range_bps", None)
        )
        direction_sign = _direction_sign(direction)
        if direction_sign == 0:
            return "quiet_continuation_direction_missing"
        if recent_return is None:
            return "quiet_continuation_recent_return_missing"
        if abs(recent_return) > self._quiet_continuation_max_recent_bps:
            return "quiet_continuation_recent_move_too_large"
        if _sign(recent_return) not in {0, direction_sign} and abs(
            recent_return
        ) >= IMPULSE_CONFIRMATION_RETURN_BPS:
            return "quiet_continuation_recent_opposite"
        if (
            recent_3m_return is not None
            and _aligned_abs(recent_3m_return, direction) is not None
            and _aligned_abs(recent_3m_return, direction)
            > self._quiet_continuation_max_3m_abs_bps
        ):
            return "quiet_continuation_3m_burst_too_large"
        if (
            recent_5m_return is not None
            and _aligned_abs(recent_5m_return, direction) is not None
            and _aligned_abs(recent_5m_return, direction)
            > self._quiet_continuation_max_5m_abs_bps
        ):
            return "quiet_continuation_5m_burst_too_large"
        if (
            recent_5m_range is not None
            and recent_5m_range > self._quiet_continuation_max_5m_range_bps
        ):
            return "quiet_continuation_range_expanded"
        if self._quiet_continuation_block_deceleration and (
            _momentum_deceleration_status(
                bias_state=bias_state,
                direction=direction,
                burst_3m_bps=self._product_exhaustion_burst_3m(product_id),
                deceleration_recent_bps=self._exhaustion_deceleration_recent_bps,
            )
            == "decelerating_after_burst"
        ):
            return "quiet_continuation_decelerating_after_burst"
        if self._quiet_continuation_block_near_extreme and _near_recent_extreme(
            bias_state=bias_state,
            direction=direction,
            threshold_bps=self._quiet_continuation_min_distance_from_extreme_bps,
        ):
            return "quiet_continuation_near_recent_extreme"
        return None

    def _exhaustion_skip_reason(
        self,
        *,
        bias_state,  # noqa: ANN001
        feasibility: TargetFeasibility,
        signal_quality_fields: Mapping[str, object],
    ) -> str | None:
        if not self._exhaustion_guard_enabled:
            return None
        if getattr(bias_state, "structure", None) != "trend":
            return None
        if bool(feasibility.side_needs_cross):
            return None
        if signal_quality_fields.get("exhaustion_status") == "blocked":
            if self._roadmap_mode_active:
                return None
            return "exhaustion_guard_blocked"
        return None

    def _product_exhaustion_burst_3m(self, product_id: str) -> Decimal:
        if product_id.upper() in self._exhaustion_strict_products:
            return self._exhaustion_strict_burst_3m_bps
        return self._exhaustion_burst_3m_bps

    def _weak_momentum_stabilization_status(
        self,
        *,
        product_id: str,
        bias_state,  # noqa: ANN001
        feasibility: TargetFeasibility | None,
        entry_price: Decimal | None,
    ) -> tuple[str, str | None]:
        min_distance, max_range, max_price = self._product_weak_momentum_thresholds(
            product_id
        )
        if min_distance is None or max_range is None or max_price is None:
            return ("disabled", None)
        if feasibility is None:
            return ("blocked", "feasibility_missing")
        if not bool(feasibility.side_currently_itm) or bool(feasibility.side_needs_cross):
            return ("blocked", "not_stable_itm_no_cross")
        if feasibility.distance_to_target_bps is None:
            return ("blocked", "distance_missing")
        if feasibility.distance_to_target_bps > min_distance:
            return ("blocked", "distance_not_deep_enough_itm")
        if entry_price is None:
            return ("blocked", "entry_price_missing")
        if entry_price > max_price:
            return ("blocked", "entry_price_above_limit")
        direction = getattr(bias_state, "direction", None)
        direction_sign = _direction_sign(direction)
        if direction_sign == 0:
            return ("blocked", "direction_missing")
        recent_return = _decimal_or_none(getattr(bias_state, "recent_return_bps", None))
        if recent_return is None:
            return ("blocked", "recent_return_missing")
        if _sign(recent_return) not in {0, direction_sign}:
            return ("blocked", "recent_return_opposite")
        if abs(recent_return) > self._quiet_continuation_max_recent_bps:
            return ("blocked", "recent_return_too_large")
        recent_5m_range = _decimal_or_none(
            getattr(bias_state, "recent_5m_range_bps", None)
        )
        if recent_5m_range is None:
            return ("blocked", "recent_5m_range_missing")
        if recent_5m_range > max_range:
            return ("blocked", "recent_5m_range_too_large")
        return ("allowed", "stable_itm_weak_momentum")

    def _mini_exhaustion_status(
        self,
        *,
        product_id: str,
        bias_state,  # noqa: ANN001
        feasibility: TargetFeasibility | None,
    ) -> tuple[str, str | None]:
        enabled, max_3m, min_range, min_recent = self._product_mini_exhaustion_thresholds(
            product_id
        )
        if not enabled:
            return ("disabled", None)
        if getattr(bias_state, "structure", None) != "trend":
            return ("not_applicable", "not_trend")
        if feasibility is None or feasibility.distance_to_target_bps is None:
            return ("clear", "distance_missing")
        if abs(feasibility.distance_to_target_bps) > NEEDS_CROSS_SOFT_DISTANCE_BPS:
            return ("clear", "not_near_strike")
        direction = getattr(bias_state, "direction", None)
        recent_return = _decimal_or_none(getattr(bias_state, "recent_return_bps", None))
        recent_3m_return = _decimal_or_none(
            getattr(bias_state, "recent_3m_return_bps", None)
        )
        recent_5m_range = _decimal_or_none(
            getattr(bias_state, "recent_5m_range_bps", None)
        )
        aligned_recent = _aligned_abs(recent_return, direction)
        aligned_3m = _aligned_abs(recent_3m_return, direction)
        if aligned_recent is None or aligned_3m is None or recent_5m_range is None:
            return ("clear", "momentum_diagnostics_missing")
        if aligned_3m > max_3m:
            return ("clear", "three_minute_move_above_moderate_limit")
        if aligned_recent < min_recent:
            return ("clear", "recent_spike_below_threshold")
        if recent_5m_range < min_range:
            return ("clear", "range_below_threshold")
        return ("flagged", "near_strike_recent_spike_elevated_range")

    def _product_weak_momentum_thresholds(
        self,
        product_id: str,
    ) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
        _ = product_id
        return (
            self._weak_momentum_stabilization_min_distance,
            self._weak_momentum_max_range,
            self._weak_momentum_max_price,
        )

    def _product_mini_exhaustion_thresholds(
        self,
        product_id: str,
    ) -> tuple[bool, Decimal, Decimal, Decimal]:
        _ = product_id
        return (
            self._mini_exhaustion_enabled,
            self._mini_exhaustion_3m_bps,
            self._mini_exhaustion_range_bps,
            self._mini_exhaustion_recent_bps,
        )

    def _product_min_cross_distance_bps(self, product_id: str) -> Decimal:
        _ = product_id
        return self._min_cross_distance_bps


def scanner_live_settings_kwargs(settings: KalshiSettings) -> dict[str, object]:
    return {
        "quiet_continuation_enabled": settings.live_quiet_continuation_enabled,
        "quiet_continuation_max_required_bps_per_minute": (
            settings.live_max_required_bps_per_minute
        ),
        "quiet_continuation_max_recent_bps": (
            settings.live_quiet_continuation_max_recent_bps
        ),
        "quiet_continuation_max_3m_abs_bps": (
            settings.live_quiet_continuation_max_3m_abs_bps
        ),
        "quiet_continuation_max_5m_abs_bps": (
            settings.live_quiet_continuation_max_5m_abs_bps
        ),
        "quiet_continuation_max_5m_range_bps": (
            settings.live_quiet_continuation_max_5m_range_bps
        ),
        "quiet_continuation_block_deceleration": (
            settings.live_quiet_continuation_block_deceleration
        ),
        "quiet_continuation_block_near_extreme": (
            settings.live_quiet_continuation_block_near_extreme
        ),
        "quiet_continuation_min_distance_from_extreme_bps": (
            settings.live_quiet_continuation_min_distance_from_extreme_bps
        ),
        "exhaustion_guard_enabled": settings.live_exhaustion_guard_enabled,
        "exhaustion_burst_3m_bps": settings.live_exhaustion_burst_3m_bps,
        "exhaustion_burst_5m_bps": settings.live_exhaustion_burst_5m_bps,
        "exhaustion_near_extreme_bps": settings.live_exhaustion_near_extreme_bps,
        "exhaustion_deceleration_recent_bps": (
            settings.live_exhaustion_deceleration_recent_bps
        ),
        "exhaustion_strict_products": settings.live_exhaustion_strict_products,
        "exhaustion_strict_burst_3m_bps": (
            settings.live_exhaustion_strict_burst_3m_bps
        ),
        "exhaustion_progression_override_enabled": (
            settings.live_exhaustion_progression_override_enabled
        ),
        "exhaustion_progression_min_aligned_cycles": (
            settings.live_exhaustion_progression_min_aligned_cycles
        ),
        "early_momentum_enabled": settings.live_early_momentum_enabled,
        "early_momentum_min_recent_bps": settings.live_early_momentum_min_recent_bps,
        "early_momentum_max_3m_burst_bps": (
            settings.live_early_momentum_max_3m_burst_bps
        ),
        "weak_momentum_stabilization_min_distance": (
            settings.live_weak_momentum_stabilization_min_distance
        ),
        "weak_momentum_max_range": settings.live_weak_momentum_max_range,
        "weak_momentum_max_price": settings.live_weak_momentum_max_price,
        "mini_exhaustion_enabled": settings.live_mini_exhaustion_enabled,
        "mini_exhaustion_3m_bps": settings.live_mini_exhaustion_3m_bps,
        "mini_exhaustion_range_bps": settings.live_mini_exhaustion_range_bps,
        "mini_exhaustion_recent_bps": settings.live_mini_exhaustion_recent_bps,
        "min_cross_distance_bps": settings.live_min_cross_distance_bps,
        "adaptive_thresholds_enabled": settings.live_adaptive_thresholds_enabled,
        "composite_score_enabled": settings.live_composite_score_enabled,
        "composite_score_min": settings.live_composite_score_min,
        "composite_borderline_min": settings.live_composite_borderline_min,
        "return_range_ratio_enabled": settings.live_return_range_ratio_enabled,
        "return_range_ratio_min_by_product": (
            settings.live_return_range_ratio_min_by_product
        ),
        "progression_memory_enabled": settings.live_progression_memory_enabled,
        "reversal_classifier_enabled": settings.live_reversal_classifier_enabled,
        "reversal_shadow_only": settings.live_reversal_shadow_only,
        "reversal_max_executable_price": settings.live_reversal_max_executable_price,
        "reversal_min_ev": settings.live_reversal_min_ev,
        "reversal_min_probability": settings.live_reversal_min_probability,
        "unified_near_extreme_enabled": settings.live_unified_near_extreme_enabled,
        "unified_near_extreme_base_bps_by_product": (
            settings.live_unified_near_extreme_base_bps_by_product
        ),
        "adaptive_chop_enabled": settings.live_adaptive_chop_enabled,
        "adaptive_pacing_enabled": settings.live_adaptive_pacing_enabled,
        "product_volatility_scale_by_product": (
            settings.live_product_volatility_scale_by_product
        ),
        "score_telemetry_enabled": settings.live_score_telemetry_enabled,
    }


class _OppositeBiasState:
    def __init__(self, contract: ScannedContract, direction: str) -> None:
        self.product_id = contract.product_id
        self.direction = direction
        self.confidence = contract.confidence
        self.structure = "reversal"
        self.latest_price = contract.latest_price
        self.lookback_return_bps = contract.lookback_return_bps
        self.recent_return_bps = contract.recent_return_bps
        self.observation_count = contract.observation_count or 0
        self.as_of = contract.bias_as_of
        self.impulse_direction = contract.impulse_direction
        self.impulse_return_bps = contract.impulse_return_bps
        self.impulse_detected = contract.impulse_detected
        self.classification_reason = "reversal_candidate_from_fake_continuation"
        self.chop_threshold_bps = contract.chop_threshold_bps
        self.recent_window_seconds = contract.recent_window_seconds
        self.lookback_window_seconds = contract.lookback_window_seconds
        self.recent_abs_bps = contract.recent_abs_bps
        self.lookback_abs_bps = contract.lookback_abs_bps
        self.recent_threshold_gap_bps = contract.recent_threshold_gap_bps
        self.lookback_threshold_gap_bps = contract.lookback_threshold_gap_bps
        self.recent_3m_return_bps = contract.recent_3m_return_bps
        self.recent_5m_return_bps = contract.recent_5m_return_bps
        self.recent_3m_range_bps = contract.recent_3m_range_bps
        self.recent_5m_range_bps = contract.recent_5m_range_bps
        self.distance_to_recent_high_bps = contract.distance_to_recent_high_bps
        self.distance_to_recent_low_bps = contract.distance_to_recent_low_bps


def _return_range_ratio(
    lookback_return_bps: Decimal | None,
    recent_5m_range_bps: Decimal | None,
) -> Decimal | None:
    lookback = _decimal_or_none(lookback_return_bps)
    recent_range = _decimal_or_none(recent_5m_range_bps)
    if lookback is None or recent_range is None or recent_range <= Decimal("0"):
        return None
    return (abs(lookback) / recent_range).quantize(Decimal("0.0001"))


def _progression_memory_for_candidate(
    states_by_product: Mapping[str, ProgressionMemoryState],
    *,
    product_id: str,
    direction: str | None,
) -> ProgressionMemoryState | None:
    state = states_by_product.get(product_id.upper()) or states_by_product.get(product_id)
    if state is None or state.memory_cold_start:
        return state
    if state.last_direction is not None and direction is not None:
        if state.last_direction != direction:
            return None
    return state


def _near_extreme_distance_bps(*, bias_state, direction: str | None) -> Decimal | None:  # noqa: ANN001
    if direction == "up":
        return _decimal_or_none(getattr(bias_state, "distance_to_recent_high_bps", None))
    if direction == "down":
        return _decimal_or_none(getattr(bias_state, "distance_to_recent_low_bps", None))
    high = _decimal_or_none(getattr(bias_state, "distance_to_recent_high_bps", None))
    low = _decimal_or_none(getattr(bias_state, "distance_to_recent_low_bps", None))
    if high is None:
        return low
    if low is None:
        return high
    return min(high, low)


def _opposite_executable_price(
    *,
    direction: str,
    ticker_state: TickerState,
) -> Decimal | None:
    if direction == "up":
        return ticker_state.yes_ask_dollars
    if direction == "down" and ticker_state.yes_bid_dollars is not None:
        return (Decimal("1") - ticker_state.yes_bid_dollars).quantize(Decimal("0.0001"))
    return None


def _reversal_candidate_rejection_reason(
    *,
    probability: Decimal | None,
    minimum_probability: Decimal,
    executable_price: Decimal | None,
    max_executable_price: Decimal,
    expected_value: Decimal | None,
    min_expected_value: Decimal,
    side_needs_cross: bool | None,
    classifier_enabled: bool,
) -> str | None:
    if not classifier_enabled:
        return "reversal_classifier_disabled"
    if probability is None:
        return "reversal_probability_missing"
    if probability < minimum_probability:
        return "reversal_probability_below_minimum"
    if executable_price is None:
        return "reversal_executable_price_missing"
    if executable_price > max_executable_price:
        return "reversal_executable_price_above_maximum"
    if expected_value is None:
        return "reversal_expected_value_missing"
    if expected_value < min_expected_value:
        return "reversal_expected_value_below_minimum"
    if bool(side_needs_cross):
        return "reversal_needs_cross_blocked"
    return None


def _range_expansion_status(
    recent_range_bps: Decimal | None,
    *,
    threshold_bps: Decimal,
) -> str:
    if recent_range_bps is None:
        return "missing"
    if recent_range_bps > threshold_bps:
        return "expanded"
    return "normal"


def _momentum_deceleration_status(
    *,
    bias_state,  # noqa: ANN001
    direction: str | None,
    burst_3m_bps: Decimal,
    deceleration_recent_bps: Decimal,
) -> str:
    recent_return = _decimal_or_none(getattr(bias_state, "recent_return_bps", None))
    recent_3m_return = _decimal_or_none(
        getattr(bias_state, "recent_3m_return_bps", None)
    )
    if recent_return is None or recent_3m_return is None:
        return "missing"
    aligned_3m = _aligned_abs(recent_3m_return, direction)
    if aligned_3m is None or aligned_3m <= burst_3m_bps:
        return "not_bursting"
    direction_sign = _direction_sign(direction)
    if _sign(recent_return) != direction_sign or abs(recent_return) <= deceleration_recent_bps:
        return "decelerating_after_burst"
    return "still_moving"


def _exhaustion_status(
    *,
    guard_enabled: bool,
    range_expansion_status: str,
    momentum_deceleration_status: str,
    near_extreme: bool,
) -> str:
    if not guard_enabled:
        return "disabled"
    if momentum_deceleration_status == "decelerating_after_burst":
        return "blocked"
    if range_expansion_status == "expanded" and near_extreme:
        return "blocked"
    if range_expansion_status == "missing" or momentum_deceleration_status == "missing":
        return "missing_diagnostics"
    return "clear"


def _exhaustion_base_reason(
    *,
    range_expansion_status: str,
    momentum_deceleration_status: str,
    near_extreme: bool,
) -> str | None:
    if momentum_deceleration_status == "decelerating_after_burst":
        return "decelerating_after_burst"
    if range_expansion_status == "expanded" and near_extreme:
        return "expanded_range_near_extreme"
    if range_expansion_status == "missing" or momentum_deceleration_status == "missing":
        return "missing_diagnostics"
    return None


def exhaustion_progression_sample_from_bias(
    *,
    product_id: str,
    bias_state,  # noqa: ANN001
    cycle_number: int | None,
    source: str,
) -> ExhaustionProgressionSample:
    return ExhaustionProgressionSample(
        product_id=product_id,
        direction=getattr(bias_state, "direction", None),
        structure=getattr(bias_state, "structure", None),
        classification_reason=getattr(bias_state, "classification_reason", None),
        recent_return_bps=_decimal_or_none(
            getattr(bias_state, "recent_return_bps", None)
        ),
        recent_3m_return_bps=_decimal_or_none(
            getattr(bias_state, "recent_3m_return_bps", None)
        ),
        lookback_return_bps=_decimal_or_none(
            getattr(bias_state, "lookback_return_bps", None)
        ),
        recent_5m_range_bps=_decimal_or_none(
            getattr(bias_state, "recent_5m_range_bps", None)
        ),
        distance_to_recent_high_bps=_decimal_or_none(
            getattr(bias_state, "distance_to_recent_high_bps", None)
        ),
        distance_to_recent_low_bps=_decimal_or_none(
            getattr(bias_state, "distance_to_recent_low_bps", None)
        ),
        cycle_number=cycle_number,
        source=source,
    )


def _exhaustion_progression_decision(
    *,
    enabled: bool,
    min_aligned_cycles: int,
    product_id: str,
    bias_state,  # noqa: ANN001
    feasibility: TargetFeasibility | None,
    base_status: str,
    base_reason: str | None,
    near_extreme: bool,
    mini_exhaustion_status: str,
    progression_context: tuple[ExhaustionProgressionSample, ...],
) -> ExhaustionProgressionDecision:
    if not enabled:
        return _progression_decision(
            "disabled",
            "feature_disabled",
            progression_context,
            aligned_count=0,
        )
    if base_status != "blocked":
        return _progression_decision(
            "not_applicable",
            "base_not_blocked",
            progression_context,
            aligned_count=0,
        )
    if getattr(bias_state, "structure", None) != "trend":
        return _progression_decision(
            "not_applicable",
            "not_trend",
            progression_context,
            aligned_count=0,
        )
    current_sample = exhaustion_progression_sample_from_bias(
        product_id=product_id,
        bias_state=bias_state,
        cycle_number=None,
        source="current_scan",
    )
    samples = tuple(progression_context) + (current_sample,)
    direction = getattr(bias_state, "direction", None)
    direction_sign = _direction_sign(direction)
    aligned_samples = tuple(
        sample
        for sample in samples
        if _progression_sample_is_aligned(
            sample,
            product_id=product_id,
            direction=direction,
        )
    )
    matched: list[str] = []
    failed: list[str] = []
    if direction_sign == 0:
        failed.append("direction_missing")
    else:
        matched.append("direction_present")
    if feasibility is None:
        failed.append("feasibility_missing")
    elif not bool(feasibility.side_currently_itm) or bool(feasibility.side_needs_cross):
        failed.append("not_stable_itm_no_cross")
    else:
        matched.append("stable_itm_no_cross")
    required_bps = (
        None
        if feasibility is None or feasibility.required_bps_per_minute is None
        else Decimal(str(feasibility.required_bps_per_minute))
    )
    if required_bps is None:
        failed.append("required_bps_missing")
    elif required_bps > Decimal("0"):
        failed.append("required_bps_positive")
    else:
        matched.append("non_positive_required_bps")
    if mini_exhaustion_status == "flagged":
        failed.append("mini_exhaustion_flagged")
    else:
        matched.append("mini_exhaustion_not_flagged")
    if len(aligned_samples) < min_aligned_cycles:
        failed.append("insufficient_aligned_progression_samples")
    else:
        matched.append("aligned_progression_samples")
    recent_return = _decimal_or_none(getattr(bias_state, "recent_return_bps", None))
    if recent_return is None:
        failed.append("recent_return_missing")
    elif _sign(recent_return) not in {0, direction_sign}:
        failed.append("recent_return_opposite")
    else:
        matched.append("recent_return_aligned_or_flat")
    recent_3m_return = _decimal_or_none(
        getattr(bias_state, "recent_3m_return_bps", None)
    )
    if _aligned_abs(recent_3m_return, direction) is None:
        failed.append("recent_3m_return_not_aligned")
    else:
        matched.append("recent_3m_return_aligned")
    lookback_return = _decimal_or_none(
        getattr(bias_state, "lookback_return_bps", None)
    )
    if _aligned_abs(lookback_return, direction) is None:
        failed.append("lookback_return_not_aligned")
    else:
        matched.append("lookback_return_aligned")
    current_range = _decimal_or_none(
        getattr(bias_state, "recent_5m_range_bps", None)
    )
    previous_range = _latest_non_null(
        sample.recent_5m_range_bps for sample in progression_context
    )
    if current_range is None or previous_range is None:
        failed.append("range_progression_missing")
    elif current_range > previous_range:
        failed.append("range_accelerating")
    else:
        matched.append("range_not_accelerating")
    current_distance = _progression_extreme_distance(current_sample, direction=direction)
    previous_distance = _latest_non_null(
        _progression_extreme_distance(sample, direction=direction)
        for sample in progression_context
    )
    if current_distance is None or previous_distance is None:
        failed.append("extreme_distance_progression_missing")
    elif current_distance < previous_distance:
        failed.append("extreme_distance_worsening")
    else:
        matched.append("extreme_distance_not_worsening")
    if failed:
        return ExhaustionProgressionDecision(
            status="blocked",
            reason=failed[0],
            sample_count=len(samples),
            aligned_count=len(aligned_samples),
            matched_conditions=tuple(dict.fromkeys(matched)),
            failed_conditions=tuple(dict.fromkeys(failed)),
            context_source=_progression_context_source(samples),
        )
    return ExhaustionProgressionDecision(
        status="allowed",
        reason="sustained_itm_no_cross_progression",
        sample_count=len(samples),
        aligned_count=len(aligned_samples),
        matched_conditions=tuple(dict.fromkeys(matched)),
        failed_conditions=(),
        context_source=_progression_context_source(samples),
    )


def _progression_decision(
    status: str,
    reason: str | None,
    samples: tuple[ExhaustionProgressionSample, ...],
    *,
    aligned_count: int,
) -> ExhaustionProgressionDecision:
    return ExhaustionProgressionDecision(
        status=status,
        reason=reason,
        sample_count=len(samples),
        aligned_count=aligned_count,
        matched_conditions=(),
        failed_conditions=(),
        context_source=_progression_context_source(samples),
    )


def _progression_sample_is_aligned(
    sample: ExhaustionProgressionSample,
    *,
    product_id: str,
    direction: str | None,
) -> bool:
    classification_reason = sample.classification_reason or ""
    return (
        sample.product_id == product_id
        and sample.direction == direction
        and sample.structure == "trend"
        and not classification_reason.startswith("reversal")
    )


def _progression_extreme_distance(
    sample: ExhaustionProgressionSample,
    *,
    direction: str | None,
) -> Decimal | None:
    if direction == "up":
        return sample.distance_to_recent_high_bps
    if direction == "down":
        return sample.distance_to_recent_low_bps
    return None


def _latest_non_null(values) -> Decimal | None:  # noqa: ANN001
    for value in reversed(tuple(values)):
        if value is not None:
            return Decimal(str(value))
    return None


def _progression_context_source(
    samples: tuple[ExhaustionProgressionSample, ...],
) -> str | None:
    sources = tuple(
        dict.fromkeys(sample.source for sample in samples if sample.source is not None)
    )
    if not sources:
        return None
    return ",".join(sources)


def _early_momentum_status(
    *,
    enabled: bool,
    bias_state,  # noqa: ANN001
    direction: str | None,
    min_recent_bps: Decimal,
    max_3m_burst_bps: Decimal,
    exhaustion_status: str,
) -> str:
    if not enabled:
        return "disabled"
    if getattr(bias_state, "structure", None) != "trend":
        return "not_trend"
    recent_return = _decimal_or_none(getattr(bias_state, "recent_return_bps", None))
    recent_3m_return = _decimal_or_none(
        getattr(bias_state, "recent_3m_return_bps", None)
    )
    aligned_recent = _aligned_abs(recent_return, direction)
    aligned_3m = _aligned_abs(recent_3m_return, direction)
    if aligned_recent is None or aligned_recent < min_recent_bps:
        return "recent_momentum_too_weak"
    if aligned_3m is not None and aligned_3m > max_3m_burst_bps:
        return "three_minute_burst_too_large"
    if exhaustion_status == "blocked":
        return "exhaustion_blocked"
    return "confirmed"


def _near_recent_extreme(
    *,
    bias_state,  # noqa: ANN001
    direction: str | None,
    threshold_bps: Decimal,
) -> bool:
    if direction == "up":
        distance = _decimal_or_none(
            getattr(bias_state, "distance_to_recent_high_bps", None)
        )
    elif direction == "down":
        distance = _decimal_or_none(
            getattr(bias_state, "distance_to_recent_low_bps", None)
        )
    else:
        return False
    return distance is not None and distance <= threshold_bps


def _aligned_abs(value: Decimal | None, direction: str | None) -> Decimal | None:
    if value is None:
        return None
    direction_sign = _direction_sign(direction)
    if direction_sign == 0 or _sign(value) != direction_sign:
        return None
    return abs(value)


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _decay_ratio(bias_state, *, direction: str | None) -> Decimal | None:  # noqa: ANN001
    recent_return = _decimal_or_none(getattr(bias_state, "recent_return_bps", None))
    recent_3m_return = _decimal_or_none(
        getattr(bias_state, "recent_3m_return_bps", None)
    )
    aligned_recent = _aligned_abs(recent_return, direction)
    aligned_3m = _aligned_abs(recent_3m_return, direction)
    if aligned_recent is None or aligned_3m is None or aligned_3m <= Decimal("0"):
        return None
    return (aligned_recent / aligned_3m).quantize(Decimal("0.001"))


def _quote_midpoint(ticker_state: TickerState) -> Decimal:
    assert ticker_state.yes_bid_dollars is not None
    assert ticker_state.yes_ask_dollars is not None
    return ((ticker_state.yes_bid_dollars + ticker_state.yes_ask_dollars) / TWO_DECIMAL).quantize(
        Decimal("0.001")
    )


def _mean_reversion_candidate_status(bias_state) -> str:  # noqa: ANN001
    if getattr(bias_state, "structure", None) != "reversal":
        return "not_reversal"
    return "diagnostic_only"


def _reversal_pullback_vs_true_reversal_status(bias_state) -> str:  # noqa: ANN001
    if getattr(bias_state, "structure", None) != "reversal":
        return "not_reversal"
    recent_return = _decimal_or_none(getattr(bias_state, "recent_return_bps", None))
    impulse_return = _decimal_or_none(getattr(bias_state, "impulse_return_bps", None))
    if recent_return is None:
        return "recent_return_missing"
    if impulse_return is not None and _sign(recent_return) != _sign(impulse_return):
        return "pullback_or_retest"
    return "unconfirmed_true_reversal"


def _skip_reason(bias_state, ticker_state: TickerState) -> str | None:
    if bias_state is None:
        return "missing_bias_state"
    if bias_state.direction == "neutral":
        return "neutral_bias"
    if bias_state.confidence <= 0:
        return "zero_confidence"
    if _is_late_expansion_bias(bias_state):
        return "too_late_after_expansion"
    if _is_unconfirmed_impulse_bias(bias_state):
        return "impulse_unconfirmed"
    if ticker_state.yes_bid_dollars is None or ticker_state.yes_ask_dollars is None:
        return "missing_best_quote"
    return None


def _quiet_continuation_bias_state(bias_state, *, enabled: bool):  # noqa: ANN001
    if not enabled or bias_state is None:
        return None
    if bias_state.direction != "neutral" or bias_state.structure not in {"chop", "exhaustion"}:
        return None
    if bias_state.structure == "reversal":
        return None
    if bias_state.confidence <= 0:
        return None
    risk_flags = getattr(bias_state, "risk_flags", None)
    if risk_flags is None or any(
        (
            bool(risk_flags.insufficient_history),
            bool(risk_flags.stale_data),
            bool(risk_flags.time_sync_failed),
        )
    ):
        return None
    lookback_return_bps = getattr(bias_state, "lookback_return_bps", None)
    recent_return_bps = getattr(bias_state, "recent_return_bps", None)
    threshold_bps = getattr(bias_state, "chop_threshold_bps", None)
    if lookback_return_bps is None or recent_return_bps is None or threshold_bps is None:
        return None
    lookback_return = Decimal(str(lookback_return_bps))
    recent_return = Decimal(str(recent_return_bps))
    threshold = Decimal(str(threshold_bps))
    lookback_sign = _sign(lookback_return)
    if lookback_sign == 0 or abs(lookback_return) <= threshold:
        return None
    if abs(recent_return) > threshold:
        return None
    direction = "up" if lookback_sign > 0 else "down"
    return replace(
        bias_state,
        direction=direction,
        structure="trend",
        confidence=max(int(bias_state.confidence), SCORE_DOWNGRADE_CONFLICT_CONFIDENCE),
        classification_reason=f"quiet_continuation_from_{bias_state.structure}",
    )


def _quiet_continuation_skip_reason(
    feasibility: TargetFeasibility,
    *,
    max_required_bps_per_minute: Decimal,
) -> str | None:
    if feasibility.target_price is None:
        return "quiet_continuation_target_missing"
    if feasibility.current_spot_price is None:
        return "quiet_continuation_current_spot_missing"
    if feasibility.side_needs_cross or not feasibility.side_currently_itm:
        return "quiet_continuation_needs_cross_blocked"
    if feasibility.required_bps_per_minute is None:
        return "quiet_continuation_required_bps_missing"
    if feasibility.required_bps_per_minute > max_required_bps_per_minute:
        return "quiet_continuation_required_bps_too_high"
    return None


def _bias_diagnostic_fields(bias_state) -> dict[str, object]:  # noqa: ANN001
    if bias_state is None:
        return {}
    return {
        "direction": getattr(bias_state, "direction", None),
        "structure": getattr(bias_state, "structure", None),
        "confidence": getattr(bias_state, "confidence", None),
        "latest_price": getattr(bias_state, "latest_price", None),
        "observation_count": getattr(bias_state, "observation_count", None),
        "recent_return_bps": getattr(bias_state, "recent_return_bps", None),
        "lookback_return_bps": getattr(bias_state, "lookback_return_bps", None),
        "impulse_direction": getattr(bias_state, "impulse_direction", None),
        "impulse_return_bps": getattr(bias_state, "impulse_return_bps", None),
        "impulse_detected": getattr(bias_state, "impulse_detected", None),
        "risk_flags": _risk_flags(getattr(bias_state, "risk_flags", None)),
        "classification_reason": getattr(bias_state, "classification_reason", None),
        "chop_threshold_bps": getattr(bias_state, "chop_threshold_bps", None),
        "recent_window_seconds": getattr(bias_state, "recent_window_seconds", None),
        "lookback_window_seconds": getattr(bias_state, "lookback_window_seconds", None),
        "recent_abs_bps": getattr(bias_state, "recent_abs_bps", None),
        "lookback_abs_bps": getattr(bias_state, "lookback_abs_bps", None),
        "recent_threshold_gap_bps": getattr(
            bias_state,
            "recent_threshold_gap_bps",
            None,
        ),
        "lookback_threshold_gap_bps": getattr(
            bias_state,
            "lookback_threshold_gap_bps",
            None,
        ),
        "recent_3m_return_bps": getattr(bias_state, "recent_3m_return_bps", None),
        "recent_5m_return_bps": getattr(bias_state, "recent_5m_return_bps", None),
        "recent_3m_range_bps": getattr(bias_state, "recent_3m_range_bps", None),
        "recent_5m_range_bps": getattr(bias_state, "recent_5m_range_bps", None),
        "distance_to_recent_high_bps": getattr(
            bias_state,
            "distance_to_recent_high_bps",
            None,
        ),
        "distance_to_recent_low_bps": getattr(
            bias_state,
            "distance_to_recent_low_bps",
            None,
        ),
    }


def _bias_threshold_diagnostic_fields(bias_state) -> dict[str, object]:  # noqa: ANN001
    if bias_state is None:
        return {}
    return {
        "classification_reason": getattr(bias_state, "classification_reason", None),
        "chop_threshold_bps": getattr(bias_state, "chop_threshold_bps", None),
        "recent_window_seconds": getattr(bias_state, "recent_window_seconds", None),
        "lookback_window_seconds": getattr(bias_state, "lookback_window_seconds", None),
        "recent_abs_bps": getattr(bias_state, "recent_abs_bps", None),
        "lookback_abs_bps": getattr(bias_state, "lookback_abs_bps", None),
        "recent_threshold_gap_bps": getattr(
            bias_state,
            "recent_threshold_gap_bps",
            None,
        ),
        "lookback_threshold_gap_bps": getattr(
            bias_state,
            "lookback_threshold_gap_bps",
            None,
        ),
        "recent_3m_return_bps": getattr(bias_state, "recent_3m_return_bps", None),
        "recent_5m_return_bps": getattr(bias_state, "recent_5m_return_bps", None),
        "recent_3m_range_bps": getattr(bias_state, "recent_3m_range_bps", None),
        "recent_5m_range_bps": getattr(bias_state, "recent_5m_range_bps", None),
        "distance_to_recent_high_bps": getattr(
            bias_state,
            "distance_to_recent_high_bps",
            None,
        ),
        "distance_to_recent_low_bps": getattr(
            bias_state,
            "distance_to_recent_low_bps",
            None,
        ),
    }


def _stale_ticker_skip_reason(metadata: Mapping[str, object]) -> str | None:
    elapsed_at = _market_elapsed_at(metadata)
    if elapsed_at is None:
        return None
    if elapsed_at <= datetime.now(timezone.utc):
        return "stale_ticker_blocked"
    return None


def _market_time_remaining_seconds(metadata: Mapping[str, object]) -> int | None:
    elapsed_at = _market_elapsed_at(metadata)
    if elapsed_at is None:
        return None
    return int((elapsed_at - datetime.now(timezone.utc)).total_seconds())


def _market_elapsed_at(metadata: Mapping[str, object]) -> datetime | None:
    candidates = (
        _optional_str_metadata(metadata, "close_time"),
        _optional_str_metadata(metadata, "expiration_time"),
    )
    parsed = tuple(
        parsed_at
        for value in candidates
        for parsed_at in (_try_parse_iso_datetime(value),)
        if parsed_at is not None
    )
    if not parsed:
        return None
    return min(parsed)


def _try_parse_iso_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return _parse_iso_datetime(value)
    except ValueError:
        return None


def _is_late_expansion_bias(bias_state) -> bool:  # noqa: ANN001
    impulse_return_bps = getattr(bias_state, "impulse_return_bps", None)
    if impulse_return_bps is None:
        return False
    return (
        bias_state.direction in {"up", "down"}
        and bias_state.structure == "trend"
        and bias_state.confidence <= 40
        and getattr(bias_state, "impulse_detected", False)
        and getattr(bias_state, "impulse_direction", None) == bias_state.direction
        and abs(Decimal(str(impulse_return_bps))) >= LATE_EXPANSION_IMPULSE_RETURN_BPS
    )


def _is_unconfirmed_impulse_bias(bias_state) -> bool:  # noqa: ANN001
    if not (
        bias_state.direction in {"up", "down"}
        and bias_state.structure == "trend"
        and bias_state.confidence == 40
        and getattr(bias_state, "impulse_detected", False)
        and getattr(bias_state, "impulse_direction", None) == bias_state.direction
    ):
        return False

    recent_return_bps = getattr(bias_state, "recent_return_bps", None)
    lookback_return_bps = getattr(bias_state, "lookback_return_bps", None)
    if recent_return_bps is None or lookback_return_bps is None:
        return True

    recent_return = Decimal(str(recent_return_bps))
    lookback_return = Decimal(str(lookback_return_bps))
    if abs(recent_return) < IMPULSE_CONFIRMATION_RETURN_BPS:
        return True
    if abs(lookback_return) < IMPULSE_CONFIRMATION_RETURN_BPS:
        return True
    if bias_state.direction == "up":
        return recent_return <= 0 or lookback_return <= 0
    return recent_return >= 0 or lookback_return >= 0


def _market_as_of(ticker_state: TickerState) -> str | None:
    if ticker_state.exchange_time:
        return ticker_state.exchange_time
    if ticker_state.exchange_ts is not None:
        return str(ticker_state.exchange_ts)
    return None


def _risk_flags(risk_flags) -> tuple[tuple[str, bool], ...]:  # noqa: ANN001
    if risk_flags is None:
        return ()
    return (
        ("insufficient_history", bool(risk_flags.insufficient_history)),
        ("stale_data", bool(risk_flags.stale_data)),
        ("time_sync_failed", bool(risk_flags.time_sync_failed)),
    )


def _target_feasibility(
    *,
    direction: str,
    current_spot_price: Decimal | None,
    target_price: Decimal | None,
    target_price_source: str | None,
    close_time: str | None,
    min_cross_distance_bps: Decimal = Decimal("0"),
) -> TargetFeasibility:
    time_remaining_seconds = _time_remaining_seconds(close_time)
    if current_spot_price is None:
        return TargetFeasibility(
            current_spot_price=None,
            target_price=target_price,
            target_price_source=target_price_source,
            distance_to_target=None,
            distance_to_target_bps=None,
            time_remaining_seconds=time_remaining_seconds,
            required_bps_per_minute=None,
            side_currently_itm=None,
            side_needs_cross=None,
            feasibility_status="current_spot_missing",
        )
    if target_price is None:
        return TargetFeasibility(
            current_spot_price=current_spot_price,
            target_price=None,
            target_price_source=target_price_source,
            distance_to_target=None,
            distance_to_target_bps=None,
            time_remaining_seconds=time_remaining_seconds,
            required_bps_per_minute=None,
            side_currently_itm=None,
            side_needs_cross=None,
            feasibility_status="target_price_missing",
        )
    if current_spot_price <= Decimal("0"):
        return TargetFeasibility(
            current_spot_price=current_spot_price,
            target_price=target_price,
            target_price_source=target_price_source,
            distance_to_target=None,
            distance_to_target_bps=None,
            time_remaining_seconds=time_remaining_seconds,
            required_bps_per_minute=None,
            side_currently_itm=None,
            side_needs_cross=None,
            feasibility_status="current_spot_invalid",
        )

    distance_to_target = _directional_distance_to_target(
        direction=direction,
        current_spot_price=current_spot_price,
        target_price=target_price,
    )
    if distance_to_target is None:
        return TargetFeasibility(
            current_spot_price=current_spot_price,
            target_price=target_price,
            target_price_source=target_price_source,
            distance_to_target=None,
            distance_to_target_bps=None,
            time_remaining_seconds=time_remaining_seconds,
            required_bps_per_minute=None,
            side_currently_itm=None,
            side_needs_cross=None,
            feasibility_status="invalid_direction",
        )

    distance_to_target_bps = (
        distance_to_target / current_spot_price * BASIS_POINTS_MULTIPLIER
    ).quantize(Decimal("0.001"))
    side_needs_cross = distance_to_target > Decimal("0")
    noise_cross_ignored = (
        side_needs_cross
        and min_cross_distance_bps > Decimal("0")
        and distance_to_target_bps <= min_cross_distance_bps
    )
    effective_side_needs_cross = side_needs_cross and not noise_cross_ignored
    required_bps_per_minute = (
        Decimal("0.000")
        if noise_cross_ignored
        else _required_bps_per_minute(
            distance_to_target_bps=distance_to_target_bps,
            time_remaining_seconds=time_remaining_seconds,
        )
    )
    if time_remaining_seconds is None:
        feasibility_status = "time_remaining_missing"
    elif time_remaining_seconds <= 0:
        feasibility_status = "time_remaining_elapsed"
    elif (
        effective_side_needs_cross
        and time_remaining_seconds <= UNREALISTIC_LATE_CROSS_SECONDS
        and distance_to_target_bps >= UNREALISTIC_LATE_CROSS_DISTANCE_BPS
    ):
        feasibility_status = "unrealistic_late_cross"
    elif noise_cross_ignored:
        feasibility_status = "noise_cross_ignored"
    elif effective_side_needs_cross:
        feasibility_status = "needs_cross"
    else:
        feasibility_status = "currently_itm"

    return TargetFeasibility(
        current_spot_price=current_spot_price,
        target_price=target_price,
        target_price_source=target_price_source,
        distance_to_target=distance_to_target,
        distance_to_target_bps=distance_to_target_bps,
        time_remaining_seconds=time_remaining_seconds,
        required_bps_per_minute=required_bps_per_minute,
        side_currently_itm=not effective_side_needs_cross,
        side_needs_cross=effective_side_needs_cross,
        feasibility_status=feasibility_status,
    )


def _directional_distance_to_target(
    *,
    direction: str,
    current_spot_price: Decimal,
    target_price: Decimal,
) -> Decimal | None:
    if direction == "up":
        return target_price - current_spot_price
    if direction == "down":
        return current_spot_price - target_price
    return None


def _required_bps_per_minute(
    *,
    distance_to_target_bps: Decimal,
    time_remaining_seconds: int | None,
) -> Decimal | None:
    if time_remaining_seconds is None or time_remaining_seconds <= 0:
        return None
    remaining_minutes = Decimal(time_remaining_seconds) / SECONDS_PER_MINUTE
    if distance_to_target_bps <= Decimal("0"):
        return Decimal("0.000")
    return (distance_to_target_bps / remaining_minutes).quantize(Decimal("0.001"))


def _time_remaining_seconds(close_time: str | None) -> int | None:
    if close_time is None:
        return None
    try:
        close_at = _parse_iso_datetime(close_time)
    except ValueError:
        return None
    return int((close_at - datetime.now(timezone.utc)).total_seconds())


def _parse_iso_datetime(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _signal_conflict_flags(
    *,
    direction: str,
    impulse_return_bps: Decimal | None,
) -> tuple[tuple[str, bool], ...]:
    impulse_conflict = False
    if impulse_return_bps is not None and abs(Decimal(str(impulse_return_bps))) >= IMPULSE_CONFIRMATION_RETURN_BPS:
        impulse_sign = _sign(Decimal(str(impulse_return_bps)))
        direction_sign = _direction_sign(direction)
        impulse_conflict = direction_sign != 0 and impulse_sign != 0 and impulse_sign != direction_sign
    return (("impulse_direction_conflict", impulse_conflict),)


def _reversal_confirmation_status(
    *,
    bias_state,
    signal_conflict_flags: tuple[tuple[str, bool], ...],
) -> str:
    if bias_state.structure != "reversal":
        return "not_reversal"
    recent_return_bps = getattr(bias_state, "recent_return_bps", None)
    if recent_return_bps is None:
        return "recent_return_missing"
    recent_return = Decimal(str(recent_return_bps))
    if _sign(recent_return) != _direction_sign(bias_state.direction):
        return "recent_direction_mismatch"
    if abs(recent_return) < REVERSAL_MIN_RECENT_RETURN_BPS:
        return "weak_recent_return"
    if dict(signal_conflict_flags).get("impulse_direction_conflict"):
        return "impulse_direction_conflict"
    return "confirmed"


def _trend_confirmation_status(
    *,
    bias_state,
    feasibility: TargetFeasibility,
) -> str:
    if bias_state.structure != "trend":
        return "not_trend"
    recent_return_bps = getattr(bias_state, "recent_return_bps", None)
    if recent_return_bps is None:
        return "recent_return_missing"
    lookback_return_bps = getattr(bias_state, "lookback_return_bps", None)
    if lookback_return_bps is None:
        return "lookback_return_missing"
    recent_return = Decimal(str(recent_return_bps))
    lookback_return = Decimal(str(lookback_return_bps))
    direction_sign = _direction_sign(bias_state.direction)
    if _sign(recent_return) != direction_sign:
        return "recent_direction_mismatch"
    if _sign(lookback_return) != direction_sign:
        return "lookback_direction_mismatch"
    if abs(recent_return) < TREND_MIN_RECENT_RETURN_BPS:
        return "weak_recent_return"
    if (
        feasibility.side_needs_cross
        and feasibility.distance_to_target_bps is not None
        and feasibility.distance_to_target_bps > NEEDS_CROSS_SOFT_DISTANCE_BPS
    ):
        return "large_cross_required"
    return "confirmed"


def _feasibility_skip_reason(
    *,
    bias_state,
    feasibility: TargetFeasibility,
    signal_conflict_flags: tuple[tuple[str, bool], ...],
) -> str | None:
    if not feasibility.side_needs_cross:
        return None
    if feasibility.feasibility_status == "unrealistic_late_cross":
        if (
            bias_state.structure == "reversal"
            and dict(signal_conflict_flags).get("impulse_direction_conflict")
        ):
            return "signal_conflict_unrealistic_reversal"
        return "target_feasibility_unrealistic_late_cross"
    if (
        feasibility.distance_to_target_bps is not None
        and feasibility.distance_to_target_bps > NEEDS_CROSS_HARD_DISTANCE_BPS
    ):
        return "target_feasibility_distance_too_far"
    if (
        feasibility.required_bps_per_minute is not None
        and feasibility.required_bps_per_minute
        > NEEDS_CROSS_HARD_REQUIRED_BPS_PER_MINUTE
    ):
        return "target_feasibility_required_move_too_fast"
    if (
        feasibility.distance_to_target_bps is not None
        and feasibility.distance_to_target_bps > Decimal("0")
        and feasibility.required_bps_per_minute is not None
        and feasibility.required_bps_per_minute
        > NEEDS_CROSS_TIGHT_REQUIRED_BPS_PER_MINUTE
    ):
        return "target_feasibility_required_move_too_fast_tight"
    return None


def _scanner_score_confidence(
    *,
    product_id: str,
    bias_state,
    feasibility: TargetFeasibility,
    reversal_confirmation_status: str,
    trend_confirmation_status: str,
    signal_conflict_flags: tuple[tuple[str, bool], ...],
    weak_momentum_stabilization_status: object = None,
    mini_exhaustion_status: object = None,
    exhaustion_status: object = None,
) -> tuple[int, tuple[str, ...], tuple[str, ...]]:
    confidence = int(bias_state.confidence)
    downgrade_reasons: list[str] = []
    bonus_reasons: list[str] = []
    if dict(signal_conflict_flags).get("impulse_direction_conflict"):
        confidence = min(confidence, SCORE_DOWNGRADE_NEEDS_CROSS_CONFIDENCE)
        downgrade_reasons.append("impulse_direction_conflict")
    if (
        feasibility.side_needs_cross
        and feasibility.distance_to_target_bps is not None
        and feasibility.distance_to_target_bps > NEEDS_CROSS_SOFT_DISTANCE_BPS
    ):
        confidence = min(confidence, SCORE_DOWNGRADE_SOFT_NEEDS_CROSS_CONFIDENCE)
        downgrade_reasons.append("needs_cross_distance_over_soft_limit")
    elif feasibility.side_needs_cross:
        confidence = min(confidence, SCORE_DOWNGRADE_NEEDS_CROSS_CONFIDENCE)
        downgrade_reasons.append("needs_cross")
    if product_id == "HYPE-USD" and feasibility.side_needs_cross:
        confidence = min(confidence, SCORE_DOWNGRADE_SOFT_NEEDS_CROSS_CONFIDENCE)
        downgrade_reasons.append("hype_needs_cross_caution")
    if bias_state.structure == "reversal" and feasibility.feasibility_status == "target_price_missing":
        confidence = min(confidence, SCORE_DOWNGRADE_NEEDS_CROSS_CONFIDENCE)
        downgrade_reasons.append("reversal_target_price_missing")
    if (
        bias_state.structure == "reversal"
        and feasibility.distance_to_target_bps is not None
        and abs(Decimal(str(feasibility.distance_to_target_bps)))
        <= REVERSAL_NOISE_ZONE_DISTANCE_BPS
    ):
        confidence = min(confidence, SCORE_DOWNGRADE_REVERSAL_NEAR_TARGET_CONFIDENCE)
        if feasibility.side_currently_itm:
            downgrade_reasons.append("reversal_fresh_cross_near_target")
        else:
            downgrade_reasons.append("reversal_noise_zone_near_target")
    if reversal_confirmation_status in {
        "recent_return_missing",
        "recent_direction_mismatch",
        "weak_recent_return",
        "impulse_direction_conflict",
    }:
        confidence = min(confidence, SCORE_DOWNGRADE_CONFLICT_CONFIDENCE)
        downgrade_reasons.append(f"reversal_{reversal_confirmation_status}")
    trend_downgrade_statuses = {
        "recent_return_missing",
        "lookback_return_missing",
        "recent_direction_mismatch",
        "lookback_direction_mismatch",
        "large_cross_required",
    }
    if (
        trend_confirmation_status == "weak_recent_return"
        and weak_momentum_stabilization_status != "allowed"
    ):
        trend_downgrade_statuses.add("weak_recent_return")
    elif trend_confirmation_status == "weak_recent_return":
        bonus_reasons.append("weak_momentum_stabilized")
    if trend_confirmation_status in trend_downgrade_statuses:
        confidence = min(confidence, SCORE_DOWNGRADE_CONFLICT_CONFIDENCE)
        downgrade_reasons.append(f"trend_{trend_confirmation_status}")
    if mini_exhaustion_status == "flagged":
        confidence = min(confidence, SCORE_DOWNGRADE_CONFLICT_CONFIDENCE)
        downgrade_reasons.append("mini_exhaustion")
    if exhaustion_status == "progression_caution":
        confidence = min(confidence, SCORE_DOWNGRADE_CONFLICT_CONFIDENCE)
        downgrade_reasons.append("exhaustion_progression_caution")
    if trend_confirmation_status == "confirmed" and not downgrade_reasons:
        confidence = min(
            SCORE_MAX_CONFIDENCE,
            confidence + SCORE_BONUS_CONFIRMED_TREND_CONFIDENCE,
        )
        bonus_reasons.append("confirmed_trend")
    return (
        confidence,
        tuple(dict.fromkeys(downgrade_reasons)),
        tuple(dict.fromkeys(bonus_reasons)),
    )


def _direction_sign(direction: str) -> int:
    if direction == "up":
        return 1
    if direction == "down":
        return -1
    return 0


def _sign(value: Decimal) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _optional_str_metadata(
    metadata: Mapping[str, object],
    key: str,
) -> str | None:
    value = metadata.get(key)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _optional_decimal_metadata(
    metadata: Mapping[str, object],
    key: str,
) -> Decimal | None:
    value = metadata.get(key)
    if value is None:
        return None
    return Decimal(str(value))
