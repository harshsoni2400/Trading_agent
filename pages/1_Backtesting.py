"""Backtesting Screen — Run 6-month strategy backtest with full analytics."""

from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime

from src.kite_client import KiteClient
from src.utils import load_config, load_nifty200
from src.backtest import run_backtest, BacktestResult

st.set_page_config(page_title="Backtesting", page_icon="📊", layout="wide")

# ── Session State ────────────────────────────────────────────────

if "bt_result" not in st.session_state:
    st.session_state.bt_result = None
if "bt_running" not in st.session_state:
    st.session_state.bt_running = False

st.title("Strategy Backtester")

# ── Sidebar: Auth + Parameters ───────────────────────────────────

with st.sidebar:
    st.subheader("Kite Authentication")

    kite = KiteClient()
    authenticated = False

    if kite.load_session():
        st.success("Session loaded")
        authenticated = True
    else:
        st.markdown(f"[Login to Kite]({kite.login_url})")
        token = st.text_input("Request Token", type="password", key="bt_token")
        if st.button("Authenticate", key="bt_auth") and token:
            try:
                kite.authenticate(token)
                authenticated = True
                st.success("Authenticated!")
            except Exception as e:
                st.error(str(e))

    st.divider()
    st.subheader("Backtest Parameters")

    months = st.slider("Months", 1, 12, 6)
    max_stocks = st.slider("Max stocks to scan", 10, 190, 50)

    with st.expander("Strategy Overrides"):
        target_pct = st.number_input("Target %", 0.5, 3.0, 1.2, 0.1)
        stoploss_pct = st.number_input("Stop Loss %", 0.3, 2.0, 0.6, 0.1)
        trailing_pct = st.number_input("Trailing Trigger %", 0.3, 2.0, 0.7, 0.1)
        min_score = st.selectbox("Min Signal Score", [2, 3, 4, 5], index=1)
        max_trades = st.slider("Max Daily Trades", 1, 8, 4)

    run_btn = st.button("Run Backtest", type="primary", disabled=not authenticated)


# ── Run Backtest ─────────────────────────────────────────────────

if run_btn and authenticated:
    config = load_config("config")
    # Apply overrides
    config.target_pct = target_pct
    config.stoploss_pct = stoploss_pct
    config.trailing_trigger_pct = trailing_pct
    config.min_score = min_score
    config.max_daily_trades = max_trades

    symbols = load_nifty200("config")[:max_stocks]

    progress_bar = st.progress(0, "Starting backtest...")
    status_text = st.empty()

    def progress_cb(step, total, message):
        progress_bar.progress(step / total if total > 0 else 0, message)
        status_text.text(message)

    result = run_backtest(config, kite, symbols, months, progress_callback=progress_cb)
    st.session_state.bt_result = result
    progress_bar.empty()
    status_text.empty()


# ── Display Results ──────────────────────────────────────────────

result: BacktestResult = st.session_state.bt_result

if result is None:
    st.info("Configure parameters in the sidebar and click 'Run Backtest' to start.")
    st.stop()

summary = result.summary()

# ── Metrics Row ──────────────────────────────────────────────────

st.subheader("Performance Summary")

col1, col2, col3, col4, col5, col6 = st.columns(6)
with col1:
    color = "normal" if summary["total_pnl"] >= 0 else "inverse"
    st.metric("Total P&L", f"{summary['total_pnl']:+,.0f}", delta_color=color)
with col2:
    st.metric("Total Trades", summary["total_trades"])
with col3:
    st.metric("Win Rate", f"{summary['win_rate']}%")
with col4:
    st.metric("Profit Factor", f"{summary['profit_factor']:.2f}")
with col5:
    st.metric("Max Drawdown", f"{summary['max_drawdown']:,.0f}")
with col6:
    st.metric("Sharpe Ratio", f"{summary['sharpe_ratio']:.2f}")

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Avg Win", f"{summary['avg_win']:+,.0f}")
with col2:
    st.metric("Avg Loss", f"{summary['avg_loss']:+,.0f}")
with col3:
    st.metric("Trading Days", summary["trading_days"])
with col4:
    st.metric("Trades/Day", summary["avg_trades_per_day"])

st.divider()

# ── Charts ───────────────────────────────────────────────────────

chart_col1, chart_col2 = st.columns(2)

