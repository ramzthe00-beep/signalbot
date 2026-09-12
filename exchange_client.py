# -*- coding: utf-8 -*-
"""
exchange_client.py  —  نسخه اصلاح‌شده، هم‌راستا با الگوی main.py
=====================================================================
هر چیزی که به «صرافی/منبع داده» مربوط است: دریافت کندل (OHLCV)،
اتصال/احراز هویت، ثبت/به‌روزرسانی سفارش، استعلام موجودی و قیمت لحظه‌ای.

★ این فایل عمداً هیچ وابستگی‌ای به تلگرام ندارد — فقط نتیجه را برمی‌گرداند
یا Exception پرتاب می‌کند؛ اطلاع‌رسانی (تلگرام/لاگ) بر عهده‌ی main.py و
telegram_logger.py است.

★ الگوی منبع داده (دقیقاً هم‌راستا با main.py که قبلاً بررسی شد):
    ۱) fetch_ohlcv_binance()  → داده‌ی سیگنال از API عمومی اسپات بایننس
       (data-api.binance.vision سپس api.binance.com به‌عنوان fallback)،
       چون خودِ TradingView هم فید بایننس را نشان می‌دهد و موتور
       واگرایی/استراتژی باید روی همان کندل‌ها محاسبه شود.
    ۲) fetch_ohlcv()          → داده‌ی اجرا از خودِ صرافیِ مقصد (از طریق
       base_url که به سازنده‌ی MarketData پاس داده می‌شود)، چون قیمتِ
       واقعیِ ورود/استاپ/تارگت باید مطابق بازارِ همان صرافی باشد.
    اگر بایننس در دسترس نبود (مثلاً به‌هر دلیلی سرور در منطقه‌ای اجرا شود
    که به بایننس دسترسی ندارد)، fetch_ohlcv_binance به‌صورت خودکار و فقط
    برای همان یک فراخوانی، روی fetch_ohlcv (صرافیِ مقصد) fallback می‌کند —
    بدون هیچ‌گونه تلاش برای دورزدنِ محدودیتِ دسترسیِ بایننس.

★ منطق ورود/حجم/استاپ در اینجا «Pine-Exact» نیست و نباید باشد — طبق
درخواست صریح کاربر، تنها بخش‌هایی که باید عیناً با پاین یکی باشند
divergence_engine.py و ssl_hybrid.py هستند. اینجا صرفاً زیرساخت دریافت
داده و اجرای معامله پیاده شده است.
"""

import hashlib
import hmac
import time
import logging

import requests
import pandas as pd
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger("exchange")

# ─────────────────────────────────────────────────────────────────
# تنظیمات نمادها
# ─────────────────────────────────────────────────────────────────
TICK_SIZES = {"LTCUSDT": 0.01, "DOGEUSDT": 0.00001, "ETHUSDT": 0.01}
LEVERAGE_MAP = {"LTCUSDT": 75, "DOGEUSDT": 75, "ETHUSDT": 50}
SYMBOLS = ["LTCUSDT", "DOGEUSDT", "ETHUSDT"]


def _precision_from_tick(tick: float) -> int:
    """
    تعداد رقم اعشار را مستقیماً از اندازه‌ی تیک محاسبه می‌کند تا
    PRICE_PRECISION هرگز با TICK_SIZES ناهماهنگ نشود (همان اصلاحی که در
    main.py برای جلوگیری از باگ «Stop Loss: 0.00» روی نمادهای شش‌رقمی
    مثل PUMPUSDT اعمال شده بود). هرگز عددِ ثابت (مثلاً 2) را برای همه‌ی
    نمادها هارد-کد نکنید.
    """
    s = f"{tick:.10f}".rstrip("0")
    return len(s.split(".")[1]) if "." in s else 0


PRICE_PRECISION = {sym: _precision_from_tick(tick) for sym, tick in TICK_SIZES.items()}


def round_price(price: float, symbol: str) -> float:
    tick = TICK_SIZES.get(symbol.upper(), 0.01)
    prec = PRICE_PRECISION.get(symbol.upper(), _precision_from_tick(tick))
    return round(round(price / tick) * tick, prec)


