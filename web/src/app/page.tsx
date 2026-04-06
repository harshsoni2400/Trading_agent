"use client";

import { useState, useEffect } from "react";
import Nav from "@/components/Nav";

interface Position {
  tradingsymbol: string;
  quantity: number;
  average_price: number;
  last_price: number;
  pnl: number;
  product: string;
}

interface Order {
  order_id: string;
  tradingsymbol: string;
  transaction_type: string;
  quantity: number;
  average_price: number;
  status: string;
  order_timestamp: string;
}

export default function LiveTrading() {
  const [authenticated, setAuthenticated] = useState(false);
  const [loginUrl, setLoginUrl] = useState("");
  const [requestToken, setRequestToken] = useState("");
  const [profile, setProfile] = useState<{ user_name?: string; user_id?: string } | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [vix, setVix] = useState(0);
  const [nifty, setNifty] = useState({ lastPrice: 0, open: 0, close: 0 });
  const [margins, setMargins] = useState({ available: 0 });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    checkStatus();
  }, []);

  async function checkStatus() {
    const res = await fetch("/api/kite?action=status");
    const data = await res.json();
    setAuthenticated(data.authenticated);
    if (data.authenticated) {
      loadDashboard();
    } else {
      const urlRes = await fetch("/api/kite?action=login_url");
      const urlData = await urlRes.json();
      setLoginUrl(urlData.url);
    }
  }

  async function authenticate() {
    setLoading(true);
    setError("");
    try {
      const res = await fetch("/api/kite", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "authenticate", requestToken }),
      });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      setAuthenticated(true);
      loadDashboard();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Auth failed");
    }
    setLoading(false);
  }

  async function loadDashboard() {
    try {
      const [profileRes, posRes, orderRes, vixRes, niftyRes, marginRes] = await Promise.all([
        fetch("/api/kite?action=profile"),
        fetch("/api/kite?action=positions"),
        fetch("/api/kite?action=orders"),
        fetch("/api/kite?action=vix"),
        fetch("/api/kite?action=nifty"),
        fetch("/api/kite?action=margins"),
      ]);

      const profileData = await profileRes.json();
      const posData = await posRes.json();
      const orderData = await orderRes.json();
      const vixData = await vixRes.json();
      const niftyData = await niftyRes.json();
      const marginData = await marginRes.json();

      setProfile(profileData);
      const dayPositions = (posData?.day || []).filter((p: Position) => p.quantity !== 0);
      setPositions(dayPositions);
      setOrders(orderData || []);
      setVix(vixData.vix || 0);
      setNifty(niftyData);
      setMargins({ available: marginData?.equity?.available?.live_balance || 0 });
    } catch {}
  }

  const totalPnl = positions.reduce((sum, p) => sum + (p.pnl || 0), 0);
  const completedOrders = orders.filter((o) => o.status === "COMPLETE");
  const gapPct = nifty.close ? Math.abs(((nifty.open - nifty.close) / nifty.close) * 100) : 0;

  if (!authenticated) {
    return (
      <>
        <Nav />
        <main className="flex-1 flex items-center justify-center p-6">
          <div className="bg-gray-900 p-8 rounded-xl border border-gray-800 w-96">
            <h2 className="text-xl font-bold mb-4">Connect Kite</h2>
            {loginUrl && (
              <a href={loginUrl} target="_blank" rel="noopener noreferrer"
                className="block text-center bg-blue-600 hover:bg-blue-700 text-white py-2 rounded-lg mb-4">
                Login to Kite
              </a>
            )}
            <p className="text-gray-400 text-sm mb-3">After login, paste the request_token from the redirect URL:</p>
            <input
              type="text" value={requestToken} onChange={(e) => setRequestToken(e.target.value)}
              placeholder="Request token"
              className="w-full p-3 bg-gray-800 border border-gray-700 rounded-lg text-white mb-3"
            />
            <button onClick={authenticate} disabled={loading || !requestToken}
              className="w-full bg-green-600 hover:bg-green-700 disabled:bg-gray-700 text-white py-2 rounded-lg">
              {loading ? "Authenticating..." : "Connect"}
            </button>
            {error && <p className="text-red-400 text-sm mt-2">{error}</p>}
          </div>
        </main>
      </>
    );
  }

  return (
    <>
      <Nav />
      <main className="flex-1 p-6 space-y-6">
        <div className="grid grid-cols-2 md:grid-cols-6 gap-4">
          <MetricCard label="Total P&L" value={`${totalPnl >= 0 ? "+" : ""}${totalPnl.toFixed(0)}`}
            color={totalPnl >= 0 ? "text-green-400" : "text-red-400"} />
          <MetricCard label="Open Positions" value={positions.length.toString()} />
          <MetricCard label="Trades Today" value={completedOrders.length.toString()} />
          <MetricCard label="VIX" value={vix.toFixed(1)}
            color={vix <= 18 ? "text-green-400" : "text-red-400"} />
          <MetricCard label="Nifty Gap" value={`${gapPct.toFixed(1)}%`}
            color={gapPct <= 1 ? "text-green-400" : "text-yellow-400"} />
          <MetricCard label="Margin" value={`${(margins.available / 1000).toFixed(0)}K`} />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
            <h2 className="text-lg font-semibold mb-4">Open Positions</h2>
            {positions.length === 0 ? (
              <p className="text-gray-500 text-sm">No open positions</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-400 border-b border-gray-800">
                    <th className="text-left py-2">Symbol</th>
                    <th className="text-right py-2">Qty</th>
                    <th className="text-right py-2">Avg</th>
                    <th className="text-right py-2">LTP</th>
                    <th className="text-right py-2">P&L</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p, i) => (
                    <tr key={i} className="border-b border-gray-800/50">
                      <td className="py-2 font-medium">{p.tradingsymbol}</td>
                      <td className="text-right py-2">{p.quantity}</td>
                      <td className="text-right py-2">{p.average_price?.toFixed(2)}</td>
                      <td className="text-right py-2">{p.last_price?.toFixed(2)}</td>
                      <td className={`text-right py-2 font-medium ${p.pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                        {p.pnl >= 0 ? "+" : ""}{p.pnl?.toFixed(0)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
            <h2 className="text-lg font-semibold mb-4">Today&apos;s Orders</h2>
            {orders.length === 0 ? (
              <p className="text-gray-500 text-sm">No orders today</p>
            ) : (
              <div className="max-h-80 overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-gray-900">
                    <tr className="text-gray-400 border-b border-gray-800">
                      <th className="text-left py-2">Symbol</th>
                      <th className="text-left py-2">Side</th>
                      <th className="text-right py-2">Qty</th>
                      <th className="text-right py-2">Price</th>
                      <th className="text-left py-2">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {orders.slice(-20).reverse().map((o, i) => (
                      <tr key={i} className="border-b border-gray-800/50">
                        <td className="py-2">{o.tradingsymbol}</td>
                        <td className={`py-2 ${o.transaction_type === "BUY" ? "text-green-400" : "text-red-400"}`}>
                          {o.transaction_type}
                        </td>
                        <td className="text-right py-2">{o.quantity}</td>
                        <td className="text-right py-2">{o.average_price?.toFixed(2) || "-"}</td>
                        <td className="py-2">
                          <span className={`text-xs px-2 py-0.5 rounded ${
                            o.status === "COMPLETE" ? "bg-green-900 text-green-300" :
                            o.status === "REJECTED" ? "bg-red-900 text-red-300" :
                            "bg-yellow-900 text-yellow-300"
                          }`}>{o.status}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        <div className="flex justify-between items-center text-sm text-gray-500">
          <span>Logged in as {profile?.user_name} ({profile?.user_id})</span>
          <button onClick={loadDashboard} className="text-blue-400 hover:text-blue-300">Refresh</button>
        </div>
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
