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
DEFAULT_BIAS_LOOKBACK_SECONDS = 1800
DEFAULT_BIAS_RECENT_WINDOW_SECONDS = 60
DEFAULT_BIAS_MIN_SAMPLES = 20
DEFAULT_BIAS_STALE_DATA_SECONDS = 15
DEFAULT_BIAS_CHOP_THRESHOLD_BPS = 10
DEFAULT_SIMULATION_ENABLED = True
DEFAULT_SIMULATION_MAX_NEW_POSITIONS_PER_EVALUATION = 1
DEFAULT_SIMULATION_POSITION_ID_PREFIX = "sim"
DEFAULT_SIMULATION_EXIT_ENABLED = True
DEFAULT_SIMULATION_ALLOW_SAME_PASS_REENTRY = False
DEFAULT_RISK_ACCOUNT_BALANCE_DOLLARS = Decimal("100")
DEFAULT_RISK_MIN_PERCENT_PER_TRADE = Decimal("0.03")
DEFAULT_RISK_MAX_PERCENT_PER_TRADE = Decimal("0.05")
DEFAULT_RISK_MIN_STAKE_DOLLARS = Decimal("3")
DEFAULT_RISK_MAX_STAKE_DOLLARS = Decimal("5")
DEFAULT_RISK_MAX_OPEN_POSITIONS = 10
DEFAULT_RISK_MAX_TOTAL_EXPOSURE_DOLLARS = Decimal("300")
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
    bias_products: tuple[str, ...]
    bias_lookback_seconds: int
    bias_recent_window_seconds: int
    bias_min_samples: int
    bias_stale_data_seconds: int
    bias_chop_threshold_bps: int
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
