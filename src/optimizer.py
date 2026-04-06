"""Self-evolving strategy optimizer.

Runs parameter optimization using recent market data to find the best
strategy configuration. Can run nightly after market close.

Approach:
1. Define a parameter search space
2. Run backtests with different parameter combinations
3. Score each combination by Sharpe ratio + profit factor
4. If a better config is found, update settings.yaml automatically
5. Log all optimization runs for tracking evolution
"""

from __future__ import annotations

import json
import os
import yaml
import itertools
from copy import deepcopy
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

from src.utils import Config, load_config
from src.backtest import run_backtest, BacktestResult
from src.kite_client import KiteClient


# ── Parameter Search Space ───────────────────────────────────────

PARAM_GRID = {
    "target_pct": [0.8, 1.0, 1.2, 1.5, 1.8],
    "stoploss_pct": [0.4, 0.5, 0.6, 0.7, 0.8],
    "trailing_trigger_pct": [0.5, 0.6, 0.7, 0.8, 1.0],
    "min_score": [2, 3, 4],
    "ema_fast": [5, 9, 13],
    "ema_slow": [15, 21, 26],
    "rsi_period": [10, 14, 20],
    "volume_spike_multiplier": [1.5, 2.0, 2.5],
}

# Reduced grid for faster optimization (still covers key params)
FAST_PARAM_GRID = {
    "target_pct": [0.8, 1.2, 1.8],
    "stoploss_pct": [0.4, 0.6, 0.8],
    "trailing_trigger_pct": [0.5, 0.7, 1.0],
    "min_score": [2, 3, 4],
}


@dataclass
class OptimizationResult:
    """Result of a single parameter combination backtest."""
    params: dict
    sharpe: float
    profit_factor: float
    total_pnl: float
    win_rate: float
    total_trades: int
    max_drawdown: float
    score: float  # Combined optimization score


@dataclass
class OptimizationRun:
    """Full optimization run result."""
    timestamp: str
    results: list[OptimizationResult]
    best: OptimizationResult
    baseline: OptimizationResult
    improved: bool
    config_updated: bool


def _compute_score(result: BacktestResult) -> float:
    """Compute a combined optimization score.

    Prioritizes:
    - Sharpe ratio (risk-adjusted returns)
    - Profit factor (win/loss ratio)
    - Penalizes low trade counts (overfitting risk)
    - Penalizes high drawdown
    """
    summary = result.summary()
    sharpe = summary["sharpe_ratio"]
    pf = min(summary["profit_factor"], 5.0)  # Cap at 5 to avoid outliers
    trades = summary["total_trades"]
    dd_pct = summary["max_drawdown_pct"]
    win_rate = summary["win_rate"]

    # Minimum trade threshold — need at least 20 trades for statistical significance
    if trades < 20:
        return -999

    # Score components (all normalized roughly to 0-10 range)
    sharpe_score = sharpe * 2                    # Sharpe of 2 = score 4
    pf_score = (pf - 1) * 3                      # PF of 2 = score 3
    wr_score = (win_rate - 40) / 10               # 60% WR = score 2
    trade_score = min(trades / 50, 2)             # Enough trades bonus
    dd_penalty = max(0, (dd_pct - 5)) * 0.3       # Penalty for >5% drawdown

    return sharpe_score + pf_score + wr_score + trade_score - dd_penalty


