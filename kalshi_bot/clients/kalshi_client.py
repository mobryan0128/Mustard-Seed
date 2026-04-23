"""Minimal authenticated Kalshi HTTP client for Phase 1 validation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlsplit

import httpx

from kalshi_bot.auth.auth_manager import AuthManagerError, KalshiAuthManager
from kalshi_bot.config.settings import KalshiSettings


BALANCE_PATH = "/portfolio/balance"
ORDERS_PATH = "/portfolio/orders"


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


class KalshiClient:
    def __init__(
        self,
        base_url: str,
        auth_manager: KalshiAuthManager,
        timeout_seconds: float,
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/"
        self._auth_manager = auth_manager
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_settings(cls, settings: KalshiSettings) -> "KalshiClient":
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
        )

    def get_balance(self) -> dict[str, object]:
        response = self._get(BALANCE_PATH)
        payload = _json_object(response, "Kalshi balance response")
        if not isinstance(payload, dict):
            raise KalshiClientError("Kalshi balance response was not a JSON object.")
        return payload

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

    def _get(self, path: str) -> httpx.Response:
        return self._request("GET", path)

    def _post_json(self, path: str, payload: dict[str, object]) -> httpx.Response:
        return self._request("POST", path, json_payload=payload)

    def _request(
        self,
        method: str,
        path: str,
        json_payload: dict[str, object] | None = None,
    ) -> httpx.Response:
        url = urljoin(self._base_url, path.lstrip("/"))
        sign_path = urlsplit(url).path
        headers = self._auth_manager.auth_headers(method=method, path=sign_path)
        if json_payload is not None:
            headers["Content-Type"] = "application/json"

        with httpx.Client(timeout=self._timeout_seconds) as client:
            response = client.request(method, url, headers=headers, json=json_payload)

        if response.status_code >= 400:
            raise KalshiClientError(_response_error_message(response))
        return response


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