# Equity Curve
with chart_col1:
    st.subheader("Equity Curve")
    if result.equity_curve and result.dates:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=result.dates,
            y=result.equity_curve,
            mode="lines",
            fill="tozeroy",
            line=dict(color="#2ecc71" if result.total_pnl >= 0 else "#e74c3c"),
            name="Equity",
        ))
        fig.update_layout(
            height=350, margin=dict(l=0, r=0, t=10, b=0),
            yaxis_title="Portfolio Value",
            xaxis_title="Date",
        )
        st.plotly_chart(fig, use_container_width=True)

# Daily P&L
with chart_col2:
    st.subheader("Daily P&L")
    if result.days:
        daily_df = pd.DataFrame([{"date": d.date, "pnl": d.pnl} for d in result.days if d.pnl != 0])
        if len(daily_df) > 0:
            colors = ["#2ecc71" if p >= 0 else "#e74c3c" for p in daily_df["pnl"]]
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=daily_df["date"], y=daily_df["pnl"],
                marker_color=colors, name="Daily P&L",
            ))
            fig.update_layout(
                height=350, margin=dict(l=0, r=0, t=10, b=0),
                yaxis_title="P&L",
            )
            st.plotly_chart(fig, use_container_width=True)

# ── Trade Analysis ───────────────────────────────────────────────

st.divider()

chart_col3, chart_col4 = st.columns(2)

# Exit reasons pie chart
with chart_col3:
    st.subheader("Exit Reasons")
    if result.trades:
        exit_counts = pd.DataFrame(result.trades).groupby("exit_reason").size().reset_index(name="count")
        fig = px.pie(exit_counts, values="count", names="exit_reason",
                     color_discrete_sequence=["#2ecc71", "#e74c3c", "#f1c40f", "#3498db"])
        fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

# P&L distribution
with chart_col4:
    st.subheader("P&L Distribution")
    if result.trades:
        pnls = [t.pnl for t in result.trades]
        fig = go.Figure()
        fig.add_trace(go.Histogram(
            x=pnls, nbinsx=30,
            marker_color="#3498db", name="P&L",
        ))
        fig.update_layout(
            height=300, margin=dict(l=0, r=0, t=10, b=0),
            xaxis_title="P&L per Trade",
        )
        st.plotly_chart(fig, use_container_width=True)

# ── Trade Log ────────────────────────────────────────────────────

st.divider()
st.subheader("All Trades")

if result.trades:
    trades_data = []
    for t in result.trades:
        trades_data.append({
            "Date": t.date,
            "Symbol": t.symbol,
            "Entry": f"{t.entry_time}",
            "Exit": f"{t.exit_time}",
            "Entry Price": t.entry_price,
            "Exit Price": t.exit_price,
            "Qty": t.quantity,
            "P&L": t.pnl,
            "P&L %": t.pnl_pct,
            "Exit Reason": t.exit_reason,
            "Score": t.score,
        })

    df_trades = pd.DataFrame(trades_data)

    def color_pnl(val):
        if isinstance(val, (int, float)):
            return "color: green" if val >= 0 else "color: red"
        return ""

    st.dataframe(
        df_trades.style.applymap(color_pnl, subset=["P&L", "P&L %"]),
        use_container_width=True,
        height=400,
    )

    # Download button
    csv = df_trades.to_csv(index=False)
    st.download_button("Download Trades CSV", csv, "backtest_trades.csv", "text/csv")

# ── Top Performing Stocks ────────────────────────────────────────

st.divider()
st.subheader("Performance by Stock")

if result.trades:
    stock_perf = {}
    for t in result.trades:
        if t.symbol not in stock_perf:
            stock_perf[t.symbol] = {"trades": 0, "pnl": 0, "wins": 0}
        stock_perf[t.symbol]["trades"] += 1
        stock_perf[t.symbol]["pnl"] += t.pnl
        if t.pnl > 0:
            stock_perf[t.symbol]["wins"] += 1

    stock_df = pd.DataFrame([
        {
            "Symbol": sym,
            "Trades": d["trades"],
            "P&L": round(d["pnl"], 0),
            "Win Rate": f"{d['wins']/d['trades']*100:.0f}%",
        }
        for sym, d in sorted(stock_perf.items(), key=lambda x: x[1]["pnl"], reverse=True)
    ])
    st.dataframe(stock_df, use_container_width=True)
