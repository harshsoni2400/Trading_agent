/** Technical indicators for intraday trading — TypeScript port. */

export interface Candle {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface ORBLevels {
  high: number;
  low: number;
  rangePct: number;
}

export function atr(candles: Candle[], period = 14): number {
  if (candles.length < period + 1) return 0;

  const tr: number[] = [];
  for (let i = 1; i < candles.length; i++) {
    const h = candles[i].high;
    const l = candles[i].low;
    const pc = candles[i - 1].close;
    tr.push(Math.max(h - l, Math.abs(h - pc), Math.abs(l - pc)));
  }

  let atrVal = tr.slice(0, period).reduce((a, b) => a + b, 0) / period;
  for (let i = period; i < tr.length; i++) {
    atrVal = (atrVal * (period - 1) + tr[i]) / period;
  }
  return atrVal;
}

export function atrPercent(candles: Candle[], period = 14): number {
  if (candles.length === 0) return 0;
  const a = atr(candles, period);
  return (a / candles[candles.length - 1].close) * 100;
}

export function avgDailyVolumeCr(candles: Candle[], period = 20): number {
  const n = Math.min(period, candles.length);
  if (n === 0) return 0;
  const recent = candles.slice(-n);
  const avg =
    recent.reduce((sum, c) => sum + c.volume * c.close, 0) / n;
  return avg / 1e7; // crores
}

export function vwap(candles: Candle[]): number[] {
  const result: number[] = [];
  let cumTpVol = 0;
  let cumVol = 0;

  for (const c of candles) {
    const tp = (c.high + c.low + c.close) / 3;
    cumTpVol += tp * c.volume;
    cumVol += c.volume;
    result.push(cumVol > 0 ? cumTpVol / cumVol : tp);
  }
  return result;
}

export function vwapCrossover(closes: number[], vwapVals: number[]): number {
  const n = closes.length;
  if (n < 2) return 0;
  const prevAbove = closes[n - 2] > vwapVals[n - 2];
  const currAbove = closes[n - 1] > vwapVals[n - 1];
  if (!prevAbove && currAbove) return 1;
  if (prevAbove && !currAbove) return -1;
  return 0;
}

export function rsi(closes: number[], period = 14): number[] {
  const result = new Array(closes.length).fill(NaN);
  if (closes.length < period + 1) return result;

  const deltas: number[] = [];
  for (let i = 1; i < closes.length; i++) {
    deltas.push(closes[i] - closes[i - 1]);
  }

  const gains = deltas.map((d) => (d > 0 ? d : 0));
  const losses = deltas.map((d) => (d < 0 ? -d : 0));

  let avgGain = gains.slice(0, period).reduce((a, b) => a + b, 0) / period;
  let avgLoss = losses.slice(0, period).reduce((a, b) => a + b, 0) / period;

  result[period] =
    avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);

  for (let i = period; i < deltas.length; i++) {
    avgGain = (avgGain * (period - 1) + gains[i]) / period;
    avgLoss = (avgLoss * (period - 1) + losses[i]) / period;
    result[i + 1] =
      avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  }
  return result;
}

export function ema(closes: number[], period: number): number[] {
  const result = new Array(closes.length).fill(NaN);
  if (closes.length < period) return result;

  const mult = 2 / (period + 1);
  result[period - 1] =
    closes.slice(0, period).reduce((a, b) => a + b, 0) / period;

  for (let i = period; i < closes.length; i++) {
    result[i] = closes[i] * mult + result[i - 1] * (1 - mult);
  }
  return result;
}

export function emaCrossover(
  closes: number[],
  fastPeriod = 9,
  slowPeriod = 21
): number {
  const fast = ema(closes, fastPeriod);
  const slow = ema(closes, slowPeriod);
  const n = closes.length;
  if (isNaN(fast[n - 1]) || isNaN(slow[n - 1]) || isNaN(fast[n - 2]) || isNaN(slow[n - 2]))
    return 0;

  const prevAbove = fast[n - 2] > slow[n - 2];
  const currAbove = fast[n - 1] > slow[n - 1];
  if (!prevAbove && currAbove) return 1;
  if (prevAbove && !currAbove) return -1;
  return 0;
}

export function volumeSpike(volumes: number[], lookback = 20): boolean {
  if (volumes.length < lookback + 1) return false;
  const avg =
    volumes.slice(-(lookback + 1), -1).reduce((a, b) => a + b, 0) / lookback;
  if (avg === 0) return false;
  return volumes[volumes.length - 1] >= 2 * avg;
}

export function volumeRatio(volumes: number[], lookback = 20): number {
  if (volumes.length < lookback + 1) return 0;
  const avg =
    volumes.slice(-(lookback + 1), -1).reduce((a, b) => a + b, 0) / lookback;
  if (avg === 0) return 0;
  return volumes[volumes.length - 1] / avg;
}

export function calculateOrb(candles: Candle[], orbCandles = 3): ORBLevels | null {
  if (candles.length < orbCandles) return null;
  const slice = candles.slice(0, orbCandles);
  const high = Math.max(...slice.map((c) => c.high));
  const low = Math.min(...slice.map((c) => c.low));
  const mid = (high + low) / 2;
  return { high, low, rangePct: mid > 0 ? ((high - low) / mid) * 100 : 0 };
}

export function orbBreakout(close: number, orb: ORBLevels | null): number {
  if (!orb) return 0;
  if (close > orb.high) return 1;
  if (close < orb.low) return -1;
  return 0;
}
