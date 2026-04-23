"""Kalshi RSA-PSS authentication helpers."""

from __future__ import annotations

import base64
import time
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


class AuthManagerError(ValueError):
    """Raised when authentication material cannot be loaded or used."""


class KalshiAuthManager:
    """Build signed Kalshi authentication headers."""

    def __init__(self, api_key_id: str, private_key: rsa.RSAPrivateKey) -> None:
        if not api_key_id.strip():
            raise AuthManagerError("KALSHI_API_KEY_ID is required.")

        self._api_key_id = api_key_id
        self._private_key = private_key

    @classmethod
    def from_pem(
        cls,
        api_key_id: str,
        private_key_pem: str,
        passphrase: str | None = None,
    ) -> "KalshiAuthManager":
        private_key = _load_private_key(
            private_key_pem.encode("utf-8"),
            passphrase,
        )
        return cls(api_key_id=api_key_id, private_key=private_key)

    @classmethod
    def from_key_path(
        cls,
        api_key_id: str,
        private_key_path: str | Path,
        passphrase: str | None = None,
    ) -> "KalshiAuthManager":
        path = Path(private_key_path).expanduser()
        try:
            key_data = path.read_bytes()
        except OSError as exc:
            raise AuthManagerError("Unable to read Kalshi private key file.") from exc

        private_key = _load_private_key(key_data, passphrase)
        return cls(api_key_id=api_key_id, private_key=private_key)

    def auth_headers(self, method: str, path: str) -> dict[str, str]:
        timestamp = current_timestamp_ms()
        signature = self.sign(timestamp=timestamp, method=method, path=path)
        return {
            "KALSHI-ACCESS-KEY": self._api_key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
        }

    def sign(self, timestamp: str, method: str, path: str) -> str:
        path_without_query = path.split("?", 1)[0]
        message = f"{timestamp}{method.upper()}{path_without_query}".encode("utf-8")
        signature = self._private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("utf-8")


def current_timestamp_ms() -> str:
    return str(int(time.time() * 1000))


def _load_private_key(key_data: bytes, passphrase: str | None) -> rsa.RSAPrivateKey:
    password = passphrase.encode("utf-8") if passphrase else None
    try:
        private_key = serialization.load_pem_private_key(key_data, password=password)
    except (TypeError, ValueError) as exc:
        raise AuthManagerError("Unable to load Kalshi private key.") from exc

    if not isinstance(private_key, rsa.RSAPrivateKey):
        raise AuthManagerError("Kalshi private key must be an RSA private key.")

    return private_key
