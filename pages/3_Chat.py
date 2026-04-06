"""Claude Chat — Ask questions about your trades, get analysis, give orders.

Uses the Anthropic API to power a trading-aware chatbot that has full
context of your positions, signals, P&L, and can execute trades.
"""

from __future__ import annotations

import os
import json
import streamlit as st
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="Trading Chat", page_icon="💬", layout="wide")

# ── Check for Anthropic API key ──────────────────────────────────

api_key = os.getenv("ANTHROPIC_API_KEY", "")

if not api_key:
    st.title("Trading Chat")
    st.warning("Set ANTHROPIC_API_KEY in your .env file to use the chatbot.")
    st.stop()

import anthropic
from src.kite_client import KiteClient
from src.live_trader import LiveTrader

# ── Session State ────────────────────────────────────────────────

if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []
if "chat_trader" not in st.session_state:
    st.session_state.chat_trader = None
if "chat_kite" not in st.session_state:
    kite = KiteClient()
    if kite.load_session():
        st.session_state.chat_kite = kite
    else:
        st.session_state.chat_kite = None

kite: KiteClient = st.session_state.chat_kite
client = anthropic.Anthropic(api_key=api_key)


def _get_trading_context() -> str:
    """Build context string with current trading state for Claude."""
    context_parts = []

    if kite and kite.is_authenticated():
        # Profile
        try:
            profile = kite.get_profile()
            context_parts.append(f"User: {profile.get('user_name', 'N/A')} ({profile.get('user_id', '')})")
        except Exception:
            pass

        # Margins
        try:
            margins = kite.get_margins()
            eq = margins.get("equity", {}).get("available", {})
            context_parts.append(f"Available Margin: {eq.get('live_balance', 0):,.0f}")
        except Exception:
            pass

        # Positions
        try:
            positions = kite.get_positions()
            day_pos = positions.get("day", [])
            net_pos = [p for p in day_pos if p.get("quantity", 0) != 0]
            if net_pos:
                context_parts.append(f"\nOpen Positions ({len(net_pos)}):")
                for p in net_pos:
                    pnl = p.get("pnl", 0)
                    context_parts.append(
                        f"  {p['tradingsymbol']}: qty={p['quantity']} "
                        f"avg={p.get('average_price', 0):.2f} "
                        f"last={p.get('last_price', 0):.2f} "
                        f"P&L={pnl:+.2f}"
                    )
            else:
                context_parts.append("\nNo open positions.")
        except Exception:
            context_parts.append("\nCould not fetch positions.")

        # Today's orders
        try:
            orders = kite.get_orders()
            if orders:
                completed = [o for o in orders if o.get("status") == "COMPLETE"]
                pending = [o for o in orders if o.get("status") in ("OPEN", "TRIGGER PENDING")]
                context_parts.append(f"\nToday's Orders: {len(completed)} completed, {len(pending)} pending")
                for o in (completed + pending)[-10:]:
                    context_parts.append(
                        f"  {o.get('transaction_type', '')} {o.get('tradingsymbol', '')} "
                        f"qty={o.get('quantity', 0)} price={o.get('average_price', 0):.2f} "
                        f"status={o.get('status', '')}"
                    )
        except Exception:
            pass

        # Holdings
        try:
            holdings = kite.get_holdings()
            if holdings:
                total_value = sum(h.get("last_price", 0) * h.get("quantity", 0) for h in holdings)
                total_pnl = sum(h.get("pnl", 0) for h in holdings)
                context_parts.append(f"\nHoldings: {len(holdings)} stocks, value={total_value:,.0f}, P&L={total_pnl:+,.0f}")
        except Exception:
            pass

    # Engine state (if trader is active)
    if "trader" in st.session_state:
        trader = st.session_state.trader
        if hasattr(trader, "engine") and trader.engine.watchlist:
            context_parts.append(f"\nBot Watchlist: {len(trader.engine.watchlist)} stocks")
            signals = trader.get_signals()
            top = [s for s in signals if s["score"] >= 3]
            if top:
                context_parts.append("Top Signals:")
                for s in top[:5]:
                    context_parts.append(f"  {s['symbol']} score={s['score']} {s['direction']} RSI={s['rsi']}")

    return "\n".join(context_parts) if context_parts else "No trading data available. Kite may not be authenticated."


