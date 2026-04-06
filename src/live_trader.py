"""Live trading orchestrator — connects the engine to Kite API.

Runs the full trading day lifecycle: scan universe, capture ORB,
detect signals, execute orders, manage positions, square off.
"""

from __future__ import annotations

import time as _time
import logging
from datetime import datetime, timedelta
from typing import Optional

from src.utils import load_config, load_nifty200, Config
from src.kite_client import KiteClient
from src.indicators import CandleData
from src.engine import TradingEngine, Action
from src.position import PositionStatus

logger = logging.getLogger("trader")


class LiveTrader:
    """Orchestrates live trading using TradingEngine + KiteClient."""

    def __init__(self, config_dir: str = "config"):
        self.config = load_config(config_dir)
        self.symbols = load_nifty200(config_dir)
        self.kite = KiteClient()
        self.engine = TradingEngine(self.config)
        self.log: list[str] = []
        self._running = False

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] {msg}"
        self.log.append(entry)
        logger.info(msg)

    # ── Auth ─────────────────────────────────────────────────────

    def try_load_session(self) -> bool:
        return self.kite.load_session()

    def authenticate(self, request_token: str) -> str:
        return self.kite.authenticate(request_token)

    @property
    def login_url(self) -> str:
        return self.kite.login_url

    # ── Phase 1: Boot ────────────────────────────────────────────

    def boot(self) -> dict:
        """Initialize: load instruments, check margins, fetch market state."""
        self._log("Booting trading engine...")

        # Load instrument tokens
        self.kite.load_instruments("NSE")
        self._log(f"Loaded {len(self.kite._instrument_cache)} NSE instruments")

        # Check margins
        try:
            margins = self.kite.get_margins()
            equity = margins.get("equity", {})
            available = equity.get("available", {}).get("live_balance", 0)
            self._log(f"Available margin: {available:,.0f}")
        except Exception as e:
            available = 0
            self._log(f"Could not fetch margins: {e}")

        # Fetch VIX and Nifty
        vix = self.kite.get_india_vix()
        nifty = self.kite.get_nifty_data()
        self.engine.risk.update_market_state(
            vix=vix,
            nifty_prev_close=nifty["close"],
            nifty_open=nifty["open"],
        )
        self._log(f"VIX: {vix:.1f} | Nifty open: {nifty['open']} close: {nifty['close']}")

        return {
            "available_margin": available,
            "vix": vix,
            "nifty_gap_pct": self.engine.risk.market_state.nifty_gap_pct,
            "can_trade": self.engine.risk.can_trade()[0],
            "reason": self.engine.risk.can_trade()[1],
        }

    # ── Phase 2: Pre-Market Scan ─────────────────────────────────

    def scan_universe(self, progress_callback=None) -> list[str]:
        """Fetch 20-day daily data and filter universe."""
        self._log(f"Scanning universe: {len(self.symbols)} candidates...")
        to_date = datetime.now()
        from_date = to_date - timedelta(days=40)  # Extra days for weekends/holidays

        stock_data = {}
        total = len(self.symbols)
        for i, symbol in enumerate(self.symbols):
            try:
                candles = self.kite.get_historical_data(symbol, "day", from_date, to_date)
                if candles:
                    stock_data[symbol] = {"candles": CandleData.from_kite_candles(candles)}
            except Exception:
                pass
            if progress_callback:
                progress_callback(i + 1, total, symbol)
            _time.sleep(0.35)  # Rate limit

        filtered = self.engine.filter_universe(stock_data)
        self._log(f"Universe filtered: {len(filtered)} stocks passed")
        return filtered

    # ── Phase 3: ORB Capture ─────────────────────────────────────

    def capture_orb(self) -> dict[str, dict]:
        """Fetch 5-min candles for watchlist and capture ORB levels."""
        self._log("Capturing ORB levels...")
        today = datetime.now().replace(hour=9, minute=15, second=0, microsecond=0)
        orb_end = today.replace(hour=9, minute=30)
        now = datetime.now()

        orb_data = {}
        for symbol in list(self.engine.watchlist.keys()):
            try:
                candles = self.kite.get_historical_data(symbol, "5minute", today, now)
                if candles:
                    cd = CandleData.from_kite_candles(candles)
                    self.engine.capture_orb(symbol, cd)
                    state = self.engine.watchlist.get(symbol)
                    if state and state.orb_levels:
                        orb_data[symbol] = {
                            "high": state.orb_levels.high,
                            "low": state.orb_levels.low,
                            "range_pct": state.orb_levels.range_pct,
                        }
            except Exception:
                pass
            _time.sleep(0.35)

        self._log(f"ORB captured for {len(orb_data)} stocks")
        return orb_data

    # ── Phase 4: Signal Scan ─────────────────────────────────────

    def scan_once(self) -> list[Action]:
        """Run one scan cycle: fetch latest candles, score, generate actions."""
        today = datetime.now().replace(hour=9, minute=15, second=0, microsecond=0)
        now = datetime.now()

        market_data = {}
        for symbol in list(self.engine.watchlist.keys()):
            try:
                candles = self.kite.get_historical_data(symbol, "5minute", today, now)
                if candles:
                    market_data[symbol] = CandleData.from_kite_candles(candles)
            except Exception:
                pass
            _time.sleep(0.35)

        actions = self.engine.scan_for_signals(market_data)

        for action in actions:
            self._log(action.message)

        return actions

    def execute_actions(self, actions: list[Action]):
        """Execute a list of actions via Kite API."""
        for action in actions:
            try:
                if action.type == "place_entry":
                    p = action.params
                    order_id = self.kite.place_order(
                        symbol=p["tradingsymbol"],
                        transaction_type=p["transaction_type"],
                        quantity=p["quantity"],
                        order_type=p["order_type"],
                        price=p.get("price", 0),
                        product=p["product"],
                    )
                    # Find position and set order ID
                    pos = self.engine.tracker.find_by_symbol(action.symbol)
                    if pos:
                        pos.entry_order_id = order_id
                    self._log(f"Entry order placed: {action.symbol} order_id={order_id}")

                elif action.type == "place_sl":
                    p = action.params
                    order_id = self.kite.place_order(
                        symbol=p["tradingsymbol"],
                        transaction_type=p["transaction_type"],
                        quantity=p["quantity"],
                        order_type=p["order_type"],
                        trigger_price=p.get("trigger_price", 0),
                        product=p["product"],
                    )
                    pos = self.engine.tracker.find_by_symbol(action.symbol)
                    if pos:
                        pos.sl_order_id = order_id
                    self._log(f"SL order placed: {action.symbol} order_id={order_id}")

                elif action.type == "place_target":
                    p = action.params
                    order_id = self.kite.place_order(
                        symbol=p["tradingsymbol"],
                        transaction_type=p["transaction_type"],
                        quantity=p["quantity"],
                        order_type=p["order_type"],
                        price=p.get("price", 0),
                        product=p["product"],
                    )
                    pos = self.engine.tracker.find_by_symbol(action.symbol)
                    if pos:
                        pos.target_order_id = order_id
                    self._log(f"Target order placed: {action.symbol} order_id={order_id}")

                elif action.type == "modify_sl":
                    p = action.params
                    self.kite.modify_order(p["order_id"], trigger_price=p["trigger_price"])
                    self._log(f"SL modified: {action.symbol}")

                elif action.type == "cancel_order":
                    self.kite.cancel_order(action.params["order_id"])
                    self._log(f"Order cancelled: {action.symbol}")

                elif action.type == "squareoff":
                    p = action.params
                    self.kite.place_order(
                        symbol=p["tradingsymbol"],
                        transaction_type=p["transaction_type"],
                        quantity=p["quantity"],
                        order_type="MARKET",
                        product=p["product"],
                    )
                    self._log(f"Squareoff executed: {action.symbol}")

                elif action.type == "log":
                    self._log(action.message)

            except Exception as e:
                self._log(f"ERROR executing {action.type} for {action.symbol}: {e}")

    # ── Position Sync ────────────────────────────────────────────

    def sync_orders(self):
        """Check order statuses and handle fills/SL/target hits."""
        try:
            orders = self.kite.get_orders()
        except Exception:
            return

        for order in orders:
            order_id = str(order.get("order_id", ""))
            status = order.get("status", "")
            price = order.get("average_price", 0)

            if status in ("COMPLETE", "REJECTED", "CANCELLED"):
                actions = self.engine.handle_order_update(order_id, status, price)
                if actions:
                    self.execute_actions(actions)

    def check_trailing_sl(self):
        """Check active positions for trailing SL activation."""
        symbols = [p.symbol for p in self.engine.tracker.active_positions
                   if p.status == PositionStatus.ACTIVE]
        if not symbols:
            return

        prices = self.kite.get_ltp(symbols)
        actions = self.engine.check_positions(prices)
        if actions:
            self.execute_actions(actions)

    # ── Square-off ───────────────────────────────────────────────

    def squareoff(self):
        """Square off all open positions."""
        actions = self.engine.squareoff_all()
        if actions:
            self.execute_actions(actions)
            self._log("All positions squared off")

    # ── Getters for Dashboard ────────────────────────────────────

    def get_signals(self) -> list[dict]:
        """Get current signal data for all watchlist stocks."""
        signals = []
        for symbol, state in self.engine.watchlist.items():
            sig = state.last_signal
            if sig:
                signals.append({
                    "symbol": symbol,
                    "score": sig.score,
                    "direction": "LONG" if sig.direction == 1 else ("SHORT" if sig.direction == -1 else "-"),
                    "price": sig.price,
                    "rsi": round(sig.rsi_value, 1),
                    "vwap": round(sig.vwap_value, 2),
                    "volume_ratio": round(sig.volume_ratio, 1),
                    "factors": sig.factors,
                })
        return sorted(signals, key=lambda x: x["score"], reverse=True)

    def get_positions_data(self) -> list[dict]:
        """Get position data for the dashboard."""
        positions = []
        # Get live prices for active positions
        active_symbols = [p.symbol for p in self.engine.tracker.active_positions]
        live_prices = self.kite.get_ltp(active_symbols) if active_symbols else {}

        for pos in self.engine.tracker.positions:
            current_price = live_prices.get(pos.symbol, pos.exit_price or pos.entry_price)
            positions.append({
                "symbol": pos.symbol,
                "direction": "LONG" if pos.is_long else "SHORT",
                "quantity": pos.quantity,
                "entry_price": pos.entry_price,
                "current_price": current_price,
                "target": pos.target_price,
                "stoploss": pos.stoploss_price,
                "pnl": pos.pnl if pos.status == PositionStatus.CLOSED else pos.calc_pnl(current_price),
                "pnl_pct": pos.calc_pnl_pct(pos.exit_price) if pos.status == PositionStatus.CLOSED
                          else pos.calc_pnl_pct(current_price),
                "status": pos.status.value,
                "trailing_active": pos.trailing_active,
                "entry_time": pos.entry_time.strftime("%H:%M:%S"),
                "score": pos.signal_score,
            })
        return positions

    def get_pnl_summary(self) -> dict:
        """Get P&L summary for the dashboard."""
        closed = self.engine.tracker.closed_positions
        active = self.engine.tracker.active_positions
        total_pnl = self.engine.tracker.total_pnl

        winners = [p for p in closed if p.pnl > 0]
        losers = [p for p in closed if p.pnl < 0]

        return {
            "total_pnl": total_pnl,
            "daily_trades": self.engine.risk.daily_trades,
            "max_daily_trades": self.config.max_daily_trades,
            "open_positions": len(active),
            "closed_trades": len(closed),
            "winners": len(winners),
            "losers": len(losers),
            "win_rate": len(winners) / len(closed) * 100 if closed else 0,
            "vix": self.engine.risk.market_state.india_vix,
            "nifty_gap": self.engine.risk.market_state.nifty_gap_pct,
            "can_trade": self.engine.risk.can_trade()[0],
            "risk_reason": self.engine.risk.can_trade()[1],
        }
