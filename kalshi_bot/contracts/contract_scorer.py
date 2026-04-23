"""Pure contract scoring helpers for Phase 6 ranking."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


ZERO_DECIMAL = Decimal("0")


@dataclass(frozen=True)
class ContractScore:
    """Component score used for deterministic contract ranking."""

    confidence: int
    spread_width: Decimal
    top_of_book_liquidity: Decimal
    dollar_volume: Decimal

    def ranking_key(self) -> tuple[int, Decimal, Decimal, Decimal]:
        """Return the deterministic sort key used by the scanner."""

        return (
            -self.confidence,
            self.spread_width,
            -self.top_of_book_liquidity,
            -self.dollar_volume,
        )


def score_contract(
    *,
    confidence: int,
    best_bid: Decimal,
    best_ask: Decimal,
    yes_bid_size_fp: Decimal | None,
    yes_ask_size_fp: Decimal | None,
    dollar_volume: Decimal | None,
) -> ContractScore:
    """Score one contract from already-normalized market and bias inputs."""

    return ContractScore(
        confidence=confidence,
        spread_width=best_ask - best_bid,
        top_of_book_liquidity=(yes_bid_size_fp or ZERO_DECIMAL) + (yes_ask_size_fp or ZERO_DECIMAL),
        dollar_volume=dollar_volume or ZERO_DECIMAL,
    )
