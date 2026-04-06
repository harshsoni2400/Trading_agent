"use client";

import { useState } from "react";
import Nav from "@/components/Nav";

interface BacktestTrade {
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

interface BacktestResult {
  totalPnl: number;
  totalTrades: number;
  winners: number;
  losers: number;
  winRate: number;
  avgWin: number;
  avgLoss: number;
  profitFactor: number;
  maxDrawdown: number;
  sharpeRatio: number;
  tradingDays: number;
  trades: BacktestTrade[];
  equityCurve: number[];
  dates: string[];
}

export default function BacktestPage() {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [params, setParams] = useState({
    months: 3,
    targetPct: 1.2,
    stoplossPct: 0.6,
    minScore: 3,
    maxStocks: 30,
  });

  async function runBacktest() {
    setRunning(true);
    try {
      const res = await fetch("/api/backtest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(params),
      });
      const data = await res.json();
      setResult(data);
    } catch {
      alert("Backtest failed. Make sure Kite is authenticated.");
    }
    setRunning(false);
  }

  return (
    <>
      <Nav />
      <main className="flex-1 p-6 space-y-6">
        <h1 className="text-2xl font-bold">Strategy Backtester</h1>

        {/* Parameters */}
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
          <h2 className="text-lg font-semibold mb-4">Parameters</h2>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <div>
              <label className="text-xs text-gray-400">Months</label>
              <input type="number" value={params.months} onChange={(e) => setParams({ ...params, months: +e.target.value })}
                className="w-full mt-1 p-2 bg-gray-800 border border-gray-700 rounded-lg text-white" />
            </div>
            <div>
              <label className="text-xs text-gray-400">Target %</label>
              <input type="number" step="0.1" value={params.targetPct} onChange={(e) => setParams({ ...params, targetPct: +e.target.value })}
                className="w-full mt-1 p-2 bg-gray-800 border border-gray-700 rounded-lg text-white" />
            </div>
            <div>
              <label className="text-xs text-gray-400">Stop Loss %</label>
              <input type="number" step="0.1" value={params.stoplossPct} onChange={(e) => setParams({ ...params, stoplossPct: +e.target.value })}
                className="w-full mt-1 p-2 bg-gray-800 border border-gray-700 rounded-lg text-white" />
            </div>
            <div>
              <label className="text-xs text-gray-400">Min Score</label>
              <select value={params.minScore} onChange={(e) => setParams({ ...params, minScore: +e.target.value })}
                className="w-full mt-1 p-2 bg-gray-800 border border-gray-700 rounded-lg text-white">
                <option value={2}>2</option>
                <option value={3}>3</option>
                <option value={4}>4</option>
              </select>
            </div>
            <div className="flex items-end">
              <button onClick={runBacktest} disabled={running}
                className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 text-white py-2 rounded-lg font-medium">
                {running ? "Running..." : "Run Backtest"}
              </button>
            </div>
          </div>
        </div>

        {/* Results */}
        {result && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-6 gap-4">
              <MetricCard label="Total P&L" value={`${result.totalPnl >= 0 ? "+" : ""}${result.totalPnl.toFixed(0)}`}
                color={result.totalPnl >= 0 ? "text-green-400" : "text-red-400"} />
              <MetricCard label="Total Trades" value={result.totalTrades.toString()} />
              <MetricCard label="Win Rate" value={`${result.winRate.toFixed(0)}%`}
                color={result.winRate >= 50 ? "text-green-400" : "text-red-400"} />
              <MetricCard label="Profit Factor" value={result.profitFactor.toFixed(2)} />
              <MetricCard label="Max Drawdown" value={result.maxDrawdown.toFixed(0)} />
              <MetricCard label="Sharpe" value={result.sharpeRatio.toFixed(2)} />
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <MetricCard label="Winners" value={result.winners.toString()} color="text-green-400" />
              <MetricCard label="Losers" value={result.losers.toString()} color="text-red-400" />
              <MetricCard label="Avg Win" value={`+${result.avgWin.toFixed(0)}`} color="text-green-400" />
              <MetricCard label="Avg Loss" value={result.avgLoss.toFixed(0)} color="text-red-400" />
            </div>

            {/* Equity curve (simple text-based for now) */}
            {result.equityCurve.length > 0 && (
              <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
                <h2 className="text-lg font-semibold mb-3">Equity Curve</h2>
                <div className="flex items-end gap-0.5 h-40">
                  {result.equityCurve.map((val, i) => {
                    const min = Math.min(...result.equityCurve);
                    const max = Math.max(...result.equityCurve);
                    const range = max - min || 1;
                    const height = ((val - min) / range) * 100;
                    return (
                      <div key={i} className="flex-1 rounded-t"
                        style={{
                          height: `${Math.max(height, 2)}%`,
                          backgroundColor: val >= result.equityCurve[0] ? "#22c55e" : "#ef4444",
                        }}
                        title={`${result.dates[i]}: ${val.toFixed(0)}`}
                      />
                    );
                  })}
                </div>
                <div className="flex justify-between text-xs text-gray-500 mt-1">
                  <span>{result.dates[0]}</span>
                  <span>{result.dates[result.dates.length - 1]}</span>
                </div>
              </div>
            )}

            {/* Trades table */}
            <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
              <h2 className="text-lg font-semibold mb-3">All Trades ({result.trades.length})</h2>
              <div className="max-h-96 overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-gray-900">
                    <tr className="text-gray-400 border-b border-gray-800">
                      <th className="text-left py-2">Date</th>
                      <th className="text-left py-2">Symbol</th>
                      <th className="text-right py-2">Entry</th>
                      <th className="text-right py-2">Exit</th>
                      <th className="text-right py-2">P&L</th>
                      <th className="text-right py-2">%</th>
                      <th className="text-left py-2">Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.trades.map((t, i) => (
                      <tr key={i} className="border-b border-gray-800/50">
                        <td className="py-2 text-gray-400">{t.date}</td>
                        <td className="py-2 font-medium">{t.symbol}</td>
                        <td className="text-right py-2">{t.entryPrice.toFixed(2)}</td>
                        <td className="text-right py-2">{t.exitPrice.toFixed(2)}</td>
                        <td className={`text-right py-2 font-medium ${t.pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                          {t.pnl >= 0 ? "+" : ""}{t.pnl.toFixed(0)}
                        </td>
                        <td className={`text-right py-2 ${t.pnlPct >= 0 ? "text-green-400" : "text-red-400"}`}>
                          {t.pnlPct >= 0 ? "+" : ""}{t.pnlPct.toFixed(1)}%
                        </td>
                        <td className="py-2">
                          <span className={`text-xs px-2 py-0.5 rounded ${
                            t.exitReason === "target" ? "bg-green-900 text-green-300" :
                            t.exitReason === "stoploss" ? "bg-red-900 text-red-300" :
                            "bg-yellow-900 text-yellow-300"
                          }`}>{t.exitReason}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </main>
    </>
  );
}

function MetricCard({ label, value, color = "text-white" }: { label: string; value: string; color?: string }) {
  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
      <p className="text-xs text-gray-400 mb-1">{label}</p>
      <p className={`text-xl font-bold ${color}`}>{value}</p>
    </div>
  );
}
