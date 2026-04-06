"""Risk management and safety rails.

Every signal must pass through RiskManager.can_trade() before execution.
"""

from __future__ import annotations

from datetime import datetime, time
from dataclasses import dataclass, field
from src.utils import Config


@dataclass
class MarketState:
    """Current market regime data."""
    india_vix: float = 0.0
    nifty_prev_close: float = 0.0
    nifty_open: float = 0.0

    @property
    def nifty_gap_pct(self) -> float:
        if self.nifty_prev_close == 0:
            return 0.0
        return abs(self.nifty_open - self.nifty_prev_close) / self.nifty_prev_close * 100


@dataclass
class RiskManager:
    """Enforces all safety rails before trade execution."""
    config: Config
    market_state: MarketState = field(default_factory=MarketState)
    daily_trades: int = 0
    daily_pnl: float = 0.0
    open_positions: int = 0

    def can_trade(self, now: datetime | None = None) -> tuple[bool, str]:
        """Check if a new trade is allowed right now.

        Returns:
            (allowed, reason) tuple.
        """
        if now is None:
            now = datetime.now()
        current_time = now.time()

        # Time window checks
        if current_time < self.config.no_trade_before:
            return False, f"Too early: {current_time} < {self.config.no_trade_before}"

        if current_time > self.config.no_trade_after:
            return False, f"Too late: {current_time} > {self.config.no_trade_after}"

        # Market regime checks
        if self.market_state.india_vix > self.config.max_vix:
            return False, f"VIX too high: {self.market_state.india_vix:.1f} > {self.config.max_vix}"

        gap = self.market_state.nifty_gap_pct
        if gap > self.config.max_gap_pct:
            return False, f"Nifty gap too large: {gap:.1f}% > {self.config.max_gap_pct}%"

        # Position limits
        if self.open_positions >= self.config.max_concurrent:
            return False, f"Max concurrent positions: {self.open_positions}/{self.config.max_concurrent}"

        if self.daily_trades >= self.config.max_daily_trades:
            return False, f"Max daily trades reached: {self.daily_trades}/{self.config.max_daily_trades}"

        # Daily loss limit
        if self.daily_pnl <= -self.config.max_daily_loss:
            return False, f"Daily loss limit hit: {self.daily_pnl:.0f} <= -{self.config.max_daily_loss}"

        return True, "Approved"

    def should_squareoff(self, now: datetime | None = None) -> bool:
        """Check if it's time to square off all positions."""
        if now is None:
            now = datetime.now()
        return now.time() >= self.config.squareoff_time

    def record_trade(self):
        """Record that a new trade was placed."""
        self.daily_trades += 1
        self.open_positions += 1

    def record_exit(self, pnl: float):
        """Record that a position was closed."""
        self.open_positions = max(0, self.open_positions - 1)
        self.daily_pnl += pnl

    def update_market_state(self, vix: float = None, nifty_prev_close: float = None,
                            nifty_open: float = None):
        """Update market regime data."""
        if vix is not None:
            self.market_state.india_vix = vix
        if nifty_prev_close is not None:
            self.market_state.nifty_prev_close = nifty_prev_close
        if nifty_open is not None:
            self.market_state.nifty_open = nifty_open

    def status(self) -> str:
        """Human-readable risk status."""
        allowed, reason = self.can_trade()
        return (
            f"Risk Status: {'OK' if allowed else 'BLOCKED'} ({reason})\n"
            f"  Trades: {self.daily_trades}/{self.config.max_daily_trades} | "
            f"Positions: {self.open_positions}/{self.config.max_concurrent}\n"
            f"  Daily P&L: {self.daily_pnl:+.0f} | "
            f"VIX: {self.market_state.india_vix:.1f} | "
            f"Gap: {self.market_state.nifty_gap_pct:.1f}%"
        )
