/** Backtest API — simulates trading on historical 5-min data from Kite. */

import { NextResponse } from "next/server";
import * as kite from "@/lib/kite";
import { Candle, calculateOrb, atrPercent, avgDailyVolumeCr } from "@/lib/indicators";
import { scoreStock } from "@/lib/scorer";
import { NIFTY_200_TOP, DEFAULT_CONFIG } from "@/lib/config";

interface BacktestParams {
  months: number;
  targetPct: number;
  stoplossPct: number;
  minScore: number;
  maxStocks: number;
}

interface Trade {
  date: string;
  symbol: string;
  entryTime: string;
  exitTime: string;
  entryPrice: number;
  exitPrice: number;
  qty: number;
  pnl: number;
  pnlPct: number;
  exitReason: string;
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

function simulateDay(
  dayCandles: Candle[],
  symbol: string,
  params: BacktestParams,
  perTrade: number
): Trade | null {
  if (dayCandles.length < 25) return null; // need enough candles

  // First 3 candles (15 min) for ORB
  const orb = calculateOrb(dayCandles, 3);

  // Walk through candles starting from candle index 6 (~30 min after open)
  for (let i = Math.max(6, DEFAULT_CONFIG.signals.emaSlow + 2); i < dayCandles.length - 2; i++) {
    const slice = dayCandles.slice(0, i + 1);
    const signal = scoreStock(symbol, slice, orb, {
      ...DEFAULT_CONFIG.signals,
      minScore: params.minScore,
    });

    if (!signal || signal.score < params.minScore || signal.direction !== 1) continue;

    // Entry
    const entryPrice = dayCandles[i].close;
    const qty = Math.floor(perTrade / entryPrice);
    if (qty <= 0) continue;

    const target = entryPrice * (1 + params.targetPct / 100);
    const stoploss = entryPrice * (1 - params.stoplossPct / 100);

    // Simulate from next candle
    for (let j = i + 1; j < dayCandles.length; j++) {
      const candle = dayCandles[j];

      // Check stoploss hit (check low first — worst case)
      if (candle.low <= stoploss) {
        const pnl = (stoploss - entryPrice) * qty;
        return {
          date: dayCandles[0].date.substring(0, 10),
          symbol,
          entryTime: dayCandles[i].date,
          exitTime: candle.date,
          entryPrice,
          exitPrice: stoploss,
          qty,
          pnl,
          pnlPct: ((stoploss - entryPrice) / entryPrice) * 100,
          exitReason: "stoploss",
          score: signal.score,
        };
      }

      // Check target hit
      if (candle.high >= target) {
        const pnl = (target - entryPrice) * qty;
        return {
          date: dayCandles[0].date.substring(0, 10),
          symbol,
          entryTime: dayCandles[i].date,
          exitTime: candle.date,
          entryPrice,
          exitPrice: target,
          qty,
          pnl,
          pnlPct: ((target - entryPrice) / entryPrice) * 100,
          exitReason: "target",
          score: signal.score,
        };
      }
    }

    // EOD squareoff
    const lastCandle = dayCandles[dayCandles.length - 1];
    const pnl = (lastCandle.close - entryPrice) * qty;
    return {
      date: dayCandles[0].date.substring(0, 10),
      symbol,
      entryTime: dayCandles[i].date,
      exitTime: lastCandle.date,
      entryPrice,
      exitPrice: lastCandle.close,
      qty,
      pnl,
      pnlPct: ((lastCandle.close - entryPrice) / entryPrice) * 100,
      exitReason: "eod",
      score: signal.score,
    };
  }

  return null;
}

export async function POST(request: Request) {
  try {
    const params: BacktestParams = await request.json();
    const { months = 3, targetPct = 1.2, stoplossPct = 0.6, minScore = 3, maxStocks = 30 } = params;

    if (!kite.isAuthenticated()) {
      return NextResponse.json({ error: "Not authenticated with Kite" }, { status: 401 });
    }

    // Load instruments if needed
    let instruments = kite.getInstrumentCache();
    if (Object.keys(instruments).length === 0) {
      instruments = await kite.loadInstruments();
    }

    // Pick stocks that have instrument tokens
    const symbols = NIFTY_200_TOP.filter((s) => instruments[s]).slice(0, maxStocks);

    const to = new Date();
    const from = new Date();
    from.setMonth(from.getMonth() - months);

    const allTrades: Trade[] = [];
    const perTrade = DEFAULT_CONFIG.capital.perTrade;

    // Fetch historical data and simulate for each symbol
    // Process in batches of 5 to avoid rate limits
    for (let batch = 0; batch < symbols.length; batch += 5) {
      const batchSymbols = symbols.slice(batch, batch + 5);

      const results = await Promise.all(
        batchSymbols.map(async (symbol) => {
          try {
            const token = instruments[symbol];
            const raw = await kite.getHistoricalData(
              token,
              "5minute",
              formatDate(from),
              formatDate(to)
            );
            const candles = parseCandlesFromKite(raw);
            const dayMap = groupCandlesByDay(candles);

            const trades: Trade[] = [];
            for (const [, dayCandles] of dayMap) {
              const trade = simulateDay(dayCandles, symbol, { months, targetPct, stoplossPct, minScore, maxStocks }, perTrade);
              if (trade) trades.push(trade);
            }
            return trades;
          } catch {
            return [];
          }
        })
      );

      for (const trades of results) {
        allTrades.push(...trades);
      }

      // Rate limit pause between batches
      if (batch + 5 < symbols.length) {
        await new Promise((r) => setTimeout(r, 500));
      }
    }

    // Sort trades by date
    allTrades.sort((a, b) => a.date.localeCompare(b.date));

    // Compute metrics
    const winners = allTrades.filter((t) => t.pnl > 0);
    const losers = allTrades.filter((t) => t.pnl <= 0);
    const totalPnl = allTrades.reduce((s, t) => s + t.pnl, 0);
    const winRate = allTrades.length > 0 ? (winners.length / allTrades.length) * 100 : 0;
    const avgWin = winners.length > 0 ? winners.reduce((s, t) => s + t.pnl, 0) / winners.length : 0;
    const avgLoss = losers.length > 0 ? losers.reduce((s, t) => s + t.pnl, 0) / losers.length : 0;
    const grossWins = winners.reduce((s, t) => s + t.pnl, 0);
    const grossLosses = Math.abs(losers.reduce((s, t) => s + t.pnl, 0));
    const profitFactor = grossLosses > 0 ? grossWins / grossLosses : grossWins > 0 ? 999 : 0;

    // Equity curve
    let cumPnl = 0;
    const equityCurve: number[] = [];
    const dates: string[] = [];
    const dailyPnl = new Map<string, number>();
    for (const t of allTrades) {
      dailyPnl.set(t.date, (dailyPnl.get(t.date) || 0) + t.pnl);
    }
    for (const [date, pnl] of [...dailyPnl.entries()].sort()) {
      cumPnl += pnl;
      equityCurve.push(cumPnl);
      dates.push(date);
    }

    // Max drawdown
    let peak = 0;
    let maxDrawdown = 0;
    for (const val of equityCurve) {
      if (val > peak) peak = val;
      const dd = peak - val;
      if (dd > maxDrawdown) maxDrawdown = dd;
    }

    // Sharpe ratio (annualized from daily returns)
    const dailyReturns = [...dailyPnl.values()];
    const avgReturn = dailyReturns.length > 0 ? dailyReturns.reduce((a, b) => a + b, 0) / dailyReturns.length : 0;
    const stdDev = dailyReturns.length > 1
      ? Math.sqrt(dailyReturns.reduce((s, r) => s + (r - avgReturn) ** 2, 0) / (dailyReturns.length - 1))
      : 1;
    const sharpeRatio = stdDev > 0 ? (avgReturn / stdDev) * Math.sqrt(252) : 0;

    return NextResponse.json({
      totalPnl,
      totalTrades: allTrades.length,
      winners: winners.length,
      losers: losers.length,
      winRate,
      avgWin,
      avgLoss,
      profitFactor,
      maxDrawdown,
      sharpeRatio,
      tradingDays: dailyPnl.size,
      trades: allTrades,
      equityCurve,
      dates,
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Backtest failed";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
