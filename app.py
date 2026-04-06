"""Trading Bot Dashboard — Live Trading Screen.

Single screen showing: signals, open trades, trade details, P&L.
Run with: streamlit run app.py
"""

from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

from src.live_trader import LiveTrader
from src.utils import load_config

st.set_page_config(
    page_title="Trading Bot",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session State Init ───────────────────────────────────────────

if "trader" not in st.session_state:
    st.session_state.trader = LiveTrader()
    st.session_state.authenticated = False
    st.session_state.booted = False
    st.session_state.universe_scanned = False
    st.session_state.trading_active = False


trader: LiveTrader = st.session_state.trader


# ── Sidebar: Auth & Controls ────────────────────────────────────

with st.sidebar:
    st.title("Trading Bot")
    st.caption(f"Date: {datetime.now().strftime('%Y-%m-%d')}")

    # Auth section
    if not st.session_state.authenticated:
        st.subheader("Login to Kite")

        # Try loading saved session
        if st.button("Load Saved Session"):
            if trader.try_load_session():
                st.session_state.authenticated = True
                st.success("Session loaded!")
                st.rerun()
            else:
                st.warning("No valid session. Please login.")

        st.markdown(f"[Login to Kite]({trader.login_url})")
        st.caption("After login, paste the request_token from the redirect URL:")
        request_token = st.text_input("Request Token", type="password")
        if st.button("Authenticate") and request_token:
            try:
                trader.authenticate(request_token)
                st.session_state.authenticated = True
                st.success("Authenticated!")
                st.rerun()
            except Exception as e:
                st.error(f"Auth failed: {e}")
    else:
        st.success("Kite Connected")

        # Boot section
        if not st.session_state.booted:
            if st.button("Boot Engine", type="primary"):
                with st.spinner("Booting..."):
                    boot_data = trader.boot()
                st.session_state.booted = True
                st.rerun()

        # Universe scan
        elif not st.session_state.universe_scanned:
            if st.button("Scan Universe", type="primary"):
                progress = st.progress(0, "Scanning stocks...")
                def update_progress(i, total, sym):
                    progress.progress(i / total, f"Scanning {sym}... ({i}/{total})")
                filtered = trader.scan_universe(progress_callback=update_progress)
                st.session_state.universe_scanned = True
                progress.empty()
                st.rerun()

        # Trading controls
        else:
            st.divider()

            col1, col2 = st.columns(2)
            with col1:
                if st.button("Scan Signals", type="primary"):
                    with st.spinner("Scanning..."):
                        actions = trader.scan_once()
                        if actions:
                            trader.execute_actions(actions)
                    st.rerun()

            with col2:
                if st.button("Sync Orders"):
                    with st.spinner("Syncing..."):
                        trader.sync_orders()
                        trader.check_trailing_sl()
                    st.rerun()

            st.divider()

            if st.button("Capture ORB"):
                with st.spinner("Capturing ORB..."):
                    trader.capture_orb()
                st.rerun()

            if st.button("SQUARE OFF ALL", type="secondary"):
                trader.squareoff()
                st.rerun()

            st.divider()
            if st.button("Refresh"):
                st.rerun()

    # Config display
    with st.expander("Config"):
        config = trader.config
        st.json({
            "capital": f"{config.total_capital:,.0f}",
            "per_trade": f"{config.per_trade_capital:,.0f}",
            "target": f"{config.target_pct}%",
            "stoploss": f"{config.stoploss_pct}%",
            "trailing_trigger": f"{config.trailing_trigger_pct}%",
            "min_score": config.min_score,
            "max_trades": config.max_daily_trades,
            "max_concurrent": config.max_concurrent,
        })


# ── Main Content ─────────────────────────────────────────────────

if not st.session_state.authenticated:
    st.title("Trading Bot Dashboard")
    st.info("Please login to Kite from the sidebar to get started.")
    st.stop()

if not st.session_state.booted:
    st.title("Trading Bot Dashboard")
    st.info("Click 'Boot Engine' in the sidebar to initialize.")
    st.stop()

if not st.session_state.universe_scanned:
    st.title("Trading Bot Dashboard")
    st.info("Click 'Scan Universe' in the sidebar to filter stocks.")
    st.stop()

# ── P&L Summary Row ─────────────────────────────────────────────

pnl = trader.get_pnl_summary()

st.title("Live Trading Dashboard")

col1, col2, col3, col4, col5, col6 = st.columns(6)
with col1:
    st.metric("Total P&L", f"{pnl['total_pnl']:+,.0f}",
              delta=f"{pnl['total_pnl']:+,.0f}")
with col2:
    st.metric("Trades", f"{pnl['daily_trades']}/{pnl['max_daily_trades']}")
with col3:
    st.metric("Open", str(pnl["open_positions"]))
with col4:
    st.metric("Win Rate", f"{pnl['win_rate']:.0f}%" if pnl["closed_trades"] else "N/A")
with col5:
    st.metric("VIX", f"{pnl['vix']:.1f}",
              delta="OK" if pnl["vix"] <= 18 else "HIGH",
              delta_color="normal" if pnl["vix"] <= 18 else "inverse")
with col6:
    status = "ACTIVE" if pnl["can_trade"] else "BLOCKED"
    st.metric("Status", status)

if not pnl["can_trade"]:
    st.warning(f"Trading blocked: {pnl['risk_reason']}")

st.divider()

# ── Two Column Layout: Signals + Positions ───────────────────────

left_col, right_col = st.columns([3, 4])

# ── Signals Table ────────────────────────────────────────────────

with left_col:
    st.subheader("Signals")
    signals = trader.get_signals()
    if signals:
        df_signals = pd.DataFrame(signals)
        # Color code by score
        def highlight_score(val):
            if val >= 4:
                return "background-color: #2ecc71; color: white"
            elif val >= 3:
                return "background-color: #f1c40f; color: black"
            return ""

        display_cols = ["symbol", "score", "direction", "price", "rsi", "volume_ratio"]
        styled = df_signals[display_cols].style.applymap(
            highlight_score, subset=["score"]
        )
        st.dataframe(styled, use_container_width=True, height=400)
    else:
        st.info("No signals yet. Click 'Scan Signals' to scan.")

# ── Positions & Trades ───────────────────────────────────────────

with right_col:
    st.subheader("Positions & Trades")
    positions = trader.get_positions_data()

    if positions:
        df_pos = pd.DataFrame(positions)

        # Active positions
        active = df_pos[df_pos["status"].isin(["active", "pending_entry"])]
        if len(active) > 0:
            st.caption("OPEN POSITIONS")
            for _, pos in active.iterrows():
                with st.container():
                    c1, c2, c3, c4, c5 = st.columns(5)
                    c1.markdown(f"**{pos['symbol']}**")
                    c2.write(f"Entry: {pos['entry_price']:.2f}")
                    c3.write(f"Current: {pos['current_price']:.2f}")
                    pnl_color = "green" if pos["pnl"] >= 0 else "red"
                    c4.markdown(f"P&L: :{pnl_color}[{pos['pnl']:+.0f} ({pos['pnl_pct']:+.1f}%)]")
                    trail = " (trailing)" if pos["trailing_active"] else ""
                    c5.write(f"SL: {pos['stoploss']:.2f}{trail}")

        # Closed trades
        closed = df_pos[df_pos["status"] == "closed"]
        if len(closed) > 0:
            st.caption("CLOSED TRADES")
            display_cols = ["symbol", "entry_price", "current_price", "pnl", "pnl_pct", "entry_time"]
            closed_display = closed[display_cols].copy()
            closed_display.columns = ["Symbol", "Entry", "Exit", "P&L", "P&L %", "Time"]

            def color_pnl(val):
                if isinstance(val, (int, float)):
                    return "color: green" if val >= 0 else "color: red"
                return ""

            st.dataframe(
                closed_display.style.applymap(color_pnl, subset=["P&L", "P&L %"]),
                use_container_width=True,
            )
    else:
        st.info("No trades yet.")

# ── Activity Log ─────────────────────────────────────────────────

st.divider()
with st.expander("Activity Log", expanded=False):
    if trader.log:
        for entry in reversed(trader.log[-50:]):
            st.text(entry)
    else:
        st.text("No activity yet.")
