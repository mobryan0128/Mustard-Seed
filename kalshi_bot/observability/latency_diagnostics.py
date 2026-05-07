"""Rate-limited latency diagnostics for feed repricing audits."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Deque

from kalshi_bot.market.market_state_cache import OrderBookState, TickerState
from kalshi_bot.observability.logger import StructuredLogger, StructuredLoggerError
from kalshi_bot.observability.replay_engine import ReplayEngine, ReplayEngineError


BASIS_POINTS_MULTIPLIER = Decimal("10000")
SPOT_HISTORY_SECONDS = 6
SPOT_RETURN_WINDOWS_SECONDS = (1, 3, 5)


@dataclass(frozen=True)
class _SpotObservation:
    received_at: datetime
    price: Decimal


class LatencyDiagnostics:
    """Emit sampled raw feed observations without affecting trading behavior."""

    def __init__(
        self,
        *,
        enabled: bool,
        sample_interval_ms: int,
        min_spot_move_bps: Decimal,
        max_depth_levels: int,
        logger: StructuredLogger | None = None,
        replay_engine: ReplayEngine | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._enabled = enabled
        self._sample_interval_seconds = Decimal(sample_interval_ms) / Decimal("1000")
        self._min_spot_move_bps = min_spot_move_bps
        self._max_depth_levels = max_depth_levels
        self._logger = logger
        self._replay_engine = replay_engine
        self._monotonic = monotonic or time.monotonic
        self._last_emit_by_key: dict[tuple[str, str, str], float] = {}
        self._spot_history_by_product: dict[str, Deque[_SpotObservation]] = {}

    @classmethod
    def from_settings(
        cls,
        settings: Any,
        *,
        logger: StructuredLogger | None = None,
        replay_engine: ReplayEngine | None = None,
    ) -> "LatencyDiagnostics":
        return cls(
            enabled=bool(getattr(settings, "latency_diagnostics_enabled", False)),
            sample_interval_ms=int(
                getattr(settings, "latency_diagnostics_sample_interval_ms", 1000)
            ),
            min_spot_move_bps=Decimal(
                str(getattr(settings, "latency_diagnostics_min_spot_move_bps", "5"))
            ),
            max_depth_levels=int(
                getattr(settings, "latency_diagnostics_max_depth_levels", 3)
            ),
            logger=logger,
            replay_engine=replay_engine,
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

    def record_spot_update(
        self,
        *,
        product_id: str,
        price: Decimal | None,
        best_bid: Decimal | None,
        best_ask: Decimal | None,
        best_bid_quantity: Decimal | None,
        best_ask_quantity: Decimal | None,
        source_timestamp: str | None,
        sequence_num: int | None,
        local_receive_timestamp: datetime,
    ) -> None:
        if not self._enabled:
            return

        local_receive_timestamp = _ensure_utc(local_receive_timestamp)
        returns = self._spot_return_payload(
            product_id=product_id,
            price=price,
            received_at=local_receive_timestamp,
        )
        if not self._should_emit(
            ("spot", product_id, "spot_update_received"),
            now=self._monotonic(),
        ):
            return

        threshold_met = any(
            abs(value) >= self._min_spot_move_bps
            for value in returns.values()
            if value is not None
        )
        payload = {
            "product_id": product_id,
            "price": price,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "best_bid_quantity": best_bid_quantity,
            "best_ask_quantity": best_ask_quantity,
            "source_timestamp": source_timestamp,
            "local_receive_timestamp": local_receive_timestamp,
            "spot_receive_timestamp": local_receive_timestamp,
            "sequence_num": sequence_num,
            "spot_move_threshold_bps": self._min_spot_move_bps,
            "spot_move_threshold_met": threshold_met,
            **returns,
        }
        self._emit(
            event_type="spot_update_received",
            source="coinbase_spot",
            identifier=product_id,
            payload=payload,
            recorded_at=local_receive_timestamp,
        )

    def record_kalshi_market_update(
        self,
        *,
        message_type: str,
        market_ticker: str,
        market_id: str | None,
        sid: int | None,
        seq: int | None,
        local_receive_timestamp: datetime,
        ticker_state: TickerState | None,
        orderbook: OrderBookState | None,
        exchange_time: str | None = None,
        exchange_ts: int | None = None,
        message_ts: str | None = None,
    ) -> None:
        if not self._enabled:
            return
        if not self._should_emit(
            ("kalshi", market_ticker, message_type),
            now=self._monotonic(),
        ):
            return

        local_receive_timestamp = _ensure_utc(local_receive_timestamp)
        payload = {
            "message_type": message_type,
            "market_ticker": market_ticker,
            "market_id": market_id,
            "sid": sid,
            "seq": seq,
            "exchange_time": exchange_time,
            "exchange_ts": exchange_ts,
            "message_ts": message_ts,
            "local_receive_timestamp": local_receive_timestamp,
            "kalshi_receive_timestamp": local_receive_timestamp,
            "orderbook_receive_timestamp": (
                local_receive_timestamp
                if message_type.startswith("orderbook")
                else None
            ),
            **_ticker_payload(ticker_state),
            **_orderbook_payload(
                orderbook,
                ticker_state=ticker_state,
                message_type=message_type,
                max_depth_levels=self._max_depth_levels,
            ),
        }
        self._emit(
            event_type="kalshi_market_update_received",
            source="kalshi_ws",
            identifier=market_ticker,
            payload=payload,
            recorded_at=local_receive_timestamp,
        )

    def _spot_return_payload(
        self,
        *,
        product_id: str,
        price: Decimal | None,
        received_at: datetime,
    ) -> dict[str, Decimal | None]:
        history = self._spot_history_by_product.setdefault(product_id, deque())
        if price is not None:
            history.append(_SpotObservation(received_at=received_at, price=price))
            cutoff = received_at - timedelta(seconds=SPOT_HISTORY_SECONDS)
            while history and history[0].received_at < cutoff:
                history.popleft()

        return {
            f"spot_move_bps_{window}s": _return_bps(
                current_price=price,
                anchor_price=_anchor_price(history, received_at, window),
            )
            for window in SPOT_RETURN_WINDOWS_SECONDS
        }

    def _should_emit(self, key: tuple[str, str, str], *, now: float) -> bool:
        previous = self._last_emit_by_key.get(key)
        if previous is not None:
            elapsed = Decimal(str(now - previous))
            if elapsed < self._sample_interval_seconds:
                return False
        self._last_emit_by_key[key] = now
        return True

    def _emit(
        self,
        *,
        event_type: str,
        source: str,
        identifier: str,
        payload: dict[str, object],
        recorded_at: datetime,
    ) -> None:
        if self._logger is not None:
            try:
                self._logger.log_event(
                    category="latency_diagnostics",
                    event_type=event_type,
                    source=source,
                    identifier=identifier,
                    payload=payload,
                    recorded_at=recorded_at,
                )
            except StructuredLoggerError:
                pass
        if self._replay_engine is not None:
            try:
                self._replay_engine.record_message(
                    source=source,
                    message_type=event_type,
                    identifier=identifier,
                    payload=payload,
                    recorded_at=recorded_at,
                )
            except ReplayEngineError:
                pass


def _ticker_payload(ticker_state: TickerState | None) -> dict[str, object]:
    if ticker_state is None:
        return {
            "ticker_present": False,
            "price_dollars": None,
            "ticker_yes_bid": None,
            "ticker_yes_ask": None,
            "ticker_yes_bid_size_fp": None,
            "ticker_yes_ask_size_fp": None,
            "ticker_exchange_time": None,
            "ticker_exchange_ts": None,
            "ticker_seq": None,
        }
    return {
        "ticker_present": True,
        "price_dollars": ticker_state.price_dollars,
        "ticker_yes_bid": ticker_state.yes_bid_dollars,
        "ticker_yes_ask": ticker_state.yes_ask_dollars,
        "ticker_yes_bid_size_fp": ticker_state.yes_bid_size_fp,
        "ticker_yes_ask_size_fp": ticker_state.yes_ask_size_fp,
        "ticker_exchange_time": ticker_state.exchange_time,
        "ticker_exchange_ts": ticker_state.exchange_ts,
        "ticker_seq": ticker_state.seq,
    }


def _orderbook_payload(
    orderbook: OrderBookState | None,
    *,
    ticker_state: TickerState | None,
    message_type: str,
    max_depth_levels: int,
) -> dict[str, object]:
    fallback = _ticker_top_of_book(ticker_state)
    if orderbook is None:
        return {
            "orderbook_present": False,
            "orderbook_status": "absent",
            "orderbook_empty_reason": "orderbook_absent",
            "orderbook_seq": None,
            "orderbook_sid": None,
            "orderbook_yes_level_count": 0,
            "orderbook_no_level_count": 0,
            **fallback,
            "yes_depth_levels": (),
            "no_depth_levels": (),
        }
    best_yes_bid = _best_bid(orderbook.yes)
    best_no_bid = _best_bid(orderbook.no)
    top_of_book = _orderbook_top_of_book(
        best_yes_bid=best_yes_bid,
        best_no_bid=best_no_bid,
        fallback=fallback,
    )
    status = _orderbook_status(orderbook)
    return {
        "orderbook_present": True,
        "orderbook_status": status,
        "orderbook_empty_reason": _orderbook_empty_reason(
            status=status,
            message_type=message_type,
        ),
        "orderbook_seq": orderbook.seq,
        "orderbook_sid": orderbook.sid,
        "orderbook_yes_level_count": len(orderbook.yes),
        "orderbook_no_level_count": len(orderbook.no),
        **top_of_book,
        "yes_depth_levels": _depth_levels(orderbook.yes, max_depth_levels),
        "no_depth_levels": _depth_levels(orderbook.no, max_depth_levels),
    }


def _ticker_top_of_book(ticker_state: TickerState | None) -> dict[str, object]:
    if ticker_state is None:
        return {
            "yes_bid": None,
            "yes_ask": None,
            "no_bid": None,
            "no_ask": None,
            "yes_bid_size_fp": None,
            "yes_ask_size_fp": None,
            "no_bid_size_fp": None,
            "no_ask_size_fp": None,
            "top_of_book_source": "unavailable",
        }
    no_bid = (
        Decimal("1") - ticker_state.yes_ask_dollars
        if ticker_state.yes_ask_dollars is not None
        else None
    )
    no_ask = (
        Decimal("1") - ticker_state.yes_bid_dollars
        if ticker_state.yes_bid_dollars is not None
        else None
    )
    return {
        "yes_bid": ticker_state.yes_bid_dollars,
        "yes_ask": ticker_state.yes_ask_dollars,
        "no_bid": no_bid,
        "no_ask": no_ask,
        "yes_bid_size_fp": ticker_state.yes_bid_size_fp,
        "yes_ask_size_fp": ticker_state.yes_ask_size_fp,
        "no_bid_size_fp": ticker_state.yes_ask_size_fp,
        "no_ask_size_fp": ticker_state.yes_bid_size_fp,
        "top_of_book_source": "ticker_fallback",
    }


def _orderbook_top_of_book(
    *,
    best_yes_bid: tuple[Decimal, Decimal] | None,
    best_no_bid: tuple[Decimal, Decimal] | None,
    fallback: dict[str, object],
) -> dict[str, object]:
    yes_bid = best_yes_bid[0] if best_yes_bid is not None else fallback["yes_bid"]
    yes_ask = (
        Decimal("1") - best_no_bid[0]
        if best_no_bid is not None
        else fallback["yes_ask"]
    )
    no_bid = best_no_bid[0] if best_no_bid is not None else fallback["no_bid"]
    no_ask = (
        Decimal("1") - best_yes_bid[0]
        if best_yes_bid is not None
        else fallback["no_ask"]
    )
    yes_bid_size = (
        best_yes_bid[1] if best_yes_bid is not None else fallback["yes_bid_size_fp"]
    )
    yes_ask_size = (
        best_no_bid[1] if best_no_bid is not None else fallback["yes_ask_size_fp"]
    )
    no_bid_size = (
        best_no_bid[1] if best_no_bid is not None else fallback["no_bid_size_fp"]
    )
    no_ask_size = (
        best_yes_bid[1] if best_yes_bid is not None else fallback["no_ask_size_fp"]
    )
    if best_yes_bid is not None or best_no_bid is not None:
        source = "orderbook"
    else:
        source = fallback["top_of_book_source"]
    return {
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "no_bid": no_bid,
        "no_ask": no_ask,
        "yes_bid_size_fp": yes_bid_size,
        "yes_ask_size_fp": yes_ask_size,
        "no_bid_size_fp": no_bid_size,
        "no_ask_size_fp": no_ask_size,
        "top_of_book_source": source,
    }


def _orderbook_status(orderbook: OrderBookState) -> str:
    yes_present = bool(orderbook.yes)
    no_present = bool(orderbook.no)
    if yes_present and no_present:
        return "populated"
    if yes_present:
        return "yes_side_only"
    if no_present:
        return "no_side_only"
    return "empty"


def _orderbook_empty_reason(*, status: str, message_type: str) -> str | None:
    if status != "empty":
        return None
    if message_type == "orderbook_snapshot":
        return "snapshot_no_levels_after_parse"
    if message_type == "orderbook_delta":
        return "delta_no_visible_levels_after_apply"
    return "unknown_empty_orderbook"


def _depth_levels(
    book: dict[Decimal, Decimal],
    max_depth_levels: int,
) -> tuple[dict[str, Decimal], ...]:
    return tuple(
        {"price_dollars": price, "quantity_fp": quantity}
        for price, quantity in sorted(book.items(), key=lambda item: item[0], reverse=True)[
            :max_depth_levels
        ]
    )


def _best_bid(book: dict[Decimal, Decimal]) -> tuple[Decimal, Decimal] | None:
    if not book:
        return None
    return max(book.items(), key=lambda level: level[0])


def _anchor_price(
    history: Deque[_SpotObservation],
    received_at: datetime,
    window_seconds: int,
) -> Decimal | None:
    if not history:
        return None
    target = received_at - timedelta(seconds=window_seconds)
    anchor: Decimal | None = None
    for observation in history:
        if observation.received_at <= target:
            anchor = observation.price
        else:
            break
    return anchor


def _return_bps(
    *,
    current_price: Decimal | None,
    anchor_price: Decimal | None,
) -> Decimal | None:
    if current_price is None or anchor_price is None or anchor_price <= Decimal("0"):
        return None
    return (
        (current_price - anchor_price) / anchor_price * BASIS_POINTS_MULTIPLIER
    ).quantize(Decimal("0.001"))


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
