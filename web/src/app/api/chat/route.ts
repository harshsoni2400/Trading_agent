/** Claude Chat API route — streams responses with trading context. */

import { NextResponse } from "next/server";
import Anthropic from "@anthropic-ai/sdk";
import * as kite from "@/lib/kite";

const SYSTEM_PROMPT = `You are a trading assistant integrated into a Zerodha intraday trading bot dashboard.
You have access to the user's real-time trading data including positions, orders, P&L, and signals.

Your capabilities:
1. Answer questions about positions, trades, and P&L
2. Explain trading signals and why they were generated
3. Provide market analysis
4. Help understand risk management decisions
5. Execute trades when explicitly asked

When the user asks to place a trade, respond with a JSON block:
\`\`\`json
{"action":"TRADE","symbol":"...","side":"BUY/SELL","qty":N,"type":"MARKET/LIMIT","price":0}
\`\`\`

IMPORTANT: Always warn about risks. Confirm before placing orders. Use MIS for intraday.
Be concise. Use Indian market context (NSE, IST, INR).`;

async function getTradingContext(): Promise<string> {
  const parts: string[] = [];

  if (kite.isAuthenticated()) {
    try {
      const profile = await kite.getProfile();
      parts.push(`User: ${profile.user_name} (${profile.user_id})`);
    } catch {}

    try {
      const positions = await kite.getPositions();
      const day = positions.day?.filter((p: { quantity: number }) => p.quantity !== 0) || [];
      if (day.length > 0) {
        parts.push(`\nOpen Positions (${day.length}):`);
        for (const p of day) {
          parts.push(`  ${p.tradingsymbol}: qty=${p.quantity} avg=${p.average_price} last=${p.last_price} P&L=${p.pnl}`);
        }
      } else {
        parts.push("\nNo open positions.");
      }
    } catch {}

    try {
      const orders = await kite.getOrders();
      if (orders?.length) {
        const completed = orders.filter((o: { status: string }) => o.status === "COMPLETE");
        parts.push(`\nToday: ${completed.length} completed orders`);
      }
    } catch {}
  } else {
    parts.push("Kite not authenticated.");
  }

  return parts.join("\n");
}

export async function POST(request: Request) {
  const { messages } = await request.json();

  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return NextResponse.json({ error: "ANTHROPIC_API_KEY not set" }, { status: 500 });
  }

  const client = new Anthropic({ apiKey });
  const context = await getTradingContext();

  const now = new Date().toLocaleString("en-IN", { timeZone: "Asia/Kolkata" });
  const system = `${SYSTEM_PROMPT}\n\nCurrent time: ${now}\n\nTrading State:\n${context}`;

  const response = await client.messages.create({
    model: "claude-sonnet-4-20250514",
    max_tokens: 1024,
    system,
    messages,
  });

  const reply = response.content[0].type === "text" ? response.content[0].text : "";
  return NextResponse.json({ reply });
}
