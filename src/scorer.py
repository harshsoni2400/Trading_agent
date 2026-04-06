"""Multi-factor signal scoring engine.

Scores each stock 0-5 based on how many technical factors align.
A signal is generated when score >= min_score (default 3).
"""

from __future__ import annotations

from dataclasses import dataclass
from src.indicators import (
    CandleData, ORBLevels,
    vwap, vwap_crossover, rsi, ema_crossover,
    volume_spike, volume_ratio, orb_breakout,
)
from src.utils import Config


@dataclass
class Signal:
    """A scored trading signal."""
    symbol: str
    direction: int          # +1 for long, -1 for short
    score: int              # 0-5
    price: float            # Latest close
    factors: dict[str, int] # Factor name -> direction (+1/-1/0)
    rsi_value: float
    vwap_value: float
    volume_ratio: float

    @property
    def is_long(self) -> bool:
        return self.direction == 1

    @property
    def is_short(self) -> bool:
        return self.direction == -1

    def summary(self) -> str:
        direction_str = "LONG" if self.is_long else "SHORT"
        active = [f for f, d in self.factors.items() if d != 0]
        return (f"{self.symbol} {direction_str} score={self.score}/5 "
                f"price={self.price:.2f} RSI={self.rsi_value:.1f} "
                f"vol_ratio={self.volume_ratio:.1f}x factors=[{', '.join(active)}]")


def score_stock(
    symbol: str,
    candles: CandleData,
    orb_levels: ORBLevels | None,
    config: Config,
) -> Signal | None:
    """Score a stock based on 5 technical factors.

    Args:
        symbol: Stock symbol (e.g., "RELIANCE").
        candles: Intraday 5-min candle data from market open.
        orb_levels: Pre-computed ORB levels (first 15 min).
        config: Bot configuration.

    Returns:
        Signal if any factors triggered, None if insufficient data.
    """
    if len(candles.close) < config.ema_slow + 2:
        return None

    factors: dict[str, int] = {}

    # Factor 1: VWAP Crossover with volume confirmation
    vwap_vals = vwap(candles.high, candles.low, candles.close, candles.volume)
    vwap_cross = vwap_crossover(candles.close, vwap_vals)
    vol_rat = volume_ratio(candles.volume)
    if vwap_cross != 0 and vol_rat >= config.vwap_volume_multiplier:
        factors["vwap"] = vwap_cross
    else:
        factors["vwap"] = 0

    # Factor 2: RSI zone
    rsi_vals = rsi(candles.close, config.rsi_period)
    latest_rsi = float(rsi_vals[-1]) if not __import__("numpy").isnan(rsi_vals[-1]) else 50.0
    if 30 <= latest_rsi <= 40:
        factors["rsi"] = 1   # Oversold bounce (bullish)
    elif 60 <= latest_rsi <= 70:
        factors["rsi"] = 1   # Momentum continuation (bullish)
    elif 70 <= latest_rsi <= 80:
        factors["rsi"] = -1  # Overbought (bearish)
    elif 20 <= latest_rsi <= 30:
        factors["rsi"] = -1  # Deep oversold, could break further
    else:
        factors["rsi"] = 0

    # Factor 3: EMA Crossover
    ema_cross = ema_crossover(candles.close, config.ema_fast, config.ema_slow)
    factors["ema"] = ema_cross

    # Factor 4: Volume Spike
    has_spike = volume_spike(candles.volume)
    factors["volume"] = 1 if has_spike else 0  # Volume spike is directionally neutral, confirms other signals

    # Factor 5: ORB Breakout
    orb_break = orb_breakout(candles.close, orb_levels)
    factors["orb"] = orb_break

    # Determine overall direction from directional factors
    directional_factors = [v for k, v in factors.items() if v != 0 and k != "volume"]
    if not directional_factors:
        return Signal(
            symbol=symbol, direction=0, score=0,
            price=float(candles.close[-1]), factors=factors,
            rsi_value=latest_rsi, vwap_value=float(vwap_vals[-1]),
            volume_ratio=vol_rat,
        )

    # Direction = majority vote of directional signals
    direction = 1 if sum(directional_factors) > 0 else -1

    # Score = count of factors aligned with the direction
    score = 0
    for name, val in factors.items():
        if name == "volume":
            # Volume spike adds to score regardless of direction (confirms momentum)
            if val != 0:
                score += 1
        elif val == direction:
            score += 1

    return Signal(
        symbol=symbol,
        direction=direction,
        score=score,
        price=float(candles.close[-1]),
        factors=factors,
        rsi_value=latest_rsi,
        vwap_value=float(vwap_vals[-1]),
        volume_ratio=vol_rat,
    )
