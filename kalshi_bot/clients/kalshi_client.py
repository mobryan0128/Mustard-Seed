"""Minimal authenticated Kalshi HTTP client for Phase 1 validation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from kalshi_bot.auth.auth_manager import AuthManagerError, KalshiAuthManager
from kalshi_bot.config.settings import KalshiSettings


BALANCE_PATH = "/portfolio/balance"
MARKETS_PATH = "/markets"
ORDERS_PATH = "/portfolio/orders"
POSITIONS_PATH = "/portfolio/positions"


class KalshiClientError(RuntimeError):
    """Raised when a Kalshi REST request fails or returns invalid data."""


@dataclass(frozen=True)
class KalshiOrderRequest:
    """Normalized request for one explicit Kalshi limit order."""

    ticker: str
    action: str
    side: str
    count: int
    price_dollars: Decimal
    time_in_force: str
    client_order_id: str

    def to_payload(self) -> dict[str, object]:
        payload = {
            "ticker": self.ticker,
            "action": self.action,
            "side": self.side,
            "count": self.count,
            "type": "limit",
            "client_order_id": self.client_order_id,
            "time_in_force": self.time_in_force,
        }
        if self.side == "yes":
            payload["yes_price_dollars"] = _decimal_string(self.price_dollars)
        else:
            payload["no_price_dollars"] = _decimal_string(self.price_dollars)
        return payload


@dataclass(frozen=True)
class KalshiOrderSummary:
    """Minimal normalized order status used by live validation."""

    order_id: str
    client_order_id: str | None
    ticker: str
    side: str
    action: str
    order_type: str | None
    status: str
    yes_price_dollars: Decimal | None
    no_price_dollars: Decimal | None
    fill_count_fp: Decimal | None
    remaining_count_fp: Decimal | None
    initial_count_fp: Decimal | None
    created_time: str | None
    last_update_time: str | None


@dataclass(frozen=True)
class KalshiMarketPosition:
    """Minimal normalized current market position used for live exits."""

    ticker: str
    position_fp: Decimal
    market_exposure_dollars: Decimal
    resting_orders_count: int | None
    last_updated_ts: str | None


@dataclass(frozen=True)
class KalshiPositionPage:
    """One paginated Kalshi positions response."""

    market_positions: tuple[KalshiMarketPosition, ...]
    cursor: str | None


@dataclass(frozen=True)
class KalshiMarketSummary:
    """Minimal normalized market metadata used by runner discovery."""

    ticker: str
    event_ticker: str | None
    status: str | None
    open_time: str | None
    close_time: str | None
    expiration_time: str | None
    latest_expiration_time: str | None
    yes_bid_dollars: Decimal | None
    yes_ask_dollars: Decimal | None
    target_price: Decimal | None
    target_price_source: str | None


@dataclass(frozen=True)
class KalshiMarketPage:
    """One paginated Kalshi market-list response."""

    markets: tuple[KalshiMarketSummary, ...]
    cursor: str | None


class KalshiClient:
    def __init__(
        self,
        base_url: str,
        auth_manager: KalshiAuthManager,
        timeout_seconds: float,
        logger: Any | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/"
        self._auth_manager = auth_manager
        self._timeout_seconds = timeout_seconds
        self._logger = logger

    @classmethod
    def from_settings(
        cls,
        settings: KalshiSettings,
        logger: Any | None = None,
    ) -> "KalshiClient":
        try:
            if settings.private_key_pem is not None:
                auth_manager = KalshiAuthManager.from_pem(
                    api_key_id=settings.api_key_id,
                    private_key_pem=settings.private_key_pem,
                    passphrase=settings.private_key_passphrase,
                )
            elif settings.private_key_path is not None:
                auth_manager = KalshiAuthManager.from_key_path(
                    api_key_id=settings.api_key_id,
                    private_key_path=settings.private_key_path,
                    passphrase=settings.private_key_passphrase,
                )
            else:
                raise KalshiClientError(
                    "Provide either KALSHI_PRIVATE_KEY_PEM or KALSHI_PRIVATE_KEY_PATH."
                )
        except AuthManagerError as exc:
            raise KalshiClientError(str(exc)) from exc

        return cls(
            base_url=settings.api_base_url,
            auth_manager=auth_manager,
            timeout_seconds=settings.request_timeout_seconds,
            logger=logger,
        )

    def get_balance(self) -> dict[str, object]:
        response = self._get(BALANCE_PATH)
        payload = _json_object(response, "Kalshi balance response")
        if not isinstance(payload, dict):
            raise KalshiClientError("Kalshi balance response was not a JSON object.")
        return payload

    def get_markets(
        self,
        *,
        series_ticker: str,
        status: str = "open",
        limit: int = 1000,
        cursor: str | None = None,
        mve_filter: str = "exclude",
    ) -> KalshiMarketPage:
        if not series_ticker.strip():
            raise KalshiClientError("series_ticker is required.")
        if limit <= 0 or limit > 1000:
            raise KalshiClientError("market discovery limit must be between 1 and 1000.")

        normalized_series_ticker = series_ticker.strip()
        query_params = {
            "series_ticker": normalized_series_ticker,
            "status": status,
            "limit": str(limit),
            "cursor": cursor or "",
            "mve_filter": mve_filter,
        }
        response = self._get(
            MARKETS_PATH,
            query_params=query_params,
        )
        payload = _json_object(response, "Kalshi markets response")
        markets_payload = payload.get("markets")
        self._log_get_markets_response(
            series_ticker=normalized_series_ticker,
            status=status,
            limit=limit,
            cursor_present=cursor is not None,
            mve_filter=mve_filter,
            markets_payload=markets_payload,
            returned_cursor_present=_optional_text(payload.get("cursor")) is not None,
        )
        if not isinstance(markets_payload, list):
            raise KalshiClientError("Kalshi markets response did not include markets.")
        return KalshiMarketPage(
            markets=tuple(_normalize_market_payload(market) for market in markets_payload),
            cursor=_optional_text(payload.get("cursor")),
        )

    def create_order(self, order: KalshiOrderRequest) -> KalshiOrderSummary:
        response = self._post_json(ORDERS_PATH, order.to_payload())
        payload = _json_object(response, "Kalshi create-order response")
        order_payload = payload.get("order")
        if not isinstance(order_payload, dict):
            raise KalshiClientError("Kalshi create-order response did not include an order.")
        return _normalize_order_payload(order_payload)

    def get_order(self, order_id: str) -> KalshiOrderSummary:
        normalized_order_id = order_id.strip()
        if not normalized_order_id:
            raise KalshiClientError("order_id is required.")
        response = self._get(f"{ORDERS_PATH}/{normalized_order_id}")
        payload = _json_object(response, "Kalshi get-order response")
        order_payload = payload.get("order")
        if not isinstance(order_payload, dict):
            raise KalshiClientError("Kalshi get-order response did not include an order.")
        return _normalize_order_payload(order_payload)

    def get_positions(
        self,
        *,
        count_filter: str = "position",
        settlement_status: str = "unsettled",
        limit: int = 1000,
        cursor: str | None = None,
    ) -> KalshiPositionPage:
        if limit <= 0 or limit > 1000:
            raise KalshiClientError("positions limit must be between 1 and 1000.")
        query_params = {
            "count_filter": count_filter,
            "settlement_status": settlement_status,
            "limit": str(limit),
            "cursor": cursor or "",
        }
        response = self._get(POSITIONS_PATH, query_params=query_params)
        payload = _json_object(response, "Kalshi positions response")
        positions_payload = payload.get("market_positions")
        if not isinstance(positions_payload, list):
            raise KalshiClientError("Kalshi positions response did not include market_positions.")
        return KalshiPositionPage(
            market_positions=tuple(
                _normalize_position_payload(position)
                for position in positions_payload
            ),
            cursor=_optional_text(payload.get("cursor")),
        )

    def _get(
        self,
        path: str,
        query_params: dict[str, str] | None = None,
    ) -> httpx.Response:
        return self._request("GET", path, query_params=query_params)

    def _post_json(self, path: str, payload: dict[str, object]) -> httpx.Response:
        return self._request("POST", path, json_payload=payload)

    def _request(
        self,
        method: str,
        path: str,
        query_params: dict[str, str] | None = None,
        json_payload: dict[str, object] | None = None,
    ) -> httpx.Response:
        url = urljoin(self._base_url, path.lstrip("/"))
        sign_path = urlsplit(url).path
        headers = self._auth_manager.auth_headers(method=method, path=sign_path)
        if json_payload is not None:
            headers["Content-Type"] = "application/json"

        with httpx.Client(timeout=self._timeout_seconds) as client:
            response = client.request(
                method,
                url,
                headers=headers,
                params=query_params,
                json=json_payload,
            )

        if response.status_code >= 400:
            raise KalshiClientError(_response_error_message(response))
        return response

    def _log_get_markets_response(
        self,
        *,
        series_ticker: str,
        status: str,
        limit: int,
        cursor_present: bool,
        mve_filter: str,
        markets_payload: object,
        returned_cursor_present: bool,
    ) -> None:
        if self._logger is None:
            return
        self._logger.log_event(
            category="kalshi_client",
            event_type="kalshi_get_markets_response",
            source="kalshi_client",
            identifier=series_ticker,
            payload={
                "series_ticker": series_ticker,
                "status": status,
                "limit": limit,
                "cursor_present": cursor_present,
                "mve_filter": mve_filter,
                "returned_cursor_present": returned_cursor_present,
                "raw_market_count": _market_payload_count(markets_payload),
                "raw_market_ticker_sample": _market_payload_ticker_sample(markets_payload),
            },
        )


def _json_object(response: httpx.Response, label: str) -> dict[str, object]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise KalshiClientError(f"{label} was not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise KalshiClientError(f"{label} was not a JSON object.")
    return payload


def _normalize_order_payload(payload: dict[str, object]) -> KalshiOrderSummary:
    return KalshiOrderSummary(
        order_id=_require_text(payload.get("order_id"), "order_id"),
        client_order_id=_optional_text(payload.get("client_order_id")),
        ticker=_require_text(payload.get("ticker"), "ticker"),
        side=_require_text(payload.get("side"), "side"),
        action=_require_text(payload.get("action"), "action"),
        order_type=_optional_text(payload.get("type")),
        status=_require_text(payload.get("status"), "status"),
        yes_price_dollars=_optional_decimal(payload.get("yes_price_dollars")),
        no_price_dollars=_optional_decimal(payload.get("no_price_dollars")),
        fill_count_fp=_optional_decimal(payload.get("fill_count_fp")),
        remaining_count_fp=_optional_decimal(payload.get("remaining_count_fp")),
        initial_count_fp=_optional_decimal(payload.get("initial_count_fp")),
        created_time=_optional_text(payload.get("created_time")),
        last_update_time=_optional_text(payload.get("last_update_time")),
    )


def _normalize_position_payload(payload: object) -> KalshiMarketPosition:
    if not isinstance(payload, dict):
        raise KalshiClientError("Kalshi position payload was not a JSON object.")
    return KalshiMarketPosition(
        ticker=_require_text(payload.get("ticker"), "ticker"),
        position_fp=(
            _optional_decimal(payload.get("position_fp"))
            or _optional_decimal(payload.get("position"))
            or Decimal("0")
        ),
        market_exposure_dollars=(
            _optional_decimal(payload.get("market_exposure_dollars"))
            or _optional_decimal(payload.get("market_exposure"))
            or Decimal("0")
        ),
        resting_orders_count=_optional_int(payload.get("resting_orders_count")),
        last_updated_ts=_optional_text(payload.get("last_updated_ts")),
    )


def _normalize_market_payload(payload: object) -> KalshiMarketSummary:
    if not isinstance(payload, dict):
        raise KalshiClientError("Kalshi market payload was not a JSON object.")
    target_price, target_price_source = _market_target_price(payload)
    return KalshiMarketSummary(
        ticker=_require_text(payload.get("ticker"), "ticker"),
        event_ticker=_optional_text(payload.get("event_ticker")),
        status=_optional_text(payload.get("status")),
        open_time=_optional_text(payload.get("open_time")),
        close_time=_optional_text(payload.get("close_time")),
        expiration_time=_optional_text(payload.get("expiration_time")),
        latest_expiration_time=_optional_text(payload.get("latest_expiration_time")),
        yes_bid_dollars=_optional_decimal(payload.get("yes_bid_dollars")),
        yes_ask_dollars=_optional_decimal(payload.get("yes_ask_dollars")),
        target_price=target_price,
        target_price_source=target_price_source,
    )


def _market_target_price(payload: dict[str, object]) -> tuple[Decimal | None, str | None]:
    for key in (
        "target_price",
        "strike_price",
        "strike",
        "floor_strike",
        "cap_strike",
        "floor_price",
        "cap_price",
        "start_price",
        "initial_price",
        "reference_price",
    ):
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return _optional_decimal(value), key
    return None, None


def _market_payload_count(markets_payload: object) -> int | None:
    if not isinstance(markets_payload, list):
        return None
    return len(markets_payload)


def _market_payload_ticker_sample(markets_payload: object) -> tuple[str, ...]:
    if not isinstance(markets_payload, list):
        return ()
    sample: list[str] = []
    for market in markets_payload[:10]:
        if not isinstance(market, dict):
            continue
        ticker = _optional_text(market.get("ticker"))
        if ticker is not None:
            sample.append(ticker)
    return tuple(sample)


def _response_error_message(response: httpx.Response) -> str:
    message = f"Kalshi request failed with status {response.status_code}."
    try:
        payload = response.json()
    except ValueError:
        return message
    if not isinstance(payload, dict):
        return message
    error = payload.get("error")
    if isinstance(error, dict):
        detail = error.get("message") or error.get("code")
        if isinstance(detail, str) and detail.strip():
            return f"{message} {detail.strip()}"
    detail = payload.get("message")
    if isinstance(detail, str) and detail.strip():
        return f"{message} {detail.strip()}"
    return message


def _decimal_string(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.0001")))


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise KalshiClientError("Kalshi order payload contained an invalid decimal field.") from exc


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise KalshiClientError("Kalshi payload contained an invalid integer field.") from exc


def _require_text(value: object, field_name: str) -> str:
    normalized = _optional_text(value)
    if normalized is None:
        raise KalshiClientError(f"Kalshi order payload missing {field_name}.")
    return normalized


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized
