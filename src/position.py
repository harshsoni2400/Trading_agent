"""Position tracking, trailing stop-loss management, and order lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class PositionStatus(Enum):
    PENDING_ENTRY = "pending_entry"    # Entry order placed, waiting for fill
    ACTIVE = "active"                  # Position open, SL+target placed
    PENDING_EXIT = "pending_exit"      # Exit triggered, waiting for fill
    CLOSED = "closed"


@dataclass
class Position:
    """Tracks a single trading position and its associated orders."""
    symbol: str
    direction: int               # +1 long, -1 short
    quantity: int
    entry_price: float
    target_price: float
    stoploss_price: float
    status: PositionStatus = PositionStatus.PENDING_ENTRY

    # Order IDs from Kite
    entry_order_id: str = ""
    sl_order_id: str = ""
    target_order_id: str = ""

    # Tracking
    entry_time: datetime = field(default_factory=datetime.now)
    exit_price: float = 0.0
    exit_time: datetime | None = None
    pnl: float = 0.0
    trailing_active: bool = False   # Whether trailing SL has been activated

    # Signal info
    signal_score: int = 0
    signal_factors: str = ""

    @property
    def is_long(self) -> bool:
        return self.direction == 1

    @property
    def unrealized_pnl(self) -> float:
        """Calculate unrealized P&L given current price stored in exit_price field temporarily."""
        return 0.0  # Calculated externally with live price

    def calc_pnl(self, current_price: float) -> float:
        """Calculate P&L at a given price."""
        if self.is_long:
            return (current_price - self.entry_price) * self.quantity
        else:
            return (self.entry_price - current_price) * self.quantity

    def calc_pnl_pct(self, current_price: float) -> float:
        """Calculate P&L percentage."""
        if self.entry_price == 0:
            return 0.0
        if self.is_long:
            return (current_price - self.entry_price) / self.entry_price * 100
        else:
            return (self.entry_price - current_price) / self.entry_price * 100

    def should_trail_sl(self, current_price: float, trigger_pct: float) -> bool:
        """Check if trailing SL should be activated (move SL to breakeven)."""
        if self.trailing_active:
            return False
        return self.calc_pnl_pct(current_price) >= trigger_pct

    def summary(self) -> str:
        direction_str = "LONG" if self.is_long else "SHORT"
        return (
            f"{self.symbol} {direction_str} qty={self.quantity} "
            f"entry={self.entry_price:.2f} SL={self.stoploss_price:.2f} "
            f"target={self.target_price:.2f} status={self.status.value}"
        )


@dataclass
class PositionTracker:
    """Manages all active and closed positions for the trading day."""
    positions: list[Position] = field(default_factory=list)

    @property
    def active_positions(self) -> list[Position]:
        return [p for p in self.positions if p.status in
                (PositionStatus.ACTIVE, PositionStatus.PENDING_ENTRY)]

    @property
    def closed_positions(self) -> list[Position]:
        return [p for p in self.positions if p.status == PositionStatus.CLOSED]

    @property
    def total_pnl(self) -> float:
        return sum(p.pnl for p in self.closed_positions)

    def add_position(self, position: Position):
        self.positions.append(position)

    def find_by_symbol(self, symbol: str) -> Position | None:
        """Find active position for a symbol."""
        for p in self.active_positions:
            if p.symbol == symbol:
                return p
        return None

    def find_by_order_id(self, order_id: str) -> Position | None:
        """Find position by any of its order IDs."""
        for p in self.positions:
            if order_id in (p.entry_order_id, p.sl_order_id, p.target_order_id):
                return p
        return None

    def close_position(self, position: Position, exit_price: float):
        """Mark a position as closed and calculate P&L."""
        position.exit_price = exit_price
        position.exit_time = datetime.now()
        position.pnl = position.calc_pnl(exit_price)
        position.status = PositionStatus.CLOSED

    def daily_summary(self) -> str:
        """Generate end-of-day summary."""
        total_trades = len(self.positions)
        closed = self.closed_positions
        winners = [p for p in closed if p.pnl > 0]
        losers = [p for p in closed if p.pnl < 0]

        lines = [
            f"=== Daily Trading Summary ===",
            f"Total trades: {total_trades}",
            f"Winners: {len(winners)} | Losers: {len(losers)}",
            f"Total P&L: {self.total_pnl:+.2f}",
        ]

        if closed:
            lines.append(f"\nTrade Details:")
            for p in closed:
                lines.append(
                    f"  {p.symbol}: {'LONG' if p.is_long else 'SHORT'} "
                    f"entry={p.entry_price:.2f} exit={p.exit_price:.2f} "
                    f"P&L={p.pnl:+.2f} ({p.calc_pnl_pct(p.exit_price):+.1f}%)"
                )

        active = self.active_positions
        if active:
            lines.append(f"\nStill Active: {len(active)}")
            for p in active:
                lines.append(f"  {p.summary()}")

        return "\n".join(lines)


def calculate_order_params(
    entry_price: float,
    direction: int,
    quantity: int,
    target_pct: float,
    stoploss_pct: float,
) -> dict:
    """Calculate SL and target prices for a new position.

    Returns dict with entry_price, target_price, stoploss_price, quantity.
    """
    if direction == 1:  # Long
        target_price = round(entry_price * (1 + target_pct / 100), 2)
        stoploss_price = round(entry_price * (1 - stoploss_pct / 100), 2)
    else:  # Short
        target_price = round(entry_price * (1 - target_pct / 100), 2)
        stoploss_price = round(entry_price * (1 + stoploss_pct / 100), 2)

    return {
        "entry_price": entry_price,
        "target_price": target_price,
        "stoploss_price": stoploss_price,
        "quantity": quantity,
    }


def calculate_quantity(capital: float, price: float) -> int:
    """Calculate number of shares to buy given capital and price.

    Rounds down to nearest lot of 1 (equity).
    """
    if price <= 0:
        return 0
    return int(capital // price)
