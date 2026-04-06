"""Strategy Optimizer Screen — Auto-tune parameters for maximum profits."""

from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

from src.kite_client import KiteClient
from src.utils import load_config, load_nifty200
from src.optimizer import (
    optimize, save_optimization_log, load_optimization_history,
    FAST_PARAM_GRID, PARAM_GRID,
)

st.set_page_config(page_title="Strategy Optimizer", page_icon="🧬", layout="wide")

st.title("Strategy Optimizer")
st.caption("Auto-evolve your strategy parameters based on recent market data")

# ── Sidebar ──────────────────────────────────────────────────────

with st.sidebar:
    st.subheader("Kite Authentication")
    kite = KiteClient()
    authenticated = kite.load_session()

    if authenticated:
        st.success("Session loaded")
    else:
        st.markdown(f"[Login to Kite]({kite.login_url})")
        token = st.text_input("Request Token", type="password", key="opt_token")
        if st.button("Authenticate", key="opt_auth") and token:
            try:
                kite.authenticate(token)
                authenticated = True
                st.success("Authenticated!")
            except Exception as e:
                st.error(str(e))

    st.divider()
    st.subheader("Optimizer Settings")
    months = st.slider("Backtest Period (months)", 1, 6, 3, key="opt_months")
    max_stocks = st.slider("Max Stocks", 10, 100, 30, key="opt_stocks")
    fast_mode = st.checkbox("Fast Mode (reduced grid)", value=True)

    grid = FAST_PARAM_GRID if fast_mode else PARAM_GRID
    import itertools
    total_combos = 1
    for v in grid.values():
        total_combos *= len(v)
    st.caption(f"Parameter combinations: {total_combos}")

    run_btn = st.button("Run Optimizer", type="primary", disabled=not authenticated)


# ── Run Optimization ─────────────────────────────────────────────

if run_btn and authenticated:
    symbols = load_nifty200("config")[:max_stocks]

    progress = st.progress(0, "Starting optimization...")
    status = st.empty()

    def progress_cb(step, total, message):
        progress.progress(step / total if total else 0, message)
        status.text(message)

    result = optimize(kite, symbols, months, fast=fast_mode, progress_callback=progress_cb)
    save_optimization_log(result)

    progress.empty()
    status.empty()

    st.session_state.opt_result = result

# ── Display Current Optimization ─────────────────────────────────

if "opt_result" in st.session_state and st.session_state.opt_result:
    result = st.session_state.opt_result

    # Result banner
    if result.improved:
        st.success(
            f"Better parameters found! Score: {result.best.score:.1f} "
            f"(was {result.baseline.score:.1f}). "
            f"{'Config updated automatically.' if result.config_updated else 'Config NOT updated.'}"
        )
    else:
        st.info(f"Current parameters are optimal. Score: {result.baseline.score:.1f}")

    # Compare baseline vs best
    st.subheader("Baseline vs Best")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Current (Baseline)**")
        st.metric("Score", f"{result.baseline.score:.1f}")
        st.metric("P&L", f"{result.baseline.total_pnl:+,.0f}")
        st.metric("Sharpe", f"{result.baseline.sharpe:.2f}")
        st.metric("Win Rate", f"{result.baseline.win_rate:.0f}%")
        st.metric("Profit Factor", f"{result.baseline.profit_factor:.2f}")

    with col2:
        st.markdown("**Optimized Best**")
        st.metric("Score", f"{result.best.score:.1f}",
                  delta=f"{result.best.score - result.baseline.score:+.1f}")
        st.metric("P&L", f"{result.best.total_pnl:+,.0f}",
                  delta=f"{result.best.total_pnl - result.baseline.total_pnl:+,.0f}")
        st.metric("Sharpe", f"{result.best.sharpe:.2f}",
                  delta=f"{result.best.sharpe - result.baseline.sharpe:+.2f}")
        st.metric("Win Rate", f"{result.best.win_rate:.0f}%",
                  delta=f"{result.best.win_rate - result.baseline.win_rate:+.0f}%")
        st.metric("Profit Factor", f"{result.best.profit_factor:.2f}",
                  delta=f"{result.best.profit_factor - result.baseline.profit_factor:+.2f}")

    if result.best.params:
        st.subheader("Best Parameters")
        st.json(result.best.params)

    # Top 10 combinations
    st.subheader("Top 10 Parameter Combinations")
    if result.results:
        top_data = []
        for r in result.results[:10]:
            row = {
                "Score": round(r.score, 1),
                "P&L": round(r.total_pnl, 0),
                "Sharpe": round(r.sharpe, 2),
                "Win Rate": f"{r.win_rate:.0f}%",
                "PF": round(r.profit_factor, 2),
                "Trades": r.total_trades,
                "Drawdown": round(r.max_drawdown, 0),
            }
            row.update({k: v for k, v in r.params.items()})
            top_data.append(row)
        st.dataframe(pd.DataFrame(top_data), use_container_width=True)

st.divider()

# ── Optimization History ─────────────────────────────────────────

st.subheader("Optimization History")
history = load_optimization_history()

if history:
    hist_df = pd.DataFrame(history)
    hist_df["timestamp"] = pd.to_datetime(hist_df["timestamp"])

    # Score evolution chart
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=hist_df["timestamp"], y=hist_df["baseline_score"],
        mode="lines+markers", name="Baseline Score",
        line=dict(color="#95a5a6"),
    ))
    fig.add_trace(go.Scatter(
        x=hist_df["timestamp"], y=hist_df["best_score"],
        mode="lines+markers", name="Best Score",
        line=dict(color="#2ecc71"),
    ))
    fig.update_layout(
        height=300, margin=dict(l=0, r=0, t=10, b=0),
        yaxis_title="Optimization Score",
    )
    st.plotly_chart(fig, use_container_width=True)

    # History table
    display_cols = ["timestamp", "baseline_score", "best_score", "best_pnl",
                    "best_sharpe", "best_win_rate", "improved", "total_combos_tested"]
    st.dataframe(hist_df[display_cols], use_container_width=True)
else:
    st.info("No optimization history yet. Run the optimizer to start tracking evolution.")
