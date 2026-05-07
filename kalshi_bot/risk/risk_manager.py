"""Deterministic live-trading guardrails for Phase 10."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from kalshi_bot.config.settings import KalshiSettings


DEFAULT_ACCOUNT_BALANCE_DOLLARS = Decimal("100")
DEFAULT_MIN_PERCENT_PER_TRADE = Decimal("0.01")
DEFAULT_MAX_PERCENT_PER_TRADE = Decimal("0.05")
DEFAULT_MIN_STAKE_DOLLARS = Decimal("1")
DEFAULT_MAX_STAKE_DOLLARS = Decimal("5")
DEFAULT_MAX_OPEN_POSITIONS = 20
DEFAULT_MAX_TOTAL_EXPOSURE_DOLLARS = Decimal("10")
DEFAULT_DAILY_LOSS_LIMIT_DOLLARS = Decimal("10")
MID_CONFIDENCE_PERCENT = Decimal("0.02")


@dataclass(frozen=True)
class LiveSafetyDecision:
    """Allow or deny one explicit live order submission."""

    allow: bool
    reason: str


@dataclass(frozen=True)
class RiskDecision:
    """Allow or deny one simulated/live entry candidate."""

    allowed: bool
    reason: str
    stake_dollars: Decimal | None


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
        max_live_order_count: int = 1000,
        required_time_in_force: str = "immediate_or_cancel",
        account_balance_dollars: Decimal = DEFAULT_ACCOUNT_BALANCE_DOLLARS,
        min_percent_per_trade: Decimal = DEFAULT_MIN_PERCENT_PER_TRADE,
        max_percent_per_trade: Decimal = DEFAULT_MAX_PERCENT_PER_TRADE,
        min_stake_dollars: Decimal = DEFAULT_MIN_STAKE_DOLLARS,
        max_stake_dollars: Decimal = DEFAULT_MAX_STAKE_DOLLARS,
        max_open_positions: int = DEFAULT_MAX_OPEN_POSITIONS,
        max_total_exposure_dollars: Decimal = DEFAULT_MAX_TOTAL_EXPOSURE_DOLLARS,
        daily_loss_limit_dollars: Decimal = DEFAULT_DAILY_LOSS_LIMIT_DOLLARS,
        risk_kill_switch_active: bool = False,
    ) -> None:
        if max_live_order_count <= 0:
            raise ValueError("max_live_order_count must be greater than zero.")
        normalized_tif = required_time_in_force.strip().lower()
        if not normalized_tif:
            raise ValueError("required_time_in_force is required.")
        if max_open_positions <= 0:
            raise ValueError("max_open_positions must be greater than zero.")

        self._live_validation_enabled = live_validation_enabled
        self._live_trading_enabled = live_trading_enabled
        self._live_kill_switch_active = live_kill_switch_active
        self._env = env.strip().lower()
        self._live_validation_env = live_validation_env.strip().lower()
        self._max_live_order_count = max_live_order_count
        self._required_time_in_force = normalized_tif
        self._account_balance_dollars = _positive_decimal(
            account_balance_dollars,
            "account_balance_dollars",
        )
        self._min_percent_per_trade = _positive_decimal(
            min_percent_per_trade,
            "min_percent_per_trade",
        )
        self._max_percent_per_trade = _positive_decimal(
            max_percent_per_trade,
            "max_percent_per_trade",
        )
        if self._min_percent_per_trade > self._max_percent_per_trade:
            raise ValueError("min_percent_per_trade must be less than or equal to max_percent_per_trade.")
        self._min_stake_dollars = _positive_decimal(
            min_stake_dollars,
            "min_stake_dollars",
        )
        self._max_stake_dollars = _positive_decimal(
            max_stake_dollars,
            "max_stake_dollars",
        )
        if self._min_stake_dollars > self._max_stake_dollars:
            raise ValueError("min_stake_dollars must be less than or equal to max_stake_dollars.")
        self._max_open_positions = max_open_positions
        self._max_total_exposure_dollars = _positive_decimal(
            max_total_exposure_dollars,
            "max_total_exposure_dollars",
        )
        self._daily_loss_limit_dollars = _positive_decimal(
            daily_loss_limit_dollars,
            "daily_loss_limit_dollars",
        )
        self._risk_kill_switch_active = risk_kill_switch_active

    @classmethod
    def from_settings(cls, settings: KalshiSettings) -> "RiskManager":
        return cls(
            live_validation_enabled=settings.live_validation_enabled,
            live_trading_enabled=settings.live_trading_enabled,
            live_kill_switch_active=settings.live_kill_switch_active,
            env=settings.env,
            live_validation_env=settings.live_validation_env,
            max_live_order_count=1000,
            required_time_in_force=settings.live_validation_time_in_force,
            account_balance_dollars=settings.risk_account_balance_dollars,
            min_percent_per_trade=settings.risk_min_percent_per_trade,
            max_percent_per_trade=settings.risk_max_percent_per_trade,
            min_stake_dollars=settings.risk_min_stake_dollars,
            max_stake_dollars=settings.risk_max_stake_dollars,
            max_open_positions=settings.risk_max_open_positions,
            max_total_exposure_dollars=settings.risk_max_total_exposure_dollars,
            daily_loss_limit_dollars=settings.risk_daily_loss_limit_dollars,
            risk_kill_switch_active=settings.risk_kill_switch_active,
        )

    @classmethod
    def from_live_settings(
        cls,
        settings: KalshiSettings,
        *,
        live_validation_enabled: bool | None = None,
        live_validation_env: str | None = None,
    ) -> "RiskManager":
        return cls(
            live_validation_enabled=(
                settings.live_validation_enabled
                if live_validation_enabled is None
                else live_validation_enabled
            ),
            live_trading_enabled=settings.live_trading_enabled,
            live_kill_switch_active=settings.live_kill_switch_active,
            env=settings.env,
            live_validation_env=(
                settings.live_validation_env
                if live_validation_env is None
                else live_validation_env
            ),
            max_live_order_count=settings.live_max_contract_count,
            required_time_in_force=settings.live_validation_time_in_force,
            account_balance_dollars=settings.risk_account_balance_dollars,
            min_percent_per_trade=settings.risk_min_percent_per_trade,
            max_percent_per_trade=settings.risk_max_percent_per_trade,
            min_stake_dollars=settings.live_min_stake_dollars,
            max_stake_dollars=settings.live_max_stake_dollars,
            max_open_positions=settings.live_max_open_positions,
            max_total_exposure_dollars=settings.live_max_exposure_dollars,
            daily_loss_limit_dollars=settings.risk_daily_loss_limit_dollars,
            risk_kill_switch_active=settings.risk_kill_switch_active,
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
        if order.count > self._max_live_order_count:
            return LiveSafetyDecision(allow=False, reason="order_count_exceeds_phase10_cap")
        if order.time_in_force.strip().lower() != self._required_time_in_force:
            return LiveSafetyDecision(allow=False, reason="unsupported_time_in_force")
        return LiveSafetyDecision(allow=True, reason="allowed")

    def compute_stake_from_confidence(
        self,
        confidence: int,
        account_balance: Decimal | None = None,
    ) -> Decimal:
        return compute_stake_from_confidence(
            confidence,
            self._account_balance_dollars if account_balance is None else account_balance,
            min_percent_per_trade=self._min_percent_per_trade,
            max_percent_per_trade=self._max_percent_per_trade,
            min_stake_dollars=self._min_stake_dollars,
            max_stake_dollars=self._max_stake_dollars,
        )

    def evaluate_entry_risk(
        self,
        *,
        product_id: str,
        confidence: int,
        open_position_count: int,
        current_exposure_dollars: Decimal,
        realized_daily_pnl_dollars: Decimal,
    ) -> RiskDecision:
        if self._risk_kill_switch_active:
            return RiskDecision(
                allowed=False,
                reason="risk_kill_switch_active",
                stake_dollars=None,
            )
        if open_position_count >= self._max_open_positions:
            return RiskDecision(
                allowed=False,
                reason="risk_max_open_positions",
                stake_dollars=None,
            )
        if realized_daily_pnl_dollars <= -self._daily_loss_limit_dollars:
            return RiskDecision(
                allowed=False,
                reason="risk_daily_loss_limit",
                stake_dollars=None,
            )

        stake_dollars = self.compute_stake_from_confidence(confidence)
        exposure = _decimal_value(current_exposure_dollars, "current_exposure_dollars")
        if exposure + stake_dollars > self._max_total_exposure_dollars:
            return RiskDecision(
                allowed=False,
                reason="risk_max_total_exposure",
                stake_dollars=None,
            )

        return RiskDecision(
            allowed=True,
            reason="allowed",
            stake_dollars=stake_dollars,
        )


def compute_stake_from_confidence(
    confidence: int,
    account_balance: Decimal,
    *,
    min_percent_per_trade: Decimal = DEFAULT_MIN_PERCENT_PER_TRADE,
    max_percent_per_trade: Decimal = DEFAULT_MAX_PERCENT_PER_TRADE,
    min_stake_dollars: Decimal = DEFAULT_MIN_STAKE_DOLLARS,
    max_stake_dollars: Decimal = DEFAULT_MAX_STAKE_DOLLARS,
) -> Decimal:
    balance = _positive_decimal(account_balance, "account_balance")
    min_percent = _positive_decimal(min_percent_per_trade, "min_percent_per_trade")
    max_percent = _positive_decimal(max_percent_per_trade, "max_percent_per_trade")
    if min_percent > max_percent:
        raise ValueError("min_percent_per_trade must be less than or equal to max_percent_per_trade.")

    if confidence >= 80:
        percent = max_percent
    elif confidence >= 60:
        percent = min(max(MID_CONFIDENCE_PERCENT, min_percent), max_percent)
    else:
        percent = min_percent

    min_stake = _positive_decimal(min_stake_dollars, "min_stake_dollars")
    max_stake = _positive_decimal(max_stake_dollars, "max_stake_dollars")
    if min_stake > max_stake:
        raise ValueError("min_stake_dollars must be less than or equal to max_stake_dollars.")
    stake = balance * percent
    return min(max(stake, min_stake), max_stake)


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


def _positive_decimal(value, name: str) -> Decimal:
    parsed = _decimal_value(value, name)
    if parsed <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return parsed


def _decimal_value(value, name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be decimal-compatible.") from exc
