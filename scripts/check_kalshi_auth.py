"""Smoke-test Kalshi authentication with a balance request."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi_bot.clients.kalshi_client import KalshiClient, KalshiClientError
from kalshi_bot.config.settings import SettingsError, load_settings


def main() -> int:
    try:
        settings = load_settings()
        client = KalshiClient.from_settings(settings)
        client.get_balance()
    except (SettingsError, KalshiClientError, httpx.HTTPError) as exc:
        print(f"Kalshi auth check failed: {exc}", file=sys.stderr)
        return 1

    print("Kalshi auth check succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
