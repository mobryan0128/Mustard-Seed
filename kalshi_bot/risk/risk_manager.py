"""Deterministic live-trading guardrails for Phase 10."""

from __future__ import annotations

from dataclasses import dataclass

from kalshi_bot.config.settings import KalshiSettings


@dataclass(frozen=True)
class LiveSafetyDecision:
    """Allow or deny one explicit live order submission."""

    allow: bool
    reason: str


class RiskManager:
    """Evaluate minimal live-trading safeguards before order submission."""

    def __init__(
        self,
        *,
        live_validation_enabled: bool,
        live_trading_enabled: bool,
        live_kill_switch_active: bool,
        env: str,
        live_validation_env: str,
        max_live_order_count: int = 1,
        required_time_in_force: str = "immediate_or_cancel",
    ) -> None:
        if max_live_order_count <= 0:
            raise ValueError("max_live_order_count must be greater than zero.")
        normalized_tif = required_time_in_force.strip().lower()
        if not normalized_tif:
            raise ValueError("required_time_in_force is required.")

        self._live_validation_enabled = live_validation_enabled
        self._live_trading_enabled = live_trading_enabled
        self._live_kill_switch_active = live_kill_switch_active
        self._env = env.strip().lower()
        self._live_validation_env = live_validation_env.strip().lower()
        self._max_live_order_count = max_live_order_count
        self._required_time_in_force = normalized_tif

    @classmethod
    def from_settings(cls, settings: KalshiSettings) -> "RiskManager":
        return cls(
            live_validation_enabled=settings.live_validation_enabled,
            live_trading_enabled=settings.live_trading_enabled,
            live_kill_switch_active=settings.live_kill_switch_active,
            env=settings.env,
            live_validation_env=settings.live_validation_env,
            max_live_order_count=1,
            required_time_in_force=settings.live_validation_time_in_force,
        )

    def evaluate_live_order(self, order) -> LiveSafetyDecision:
        if self._live_kill_switch_active:
            return LiveSafetyDecision(allow=False, reason="kill_switch_active")
        if not self._live_validation_enabled:
            return LiveSafetyDecision(allow=False, reason="live_validation_disabled")
        if not self._live_trading_enabled:
            return LiveSafetyDecision(allow=False, reason="live_trading_not_enabled")
        if self._env != "prod" or self._live_validation_env != "prod":
            return LiveSafetyDecision(allow=False, reason="live_env_not_prod")
        if _missing_live_order_field(order):
            return LiveSafetyDecision(allow=False, reason="missing_live_order_field")
        if order.count != self._max_live_order_count:
            return LiveSafetyDecision(allow=False, reason="order_count_exceeds_phase10_cap")
        if order.time_in_force.strip().lower() != self._required_time_in_force:
            return LiveSafetyDecision(allow=False, reason="unsupported_time_in_force")
        return LiveSafetyDecision(allow=True, reason="allowed")


def _missing_live_order_field(order) -> bool:
    return any(
        (
            not _text_value(getattr(order, "ticker", None)),
            not _text_value(getattr(order, "action", None)),
            not _text_value(getattr(order, "side", None)),
            getattr(order, "count", None) is None,
            getattr(order, "price_dollars", None) is None,
            not _text_value(getattr(order, "time_in_force", None)),
            not _text_value(getattr(order, "client_order_id", None)),
        )
    )


def _text_value(value) -> str:
    if value is None:
        return ""
    return str(value).strip()
