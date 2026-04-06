"use client";

import { useState } from "react";
import Nav from "@/components/Nav";

interface OptResult {
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

interface OptResponse {
  results: OptResult[];
  best: OptResult | null;
  current: OptResult | null;
  totalCombinations: number;
  symbolsTested: number;
  months: number;
}

export default function OptimizerPage() {
  const [running, setRunning] = useState(false);
  const [data, setData] = useState<OptResponse | null>(null);
  const [params, setParams] = useState({ months: 3, maxStocks: 15 });

  async function runOptimizer() {
    setRunning(true);
    try {
      const res = await fetch("/api/optimizer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(params),
      });
      const result = await res.json();
      if (result.error) {
        alert(result.error);
      } else {
        setData(result);
      }
    } catch {
      alert("Optimizer failed. Make sure Kite is authenticated.");
    }
    setRunning(false);
  }

  return (
    <>
      <Nav />
      <main className="flex-1 p-6 space-y-6">
        <h1 className="text-2xl font-bold">Strategy Optimizer</h1>
        <p className="text-gray-400 text-sm">
          Grid search over target%, stop loss%, and min score to find the best parameter combination.
        </p>

        {/* Controls */}
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
          <div className="flex items-end gap-4">
            <div>
              <label className="text-xs text-gray-400">Months of Data</label>
              <input type="number" value={params.months}
                onChange={(e) => setParams({ ...params, months: +e.target.value })}
                className="w-full mt-1 p-2 bg-gray-800 border border-gray-700 rounded-lg text-white" />
            </div>
            <div>
              <label className="text-xs text-gray-400">Max Stocks</label>
              <input type="number" value={params.maxStocks}
                onChange={(e) => setParams({ ...params, maxStocks: +e.target.value })}
                className="w-full mt-1 p-2 bg-gray-800 border border-gray-700 rounded-lg text-white" />
            </div>
            <button onClick={runOptimizer} disabled={running}
              className="bg-purple-600 hover:bg-purple-700 disabled:bg-gray-700 text-white py-2 px-6 rounded-lg font-medium whitespace-nowrap">
              {running ? "Optimizing..." : "Run Optimizer"}
            </button>
          </div>
          {running && (
            <p className="text-yellow-400 text-sm mt-3">
              Testing 75 parameter combinations across {params.maxStocks} stocks. This may take a few minutes...
            </p>
          )}
        </div>

        {data && (
          <>
            {/* Summary */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
                <p className="text-xs text-gray-400 mb-1">Combinations Tested</p>
                <p className="text-xl font-bold">{data.totalCombinations}</p>
              </div>
              <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
                <p className="text-xs text-gray-400 mb-1">Stocks Tested</p>
                <p className="text-xl font-bold">{data.symbolsTested}</p>
              </div>
              <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
                <p className="text-xs text-gray-400 mb-1">Data Period</p>
                <p className="text-xl font-bold">{data.months} months</p>
              </div>
              <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
                <p className="text-xs text-gray-400 mb-1">Best Score</p>
                <p className="text-xl font-bold text-purple-400">{data.best?.score.toFixed(3)}</p>
              </div>
            </div>

            {/* Best vs Current */}
            {data.best && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <ParamCard title="Best Parameters" result={data.best} highlight="purple" />
                {data.current && (
                  <ParamCard title="Current Parameters" result={data.current} highlight="blue" />
                )}
              </div>
            )}

            {/* Results Table */}
            <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
              <h2 className="text-lg font-semibold mb-3">Top Parameter Combinations</h2>
              <div className="max-h-96 overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-gray-900">
                    <tr className="text-gray-400 border-b border-gray-800">
                      <th className="text-left py-2">#</th>
                      <th className="text-right py-2">Target%</th>
                      <th className="text-right py-2">SL%</th>
                      <th className="text-right py-2">Min Score</th>
                      <th className="text-right py-2">P&L</th>
                      <th className="text-right py-2">Trades</th>
                      <th className="text-right py-2">Win%</th>
                      <th className="text-right py-2">PF</th>
                      <th className="text-right py-2">Sharpe</th>
                      <th className="text-right py-2">Drawdown</th>
                      <th className="text-right py-2">Score</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.results.map((r, i) => (
                      <tr key={i} className={`border-b border-gray-800/50 ${i === 0 ? "bg-purple-900/20" : ""}`}>
                        <td className="py-2 text-gray-400">{i + 1}</td>
                        <td className="text-right py-2">{r.targetPct}%</td>
                        <td className="text-right py-2">{r.stoplossPct}%</td>
                        <td className="text-right py-2">{r.minScore}</td>
                        <td className={`text-right py-2 font-medium ${r.totalPnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                          {r.totalPnl >= 0 ? "+" : ""}{r.totalPnl.toFixed(0)}
                        </td>
                        <td className="text-right py-2">{r.totalTrades}</td>
                        <td className={`text-right py-2 ${r.winRate >= 50 ? "text-green-400" : "text-red-400"}`}>
                          {r.winRate.toFixed(0)}%
                        </td>
                        <td className="text-right py-2">{r.profitFactor.toFixed(2)}</td>
                        <td className="text-right py-2">{r.sharpeRatio.toFixed(2)}</td>
                        <td className="text-right py-2 text-red-400">{r.maxDrawdown.toFixed(0)}</td>
                        <td className="text-right py-2 font-medium text-purple-400">{r.score.toFixed(3)}</td>
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

function ParamCard({ title, result, highlight }: { title: string; result: OptResult; highlight: string }) {
  const borderColor = highlight === "purple" ? "border-purple-600" : "border-blue-600";
  const textColor = highlight === "purple" ? "text-purple-400" : "text-blue-400";

  return (
    <div className={`bg-gray-900 rounded-xl border ${borderColor} p-5`}>
      <h3 className={`text-sm font-semibold mb-3 ${textColor}`}>{title}</h3>
      <div className="grid grid-cols-3 gap-3 text-sm">
        <div>
          <p className="text-gray-400 text-xs">Target%</p>
          <p className="font-bold">{result.targetPct}%</p>
        </div>
        <div>
          <p className="text-gray-400 text-xs">Stop Loss%</p>
          <p className="font-bold">{result.stoplossPct}%</p>
        </div>
        <div>
          <p className="text-gray-400 text-xs">Min Score</p>
          <p className="font-bold">{result.minScore}</p>
        </div>
        <div>
          <p className="text-gray-400 text-xs">Total P&L</p>
          <p className={`font-bold ${result.totalPnl >= 0 ? "text-green-400" : "text-red-400"}`}>
            {result.totalPnl >= 0 ? "+" : ""}{result.totalPnl.toFixed(0)}
          </p>
        </div>
        <div>
          <p className="text-gray-400 text-xs">Win Rate</p>
          <p className={`font-bold ${result.winRate >= 50 ? "text-green-400" : "text-red-400"}`}>
            {result.winRate.toFixed(0)}%
          </p>
        </div>
        <div>
          <p className="text-gray-400 text-xs">Sharpe</p>
          <p className="font-bold">{result.sharpeRatio.toFixed(2)}</p>
        </div>
      </div>
    </div>
  );
}
