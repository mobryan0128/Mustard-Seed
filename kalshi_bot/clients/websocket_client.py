"""Authenticated Kalshi WebSocket market-data client."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Union
from urllib.parse import urlsplit

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from kalshi_bot.auth.auth_manager import AuthManagerError, KalshiAuthManager
from kalshi_bot.config.settings import KalshiSettings
from kalshi_bot.market.market_state_cache import MarketStateCache, MarketStateCacheError


WS_AUTH_PATH = "/trade-api/ws/v2"
ALLOWED_CHANNELS = frozenset({"ticker", "orderbook_delta"})
DEFAULT_CHANNELS = ("ticker", "orderbook_delta")


class KalshiWebSocketError(RuntimeError):
    pass


@dataclass(frozen=True)
class PriceLevel:
    price_dollars: str
    quantity_fp: str


@dataclass(frozen=True)
class TickerMessage:
    market_ticker: str
    market_id: str | None
    price_dollars: str | None
    yes_bid_dollars: str | None
    yes_ask_dollars: str | None
    yes_bid_size_fp: str | None
    yes_ask_size_fp: str | None
    volume_fp: str | None
    open_interest_fp: str | None
    dollar_volume: int | str | None
    dollar_open_interest: int | str | None
    last_trade_size_fp: str | None
    exchange_ts: int | None
    exchange_time: str | None
    sid: int | None
    seq: int | None


@dataclass(frozen=True)
class OrderbookSnapshotMessage:
    market_ticker: str
    market_id: str | None
    yes_levels: tuple[PriceLevel, ...]
    no_levels: tuple[PriceLevel, ...]
    sid: int | None
    seq: int | None


@dataclass(frozen=True)
class OrderbookDeltaMessage:
    market_ticker: str
    market_id: str | None
    side: str
    price_dollars: str
    delta_fp: str
    ts: str | None
    sid: int | None
    seq: int | None


@dataclass(frozen=True)
class SubscribedMessage:
    command_id: int | None
    sid: int | None
    channels: tuple[str, ...]


@dataclass(frozen=True)
class ErrorMessage:
    command_id: int | None
    code: int | str | None
    message: str


@dataclass(frozen=True)
class UnsupportedMessage:
    message_type: str


@dataclass(frozen=True)
class WebSocketRunResult:
    messages_received: int = 0
    market_data_messages: int = 0
    ticker_messages: int = 0
    orderbook_snapshots: int = 0
    orderbook_deltas: int = 0
    subscription_messages: int = 0
    unsupported_messages: int = 0
    reconnects: int = 0
    timed_out: bool = False
    subscribed_market_tickers: tuple[str, ...] = ()


ParsedMessage = Union[
    TickerMessage,
    OrderbookSnapshotMessage,
    OrderbookDeltaMessage,
    SubscribedMessage,
    ErrorMessage,
    UnsupportedMessage,
]


class KalshiWebSocketClient:
    def __init__(
        self,
        *,
        ws_url: str,
        auth_manager: KalshiAuthManager,
        market_state_cache: MarketStateCache,
        message_limit: int,
        receive_timeout_seconds: float,
        max_reconnect_attempts: int,
        reconnect_initial_delay_seconds: float,
        reconnect_max_delay_seconds: float,
    ) -> None:
        self._ws_url = ws_url
        self._auth_manager = auth_manager
        self._cache = market_state_cache
        self._message_limit = message_limit
        self._receive_timeout_seconds = receive_timeout_seconds
        self._max_reconnect_attempts = max_reconnect_attempts
        self._reconnect_initial_delay_seconds = reconnect_initial_delay_seconds
        self._reconnect_max_delay_seconds = reconnect_max_delay_seconds
        self._connection: Any | None = None
        self._next_command_id = 1

    @classmethod
    def from_settings(
        cls,
        settings: KalshiSettings,
        market_state_cache: MarketStateCache | None = None,
    ) -> "KalshiWebSocketClient":
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
                raise KalshiWebSocketError(
                    "Provide either KALSHI_PRIVATE_KEY_PEM or KALSHI_PRIVATE_KEY_PATH."
                )
        except AuthManagerError as exc:
            raise KalshiWebSocketError(str(exc)) from exc

        return cls(
            ws_url=settings.ws_url,
            auth_manager=auth_manager,
            market_state_cache=market_state_cache or MarketStateCache(),
            message_limit=settings.ws_message_limit,
            receive_timeout_seconds=settings.ws_receive_timeout_seconds,
            max_reconnect_attempts=settings.ws_max_reconnect_attempts,
            reconnect_initial_delay_seconds=settings.ws_reconnect_initial_delay_seconds,
            reconnect_max_delay_seconds=settings.ws_reconnect_max_delay_seconds,
        )

    @property
    def market_state_cache(self) -> MarketStateCache:
        return self._cache

    async def connect(self) -> None:
        headers = self._auth_manager.auth_headers(method="GET", path=WS_AUTH_PATH)
        self._connection = await websockets.connect(
            self._ws_url,
            additional_headers=headers,
        )

    async def disconnect(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def subscribe(
        self,
        *,
        market_tickers: tuple[str, ...],
        channels: tuple[str, ...] = DEFAULT_CHANNELS,
    ) -> int:
        if self._connection is None:
            raise KalshiWebSocketError("WebSocket is not connected.")
        if not market_tickers:
            raise KalshiWebSocketError("At least one market ticker is required.")

        invalid_channels = sorted(set(channels) - ALLOWED_CHANNELS)
        if invalid_channels:
            raise KalshiWebSocketError("Unsupported WebSocket channel requested.")

        command_id = self._next_command_id
        self._next_command_id += 1
        message = {
            "id": command_id,
            "cmd": "subscribe",
            "params": {
                "channels": list(channels),
                "market_tickers": list(market_tickers),
            },
        }
        await self._connection.send(json.dumps(message))
        return command_id

    async def run(
        self,
        *,
        market_tickers: tuple[str, ...],
        channels: tuple[str, ...] = DEFAULT_CHANNELS,
        message_limit: int | None = None,
    ) -> WebSocketRunResult:
        limit = message_limit or self._message_limit
        attempts = 0
        delay = self._reconnect_initial_delay_seconds
        result = WebSocketRunResult()

        subscribed_tickers = tuple(dict.fromkeys(market_tickers))
        result = _with_subscribed_market_tickers(result, subscribed_tickers)

        while result.market_data_messages < limit:
            try:
                await self.connect()
                await self.subscribe(market_tickers=subscribed_tickers, channels=channels)
                result = await self._receive_until_limit(limit=limit, result=result)
                break
            except (ConnectionClosed, OSError, WebSocketException) as exc:
                attempts += 1
                if attempts > self._max_reconnect_attempts:
                    raise KalshiWebSocketError(
                        "Kalshi WebSocket disconnected after maximum reconnect attempts."
                    ) from exc
                result = _increment_result(result, reconnects=1)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._reconnect_max_delay_seconds)
            finally:
                await self.disconnect()

        return result

    async def _receive_until_limit(
        self,
        *,
        limit: int,
        result: WebSocketRunResult,
    ) -> WebSocketRunResult:
        if self._connection is None:
            raise KalshiWebSocketError("WebSocket is not connected.")

        while result.market_data_messages < limit:
            try:
                raw_message = await asyncio.wait_for(
                    self._connection.recv(),
                    timeout=self._receive_timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                if result.messages_received > 0:
                    return _increment_result(result, timed_out=True)
                raise KalshiWebSocketError("Timed out waiting for WebSocket data.") from exc

            parsed = parse_ws_message(raw_message)
            if isinstance(parsed, ErrorMessage):
                raise KalshiWebSocketError(
                    f"Kalshi WebSocket error {parsed.code}: {parsed.message}"
                )

            self._apply_message(parsed)
            result = _count_message(result, parsed)

        return result

    def _apply_message(self, message: ParsedMessage) -> None:
        try:
            if isinstance(message, TickerMessage):
                self._cache.update_ticker(
                    market_ticker=message.market_ticker,
                    market_id=message.market_id,
                    price_dollars=message.price_dollars,
                    yes_bid_dollars=message.yes_bid_dollars,
                    yes_ask_dollars=message.yes_ask_dollars,
                    yes_bid_size_fp=message.yes_bid_size_fp,
                    yes_ask_size_fp=message.yes_ask_size_fp,
                    volume_fp=message.volume_fp,
                    open_interest_fp=message.open_interest_fp,
                    dollar_volume=message.dollar_volume,
                    dollar_open_interest=message.dollar_open_interest,
                    last_trade_size_fp=message.last_trade_size_fp,
                    exchange_ts=message.exchange_ts,
                    exchange_time=message.exchange_time,
                    sid=message.sid,
                    seq=message.seq,
                )
            elif isinstance(message, OrderbookSnapshotMessage):
                self._cache.replace_orderbook(
                    market_ticker=message.market_ticker,
                    market_id=message.market_id,
                    yes_levels=tuple(
                        (level.price_dollars, level.quantity_fp)
                        for level in message.yes_levels
                    ),
                    no_levels=tuple(
                        (level.price_dollars, level.quantity_fp)
                        for level in message.no_levels
                    ),
                    sid=message.sid,
                    seq=message.seq,
                )
            elif isinstance(message, OrderbookDeltaMessage):
                self._cache.apply_orderbook_delta(
                    market_ticker=message.market_ticker,
                    market_id=message.market_id,
                    side=message.side,
                    price_dollars=message.price_dollars,
                    delta_fp=message.delta_fp,
                    sid=message.sid,
                    seq=message.seq,
                )
        except MarketStateCacheError as exc:
            raise KalshiWebSocketError(str(exc)) from exc


def parse_ws_message(raw_message: str | bytes) -> ParsedMessage:
    try:
        decoded = raw_message.decode("utf-8") if isinstance(raw_message, bytes) else raw_message
        data = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KalshiWebSocketError("Received malformed WebSocket JSON.") from exc

    if not isinstance(data, dict):
        raise KalshiWebSocketError("WebSocket message must be a JSON object.")

    message_type = _required_str(data, "type")
    if message_type == "ticker":
        return _parse_ticker(data)
    if message_type == "orderbook_snapshot":
        return _parse_orderbook_snapshot(data)
    if message_type == "orderbook_delta":
        return _parse_orderbook_delta(data)
    if message_type == "subscribed":
        return _parse_subscribed(data)
    if message_type == "error":
        return _parse_error(data)
    return UnsupportedMessage(message_type=message_type)


def _parse_ticker(data: dict[str, Any]) -> TickerMessage:
    msg = _required_msg(data)
    return TickerMessage(
        market_ticker=_required_str(msg, "market_ticker"),
        market_id=_optional_str(msg, "market_id"),
        price_dollars=_optional_str(msg, "price_dollars"),
        yes_bid_dollars=_optional_str(msg, "yes_bid_dollars"),
        yes_ask_dollars=_optional_str(msg, "yes_ask_dollars"),
        yes_bid_size_fp=_optional_str(msg, "yes_bid_size_fp"),
        yes_ask_size_fp=_optional_str(msg, "yes_ask_size_fp"),
        volume_fp=_optional_str(msg, "volume_fp"),
        open_interest_fp=_optional_str(msg, "open_interest_fp"),
        dollar_volume=_optional_int_or_str(msg, "dollar_volume"),
        dollar_open_interest=_optional_int_or_str(msg, "dollar_open_interest"),
        last_trade_size_fp=_optional_str(msg, "last_trade_size_fp"),
        exchange_ts=_optional_int(msg, "ts"),
        exchange_time=_optional_str(msg, "time"),
        sid=_optional_int(data, "sid"),
        seq=_optional_int(data, "seq"),
    )


def _parse_orderbook_snapshot(data: dict[str, Any]) -> OrderbookSnapshotMessage:
    msg = _required_msg(data)
    yes_levels, no_levels = _extract_orderbook_sides(msg)
    return OrderbookSnapshotMessage(
        market_ticker=_required_str(msg, "market_ticker"),
        market_id=_optional_str(msg, "market_id"),
        yes_levels=_parse_levels(yes_levels),
        no_levels=_parse_levels(no_levels),
        sid=_optional_int(data, "sid"),
        seq=_optional_int(data, "seq"),
    )


def _parse_orderbook_delta(data: dict[str, Any]) -> OrderbookDeltaMessage:
    msg = _required_msg(data)
    return OrderbookDeltaMessage(
        market_ticker=_required_str(msg, "market_ticker"),
        market_id=_optional_str(msg, "market_id"),
        side=_required_str(msg, "side"),
        price_dollars=_required_str(msg, "price_dollars"),
        delta_fp=_required_str(msg, "delta_fp"),
        ts=_optional_str(msg, "ts"),
        sid=_optional_int(data, "sid"),
        seq=_optional_int(data, "seq"),
    )


def _parse_subscribed(data: dict[str, Any]) -> SubscribedMessage:
    msg = data.get("msg")
    channels: tuple[str, ...] = ()
    sid = _optional_int(data, "sid")
    if isinstance(msg, dict):
        raw_channels = msg.get("channels", ())
        if isinstance(raw_channels, list):
            channels = tuple(str(channel) for channel in raw_channels)
        elif msg.get("channel") is not None:
            channels = (str(msg["channel"]),)
        if sid is None:
            sid = _optional_int(msg, "sid")
    return SubscribedMessage(
        command_id=_optional_int(data, "id"),
        sid=sid,
        channels=channels,
    )


def _parse_error(data: dict[str, Any]) -> ErrorMessage:
    msg = data.get("msg")
    if not isinstance(msg, dict):
        return ErrorMessage(
            command_id=_optional_int(data, "id"),
            code=None,
            message="Unknown WebSocket error.",
        )
    return ErrorMessage(
        command_id=_optional_int(data, "id"),
        code=msg.get("code"),
        message=str(msg.get("msg", "Unknown WebSocket error.")),
    )


def _extract_orderbook_sides(msg: dict[str, Any]) -> tuple[Any, Any]:
    direct_pairs = (
        ("yes_dollars_fp", "no_dollars_fp"),
        ("yes_dollars", "no_dollars"),
        ("yes", "no"),
    )
    for yes_key, no_key in direct_pairs:
        if yes_key in msg or no_key in msg:
            return msg.get(yes_key), msg.get(no_key)

    nested_candidates = (
        ("orderbook_fp", (("yes_dollars", "no_dollars"), ("yes", "no"))),
        ("orderbook", (("yes", "no"), ("yes_dollars", "no_dollars"))),
    )
    for container_key, side_pairs in nested_candidates:
        container = msg.get(container_key)
        if not isinstance(container, dict):
            continue
        for yes_key, no_key in side_pairs:
            if yes_key in container or no_key in container:
                return container.get(yes_key), container.get(no_key)

    return None, None


def _parse_levels(raw_levels: Any) -> tuple[PriceLevel, ...]:
    if raw_levels is None:
        return ()
    if isinstance(raw_levels, dict):
        return tuple(
            PriceLevel(price_dollars=str(price), quantity_fp=str(quantity))
            for price, quantity in raw_levels.items()
        )
    if not isinstance(raw_levels, (list, tuple)):
        raise KalshiWebSocketError("Orderbook levels must be a list, tuple, or mapping.")

    levels: list[PriceLevel] = []
    for raw_level in raw_levels:
        if not isinstance(raw_level, (list, tuple)) or len(raw_level) != 2:
            raise KalshiWebSocketError("Orderbook levels must contain price/quantity pairs.")
        levels.append(
            PriceLevel(
                price_dollars=str(raw_level[0]),
                quantity_fp=str(raw_level[1]),
            )
        )
    return tuple(levels)


def _required_msg(data: dict[str, Any]) -> dict[str, Any]:
    msg = data.get("msg")
    if not isinstance(msg, dict):
        raise KalshiWebSocketError("WebSocket message is missing object field 'msg'.")
    return msg


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if value is None:
        raise KalshiWebSocketError(f"WebSocket message is missing field '{key}'.")
    return str(value)


def _optional_str(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    return str(value)


def _optional_int(data: dict[str, Any], key: str) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise KalshiWebSocketError(f"WebSocket field '{key}' must be an integer.") from exc


def _optional_int_or_str(data: dict[str, Any], key: str) -> int | str | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return str(value)


def _count_message(result: WebSocketRunResult, message: ParsedMessage) -> WebSocketRunResult:
    is_market_data = isinstance(
        message,
        (TickerMessage, OrderbookSnapshotMessage, OrderbookDeltaMessage),
    )
    return _increment_result(
        result,
        messages_received=1,
        market_data_messages=1 if is_market_data else 0,
        ticker_messages=1 if isinstance(message, TickerMessage) else 0,
        orderbook_snapshots=1 if isinstance(message, OrderbookSnapshotMessage) else 0,
        orderbook_deltas=1 if isinstance(message, OrderbookDeltaMessage) else 0,
        subscription_messages=1 if isinstance(message, SubscribedMessage) else 0,
        unsupported_messages=1 if isinstance(message, UnsupportedMessage) else 0,
    )


def _increment_result(
    result: WebSocketRunResult,
    *,
    messages_received: int = 0,
    market_data_messages: int = 0,
    ticker_messages: int = 0,
    orderbook_snapshots: int = 0,
    orderbook_deltas: int = 0,
    subscription_messages: int = 0,
    unsupported_messages: int = 0,
    reconnects: int = 0,
    timed_out: bool = False,
) -> WebSocketRunResult:
    return WebSocketRunResult(
        messages_received=result.messages_received + messages_received,
        market_data_messages=result.market_data_messages + market_data_messages,
        ticker_messages=result.ticker_messages + ticker_messages,
        orderbook_snapshots=result.orderbook_snapshots + orderbook_snapshots,
        orderbook_deltas=result.orderbook_deltas + orderbook_deltas,
        subscription_messages=result.subscription_messages + subscription_messages,
        unsupported_messages=result.unsupported_messages + unsupported_messages,
        reconnects=result.reconnects + reconnects,
        timed_out=result.timed_out or timed_out,
        subscribed_market_tickers=result.subscribed_market_tickers,
    )


def _with_subscribed_market_tickers(
    result: WebSocketRunResult,
    subscribed_market_tickers: tuple[str, ...],
) -> WebSocketRunResult:
    return WebSocketRunResult(
        messages_received=result.messages_received,
        market_data_messages=result.market_data_messages,
        ticker_messages=result.ticker_messages,
        orderbook_snapshots=result.orderbook_snapshots,
        orderbook_deltas=result.orderbook_deltas,
        subscription_messages=result.subscription_messages,
        unsupported_messages=result.unsupported_messages,
        reconnects=result.reconnects,
        timed_out=result.timed_out,
        subscribed_market_tickers=subscribed_market_tickers,
    )
