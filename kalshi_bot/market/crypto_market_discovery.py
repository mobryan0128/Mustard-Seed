"""Kalshi crypto market discovery for runner-managed subscriptions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from kalshi_bot.clients.kalshi_client import (
    KalshiClient,
    KalshiClientError,
    KalshiMarketPage,
    KalshiMarketSummary,
)
from kalshi_bot.config.settings import KalshiSettings


DISCOVERY_PAGE_LIMIT = 1000


class CryptoMarketDiscoveryError(RuntimeError):
    """Raised when crypto market discovery fails."""


@dataclass(frozen=True)
class DiscoveredCryptoMarket:
    """One active Kalshi crypto market selected for runner use."""

    product_id: str
    series_ticker: str
    market_ticker: str
    close_time: str | None
    open_time: str | None
    expiration_time: str | None
    contract_target_price: Decimal | None = None
    title: str | None = None
    subtitle: str | None = None
    yes_sub_title: str | None = None
    no_sub_title: str | None = None
    target_source_field: str | None = None


@dataclass(frozen=True)
class CryptoMarketDiscoverySnapshot:
    """Effective product-to-market mapping from one discovery pass."""

    product_markets: dict[str, tuple[str, ...]]
    discovered_markets: tuple[DiscoveredCryptoMarket, ...]


class CryptoMarketDiscovery:
    """Discover active BTC/ETH Kalshi crypto duration markets."""

    def __init__(
        self,
        *,
        kalshi_client: KalshiClient,
        product_series: Mapping[str, tuple[str, ...]],
        products: tuple[str, ...],
        logger: Any | None = None,
    ) -> None:
        self._kalshi_client = kalshi_client
        self._logger = logger
        self._product_series = {
            product_id.strip(): tuple(
                dict.fromkeys(series.strip() for series in series_tickers if series.strip())
            )
            for product_id, series_tickers in product_series.items()
            if product_id.strip()
        }
        self._products = tuple(dict.fromkeys(product.strip() for product in products if product.strip()))

    @classmethod
    def from_settings(
        cls,
        settings: KalshiSettings,
        kalshi_client: KalshiClient,
        logger: Any | None = None,
    ) -> "CryptoMarketDiscovery":
        return cls(
            kalshi_client=kalshi_client,
            product_series=settings.crypto_market_series,
            products=settings.bias_products,
            logger=logger,
        )

    def discover(self) -> CryptoMarketDiscoverySnapshot:
        discovered: list[DiscoveredCryptoMarket] = []
        product_markets: dict[str, tuple[str, ...]] = {}

        for product_id in self._products:
            series_tickers = self._product_series.get(product_id, ())
            product_discovered: list[DiscoveredCryptoMarket] = []
            for series_ticker in series_tickers:
                product_discovered.extend(
                    self._discover_series(
                        product_id=product_id,
                        series_ticker=series_ticker,
                    )
                )
            product_discovered.sort(
                key=lambda market: (_close_time_sort_key(market.close_time), market.market_ticker)
            )
            tickers = tuple(dict.fromkeys(market.market_ticker for market in product_discovered))
            self._log_selected_tickers(
                product_id=product_id,
                series_tickers=series_tickers,
                selected_market_tickers=tickers,
            )
            if tickers:
                product_markets[product_id] = tickers
                discovered.extend(product_discovered)

        return CryptoMarketDiscoverySnapshot(
            product_markets=product_markets,
            discovered_markets=tuple(discovered),
        )

    def _discover_series(
        self,
        *,
        product_id: str,
        series_ticker: str,
    ) -> tuple[DiscoveredCryptoMarket, ...]:
        now = datetime.now(timezone.utc)
        markets: list[DiscoveredCryptoMarket] = []
        cursor: str | None = None
        while True:
            try:
                page = self._kalshi_client.get_markets(
                    series_ticker=series_ticker,
                    status="open",
                    limit=DISCOVERY_PAGE_LIMIT,
                    cursor=cursor,
                    mve_filter="exclude",
                )
            except KalshiClientError as exc:
                raise CryptoMarketDiscoveryError(str(exc)) from exc

            self._log_discovery_api_page(
                product_id=product_id,
                series_ticker=series_ticker,
                status="open",
                limit=DISCOVERY_PAGE_LIMIT,
                cursor_present=cursor is not None,
                mve_filter="exclude",
                page=page,
            )
            for market in page.markets:
                if not _is_currently_tradable_market(market, now):
                    continue
                markets.append(
                    DiscoveredCryptoMarket(
                        product_id=product_id,
                        series_ticker=series_ticker,
                        market_ticker=market.ticker,
                        close_time=market.close_time,
                        open_time=market.open_time,
                        expiration_time=market.expiration_time,
                        contract_target_price=market.contract_target_price,
                        title=market.title,
                        subtitle=market.subtitle,
                        yes_sub_title=market.yes_sub_title,
                        no_sub_title=market.no_sub_title,
                        target_source_field=market.target_source_field,
                    )
                )
            if page.cursor is None:
                break
            cursor = page.cursor
        return tuple(markets)

    def _log_discovery_api_page(
        self,
        *,
        product_id: str,
        series_ticker: str,
        status: str,
        limit: int,
        cursor_present: bool,
        mve_filter: str,
        page: KalshiMarketPage,
    ) -> None:
        if self._logger is None:
            return
        markets = page.markets
        self._logger.log_event(
            category="market_discovery",
            event_type="crypto_market_discovery_api_page",
            source="crypto_market_discovery",
            identifier=series_ticker,
            payload={
                "product_id": product_id,
                "series_ticker": series_ticker,
                "status": status,
                "limit": limit,
                "cursor_present": cursor_present,
                "mve_filter": mve_filter,
                "returned_cursor_present": page.cursor is not None,
                "normalized_market_count": len(markets),
                "normalized_market_ticker_sample": tuple(
                    market.ticker for market in markets[:10]
                ),
                "normalized_market_status_sample": tuple(
                    market.status for market in markets[:10]
                ),
            },
        )

    def _log_selected_tickers(
        self,
        *,
        product_id: str,
        series_tickers: tuple[str, ...],
        selected_market_tickers: tuple[str, ...],
    ) -> None:
        if self._logger is None:
            return
        self._logger.log_event(
            category="market_discovery",
            event_type="crypto_market_discovery_selected_tickers",
            source="crypto_market_discovery",
            identifier=product_id,
            payload={
                "product_id": product_id,
                "series_tickers": series_tickers,
                "selected_market_count": len(selected_market_tickers),
                "selected_market_tickers": selected_market_tickers,
            },
        )


def _close_time_sort_key(value: str | None) -> datetime:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return datetime.max.replace(tzinfo=timezone.utc)
    return parsed


def _is_currently_tradable_market(market: KalshiMarketSummary, now: datetime) -> bool:
    if _is_definitely_expired(market.close_time, now):
        return False

    if _is_definitely_expired(market.expiration_time, now):
        return False

    if _is_definitely_expired(market.latest_expiration_time, now):
        return False

    return True


def _is_definitely_expired(value: str | None, now: datetime) -> bool:
    parsed = _parse_aware_timestamp(value)
    return parsed is not None and parsed <= now


def _parse_aware_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
