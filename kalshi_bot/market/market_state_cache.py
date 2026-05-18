"""In-memory Kalshi market state cache."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation


class MarketStateCacheError(ValueError):
    pass


@dataclass(frozen=True)
class TickerState:
    market_ticker: str
    market_id: str | None = None
    price_dollars: Decimal | None = None
    yes_bid_dollars: Decimal | None = None
    yes_ask_dollars: Decimal | None = None
    yes_bid_size_fp: Decimal | None = None
    yes_ask_size_fp: Decimal | None = None
    volume_fp: Decimal | None = None
    open_interest_fp: Decimal | None = None
    dollar_volume: Decimal | None = None
    dollar_open_interest: Decimal | None = None
    last_trade_size_fp: Decimal | None = None
    exchange_ts: int | None = None
    exchange_time: str | None = None
    local_receive_timestamp: str | None = None
    sid: int | None = None
    seq: int | None = None


@dataclass
class OrderBookState:
    market_ticker: str
    market_id: str | None = None
    yes: dict[Decimal, Decimal] = field(default_factory=dict)
    no: dict[Decimal, Decimal] = field(default_factory=dict)
    sid: int | None = None
    seq: int | None = None
    local_receive_timestamp: str | None = None


@dataclass(frozen=True)
class MarketStateSnapshot:
    tickers: dict[str, TickerState]
    orderbooks: dict[str, OrderBookState]
    last_sequence_by_sid: dict[int, int]


class MarketStateCache:
    def __init__(self) -> None:
        self._tickers: dict[str, TickerState] = {}
        self._orderbooks: dict[str, OrderBookState] = {}
        self._last_sequence_by_sid: dict[int, int] = {}

    def update_ticker(
        self,
        *,
        market_ticker: str,
        market_id: str | None = None,
        price_dollars: str | None = None,
        yes_bid_dollars: str | None = None,
        yes_ask_dollars: str | None = None,
        yes_bid_size_fp: str | None = None,
        yes_ask_size_fp: str | None = None,
        volume_fp: str | None = None,
        open_interest_fp: str | None = None,
        dollar_volume: int | str | None = None,
        dollar_open_interest: int | str | None = None,
        last_trade_size_fp: str | None = None,
        exchange_ts: int | None = None,
        exchange_time: str | None = None,
        local_receive_timestamp: str | None = None,
        sid: int | None = None,
        seq: int | None = None,
    ) -> None:
        self._require_market_ticker(market_ticker)
        self._tickers[market_ticker] = TickerState(
            market_ticker=market_ticker,
            market_id=market_id,
            price_dollars=_optional_decimal(price_dollars),
            yes_bid_dollars=_optional_decimal(yes_bid_dollars),
            yes_ask_dollars=_optional_decimal(yes_ask_dollars),
            yes_bid_size_fp=_optional_decimal(yes_bid_size_fp),
            yes_ask_size_fp=_optional_decimal(yes_ask_size_fp),
            volume_fp=_optional_decimal(volume_fp),
            open_interest_fp=_optional_decimal(open_interest_fp),
            dollar_volume=_optional_decimal(dollar_volume),
            dollar_open_interest=_optional_decimal(dollar_open_interest),
            last_trade_size_fp=_optional_decimal(last_trade_size_fp),
            exchange_ts=exchange_ts,
            exchange_time=exchange_time,
            local_receive_timestamp=local_receive_timestamp,
            sid=sid,
            seq=seq,
        )
        self._track_sequence(sid, seq)

    def replace_orderbook(
        self,
        *,
        market_ticker: str,
        yes_levels: tuple[tuple[str, str], ...],
        no_levels: tuple[tuple[str, str], ...],
        market_id: str | None = None,
        sid: int | None = None,
        seq: int | None = None,
        local_receive_timestamp: str | None = None,
    ) -> None:
        self._require_market_ticker(market_ticker)
        self._orderbooks[market_ticker] = OrderBookState(
            market_ticker=market_ticker,
            market_id=market_id,
            yes=_levels_to_book(yes_levels),
            no=_levels_to_book(no_levels),
            sid=sid,
            seq=seq,
            local_receive_timestamp=local_receive_timestamp,
        )
        self._track_sequence(sid, seq)
        self._normalize_orderbook_ticker(market_ticker)

    def apply_orderbook_delta(
        self,
        *,
        market_ticker: str,
        side: str,
        price_dollars: str,
        delta_fp: str,
        market_id: str | None = None,
        sid: int | None = None,
        seq: int | None = None,
        local_receive_timestamp: str | None = None,
    ) -> None:
        self._require_market_ticker(market_ticker)
        normalized_side = side.lower()
        if normalized_side not in {"yes", "no"}:
            raise MarketStateCacheError("Orderbook side must be 'yes' or 'no'.")

        orderbook = self._orderbooks.setdefault(
            market_ticker,
            OrderBookState(market_ticker=market_ticker, market_id=market_id),
        )
        if market_id is not None:
            orderbook.market_id = market_id
        orderbook.sid = sid
        orderbook.seq = seq
        orderbook.local_receive_timestamp = local_receive_timestamp

        book_side = orderbook.yes if normalized_side == "yes" else orderbook.no
        price = _required_decimal(price_dollars)
        delta = _required_decimal(delta_fp)
        next_quantity = book_side.get(price, Decimal("0")) + delta

        if next_quantity < 0:
            raise MarketStateCacheError("Orderbook delta produced a negative quantity.")
        if next_quantity == 0:
            book_side.pop(price, None)
        else:
            book_side[price] = next_quantity

        self._track_sequence(sid, seq)
        self._normalize_orderbook_ticker(market_ticker)

    def ticker(self, market_ticker: str) -> TickerState | None:
        return self._tickers.get(market_ticker)

    def orderbook(self, market_ticker: str) -> OrderBookState | None:
        return self._orderbooks.get(market_ticker)

    def market_tickers(self) -> tuple[str, ...]:
        return tuple(sorted(set(self._tickers) | set(self._orderbooks)))

    def retain_markets(self, market_tickers: tuple[str, ...]) -> None:
        retained = set(market_tickers)
        for market_ticker in tuple(self._tickers):
            if market_ticker not in retained:
                self._tickers.pop(market_ticker, None)
        for market_ticker in tuple(self._orderbooks):
            if market_ticker not in retained:
                self._orderbooks.pop(market_ticker, None)

    def snapshot(self) -> MarketStateSnapshot:
        return MarketStateSnapshot(
            tickers=dict(self._tickers),
            orderbooks={
                ticker: OrderBookState(
                    market_ticker=state.market_ticker,
                    market_id=state.market_id,
                    yes=dict(state.yes),
                    no=dict(state.no),
                    sid=state.sid,
                    seq=state.seq,
                )
                for ticker, state in self._orderbooks.items()
            },
            last_sequence_by_sid=dict(self._last_sequence_by_sid),
        )

    def _track_sequence(self, sid: int | None, seq: int | None) -> None:
        if sid is not None and seq is not None:
            self._last_sequence_by_sid[sid] = seq

    def _normalize_orderbook_ticker(self, market_ticker: str) -> None:
        orderbook = self._orderbooks[market_ticker]
        yes_bid = _best_bid(orderbook.yes)
        no_bid = _best_bid(orderbook.no)
        yes_ask_dollars = None
        yes_ask_size_fp = None
        if no_bid is not None:
            no_bid_dollars, no_bid_size_fp = no_bid
            yes_ask_dollars = Decimal("1") - no_bid_dollars
            yes_ask_size_fp = no_bid_size_fp

        existing = self._tickers.get(market_ticker)
        if existing is None:
            self._tickers[market_ticker] = TickerState(
                market_ticker=market_ticker,
                market_id=orderbook.market_id,
                yes_bid_dollars=yes_bid[0] if yes_bid is not None else None,
                yes_ask_dollars=yes_ask_dollars,
                yes_bid_size_fp=yes_bid[1] if yes_bid is not None else None,
                yes_ask_size_fp=yes_ask_size_fp,
                sid=orderbook.sid,
                seq=orderbook.seq,
            )
            return

        self._tickers[market_ticker] = replace(
            existing,
            market_id=orderbook.market_id or existing.market_id,
            yes_bid_dollars=yes_bid[0] if yes_bid is not None else None,
            yes_ask_dollars=yes_ask_dollars,
            yes_bid_size_fp=yes_bid[1] if yes_bid is not None else None,
            yes_ask_size_fp=yes_ask_size_fp,
            sid=orderbook.sid,
            seq=orderbook.seq,
        )

    @staticmethod
    def _require_market_ticker(market_ticker: str) -> None:
        if not market_ticker.strip():
            raise MarketStateCacheError("market_ticker is required.")


def _levels_to_book(levels: tuple[tuple[str, str], ...]) -> dict[Decimal, Decimal]:
    book: dict[Decimal, Decimal] = {}
    for price_text, quantity_text in levels:
        price = _required_decimal(price_text)
        quantity = _required_decimal(quantity_text)
        if quantity < 0:
            raise MarketStateCacheError("Orderbook quantity cannot be negative.")
        if quantity > 0:
            book[price] = quantity
    return book


def _best_bid(book: dict[Decimal, Decimal]) -> tuple[Decimal, Decimal] | None:
    if not book:
        return None
    return max(book.items(), key=lambda level: level[0])


def _optional_decimal(value: int | str | None) -> Decimal | None:
    if value is None:
        return None
    return _required_decimal(value)


def _required_decimal(value: int | str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise MarketStateCacheError("Invalid fixed-point decimal value.") from exc
