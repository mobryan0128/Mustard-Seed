"""Environment-backed settings for Kalshi API access."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
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
DEFAULT_CRYPTO_FEED_PRODUCTS = ("BTC-USD", "ETH-USD")
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
    simulation_enabled: bool
    simulation_max_new_positions_per_evaluation: int
    simulation_position_id_prefix: str
    simulation_exit_enabled: bool
    simulation_allow_same_pass_reentry: bool


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
    simulation_position_id_prefix = (
        _optional(values, "SIMULATION_POSITION_ID_PREFIX")
        or DEFAULT_SIMULATION_POSITION_ID_PREFIX
    )

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
        "SIMULATION_ENABLED",
        "SIMULATION_MAX_NEW_POSITIONS_PER_EVALUATION",
        "SIMULATION_POSITION_ID_PREFIX",
        "SIMULATION_EXIT_ENABLED",
        "SIMULATION_ALLOW_SAME_PASS_REENTRY",
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
