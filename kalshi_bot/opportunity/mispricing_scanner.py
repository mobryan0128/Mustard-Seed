"""CEX-vs-Kalshi target-distance opportunity scanning."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from kalshi_bot.contracts.contract_scorer import score_contract
from kalshi_bot.contracts.contract_scanner import (
    ContractScanSnapshot,
    ScannedContract,
    SkippedContract,
)
from kalshi_bot.market.crypto_market_discovery import DiscoveredCryptoMarket
from kalshi_bot.market.market_state_cache import MarketStateSnapshot, TickerState

if TYPE_CHECKING:
    from kalshi_bot.clients.crypto_feed_client import CryptoFeedSnapshot


BASIS_POINTS_MULTIPLIER = Decimal("10000")
TWO_DECIMAL = Decimal("2")
ONE_DECIMAL = Decimal("1")


def scan_mispricing_opportunities(
    *,
    discovered_markets: tuple[DiscoveredCryptoMarket, ...],
    crypto_snapshot: "CryptoFeedSnapshot",
    market_snapshot: MarketStateSnapshot,
    min_entry_price: Decimal,
    max_entry_price: Decimal,
    max_execution_spread_dollars: Decimal,
    min_edge_bps: Decimal | None = None,
    max_external_price_age_ms: int | None = None,
    max_kalshi_quote_age_ms: int | None = None,
    cycle_started_at: str | None = None,
) -> ContractScanSnapshot:
    """Return mispricing candidates without applying directional-bias skips."""

    scan_time = _parse_timestamp(cycle_started_at) or datetime.now(timezone.utc)
    scan_started_at = scan_time.isoformat()
    ranked_contracts: list[ScannedContract] = []
    skipped_contracts: list[SkippedContract] = []

    for market in discovered_markets:
        product_state = crypto_snapshot.products.get(market.product_id)
        ticker_state = market_snapshot.tickers.get(market.market_ticker)
        candidate, skipped = _evaluate_market(
            market=market,
            product_state=product_state,
            ticker_state=ticker_state,
            min_entry_price=min_entry_price,
            max_entry_price=max_entry_price,
            max_execution_spread_dollars=max_execution_spread_dollars,
            min_edge_bps=min_edge_bps,
            max_external_price_age_ms=max_external_price_age_ms,
            max_kalshi_quote_age_ms=max_kalshi_quote_age_ms,
            scan_time=scan_time,
            cycle_started_at=scan_started_at,
        )
        if candidate is not None:
            ranked_contracts.append(candidate)
        elif skipped is not None:
            skipped_contracts.append(skipped)

    ranked_contracts.sort(key=_mispricing_rank_key)
    skipped_contracts.sort(
        key=lambda contract: (
            contract.product_id,
            contract.market_ticker,
            contract.reason,
        )
    )
    return ContractScanSnapshot(
        ranked_contracts=tuple(ranked_contracts),
        skipped_contracts=tuple(skipped_contracts),
    )


def _evaluate_market(
    *,
    market: DiscoveredCryptoMarket,
    product_state,  # noqa: ANN001
    ticker_state: TickerState | None,
    min_entry_price: Decimal,
    max_entry_price: Decimal,
    max_execution_spread_dollars: Decimal,
    min_edge_bps: Decimal | None,
    max_external_price_age_ms: int | None,
    max_kalshi_quote_age_ms: int | None,
    scan_time: datetime,
    cycle_started_at: str,
) -> tuple[ScannedContract | None, SkippedContract | None]:
    external_price = getattr(product_state, "price", None)
    external_price_timestamp = (
        getattr(product_state, "price_source_timestamp", None)
        or getattr(product_state, "source_timestamp", None)
    )
    target_price = market.contract_target_price
    market_as_of = _market_as_of(ticker_state) if ticker_state is not None else None
    external_price_age_ms = _age_ms(external_price_timestamp, scan_time)
    kalshi_quote_age_ms = _age_ms(market_as_of, scan_time)
    base_payload = {
        "opportunity_source": "mispricing",
        "external_price": external_price,
        "external_price_timestamp": external_price_timestamp,
        "contract_target_price": target_price,
        "target_source_field": market.target_source_field,
        "market_as_of": market_as_of,
        "external_price_age_ms": external_price_age_ms,
        "kalshi_quote_age_ms": kalshi_quote_age_ms,
        "cycle_started_at": cycle_started_at,
        "intent_latency_ms": None,
    }

    if target_price is None:
        return None, _skipped(market, "missing_contract_target_price", base_payload)
    if external_price is None:
        return None, _skipped(market, "missing_external_price", base_payload)
    if ticker_state is None:
        return None, _skipped(market, "missing_market_state", base_payload)
    if target_price <= Decimal("0"):
        return None, _skipped(market, "invalid_contract_target_price", base_payload)
    if (
        max_external_price_age_ms is not None
        and (
            external_price_age_ms is None
            or external_price_age_ms > max_external_price_age_ms
        )
    ):
        return None, _skipped(
            market,
            "mispricing_external_price_stale",
            base_payload,
        )
    if (
        max_kalshi_quote_age_ms is not None
        and (
            kalshi_quote_age_ms is None
            or kalshi_quote_age_ms > max_kalshi_quote_age_ms
        )
    ):
        return None, _skipped(
            market,
            "mispricing_kalshi_quote_stale",
            base_payload,
        )

    distance_to_target = (external_price - target_price).quantize(Decimal("0.001"))
    implied_side = _implied_side(distance_to_target)
    base_payload.update(
        {
            "distance_to_target": distance_to_target,
            "implied_side": implied_side,
        }
    )
    if implied_side is None:
        return None, _skipped(market, "external_price_at_target", base_payload)
    edge_bps = (
        abs(distance_to_target) / target_price * BASIS_POINTS_MULTIPLIER
    ).quantize(Decimal("0.001"))
    base_payload["edge_bps"] = edge_bps
    if min_edge_bps is not None and edge_bps < min_edge_bps:
        return None, _skipped(
            market,
            "mispricing_edge_below_minimum",
            base_payload,
        )

    quote_payload = _quote_payload(ticker_state)
    base_payload.update(quote_payload)
    executable_price, side_liquidity, skip_reason = _executable_mispricing_price(
        ticker_state,
        implied_side=implied_side,
        max_execution_spread_dollars=max_execution_spread_dollars,
    )
    base_payload["executable_price"] = executable_price
    if skip_reason is not None or executable_price is None:
        return None, _skipped(
            market,
            skip_reason or "executable_price_missing",
            base_payload,
        )
    if min_entry_price > Decimal("0") and executable_price < min_entry_price:
        return None, _skipped(
            market,
            "executable_price_below_minimum",
            base_payload,
        )
    if executable_price > max_entry_price:
        return None, _skipped(
            market,
            "executable_price_above_limit",
            base_payload,
        )
    if side_liquidity is None or side_liquidity <= Decimal("0"):
        return None, _skipped(market, "liquidity_missing", base_payload)

    direction = "up" if implied_side == "yes" else "down"
    confidence = _confidence_from_edge(edge_bps)
    midpoint = (
        (ticker_state.yes_bid_dollars + ticker_state.yes_ask_dollars)
        / TWO_DECIMAL
    ).quantize(Decimal("0.001"))
    score = score_contract(
        confidence=confidence,
        best_bid=ticker_state.yes_bid_dollars,
        best_ask=ticker_state.yes_ask_dollars,
        yes_bid_size_fp=ticker_state.yes_bid_size_fp,
        yes_ask_size_fp=ticker_state.yes_ask_size_fp,
        dollar_volume=ticker_state.dollar_volume,
    )

    return (
        ScannedContract(
            product_id=market.product_id,
            market_ticker=market.market_ticker,
            direction=direction,
            structure="mispricing",
            confidence=confidence,
            best_bid=ticker_state.yes_bid_dollars,
            best_ask=ticker_state.yes_ask_dollars,
            midpoint=midpoint,
            bias_as_of=external_price_timestamp,
            market_as_of=market_as_of,
            score=score,
            classification_reason="mispricing_edge",
            confidence_reason="mispricing_edge_bucket",
            opportunity_source="mispricing",
            external_price=external_price,
            external_price_timestamp=external_price_timestamp,
            contract_target_price=target_price,
            target_source_field=market.target_source_field,
            distance_to_target=distance_to_target,
            implied_side=implied_side,
            kalshi_yes_bid=ticker_state.yes_bid_dollars,
            kalshi_yes_ask=ticker_state.yes_ask_dollars,
            kalshi_no_bid=quote_payload["kalshi_no_bid"],
            kalshi_no_ask=quote_payload["kalshi_no_ask"],
            executable_price=executable_price,
            edge_bps=edge_bps,
            external_price_age_ms=external_price_age_ms,
            kalshi_quote_age_ms=kalshi_quote_age_ms,
            cycle_started_at=cycle_started_at,
            intent_latency_ms=None,
            lag_detected=True,
            reason_selected="mispricing_edge_available",
        ),
        None,
    )


def _implied_side(distance_to_target: Decimal) -> str | None:
    if distance_to_target > Decimal("0"):
        return "yes"
    if distance_to_target < Decimal("0"):
        return "no"
    return None


def _executable_mispricing_price(
    ticker_state: TickerState,
    *,
    implied_side: str,
    max_execution_spread_dollars: Decimal,
) -> tuple[Decimal | None, Decimal | None, str | None]:
    best_bid = ticker_state.yes_bid_dollars
    best_ask = ticker_state.yes_ask_dollars
    if best_bid is None or best_ask is None:
        return None, None, "executable_price_missing"

    spread_width = best_ask - best_bid
    if spread_width < Decimal("0") or spread_width > max_execution_spread_dollars:
        return None, None, "unsafe_executable_spread"

    if implied_side == "yes":
        return best_ask, ticker_state.yes_ask_size_fp, None
    if implied_side == "no":
        return ONE_DECIMAL - best_bid, ticker_state.yes_bid_size_fp, None
    return None, None, "invalid_implied_side"


def _quote_payload(ticker_state: TickerState) -> dict[str, Decimal | None]:
    yes_bid = ticker_state.yes_bid_dollars
    yes_ask = ticker_state.yes_ask_dollars
    return {
        "kalshi_yes_bid": yes_bid,
        "kalshi_yes_ask": yes_ask,
        "kalshi_no_bid": ONE_DECIMAL - yes_ask if yes_ask is not None else None,
        "kalshi_no_ask": ONE_DECIMAL - yes_bid if yes_bid is not None else None,
    }


def _confidence_from_edge(edge_bps: Decimal) -> int:
    if edge_bps >= Decimal("50"):
        return 80
    if edge_bps >= Decimal("25"):
        return 60
    return 40


def _mispricing_rank_key(
    contract: ScannedContract,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal, str]:
    liquidity = _side_liquidity(contract) or Decimal("0")
    spread_width = contract.best_ask - contract.best_bid
    return (
        -(contract.edge_bps or Decimal("0")),
        contract.executable_price or Decimal("1"),
        spread_width,
        -liquidity,
        -contract.score.dollar_volume,
        contract.market_ticker,
    )


def _side_liquidity(contract: ScannedContract) -> Decimal | None:
    if contract.implied_side == "yes":
        return contract.score.top_of_book_liquidity
    if contract.implied_side == "no":
        return contract.score.top_of_book_liquidity
    return None


def _skipped(
    market: DiscoveredCryptoMarket,
    reason: str,
    payload: dict[str, object],
) -> SkippedContract:
    return SkippedContract(
        product_id=market.product_id,
        market_ticker=market.market_ticker,
        reason=reason,
        opportunity_source="mispricing",
        external_price=payload.get("external_price"),
        external_price_timestamp=payload.get("external_price_timestamp"),
        contract_target_price=payload.get("contract_target_price"),
        target_source_field=payload.get("target_source_field"),
        market_as_of=payload.get("market_as_of"),
        distance_to_target=payload.get("distance_to_target"),
        implied_side=payload.get("implied_side"),
        kalshi_yes_bid=payload.get("kalshi_yes_bid"),
        kalshi_yes_ask=payload.get("kalshi_yes_ask"),
        kalshi_no_bid=payload.get("kalshi_no_bid"),
        kalshi_no_ask=payload.get("kalshi_no_ask"),
        executable_price=payload.get("executable_price"),
        edge_bps=payload.get("edge_bps"),
        external_price_age_ms=payload.get("external_price_age_ms"),
        kalshi_quote_age_ms=payload.get("kalshi_quote_age_ms"),
        cycle_started_at=payload.get("cycle_started_at"),
        intent_latency_ms=payload.get("intent_latency_ms"),
        lag_detected=False,
        reason_skipped=reason,
    )


def _market_as_of(ticker_state: TickerState) -> str | None:
    if ticker_state.exchange_time:
        return ticker_state.exchange_time
    if ticker_state.exchange_ts is not None:
        return str(ticker_state.exchange_ts)
    return None


def _age_ms(source_timestamp: str | int | None, now: datetime) -> int | None:
    parsed = _parse_timestamp(source_timestamp)
    if parsed is None:
        return None
    return max(int((now - parsed).total_seconds() * 1000), 0)


def _parse_timestamp(value: str | int | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, int):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    stripped = str(value).strip()
    if not stripped:
        return None
    if stripped.isdigit():
        return datetime.fromtimestamp(int(stripped) / 1000, tz=timezone.utc)
    try:
        parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
