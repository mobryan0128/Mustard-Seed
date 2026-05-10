"""Environment-backed settings for Kalshi API access."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path


DEMO_API_BASE_URL = "https://demo-api.kalshi.co/trade-api/v2"
PROD_API_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
DEMO_WS_URL = "wss://demo-api.kalshi.co/trade-api/ws/v2"
PROD_WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"
DEFAULT_CRYPTO_FEED_WS_URL = "wss://advanced-trade-ws.coinbase.com"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 10.0
DEFAULT_WS_MESSAGE_LIMIT = 25
DEFAULT_WS_RECEIVE_TIMEOUT_SECONDS = 30.0
DEFAULT_WS_MAX_RECONNECT_ATTEMPTS = 3
DEFAULT_WS_RECONNECT_INITIAL_DELAY_SECONDS = 1.0
DEFAULT_WS_RECONNECT_MAX_DELAY_SECONDS = 30.0
DEFAULT_CRYPTO_FEED_PRODUCTS = (
    "BTC-USD",
    "ETH-USD",
    "SOL-USD",
    "XRP-USD",
    "DOGE-USD",
    "BNB-USD",
    "HYPE-USD",
)
DEFAULT_CRYPTO_FEED_MESSAGE_LIMIT = 25
DEFAULT_CRYPTO_FEED_RECEIVE_TIMEOUT_SECONDS = 30.0
DEFAULT_CRYPTO_FEED_MAX_RECONNECT_ATTEMPTS = 3
DEFAULT_CRYPTO_FEED_RECONNECT_INITIAL_DELAY_SECONDS = 1.0
DEFAULT_CRYPTO_FEED_RECONNECT_MAX_DELAY_SECONDS = 30.0
DEFAULT_LOG_DIRECTORY = Path("logs")
DEFAULT_REPLAY_DIRECTORY = Path("replay")
DEFAULT_TIME_SYNC_MAX_DRIFT_MS = 1500
DEFAULT_LATENCY_DIAGNOSTICS_ENABLED = False
DEFAULT_LATENCY_DIAGNOSTICS_SAMPLE_INTERVAL_MS = 1000
DEFAULT_LATENCY_DIAGNOSTICS_MIN_SPOT_MOVE_BPS = Decimal("5")
DEFAULT_LATENCY_DIAGNOSTICS_MAX_DEPTH_LEVELS = 3
DEFAULT_BIAS_LOOKBACK_SECONDS = 1800
DEFAULT_BIAS_RECENT_WINDOW_SECONDS = 60
DEFAULT_BIAS_MIN_SAMPLES = 20
DEFAULT_BIAS_STALE_DATA_SECONDS = 15
DEFAULT_BIAS_CHOP_THRESHOLD_BPS = 10
DEFAULT_BIAS_IMPULSE_MIN_ABS_BPS = Decimal("15")
DEFAULT_SIMULATION_ENABLED = True
DEFAULT_SIMULATION_MAX_NEW_POSITIONS_PER_EVALUATION = 1
DEFAULT_SIMULATION_POSITION_ID_PREFIX = "sim"
DEFAULT_SIMULATION_EXIT_ENABLED = True
DEFAULT_SIMULATION_ALLOW_SAME_PASS_REENTRY = False
DEFAULT_RISK_ACCOUNT_BALANCE_DOLLARS = Decimal("100")
DEFAULT_RISK_MIN_PERCENT_PER_TRADE = Decimal("0.01")
DEFAULT_RISK_MAX_PERCENT_PER_TRADE = Decimal("0.05")
DEFAULT_RISK_MIN_STAKE_DOLLARS = Decimal("1")
DEFAULT_RISK_MAX_STAKE_DOLLARS = Decimal("5")
DEFAULT_RISK_MAX_OPEN_POSITIONS = 20
DEFAULT_RISK_MAX_TOTAL_EXPOSURE_DOLLARS = Decimal("10")
DEFAULT_RISK_DAILY_LOSS_LIMIT_DOLLARS = Decimal("10")
DEFAULT_RISK_KILL_SWITCH_ACTIVE = False
DEFAULT_LIVE_VALIDATION_ENABLED = False
DEFAULT_LIVE_VALIDATION_ENV = "prod"
DEFAULT_LIVE_VALIDATION_COUNT = 1
DEFAULT_LIVE_VALIDATION_TIME_IN_FORCE = "immediate_or_cancel"
DEFAULT_LIVE_VALIDATION_POLL_ATTEMPTS = 5
DEFAULT_LIVE_VALIDATION_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_LIVE_VALIDATION_CLIENT_ORDER_ID_PREFIX = "live-smoke"
DEFAULT_LIVE_TRADING_ENABLED = False
DEFAULT_LIVE_KILL_SWITCH_ACTIVE = False
DEFAULT_LIVE_RUNNER_EXECUTION_ENABLED = False
DEFAULT_LIVE_MAX_CONTRACT_COUNT = 1000
DEFAULT_LIVE_PROFIT_CAPTURE_ENABLED = False
DEFAULT_LIVE_PROFIT_CAPTURE_PRICE = Decimal("0.99")
DEFAULT_LIVE_TRAILING_STOP_ENABLED = False
DEFAULT_LIVE_TRAILING_STOP_DISTANCE = Decimal("0.05")
DEFAULT_LIVE_ENTRY_END_WINDOW_ONLY = False
DEFAULT_LIVE_ENTRY_END_WINDOW_MINUTES = 5
DEFAULT_LIVE_ENTRY_MIN_REMAINING_SECONDS = 0
DEFAULT_LIVE_ENTRY_SEGMENT_PACING_ENABLED = False
DEFAULT_LIVE_ENTRY_SEGMENT_MAX_10_TO_5 = 1
DEFAULT_LIVE_ENTRY_SEGMENT_MAX_5_TO_3 = 1
DEFAULT_LIVE_ENTRY_SEGMENT_MAX_3_TO_1 = 1
DEFAULT_LIVE_ENTRY_SEGMENT_MAX_FINAL_1 = 1
DEFAULT_LIVE_FAST_SCAN_ENABLED = False
DEFAULT_LIVE_FAST_SCAN_INTERVAL_SECONDS = 2.0
DEFAULT_LIVE_FAST_SCAN_COOLDOWN_SECONDS = 5.0
DEFAULT_LIVE_REVERSAL_CROSS_HOLD_ENABLED = True
DEFAULT_LIVE_REVERSAL_CROSS_HOLD_SECONDS = 60
DEFAULT_LIVE_MID_PRICE_TIGHTENING_ENABLED = True
DEFAULT_LIVE_MID_PRICE_MIN = Decimal("0.50")
DEFAULT_LIVE_MID_PRICE_MAX = Decimal("0.70")
DEFAULT_LIVE_MAX_OPEN_POSITIONS_PER_PRODUCT = 2
DEFAULT_LIVE_MAX_ENTRIES_PER_PRODUCT_PER_SESSION = 2
DEFAULT_LIVE_COMPOSITE_QUALITY_FILTER_ENABLED = True
DEFAULT_LIVE_COMPOSITE_MAX_ENTRY_PRICE = Decimal("0.70")
DEFAULT_LIVE_COMPOSITE_LOW_PRICE_MAX = Decimal("0.30")
DEFAULT_LIVE_COMPOSITE_ALLOWED_SEGMENTS = ("10_to_5", "5_to_3")
DEFAULT_LIVE_COMPOSITE_REQUIRE_TREND = True
DEFAULT_LIVE_COMPOSITE_REQUIRE_ITM = True
DEFAULT_LIVE_COMPOSITE_BLOCK_NEEDS_CROSS = True
DEFAULT_LIVE_REVERSAL_MAX_ENTRY_PRICE = Decimal("0.10")
DEFAULT_LIVE_BLOCK_NEEDS_CROSS = True
DEFAULT_LIVE_MAX_REQUIRED_BPS_PER_MINUTE = Decimal("0.25")
DEFAULT_LIVE_OUTSIDE_END_WINDOW_EXCEPTION_ENABLED = False
DEFAULT_LIVE_OUTSIDE_END_WINDOW_MAX_PRICE = Decimal("0.30")
DEFAULT_LIVE_EV_FILTER_ENABLED = True
DEFAULT_LIVE_MIN_EXPECTED_VALUE = Decimal("0.00")
DEFAULT_LIVE_EV_PRICE_MAX_ITM_NO_CROSS = Decimal("0.70")
DEFAULT_LIVE_EV_PRICE_MAX_NEEDS_CROSS = Decimal("0.30")
DEFAULT_LIVE_EV_REQUIRED_BPS_MAX = Decimal("0.25")
DEFAULT_LIVE_EV_ALLOWED_SEGMENTS = ("10_to_5", "5_to_3")
DEFAULT_LIVE_EV_CONSERVATIVE_ALLOWED_SEGMENTS = (
    "10_to_5",
    "5_to_3",
    "3_to_1",
)
DEFAULT_LIVE_EV_ALLOW_REVERSAL = False
DEFAULT_LIVE_EV_CANDIDATE_A_WIN_PROBABILITY = Decimal("0.87")
DEFAULT_LIVE_EV_CANDIDATE_B_WIN_PROBABILITY = Decimal("0.92")
DEFAULT_LIVE_PRODUCT_BLOCKLIST: tuple[str, ...] = ()
DEFAULT_LIVE_CONDITIONAL_HIGH_PRICE_PASS_ENABLED = True
DEFAULT_LIVE_CONDITIONAL_MAX_PREMIUM_OVER_MIDPOINT = Decimal("0.08")
DEFAULT_LIVE_CONDITIONAL_MAX_SPREAD = Decimal("0.15")
DEFAULT_LIVE_CONDITIONAL_MAX_SCANNER_PREMIUM = Decimal("0.12")
DEFAULT_LIVE_CONDITIONAL_ALLOW_EXTREME_ASYMMETRY = False
DEFAULT_LIVE_CONDITIONAL_ALLOW_HIGH_PRICE_CEILING_BYPASS = False
DEFAULT_LIVE_CONDITIONAL_HIGH_PRICE_CEILING_MAX = Decimal("0.70")
DEFAULT_LIVE_EV_TIMING_BYPASS_ENABLED = True
DEFAULT_LIVE_EV_EXTRA_ENTRIES_PER_PRODUCT_PER_SESSION = 0
DEFAULT_LIVE_EV_EXTRA_OPEN_POSITIONS_PER_PRODUCT = 0
DEFAULT_LIVE_QUIET_CONTINUATION_ENABLED = False
DEFAULT_LIVE_QUIET_CONTINUATION_MAX_RECENT_BPS = Decimal("6")
DEFAULT_LIVE_QUIET_CONTINUATION_MAX_3M_ABS_BPS = Decimal("12")
DEFAULT_LIVE_QUIET_CONTINUATION_MAX_5M_ABS_BPS = Decimal("20")
DEFAULT_LIVE_QUIET_CONTINUATION_MAX_5M_RANGE_BPS = Decimal("25")
DEFAULT_LIVE_QUIET_CONTINUATION_BLOCK_DECELERATION = True
DEFAULT_LIVE_QUIET_CONTINUATION_BLOCK_NEAR_EXTREME = True
DEFAULT_LIVE_QUIET_CONTINUATION_MIN_DISTANCE_FROM_EXTREME_BPS = Decimal("5")
DEFAULT_LIVE_EXHAUSTION_GUARD_ENABLED = True
DEFAULT_LIVE_EXHAUSTION_BURST_3M_BPS = Decimal("20")
DEFAULT_LIVE_EXHAUSTION_BURST_5M_BPS = Decimal("30")
DEFAULT_LIVE_EXHAUSTION_NEAR_EXTREME_BPS = Decimal("3")
DEFAULT_LIVE_EXHAUSTION_DECELERATION_RECENT_BPS = Decimal("8")
DEFAULT_LIVE_EXHAUSTION_STRICT_PRODUCTS = ("HYPE-USD", "ETH-USD", "XRP-USD")
DEFAULT_LIVE_EXHAUSTION_STRICT_BURST_3M_BPS = Decimal("15")
DEFAULT_LIVE_EARLY_MOMENTUM_ENABLED = True
DEFAULT_LIVE_EARLY_MOMENTUM_MIN_RECENT_BPS = Decimal("15")
DEFAULT_LIVE_EARLY_MOMENTUM_MAX_3M_BURST_BPS = Decimal("20")
DEFAULT_LIVE_EARLY_MOMENTUM_MAX_ENTRY_PRICE = Decimal("0.50")
DEFAULT_LIVE_EV_MAX_ACTUAL_COST = Decimal("0.70")
DEFAULT_LIVE_EV_MIN_REWARD_DOLLARS = Decimal("0.30")
DEFAULT_LIVE_EV_REQUIRE_POSITIVE_COST_EXPECTED_VALUE = True
DEFAULT_LIVE_EV_EXHAUSTION_BLOCK_ENABLED = True
DEFAULT_LIVE_CANDIDATE_FUNNEL_DIAGNOSTICS_ENABLED = False
DEFAULT_RUNNER_ENABLED = True
DEFAULT_RUNNER_LOOP_INTERVAL_SECONDS = 5.0
DEFAULT_RUNNER_STATUS_LOG_EVERY_N_CYCLES = 1
DEFAULT_RUNNER_FAIL_FAST_ON_STARTUP = True
DEFAULT_AUTO_MARKET_DISCOVERY_ENABLED = True
DEFAULT_CRYPTO_MARKET_SERIES = {
    "BTC-USD": ("KXBTC15M", "KXBTC30M"),
    "ETH-USD": ("KXETH15M", "KXETH30M"),
    "SOL-USD": ("KXSOL15M",),
    "XRP-USD": ("KXXRP15M",),
    "DOGE-USD": ("KXDOGE15M",),
    "BNB-USD": ("KXBNB15M",),
    "HYPE-USD": ("KXHYPE15M",),
}
DEFAULT_MARKET_DISCOVERY_REFRESH_CYCLES = 12


class SettingsError(ValueError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class KalshiSettings:
    """Validated Kalshi auth, REST, and WebSocket settings."""

    env: str
    api_base_url: str
    ws_url: str
    api_key_id: str
    private_key_pem: str | None
    private_key_path: Path | None
    private_key_passphrase: str | None
    request_timeout_seconds: float
    ws_market_tickers: tuple[str, ...]
    ws_message_limit: int
    ws_receive_timeout_seconds: float
    ws_max_reconnect_attempts: int
    ws_reconnect_initial_delay_seconds: float
    ws_reconnect_max_delay_seconds: float
    crypto_feed_ws_url: str
    crypto_feed_products: tuple[str, ...]
    crypto_feed_message_limit: int
    crypto_feed_receive_timeout_seconds: float
    crypto_feed_max_reconnect_attempts: int
    crypto_feed_reconnect_initial_delay_seconds: float
    crypto_feed_reconnect_max_delay_seconds: float
    log_directory: Path
    log_jsonl_enabled: bool
    replay_directory: Path
    replay_write_enabled: bool
    time_sync_max_drift_ms: int
    time_sync_log_results: bool
    latency_diagnostics_enabled: bool
    latency_diagnostics_sample_interval_ms: int
    latency_diagnostics_min_spot_move_bps: Decimal
    latency_diagnostics_max_depth_levels: int
    bias_products: tuple[str, ...]
    bias_lookback_seconds: int
    bias_recent_window_seconds: int
    bias_min_samples: int
    bias_stale_data_seconds: int
    bias_chop_threshold_bps: int
    bias_impulse_min_abs_bps: Decimal
    contract_scanner_product_markets: dict[str, tuple[str, ...]]
    auto_market_discovery_enabled: bool
    crypto_market_series: dict[str, tuple[str, ...]]
    market_discovery_refresh_cycles: int
    simulation_enabled: bool
    simulation_max_new_positions_per_evaluation: int
    simulation_position_id_prefix: str
    simulation_exit_enabled: bool
    simulation_allow_same_pass_reentry: bool
    risk_account_balance_dollars: Decimal
    risk_min_percent_per_trade: Decimal
    risk_max_percent_per_trade: Decimal
    risk_min_stake_dollars: Decimal
    risk_max_stake_dollars: Decimal
    risk_max_open_positions: int
    risk_max_total_exposure_dollars: Decimal
    risk_daily_loss_limit_dollars: Decimal
    risk_kill_switch_active: bool
    live_validation_enabled: bool
    live_validation_env: str
    live_validation_ticker: str | None
    live_validation_action: str | None
    live_validation_side: str | None
    live_validation_count: int
    live_validation_price_dollars: Decimal | None
    live_validation_time_in_force: str
    live_validation_poll_attempts: int
    live_validation_poll_interval_seconds: float
    live_validation_client_order_id_prefix: str
    live_trading_enabled: bool
    live_kill_switch_active: bool
    live_runner_execution_enabled: bool
    live_max_exposure_dollars: Decimal
    live_min_stake_dollars: Decimal
    live_max_stake_dollars: Decimal
    live_max_open_positions: int
    live_max_contract_count: int
    live_profit_capture_enabled: bool
    live_profit_capture_price: Decimal
    live_trailing_stop_enabled: bool
    live_trailing_stop_distance: Decimal
    live_entry_end_window_only: bool
    live_entry_end_window_minutes: int
    live_entry_min_remaining_seconds: int
    live_entry_segment_pacing_enabled: bool
    live_entry_segment_max_10_to_5: int
    live_entry_segment_max_5_to_3: int
    live_entry_segment_max_3_to_1: int
    live_entry_segment_max_final_1: int
    live_fast_scan_enabled: bool
    live_fast_scan_interval_seconds: float
    live_fast_scan_cooldown_seconds: float
    live_reversal_cross_hold_enabled: bool
    live_reversal_cross_hold_seconds: int
    live_mid_price_tightening_enabled: bool
    live_mid_price_min: Decimal
    live_mid_price_max: Decimal
    live_max_open_positions_per_product: int
    live_max_entries_per_product_per_session: int
    live_composite_quality_filter_enabled: bool
    live_composite_max_entry_price: Decimal
    live_composite_low_price_max: Decimal
    live_composite_allowed_segments: tuple[str, ...]
    live_composite_require_trend: bool
    live_composite_require_itm: bool
    live_composite_block_needs_cross: bool
    live_reversal_max_entry_price: Decimal
    live_block_needs_cross: bool
    live_max_required_bps_per_minute: Decimal
    live_outside_end_window_exception_enabled: bool
    live_outside_end_window_max_price: Decimal
    live_ev_filter_enabled: bool
    live_min_expected_value: Decimal
    live_ev_price_max_itm_no_cross: Decimal
    live_ev_price_max_needs_cross: Decimal
    live_ev_required_bps_max: Decimal
    live_ev_allowed_segments: tuple[str, ...]
    live_ev_conservative_allowed_segments: tuple[str, ...]
    live_ev_allow_reversal: bool
    live_ev_candidate_a_win_probability: Decimal
    live_ev_candidate_b_win_probability: Decimal
    live_product_blocklist: tuple[str, ...]
    live_conditional_high_price_pass_enabled: bool
    live_conditional_max_premium_over_midpoint: Decimal
    live_conditional_max_spread: Decimal
    live_conditional_max_scanner_premium: Decimal
    live_conditional_allow_extreme_asymmetry: bool
    live_conditional_allow_high_price_ceiling_bypass: bool
    live_conditional_high_price_ceiling_max: Decimal
    live_ev_timing_bypass_enabled: bool
    live_ev_extra_entries_per_product_per_session: int
    live_ev_extra_open_positions_per_product: int
    live_quiet_continuation_enabled: bool
    live_quiet_continuation_max_recent_bps: Decimal
    live_quiet_continuation_max_3m_abs_bps: Decimal
    live_quiet_continuation_max_5m_abs_bps: Decimal
    live_quiet_continuation_max_5m_range_bps: Decimal
    live_quiet_continuation_block_deceleration: bool
    live_quiet_continuation_block_near_extreme: bool
    live_quiet_continuation_min_distance_from_extreme_bps: Decimal
    live_exhaustion_guard_enabled: bool
    live_exhaustion_burst_3m_bps: Decimal
    live_exhaustion_burst_5m_bps: Decimal
    live_exhaustion_near_extreme_bps: Decimal
    live_exhaustion_deceleration_recent_bps: Decimal
    live_exhaustion_strict_products: tuple[str, ...]
    live_exhaustion_strict_burst_3m_bps: Decimal
    live_early_momentum_enabled: bool
    live_early_momentum_min_recent_bps: Decimal
    live_early_momentum_max_3m_burst_bps: Decimal
    live_early_momentum_max_entry_price: Decimal
    live_ev_max_actual_cost: Decimal
    live_ev_min_reward_dollars: Decimal
    live_ev_require_positive_cost_expected_value: bool
    live_ev_exhaustion_block_enabled: bool
    live_candidate_funnel_diagnostics_enabled: bool
    runner_enabled: bool
    runner_loop_interval_seconds: float
    runner_status_log_every_n_cycles: int
    runner_fail_fast_on_startup: bool
    runner_max_cycles: int | None


def load_settings(env_file: str | Path = ".env") -> KalshiSettings:
    """Load settings from an optional .env file and OS environment."""

    file_values = _read_env_file(Path(env_file))
    values = _merge_env(file_values)

    kalshi_env = values.get("KALSHI_ENV", "demo").strip().lower()
    if kalshi_env not in {"demo", "prod"}:
        raise SettingsError("KALSHI_ENV must be either 'demo' or 'prod'.")

    api_base_url = values.get("KALSHI_API_BASE_URL") or _default_base_url(kalshi_env)
    api_base_url = api_base_url.rstrip("/")
    ws_url = values.get("KALSHI_WS_URL") or _default_ws_url(kalshi_env)
    ws_url = ws_url.rstrip("/")

    api_key_id = _required(values, "KALSHI_API_KEY_ID")
    private_key_pem = _optional(values, "KALSHI_PRIVATE_KEY_PEM")
    private_key_path_text = _optional(values, "KALSHI_PRIVATE_KEY_PATH")
    private_key_path = Path(private_key_path_text).expanduser() if private_key_path_text else None

    if private_key_pem is None and private_key_path is None:
        raise SettingsError(
            "Provide either KALSHI_PRIVATE_KEY_PEM or KALSHI_PRIVATE_KEY_PATH."
        )

    timeout_seconds = _parse_timeout(
        values.get("KALSHI_REQUEST_TIMEOUT_SECONDS"),
        DEFAULT_REQUEST_TIMEOUT_SECONDS,
    )
    ws_initial_delay_seconds = _parse_positive_float(
        values.get("KALSHI_WS_RECONNECT_INITIAL_DELAY_SECONDS"),
        DEFAULT_WS_RECONNECT_INITIAL_DELAY_SECONDS,
        "KALSHI_WS_RECONNECT_INITIAL_DELAY_SECONDS",
    )
    ws_max_delay_seconds = _parse_positive_float(
        values.get("KALSHI_WS_RECONNECT_MAX_DELAY_SECONDS"),
        DEFAULT_WS_RECONNECT_MAX_DELAY_SECONDS,
        "KALSHI_WS_RECONNECT_MAX_DELAY_SECONDS",
    )
    if ws_initial_delay_seconds > ws_max_delay_seconds:
        raise SettingsError(
            "KALSHI_WS_RECONNECT_INITIAL_DELAY_SECONDS must be less than or equal "
            "to KALSHI_WS_RECONNECT_MAX_DELAY_SECONDS."
        )
    crypto_feed_initial_delay_seconds = _parse_positive_float(
        values.get("CRYPTO_FEED_RECONNECT_INITIAL_DELAY_SECONDS"),
        DEFAULT_CRYPTO_FEED_RECONNECT_INITIAL_DELAY_SECONDS,
        "CRYPTO_FEED_RECONNECT_INITIAL_DELAY_SECONDS",
    )
    crypto_feed_max_delay_seconds = _parse_positive_float(
        values.get("CRYPTO_FEED_RECONNECT_MAX_DELAY_SECONDS"),
        DEFAULT_CRYPTO_FEED_RECONNECT_MAX_DELAY_SECONDS,
        "CRYPTO_FEED_RECONNECT_MAX_DELAY_SECONDS",
    )
    if crypto_feed_initial_delay_seconds > crypto_feed_max_delay_seconds:
        raise SettingsError(
            "CRYPTO_FEED_RECONNECT_INITIAL_DELAY_SECONDS must be less than or equal "
            "to CRYPTO_FEED_RECONNECT_MAX_DELAY_SECONDS."
        )
    crypto_feed_products = (
        _parse_csv(values.get("CRYPTO_FEED_PRODUCTS")) or DEFAULT_CRYPTO_FEED_PRODUCTS
    )
    crypto_feed_ws_url = (
        values.get("CRYPTO_FEED_WS_URL") or DEFAULT_CRYPTO_FEED_WS_URL
    ).rstrip("/")
    log_directory = _parse_path(values.get("LOG_DIRECTORY"), DEFAULT_LOG_DIRECTORY)
    replay_directory = _parse_path(values.get("REPLAY_DIRECTORY"), DEFAULT_REPLAY_DIRECTORY)
    bias_products = _parse_csv(values.get("BIAS_PRODUCTS")) or crypto_feed_products
    bias_lookback_seconds = _parse_positive_int(
        values.get("BIAS_LOOKBACK_SECONDS"),
        DEFAULT_BIAS_LOOKBACK_SECONDS,
        "BIAS_LOOKBACK_SECONDS",
    )
    bias_recent_window_seconds = _parse_positive_int(
        values.get("BIAS_RECENT_WINDOW_SECONDS"),
        DEFAULT_BIAS_RECENT_WINDOW_SECONDS,
        "BIAS_RECENT_WINDOW_SECONDS",
    )
    bias_impulse_min_abs_bps = _parse_positive_decimal(
        values.get("BIAS_IMPULSE_MIN_ABS_BPS"),
        DEFAULT_BIAS_IMPULSE_MIN_ABS_BPS,
        "BIAS_IMPULSE_MIN_ABS_BPS",
    )
    if bias_recent_window_seconds > bias_lookback_seconds:
        raise SettingsError(
            "BIAS_RECENT_WINDOW_SECONDS must be less than or equal to "
            "BIAS_LOOKBACK_SECONDS."
        )
    contract_scanner_product_markets = _parse_product_markets_json(
        values.get("CONTRACT_SCANNER_PRODUCT_MARKETS_JSON")
    )
    auto_market_discovery_enabled = _parse_bool(
        values.get("KALSHI_AUTO_MARKET_DISCOVERY_ENABLED"),
        DEFAULT_AUTO_MARKET_DISCOVERY_ENABLED,
        "KALSHI_AUTO_MARKET_DISCOVERY_ENABLED",
    )
    crypto_market_series = _parse_product_series_json(
        values.get("KALSHI_CRYPTO_MARKET_SERIES_JSON")
    ) or {
        product_id: tuple(series_tickers)
        for product_id, series_tickers in DEFAULT_CRYPTO_MARKET_SERIES.items()
    }
    market_discovery_refresh_cycles = _parse_positive_int(
        values.get("KALSHI_MARKET_DISCOVERY_REFRESH_CYCLES"),
        DEFAULT_MARKET_DISCOVERY_REFRESH_CYCLES,
        "KALSHI_MARKET_DISCOVERY_REFRESH_CYCLES",
    )
    simulation_position_id_prefix = (
        _optional(values, "SIMULATION_POSITION_ID_PREFIX")
        or DEFAULT_SIMULATION_POSITION_ID_PREFIX
    )
    risk_account_balance_dollars = _parse_positive_decimal(
        values.get("RISK_ACCOUNT_BALANCE_DOLLARS"),
        DEFAULT_RISK_ACCOUNT_BALANCE_DOLLARS,
        "RISK_ACCOUNT_BALANCE_DOLLARS",
    )
    risk_min_percent_per_trade = _parse_positive_decimal(
        values.get("RISK_MIN_PERCENT_PER_TRADE"),
        DEFAULT_RISK_MIN_PERCENT_PER_TRADE,
        "RISK_MIN_PERCENT_PER_TRADE",
    )
    risk_max_percent_per_trade = _parse_positive_decimal(
        values.get("RISK_MAX_PERCENT_PER_TRADE"),
        DEFAULT_RISK_MAX_PERCENT_PER_TRADE,
        "RISK_MAX_PERCENT_PER_TRADE",
    )
    if risk_min_percent_per_trade > risk_max_percent_per_trade:
        raise SettingsError(
            "RISK_MIN_PERCENT_PER_TRADE must be less than or equal to "
            "RISK_MAX_PERCENT_PER_TRADE."
        )
    risk_min_stake_dollars = _parse_positive_decimal(
        values.get("RISK_MIN_STAKE_DOLLARS"),
        DEFAULT_RISK_MIN_STAKE_DOLLARS,
        "RISK_MIN_STAKE_DOLLARS",
    )
    risk_max_stake_dollars = _parse_positive_decimal(
        values.get("RISK_MAX_STAKE_DOLLARS"),
        DEFAULT_RISK_MAX_STAKE_DOLLARS,
        "RISK_MAX_STAKE_DOLLARS",
    )
    if risk_min_stake_dollars > risk_max_stake_dollars:
        raise SettingsError(
            "RISK_MIN_STAKE_DOLLARS must be less than or equal to "
            "RISK_MAX_STAKE_DOLLARS."
        )
    risk_max_open_positions = _parse_positive_int(
        values.get("RISK_MAX_OPEN_POSITIONS"),
        DEFAULT_RISK_MAX_OPEN_POSITIONS,
        "RISK_MAX_OPEN_POSITIONS",
    )
    risk_max_total_exposure_dollars = _parse_positive_decimal(
        values.get("RISK_MAX_TOTAL_EXPOSURE_DOLLARS"),
        DEFAULT_RISK_MAX_TOTAL_EXPOSURE_DOLLARS,
        "RISK_MAX_TOTAL_EXPOSURE_DOLLARS",
    )
    risk_daily_loss_limit_dollars = _parse_positive_decimal(
        values.get("RISK_DAILY_LOSS_LIMIT_DOLLARS"),
        DEFAULT_RISK_DAILY_LOSS_LIMIT_DOLLARS,
        "RISK_DAILY_LOSS_LIMIT_DOLLARS",
    )
    risk_kill_switch_active = _parse_bool(
        values.get("RISK_KILL_SWITCH_ACTIVE"),
        DEFAULT_RISK_KILL_SWITCH_ACTIVE,
        "RISK_KILL_SWITCH_ACTIVE",
    )
    live_validation_enabled = _parse_bool(
        values.get("LIVE_VALIDATION_ENABLED"),
        DEFAULT_LIVE_VALIDATION_ENABLED,
        "LIVE_VALIDATION_ENABLED",
    )
    live_validation_env = (
        _optional(values, "LIVE_VALIDATION_ENV") or DEFAULT_LIVE_VALIDATION_ENV
    ).lower()
    if live_validation_env not in {"prod", "demo"}:
        raise SettingsError("LIVE_VALIDATION_ENV must be either 'prod' or 'demo'.")
    live_validation_ticker = _optional(values, "LIVE_VALIDATION_TICKER")
    live_validation_action = _optional(values, "LIVE_VALIDATION_ACTION")
    if live_validation_action is not None:
        live_validation_action = live_validation_action.lower()
    if live_validation_action not in {None, "buy", "sell"}:
        raise SettingsError("LIVE_VALIDATION_ACTION must be either 'buy' or 'sell'.")
    live_validation_side = _optional(values, "LIVE_VALIDATION_SIDE")
    if live_validation_side is not None:
        live_validation_side = live_validation_side.lower()
    if live_validation_side not in {None, "yes", "no"}:
        raise SettingsError("LIVE_VALIDATION_SIDE must be either 'yes' or 'no'.")
    live_validation_count = _parse_positive_int(
        values.get("LIVE_VALIDATION_COUNT"),
        DEFAULT_LIVE_VALIDATION_COUNT,
        "LIVE_VALIDATION_COUNT",
    )
    live_validation_price_dollars = _parse_price_dollars(
        values.get("LIVE_VALIDATION_PRICE_DOLLARS"),
        "LIVE_VALIDATION_PRICE_DOLLARS",
    )
    live_validation_poll_attempts = _parse_positive_int(
        values.get("LIVE_VALIDATION_POLL_ATTEMPTS"),
        DEFAULT_LIVE_VALIDATION_POLL_ATTEMPTS,
        "LIVE_VALIDATION_POLL_ATTEMPTS",
    )
    live_validation_poll_interval_seconds = _parse_positive_float(
        values.get("LIVE_VALIDATION_POLL_INTERVAL_SECONDS"),
        DEFAULT_LIVE_VALIDATION_POLL_INTERVAL_SECONDS,
        "LIVE_VALIDATION_POLL_INTERVAL_SECONDS",
    )
    live_validation_client_order_id_prefix = (
        _optional(values, "LIVE_VALIDATION_CLIENT_ORDER_ID_PREFIX")
        or DEFAULT_LIVE_VALIDATION_CLIENT_ORDER_ID_PREFIX
    )
    live_validation_time_in_force = DEFAULT_LIVE_VALIDATION_TIME_IN_FORCE
    live_trading_enabled = _parse_bool(
        values.get("LIVE_TRADING_ENABLED"),
        DEFAULT_LIVE_TRADING_ENABLED,
        "LIVE_TRADING_ENABLED",
    )
    live_kill_switch_active = _parse_bool(
        values.get("LIVE_KILL_SWITCH_ACTIVE"),
        DEFAULT_LIVE_KILL_SWITCH_ACTIVE,
        "LIVE_KILL_SWITCH_ACTIVE",
    )
    live_runner_execution_enabled = _parse_bool(
        values.get("LIVE_RUNNER_EXECUTION_ENABLED"),
        DEFAULT_LIVE_RUNNER_EXECUTION_ENABLED,
        "LIVE_RUNNER_EXECUTION_ENABLED",
    )
    live_max_exposure_dollars = _parse_positive_decimal(
        values.get("LIVE_MAX_EXPOSURE_DOLLARS"),
        risk_max_total_exposure_dollars,
        "LIVE_MAX_EXPOSURE_DOLLARS",
    )
    live_min_stake_dollars = _parse_positive_decimal(
        values.get("LIVE_MIN_STAKE_DOLLARS"),
        risk_min_stake_dollars,
        "LIVE_MIN_STAKE_DOLLARS",
    )
    live_max_stake_dollars = _parse_positive_decimal(
        values.get("LIVE_MAX_STAKE_DOLLARS"),
        risk_max_stake_dollars,
        "LIVE_MAX_STAKE_DOLLARS",
    )
    if live_min_stake_dollars > live_max_stake_dollars:
        raise SettingsError(
            "LIVE_MIN_STAKE_DOLLARS must be less than or equal to "
            "LIVE_MAX_STAKE_DOLLARS."
        )
    live_max_open_positions = _parse_positive_int(
        values.get("LIVE_MAX_OPEN_POSITIONS"),
        risk_max_open_positions,
        "LIVE_MAX_OPEN_POSITIONS",
    )
    live_max_contract_count = _parse_positive_int(
        values.get("LIVE_MAX_CONTRACT_COUNT"),
        DEFAULT_LIVE_MAX_CONTRACT_COUNT,
        "LIVE_MAX_CONTRACT_COUNT",
    )
    live_profit_capture_enabled = _parse_bool(
        values.get("LIVE_PROFIT_CAPTURE_ENABLED"),
        DEFAULT_LIVE_PROFIT_CAPTURE_ENABLED,
        "LIVE_PROFIT_CAPTURE_ENABLED",
    )
    live_profit_capture_price = _parse_price_dollars(
        values.get("LIVE_PROFIT_CAPTURE_PRICE"),
        "LIVE_PROFIT_CAPTURE_PRICE",
    ) or DEFAULT_LIVE_PROFIT_CAPTURE_PRICE
    live_trailing_stop_enabled = _parse_bool(
        values.get("LIVE_TRAILING_STOP_ENABLED"),
        DEFAULT_LIVE_TRAILING_STOP_ENABLED,
        "LIVE_TRAILING_STOP_ENABLED",
    )
    live_trailing_stop_distance = _parse_price_dollars(
        values.get("LIVE_TRAILING_STOP_DISTANCE"),
        "LIVE_TRAILING_STOP_DISTANCE",
    ) or DEFAULT_LIVE_TRAILING_STOP_DISTANCE
    live_entry_end_window_only = _parse_bool(
        values.get("LIVE_ENTRY_END_WINDOW_ONLY"),
        DEFAULT_LIVE_ENTRY_END_WINDOW_ONLY,
        "LIVE_ENTRY_END_WINDOW_ONLY",
    )
    live_entry_end_window_minutes = _parse_positive_int(
        values.get("LIVE_ENTRY_END_WINDOW_MINUTES"),
        DEFAULT_LIVE_ENTRY_END_WINDOW_MINUTES,
        "LIVE_ENTRY_END_WINDOW_MINUTES",
    )
    live_entry_min_remaining_seconds = _parse_non_negative_int(
        values.get("LIVE_ENTRY_MIN_REMAINING_SECONDS"),
        DEFAULT_LIVE_ENTRY_MIN_REMAINING_SECONDS,
        "LIVE_ENTRY_MIN_REMAINING_SECONDS",
    )
    live_entry_segment_pacing_enabled = _parse_bool(
        values.get("LIVE_ENTRY_SEGMENT_PACING_ENABLED"),
        DEFAULT_LIVE_ENTRY_SEGMENT_PACING_ENABLED,
        "LIVE_ENTRY_SEGMENT_PACING_ENABLED",
    )
    live_entry_segment_max_10_to_5 = _parse_non_negative_int(
        values.get("LIVE_ENTRY_SEGMENT_MAX_10_TO_5"),
        DEFAULT_LIVE_ENTRY_SEGMENT_MAX_10_TO_5,
        "LIVE_ENTRY_SEGMENT_MAX_10_TO_5",
    )
    live_entry_segment_max_5_to_3 = _parse_non_negative_int(
        values.get("LIVE_ENTRY_SEGMENT_MAX_5_TO_3"),
        DEFAULT_LIVE_ENTRY_SEGMENT_MAX_5_TO_3,
        "LIVE_ENTRY_SEGMENT_MAX_5_TO_3",
    )
    live_entry_segment_max_3_to_1 = _parse_non_negative_int(
        values.get("LIVE_ENTRY_SEGMENT_MAX_3_TO_1"),
        DEFAULT_LIVE_ENTRY_SEGMENT_MAX_3_TO_1,
        "LIVE_ENTRY_SEGMENT_MAX_3_TO_1",
    )
    live_entry_segment_max_final_1 = _parse_non_negative_int(
        values.get("LIVE_ENTRY_SEGMENT_MAX_FINAL_1"),
        DEFAULT_LIVE_ENTRY_SEGMENT_MAX_FINAL_1,
        "LIVE_ENTRY_SEGMENT_MAX_FINAL_1",
    )
    live_fast_scan_enabled = _parse_bool(
        values.get("LIVE_FAST_SCAN_ENABLED"),
        DEFAULT_LIVE_FAST_SCAN_ENABLED,
        "LIVE_FAST_SCAN_ENABLED",
    )
    live_fast_scan_interval_seconds = _parse_positive_float(
        values.get("LIVE_FAST_SCAN_INTERVAL_SECONDS"),
        DEFAULT_LIVE_FAST_SCAN_INTERVAL_SECONDS,
        "LIVE_FAST_SCAN_INTERVAL_SECONDS",
    )
    live_fast_scan_cooldown_seconds = _parse_positive_float(
        values.get("LIVE_FAST_SCAN_COOLDOWN_SECONDS"),
        DEFAULT_LIVE_FAST_SCAN_COOLDOWN_SECONDS,
        "LIVE_FAST_SCAN_COOLDOWN_SECONDS",
    )
    live_reversal_cross_hold_enabled = _parse_bool(
        values.get("LIVE_REVERSAL_CROSS_HOLD_ENABLED"),
        DEFAULT_LIVE_REVERSAL_CROSS_HOLD_ENABLED,
        "LIVE_REVERSAL_CROSS_HOLD_ENABLED",
    )
    live_reversal_cross_hold_seconds = _parse_positive_int(
        values.get("LIVE_REVERSAL_CROSS_HOLD_SECONDS"),
        DEFAULT_LIVE_REVERSAL_CROSS_HOLD_SECONDS,
        "LIVE_REVERSAL_CROSS_HOLD_SECONDS",
    )
    live_mid_price_tightening_enabled = _parse_bool(
        values.get("LIVE_MID_PRICE_TIGHTENING_ENABLED"),
        DEFAULT_LIVE_MID_PRICE_TIGHTENING_ENABLED,
        "LIVE_MID_PRICE_TIGHTENING_ENABLED",
    )
    live_mid_price_min = _parse_price_dollars(
        values.get("LIVE_MID_PRICE_MIN"),
        "LIVE_MID_PRICE_MIN",
    ) or DEFAULT_LIVE_MID_PRICE_MIN
    live_mid_price_max = _parse_price_dollars(
        values.get("LIVE_MID_PRICE_MAX"),
        "LIVE_MID_PRICE_MAX",
    ) or DEFAULT_LIVE_MID_PRICE_MAX
    if live_mid_price_min > live_mid_price_max:
        raise SettingsError(
            "LIVE_MID_PRICE_MIN must be less than or equal to LIVE_MID_PRICE_MAX."
        )
    live_max_open_positions_per_product = _parse_positive_int(
        values.get("LIVE_MAX_OPEN_POSITIONS_PER_PRODUCT"),
        DEFAULT_LIVE_MAX_OPEN_POSITIONS_PER_PRODUCT,
        "LIVE_MAX_OPEN_POSITIONS_PER_PRODUCT",
    )
    live_max_entries_per_product_per_session = _parse_positive_int(
        values.get("LIVE_MAX_ENTRIES_PER_PRODUCT_PER_SESSION"),
        DEFAULT_LIVE_MAX_ENTRIES_PER_PRODUCT_PER_SESSION,
        "LIVE_MAX_ENTRIES_PER_PRODUCT_PER_SESSION",
    )
    live_composite_quality_filter_enabled = _parse_bool(
        values.get("LIVE_COMPOSITE_QUALITY_FILTER_ENABLED"),
        DEFAULT_LIVE_COMPOSITE_QUALITY_FILTER_ENABLED,
        "LIVE_COMPOSITE_QUALITY_FILTER_ENABLED",
    )
    live_composite_max_entry_price = _parse_price_dollars(
        values.get("LIVE_COMPOSITE_MAX_ENTRY_PRICE"),
        "LIVE_COMPOSITE_MAX_ENTRY_PRICE",
    ) or DEFAULT_LIVE_COMPOSITE_MAX_ENTRY_PRICE
    live_composite_low_price_max = _parse_price_dollars(
        values.get("LIVE_COMPOSITE_LOW_PRICE_MAX"),
        "LIVE_COMPOSITE_LOW_PRICE_MAX",
    ) or DEFAULT_LIVE_COMPOSITE_LOW_PRICE_MAX
    if live_composite_low_price_max > live_composite_max_entry_price:
        raise SettingsError(
            "LIVE_COMPOSITE_LOW_PRICE_MAX must be less than or equal to "
            "LIVE_COMPOSITE_MAX_ENTRY_PRICE."
        )
    live_composite_allowed_segments = _parse_allowed_segments(
        values.get("LIVE_COMPOSITE_ALLOWED_SEGMENTS"),
        DEFAULT_LIVE_COMPOSITE_ALLOWED_SEGMENTS,
        "LIVE_COMPOSITE_ALLOWED_SEGMENTS",
    )
    live_composite_require_trend = _parse_bool(
        values.get("LIVE_COMPOSITE_REQUIRE_TREND"),
        DEFAULT_LIVE_COMPOSITE_REQUIRE_TREND,
        "LIVE_COMPOSITE_REQUIRE_TREND",
    )
    live_composite_require_itm = _parse_bool(
        values.get("LIVE_COMPOSITE_REQUIRE_ITM"),
        DEFAULT_LIVE_COMPOSITE_REQUIRE_ITM,
        "LIVE_COMPOSITE_REQUIRE_ITM",
    )
    live_composite_block_needs_cross = _parse_bool(
        values.get("LIVE_COMPOSITE_BLOCK_NEEDS_CROSS"),
        DEFAULT_LIVE_COMPOSITE_BLOCK_NEEDS_CROSS,
        "LIVE_COMPOSITE_BLOCK_NEEDS_CROSS",
    )
    live_reversal_max_entry_price = _parse_price_dollars(
        values.get("LIVE_REVERSAL_MAX_ENTRY_PRICE"),
        "LIVE_REVERSAL_MAX_ENTRY_PRICE",
    ) or DEFAULT_LIVE_REVERSAL_MAX_ENTRY_PRICE
    live_block_needs_cross = _parse_bool(
        values.get("LIVE_BLOCK_NEEDS_CROSS"),
        DEFAULT_LIVE_BLOCK_NEEDS_CROSS,
        "LIVE_BLOCK_NEEDS_CROSS",
    )
    live_max_required_bps_per_minute = _parse_positive_decimal(
        values.get("LIVE_MAX_REQUIRED_BPS_PER_MINUTE"),
        DEFAULT_LIVE_MAX_REQUIRED_BPS_PER_MINUTE,
        "LIVE_MAX_REQUIRED_BPS_PER_MINUTE",
    )
    live_outside_end_window_exception_enabled = _parse_bool(
        values.get("LIVE_OUTSIDE_END_WINDOW_EXCEPTION_ENABLED"),
        DEFAULT_LIVE_OUTSIDE_END_WINDOW_EXCEPTION_ENABLED,
        "LIVE_OUTSIDE_END_WINDOW_EXCEPTION_ENABLED",
    )
    live_outside_end_window_max_price = _parse_price_dollars(
        values.get("LIVE_OUTSIDE_END_WINDOW_MAX_PRICE"),
        "LIVE_OUTSIDE_END_WINDOW_MAX_PRICE",
    ) or DEFAULT_LIVE_OUTSIDE_END_WINDOW_MAX_PRICE
    live_ev_filter_enabled = _parse_bool(
        values.get("LIVE_EV_FILTER_ENABLED"),
        DEFAULT_LIVE_EV_FILTER_ENABLED,
        "LIVE_EV_FILTER_ENABLED",
    )
    live_min_expected_value = _parse_non_negative_decimal(
        values.get("LIVE_MIN_EXPECTED_VALUE"),
        DEFAULT_LIVE_MIN_EXPECTED_VALUE,
        "LIVE_MIN_EXPECTED_VALUE",
    )
    live_ev_price_max_itm_no_cross = _parse_price_dollars(
        values.get("LIVE_EV_PRICE_MAX_ITM_NO_CROSS"),
        "LIVE_EV_PRICE_MAX_ITM_NO_CROSS",
    ) or DEFAULT_LIVE_EV_PRICE_MAX_ITM_NO_CROSS
    live_ev_price_max_needs_cross = _parse_price_dollars(
        values.get("LIVE_EV_PRICE_MAX_NEEDS_CROSS"),
        "LIVE_EV_PRICE_MAX_NEEDS_CROSS",
    ) or DEFAULT_LIVE_EV_PRICE_MAX_NEEDS_CROSS
    live_ev_required_bps_max = _parse_positive_decimal(
        values.get("LIVE_EV_REQUIRED_BPS_MAX"),
        DEFAULT_LIVE_EV_REQUIRED_BPS_MAX,
        "LIVE_EV_REQUIRED_BPS_MAX",
    )
    live_ev_allowed_segments = _parse_allowed_segments(
        values.get("LIVE_EV_ALLOWED_SEGMENTS"),
        DEFAULT_LIVE_EV_ALLOWED_SEGMENTS,
        "LIVE_EV_ALLOWED_SEGMENTS",
    )
    live_ev_conservative_allowed_segments = _parse_allowed_segments(
        values.get("LIVE_EV_CONSERVATIVE_ALLOWED_SEGMENTS"),
        DEFAULT_LIVE_EV_CONSERVATIVE_ALLOWED_SEGMENTS,
        "LIVE_EV_CONSERVATIVE_ALLOWED_SEGMENTS",
    )
    live_ev_allow_reversal = _parse_bool(
        values.get("LIVE_EV_ALLOW_REVERSAL"),
        DEFAULT_LIVE_EV_ALLOW_REVERSAL,
        "LIVE_EV_ALLOW_REVERSAL",
    )
    live_ev_candidate_a_win_probability = _parse_probability(
        values.get("LIVE_EV_CANDIDATE_A_WIN_PROBABILITY"),
        DEFAULT_LIVE_EV_CANDIDATE_A_WIN_PROBABILITY,
        "LIVE_EV_CANDIDATE_A_WIN_PROBABILITY",
    )
    live_ev_candidate_b_win_probability = _parse_probability(
        values.get("LIVE_EV_CANDIDATE_B_WIN_PROBABILITY"),
        DEFAULT_LIVE_EV_CANDIDATE_B_WIN_PROBABILITY,
        "LIVE_EV_CANDIDATE_B_WIN_PROBABILITY",
    )
    live_product_blocklist = tuple(
        dict.fromkeys(item.upper() for item in _parse_csv(values.get("LIVE_PRODUCT_BLOCKLIST")))
    )
    live_conditional_high_price_pass_enabled = _parse_bool(
        values.get("LIVE_CONDITIONAL_HIGH_PRICE_PASS_ENABLED"),
        DEFAULT_LIVE_CONDITIONAL_HIGH_PRICE_PASS_ENABLED,
        "LIVE_CONDITIONAL_HIGH_PRICE_PASS_ENABLED",
    )
    live_conditional_max_premium_over_midpoint = _parse_price_dollars(
        values.get("LIVE_CONDITIONAL_MAX_PREMIUM_OVER_MIDPOINT"),
        "LIVE_CONDITIONAL_MAX_PREMIUM_OVER_MIDPOINT",
    ) or DEFAULT_LIVE_CONDITIONAL_MAX_PREMIUM_OVER_MIDPOINT
    live_conditional_max_spread = _parse_price_dollars(
        values.get("LIVE_CONDITIONAL_MAX_SPREAD"),
        "LIVE_CONDITIONAL_MAX_SPREAD",
    ) or DEFAULT_LIVE_CONDITIONAL_MAX_SPREAD
    live_conditional_max_scanner_premium = _parse_price_dollars(
        values.get("LIVE_CONDITIONAL_MAX_SCANNER_PREMIUM"),
        "LIVE_CONDITIONAL_MAX_SCANNER_PREMIUM",
    ) or DEFAULT_LIVE_CONDITIONAL_MAX_SCANNER_PREMIUM
    live_conditional_allow_extreme_asymmetry = _parse_bool(
        values.get("LIVE_CONDITIONAL_ALLOW_EXTREME_ASYMMETRY"),
        DEFAULT_LIVE_CONDITIONAL_ALLOW_EXTREME_ASYMMETRY,
        "LIVE_CONDITIONAL_ALLOW_EXTREME_ASYMMETRY",
    )
    live_conditional_allow_high_price_ceiling_bypass = _parse_bool(
        values.get("LIVE_CONDITIONAL_ALLOW_HIGH_PRICE_CEILING_BYPASS"),
        DEFAULT_LIVE_CONDITIONAL_ALLOW_HIGH_PRICE_CEILING_BYPASS,
        "LIVE_CONDITIONAL_ALLOW_HIGH_PRICE_CEILING_BYPASS",
    )
    live_conditional_high_price_ceiling_max = _parse_price_dollars(
        values.get("LIVE_CONDITIONAL_HIGH_PRICE_CEILING_MAX"),
        "LIVE_CONDITIONAL_HIGH_PRICE_CEILING_MAX",
    ) or DEFAULT_LIVE_CONDITIONAL_HIGH_PRICE_CEILING_MAX
    live_ev_timing_bypass_enabled = _parse_bool(
        values.get("LIVE_EV_TIMING_BYPASS_ENABLED"),
        DEFAULT_LIVE_EV_TIMING_BYPASS_ENABLED,
        "LIVE_EV_TIMING_BYPASS_ENABLED",
    )
    live_ev_extra_entries_per_product_per_session = _parse_non_negative_int(
        values.get("LIVE_EV_EXTRA_ENTRIES_PER_PRODUCT_PER_SESSION"),
        DEFAULT_LIVE_EV_EXTRA_ENTRIES_PER_PRODUCT_PER_SESSION,
        "LIVE_EV_EXTRA_ENTRIES_PER_PRODUCT_PER_SESSION",
    )
    live_ev_extra_open_positions_per_product = _parse_non_negative_int(
        values.get("LIVE_EV_EXTRA_OPEN_POSITIONS_PER_PRODUCT"),
        DEFAULT_LIVE_EV_EXTRA_OPEN_POSITIONS_PER_PRODUCT,
        "LIVE_EV_EXTRA_OPEN_POSITIONS_PER_PRODUCT",
    )
    live_quiet_continuation_enabled = _parse_bool(
        values.get("LIVE_QUIET_CONTINUATION_ENABLED"),
        DEFAULT_LIVE_QUIET_CONTINUATION_ENABLED,
        "LIVE_QUIET_CONTINUATION_ENABLED",
    )
    live_quiet_continuation_max_recent_bps = _parse_positive_decimal(
        values.get("LIVE_QUIET_CONTINUATION_MAX_RECENT_BPS"),
        DEFAULT_LIVE_QUIET_CONTINUATION_MAX_RECENT_BPS,
        "LIVE_QUIET_CONTINUATION_MAX_RECENT_BPS",
    )
    live_quiet_continuation_max_3m_abs_bps = _parse_positive_decimal(
        values.get("LIVE_QUIET_CONTINUATION_MAX_3M_ABS_BPS"),
        DEFAULT_LIVE_QUIET_CONTINUATION_MAX_3M_ABS_BPS,
        "LIVE_QUIET_CONTINUATION_MAX_3M_ABS_BPS",
    )
    live_quiet_continuation_max_5m_abs_bps = _parse_positive_decimal(
        values.get("LIVE_QUIET_CONTINUATION_MAX_5M_ABS_BPS"),
        DEFAULT_LIVE_QUIET_CONTINUATION_MAX_5M_ABS_BPS,
        "LIVE_QUIET_CONTINUATION_MAX_5M_ABS_BPS",
    )
    live_quiet_continuation_max_5m_range_bps = _parse_positive_decimal(
        values.get("LIVE_QUIET_CONTINUATION_MAX_5M_RANGE_BPS"),
        DEFAULT_LIVE_QUIET_CONTINUATION_MAX_5M_RANGE_BPS,
        "LIVE_QUIET_CONTINUATION_MAX_5M_RANGE_BPS",
    )
    live_quiet_continuation_block_deceleration = _parse_bool(
        values.get("LIVE_QUIET_CONTINUATION_BLOCK_DECELERATION"),
        DEFAULT_LIVE_QUIET_CONTINUATION_BLOCK_DECELERATION,
        "LIVE_QUIET_CONTINUATION_BLOCK_DECELERATION",
    )
    live_quiet_continuation_block_near_extreme = _parse_bool(
        values.get("LIVE_QUIET_CONTINUATION_BLOCK_NEAR_EXTREME"),
        DEFAULT_LIVE_QUIET_CONTINUATION_BLOCK_NEAR_EXTREME,
        "LIVE_QUIET_CONTINUATION_BLOCK_NEAR_EXTREME",
    )
    live_quiet_continuation_min_distance_from_extreme_bps = _parse_positive_decimal(
        values.get("LIVE_QUIET_CONTINUATION_MIN_DISTANCE_FROM_EXTREME_BPS"),
        DEFAULT_LIVE_QUIET_CONTINUATION_MIN_DISTANCE_FROM_EXTREME_BPS,
        "LIVE_QUIET_CONTINUATION_MIN_DISTANCE_FROM_EXTREME_BPS",
    )
    live_exhaustion_guard_enabled = _parse_bool(
        values.get("LIVE_EXHAUSTION_GUARD_ENABLED"),
        DEFAULT_LIVE_EXHAUSTION_GUARD_ENABLED,
        "LIVE_EXHAUSTION_GUARD_ENABLED",
    )
    live_exhaustion_burst_3m_bps = _parse_positive_decimal(
        values.get("LIVE_EXHAUSTION_BURST_3M_BPS"),
        DEFAULT_LIVE_EXHAUSTION_BURST_3M_BPS,
        "LIVE_EXHAUSTION_BURST_3M_BPS",
    )
    live_exhaustion_burst_5m_bps = _parse_positive_decimal(
        values.get("LIVE_EXHAUSTION_BURST_5M_BPS"),
        DEFAULT_LIVE_EXHAUSTION_BURST_5M_BPS,
        "LIVE_EXHAUSTION_BURST_5M_BPS",
    )
    live_exhaustion_near_extreme_bps = _parse_positive_decimal(
        values.get("LIVE_EXHAUSTION_NEAR_EXTREME_BPS"),
        DEFAULT_LIVE_EXHAUSTION_NEAR_EXTREME_BPS,
        "LIVE_EXHAUSTION_NEAR_EXTREME_BPS",
    )
    live_exhaustion_deceleration_recent_bps = _parse_positive_decimal(
        values.get("LIVE_EXHAUSTION_DECELERATION_RECENT_BPS"),
        DEFAULT_LIVE_EXHAUSTION_DECELERATION_RECENT_BPS,
        "LIVE_EXHAUSTION_DECELERATION_RECENT_BPS",
    )
    live_exhaustion_strict_products = tuple(
        dict.fromkeys(
            item.upper()
            for item in (
                _parse_csv(values.get("LIVE_EXHAUSTION_STRICT_PRODUCTS"))
                or DEFAULT_LIVE_EXHAUSTION_STRICT_PRODUCTS
            )
        )
    )
    live_exhaustion_strict_burst_3m_bps = _parse_positive_decimal(
        values.get("LIVE_EXHAUSTION_STRICT_BURST_3M_BPS"),
        DEFAULT_LIVE_EXHAUSTION_STRICT_BURST_3M_BPS,
        "LIVE_EXHAUSTION_STRICT_BURST_3M_BPS",
    )
    live_early_momentum_enabled = _parse_bool(
        values.get("LIVE_EARLY_MOMENTUM_ENABLED"),
        DEFAULT_LIVE_EARLY_MOMENTUM_ENABLED,
        "LIVE_EARLY_MOMENTUM_ENABLED",
    )
    live_early_momentum_min_recent_bps = _parse_positive_decimal(
        values.get("LIVE_EARLY_MOMENTUM_MIN_RECENT_BPS"),
        DEFAULT_LIVE_EARLY_MOMENTUM_MIN_RECENT_BPS,
        "LIVE_EARLY_MOMENTUM_MIN_RECENT_BPS",
    )
    live_early_momentum_max_3m_burst_bps = _parse_positive_decimal(
        values.get("LIVE_EARLY_MOMENTUM_MAX_3M_BURST_BPS"),
        DEFAULT_LIVE_EARLY_MOMENTUM_MAX_3M_BURST_BPS,
        "LIVE_EARLY_MOMENTUM_MAX_3M_BURST_BPS",
    )
    live_early_momentum_max_entry_price = _parse_price_dollars(
        values.get("LIVE_EARLY_MOMENTUM_MAX_ENTRY_PRICE"),
        "LIVE_EARLY_MOMENTUM_MAX_ENTRY_PRICE",
    ) or DEFAULT_LIVE_EARLY_MOMENTUM_MAX_ENTRY_PRICE
    live_ev_max_actual_cost = _parse_price_dollars(
        values.get("LIVE_EV_MAX_ACTUAL_COST"),
        "LIVE_EV_MAX_ACTUAL_COST",
    ) or DEFAULT_LIVE_EV_MAX_ACTUAL_COST
    live_ev_min_reward_dollars = _parse_price_dollars(
        values.get("LIVE_EV_MIN_REWARD_DOLLARS"),
        "LIVE_EV_MIN_REWARD_DOLLARS",
    ) or DEFAULT_LIVE_EV_MIN_REWARD_DOLLARS
    live_ev_require_positive_cost_expected_value = _parse_bool(
        values.get("LIVE_EV_REQUIRE_POSITIVE_COST_EXPECTED_VALUE"),
        DEFAULT_LIVE_EV_REQUIRE_POSITIVE_COST_EXPECTED_VALUE,
        "LIVE_EV_REQUIRE_POSITIVE_COST_EXPECTED_VALUE",
    )
    live_ev_exhaustion_block_enabled = _parse_bool(
        values.get("LIVE_EV_EXHAUSTION_BLOCK_ENABLED"),
        DEFAULT_LIVE_EV_EXHAUSTION_BLOCK_ENABLED,
        "LIVE_EV_EXHAUSTION_BLOCK_ENABLED",
    )
    live_candidate_funnel_diagnostics_enabled = _parse_bool(
        values.get("LIVE_CANDIDATE_FUNNEL_DIAGNOSTICS_ENABLED"),
        DEFAULT_LIVE_CANDIDATE_FUNNEL_DIAGNOSTICS_ENABLED,
        "LIVE_CANDIDATE_FUNNEL_DIAGNOSTICS_ENABLED",
    )
    runner_enabled = _parse_bool(
        values.get("RUNNER_ENABLED"),
        DEFAULT_RUNNER_ENABLED,
        "RUNNER_ENABLED",
    )
    runner_loop_interval_seconds = _parse_positive_float(
        values.get("RUNNER_LOOP_INTERVAL_SECONDS"),
        DEFAULT_RUNNER_LOOP_INTERVAL_SECONDS,
        "RUNNER_LOOP_INTERVAL_SECONDS",
    )
    runner_status_log_every_n_cycles = _parse_positive_int(
        values.get("RUNNER_STATUS_LOG_EVERY_N_CYCLES"),
        DEFAULT_RUNNER_STATUS_LOG_EVERY_N_CYCLES,
        "RUNNER_STATUS_LOG_EVERY_N_CYCLES",
    )
    runner_fail_fast_on_startup = _parse_bool(
        values.get("RUNNER_FAIL_FAST_ON_STARTUP"),
        DEFAULT_RUNNER_FAIL_FAST_ON_STARTUP,
        "RUNNER_FAIL_FAST_ON_STARTUP",
    )
    runner_max_cycles = _parse_optional_positive_int(
        values.get("RUNNER_MAX_CYCLES"),
        "RUNNER_MAX_CYCLES",
    )

    if live_validation_enabled:
        if kalshi_env != "prod":
            raise SettingsError(
                "KALSHI_ENV must be 'prod' when LIVE_VALIDATION_ENABLED is true."
            )
        if live_validation_env != "prod":
            raise SettingsError(
                "LIVE_VALIDATION_ENV must be 'prod' when LIVE_VALIDATION_ENABLED is true."
            )
        if live_validation_ticker is None:
            raise SettingsError(
                "LIVE_VALIDATION_TICKER is required when LIVE_VALIDATION_ENABLED is true."
            )
        if live_validation_action is None:
            raise SettingsError(
                "LIVE_VALIDATION_ACTION is required when LIVE_VALIDATION_ENABLED is true."
            )
        if live_validation_side is None:
            raise SettingsError(
                "LIVE_VALIDATION_SIDE is required when LIVE_VALIDATION_ENABLED is true."
            )
        if live_validation_price_dollars is None:
            raise SettingsError(
                "LIVE_VALIDATION_PRICE_DOLLARS is required when LIVE_VALIDATION_ENABLED is true."
            )
        if live_validation_count != 1:
            raise SettingsError("LIVE_VALIDATION_COUNT must be 1 for Phase 9.")

    return KalshiSettings(
        env=kalshi_env,
        api_base_url=api_base_url,
        ws_url=ws_url,
        api_key_id=api_key_id,
        private_key_pem=private_key_pem,
        private_key_path=private_key_path,
        private_key_passphrase=_optional(values, "KALSHI_PRIVATE_KEY_PASSPHRASE"),
        request_timeout_seconds=timeout_seconds,
        ws_market_tickers=_parse_csv(values.get("KALSHI_WS_MARKET_TICKERS")),
        ws_message_limit=_parse_positive_int(
            values.get("KALSHI_WS_MESSAGE_LIMIT"),
            DEFAULT_WS_MESSAGE_LIMIT,
            "KALSHI_WS_MESSAGE_LIMIT",
        ),
        ws_receive_timeout_seconds=_parse_positive_float(
            values.get("KALSHI_WS_RECEIVE_TIMEOUT_SECONDS"),
            DEFAULT_WS_RECEIVE_TIMEOUT_SECONDS,
            "KALSHI_WS_RECEIVE_TIMEOUT_SECONDS",
        ),
        ws_max_reconnect_attempts=_parse_non_negative_int(
            values.get("KALSHI_WS_MAX_RECONNECT_ATTEMPTS"),
            DEFAULT_WS_MAX_RECONNECT_ATTEMPTS,
            "KALSHI_WS_MAX_RECONNECT_ATTEMPTS",
        ),
        ws_reconnect_initial_delay_seconds=ws_initial_delay_seconds,
        ws_reconnect_max_delay_seconds=ws_max_delay_seconds,
        crypto_feed_ws_url=crypto_feed_ws_url,
        crypto_feed_products=crypto_feed_products,
        crypto_feed_message_limit=_parse_positive_int(
            values.get("CRYPTO_FEED_MESSAGE_LIMIT"),
            DEFAULT_CRYPTO_FEED_MESSAGE_LIMIT,
            "CRYPTO_FEED_MESSAGE_LIMIT",
        ),
        crypto_feed_receive_timeout_seconds=_parse_positive_float(
            values.get("CRYPTO_FEED_RECEIVE_TIMEOUT_SECONDS"),
            DEFAULT_CRYPTO_FEED_RECEIVE_TIMEOUT_SECONDS,
            "CRYPTO_FEED_RECEIVE_TIMEOUT_SECONDS",
        ),
        crypto_feed_max_reconnect_attempts=_parse_non_negative_int(
            values.get("CRYPTO_FEED_MAX_RECONNECT_ATTEMPTS"),
            DEFAULT_CRYPTO_FEED_MAX_RECONNECT_ATTEMPTS,
            "CRYPTO_FEED_MAX_RECONNECT_ATTEMPTS",
        ),
        crypto_feed_reconnect_initial_delay_seconds=crypto_feed_initial_delay_seconds,
        crypto_feed_reconnect_max_delay_seconds=crypto_feed_max_delay_seconds,
        log_directory=log_directory,
        log_jsonl_enabled=_parse_bool(
            values.get("LOG_JSONL_ENABLED"),
            True,
            "LOG_JSONL_ENABLED",
        ),
        replay_directory=replay_directory,
        replay_write_enabled=_parse_bool(
            values.get("REPLAY_WRITE_ENABLED"),
            True,
            "REPLAY_WRITE_ENABLED",
        ),
        time_sync_max_drift_ms=_parse_non_negative_int(
            values.get("TIME_SYNC_MAX_DRIFT_MS"),
            DEFAULT_TIME_SYNC_MAX_DRIFT_MS,
            "TIME_SYNC_MAX_DRIFT_MS",
        ),
        time_sync_log_results=_parse_bool(
            values.get("TIME_SYNC_LOG_RESULTS"),
            True,
            "TIME_SYNC_LOG_RESULTS",
        ),
        latency_diagnostics_enabled=_parse_bool(
            values.get("LATENCY_DIAGNOSTICS_ENABLED"),
            DEFAULT_LATENCY_DIAGNOSTICS_ENABLED,
            "LATENCY_DIAGNOSTICS_ENABLED",
        ),
        latency_diagnostics_sample_interval_ms=_parse_positive_int(
            values.get("LATENCY_DIAGNOSTICS_SAMPLE_INTERVAL_MS"),
            DEFAULT_LATENCY_DIAGNOSTICS_SAMPLE_INTERVAL_MS,
            "LATENCY_DIAGNOSTICS_SAMPLE_INTERVAL_MS",
        ),
        latency_diagnostics_min_spot_move_bps=_parse_positive_decimal(
            values.get("LATENCY_DIAGNOSTICS_MIN_SPOT_MOVE_BPS"),
            DEFAULT_LATENCY_DIAGNOSTICS_MIN_SPOT_MOVE_BPS,
            "LATENCY_DIAGNOSTICS_MIN_SPOT_MOVE_BPS",
        ),
        latency_diagnostics_max_depth_levels=_parse_positive_int(
            values.get("LATENCY_DIAGNOSTICS_MAX_DEPTH_LEVELS"),
            DEFAULT_LATENCY_DIAGNOSTICS_MAX_DEPTH_LEVELS,
            "LATENCY_DIAGNOSTICS_MAX_DEPTH_LEVELS",
        ),
        bias_products=bias_products,
        bias_lookback_seconds=bias_lookback_seconds,
        bias_recent_window_seconds=bias_recent_window_seconds,
        bias_min_samples=_parse_positive_int(
            values.get("BIAS_MIN_SAMPLES"),
            DEFAULT_BIAS_MIN_SAMPLES,
            "BIAS_MIN_SAMPLES",
        ),
        bias_stale_data_seconds=_parse_positive_int(
            values.get("BIAS_STALE_DATA_SECONDS"),
            DEFAULT_BIAS_STALE_DATA_SECONDS,
            "BIAS_STALE_DATA_SECONDS",
        ),
        bias_chop_threshold_bps=_parse_positive_int(
            values.get("BIAS_CHOP_THRESHOLD_BPS"),
            DEFAULT_BIAS_CHOP_THRESHOLD_BPS,
            "BIAS_CHOP_THRESHOLD_BPS",
        ),
        bias_impulse_min_abs_bps=bias_impulse_min_abs_bps,
        contract_scanner_product_markets=contract_scanner_product_markets,
        auto_market_discovery_enabled=auto_market_discovery_enabled,
        crypto_market_series=crypto_market_series,
        market_discovery_refresh_cycles=market_discovery_refresh_cycles,
        simulation_enabled=_parse_bool(
            values.get("SIMULATION_ENABLED"),
            DEFAULT_SIMULATION_ENABLED,
            "SIMULATION_ENABLED",
        ),
        simulation_max_new_positions_per_evaluation=_parse_positive_int(
            values.get("SIMULATION_MAX_NEW_POSITIONS_PER_EVALUATION"),
            DEFAULT_SIMULATION_MAX_NEW_POSITIONS_PER_EVALUATION,
            "SIMULATION_MAX_NEW_POSITIONS_PER_EVALUATION",
        ),
        simulation_position_id_prefix=simulation_position_id_prefix,
        simulation_exit_enabled=_parse_bool(
            values.get("SIMULATION_EXIT_ENABLED"),
            DEFAULT_SIMULATION_EXIT_ENABLED,
            "SIMULATION_EXIT_ENABLED",
        ),
        simulation_allow_same_pass_reentry=_parse_bool(
            values.get("SIMULATION_ALLOW_SAME_PASS_REENTRY"),
            DEFAULT_SIMULATION_ALLOW_SAME_PASS_REENTRY,
            "SIMULATION_ALLOW_SAME_PASS_REENTRY",
        ),
        risk_account_balance_dollars=risk_account_balance_dollars,
        risk_min_percent_per_trade=risk_min_percent_per_trade,
        risk_max_percent_per_trade=risk_max_percent_per_trade,
        risk_min_stake_dollars=risk_min_stake_dollars,
        risk_max_stake_dollars=risk_max_stake_dollars,
        risk_max_open_positions=risk_max_open_positions,
        risk_max_total_exposure_dollars=risk_max_total_exposure_dollars,
        risk_daily_loss_limit_dollars=risk_daily_loss_limit_dollars,
        risk_kill_switch_active=risk_kill_switch_active,
        live_validation_enabled=live_validation_enabled,
        live_validation_env=live_validation_env,
        live_validation_ticker=live_validation_ticker,
        live_validation_action=live_validation_action,
        live_validation_side=live_validation_side,
        live_validation_count=live_validation_count,
        live_validation_price_dollars=live_validation_price_dollars,
        live_validation_time_in_force=live_validation_time_in_force,
        live_validation_poll_attempts=live_validation_poll_attempts,
        live_validation_poll_interval_seconds=live_validation_poll_interval_seconds,
        live_validation_client_order_id_prefix=live_validation_client_order_id_prefix,
        live_trading_enabled=live_trading_enabled,
        live_kill_switch_active=live_kill_switch_active,
        live_runner_execution_enabled=live_runner_execution_enabled,
        live_max_exposure_dollars=live_max_exposure_dollars,
        live_min_stake_dollars=live_min_stake_dollars,
        live_max_stake_dollars=live_max_stake_dollars,
        live_max_open_positions=live_max_open_positions,
        live_max_contract_count=live_max_contract_count,
        live_profit_capture_enabled=live_profit_capture_enabled,
        live_profit_capture_price=live_profit_capture_price,
        live_trailing_stop_enabled=live_trailing_stop_enabled,
        live_trailing_stop_distance=live_trailing_stop_distance,
        live_entry_end_window_only=live_entry_end_window_only,
        live_entry_end_window_minutes=live_entry_end_window_minutes,
        live_entry_min_remaining_seconds=live_entry_min_remaining_seconds,
        live_entry_segment_pacing_enabled=live_entry_segment_pacing_enabled,
        live_entry_segment_max_10_to_5=live_entry_segment_max_10_to_5,
        live_entry_segment_max_5_to_3=live_entry_segment_max_5_to_3,
        live_entry_segment_max_3_to_1=live_entry_segment_max_3_to_1,
        live_entry_segment_max_final_1=live_entry_segment_max_final_1,
        live_fast_scan_enabled=live_fast_scan_enabled,
        live_fast_scan_interval_seconds=live_fast_scan_interval_seconds,
        live_fast_scan_cooldown_seconds=live_fast_scan_cooldown_seconds,
        live_reversal_cross_hold_enabled=live_reversal_cross_hold_enabled,
        live_reversal_cross_hold_seconds=live_reversal_cross_hold_seconds,
        live_mid_price_tightening_enabled=live_mid_price_tightening_enabled,
        live_mid_price_min=live_mid_price_min,
        live_mid_price_max=live_mid_price_max,
        live_max_open_positions_per_product=live_max_open_positions_per_product,
        live_max_entries_per_product_per_session=(
            live_max_entries_per_product_per_session
        ),
        live_composite_quality_filter_enabled=(
            live_composite_quality_filter_enabled
        ),
        live_composite_max_entry_price=live_composite_max_entry_price,
        live_composite_low_price_max=live_composite_low_price_max,
        live_composite_allowed_segments=live_composite_allowed_segments,
        live_composite_require_trend=live_composite_require_trend,
        live_composite_require_itm=live_composite_require_itm,
        live_composite_block_needs_cross=live_composite_block_needs_cross,
        live_reversal_max_entry_price=live_reversal_max_entry_price,
        live_block_needs_cross=live_block_needs_cross,
        live_max_required_bps_per_minute=live_max_required_bps_per_minute,
        live_outside_end_window_exception_enabled=(
            live_outside_end_window_exception_enabled
        ),
        live_outside_end_window_max_price=live_outside_end_window_max_price,
        live_ev_filter_enabled=live_ev_filter_enabled,
        live_min_expected_value=live_min_expected_value,
        live_ev_price_max_itm_no_cross=live_ev_price_max_itm_no_cross,
        live_ev_price_max_needs_cross=live_ev_price_max_needs_cross,
        live_ev_required_bps_max=live_ev_required_bps_max,
        live_ev_allowed_segments=live_ev_allowed_segments,
        live_ev_conservative_allowed_segments=(
            live_ev_conservative_allowed_segments
        ),
        live_ev_allow_reversal=live_ev_allow_reversal,
        live_ev_candidate_a_win_probability=(
            live_ev_candidate_a_win_probability
        ),
        live_ev_candidate_b_win_probability=(
            live_ev_candidate_b_win_probability
        ),
        live_product_blocklist=live_product_blocklist,
        live_conditional_high_price_pass_enabled=(
            live_conditional_high_price_pass_enabled
        ),
        live_conditional_max_premium_over_midpoint=(
            live_conditional_max_premium_over_midpoint
        ),
        live_conditional_max_spread=live_conditional_max_spread,
        live_conditional_max_scanner_premium=(
            live_conditional_max_scanner_premium
        ),
        live_conditional_allow_extreme_asymmetry=(
            live_conditional_allow_extreme_asymmetry
        ),
        live_conditional_allow_high_price_ceiling_bypass=(
            live_conditional_allow_high_price_ceiling_bypass
        ),
        live_conditional_high_price_ceiling_max=(
            live_conditional_high_price_ceiling_max
        ),
        live_ev_timing_bypass_enabled=live_ev_timing_bypass_enabled,
        live_ev_extra_entries_per_product_per_session=(
            live_ev_extra_entries_per_product_per_session
        ),
        live_ev_extra_open_positions_per_product=(
            live_ev_extra_open_positions_per_product
        ),
        live_quiet_continuation_enabled=live_quiet_continuation_enabled,
        live_quiet_continuation_max_recent_bps=(
            live_quiet_continuation_max_recent_bps
        ),
        live_quiet_continuation_max_3m_abs_bps=(
            live_quiet_continuation_max_3m_abs_bps
        ),
        live_quiet_continuation_max_5m_abs_bps=(
            live_quiet_continuation_max_5m_abs_bps
        ),
        live_quiet_continuation_max_5m_range_bps=(
            live_quiet_continuation_max_5m_range_bps
        ),
        live_quiet_continuation_block_deceleration=(
            live_quiet_continuation_block_deceleration
        ),
        live_quiet_continuation_block_near_extreme=(
            live_quiet_continuation_block_near_extreme
        ),
        live_quiet_continuation_min_distance_from_extreme_bps=(
            live_quiet_continuation_min_distance_from_extreme_bps
        ),
        live_exhaustion_guard_enabled=live_exhaustion_guard_enabled,
        live_exhaustion_burst_3m_bps=live_exhaustion_burst_3m_bps,
        live_exhaustion_burst_5m_bps=live_exhaustion_burst_5m_bps,
        live_exhaustion_near_extreme_bps=live_exhaustion_near_extreme_bps,
        live_exhaustion_deceleration_recent_bps=(
            live_exhaustion_deceleration_recent_bps
        ),
        live_exhaustion_strict_products=live_exhaustion_strict_products,
        live_exhaustion_strict_burst_3m_bps=(
            live_exhaustion_strict_burst_3m_bps
        ),
        live_early_momentum_enabled=live_early_momentum_enabled,
        live_early_momentum_min_recent_bps=live_early_momentum_min_recent_bps,
        live_early_momentum_max_3m_burst_bps=(
            live_early_momentum_max_3m_burst_bps
        ),
        live_early_momentum_max_entry_price=live_early_momentum_max_entry_price,
        live_ev_max_actual_cost=live_ev_max_actual_cost,
        live_ev_min_reward_dollars=live_ev_min_reward_dollars,
        live_ev_require_positive_cost_expected_value=(
            live_ev_require_positive_cost_expected_value
        ),
        live_ev_exhaustion_block_enabled=live_ev_exhaustion_block_enabled,
        live_candidate_funnel_diagnostics_enabled=(
            live_candidate_funnel_diagnostics_enabled
        ),
        runner_enabled=runner_enabled,
        runner_loop_interval_seconds=runner_loop_interval_seconds,
        runner_status_log_every_n_cycles=runner_status_log_every_n_cycles,
        runner_fail_fast_on_startup=runner_fail_fast_on_startup,
        runner_max_cycles=runner_max_cycles,
    )


def _default_base_url(kalshi_env: str) -> str:
    if kalshi_env == "prod":
        return PROD_API_BASE_URL
    return DEMO_API_BASE_URL


def _default_ws_url(kalshi_env: str) -> str:
    if kalshi_env == "prod":
        return PROD_WS_URL
    return DEMO_WS_URL


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            raise SettingsError(f"Invalid .env entry on line {line_number}: expected KEY=VALUE.")

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise SettingsError(f"Invalid .env entry on line {line_number}: missing key.")

        values[key] = _clean_env_value(value)

    return values


def _merge_env(file_values: dict[str, str]) -> dict[str, str]:
    values = dict(file_values)
    for key in (
        "KALSHI_ENV",
        "KALSHI_API_BASE_URL",
        "KALSHI_API_KEY_ID",
        "KALSHI_PRIVATE_KEY_PEM",
        "KALSHI_PRIVATE_KEY_PATH",
        "KALSHI_PRIVATE_KEY_PASSPHRASE",
        "KALSHI_REQUEST_TIMEOUT_SECONDS",
        "KALSHI_WS_URL",
        "KALSHI_WS_MARKET_TICKERS",
        "KALSHI_WS_MESSAGE_LIMIT",
        "KALSHI_WS_RECEIVE_TIMEOUT_SECONDS",
        "KALSHI_WS_MAX_RECONNECT_ATTEMPTS",
        "KALSHI_WS_RECONNECT_INITIAL_DELAY_SECONDS",
        "KALSHI_WS_RECONNECT_MAX_DELAY_SECONDS",
        "CRYPTO_FEED_WS_URL",
        "CRYPTO_FEED_PRODUCTS",
        "CRYPTO_FEED_MESSAGE_LIMIT",
        "CRYPTO_FEED_RECEIVE_TIMEOUT_SECONDS",
        "CRYPTO_FEED_MAX_RECONNECT_ATTEMPTS",
        "CRYPTO_FEED_RECONNECT_INITIAL_DELAY_SECONDS",
        "CRYPTO_FEED_RECONNECT_MAX_DELAY_SECONDS",
        "LOG_DIRECTORY",
        "LOG_JSONL_ENABLED",
        "REPLAY_DIRECTORY",
        "REPLAY_WRITE_ENABLED",
        "TIME_SYNC_MAX_DRIFT_MS",
        "TIME_SYNC_LOG_RESULTS",
        "BIAS_PRODUCTS",
        "BIAS_LOOKBACK_SECONDS",
        "BIAS_RECENT_WINDOW_SECONDS",
        "BIAS_MIN_SAMPLES",
        "BIAS_STALE_DATA_SECONDS",
        "BIAS_CHOP_THRESHOLD_BPS",
        "BIAS_IMPULSE_MIN_ABS_BPS",
        "CONTRACT_SCANNER_PRODUCT_MARKETS_JSON",
        "KALSHI_AUTO_MARKET_DISCOVERY_ENABLED",
        "KALSHI_CRYPTO_MARKET_SERIES_JSON",
        "KALSHI_MARKET_DISCOVERY_REFRESH_CYCLES",
        "SIMULATION_ENABLED",
        "SIMULATION_MAX_NEW_POSITIONS_PER_EVALUATION",
        "SIMULATION_POSITION_ID_PREFIX",
        "SIMULATION_EXIT_ENABLED",
        "SIMULATION_ALLOW_SAME_PASS_REENTRY",
        "RISK_ACCOUNT_BALANCE_DOLLARS",
        "RISK_MIN_PERCENT_PER_TRADE",
        "RISK_MAX_PERCENT_PER_TRADE",
        "RISK_MIN_STAKE_DOLLARS",
        "RISK_MAX_STAKE_DOLLARS",
        "RISK_MAX_OPEN_POSITIONS",
        "RISK_MAX_TOTAL_EXPOSURE_DOLLARS",
        "RISK_DAILY_LOSS_LIMIT_DOLLARS",
        "RISK_KILL_SWITCH_ACTIVE",
        "LIVE_VALIDATION_ENABLED",
        "LIVE_VALIDATION_ENV",
        "LIVE_VALIDATION_TICKER",
        "LIVE_VALIDATION_ACTION",
        "LIVE_VALIDATION_SIDE",
        "LIVE_VALIDATION_COUNT",
        "LIVE_VALIDATION_PRICE_DOLLARS",
        "LIVE_VALIDATION_TIME_IN_FORCE",
        "LIVE_VALIDATION_POLL_ATTEMPTS",
        "LIVE_VALIDATION_POLL_INTERVAL_SECONDS",
        "LIVE_VALIDATION_CLIENT_ORDER_ID_PREFIX",
        "LIVE_TRADING_ENABLED",
        "LIVE_KILL_SWITCH_ACTIVE",
        "LIVE_RUNNER_EXECUTION_ENABLED",
        "LIVE_MAX_EXPOSURE_DOLLARS",
        "LIVE_MIN_STAKE_DOLLARS",
        "LIVE_MAX_STAKE_DOLLARS",
        "LIVE_MAX_OPEN_POSITIONS",
        "LIVE_MAX_CONTRACT_COUNT",
        "LIVE_PROFIT_CAPTURE_ENABLED",
        "LIVE_PROFIT_CAPTURE_PRICE",
        "LIVE_TRAILING_STOP_ENABLED",
        "LIVE_TRAILING_STOP_DISTANCE",
        "LIVE_ENTRY_END_WINDOW_ONLY",
        "LIVE_ENTRY_END_WINDOW_MINUTES",
        "LIVE_ENTRY_MIN_REMAINING_SECONDS",
        "LIVE_ENTRY_SEGMENT_PACING_ENABLED",
        "LIVE_ENTRY_SEGMENT_MAX_10_TO_5",
        "LIVE_ENTRY_SEGMENT_MAX_5_TO_3",
        "LIVE_ENTRY_SEGMENT_MAX_3_TO_1",
        "LIVE_ENTRY_SEGMENT_MAX_FINAL_1",
        "LIVE_FAST_SCAN_ENABLED",
        "LIVE_FAST_SCAN_INTERVAL_SECONDS",
        "LIVE_FAST_SCAN_COOLDOWN_SECONDS",
        "LIVE_REVERSAL_CROSS_HOLD_ENABLED",
        "LIVE_REVERSAL_CROSS_HOLD_SECONDS",
        "LIVE_MID_PRICE_TIGHTENING_ENABLED",
        "LIVE_MID_PRICE_MIN",
        "LIVE_MID_PRICE_MAX",
        "LIVE_MAX_OPEN_POSITIONS_PER_PRODUCT",
        "LIVE_MAX_ENTRIES_PER_PRODUCT_PER_SESSION",
        "LIVE_COMPOSITE_QUALITY_FILTER_ENABLED",
        "LIVE_COMPOSITE_MAX_ENTRY_PRICE",
        "LIVE_COMPOSITE_LOW_PRICE_MAX",
        "LIVE_COMPOSITE_ALLOWED_SEGMENTS",
        "LIVE_COMPOSITE_REQUIRE_TREND",
        "LIVE_COMPOSITE_REQUIRE_ITM",
        "LIVE_COMPOSITE_BLOCK_NEEDS_CROSS",
        "LIVE_REVERSAL_MAX_ENTRY_PRICE",
        "LIVE_BLOCK_NEEDS_CROSS",
        "LIVE_MAX_REQUIRED_BPS_PER_MINUTE",
        "LIVE_OUTSIDE_END_WINDOW_EXCEPTION_ENABLED",
        "LIVE_OUTSIDE_END_WINDOW_MAX_PRICE",
        "LIVE_EV_FILTER_ENABLED",
        "LIVE_MIN_EXPECTED_VALUE",
        "LIVE_EV_PRICE_MAX_ITM_NO_CROSS",
        "LIVE_EV_PRICE_MAX_NEEDS_CROSS",
        "LIVE_EV_REQUIRED_BPS_MAX",
        "LIVE_EV_ALLOWED_SEGMENTS",
        "LIVE_EV_CONSERVATIVE_ALLOWED_SEGMENTS",
        "LIVE_EV_ALLOW_REVERSAL",
        "LIVE_EV_CANDIDATE_A_WIN_PROBABILITY",
        "LIVE_EV_CANDIDATE_B_WIN_PROBABILITY",
        "LIVE_PRODUCT_BLOCKLIST",
        "LIVE_CONDITIONAL_HIGH_PRICE_PASS_ENABLED",
        "LIVE_CONDITIONAL_MAX_PREMIUM_OVER_MIDPOINT",
        "LIVE_CONDITIONAL_MAX_SPREAD",
        "LIVE_CONDITIONAL_MAX_SCANNER_PREMIUM",
        "LIVE_CONDITIONAL_ALLOW_EXTREME_ASYMMETRY",
        "LIVE_CONDITIONAL_ALLOW_HIGH_PRICE_CEILING_BYPASS",
        "LIVE_CONDITIONAL_HIGH_PRICE_CEILING_MAX",
        "LIVE_EV_TIMING_BYPASS_ENABLED",
        "LIVE_EV_EXTRA_ENTRIES_PER_PRODUCT_PER_SESSION",
        "LIVE_EV_EXTRA_OPEN_POSITIONS_PER_PRODUCT",
        "LIVE_QUIET_CONTINUATION_ENABLED",
        "LIVE_QUIET_CONTINUATION_MAX_RECENT_BPS",
        "LIVE_QUIET_CONTINUATION_MAX_3M_ABS_BPS",
        "LIVE_QUIET_CONTINUATION_MAX_5M_ABS_BPS",
        "LIVE_QUIET_CONTINUATION_MAX_5M_RANGE_BPS",
        "LIVE_QUIET_CONTINUATION_BLOCK_DECELERATION",
        "LIVE_QUIET_CONTINUATION_BLOCK_NEAR_EXTREME",
        "LIVE_QUIET_CONTINUATION_MIN_DISTANCE_FROM_EXTREME_BPS",
        "LIVE_EXHAUSTION_GUARD_ENABLED",
        "LIVE_EXHAUSTION_BURST_3M_BPS",
        "LIVE_EXHAUSTION_BURST_5M_BPS",
        "LIVE_EXHAUSTION_NEAR_EXTREME_BPS",
        "LIVE_EXHAUSTION_DECELERATION_RECENT_BPS",
        "LIVE_EXHAUSTION_STRICT_PRODUCTS",
        "LIVE_EXHAUSTION_STRICT_BURST_3M_BPS",
        "LIVE_EARLY_MOMENTUM_ENABLED",
        "LIVE_EARLY_MOMENTUM_MIN_RECENT_BPS",
        "LIVE_EARLY_MOMENTUM_MAX_3M_BURST_BPS",
        "LIVE_EARLY_MOMENTUM_MAX_ENTRY_PRICE",
        "LIVE_EV_MAX_ACTUAL_COST",
        "LIVE_EV_MIN_REWARD_DOLLARS",
        "LIVE_EV_REQUIRE_POSITIVE_COST_EXPECTED_VALUE",
        "LIVE_EV_EXHAUSTION_BLOCK_ENABLED",
        "LIVE_CANDIDATE_FUNNEL_DIAGNOSTICS_ENABLED",
        "RUNNER_ENABLED",
        "RUNNER_LOOP_INTERVAL_SECONDS",
        "RUNNER_STATUS_LOG_EVERY_N_CYCLES",
        "RUNNER_FAIL_FAST_ON_STARTUP",
        "RUNNER_MAX_CYCLES",
    ):
        if key in os.environ:
            values[key] = _clean_env_value(os.environ[key])
    return values


def _clean_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value.replace("\\n", "\n")


def _required(values: dict[str, str], key: str) -> str:
    value = _optional(values, key)
    if value is None:
        raise SettingsError(f"{key} is required.")
    return value


def _optional(values: dict[str, str], key: str) -> str | None:
    value = values.get(key)
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped


def _parse_timeout(value: str | None, default: float) -> float:
    if value is None or not value.strip():
        return default
    try:
        timeout = float(value)
    except ValueError as exc:
        raise SettingsError("KALSHI_REQUEST_TIMEOUT_SECONDS must be numeric.") from exc
    if timeout <= 0:
        raise SettingsError("KALSHI_REQUEST_TIMEOUT_SECONDS must be greater than zero.")
    return timeout


def _parse_positive_float(value: str | None, default: float, key: str) -> float:
    if value is None or not value.strip():
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise SettingsError(f"{key} must be numeric.") from exc
    if parsed <= 0:
        raise SettingsError(f"{key} must be greater than zero.")
    return parsed


def _parse_positive_int(value: str | None, default: int, key: str) -> int:
    parsed = _parse_non_negative_int(value, default, key)
    if parsed <= 0:
        raise SettingsError(f"{key} must be greater than zero.")
    return parsed


def _parse_non_negative_int(value: str | None, default: int, key: str) -> int:
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise SettingsError(f"{key} must be an integer.") from exc
    if parsed < 0:
        raise SettingsError(f"{key} must be greater than or equal to zero.")
    return parsed


def _parse_csv(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    items = tuple(item.strip() for item in value.split(",") if item.strip())
    return items


def _parse_allowed_segments(
    value: str | None,
    default: tuple[str, ...],
    key: str,
) -> tuple[str, ...]:
    segments = (
        tuple(_normalize_segment(item) for item in _parse_csv(value))
        if value is not None and value.strip()
        else default
    )
    allowed = {"10_to_5", "5_to_3", "3_to_1", "final_1"}
    invalid = tuple(segment for segment in segments if segment not in allowed)
    if invalid:
        raise SettingsError(
            f"{key} contains unsupported segment(s): {', '.join(invalid)}."
        )
    if not segments:
        raise SettingsError(f"{key} must include at least one segment.")
    return tuple(dict.fromkeys(segments))


def _normalize_segment(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def _parse_bool(value: str | None, default: bool, key: str) -> bool:
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise SettingsError(f"{key} must be a boolean-like value.")


def _parse_path(value: str | None, default: Path) -> Path:
    if value is None or not value.strip():
        return default
    return Path(value).expanduser()


def _parse_price_dollars(value: str | None, key: str) -> Decimal | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = Decimal(value.strip())
    except (InvalidOperation, ValueError) as exc:
        raise SettingsError(f"{key} must be a valid decimal string.") from exc
    if parsed < Decimal("0.01") or parsed > Decimal("0.99"):
        raise SettingsError(f"{key} must be between 0.01 and 0.99 inclusive.")
    if parsed.as_tuple().exponent < -4:
        raise SettingsError(f"{key} must have at most four decimal places.")
    return parsed.quantize(Decimal("0.0001"))


def _parse_positive_decimal(value: str | None, default: Decimal, key: str) -> Decimal:
    if value is None or not value.strip():
        return default
    try:
        parsed = Decimal(value.strip())
    except (InvalidOperation, ValueError) as exc:
        raise SettingsError(f"{key} must be a valid decimal string.") from exc
    if parsed <= 0:
        raise SettingsError(f"{key} must be greater than zero.")
    return parsed


def _parse_non_negative_decimal(
    value: str | None,
    default: Decimal,
    key: str,
) -> Decimal:
    if value is None or not value.strip():
        return default
    try:
        parsed = Decimal(value.strip())
    except (InvalidOperation, ValueError) as exc:
        raise SettingsError(f"{key} must be a valid decimal string.") from exc
    if parsed < 0:
        raise SettingsError(f"{key} must be greater than or equal to zero.")
    return parsed


def _parse_probability(value: str | None, default: Decimal, key: str) -> Decimal:
    parsed = _parse_positive_decimal(value, default, key)
    if parsed > Decimal("1"):
        raise SettingsError(f"{key} must be less than or equal to 1.")
    return parsed


def _parse_optional_positive_int(value: str | None, key: str) -> int | None:
    if value is None or not value.strip():
        return None
    parsed = _parse_non_negative_int(value, 0, key)
    if parsed <= 0:
        raise SettingsError(f"{key} must be greater than zero when provided.")
    return parsed


def _parse_product_markets_json(value: str | None) -> dict[str, tuple[str, ...]]:
    if value is None or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SettingsError("CONTRACT_SCANNER_PRODUCT_MARKETS_JSON must be valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise SettingsError("CONTRACT_SCANNER_PRODUCT_MARKETS_JSON must be a JSON object.")

    normalized: dict[str, tuple[str, ...]] = {}
    for raw_product_id, raw_tickers in parsed.items():
        product_id = str(raw_product_id).strip()
        if not product_id:
            raise SettingsError(
                "CONTRACT_SCANNER_PRODUCT_MARKETS_JSON product keys must be non-empty strings."
            )
        if not isinstance(raw_tickers, list):
            raise SettingsError(
                "CONTRACT_SCANNER_PRODUCT_MARKETS_JSON values must be arrays of market tickers."
            )
        tickers = tuple(
            dict.fromkeys(str(raw_ticker).strip() for raw_ticker in raw_tickers if str(raw_ticker).strip())
        )
        if not tickers:
            raise SettingsError(
                "CONTRACT_SCANNER_PRODUCT_MARKETS_JSON values must contain non-empty market tickers."
            )
        normalized[product_id] = tickers
    return normalized


def _parse_product_series_json(value: str | None) -> dict[str, tuple[str, ...]]:
    if value is None or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SettingsError("KALSHI_CRYPTO_MARKET_SERIES_JSON must be valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise SettingsError("KALSHI_CRYPTO_MARKET_SERIES_JSON must be a JSON object.")

    normalized: dict[str, tuple[str, ...]] = {}
    for raw_product_id, raw_series in parsed.items():
        product_id = str(raw_product_id).strip()
        if not product_id:
            raise SettingsError(
                "KALSHI_CRYPTO_MARKET_SERIES_JSON product keys must be non-empty strings."
            )
        if not isinstance(raw_series, list):
            raise SettingsError(
                "KALSHI_CRYPTO_MARKET_SERIES_JSON values must be arrays of series tickers."
            )
        series = tuple(
            dict.fromkeys(str(raw_ticker).strip() for raw_ticker in raw_series if str(raw_ticker).strip())
        )
        if not series:
            raise SettingsError(
                "KALSHI_CRYPTO_MARKET_SERIES_JSON values must contain non-empty series tickers."
            )
        normalized[product_id] = series
    return normalized
