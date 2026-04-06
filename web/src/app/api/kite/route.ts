/** Kite API proxy routes — handles auth, market data, orders. */

import { NextResponse } from "next/server";
import * as kite from "@/lib/kite";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const action = searchParams.get("action");

  try {
    switch (action) {
      case "login_url":
        return NextResponse.json({ url: kite.getLoginUrl() });

      case "status":
        return NextResponse.json({ authenticated: kite.isAuthenticated() });

      case "profile":
        return NextResponse.json(await kite.getProfile());

      case "margins":
        return NextResponse.json(await kite.getMargins());

      case "positions":
        return NextResponse.json(await kite.getPositions());

      case "orders":
        return NextResponse.json(await kite.getOrders());

      case "holdings":
        return NextResponse.json(await kite.getHoldings());

      case "vix":
        return NextResponse.json({ vix: await kite.getIndiaVIX() });

      case "nifty":
        return NextResponse.json(await kite.getNiftyData());

      case "ltp": {
        const symbols = searchParams.get("symbols")?.split(",") || [];
        return NextResponse.json(await kite.getLTP(symbols));
      }

      case "historical": {
        const token = parseInt(searchParams.get("token") || "0");
        const interval = searchParams.get("interval") || "5minute";
        const from = searchParams.get("from") || "";
        const to = searchParams.get("to") || "";
        const data = await kite.getHistoricalData(token, interval, from, to);
        return NextResponse.json(data);
      }

      case "instruments":
        const cache = kite.getInstrumentCache();
        if (Object.keys(cache).length > 0) {
          return NextResponse.json(cache);
        }
        return NextResponse.json(await kite.loadInstruments());

      default:
        return NextResponse.json({ error: "Unknown action" }, { status: 400 });
    }
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function POST(request: Request) {
  const body = await request.json();
  const { action } = body;

  try {
    switch (action) {
      case "authenticate": {
        const data = await kite.generateSession(body.requestToken);
        return NextResponse.json({ success: true, profile: data });
      }

      case "place_order": {
        const result = await kite.placeOrder(body.params);
        return NextResponse.json(result);
      }

      case "cancel_order": {
        const result = await kite.cancelOrder(body.orderId);
        return NextResponse.json(result);
      }

      default:
        return NextResponse.json({ error: "Unknown action" }, { status: 400 });
    }
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
