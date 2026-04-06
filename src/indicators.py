"""Technical indicator calculations for intraday trading.

All functions operate on numpy arrays for performance.
Candle data format: list of dicts with keys: date, open, high, low, close, volume
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from typing import Optional, List


@dataclass
class CandleData:
    """Parsed candle data as numpy arrays."""
    timestamps: list
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray

    @classmethod
    def from_kite_candles(cls, candles: List[dict]) -> "CandleData":
        """Parse Kite historical data response into CandleData.

        Kite returns candles as: [date, open, high, low, close, volume]
        or as dicts with those keys.
        """
        if not candles:
            return cls([], np.array([]), np.array([]), np.array([]),
                       np.array([]), np.array([]))

        # Handle both list-of-lists and list-of-dicts formats
        if isinstance(candles[0], dict):
            timestamps = [c["date"] for c in candles]
            o = np.array([float(c["open"]) for c in candles])
            h = np.array([float(c["high"]) for c in candles])
            l = np.array([float(c["low"]) for c in candles])
            c = np.array([float(c["close"]) for c in candles])
            v = np.array([float(c["volume"]) for c in candles])
        else:
            # List of lists: [date, open, high, low, close, volume]
            timestamps = [row[0] for row in candles]
            o = np.array([float(row[1]) for row in candles])
            h = np.array([float(row[2]) for row in candles])
            l = np.array([float(row[3]) for row in candles])
            c = np.array([float(row[4]) for row in candles])
            v = np.array([float(row[5]) for row in candles])

        return cls(timestamps, o, h, l, c, v)


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> float:
    """Calculate Average True Range over the given period.

    Returns the latest ATR value.
    """
    if len(close) < period + 1:
        return 0.0

    # True Range = max(H-L, |H-prevC|, |L-prevC|)
    prev_close = close[:-1]
    curr_high = high[1:]
    curr_low = low[1:]

    tr1 = curr_high - curr_low
    tr2 = np.abs(curr_high - prev_close)
    tr3 = np.abs(curr_low - prev_close)
    true_range = np.maximum(tr1, np.maximum(tr2, tr3))

    # Wilder's smoothing: first ATR is simple average, then EMA-like
    if len(true_range) < period:
        return float(np.mean(true_range))

    atr_val = np.mean(true_range[:period])
    for i in range(period, len(true_range)):
        atr_val = (atr_val * (period - 1) + true_range[i]) / period

    return float(atr_val)


def atr_percent(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> float:
    """ATR as a percentage of the latest close price."""
    if len(close) == 0:
        return 0.0
    atr_val = atr(high, low, close, period)
    return (atr_val / close[-1]) * 100


def avg_daily_volume_cr(volume: np.ndarray, close: np.ndarray, period: int = 20) -> float:
    """Average daily traded value in crores (volume * close / 1e7)."""
    if len(volume) < period:
        period = len(volume)
    if period == 0:
        return 0.0
    recent_vol = volume[-period:]
    recent_close = close[-period:]
    daily_value = recent_vol * recent_close
    return float(np.mean(daily_value) / 1e7)  # Convert to crores


def vwap(high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    """Calculate cumulative VWAP from start of data (should be from market open).

    Returns array of VWAP values, same length as input.
    """
    typical_price = (high + low + close) / 3
    cum_tp_vol = np.cumsum(typical_price * volume)
    cum_vol = np.cumsum(volume)

    # Avoid division by zero
    vwap_vals = np.where(cum_vol > 0, cum_tp_vol / cum_vol, typical_price)
    return vwap_vals


def vwap_crossover(close: np.ndarray, vwap_vals: np.ndarray) -> int:
    """Detect VWAP crossover on the latest candle.

    Returns:
        +1 if price crossed above VWAP (bullish)
        -1 if price crossed below VWAP (bearish)
         0 if no crossover
    """
    if len(close) < 2:
        return 0

    prev_above = close[-2] > vwap_vals[-2]
    curr_above = close[-1] > vwap_vals[-1]

    if not prev_above and curr_above:
        return 1
    elif prev_above and not curr_above:
        return -1
    return 0


def rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    """Calculate RSI using Wilder's smoothing method.

    Returns array of RSI values. First `period` values will be NaN.
    """
    if len(close) < period + 1:
        return np.full(len(close), np.nan)

    deltas = np.diff(close)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    rsi_vals = np.full(len(close), np.nan)

    # Seed with simple average
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    if avg_loss == 0:
        rsi_vals[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi_vals[period] = 100 - (100 / (1 + rs))

    # Wilder's smoothing for subsequent values
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            rsi_vals[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi_vals[i + 1] = 100 - (100 / (1 + rs))

    return rsi_vals


def ema(close: np.ndarray, period: int) -> np.ndarray:
    """Calculate Exponential Moving Average.

    Returns array of EMA values. First `period-1` values will be NaN.
    """
    if len(close) < period:
        return np.full(len(close), np.nan)

    ema_vals = np.full(len(close), np.nan)
    multiplier = 2.0 / (period + 1)

    # Seed with SMA
    ema_vals[period - 1] = np.mean(close[:period])

    for i in range(period, len(close)):
        ema_vals[i] = close[i] * multiplier + ema_vals[i - 1] * (1 - multiplier)

    return ema_vals


def ema_crossover(close: np.ndarray, fast_period: int = 9, slow_period: int = 21) -> int:
    """Detect EMA crossover on the latest candle.

    Returns:
        +1 if fast EMA crossed above slow EMA (bullish)
        -1 if fast EMA crossed below slow EMA (bearish)
         0 if no crossover or insufficient data
    """
    fast = ema(close, fast_period)
    slow = ema(close, slow_period)

    if np.isnan(fast[-1]) or np.isnan(slow[-1]) or np.isnan(fast[-2]) or np.isnan(slow[-2]):
        return 0

    prev_fast_above = fast[-2] > slow[-2]
    curr_fast_above = fast[-1] > slow[-1]

    if not prev_fast_above and curr_fast_above:
        return 1
    elif prev_fast_above and not curr_fast_above:
        return -1
    return 0


def volume_spike(volume: np.ndarray, lookback: int = 20) -> bool:
    """Check if latest candle volume is >= 2x the rolling average.

    Args:
        volume: Array of volumes (5-min candles).
        lookback: Number of candles for rolling average.
    """
    if len(volume) < lookback + 1:
        return False

    avg_vol = np.mean(volume[-(lookback + 1):-1])
    if avg_vol == 0:
        return False
    return float(volume[-1]) >= 2.0 * avg_vol


def volume_ratio(volume: np.ndarray, lookback: int = 20) -> float:
    """Current volume as a ratio of the rolling average."""
    if len(volume) < lookback + 1:
        return 0.0
    avg_vol = np.mean(volume[-(lookback + 1):-1])
    if avg_vol == 0:
        return 0.0
    return float(volume[-1] / avg_vol)


@dataclass
class ORBLevels:
    """Opening Range Breakout levels."""
    high: float
    low: float
    range_pct: float  # Range as % of midpoint


def calculate_orb(candles: CandleData, orb_candles: int = 3) -> Optional[ORBLevels]:
    """Calculate ORB levels from the first N candles (default 3 = 15 min on 5-min chart).

    Args:
        candles: Intraday 5-min candle data from market open.
        orb_candles: Number of candles for ORB (3 candles * 5 min = 15 min).
    """
    if len(candles.high) < orb_candles:
        return None

    orb_high = float(np.max(candles.high[:orb_candles]))
    orb_low = float(np.min(candles.low[:orb_candles]))
    midpoint = (orb_high + orb_low) / 2
    range_pct = ((orb_high - orb_low) / midpoint) * 100 if midpoint > 0 else 0

    return ORBLevels(high=orb_high, low=orb_low, range_pct=range_pct)


def orb_breakout(close: np.ndarray, orb: ORBLevels) -> int:
    """Check if latest close breaks ORB levels.

    Returns:
        +1 if close above ORB high (bullish breakout)
        -1 if close below ORB low (bearish breakout)
         0 if within range
    """
    if orb is None or len(close) == 0:
        return 0

    latest = float(close[-1])
    if latest > orb.high:
        return 1
    elif latest < orb.low:
        return -1
    return 0