def optimize(
    kite: KiteClient,
    symbols: list[str],
    months: int = 3,
    fast: bool = True,
    progress_callback=None,
) -> OptimizationRun:
    """Run parameter optimization.

    Args:
        kite: Authenticated KiteClient.
        symbols: Stock symbols to backtest.
        months: Backtest period in months.
        fast: Use reduced parameter grid.
        progress_callback: Optional callback(step, total, message).

    Returns:
        OptimizationRun with all results and best parameters.
    """
    grid = FAST_PARAM_GRID if fast else PARAM_GRID
    base_config = load_config("config")

    # Generate all parameter combinations
    param_names = list(grid.keys())
    param_values = list(grid.values())
    combinations = list(itertools.product(*param_values))

    # Run baseline first
    if progress_callback:
        progress_callback(0, len(combinations) + 1, "Running baseline backtest...")

    baseline_result = run_backtest(base_config, kite, symbols, months)
    baseline_score = _compute_score(baseline_result)
    baseline_summary = baseline_result.summary()

    baseline = OptimizationResult(
        params={},
        sharpe=baseline_summary["sharpe_ratio"],
        profit_factor=baseline_summary["profit_factor"],
        total_pnl=baseline_summary["total_pnl"],
        win_rate=baseline_summary["win_rate"],
        total_trades=baseline_summary["total_trades"],
        max_drawdown=baseline_summary["max_drawdown"],
        score=baseline_score,
    )

    results = []
    best = baseline

    for i, combo in enumerate(combinations):
        if progress_callback:
            progress_callback(
                i + 1, len(combinations) + 1,
                f"Testing combo {i+1}/{len(combinations)}: {dict(zip(param_names, combo))}"
            )

        # Create config with this parameter combo
        test_config = deepcopy(base_config)
        param_dict = dict(zip(param_names, combo))
        for key, value in param_dict.items():
            setattr(test_config, key, value)

        # Skip invalid combos (e.g., fast EMA >= slow EMA)
        if test_config.ema_fast >= test_config.ema_slow:
            continue

        try:
            bt_result = run_backtest(test_config, kite, symbols, months)
            score = _compute_score(bt_result)
            summary = bt_result.summary()

            opt_result = OptimizationResult(
                params=param_dict,
                sharpe=summary["sharpe_ratio"],
                profit_factor=summary["profit_factor"],
                total_pnl=summary["total_pnl"],
                win_rate=summary["win_rate"],
                total_trades=summary["total_trades"],
                max_drawdown=summary["max_drawdown"],
                score=score,
            )
            results.append(opt_result)

            if score > best.score:
                best = opt_result

        except Exception:
            continue

    improved = best.score > baseline.score and best.params  # Must have params (not baseline itself)
    config_updated = False

    if improved:
        config_updated = _update_config(best.params)

    return OptimizationRun(
        timestamp=datetime.now().isoformat(),
        results=sorted(results, key=lambda x: x.score, reverse=True),
        best=best,
        baseline=baseline,
        improved=improved,
        config_updated=config_updated,
    )


def _update_config(params: dict) -> bool:
    """Update settings.yaml with new parameters."""
    config_path = os.path.join("config", "settings.yaml")
    try:
        with open(config_path) as f:
            raw = yaml.safe_load(f)

        # Map flat params to nested YAML structure
        param_map = {
            "target_pct": ("exits", "target_pct"),
            "stoploss_pct": ("exits", "stoploss_pct"),
            "trailing_trigger_pct": ("exits", "trailing_trigger_pct"),
            "min_score": ("signals", "min_score"),
            "ema_fast": ("signals", "ema_fast"),
            "ema_slow": ("signals", "ema_slow"),
            "rsi_period": ("signals", "rsi_period"),
            "volume_spike_multiplier": ("signals", "volume_spike_multiplier"),
        }

        for key, value in params.items():
            if key in param_map:
                section, field = param_map[key]
                raw[section][field] = value

        with open(config_path, "w") as f:
            yaml.dump(raw, f, default_flow_style=False, sort_keys=False)

        return True
    except Exception:
        return False


def save_optimization_log(run: OptimizationRun, log_dir: str = "data"):
    """Save optimization results to a log file for tracking evolution."""
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "optimization_history.json")

    # Load existing history
    history = []
    if os.path.exists(log_file):
        try:
            with open(log_file) as f:
                history = json.load(f)
        except Exception:
            pass

    # Add this run
    entry = {
        "timestamp": run.timestamp,
        "baseline_score": run.baseline.score,
        "best_score": run.best.score,
        "best_params": run.best.params,
        "best_pnl": run.best.total_pnl,
        "best_sharpe": run.best.sharpe,
        "best_win_rate": run.best.win_rate,
        "improved": run.improved,
        "config_updated": run.config_updated,
        "total_combos_tested": len(run.results),
    }
    history.append(entry)

    with open(log_file, "w") as f:
        json.dump(history, f, indent=2)


def load_optimization_history(log_dir: str = "data") -> list[dict]:
    """Load optimization history for dashboard display."""
    log_file = os.path.join(log_dir, "optimization_history.json")
    if os.path.exists(log_file):
        with open(log_file) as f:
            return json.load(f)
    return []
