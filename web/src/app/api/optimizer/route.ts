/** Optimizer API — grid search over parameters using backtest simulation. */

import { NextResponse } from "next/server";
import * as kite from "@/lib/kite";
import { Candle, calculateOrb } from "@/lib/indicators";
import { scoreStock } from "@/lib/scorer";
import { NIFTY_200_TOP, DEFAULT_CONFIG } from "@/lib/config";

interface OptParams {
  months: number;
  maxStocks: number;
}

interface SimResult {
  targetPct: number;
  stoplossPct: number;
  minScore: number;
  totalPnl: number;
  totalTrades: number;
  winRate: number;
  profitFactor: number;
  sharpeRatio: number;
  maxDrawdown: number;
  score: number;
}

function formatDate(d: Date): string {
  return d.toISOString().split("T")[0];
}

function parseCandlesFromKite(raw: { candles: (string | number)[][] }): Candle[] {
  if (!raw?.candles) return [];
  return raw.candles.map((c) => ({
    date: c[0] as string,
    open: c[1] as number,
    high: c[2] as number,
    low: c[3] as number,
    close: c[4] as number,
    volume: c[5] as number,
  }));
}

function groupCandlesByDay(candles: Candle[]): Map<string, Candle[]> {
  const days = new Map<string, Candle[]>();
  for (const c of candles) {
    const day = c.date.substring(0, 10);
    if (!days.has(day)) days.set(day, []);
    days.get(day)!.push(c);
  }
  return days;
}

function simulateDayWithParams(
  dayCandles: Candle[],
  symbol: string,
  targetPct: number,
  stoplossPct: number,
  minScore: number,
  perTrade: number
): { pnl: number; won: boolean } | null {
  if (dayCandles.length < 25) return null;
  const orb = calculateOrb(dayCandles, 3);

  for (let i = Math.max(6, DEFAULT_CONFIG.signals.emaSlow + 2); i < dayCandles.length - 2; i++) {
    const slice = dayCandles.slice(0, i + 1);
    const signal = scoreStock(symbol, slice, orb, { ...DEFAULT_CONFIG.signals, minScore });
    if (!signal || signal.score < minScore || signal.direction !== 1) continue;

    const entryPrice = dayCandles[i].close;
    const qty = Math.floor(perTrade / entryPrice);
    if (qty <= 0) continue;

    const target = entryPrice * (1 + targetPct / 100);
    const stoploss = entryPrice * (1 - stoplossPct / 100);

    for (let j = i + 1; j < dayCandles.length; j++) {
      const c = dayCandles[j];
      if (c.low <= stoploss) return { pnl: (stoploss - entryPrice) * qty, won: false };
      if (c.high >= target) return { pnl: (target - entryPrice) * qty, won: true };
    }

    const lastClose = dayCandles[dayCandles.length - 1].close;
    const pnl = (lastClose - entryPrice) * qty;
    return { pnl, won: pnl > 0 };
  }
  return null;
}

// Parameter grid
const TARGET_PCTS = [0.8, 1.0, 1.2, 1.5, 2.0];
const STOPLOSS_PCTS = [0.4, 0.5, 0.6, 0.8, 1.0];
const MIN_SCORES = [2, 3, 4];

