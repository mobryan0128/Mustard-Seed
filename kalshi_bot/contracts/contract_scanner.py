"""Read-only contract scanning over current Kalshi market state and bias output."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

from kalshi_bot.config.settings import KalshiSettings
from kalshi_bot.contracts.contract_scorer import ContractScore, score_contract
from kalshi_bot.forecast.bias_engine import BiasSnapshot
from kalshi_bot.market.market_state_cache import MarketStateSnapshot, TickerState


TWO_DECIMAL = Decimal("2")
LATE_EXPANSION_IMPULSE_RETURN_BPS = Decimal("6.000")
IMPULSE_CONFIRMATION_RETURN_BPS = Decimal("3.000")


class ContractScannerError(ValueError):
    """Raised when scanner configuration is missing or invalid."""


@dataclass(frozen=True)
class ScannedContract:
    """Normalized ranked contract candidate."""

    product_id: str
    market_ticker: str
    direction: str
    structure: str
    confidence: int
    best_bid: Decimal
    best_ask: Decimal
    midpoint: Decimal
    bias_as_of: str | None
    market_as_of: str | None
    score: ContractScore
    contract_close_time: str | None = None
    contract_time_remaining_seconds: int | None = None
    end_window_allowed: bool | None = None
    end_window_reason: str | None = None


@dataclass(frozen=True)
class SkippedContract:
    """Normalized skipped contract record."""

    product_id: str
    market_ticker: str
    reason: str
    contract_close_time: str | None = None
    contract_time_remaining_seconds: int | None = None
    end_window_allowed: bool | None = None
    end_window_reason: str | None = None


@dataclass(frozen=True)
class ContractScanSnapshot:
    """Ranked and skipped contract results for one scan pass."""

    ranked_contracts: tuple[ScannedContract, ...]
    skipped_contracts: tuple[SkippedContract, ...]


class ContractScanner:
    """Read-only scanner over mapped Kalshi markets already present in local state."""

    def __init__(
        self,
        *,
        product_markets: Mapping[str, tuple[str, ...]],
        market_metadata_by_ticker: Mapping[str, Mapping[str, object]] | None = None,
    ) -> None:
        normalized = {
            product_id.strip(): tuple(
                dict.fromkeys(market_ticker.strip() for market_ticker in market_tickers if market_ticker.strip())
            )
            for product_id, market_tickers in product_markets.items()
            if product_id.strip()
        }
        if not normalized:
            raise ContractScannerError("Contract scanner product mapping is required.")
        if any(not market_tickers for market_tickers in normalized.values()):
            raise ContractScannerError("Each contract scanner product must map to at least one market.")
        self._product_markets = normalized
        self._market_metadata_by_ticker = {
            market_ticker: dict(metadata)
            for market_ticker, metadata in (market_metadata_by_ticker or {}).items()
        }

    @classmethod
    def from_settings(cls, settings: KalshiSettings) -> "ContractScanner":
        if not settings.contract_scanner_product_markets:
            raise ContractScannerError("CONTRACT_SCANNER_PRODUCT_MARKETS_JSON is required.")
        return cls(product_markets=settings.contract_scanner_product_markets)

    def scan(
        self,
        *,
        bias_snapshot: BiasSnapshot,
        market_snapshot: MarketStateSnapshot,
    ) -> ContractScanSnapshot:
        ranked_contracts: list[ScannedContract] = []
        skipped_contracts: list[SkippedContract] = []

        for product_id, market_tickers in self._product_markets.items():
            bias_state = bias_snapshot.products.get(product_id)
            for market_ticker in market_tickers:
                ticker_state = market_snapshot.tickers.get(market_ticker)
                if ticker_state is None:
                    continue
                metadata = self._market_metadata_by_ticker.get(market_ticker, {})
                skip_reason = _skip_reason(bias_state, ticker_state)
                if skip_reason is not None:
                    skipped_contracts.append(
                        SkippedContract(
                            product_id=product_id,
                            market_ticker=market_ticker,
                            reason=skip_reason,
                            contract_close_time=_optional_str_metadata(
                                metadata,
                                "close_time",
                            ),
                        )
                    )
                    continue

                assert bias_state is not None
                assert ticker_state.yes_bid_dollars is not None
                assert ticker_state.yes_ask_dollars is not None
                midpoint = ((ticker_state.yes_bid_dollars + ticker_state.yes_ask_dollars) / TWO_DECIMAL).quantize(
                    Decimal("0.001")
                )
                score = score_contract(
                    confidence=bias_state.confidence,
                    best_bid=ticker_state.yes_bid_dollars,
                    best_ask=ticker_state.yes_ask_dollars,
                    yes_bid_size_fp=ticker_state.yes_bid_size_fp,
                    yes_ask_size_fp=ticker_state.yes_ask_size_fp,
                    dollar_volume=ticker_state.dollar_volume,
                )
                ranked_contracts.append(
                    ScannedContract(
                        product_id=product_id,
                        market_ticker=market_ticker,
                        direction=bias_state.direction,
                        structure=bias_state.structure,
                        confidence=bias_state.confidence,
                        best_bid=ticker_state.yes_bid_dollars,
                        best_ask=ticker_state.yes_ask_dollars,
                        midpoint=midpoint,
                        bias_as_of=bias_state.as_of,
                        market_as_of=_market_as_of(ticker_state),
                        score=score,
                        contract_close_time=_optional_str_metadata(
                            metadata,
                            "close_time",
                        ),
                    )
                )

        ranked_contracts.sort(key=lambda contract: contract.score.ranking_key() + (contract.market_ticker,))
        skipped_contracts.sort(key=lambda contract: (contract.product_id, contract.market_ticker, contract.reason))
        return ContractScanSnapshot(
            ranked_contracts=tuple(ranked_contracts),
            skipped_contracts=tuple(skipped_contracts),
        )


def _skip_reason(bias_state, ticker_state: TickerState) -> str | None:
    if bias_state is None:
        return "missing_bias_state"
    if bias_state.direction == "neutral":
        return "neutral_bias"
    if bias_state.confidence <= 0:
        return "zero_confidence"
    if _is_late_expansion_bias(bias_state):
        return "too_late_after_expansion"
    if _is_unconfirmed_impulse_bias(bias_state):
        return "impulse_unconfirmed"
    if ticker_state.yes_bid_dollars is None or ticker_state.yes_ask_dollars is None:
        return "missing_best_quote"
    return None


def _is_late_expansion_bias(bias_state) -> bool:  # noqa: ANN001
    impulse_return_bps = getattr(bias_state, "impulse_return_bps", None)
    if impulse_return_bps is None:
        return False
    return (
        bias_state.direction in {"up", "down"}
        and bias_state.structure == "trend"
        and bias_state.confidence <= 40
        and getattr(bias_state, "impulse_detected", False)
        and getattr(bias_state, "impulse_direction", None) == bias_state.direction
        and abs(Decimal(str(impulse_return_bps))) >= LATE_EXPANSION_IMPULSE_RETURN_BPS
    )


def _is_unconfirmed_impulse_bias(bias_state) -> bool:  # noqa: ANN001
    if not (
        bias_state.direction in {"up", "down"}
        and bias_state.structure == "trend"
        and bias_state.confidence == 40
        and getattr(bias_state, "impulse_detected", False)
        and getattr(bias_state, "impulse_direction", None) == bias_state.direction
    ):
        return False

    recent_return_bps = getattr(bias_state, "recent_return_bps", None)
    lookback_return_bps = getattr(bias_state, "lookback_return_bps", None)
    if recent_return_bps is None or lookback_return_bps is None:
        return True

    recent_return = Decimal(str(recent_return_bps))
    lookback_return = Decimal(str(lookback_return_bps))
    if abs(recent_return) < IMPULSE_CONFIRMATION_RETURN_BPS:
        return True
    if abs(lookback_return) < IMPULSE_CONFIRMATION_RETURN_BPS:
        return True
    if bias_state.direction == "up":
        return recent_return <= 0 or lookback_return <= 0
    return recent_return >= 0 or lookback_return >= 0


def _market_as_of(ticker_state: TickerState) -> str | None:
    if ticker_state.exchange_time:
        return ticker_state.exchange_time
    if ticker_state.exchange_ts is not None:
        return str(ticker_state.exchange_ts)
    return None


def _optional_str_metadata(
    metadata: Mapping[str, object],
    key: str,
) -> str | None:
    value = metadata.get(key)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