SYSTEM_PROMPT = """You are a trading assistant integrated into a Zerodha intraday trading bot dashboard.
You have access to the user's real-time trading data including positions, orders, P&L, and signals.

Your capabilities:
1. Answer questions about the user's current positions, trades, and P&L
2. Explain trading signals and why they were generated
3. Provide market analysis and opinions
4. Help the user understand risk management decisions
5. Execute trades when the user explicitly asks (buy/sell specific stocks)

When the user asks to place a trade, extract:
- Symbol (e.g., RELIANCE, TCS)
- Action (BUY/SELL)
- Quantity
- Order type (MARKET/LIMIT)
- Price (for LIMIT orders)

Format trade commands as JSON: {"action": "TRADE", "symbol": "...", "side": "BUY/SELL", "qty": N, "type": "MARKET/LIMIT", "price": 0}

IMPORTANT:
- Always warn about risks before executing trades
- Confirm with the user before placing any order
- For intraday, always use product type MIS
- Be concise and direct in your responses
- Use Indian market context (NSE, IST timezone, INR)

Current date/time: {datetime}

Current Trading State:
{context}"""


def _parse_trade_command(text: str) -> dict:
    """Try to extract a trade command JSON from Claude's response."""
    try:
        start = text.find('{"action": "TRADE"')
        if start == -1:
            return {}
        end = text.find("}", start) + 1
        return json.loads(text[start:end])
    except Exception:
        return {}


def _execute_trade(cmd: dict) -> str:
    """Execute a trade command via Kite."""
    if not kite or not kite.is_authenticated():
        return "Error: Kite not authenticated"

    try:
        order_id = kite.place_order(
            symbol=cmd["symbol"],
            transaction_type=cmd["side"],
            quantity=cmd["qty"],
            order_type=cmd.get("type", "MARKET"),
            price=cmd.get("price", 0),
            product="MIS",
        )
        return f"Order placed! ID: {order_id} | {cmd['side']} {cmd['qty']} {cmd['symbol']}"
    except Exception as e:
        return f"Order failed: {e}"


# ── UI ───────────────────────────────────────────────────────────

st.title("Trading Chat")

# Sidebar status
with st.sidebar:
    if kite and kite.is_authenticated():
        st.success("Kite Connected")
    else:
        st.warning("Kite not connected")
        st.markdown("Login from the Live Trading page first.")

    st.divider()
    st.caption("Ask about your trades, P&L, signals, or give trade orders.")
    st.caption("Examples:")
    st.code("What are my open positions?")
    st.code("Why did the bot buy RELIANCE?")
    st.code("Buy 10 shares of TCS at market")
    st.code("What's my P&L today?")
    st.code("Analyze INFY for intraday")

    if st.button("Clear Chat"):
        st.session_state.chat_messages = []
        st.rerun()

# Chat display
for msg in st.session_state.chat_messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("trade_result"):
            st.success(msg["trade_result"])

# Chat input
if prompt := st.chat_input("Ask about trades, signals, or give orders..."):
    # Add user message
    st.session_state.chat_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Get trading context
    context = _get_trading_context()

    # Build messages for Claude
    system = SYSTEM_PROMPT.format(
        datetime=datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
        context=context,
    )

    messages = [
        {"role": m["role"], "content": m["content"]}
        for m in st.session_state.chat_messages
    ]

    # Call Claude
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                system=system,
                messages=messages,
            )
            reply = response.content[0].text

        st.markdown(reply)

        # Check for trade command
        trade_cmd = _parse_trade_command(reply)
        trade_result = ""
        if trade_cmd and trade_cmd.get("action") == "TRADE":
            # Show confirmation
            st.warning(
                f"Trade detected: {trade_cmd['side']} {trade_cmd['qty']} "
                f"{trade_cmd['symbol']} ({trade_cmd.get('type', 'MARKET')})"
            )
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Confirm Trade", key=f"confirm_{len(st.session_state.chat_messages)}"):
                    trade_result = _execute_trade(trade_cmd)
                    st.success(trade_result)
            with col2:
                if st.button("Cancel", key=f"cancel_{len(st.session_state.chat_messages)}"):
                    trade_result = "Trade cancelled by user."
                    st.info(trade_result)

    st.session_state.chat_messages.append({
        "role": "assistant",
        "content": reply,
        "trade_result": trade_result,
    })
