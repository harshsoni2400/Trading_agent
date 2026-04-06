"""Kite Connect SDK wrapper with authentication and data fetching."""

from __future__ import annotations

import os
import json
import time as _time
from datetime import datetime, timedelta, date
from typing import Optional

from dotenv import load_dotenv
from kiteconnect import KiteConnect

load_dotenv()


class KiteClient:
    """Wrapper around KiteConnect SDK for the trading bot."""

    def __init__(self):
        self.api_key = os.getenv("KITE_API_KEY", "")
        self.api_secret = os.getenv("KITE_API_SECRET", "")
        self.kite = KiteConnect(api_key=self.api_key)
        self.access_token: Optional[str] = None
        self._instrument_cache: dict[str, int] = {}  # symbol -> instrument_token
        self._token_file = os.path.join(os.path.dirname(__file__), "..", ".kite_session")

    @property
    def login_url(self) -> str:
        return self.kite.login_url()

    def authenticate(self, request_token: str) -> str:
        """Complete OAuth with request_token from redirect URL."""
        data = self.kite.generate_session(request_token, api_secret=self.api_secret)
        self.access_token = data["access_token"]
        self.kite.set_access_token(self.access_token)
        # Save session
        with open(self._token_file, "w") as f:
            json.dump({"access_token": self.access_token, "date": str(date.today())}, f)
        return self.access_token

    def load_session(self) -> bool:
        """Try to load a saved session from today."""
        try:
            with open(self._token_file) as f:
                data = json.load(f)
            if data.get("date") == str(date.today()):
                self.access_token = data["access_token"]
                self.kite.set_access_token(self.access_token)
                # Verify session is still valid
                self.kite.profile()
                return True
        except Exception:
            pass
        return False

    def is_authenticated(self) -> bool:
        if not self.access_token:
            return False
        try:
            self.kite.profile()
            return True
        except Exception:
            return False

    # ── Profile & Margins ────────────────────────────────────────

    def get_profile(self) -> dict:
        return self.kite.profile()

    def get_margins(self) -> dict:
        return self.kite.margins()

    # ── Instruments ──────────────────────────────────────────────

    def load_instruments(self, exchange: str = "NSE") -> dict[str, int]:
        """Load all instruments for an exchange and cache the token mapping."""
        instruments = self.kite.instruments(exchange)
        for inst in instruments:
            self._instrument_cache[inst["tradingsymbol"]] = inst["instrument_token"]
        return self._instrument_cache

    def get_instrument_token(self, symbol: str) -> Optional[int]:
        """Get instrument token for a symbol. Loads instruments if cache is empty."""
        if not self._instrument_cache:
            self.load_instruments()
        return self._instrument_cache.get(symbol)

    # ── Market Data ──────────────────────────────────────────────

    def get_ltp(self, symbols: list[str]) -> dict[str, float]:
        """Get last traded price for multiple symbols.

        Args:
            symbols: List like ["RELIANCE", "TCS"]

        Returns:
            {"RELIANCE": 2850.5, "TCS": 3400.0}
        """
        instruments = [f"NSE:{s}" for s in symbols]
        data = self.kite.ltp(instruments)
        result = {}
        for s in symbols:
            key = f"NSE:{s}"
            if key in data:
                result[s] = data[key]["last_price"]
        return result

    def get_ohlc(self, symbols: list[str]) -> dict[str, dict]:
        """Get OHLC + last price for multiple symbols."""
        instruments = [f"NSE:{s}" for s in symbols]
        data = self.kite.ohlc(instruments)
        result = {}
        for s in symbols:
            key = f"NSE:{s}"
            if key in data:
                result[s] = data[key]
        return result

    def get_quotes(self, symbols: list[str]) -> dict[str, dict]:
        """Get full quote data for symbols."""
        instruments = [f"NSE:{s}" for s in symbols]
        data = self.kite.quote(instruments)
        result = {}
        for s in symbols:
            key = f"NSE:{s}"
            if key in data:
                result[s] = data[key]
        return result

    def get_historical_data(
        self,
        symbol: str,
        interval: str,
        from_date: datetime,
        to_date: datetime,
    ) -> list[dict]:
        """Fetch historical candle data.

        Args:
            symbol: Stock symbol (e.g., "RELIANCE")
            interval: "minute", "5minute", "15minute", "day", etc.
            from_date: Start datetime
            to_date: End datetime

        Returns:
            List of dicts: [{date, open, high, low, close, volume}, ...]
        """
        token = self.get_instrument_token(symbol)
        if token is None:
            return []
        data = self.kite.historical_data(token, from_date, to_date, interval)
        return data

    def get_historical_batch(
        self,
        symbols: list[str],
        interval: str,
        from_date: datetime,
        to_date: datetime,
        delay: float = 0.35,
    ) -> dict[str, list[dict]]:
        """Fetch historical data for multiple symbols with rate limiting.

        Args:
            symbols: List of stock symbols.
            interval: Candle interval.
            from_date: Start datetime.
            to_date: End datetime.
            delay: Seconds between API calls (Kite allows ~3/sec).

        Returns:
            {symbol: [candle_dicts], ...}
        """
        result = {}
        for i, symbol in enumerate(symbols):
            try:
                data = self.get_historical_data(symbol, interval, from_date, to_date)
                result[symbol] = data
            except Exception as e:
                result[symbol] = []
            if i < len(symbols) - 1:
                _time.sleep(delay)
        return result

    # ── VIX & Nifty ──────────────────────────────────────────────

    def get_india_vix(self) -> float:
        """Get current India VIX value."""
        try:
            data = self.kite.ltp(["NSE:INDIA VIX"])
            return data.get("NSE:INDIA VIX", {}).get("last_price", 0.0)
        except Exception:
            return 0.0

    def get_nifty_data(self) -> dict:
        """Get Nifty 50 OHLC data for gap calculation."""
        try:
            data = self.kite.ohlc(["NSE:NIFTY 50"])
            nifty = data.get("NSE:NIFTY 50", {})
            return {
                "last_price": nifty.get("last_price", 0),
                "open": nifty.get("ohlc", {}).get("open", 0),
                "close": nifty.get("ohlc", {}).get("close", 0),  # prev day close
            }
        except Exception:
            return {"last_price": 0, "open": 0, "close": 0}

    # ── Orders ───────────────────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        transaction_type: str,
        quantity: int,
        order_type: str = "LIMIT",
        price: float = 0,
        trigger_price: float = 0,
        product: str = "MIS",
    ) -> str:
        """Place an order and return order_id."""
        params = {
            "tradingsymbol": symbol,
            "exchange": "NSE",
            "transaction_type": transaction_type,
            "quantity": quantity,
            "order_type": order_type,
            "product": product,
            "variety": "regular",
        }
        if price > 0:
            params["price"] = price
        if trigger_price > 0:
            params["trigger_price"] = trigger_price

        order_id = self.kite.place_order(**params)
        return str(order_id)

    def modify_order(self, order_id: str, trigger_price: float = 0, price: float = 0) -> str:
        """Modify an existing order."""
        params = {"order_id": order_id, "variety": "regular"}
        if trigger_price > 0:
            params["trigger_price"] = trigger_price
        if price > 0:
            params["price"] = price
        return str(self.kite.modify_order(**params))

    def cancel_order(self, order_id: str) -> str:
        """Cancel an order."""
        return str(self.kite.cancel_order(variety="regular", order_id=order_id))

    def get_orders(self) -> list[dict]:
        """Get all orders for the day."""
        return self.kite.orders()

    def get_positions(self) -> dict:
        """Get day positions."""
        return self.kite.positions()

    def get_holdings(self) -> list[dict]:
        """Get holdings."""
        return self.kite.holdings()
