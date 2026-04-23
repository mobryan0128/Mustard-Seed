"""Smoke-test the external crypto feed and in-memory state updates."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from websockets.exceptions import WebSocketException

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi_bot.clients.crypto_feed_client import (  # noqa: E402
    CryptoFeedClient,
    CryptoFeedClientError,
)
from kalshi_bot.config.settings import SettingsError, load_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate external crypto feed updates.")
    parser.add_argument(
        "--message-limit",
        type=int,
        default=None,
        help="Maximum number of feed messages to process.",
    )
    args = parser.parse_args()

    try:
        settings = load_settings()
        client = CryptoFeedClient.from_settings(settings)
        result = asyncio.run(client.run(message_limit=args.message_limit))
    except (SettingsError, CryptoFeedClientError, WebSocketException) as exc:
        print(f"Crypto feed check failed: {exc}", file=sys.stderr)
        return 1

    snapshot = client.snapshot()
    print("Crypto feed check succeeded.")
    print(f"subscribed_channels={','.join(snapshot.subscribed_channels)}")
    print(f"messages_received={result.messages_received}")
    print(f"ticker_updates={result.ticker_updates}")
    print(f"heartbeat_updates={result.heartbeat_updates}")
    print(f"unsupported_messages={result.unsupported_messages}")
    print(f"reconnects={result.reconnects}")
    print(f"products_updated={len(snapshot.products)}")
    for product_id in sorted(snapshot.products):
        state = snapshot.products[product_id]
        print(
            f"{product_id} "
            f"price={'yes' if state.price is not None else 'no'} "
            f"bid={'yes' if state.best_bid is not None else 'no'} "
            f"ask={'yes' if state.best_ask is not None else 'no'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