export async function POST(request: Request) {
  try {
    const { months = 3, maxStocks = 15 }: OptParams = await request.json();

    if (!kite.isAuthenticated()) {
      return NextResponse.json({ error: "Not authenticated with Kite" }, { status: 401 });
    }

    let instruments = kite.getInstrumentCache();
    if (Object.keys(instruments).length === 0) {
      instruments = await kite.loadInstruments();
    }

    const symbols = NIFTY_200_TOP.filter((s) => instruments[s]).slice(0, maxStocks);
    const to = new Date();
    const from = new Date();
    from.setMonth(from.getMonth() - months);
    const perTrade = DEFAULT_CONFIG.capital.perTrade;

    // Fetch all historical data first
    const allDayData: Map<string, Map<string, Candle[]>> = new Map(); // symbol -> day -> candles

    for (let batch = 0; batch < symbols.length; batch += 5) {
      const batchSymbols = symbols.slice(batch, batch + 5);
      await Promise.all(
        batchSymbols.map(async (symbol) => {
          try {
            const token = instruments[symbol];
            const raw = await kite.getHistoricalData(token, "5minute", formatDate(from), formatDate(to));
            const candles = parseCandlesFromKite(raw);
            allDayData.set(symbol, groupCandlesByDay(candles));
          } catch {}
        })
      );
      if (batch + 5 < symbols.length) await new Promise((r) => setTimeout(r, 500));
    }

    // Grid search
    const results: SimResult[] = [];

    for (const targetPct of TARGET_PCTS) {
      for (const stoplossPct of STOPLOSS_PCTS) {
        for (const minScore of MIN_SCORES) {
          let totalPnl = 0;
          let wins = 0;
          let losses = 0;
          let grossWin = 0;
          let grossLoss = 0;
          const dailyPnlMap = new Map<string, number>();

          for (const [symbol, dayMap] of allDayData) {
            for (const [day, dayCandles] of dayMap) {
              const result = simulateDayWithParams(dayCandles, symbol, targetPct, stoplossPct, minScore, perTrade);
              if (!result) continue;
              totalPnl += result.pnl;
              if (result.won) { wins++; grossWin += result.pnl; }
              else { losses++; grossLoss += Math.abs(result.pnl); }
              dailyPnlMap.set(day, (dailyPnlMap.get(day) || 0) + result.pnl);
            }
          }

          const totalTrades = wins + losses;
          const winRate = totalTrades > 0 ? (wins / totalTrades) * 100 : 0;
          const profitFactor = grossLoss > 0 ? grossWin / grossLoss : grossWin > 0 ? 999 : 0;

          // Equity curve for drawdown + sharpe
          let cumPnl = 0;
          let peak = 0;
          let maxDrawdown = 0;
          const dailyReturns: number[] = [];
          for (const [, pnl] of [...dailyPnlMap.entries()].sort()) {
            cumPnl += pnl;
            dailyReturns.push(pnl);
            if (cumPnl > peak) peak = cumPnl;
            const dd = peak - cumPnl;
            if (dd > maxDrawdown) maxDrawdown = dd;
          }

          const avgRet = dailyReturns.length > 0 ? dailyReturns.reduce((a, b) => a + b, 0) / dailyReturns.length : 0;
          const stdDev = dailyReturns.length > 1
            ? Math.sqrt(dailyReturns.reduce((s, r) => s + (r - avgRet) ** 2, 0) / (dailyReturns.length - 1))
            : 1;
          const sharpeRatio = stdDev > 0 ? (avgRet / stdDev) * Math.sqrt(252) : 0;

          // Composite score: weighted sharpe + profit factor + win rate - drawdown penalty
          const score =
            sharpeRatio * 0.4 +
            Math.min(profitFactor, 5) * 0.3 +
            (winRate / 100) * 0.2 -
            (maxDrawdown / (perTrade * 2)) * 0.1;

          results.push({
            targetPct, stoplossPct, minScore,
            totalPnl, totalTrades, winRate, profitFactor, sharpeRatio, maxDrawdown, score,
          });
        }
      }
    }

    results.sort((a, b) => b.score - a.score);

    const best = results[0] || null;
    const current = results.find(
      (r) =>
        r.targetPct === DEFAULT_CONFIG.exits.targetPct &&
        r.stoplossPct === DEFAULT_CONFIG.exits.stoplossPct &&
        r.minScore === DEFAULT_CONFIG.signals.minScore
    ) || null;

    return NextResponse.json({
      results: results.slice(0, 20), // top 20
      best,
      current,
      totalCombinations: results.length,
      symbolsTested: symbols.length,
      months,
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Optimization failed";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
