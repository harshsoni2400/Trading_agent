"""Main trading engine — wires indicators, scoring, risk, and position management.

This engine is stateful and designed to be called by the Claude orchestrator.
Claude feeds market data (from MCP calls) into the engine, and the engine
returns actions (orders to place, orders to modify, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from src.utils import Config
from src.indicators import (
    CandleData, ORBLevels,
    atr_percent, avg_daily_volume_cr, calculate_orb,
)
from src.scorer import score_stock, Signal
from src.risk import RiskManager
from src.position import (
    Position, PositionTracker, PositionStatus,
    calculate_order_params, calculate_quantity,
)


@dataclass
class Action:
    """An action the orchestrator should execute via MCP."""
    type: str           # "place_entry", "place_sl", "place_target", "modify_sl",
                        # "cancel_order", "squareoff", "log"
    symbol: str = ""
    params: dict = field(default_factory=dict)
    message: str = ""


@dataclass
class StockState:
    """Cached state for a stock being monitored."""
    symbol: str
    instrument_token: str = ""
    candles: CandleData | None = None
    orb_levels: ORBLevels | None = None
    last_signal: Signal | None = None


class TradingEngine:
    """Main trading engine, called step-by-step by the Claude orchestrator."""

    def __init__(self, config: Config):
        self.config = config
        self.risk = RiskManager(config=config)
        self.tracker = PositionTracker()
        self.watchlist: dict[str, StockState] = {}  # symbol -> StockState
        self.instrument_tokens: dict[str, str] = {} # symbol -> instrument_token

    # ── Phase 1: Universe Filtering ──────────────────────────────

    def filter_universe(self, stock_data: dict[str, dict]) -> list[str]:
        """Filter stocks based on ATR% and average volume.

        Args:
            stock_data: {symbol: {"candles": CandleData from daily historical data}}

        Returns:
            List of symbols that pass the filter.
        """
        filtered = []
        for symbol, data in stock_data.items():
            candles = data["candles"]
            if len(candles.close) < self.config.lookback_days:
                continue

            atr_pct = atr_percent(candles.high, candles.low, candles.close,
                                  period=min(14, self.config.lookback_days))
            vol_cr = avg_daily_volume_cr(candles.volume, candles.close,
                                         period=self.config.lookback_days)

            if (self.config.atr_pct_min <= atr_pct <= self.config.atr_pct_max
                    and vol_cr >= self.config.min_volume_cr):
                filtered.append(symbol)
                self.watchlist[symbol] = StockState(
                    symbol=symbol,
                    instrument_token=self.instrument_tokens.get(symbol, ""),
                )

        return filtered

    # ── Phase 2: ORB Capture ─────────────────────────────────────

    def capture_orb(self, symbol: str, candles: CandleData):
        """Record ORB levels from the first 15 minutes of trading.

        Call this after 9:30 AM with the 5-min candles from 9:15-9:30.
        """
        if symbol not in self.watchlist:
            return

        orb_candle_count = self.config.orb_minutes // 5  # 15 min / 5 = 3 candles
        orb = calculate_orb(candles, orb_candle_count)
        self.watchlist[symbol].orb_levels = orb
        self.watchlist[symbol].candles = candles

    # ── Phase 3: Signal Scan ─────────────────────────────────────

    def scan_for_signals(self, market_data: dict[str, CandleData]) -> list[Action]:
        """Scan all watchlist stocks for entry signals.

        Args:
            market_data: {symbol: CandleData} with latest 5-min candles.

        Returns:
            List of actions for the orchestrator to execute.
        """
        actions = []

        for symbol, candles in market_data.items():
            if symbol not in self.watchlist:
                continue

            state = self.watchlist[symbol]
            state.candles = candles

            # Skip if already have a position in this stock
            if self.tracker.find_by_symbol(symbol):
                continue

            # Score the stock
            signal = score_stock(symbol, candles, state.orb_levels, self.config)
            state.last_signal = signal

            if signal is None or signal.score < self.config.min_score:
                continue

            # Only take long trades for simplicity (short selling intraday is riskier)
            if signal.direction != 1:
                continue

            # Risk check
            allowed, reason = self.risk.can_trade()
            if not allowed:
                actions.append(Action(
                    type="log",
                    symbol=symbol,
                    message=f"Signal blocked by risk: {reason} | {signal.summary()}",
                ))
                continue

            # Calculate position sizing
            qty = calculate_quantity(self.config.per_trade_capital, signal.price)
            if qty <= 0:
                continue

            order_params = calculate_order_params(
                entry_price=signal.price,
                direction=signal.direction,
                quantity=qty,
                target_pct=self.config.target_pct,
                stoploss_pct=self.config.stoploss_pct,
            )

            # Create position object
            position = Position(
                symbol=symbol,
                direction=signal.direction,
                quantity=qty,
                entry_price=signal.price,
                target_price=order_params["target_price"],
                stoploss_price=order_params["stoploss_price"],
                signal_score=signal.score,
                signal_factors=str(signal.factors),
            )
            self.tracker.add_position(position)
            self.risk.record_trade()

            actions.append(Action(
                type="place_entry",
                symbol=symbol,
                params={
                    "exchange": "NSE",
                    "tradingsymbol": symbol,
                    "transaction_type": "BUY",
                    "quantity": qty,
                    "product": "MIS",
                    "order_type": "LIMIT",
                    "price": signal.price,
                    "target_price": order_params["target_price"],
                    "stoploss_price": order_params["stoploss_price"],
                },
                message=f"ENTRY: {signal.summary()} qty={qty} "
                        f"SL={order_params['stoploss_price']:.2f} "
                        f"target={order_params['target_price']:.2f}",
            ))

        return actions

    # ── Phase 4: Position Monitoring ─────────────────────────────

    def check_positions(self, current_prices: dict[str, float]) -> list[Action]:
        """Check active positions for trailing SL activation.

        Args:
            current_prices: {symbol: latest_price}

        Returns:
            Actions to modify orders.
        """
        actions = []

        for position in self.tracker.active_positions:
            if position.status != PositionStatus.ACTIVE:
                continue

            price = current_prices.get(position.symbol)
            if price is None:
                continue

            # Check trailing SL
            if position.should_trail_sl(price, self.config.trailing_trigger_pct):
                position.trailing_active = True
                new_sl = position.entry_price  # Move SL to breakeven

                actions.append(Action(
                    type="modify_sl",
                    symbol=position.symbol,
                    params={
                        "order_id": position.sl_order_id,
                        "trigger_price": new_sl,
                    },
                    message=f"TRAILING SL: {position.symbol} moving SL to breakeven "
                            f"{new_sl:.2f} (was {position.stoploss_price:.2f})",
                ))
                position.stoploss_price = new_sl

        return actions

    def handle_order_update(self, order_id: str, status: str,
                            price: float = 0) -> list[Action]:
        """Handle an order status update from Kite.

        Args:
            order_id: The Kite order ID.
            status: Order status ("COMPLETE", "REJECTED", "CANCELLED").
            price: Fill price if completed.

        Returns:
            Follow-up actions (place SL/target after entry fill, cancel counterpart).
        """
        actions = []
        position = self.tracker.find_by_order_id(order_id)
        if position is None:
            return actions

        if order_id == position.entry_order_id:
            if status == "COMPLETE":
                position.status = PositionStatus.ACTIVE
                position.entry_price = price  # Use actual fill price

                # Recalculate SL and target based on actual fill
                params = calculate_order_params(
                    price, position.direction, position.quantity,
                    self.config.target_pct, self.config.stoploss_pct,
                )
                position.target_price = params["target_price"]
                position.stoploss_price = params["stoploss_price"]

                # Place SL order
                actions.append(Action(
                    type="place_sl",
                    symbol=position.symbol,
                    params={
                        "exchange": "NSE",
                        "tradingsymbol": position.symbol,
                        "transaction_type": "SELL",
                        "quantity": position.quantity,
                        "product": "MIS",
                        "order_type": "SL-M",
                        "trigger_price": position.stoploss_price,
                    },
                    message=f"Placing SL at {position.stoploss_price:.2f}",
                ))

                # Place target order
                actions.append(Action(
                    type="place_target",
                    symbol=position.symbol,
                    params={
                        "exchange": "NSE",
                        "tradingsymbol": position.symbol,
                        "transaction_type": "SELL",
                        "quantity": position.quantity,
                        "product": "MIS",
                        "order_type": "LIMIT",
                        "price": position.target_price,
                    },
                    message=f"Placing target at {position.target_price:.2f}",
                ))

            elif status == "REJECTED":
                position.status = PositionStatus.CLOSED
                position.pnl = 0
                self.risk.open_positions = max(0, self.risk.open_positions - 1)
                actions.append(Action(
                    type="log",
                    symbol=position.symbol,
                    message=f"Entry REJECTED for {position.symbol}",
                ))

        elif order_id == position.sl_order_id:
            if status == "COMPLETE":
                # SL hit — cancel target order
                self.tracker.close_position(position, price)
                self.risk.record_exit(position.pnl)
                if position.target_order_id:
                    actions.append(Action(
                        type="cancel_order",
                        symbol=position.symbol,
                        params={"order_id": position.target_order_id},
                        message=f"SL hit at {price:.2f}. P&L: {position.pnl:+.2f}. Cancelling target.",
                    ))

        elif order_id == position.target_order_id:
            if status == "COMPLETE":
                # Target hit — cancel SL order
                self.tracker.close_position(position, price)
                self.risk.record_exit(position.pnl)
                if position.sl_order_id:
                    actions.append(Action(
                        type="cancel_order",
                        symbol=position.symbol,
                        params={"order_id": position.sl_order_id},
                        message=f"Target hit at {price:.2f}. P&L: {position.pnl:+.2f}. Cancelling SL.",
                    ))

        return actions

    # ── Phase 5: Square-off ──────────────────────────────────────

    def squareoff_all(self) -> list[Action]:
        """Generate square-off actions for all open positions."""
        actions = []
        for position in self.tracker.active_positions:
            # Cancel existing SL and target orders
            if position.sl_order_id:
                actions.append(Action(
                    type="cancel_order",
                    symbol=position.symbol,
                    params={"order_id": position.sl_order_id},
                    message=f"Squareoff: cancelling SL for {position.symbol}",
                ))
            if position.target_order_id:
                actions.append(Action(
                    type="cancel_order",
                    symbol=position.symbol,
                    params={"order_id": position.target_order_id},
                    message=f"Squareoff: cancelling target for {position.symbol}",
                ))

            # Place market sell order
            tx_type = "SELL" if position.is_long else "BUY"
            actions.append(Action(
                type="squareoff",
                symbol=position.symbol,
                params={
                    "exchange": "NSE",
                    "tradingsymbol": position.symbol,
                    "transaction_type": tx_type,
                    "quantity": position.quantity,
                    "product": "MIS",
                    "order_type": "MARKET",
                },
                message=f"Squareoff: market {tx_type} {position.quantity} {position.symbol}",
            ))

        return actions

    # ── Status & Summary ─────────────────────────────────────────

    def status(self) -> str:
        """Full engine status for logging."""
        lines = [
            f"=== Engine Status ===",
            f"Watchlist: {len(self.watchlist)} stocks",
            f"Active positions: {len(self.tracker.active_positions)}",
            self.risk.status(),
        ]

        for pos in self.tracker.active_positions:
            lines.append(f"  {pos.summary()}")

        top_signals = sorted(
            [s.last_signal for s in self.watchlist.values() if s.last_signal and s.last_signal.score >= 2],
            key=lambda x: x.score,
            reverse=True,
        )[:5]

        if top_signals:
            lines.append(f"\nTop signals:")
            for sig in top_signals:
                lines.append(f"  {sig.summary()}")

        return "\n".join(lines)

    def daily_summary(self) -> str:
        """End-of-day summary."""
        return self.tracker.daily_summary()
