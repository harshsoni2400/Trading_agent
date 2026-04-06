"""Shared utilities, constants, and config loader."""

from __future__ import annotations

import yaml
import json
import os
from datetime import time, datetime
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Config:
    """Trading bot configuration loaded from settings.yaml."""
    # Capital
    total_capital: float = 100000
    per_trade_capital: float = 45000
    max_concurrent: int = 2
    max_daily_trades: int = 4

    # Signals
    rsi_period: int = 14
    ema_fast: int = 9
    ema_slow: int = 21
    orb_minutes: int = 15
    volume_spike_multiplier: float = 2.0
    vwap_volume_multiplier: float = 1.5
    min_score: int = 3

    # Exits
    target_pct: float = 1.2
    stoploss_pct: float = 0.6
    trailing_trigger_pct: float = 0.7
    squareoff_time: time = field(default_factory=lambda: time(15, 15))

    # Safety
    no_trade_before: time = field(default_factory=lambda: time(9, 20))
    no_trade_after: time = field(default_factory=lambda: time(14, 30))
    max_vix: float = 18.0
    max_gap_pct: float = 1.0
    max_daily_loss: float = 2000

    # Universe
    min_volume_cr: float = 50
    atr_pct_min: float = 1.5
    atr_pct_max: float = 3.0
    lookback_days: int = 20


def load_config(config_dir: str) -> Config:
    """Load config from settings.yaml."""
    settings_path = os.path.join(config_dir, "settings.yaml")
    with open(settings_path) as f:
        raw = yaml.safe_load(f)

    def parse_time(s: str) -> time:
        parts = s.split(":")
        return time(int(parts[0]), int(parts[1]))

    return Config(
        total_capital=raw["capital"]["total"],
        per_trade_capital=raw["capital"]["per_trade"],
        max_concurrent=raw["capital"]["max_concurrent"],
        max_daily_trades=raw["capital"]["max_daily_trades"],
        rsi_period=raw["signals"]["rsi_period"],
        ema_fast=raw["signals"]["ema_fast"],
        ema_slow=raw["signals"]["ema_slow"],
        orb_minutes=raw["signals"]["orb_minutes"],
        volume_spike_multiplier=raw["signals"]["volume_spike_multiplier"],
        vwap_volume_multiplier=raw["signals"]["vwap_volume_multiplier"],
        min_score=raw["signals"]["min_score"],
        target_pct=raw["exits"]["target_pct"],
        stoploss_pct=raw["exits"]["stoploss_pct"],
        trailing_trigger_pct=raw["exits"]["trailing_trigger_pct"],
        squareoff_time=parse_time(raw["exits"]["squareoff_time"]),
        no_trade_before=parse_time(raw["safety"]["no_trade_before"]),
        no_trade_after=parse_time(raw["safety"]["no_trade_after"]),
        max_vix=raw["safety"]["max_vix"],
        max_gap_pct=raw["safety"]["max_gap_pct"],
        max_daily_loss=raw["safety"]["max_daily_loss"],
        min_volume_cr=raw["universe"]["min_volume_cr"],
        atr_pct_min=raw["universe"]["atr_pct_min"],
        atr_pct_max=raw["universe"]["atr_pct_max"],
        lookback_days=raw["universe"]["lookback_days"],
    )


def load_nifty200(config_dir: str) -> list[str]:
    """Load Nifty 200 symbol list from JSON."""
    path = os.path.join(config_dir, "nifty200.json")
    with open(path) as f:
        data = json.load(f)
    return data["stocks"]


# Exchange constants
EXCHANGE = "NSE"
PRODUCT_MIS = "MIS"
ORDER_TYPE_LIMIT = "LIMIT"
ORDER_TYPE_SLM = "SL-M"
ORDER_TYPE_MARKET = "MARKET"
TRANSACTION_BUY = "BUY"
TRANSACTION_SELL = "SELL"

# Market hours (IST)
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
