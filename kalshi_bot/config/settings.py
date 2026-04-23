"""Environment-backed settings for Kalshi API access."""

from __future__ import annotations

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
