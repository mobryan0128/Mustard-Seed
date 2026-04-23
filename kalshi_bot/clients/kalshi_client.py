"""Minimal authenticated Kalshi HTTP client for Phase 1 validation."""

from __future__ import annotations

from urllib.parse import urljoin, urlsplit

import httpx

from kalshi_bot.auth.auth_manager import AuthManagerError, KalshiAuthManager
from kalshi_bot.config.settings import KalshiSettings


BALANCE_PATH = "/portfolio/balance"


class KalshiClientError(RuntimeError):
    pass


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
        try:
            payload = response.json()
        except ValueError as exc:
            raise KalshiClientError("Kalshi balance response was not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise KalshiClientError("Kalshi balance response was not a JSON object.")
        return payload

    def _get(self, path: str) -> httpx.Response:
        url = urljoin(self._base_url, path.lstrip("/"))
        sign_path = urlsplit(url).path
        headers = self._auth_manager.auth_headers(method="GET", path=sign_path)

        with httpx.Client(timeout=self._timeout_seconds) as client:
            response = client.get(url, headers=headers)

        if response.status_code >= 400:
            raise KalshiClientError(
                f"Kalshi authenticated request failed with status {response.status_code}."
            )

        return response
