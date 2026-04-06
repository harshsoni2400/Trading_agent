"""Backtesting engine — simulate the trading strategy on historical data.

Simulates the full trading day lifecycle on 6 months of 5-minute candle data.
Produces trade-by-trade results, equity curve, and performance metrics.
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time, date
from typing import Optional

import numpy as np
import pandas as pd

from src.utils import Config, load_config, load_nifty200
from src.indicators import (
    CandleData, ORBLevels,
    atr_percent, avg_daily_volume_cr, calculate_orb,
    vwap, vwap_crossover, rsi, ema, ema_crossover,
    volume_spike, volume_ratio, orb_breakout,
)
from src.scorer import score_stock, Signal
from src.kite_client import KiteClient


@dataclass
class BacktestTrade:
    """A single trade in the backtest."""
    date: str
    symbol: str
    direction: str
    entry_time: str
    entry_price: float
    exit_time: str
    exit_price: float
    quantity: int
    pnl: float
    pnl_pct: float
    exit_reason: str    # "target", "stoploss", "trailing_sl", "squareoff"
    score: int
    factors: dict


@dataclass
class BacktestDay:
    """Results for a single trading day."""
    date: str
    trades: list[BacktestTrade] = field(default_factory=list)
    pnl: float = 0.0
    num_trades: int = 0
    signals_generated: int = 0
    signals_blocked: int = 0


@dataclass
class BacktestResult:
    """Full backtest results."""
    days: list[BacktestDay] = field(default_factory=list)
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def winners(self) -> list[BacktestTrade]:
        return [t for t in self.trades if t.pnl > 0]

    @property
    def losers(self) -> list[BacktestTrade]:
        return [t for t in self.trades if t.pnl <= 0]

    @property
    def win_rate(self) -> float:
        return len(self.winners) / self.total_trades * 100 if self.total_trades else 0

    @property
    def avg_win(self) -> float:
        return np.mean([t.pnl for t in self.winners]) if self.winners else 0

    @property
    def avg_loss(self) -> float:
        return np.mean([t.pnl for t in self.losers]) if self.losers else 0

    @property
    def profit_factor(self) -> float:
        total_wins = sum(t.pnl for t in self.winners)
        total_losses = abs(sum(t.pnl for t in self.losers))
        return total_wins / total_losses if total_losses > 0 else float("inf")

    @property
    def max_drawdown(self) -> float:
        if not self.equity_curve:
            return 0
        peak = self.equity_curve[0]
        max_dd = 0
        for val in self.equity_curve:
            if val > peak:
                peak = val
            dd = peak - val
            if dd > max_dd:
                max_dd = dd
        return max_dd

    @property
    def max_drawdown_pct(self) -> float:
        if not self.equity_curve:
            return 0
        peak = self.equity_curve[0]
        max_dd_pct = 0
        for val in self.equity_curve:
            if val > peak:
                peak = val
            if peak > 0:
                dd_pct = (peak - val) / peak * 100
                if dd_pct > max_dd_pct:
                    max_dd_pct = dd_pct
        return max_dd_pct

    @property
    def sharpe_ratio(self) -> float:
        if not self.trades:
            return 0
        daily_pnls = [d.pnl for d in self.days if d.pnl != 0]
        if len(daily_pnls) < 2:
            return 0
        mean_ret = np.mean(daily_pnls)
        std_ret = np.std(daily_pnls)
        if std_ret == 0:
            return 0
        return float(mean_ret / std_ret * np.sqrt(252))

    def summary(self) -> dict:
        return {
            "total_pnl": round(self.total_pnl, 2),
            "total_trades": self.total_trades,
            "winners": len(self.winners),
            "losers": len(self.losers),
            "win_rate": round(self.win_rate, 1),
            "avg_win": round(self.avg_win, 2),
            "avg_loss": round(self.avg_loss, 2),
            "profit_factor": round(self.profit_factor, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 1),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "trading_days": len(self.days),
            "avg_trades_per_day": round(self.total_trades / len(self.days), 1) if self.days else 0,
        }


def _simulate_day(
    day_candles: dict[str, pd.DataFrame],
    daily_data: dict[str, CandleData],
    config: Config,
) -> BacktestDay:
    """Simulate one trading day.

    Args:
        day_candles: {symbol: DataFrame of 5-min candles for the day}
        daily_data: {symbol: CandleData of 20-day daily candles for universe filtering}
        config: Trading config

    Returns:
        BacktestDay with all trades for the day.
    """
    day_result = BacktestDay(date="")
    active_trades: list[dict] = []  # Simulated open positions
    daily_trades = 0
    daily_pnl = 0.0
    orb_levels: dict[str, ORBLevels] = {}

    # Get the date from first available candle
    for sym, df in day_candles.items():
        if len(df) > 0:
            day_result.date = str(df.iloc[0]["date"]).split(" ")[0]
            break

    if not day_result.date:
        return day_result

    # Phase 1: Capture ORB (first 3 candles = 15 min)
    for symbol, df in day_candles.items():
        if len(df) >= 3:
            orb_cd = CandleData.from_kite_candles(df.iloc[:3].to_dict("records"))
            orb = calculate_orb(orb_cd, 3)
            if orb:
                orb_levels[symbol] = orb

    # Phase 2: Scan candles from candle index 3 onward (after 9:30)
    # Find max candle count across all symbols
    max_candles = max(len(df) for df in day_candles.values()) if day_candles else 0

    for candle_idx in range(3, max_candles):
        # Check time window — each candle is 5 min from 9:15
        minutes_from_open = candle_idx * 5
        candle_hour = 9 + (15 + minutes_from_open) // 60
        candle_min = (15 + minutes_from_open) % 60
        candle_time = time(candle_hour, candle_min)

        # Check if within trading window
        in_entry_window = config.no_trade_before <= candle_time <= config.no_trade_after
        past_squareoff = candle_time >= config.squareoff_time

        # Update active trades — check SL, target, trailing
        for trade in list(active_trades):
            sym = trade["symbol"]
            df = day_candles.get(sym)
            if df is None or candle_idx >= len(df):
                continue

            row = df.iloc[candle_idx]
            high = float(row["high"])
            low = float(row["low"])
            close = float(row["close"])

            entry_price = trade["entry_price"]
            sl = trade["stoploss"]
            target = trade["target"]

            # Check stop loss hit (price went below SL)
            if low <= sl:
                exit_price = sl
                pnl = (exit_price - entry_price) * trade["quantity"]
                daily_pnl += pnl
                day_result.trades.append(BacktestTrade(
                    date=day_result.date, symbol=sym, direction="LONG",
                    entry_time=trade["entry_time"],
                    entry_price=entry_price,
                    exit_time=f"{candle_hour:02d}:{candle_min:02d}",
                    exit_price=exit_price,
                    quantity=trade["quantity"], pnl=round(pnl, 2),
                    pnl_pct=round((exit_price - entry_price) / entry_price * 100, 2),
                    exit_reason="trailing_sl" if trade.get("trailing") else "stoploss",
                    score=trade["score"], factors=trade["factors"],
                ))
                active_trades.remove(trade)
                continue

            # Check target hit
            if high >= target:
                exit_price = target
                pnl = (exit_price - entry_price) * trade["quantity"]
                daily_pnl += pnl
                day_result.trades.append(BacktestTrade(
                    date=day_result.date, symbol=sym, direction="LONG",
                    entry_time=trade["entry_time"],
                    entry_price=entry_price,
                    exit_time=f"{candle_hour:02d}:{candle_min:02d}",
                    exit_price=exit_price,
                    quantity=trade["quantity"], pnl=round(pnl, 2),
                    pnl_pct=round((exit_price - entry_price) / entry_price * 100, 2),
                    exit_reason="target",
                    score=trade["score"], factors=trade["factors"],
                ))
                active_trades.remove(trade)
                continue

            # Check trailing SL activation
            pnl_pct = (close - entry_price) / entry_price * 100
            if not trade.get("trailing") and pnl_pct >= config.trailing_trigger_pct:
                trade["stoploss"] = entry_price  # Move SL to breakeven
                trade["trailing"] = True

        # Square off remaining at 3:15
        if past_squareoff:
            for trade in list(active_trades):
                sym = trade["symbol"]
                df = day_candles.get(sym)
                if df is None or candle_idx >= len(df):
                    continue
                exit_price = float(df.iloc[candle_idx]["close"])
                pnl = (exit_price - trade["entry_price"]) * trade["quantity"]
                daily_pnl += pnl
                day_result.trades.append(BacktestTrade(
                    date=day_result.date, symbol=sym, direction="LONG",
                    entry_time=trade["entry_time"],
                    entry_price=trade["entry_price"],
                    exit_time=f"{candle_hour:02d}:{candle_min:02d}",
                    exit_price=exit_price,
                    quantity=trade["quantity"], pnl=round(pnl, 2),
                    pnl_pct=round((exit_price - trade["entry_price"]) / trade["entry_price"] * 100, 2),
                    exit_reason="squareoff",
                    score=trade["score"], factors=trade["factors"],
                ))
            active_trades.clear()
            break

        # Skip entry if not in window or limits hit
        if not in_entry_window:
            continue
        if daily_trades >= config.max_daily_trades:
            continue
        if len(active_trades) >= config.max_concurrent:
            continue
        if daily_pnl <= -config.max_daily_loss:
            continue

        # Score each stock using candles up to current index
        for symbol, df in day_candles.items():
            if candle_idx >= len(df):
                continue
            if any(t["symbol"] == symbol for t in active_trades):
                continue
            if daily_trades >= config.max_daily_trades:
                break
            if len(active_trades) >= config.max_concurrent:
                break

            # Build CandleData from candles 0 to candle_idx+1
            slice_df = df.iloc[:candle_idx + 1]
            cd = CandleData.from_kite_candles(slice_df.to_dict("records"))

            signal = score_stock(symbol, cd, orb_levels.get(symbol), config)
            if signal is None or signal.score < config.min_score:
                continue
            if signal.direction != 1:  # Only longs
                continue

            day_result.signals_generated += 1

            # Calculate position
            qty = int(config.per_trade_capital // signal.price)
            if qty <= 0:
                continue

            entry_price = signal.price
            target = round(entry_price * (1 + config.target_pct / 100), 2)
            sl = round(entry_price * (1 - config.stoploss_pct / 100), 2)

            active_trades.append({
                "symbol": symbol,
                "entry_price": entry_price,
                "target": target,
                "stoploss": sl,
                "quantity": qty,
                "entry_time": f"{candle_hour:02d}:{candle_min:02d}",
                "score": signal.score,
                "factors": signal.factors,
                "trailing": False,
            })
            daily_trades += 1

    day_result.pnl = round(daily_pnl, 2)
    day_result.num_trades = daily_trades
    return day_result


def run_backtest(
    config: Config,
    kite: KiteClient,
    symbols: list[str],
    months: int = 6,
    progress_callback=None,
) -> BacktestResult:
    """Run a full backtest over the specified period.

    Args:
        config: Trading config.
        kite: Authenticated KiteClient for fetching historical data.
        symbols: List of stock symbols to backtest.
        months: Number of months to backtest.
        progress_callback: Optional callback(step, total, message).

    Returns:
        BacktestResult with all trades and metrics.
    """
    result = BacktestResult()
    to_date = datetime.now()
    from_date = to_date - timedelta(days=months * 30)

    # Step 1: Fetch daily data for universe filtering
    if progress_callback:
        progress_callback(0, 3, "Fetching daily data for universe filtering...")

    daily_from = from_date - timedelta(days=40)
    daily_data_all = {}
    for i, symbol in enumerate(symbols):
        try:
            candles = kite.get_historical_data(symbol, "day", daily_from, to_date)
            if candles:
                daily_data_all[symbol] = candles
        except Exception:
            pass
        _time.sleep(0.35)
        if progress_callback and i % 10 == 0:
            progress_callback(0, 3, f"Daily data: {i+1}/{len(symbols)} stocks...")

    # Step 2: Filter universe using full-period daily data
    if progress_callback:
        progress_callback(1, 3, "Filtering universe...")

    # Use simple volume/ATR filter on daily data
    filtered_symbols = []
    for symbol, candles in daily_data_all.items():
        cd = CandleData.from_kite_candles(candles)
        if len(cd.close) < config.lookback_days:
            continue
        atr_pct = atr_percent(cd.high, cd.low, cd.close, period=14)
        vol_cr = avg_daily_volume_cr(cd.volume, cd.close, period=config.lookback_days)
        if config.atr_pct_min <= atr_pct <= config.atr_pct_max and vol_cr >= config.min_volume_cr:
            filtered_symbols.append(symbol)

    if progress_callback:
        progress_callback(1, 3, f"Filtered to {len(filtered_symbols)} stocks")

    # Step 3: Fetch 5-min data and simulate day by day
    if progress_callback:
        progress_callback(2, 3, "Fetching 5-minute data and simulating...")

    # Fetch 5-min data for filtered symbols (in chunks to manage rate limits)
    five_min_data: dict[str, pd.DataFrame] = {}
    for i, symbol in enumerate(filtered_symbols):
        try:
            candles = kite.get_historical_data(symbol, "5minute", from_date, to_date)
            if candles:
                df = pd.DataFrame(candles)
                df["date"] = pd.to_datetime(df["date"])
                five_min_data[symbol] = df
        except Exception:
            pass
        _time.sleep(0.35)
        if progress_callback and i % 5 == 0:
            progress_callback(2, 3, f"5-min data: {i+1}/{len(filtered_symbols)} stocks...")

    # Get unique trading days
    all_dates = set()
    for df in five_min_data.values():
        all_dates.update(df["date"].dt.date.unique())
    trading_days = sorted(all_dates)

    if progress_callback:
        progress_callback(2, 3, f"Simulating {len(trading_days)} trading days...")

    # Simulate each day
    equity = config.total_capital
    for day_idx, trading_date in enumerate(trading_days):
        # Get candles for this day
        day_candles = {}
        for symbol, df in five_min_data.items():
            day_df = df[df["date"].dt.date == trading_date].reset_index(drop=True)
            if len(day_df) > 0:
                day_candles[symbol] = day_df

        if not day_candles:
            continue

        # Get daily data for universe context
        daily_data = {}
        for symbol in day_candles:
            if symbol in daily_data_all:
                cd = CandleData.from_kite_candles(daily_data_all[symbol])
                daily_data[symbol] = cd

        day_result = _simulate_day(day_candles, daily_data, config)
        equity += day_result.pnl

        result.days.append(day_result)
        result.trades.extend(day_result.trades)
        result.equity_curve.append(equity)
        result.dates.append(day_result.date)

        if progress_callback and day_idx % 10 == 0:
            progress_callback(2, 3, f"Day {day_idx+1}/{len(trading_days)}: P&L={day_result.pnl:+.0f}")

    if progress_callback:
        progress_callback(3, 3, "Backtest complete!")

    return result
