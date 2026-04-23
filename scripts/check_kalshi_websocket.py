"""Smoke-test Kalshi WebSocket market data and in-memory state updates."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from websockets.exceptions import WebSocketException

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi_bot.clients.websocket_client import (  # noqa: E402
    KalshiWebSocketClient,
    KalshiWebSocketError,
)
from kalshi_bot.config.settings import SettingsError, load_settings  # noqa: E402
from kalshi_bot.market.market_state_cache import MarketStateCache  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Kalshi WebSocket market data.")
    parser.add_argument(
        "--market-ticker",
        action="append",
        default=[],
        help="Market ticker to subscribe to. May be passed more than once.",
    )
    parser.add_argument(
        "--market-tickers",
        default="",
        help="Comma-separated market tickers to subscribe to.",
    )
    parser.add_argument(
        "--message-limit",
        type=int,
        default=None,
        help="Maximum number of WebSocket messages to process.",
    )
    args = parser.parse_args()

    try:
        settings = load_settings()
        market_tickers = _resolve_market_tickers(
            args.market_ticker,
            args.market_tickers,
            settings.ws_market_tickers,
        )
        cache = MarketStateCache()
        client = KalshiWebSocketClient.from_settings(settings, market_state_cache=cache)
        result = asyncio.run(
            client.run(
                market_tickers=market_tickers,
                message_limit=args.message_limit or settings.ws_message_limit,
            )
        )
    except (SettingsError, KalshiWebSocketError, WebSocketException) as exc:
        print(f"Kalshi WebSocket check failed: {exc}", file=sys.stderr)
        return 1

    snapshot = cache.snapshot()
    print("Kalshi WebSocket check succeeded.")
    print(f"messages_received={result.messages_received}")
    print(f"subscription_messages={result.subscription_messages}")
    print(f"ticker_messages={result.ticker_messages}")
    print(f"orderbook_snapshots={result.orderbook_snapshots}")
    print(f"orderbook_deltas={result.orderbook_deltas}")
    print(f"unsupported_messages={result.unsupported_messages}")
    print(f"reconnects={result.reconnects}")
    print(f"markets_updated={len(snapshot.tickers) + len(snapshot.orderbooks)}")
    return 0


def _resolve_market_tickers(
    repeated_tickers: list[str],
    comma_tickers: str,
    env_tickers: tuple[str, ...],
) -> tuple[str, ...]:
    tickers: list[str] = []
    tickers.extend(repeated_tickers)
    tickers.extend(item.strip() for item in comma_tickers.split(",") if item.strip())
    if not tickers:
        tickers.extend(env_tickers)

    normalized = tuple(dict.fromkeys(ticker.strip() for ticker in tickers if ticker.strip()))
    if not normalized:
        raise KalshiWebSocketError(
            "Provide --market-ticker, --market-tickers, or KALSHI_WS_MARKET_TICKERS."
        )
    return normalized


if __name__ == "__main__":
    raise SystemExit(main())
