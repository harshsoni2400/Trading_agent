/** Multi-factor signal scoring engine. */

import {
  Candle,
  ORBLevels,
  vwap,
  vwapCrossover,
  rsi,
  emaCrossover,
  volumeSpike,
  volumeRatio,
  orbBreakout,
} from "./indicators";

export interface Signal {
  symbol: string;
  direction: number; // +1 long, -1 short, 0 neutral
  score: number;
  price: number;
  rsi: number;
  vwapValue: number;
  volumeRatio: number;
  factors: Record<string, number>;
}

export interface ScorerConfig {
  rsiPeriod: number;
  emaFast: number;
  emaSlow: number;
  vwapVolumeMultiplier: number;
  minScore: number;
}

const DEFAULT_CONFIG: ScorerConfig = {
  rsiPeriod: 14,
  emaFast: 9,
  emaSlow: 21,
  vwapVolumeMultiplier: 1.5,
  minScore: 3,
};

export function scoreStock(
  symbol: string,
  candles: Candle[],
  orb: ORBLevels | null,
  config: ScorerConfig = DEFAULT_CONFIG
): Signal | null {
  if (candles.length < config.emaSlow + 2) return null;

  const closes = candles.map((c) => c.close);
  const highs = candles.map((c) => c.high);
  const lows = candles.map((c) => c.low);
  const volumes = candles.map((c) => c.volume);

  const factors: Record<string, number> = {};

  // Factor 1: VWAP crossover with volume
  const vwapVals = vwap(candles);
  const vwapCross = vwapCrossover(closes, vwapVals);
  const volRat = volumeRatio(volumes);
  factors.vwap = vwapCross !== 0 && volRat >= config.vwapVolumeMultiplier ? vwapCross : 0;

  // Factor 2: RSI zone
  const rsiVals = rsi(closes, config.rsiPeriod);
  const latestRsi = isNaN(rsiVals[rsiVals.length - 1]) ? 50 : rsiVals[rsiVals.length - 1];
  if (latestRsi >= 30 && latestRsi <= 40) factors.rsi = 1;
  else if (latestRsi >= 60 && latestRsi <= 70) factors.rsi = 1;
  else if (latestRsi >= 70 && latestRsi <= 80) factors.rsi = -1;
  else if (latestRsi >= 20 && latestRsi <= 30) factors.rsi = -1;
  else factors.rsi = 0;

  // Factor 3: EMA crossover
  factors.ema = emaCrossover(closes, config.emaFast, config.emaSlow);

  // Factor 4: Volume spike
  factors.volume = volumeSpike(volumes) ? 1 : 0;

  // Factor 5: ORB breakout
  factors.orb = orbBreakout(closes[closes.length - 1], orb);

  // Direction from majority vote
  const directional = Object.entries(factors)
    .filter(([k, v]) => v !== 0 && k !== "volume")
    .map(([, v]) => v);

  if (directional.length === 0) {
    return {
      symbol, direction: 0, score: 0,
      price: closes[closes.length - 1],
      rsi: latestRsi,
      vwapValue: vwapVals[vwapVals.length - 1],
      volumeRatio: volRat,
      factors,
    };
  }

  const direction = directional.reduce((a, b) => a + b, 0) > 0 ? 1 : -1;
  let score = 0;
  for (const [name, val] of Object.entries(factors)) {
    if (name === "volume" && val !== 0) score++;
    else if (val === direction) score++;
  }

  return {
    symbol, direction, score,
    price: closes[closes.length - 1],
    rsi: latestRsi,
    vwapValue: vwapVals[vwapVals.length - 1],
    volumeRatio: volRat,
    factors,
  };
}