# ═══════════════════════════════════════════════════════════════════
# دریافت داده
# ═══════════════════════════════════════════════════════════════════
class MarketData:
    """
    منبعِ دادهٔ کندل — دو مسیرِ مجزا:
      • fetch_ohlcv_binance(): برای محاسبه‌ی سیگنال، از API عمومیِ اسپات
        بایننس (بدون نیاز به کلید/احراز هویت، چون این endpoint‌ها عمومی‌اند).
      • fetch_ohlcv(): برای قیمتِ لنگرِ اجرا، از صرافیِ مقصدی که base_url
        آن به سازنده داده شده (فرمت UDF استاندارد استفاده شده که اکثر
        پلتفرم‌های مبتنی بر TradingView Charting Library پیاده‌سازی‌اش
        می‌کنند — اگر endpoint صرافیِ شما فرق دارد، فقط همین متد را
        عوض کنید).
    """

    BINANCE_BASE_CANDIDATES = [
        "https://data-api.binance.vision",
        "https://api.binance.com",
    ]

    def __init__(self, base_url: str, history_bars: int = 500):
        self.base_url = base_url
        self.history_bars = history_bars
        self.session = requests.Session()
        self._binance_base_working = None

    # ------------------------------------------------------------------
    # منبع سیگنال: بایننس (عمومی)
    # ------------------------------------------------------------------
    def fetch_ohlcv_binance(self, symbol: str, timeframe: str = "1") -> pd.DataFrame:
        """
        timeframe به‌سبکِ عددِ خامِ دقیقه ("1","5","15",...) پذیرفته می‌شود
        تا با بقیه‌ی پروژه (و main.py) هماهنگ بماند؛ داخلاً به فرمت
        interval بایننس ("1m","5m",...) ترجمه می‌شود.
        """
        interval_map = {"1": "1m", "5": "5m", "15": "15m", "30": "30m", "60": "1h", "240": "4h"}
        interval = interval_map.get(str(timeframe), f"{timeframe}m")

        try:
            multiplier = int(timeframe)
        except (TypeError, ValueError):
            multiplier = 1

        limit = min(self.history_bars, 1000)   # سقف واقعیِ endpoint بایننس
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - limit * multiplier * 60 * 1000

        bases = (
            [self._binance_base_working] if self._binance_base_working
            else self.BINANCE_BASE_CANDIDATES
        )

        last_err = None
        for base in bases:
            try:
                url = (
                    f"{base}/api/v3/klines?symbol={symbol.upper()}"
                    f"&interval={interval}&startTime={start_ms}&endTime={now_ms}&limit={limit}"
                )
                r = self.session.get(url, timeout=15)
                r.raise_for_status()
                rows = r.json()
                if not rows:
                    logger.warning(f"Binance: no candles for {symbol} {timeframe}m")
                    return pd.DataFrame()

                t = [row[0] / 1000.0 for row in rows]
                o = [row[1] for row in rows]
                h = [row[2] for row in rows]
                l = [row[3] for row in rows]
                c = [row[4] for row in rows]
                v = [row[5] for row in rows]

                df = pd.DataFrame({
                    "open": pd.to_numeric(o, errors="coerce"),
                    "high": pd.to_numeric(h, errors="coerce"),
                    "low": pd.to_numeric(l, errors="coerce"),
                    "close": pd.to_numeric(c, errors="coerce"),
                    "volume": pd.to_numeric(v, errors="coerce"),
                }, index=pd.to_datetime(t, unit="s", utc=True))

                df = df.sort_index()
                df = df[~df.index.duplicated(keep="last")]
                df = df.dropna(subset=["open", "high", "low", "close"])

                self._binance_base_working = base   # کش کن تا دفعه‌ی بعد مستقیم همین base را بزند
                result = df.tail(self.history_bars)
                logger.info(f"Fetched {len(result)} BINANCE-SPOT candles for {symbol} {timeframe}m via {base}")
                return result

            except Exception as e:
                last_err = e
                logger.warning(f"Binance base {base} failed for {symbol} {timeframe}m: {e}")
                self._binance_base_working = None
                continue

        logger.error(
            f"⚠️ Binance UNREACHABLE for {symbol} {timeframe}m ({last_err}) — "
            f"falling back to exchange data (base_url) for THIS call only."
        )
        return self.fetch_ohlcv(symbol, timeframe)

    # ------------------------------------------------------------------
    # منبع اجرا: خودِ صرافیِ مقصد (UDF)
    # ------------------------------------------------------------------
    def fetch_ohlcv(self, symbol: str, timeframe: str = "1") -> pd.DataFrame:
        try:
            multiplier = int(timeframe)
        except (TypeError, ValueError):
            multiplier = 1

        now = int(time.time())
        bars_needed = self.history_bars * multiplier * 2
        from_ts = now - bars_needed * 60 - 60
        uri = (
            f"/futures/udf/history?symbol={symbol.upper()}&resolution={timeframe}"
            f"&from={from_ts}&to={now}&countback={self.history_bars * multiplier}"
        )

        try:
            r = self.session.get(f"{self.base_url}{uri}", timeout=20)
            r.raise_for_status()
            data = r.json()

            if not data or data.get("s") != "ok":
                logger.warning(f"Exchange data not ok for {symbol} {timeframe}m: {data.get('s') if data else None}")
                return pd.DataFrame()
            if not data.get("t"):
                logger.warning(f"No exchange data for {symbol} {timeframe}m")
                return pd.DataFrame()

            df = pd.DataFrame({
                "open": pd.to_numeric(data["o"], errors="coerce"),
                "high": pd.to_numeric(data["h"], errors="coerce"),
                "low": pd.to_numeric(data["l"], errors="coerce"),
                "close": pd.to_numeric(data["c"], errors="coerce"),
                "volume": pd.to_numeric(data.get("v", [None] * len(data["t"])), errors="coerce"),
            }, index=pd.to_datetime(data["t"], unit="s", utc=True))

            df = df.sort_index()
            df = df[~df.index.duplicated(keep="last")]
            df = df.dropna(subset=["open", "high", "low", "close"])

            result = df.tail(self.history_bars)
            logger.info(f"Fetched {len(result)} exchange candles for {symbol} {timeframe}m")
            return result

        except Exception as e:
            logger.error(f"[FETCH] {symbol} ({timeframe}): {e}")
            return pd.DataFrame()

    def fetch_current_price(self, symbol: str) -> Optional[float]:
        """قیمت لحظه‌ای برای لنگرِ اجرا — از خودِ صرافیِ مقصد (نه بایننس)،
        چون این قیمت باید دقیقاً همان چیزی باشد که سفارش رویش اجرا می‌شود."""
        df = self.fetch_ohlcv(symbol, "1")
        if df is not None and not df.empty:
            return float(df["close"].iloc[-1])
        return None


