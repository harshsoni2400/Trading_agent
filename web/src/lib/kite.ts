/** Kite Connect REST API client — server-side only. */

const BASE_URL = "https://api.kite.trade";

let accessToken: string | null = null;
let tokenDate: string | null = null;

export function setAccessToken(token: string) {
  accessToken = token;
  tokenDate = new Date().toISOString().split("T")[0];
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function isAuthenticated(): boolean {
  return !!accessToken;
}

function headers() {
  return {
    "X-Kite-Version": "3",
    Authorization: `token ${process.env.KITE_API_KEY}:${accessToken}`,
    "Content-Type": "application/x-www-form-urlencoded",
  };
}

async function kiteGet(path: string, params?: Record<string, string>) {
  const url = new URL(`${BASE_URL}${path}`);
  if (params) {
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  }
  const res = await fetch(url.toString(), { headers: headers() });
  const data = await res.json();
  if (data.status === "error") throw new Error(data.message);
  return data.data;
}

async function kitePost(path: string, body: Record<string, string>) {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: headers(),
    body: new URLSearchParams(body).toString(),
  });
  const data = await res.json();
  if (data.status === "error") throw new Error(data.message);
  return data.data;
}

// ── Auth ─────────────────────────────────────────────────────────

export function getLoginUrl(): string {
  return `https://kite.zerodha.com/connect/login?v=3&api_key=${process.env.KITE_API_KEY}`;
}

export async function generateSession(requestToken: string) {
  const crypto = await import("crypto");
  const checksum = crypto
    .createHash("sha256")
    .update(`${process.env.KITE_API_KEY}${requestToken}${process.env.KITE_API_SECRET}`)
    .digest("hex");

  const res = await fetch(`${BASE_URL}/session/token`, {
    method: "POST",
    headers: {
      "X-Kite-Version": "3",
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({
      api_key: process.env.KITE_API_KEY!,
      request_token: requestToken,
      checksum,
    }).toString(),
  });
  const data = await res.json();
  if (data.status === "error") throw new Error(data.message);
  setAccessToken(data.data.access_token);
  return data.data;
}

// ── Profile & Margins ────────────────────────────────────────────

export async function getProfile() {
  return kiteGet("/user/profile");
}

export async function getMargins() {
  return kiteGet("/user/margins");
}

// ── Market Data ──────────────────────────────────────────────────

export async function getLTP(symbols: string[]): Promise<Record<string, number>> {
  const instruments = symbols.map((s) => `NSE:${s}`).join("&i=");
  const data = await kiteGet(`/quote/ltp?i=${instruments}`);
  const result: Record<string, number> = {};
  for (const s of symbols) {
    const key = `NSE:${s}`;
    if (data[key]) result[s] = data[key].last_price;
  }
  return result;
}

export async function getOHLC(symbols: string[]) {
  const instruments = symbols.map((s) => `NSE:${s}`).join("&i=");
  return kiteGet(`/quote/ohlc?i=${instruments}`);
}

export async function getQuotes(symbols: string[]) {
  const instruments = symbols.map((s) => `NSE:${s}`).join("&i=");
  return kiteGet(`/quote?i=${instruments}`);
}

export async function getHistoricalData(
  instrumentToken: number,
  interval: string,
  from: string,
  to: string
) {
  return kiteGet(
    `/instruments/historical/${instrumentToken}/${interval}`,
    { from, to }
  );
}

// ── Instruments ──────────────────────────────────────────────────

let instrumentCache: Record<string, number> = {};

export async function loadInstruments(): Promise<Record<string, number>> {
  const res = await fetch(`${BASE_URL}/instruments/NSE`, { headers: headers() });
  const text = await res.text();
  const lines = text.split("\n").slice(1); // skip header
  instrumentCache = {};
  for (const line of lines) {
    const cols = line.split(",");
    if (cols.length > 2) {
      instrumentCache[cols[2]] = parseInt(cols[0]); // tradingsymbol -> token
    }
  }
  return instrumentCache;
}

export function getInstrumentToken(symbol: string): number | undefined {
  return instrumentCache[symbol];
}

export function getInstrumentCache() {
  return instrumentCache;
}

// ── Orders ───────────────────────────────────────────────────────

export async function placeOrder(params: {
  tradingsymbol: string;
  transaction_type: string;
  quantity: number;
  order_type: string;
  price?: number;
  trigger_price?: number;
  product?: string;
}) {
  const body: Record<string, string> = {
    exchange: "NSE",
    tradingsymbol: params.tradingsymbol,
    transaction_type: params.transaction_type,
    quantity: params.quantity.toString(),
    order_type: params.order_type,
    product: params.product || "MIS",
    validity: "DAY",
  };
  if (params.price) body.price = params.price.toString();
  if (params.trigger_price) body.trigger_price = params.trigger_price.toString();

  return kitePost("/orders/regular", body);
}

export async function modifyOrder(orderId: string, params: { trigger_price?: number; price?: number }) {
  const body: Record<string, string> = {};
  if (params.trigger_price) body.trigger_price = params.trigger_price.toString();
  if (params.price) body.price = params.price.toString();
  return kitePost(`/orders/regular/${orderId}`, body);
}

export async function cancelOrder(orderId: string) {
  const res = await fetch(`${BASE_URL}/orders/regular/${orderId}`, {
    method: "DELETE",
    headers: headers(),
  });
  return res.json();
}

export async function getOrders() {
  return kiteGet("/orders");
}

export async function getPositions() {
  return kiteGet("/portfolio/positions");
}

export async function getHoldings() {
  return kiteGet("/portfolio/holdings");
}

// ── VIX & Nifty ──────────────────────────────────────────────────

export async function getIndiaVIX(): Promise<number> {
  try {
    const data = await kiteGet("/quote/ltp?i=NSE:INDIA VIX");
    return data["NSE:INDIA VIX"]?.last_price || 0;
  } catch {
    return 0;
  }
}

export async function getNiftyData() {
  try {
    const data = await kiteGet("/quote/ohlc?i=NSE:NIFTY 50");
    const nifty = data["NSE:NIFTY 50"] || {};
    return {
      lastPrice: nifty.last_price || 0,
      open: nifty.ohlc?.open || 0,
      close: nifty.ohlc?.close || 0,
    };
  } catch {
    return { lastPrice: 0, open: 0, close: 0 };
  }
}
