"""Public external crypto price feed client using Coinbase Advanced Trade data."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple, Union

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from kalshi_bot.config.settings import KalshiSettings


TICKER_CHANNEL = "ticker"
HEARTBEATS_CHANNEL = "heartbeats"


class CryptoFeedClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class CryptoTickerUpdate:
    product_id: str
    price: Optional[Decimal]
    best_bid: Optional[Decimal]
    best_ask: Optional[Decimal]
    best_bid_quantity: Optional[Decimal]
    best_ask_quantity: Optional[Decimal]
    volume_24_h: Optional[Decimal]
    source_timestamp: Optional[str]
    sequence_num: Optional[int]


@dataclass(frozen=True)
class CryptoHeartbeatUpdate:
    current_time: Optional[str]
    heartbeat_counter: Optional[int]
    product_id: Optional[str]
    source_timestamp: Optional[str]
    sequence_num: Optional[int]


@dataclass(frozen=True)
class UnsupportedCryptoFeedMessage:
    channel: str
    event_type: Optional[str]


@dataclass(frozen=True)
class CryptoPriceState:
    product_id: str
    price: Optional[Decimal] = None
    best_bid: Optional[Decimal] = None
    best_ask: Optional[Decimal] = None
    best_bid_quantity: Optional[Decimal] = None
    best_ask_quantity: Optional[Decimal] = None
    volume_24_h: Optional[Decimal] = None
    source_timestamp: Optional[str] = None
    sequence_num: Optional[int] = None
    last_heartbeat_time: Optional[str] = None
    last_heartbeat_counter: Optional[int] = None


@dataclass(frozen=True)
class CryptoFeedSnapshot:
    products: Dict[str, CryptoPriceState]
    last_heartbeat_time: Optional[str]
    last_heartbeat_counter: Optional[int]
    subscribed_channels: Tuple[str, ...]


@dataclass(frozen=True)
class CryptoFeedRunResult:
    messages_received: int = 0
    ticker_updates: int = 0
    heartbeat_updates: int = 0
    unsupported_messages: int = 0
    reconnects: int = 0


ParsedCryptoFeedMessage = Union[
    CryptoTickerUpdate,
    CryptoHeartbeatUpdate,
    UnsupportedCryptoFeedMessage,
]


class CryptoFeedClient:
    def __init__(
        self,
        *,
        ws_url: str,
        products: Tuple[str, ...],
        message_limit: int,
        receive_timeout_seconds: float,
        max_reconnect_attempts: int,
        reconnect_initial_delay_seconds: float,
        reconnect_max_delay_seconds: float,
    ) -> None:
        normalized_products = tuple(
            dict.fromkeys(product.strip() for product in products if product.strip())
        )
        if not normalized_products:
            raise CryptoFeedClientError("At least one crypto feed product is required.")

        self._ws_url = ws_url.rstrip("/")
        self._products = normalized_products
        self._message_limit = message_limit
        self._receive_timeout_seconds = receive_timeout_seconds
        self._max_reconnect_attempts = max_reconnect_attempts
        self._reconnect_initial_delay_seconds = reconnect_initial_delay_seconds
        self._reconnect_max_delay_seconds = reconnect_max_delay_seconds
        self._connection: Any = None
        self._states: Dict[str, CryptoPriceState] = {}
        self._last_heartbeat_time: Optional[str] = None
        self._last_heartbeat_counter: Optional[int] = None
        self._subscribed_channels: Tuple[str, ...] = ()

    @classmethod
    def from_settings(cls, settings: KalshiSettings) -> "CryptoFeedClient":
        return cls(
            ws_url=settings.crypto_feed_ws_url,
            products=settings.crypto_feed_products,
            message_limit=settings.crypto_feed_message_limit,
            receive_timeout_seconds=settings.crypto_feed_receive_timeout_seconds,
            max_reconnect_attempts=settings.crypto_feed_max_reconnect_attempts,
            reconnect_initial_delay_seconds=settings.crypto_feed_reconnect_initial_delay_seconds,
            reconnect_max_delay_seconds=settings.crypto_feed_reconnect_max_delay_seconds,
        )

    @property
    def products(self) -> Tuple[str, ...]:
        return self._products

    async def connect(self) -> None:
        self._connection = await websockets.connect(self._ws_url)

    async def disconnect(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def subscribe(self) -> None:
        if self._connection is None:
            raise CryptoFeedClientError("Crypto feed WebSocket is not connected.")

        ticker_message = {
            "type": "subscribe",
            "channel": TICKER_CHANNEL,
            "product_ids": list(self._products),
        }
        heartbeat_message = {
            "type": "subscribe",
            "channel": HEARTBEATS_CHANNEL,
        }
        await self._connection.send(json.dumps(ticker_message))
        await self._connection.send(json.dumps(heartbeat_message))
        self._subscribed_channels = (TICKER_CHANNEL, HEARTBEATS_CHANNEL)

    async def run(self, message_limit: Optional[int] = None) -> CryptoFeedRunResult:
        limit = message_limit or self._message_limit
        attempts = 0
        delay = self._reconnect_initial_delay_seconds
        result = CryptoFeedRunResult()

        while result.messages_received < limit:
            try:
                await self.connect()
                await self.subscribe()
                result = await self._receive_until_limit(limit=limit, result=result)
                break
            except (ConnectionClosed, OSError, WebSocketException) as exc:
                attempts += 1
                if attempts > self._max_reconnect_attempts:
                    raise CryptoFeedClientError(
                        "Crypto feed disconnected after maximum reconnect attempts."
                    ) from exc
                result = _increment_run_result(result, reconnects=1)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._reconnect_max_delay_seconds)
            finally:
                await self.disconnect()

        return result

    def snapshot(self) -> CryptoFeedSnapshot:
        return CryptoFeedSnapshot(
            products=dict(self._states),
            last_heartbeat_time=self._last_heartbeat_time,
            last_heartbeat_counter=self._last_heartbeat_counter,
            subscribed_channels=self._subscribed_channels,
        )

    async def _receive_until_limit(
        self,
        *,
        limit: int,
        result: CryptoFeedRunResult,
    ) -> CryptoFeedRunResult:
        if self._connection is None:
            raise CryptoFeedClientError("Crypto feed WebSocket is not connected.")

        while result.messages_received < limit:
            try:
                raw_message = await asyncio.wait_for(
                    self._connection.recv(),
                    timeout=self._receive_timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                raise CryptoFeedClientError(
                    "Timed out waiting for external crypto feed data."
                ) from exc

            parsed_messages = parse_crypto_feed_message(raw_message)
            result = _increment_run_result(result, messages_received=1)
            for parsed_message in parsed_messages:
                self._apply_message(parsed_message)
                result = _count_parsed_message(result, parsed_message)

        return result

    def _apply_message(self, message: ParsedCryptoFeedMessage) -> None:
        if isinstance(message, CryptoTickerUpdate):
            current = self._states.get(
                message.product_id,
                CryptoPriceState(product_id=message.product_id),
            )
            self._states[message.product_id] = CryptoPriceState(
                product_id=message.product_id,
                price=_prefer(message.price, current.price),
                best_bid=_prefer(message.best_bid, current.best_bid),
                best_ask=_prefer(message.best_ask, current.best_ask),
                best_bid_quantity=_prefer(message.best_bid_quantity, current.best_bid_quantity),
                best_ask_quantity=_prefer(message.best_ask_quantity, current.best_ask_quantity),
                volume_24_h=_prefer(message.volume_24_h, current.volume_24_h),
                source_timestamp=_prefer(message.source_timestamp, current.source_timestamp),
                sequence_num=_prefer(message.sequence_num, current.sequence_num),
                last_heartbeat_time=current.last_heartbeat_time,
                last_heartbeat_counter=current.last_heartbeat_counter,
            )
            return

        if isinstance(message, CryptoHeartbeatUpdate):
            self._last_heartbeat_time = _prefer(message.current_time, self._last_heartbeat_time)
            self._last_heartbeat_counter = _prefer(
                message.heartbeat_counter,
                self._last_heartbeat_counter,
            )
            if message.product_id:
                current = self._states.get(
                    message.product_id,
                    CryptoPriceState(product_id=message.product_id),
                )
                self._states[message.product_id] = CryptoPriceState(
                    product_id=message.product_id,
                    price=current.price,
                    best_bid=current.best_bid,
                    best_ask=current.best_ask,
                    best_bid_quantity=current.best_bid_quantity,
                    best_ask_quantity=current.best_ask_quantity,
                    volume_24_h=current.volume_24_h,
                    source_timestamp=_prefer(message.source_timestamp, current.source_timestamp),
                    sequence_num=_prefer(message.sequence_num, current.sequence_num),
                    last_heartbeat_time=_prefer(message.current_time, current.last_heartbeat_time),
                    last_heartbeat_counter=_prefer(
                        message.heartbeat_counter,
                        current.last_heartbeat_counter,
                    ),
                )


def parse_crypto_feed_message(raw_message: Union[str, bytes]) -> Tuple[ParsedCryptoFeedMessage, ...]:
    try:
        decoded = raw_message.decode("utf-8") if isinstance(raw_message, bytes) else raw_message
        data = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CryptoFeedClientError("Received malformed crypto feed JSON.") from exc

    if not isinstance(data, dict):
        raise CryptoFeedClientError("Crypto feed message must be a JSON object.")

    channel = _required_str(data, "channel")
    events = data.get("events")
    if not isinstance(events, list):
        raise CryptoFeedClientError("Crypto feed message is missing list field 'events'.")

    timestamp = _optional_str(data, "timestamp")
    sequence_num = _optional_int(data, "sequence_num")
    parsed_messages: List[ParsedCryptoFeedMessage] = []

    if channel == TICKER_CHANNEL:
        for event in events:
            if not isinstance(event, dict):
                raise CryptoFeedClientError("Ticker event must be a JSON object.")
            tickers = event.get("tickers")
            if not isinstance(tickers, list):
                raise CryptoFeedClientError("Ticker event is missing list field 'tickers'.")
            for ticker in tickers:
                if not isinstance(ticker, dict):
                    raise CryptoFeedClientError("Ticker payload must be a JSON object.")
                parsed_messages.append(
                    CryptoTickerUpdate(
                        product_id=_required_str(ticker, "product_id"),
                        price=_optional_decimal(ticker, "price"),
                        best_bid=_optional_decimal(ticker, "best_bid"),
                        best_ask=_optional_decimal(ticker, "best_ask"),
                        best_bid_quantity=_optional_decimal(ticker, "best_bid_quantity"),
                        best_ask_quantity=_optional_decimal(ticker, "best_ask_quantity"),
                        volume_24_h=_optional_decimal(ticker, "volume_24_h"),
                        source_timestamp=timestamp,
                        sequence_num=sequence_num,
                    )
                )
        return tuple(parsed_messages)

    if channel == HEARTBEATS_CHANNEL:
        for event in events:
            if not isinstance(event, dict):
                raise CryptoFeedClientError("Heartbeat event must be a JSON object.")
            parsed_messages.append(
                CryptoHeartbeatUpdate(
                    current_time=_optional_str(event, "current_time"),
                    heartbeat_counter=_optional_int(event, "heartbeat_counter"),
                    product_id=_optional_str(event, "product_id"),
                    source_timestamp=timestamp,
                    sequence_num=sequence_num,
                )
            )
        return tuple(parsed_messages)

    event_type = None
    if events and isinstance(events[0], dict):
        event_type = _optional_str(events[0], "type")
    return (UnsupportedCryptoFeedMessage(channel=channel, event_type=event_type),)


def _required_str(data: Dict[str, Any], key: str) -> str:
    value = data.get(key)
    if value is None:
        raise CryptoFeedClientError(f"Crypto feed message is missing field '{key}'.")
    return str(value)


def _optional_str(data: Dict[str, Any], key: str) -> Optional[str]:
    value = data.get(key)
    if value is None:
        return None
    return str(value)


def _optional_int(data: Dict[str, Any], key: str) -> Optional[int]:
    value = data.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise CryptoFeedClientError(f"Crypto feed field '{key}' must be an integer.") from exc


def _optional_decimal(data: Dict[str, Any], key: str) -> Optional[Decimal]:
    value = data.get(key)
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CryptoFeedClientError(
            f"Crypto feed field '{key}' must be decimal-compatible."
        ) from exc


def _prefer(new_value: Any, existing_value: Any) -> Any:
    if new_value is None:
        return existing_value
    return new_value


def _count_parsed_message(
    result: CryptoFeedRunResult,
    message: ParsedCryptoFeedMessage,
) -> CryptoFeedRunResult:
    return _increment_run_result(
        result,
        ticker_updates=1 if isinstance(message, CryptoTickerUpdate) else 0,
        heartbeat_updates=1 if isinstance(message, CryptoHeartbeatUpdate) else 0,
        unsupported_messages=1 if isinstance(message, UnsupportedCryptoFeedMessage) else 0,
    )


def _increment_run_result(
    result: CryptoFeedRunResult,
    *,
    messages_received: int = 0,
    ticker_updates: int = 0,
    heartbeat_updates: int = 0,
    unsupported_messages: int = 0,
    reconnects: int = 0,
) -> CryptoFeedRunResult:
    return CryptoFeedRunResult(
        messages_received=result.messages_received + messages_received,
        ticker_updates=result.ticker_updates + ticker_updates,
        heartbeat_updates=result.heartbeat_updates + heartbeat_updates,
        unsupported_messages=result.unsupported_messages + unsupported_messages,
        reconnects=result.reconnects + reconnects,
    )