# ═══════════════════════════════════════════════════════════════════
# اتصال خصوصی صرافی (سفارش/موجودی)
# ═══════════════════════════════════════════════════════════════════
class ExchangeError(Exception):
    def __init__(self, message, response=None):
        super().__init__(message)
        self.response = response


class PrivateExchange:
    def __init__(self, api_key: str, api_secret: str, base_url: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self.session = requests.Session()
        self.connected = False
        self._last_response = None

    def _sign(self, method, uri, ts):
        payload = f"{ts}{method.upper()}{uri}"
        return hmac.new(self.api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

    def _request(self, method, uri, data=None):
        ts = str(int(time.time() * 1000))
        sig = self._sign(method, uri, ts)
        headers = {"X-API-Key": self.api_key, "X-Timestamp": ts,
                   "X-Signature": sig, "Content-Type": "application/json"}
        r = self.session.request(method, f"{self.base_url}{uri}", headers=headers, json=data, timeout=15)
        self._last_response = r
        if not r.ok:
            if r.status_code in (401, 403):
                self.connected = False
            raise ExchangeError(f"{method} {uri} -> {r.status_code}: {r.text[:300]}", response=r)
        self.connected = True
        return r.json()

    def test_connection(self) -> bool:
        try:
            self._request("GET", "/futures/positions")
            self.connected = True
            return True
        except Exception as e:
            self.connected = False
            logger.error(f"[CONN] {e}")
            return False

    def fetch_balance(self):
        try:
            data = self._request("GET", "/futures/assets")
            assets = data.get("assets", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            for a in assets:
                if a.get("symbol") == "USDT":
                    return float(a.get("availableBalance", a.get("totalAssets", 0)))
            return 0.0
        except Exception as e:
            logger.error(f"[BALANCE] {e}")
            return None

    def _round_price(self, price, symbol):
        tick = TICK_SIZES.get(symbol.upper(), 0.01)
        prec = PRICE_PRECISION.get(symbol.upper(), _precision_from_tick(tick))
        return round(round(float(price) / tick) * tick, prec)

    def create_order(self, symbol, side, capital, leverage, stop_loss=None, take_profit=None):
        """
        ثبت سفارش مارکت با SL/TP اختیاری. مقادیر SL/TP قبل از ارسال به تیکِ
        نماد رند می‌شوند؛ اگر بعد از رند صفر/نامعتبر شد، از بدنه حذف می‌شود
        تا خطای صرافی نگیریم.
        برمی‌گرداند: dict نتیجه صرافی، یا ExchangeError پرتاب می‌کند.
        """
        prec = PRICE_PRECISION.get(symbol.upper(), 2)
        order_data = {
            "symbol": symbol.upper(), "side": side.upper(), "tradeType": "MARKET",
            "leverage": int(leverage), "cost": f"{capital:.{prec}f}", "walletType": "debit",
        }
        if stop_loss is not None:
            rsl = self._round_price(stop_loss, symbol)
            if rsl and rsl > 0:
                order_data["stopLoss"] = f"{rsl:.{prec}f}"
        if take_profit is not None:
            rtp = self._round_price(take_profit, symbol)
            if rtp and rtp > 0:
                order_data["takeProfit"] = f"{rtp:.{prec}f}"

        try:
            result = self._request("POST", "/futures/positions", order_data)
            return {"order_data": order_data, "result": result,
                    "position_id": result.get("positionId") if isinstance(result, dict) else None}
        except ExchangeError:
            raise
        except Exception as e:
            raise ExchangeError(str(e))

    def update_position_sl(self, position_id, symbol, stop_loss, take_profit=None):
        """ریسک‌فری: جابه‌جایی حد ضرر یک پوزیشن باز به نقطه‌ی سر‌به‌سر."""
        prec = PRICE_PRECISION.get(symbol.upper(), 2)
        body = {
            "stopLoss": f"{self._round_price(stop_loss, symbol):.{prec}f}",
            "stopLossStrategy": "LATEST_PRICE",
            "stopLossOrderType": "STOP_MARKET",
        }
        if take_profit is not None:
            body["takeProfit"] = f"{self._round_price(take_profit, symbol):.{prec}f}"
        return self._request("PATCH", f"/futures/positions/{position_id}/tpsl", body)
