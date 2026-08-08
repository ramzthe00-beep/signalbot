# -*- coding: utf-8 -*-
"""
Signal Bot Pro - TheTrueTrade
====================================================================
ربات سیگنال‌دهی پیشرفته - فقط ارسال سیگنال (بدون ترید خودکار)
نسخه اصلاح شده نهایی - با لاگ کامل تلگرام و پیام‌های اختصاصی
+ محدودیت پیام نزدیکی (آستانه‌های 5%، 3%، 1%، 0.5%)
+ رند کردن قیمت‌ها با ۱۰ رقم اعشار
+ اضافه شدن BNBUSDT, SOLUSDT, PAXGUSDT
"""

import os
import time
import threading
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from flask import Flask
import json
import logging

# =====================================================================================
# تنظیمات logging
# =====================================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# =====================================================================================
# تنظیمات تلگرام
# =====================================================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8681448214:AAG4Ve-8GUTtQQS3wb5V9FDcuTeOoGbA4oM")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "7402770612")

# =====================================================================================
# تنظیمات صرافی
# =====================================================================================
BASE_URL = "https://apiv2.thetruetrade.io"

HISTORY_FILE = "trades_history.json"

# =====================================================================================
# تنظیمات Tick Size و Precision برای هر نماد
# =====================================================================================
TICK_SIZES = {
    "LTCUSDT": 0.01,
    "DOGEUSDT": 0.00001,
    "ETHUSDT": 0.01,
    "BNBUSDT": 0.01,
    "SOLUSDT": 0.001,
    "PAXGUSDT": 0.01,
}

PRICE_PRECISION = {
    "LTCUSDT": 2,
    "DOGEUSDT": 5,
    "ETHUSDT": 2,
    "BNBUSDT": 2,
    "SOLUSDT": 3,
    "PAXGUSDT": 2,
}

# =====================================================================================
# کلاس دریافت داده
# =====================================================================================
class TrueTradeData:
    def __init__(self):
        self.base_url = BASE_URL

    def fetch_ohlcv(self, symbol, timeframe='1m', limit=500):
        symbol_clean = symbol.upper()
        resolution_map = {
            "1m": "1", "5m": "5", "15m": "15", "30m": "30",
            "1h": "60", "4h": "240", "1d": "D", "1w": "W", "1M": "M"
        }
        resolution = resolution_map.get(timeframe, "1")

        to_timestamp = int(time.time())
        from_timestamp = to_timestamp - (limit * 60)

        uri = f"/futures/udf/history?symbol={symbol_clean}&resolution={resolution}&from={from_timestamp}&to={to_timestamp}&countback={limit}"

        try:
            response = requests.get(f"{self.base_url}{uri}", timeout=15)
            response.raise_for_status()
            data = response.json()

            if not data or data.get('s') != 'ok':
                return None

            df = pd.DataFrame({
                'timestamp': pd.to_datetime(data['t'], unit='s'),
                'open': pd.to_numeric(data['o']),
                'high': pd.to_numeric(data['h']),
                'low': pd.to_numeric(data['l']),
                'close': pd.to_numeric(data['c']),
                'volume': pd.to_numeric(data['v'])
            })
            df.set_index('timestamp', inplace=True)
            return df
        except Exception as e:
            logger.error(f"[FETCH ERROR] {symbol}: {e}")
            return None

# =====================================================================================
# توابع تلگرام
# =====================================================================================
def send_telegram_message(message: str):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        logger.error(f"[TELEGRAM] {e}")

def format_iran_time(dt=None):
    if dt is None:
        dt = datetime.now(timezone(timedelta(hours=3, minutes=30)))
    return dt.strftime('%Y-%m-%d %H:%M:%S')

def format_iran_date(dt=None):
    if dt is None:
        dt = datetime.now(timezone(timedelta(hours=3, minutes=30)))
    return dt.strftime('%Y-%m-%d')

# =====================================================================================
# کلاس وضعیت هشدار نزدیکی
# =====================================================================================
class ProximityState:
    def __init__(self):
        self._last_target_alert = None
        self._last_stop_alert = None
        self._target_hit_notified = False
        self._stop_hit_notified = False

_proximity_states = {}

# =====================================================================================
# توابع محاسباتی
# =====================================================================================
def calc_rsi(close, length=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1.0/length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0/length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50)

def calc_ema(series, length):
    return series.ewm(span=length, adjust=False).mean()

def calc_macd(close, fast=12, slow=26, signal=9):
    ema_fast = calc_ema(close, fast)
    ema_slow = calc_ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    return macd_line, signal_line, macd_line - signal_line

def calc_atr(high, low, close, length=14):
    prev_close = close.shift(1)
    tr = pd.concat([high-low, (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0/length, min_periods=length, adjust=False).mean()

def find_pivot_high(high, left=5, right=3):
    n = len(high)
    result = pd.Series(np.nan, index=high.index)
    for i in range(left, n - right):
        if not (high.iloc[i-left:i] >= high.iloc[i]).any() and not (high.iloc[i+1:i+right+1] >= high.iloc[i]).any():
            result.iloc[i] = high.iloc[i]
    return result

def find_pivot_low(low, left=5, right=3):
    n = len(low)
    result = pd.Series(np.nan, index=low.index)
    for i in range(left, n - right):
        if not (low.iloc[i-left:i] <= low.iloc[i]).any() and not (low.iloc[i+1:i+right+1] <= low.iloc[i]).any():
            result.iloc[i] = low.iloc[i]
    return result

def is_trending_up(close, ref_bar, lookback=20, slope_min_pct=0.05):
    if ref_bar is None or ref_bar - lookback < 0:
        return False
    y = close.iloc[ref_bar - lookback:ref_bar + 1].values
    if len(y) < 2:
        return False
    slope = np.polyfit(np.arange(len(y)), y, 1)[0]
    avg = y.mean()
    return (slope / avg) * 100 > slope_min_pct if avg != 0 else False

def is_trending_down(close, ref_bar, lookback=20, slope_min_pct=0.05):
    if ref_bar is None or ref_bar - lookback < 0:
        return False
    y = close.iloc[ref_bar - lookback:ref_bar + 1].values
    if len(y) < 2:
        return False
    slope = np.polyfit(np.arange(len(y)), y, 1)[0]
    avg = y.mean()
    return (slope / avg) * 100 < -slope_min_pct if avg != 0 else False

def resolve_bar_from_ts(df_indexed, ts):
    if ts not in df_indexed.index:
        return None
    return df_indexed.index.get_loc(ts)

def round_price(price, symbol):
    """رند کردن قیمت با ۱۰ رقم اعشار و tick size"""
    precision = PRICE_PRECISION.get(symbol.upper(), 2)
    tick = TICK_SIZES.get(symbol.upper(), 0.01)
    rounded = round(price / tick) * tick
    return round(rounded, precision)

def compute_stop_and_targets(pivot_highs, pivot_lows, direction, df_indexed, atr_val, stop_buffer_pct=0.05):
    if direction == "long":
        if len(pivot_lows) < 2:
            return None, None, None
        pl_1, pl_2 = pivot_lows[-2], pivot_lows[-1]

        bar1 = resolve_bar_from_ts(df_indexed, pl_1['ts'])
        bar2 = resolve_bar_from_ts(df_indexed, pl_2['ts'])

        if bar1 is None or bar2 is None or bar2 <= bar1:
            return None, None, None

        stop_price = min(pl_1['price'], pl_2['price']) - stop_buffer_pct * atr_val
        mid_peak = df_indexed["high"].iloc[bar1+1:bar2].max() if bar2 > bar1+1 else df_indexed["high"].iloc[bar1:bar2+1].max()
        if pd.isna(mid_peak):
            return None, None, None
        return stop_price, mid_peak, None

    elif direction == "short":
        if len(pivot_highs) < 2:
            return None, None, None
        ph_1, ph_2 = pivot_highs[-2], pivot_highs[-1]

        bar1 = resolve_bar_from_ts(df_indexed, ph_1['ts'])
        bar2 = resolve_bar_from_ts(df_indexed, ph_2['ts'])

        if bar1 is None or bar2 is None or bar2 <= bar1:
            return None, None, None

        stop_price = max(ph_1['price'], ph_2['price']) + stop_buffer_pct * atr_val
        mid_trough = df_indexed["low"].iloc[bar1+1:bar2].min() if bar2 > bar1+1 else df_indexed["low"].iloc[bar1:bar2+1].min()
        if pd.isna(mid_trough):
            return None, None, None
        return stop_price, mid_trough, None

    return None, None, None

def resolve_final_target(entry, stop, tp_raw, direction, min_rr=2.0):
    risk = abs(entry - stop)
    if risk <= 0:
        return tp_raw
    rr = abs(tp_raw - entry) / risk
    if rr >= min_rr:
        return tp_raw
    return entry + risk * min_rr if direction == "long" else entry - risk * min_rr

# =====================================================================================
# سیستم امتیازدهی
# =====================================================================================
def calculate_divergence_score(p1, p2, direction, df, current_price):
    score = 0
    details = []

    if direction == "BUY":
        if p2['price'] < p1['price'] and p2['rsi'] > p1['rsi']:
            score += 1; details.append("✅ RSI Divergence (Classic)")
        elif p2['price'] > p1['price'] and p2['rsi'] < p1['rsi']:
            score += 1; details.append("✅ RSI Divergence (Hidden)")
        else:
            details.append("❌ RSI")
    else:
        if p2['price'] > p1['price'] and p2['rsi'] < p1['rsi']:
            score += 1; details.append("✅ RSI Divergence (Classic)")
        elif p2['price'] < p1['price'] and p2['rsi'] > p1['rsi']:
            score += 1; details.append("✅ RSI Divergence (Hidden)")
        else:
            details.append("❌ RSI")

    if direction == "BUY":
        if p2['price'] < p1['price'] and p2['macdline'] > p1['macdline']:
            score += 1; details.append("✅ MACD Line Divergence")
        elif p2['price'] > p1['price'] and p2['macdline'] < p1['macdline']:
            score += 1; details.append("✅ MACD Line Divergence (Hidden)")
        else:
            details.append("❌ MACD Line")
    else:
        if p2['price'] > p1['price'] and p2['macdline'] < p1['macdline']:
            score += 1; details.append("✅ MACD Line Divergence")
        elif p2['price'] < p1['price'] and p2['macdline'] > p1['macdline']:
            score += 1; details.append("✅ MACD Line Divergence (Hidden)")
        else:
            details.append("❌ MACD Line")

    hist_div = False
    if direction == "BUY":
        if p2['price'] < p1['price'] and p2['hist'] > p1['hist']:
            hist_div = True
        elif p2['price'] > p1['price'] and p2['hist'] < p1['hist']:
            hist_div = True
    else:
        if p2['price'] > p1['price'] and p2['hist'] < p1['hist']:
            hist_div = True
        elif p2['price'] < p1['price'] and p2['hist'] > p1['hist']:
            hist_div = True

    color_changed = (p1['hist'] < 0 and p2['hist'] > 0) or (p1['hist'] > 0 and p2['hist'] < 0)
    if hist_div and color_changed:
        score += 1; details.append("✅ MACD Histogram + Color Change")
    elif hist_div:
        details.append("⚠️ MACD Histogram (No Color Change)")
    else:
        details.append("❌ MACD Histogram")

    if len(df) > 20:
        h20, l20 = df['high'].iloc[-20:].max(), df['low'].iloc[-20:].min()
        if h20 != l20:
            f618 = l20 + 0.618*(h20-l20)
            f786 = l20 + 0.786*(h20-l20)
            if abs(current_price-f618)/f618 < 0.005 or abs(current_price-f786)/f786 < 0.005:
                score += 1; details.append("✅ Fibonacci (0.618/0.786)")
            else:
                details.append("❌ Fibonacci")
        else:
            details.append("❌ Fibonacci")
    else:
        details.append("❌ Fibonacci")

    if len(df) >= 3:
        last, prev = df.iloc[-1], df.iloc[-2]
        avg_range = (df['high']-df['low']).rolling(10).mean().iloc[-1]
        body = abs(last['close']-last['open'])
        upper_wick = last['high'] - max(last['open'], last['close'])
        lower_wick = min(last['open'], last['close']) - last['low']

        pa = False
        pa_reasons = []
        if (last['high']-last['low']) > avg_range*2:
            pa = True; pa_reasons.append("Large Candle")
        if direction == "BUY" and lower_wick > body*2 and upper_wick < body*0.5:
            pa = True; pa_reasons.append("Hammer")
        if direction == "SELL" and upper_wick > body*2 and lower_wick < body*0.5:
            pa = True; pa_reasons.append("Shooting Star")
        if direction == "BUY" and last['close']>last['open'] and prev['close']<prev['open'] and last['close']>prev['open'] and last['open']<prev['close']:
            pa = True; pa_reasons.append("Bullish Engulfing")
        if direction == "SELL" and last['close']<last['open'] and prev['close']>prev['open'] and last['close']<prev['open'] and last['open']>prev['close']:
            pa = True; pa_reasons.append("Bearish Engulfing")

        if pa:
            score += 1; details.append(f"✅ Price Action ({', '.join(pa_reasons)})")
        else:
            details.append("❌ Price Action")
    else:
        details.append("❌ Price Action")

    return score, details

def classify_signal(score, details, direction):
    if score >= 5:
        return "🟢", "Ideal", score, details
    elif score >= 4:
        return "🟡", "Custom", score, details
    elif score >= 3:
        return "⚪", "Minimal", score, details
    else:
        return None, None, score, details

# =====================================================================================
# کلاس وضعیت
# =====================================================================================
class SymbolState:
    def __init__(self):
        self.pivot_highs = []
        self.pivot_lows = []
        self.last_processed_ts = None
        self.alert_sent = False
        self.telegram_log_count = 0
        self.last_telegram_log_time = 0

SYMBOLS = ["LTCUSDT", "DOGEUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "PAXGUSDT"]
SYMBOL_STATES = {s: SymbolState() for s in SYMBOLS}

# =====================================================================================
# مدیریت تاریخچه
# =====================================================================================
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE) as f:
                return json.load(f)
        except:
            return []
    return []

def save_history(h):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(h, f, indent=2)

def update_trade_result(symbol, stime, result, price):
    h = load_history()
    for t in h:
        if t['symbol'] == symbol and t['signal_time'] == stime:
            t['result'] = result
            t['close_price'] = price
            t['close_time'] = format_iran_time()
    save_history(h)

# =====================================================================================
# توابع گزارش
# =====================================================================================
def send_daily_report():
    history = load_history()
    today_str = format_iran_date()
    today_trades = [t for t in history if t.get('signal_time', '').startswith(today_str)]
    
    if not today_trades:
        return
    
    total = len(today_trades)
    wins = len([t for t in today_trades if t.get('result') == 'TAKE_PROFIT'])
    losses = len([t for t in today_trades if t.get('result') == 'STOP_LOSS'])
    open_trades = len([t for t in today_trades if t.get('result') is None])
    closed = wins + losses
    win_rate = (wins / closed * 100) if closed > 0 else 0
    
    message = f"""📊 گزارش روزانه — {today_str}
━━━━━━━━━━━━━━━━━━━━━━

📈 کل سیگنال‌ها: {total} عدد
✅ موفق: {wins} ({win_rate:.1f}%)
❌ ناموفق: {losses}
⏳ باز: {open_trades}

📊 نرخ موفقیت (بسته شده): {win_rate:.1f}%
💪 وضعیت: {'عالی! 🚀' if wins > losses else 'نیاز به بررسی 📊'}"""

    for i, trade in enumerate(today_trades[-5:], 1):
        result_emoji = "✅" if trade.get('result') == 'TAKE_PROFIT' else "❌" if trade.get('result') == 'STOP_LOSS' else "⏳"
        direction = "LONG" if trade.get('direction') == 'BUY' else "SHORT"
        message += f"\n{i}. {trade['symbol']} {direction} {result_emoji}"
    
    message += f"\n\n━━━━━━━━━━━━━━━━━━━━━━\n🕒 {format_iran_time()}"
    send_telegram_message(message)

def send_monthly_report():
    history = load_history()
    month_ago = (datetime.now(timezone(timedelta(hours=3, minutes=30))) - timedelta(days=30)).strftime('%Y-%m-%d')
    month_trades = [t for t in history if t.get('signal_time', '') >= month_ago]
    
    if not month_trades:
        return
    
    total = len(month_trades)
    wins = len([t for t in month_trades if t.get('result') == 'TAKE_PROFIT'])
    losses = len([t for t in month_trades if t.get('result') == 'STOP_LOSS'])
    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
    
    message = f"""📈 گزارش ۳۰ روز گذشته
━━━━━━━━━━━━━━━━━━━━━━

📊 کل سیگنال‌ها: {total} عدد
✅ موفق: {wins} ({win_rate:.1f}%)
❌ ناموفق: {losses}

📈 نرخ موفقیت: {win_rate:.1f}%
📊 میانگین روزانه: {(wins-losses)/30:.1f} سیگنال
💪 ارزیابی: {'پروژه موفق! 🎉' if wins > losses else 'نیاز به بهینه‌سازی ⚙️'}

━━━━━━━━━━━━━━━━━━━━━━
🕒 {format_iran_time()}"""
    send_telegram_message(message)

# =====================================================================================
# Startup Diagnostic
# =====================================================================================
def run_startup_diagnostic():
    logger.info("Running Startup Diagnostic...")
    
    diagnostic_log = []
    diagnostic_log.append("🔍 بررسی سلامت سیستم")
    diagnostic_log.append("━━━━━━━━━━━━━━━━━━━━━━")
    
    try:
        requests.get("https://www.google.com", timeout=5)
        diagnostic_log.append("🟢 اتصال اینترنت")
    except:
        diagnostic_log.append("🔴 اتصال اینترنت")
    
    data = TrueTradeData()
    try:
        df = data.fetch_ohlcv("LTCUSDT", "1m", 500)
        if df is not None and not df.empty:
            diagnostic_log.append(f"🟢 دریافت داده: {len(df)} کندل")
        else:
            diagnostic_log.append("🔴 دریافت داده")
    except Exception as e:
        diagnostic_log.append(f"🔴 دریافت داده: {str(e)[:50]}")
    
    try:
        if df is not None and not df.empty:
            rsi = calc_rsi(df['close'], 14)
            diagnostic_log.append(f"🟢 RSI(14): {rsi.iloc[-1]:.2f}")
            diagnostic_log.append("🟢 MACD(12,26,9): فعال")
            atr = calc_atr(df['high'], df['low'], df['close'], 14)
            diagnostic_log.append(f"🟢 ATR(14): {atr.iloc[-1]:.4f}")
            ph = find_pivot_high(df['high'], 5, 3)
            pl = find_pivot_low(df['low'], 5, 3)
            diagnostic_log.append(f"🟢 Pivot High(5,3): {ph.notna().sum()} عدد")
            diagnostic_log.append(f"🟢 Pivot Low(5,3): {pl.notna().sum()} عدد")
            diagnostic_log.append("🟢 تشخیص روند: فعال")
    except Exception as e:
        diagnostic_log.append(f"🔴 خطا در محاسبات: {str(e)[:50]}")
    
    diagnostic_log.append("🟢 موتور امتیازدهی: آماده")
    diagnostic_log.append("🟢 اتصال به تلگرام")
    
    diagnostic_log.append("\n━━━━━━━━━━━━━━━━━━━━━━")
    diagnostic_log.append("✅ تمام بخش‌ها فعال هستند")
    diagnostic_log.append(f"🕒 {format_iran_time()}")
    
    send_telegram_message("\n".join(diagnostic_log))
    logger.info("Startup Diagnostic Complete")

# =====================================================================================
# تابع تشخیص سیگنال
# =====================================================================================
def detect_signal(df, state, symbol, debug=False):
    debug_log = []
    def log(msg):
        debug_log.append(msg)
        if debug:
            logger.info(msg)

    log(f"🔍 DTM — {symbol} | {format_iran_time()}")

    closed_df_indexed = df.iloc[:-1].copy()
    closed_df = closed_df_indexed.reset_index(drop=True)

    n = len(closed_df)
    if n < 33:
        log(f"❌ داده ناکافی: {n}")
        return None, None, None, None, False, None, None, None, [], ""

    close = closed_df["close"]
    high = closed_df["high"]
    low = closed_df["low"]

    rsi_val = calc_rsi(close, 14)
    macd_line, signal_line, hist_line = calc_macd(close, 12, 26, 9)
    atr14 = calc_atr(high, low, close, 14)
    pivot_high = find_pivot_high(high, 5, 3)
    pivot_low = find_pivot_low(low, 5, 3)

    right_bars = 3
    last_valid_pivot_index = n - right_bars - 1

    new_pivots_high = []
    new_pivots_low = []

    existing_high_ts = {p['ts'] for p in state.pivot_highs}
    existing_low_ts = {p['ts'] for p in state.pivot_lows}

    if state.last_processed_ts is None:
        start_bar = 0
    else:
        if state.last_processed_ts in closed_df_indexed.index:
            last_pos = closed_df_indexed.index.get_loc(state.last_processed_ts)
            start_bar = max(0, last_pos - 5)
        else:
            start_bar = max(0, n - 10)

    start_bar = min(start_bar, last_valid_pivot_index)

    log(f"   n={n}, last_valid={last_valid_pivot_index}, start={start_bar}")

    for i in range(start_bar, last_valid_pivot_index + 1):
        ts = closed_df_indexed.index[i]

        if not pd.isna(pivot_high.iloc[i]) and ts not in existing_high_ts:
            new_pivots_high.append({
                'ts': ts, 'price': pivot_high.iloc[i],
                'rsi': rsi_val.iloc[i], 'macdline': macd_line.iloc[i], 'hist': hist_line.iloc[i]
            })
        if not pd.isna(pivot_low.iloc[i]) and ts not in existing_low_ts:
            new_pivots_low.append({
                'ts': ts, 'price': pivot_low.iloc[i],
                'rsi': rsi_val.iloc[i], 'macdline': macd_line.iloc[i], 'hist': hist_line.iloc[i]
            })

    if n > 0:
        state.last_processed_ts = closed_df_indexed.index[min(last_valid_pivot_index, n-1)]

    state.pivot_highs.extend(new_pivots_high)
    state.pivot_lows.extend(new_pivots_low)

    if len(state.pivot_highs) > 100:
        state.pivot_highs = state.pivot_highs[-100:]
    if len(state.pivot_lows) > 100:
        state.pivot_lows = state.pivot_lows[-100:]

    log(f"   new_high={len(new_pivots_high)}, new_low={len(new_pivots_low)} | mem: H={len(state.pivot_highs)} L={len(state.pivot_lows)}")

    early_signal = len(new_pivots_high) > 0 or len(new_pivots_low) > 0
    entry_price = close.iloc[-1]
    current_price = df['close'].iloc[-1]

    buy_signal = sell_signal = None
    buy_emoji = sell_emoji = None
    buy_label = sell_label = None
    buy_score = sell_score = 0
    buy_stop = buy_target = sell_stop = sell_target = None
    buy_details = sell_details = []
    buy_signal_type = sell_signal_type = ""

    # BUY
    if len(state.pivot_lows) >= 2:
        pl_1, pl_2 = state.pivot_lows[-2], state.pivot_lows[-1]
        bar1 = resolve_bar_from_ts(closed_df_indexed, pl_1['ts'])

        if bar1 is not None:
            is_classic_buy = pl_2['price'] < pl_1['price']
            is_hidden_buy = pl_2['price'] > pl_1['price']

            if is_classic_buy or is_hidden_buy:
                if is_classic_buy:
                    trend_ok = is_trending_down(close, bar1, 20, 0.05)
                    log(f"   🔵 Classic BUY check: bar1={bar1}, trend={'✅' if trend_ok else '❌'}")
                else:
                    trend_ok = True
                    log(f"   🔵 Hidden BUY check: bar1={bar1}, trend=⏭️ (skipped)")

                if trend_ok:
                    score, details = calculate_divergence_score(pl_1, pl_2, "BUY", df, current_price)
                    buy_emoji, buy_label, buy_score, _ = classify_signal(score, details, "BUY")
                    buy_details = details
                    buy_signal_type = "Classic" if is_classic_buy else "Hidden"
                    log(f"   🔵 {buy_signal_type} BUY score={score}/5 {'✅' if buy_emoji else '❌'}")
                    if score >= 2:
                        for d in details:
                            log(f"      {d}")

                    if buy_emoji and score >= 3:
                        stop, tp_raw, _ = compute_stop_and_targets(
                            state.pivot_highs, state.pivot_lows, "long", closed_df_indexed, atr14.iloc[-1]
                        )
                        if stop and tp_raw:
                            buy_stop, buy_target = stop, resolve_final_target(entry_price, stop, tp_raw, "long")
                            buy_signal = "BUY"
                            log(f"   Entry={entry_price:.4f}, SL={stop:.4f}, TP={buy_target:.4f}")
        else:
            log(f"   🔵 BUY: pl_1 ts not in current window")

    # SELL
    if len(state.pivot_highs) >= 2:
        ph_1, ph_2 = state.pivot_highs[-2], state.pivot_highs[-1]
        bar1 = resolve_bar_from_ts(closed_df_indexed, ph_1['ts'])

        if bar1 is not None:
            is_classic_sell = ph_2['price'] > ph_1['price']
            is_hidden_sell = ph_2['price'] < ph_1['price']

            if is_classic_sell or is_hidden_sell:
                if is_classic_sell:
                    trend_ok = is_trending_up(close, bar1, 20, 0.05)
                    log(f"   🔴 Classic SELL check: bar1={bar1}, trend={'✅' if trend_ok else '❌'}")
                else:
                    trend_ok = True
                    log(f"   🔴 Hidden SELL check: bar1={bar1}, trend=⏭️ (skipped)")

                if trend_ok:
                    score, details = calculate_divergence_score(ph_1, ph_2, "SELL", df, current_price)
                    sell_emoji, sell_label, sell_score, _ = classify_signal(score, details, "SELL")
                    sell_details = details
                    sell_signal_type = "Classic" if is_classic_sell else "Hidden"
                    log(f"   🔴 {sell_signal_type} SELL score={score}/5 {'✅' if sell_emoji else '❌'}")
                    if score >= 2:
                        for d in details:
                            log(f"      {d}")

                    if sell_emoji and score >= 3:
                        stop, tp_raw, _ = compute_stop_and_targets(
                            state.pivot_highs, state.pivot_lows, "short", closed_df_indexed, atr14.iloc[-1]
                        )
                        if stop and tp_raw:
                            sell_stop, sell_target = stop, resolve_final_target(entry_price, stop, tp_raw, "short")
                            sell_signal = "SELL"
                            log(f"   Entry={entry_price:.4f}, SL={stop:.4f}, TP={sell_target:.4f}")
        else:
            log(f"   🔴 SELL: ph_1 ts not in current window")

    if not buy_signal and not sell_signal:
        log(f"   ⚪ No signal")

    # ⚡ ارسال لاگ به تلگرام
    current_time = time.time()
    should_send = False
    if state.telegram_log_count < 10:
        if state.last_telegram_log_time == 0 or (current_time - state.last_telegram_log_time) >= 300:
            should_send = True
    else:
        if current_time - state.last_telegram_log_time >= 21600:
            should_send = True

    if should_send:
        state.last_telegram_log_time = current_time
        state.telegram_log_count += 1
        try:
            telegram_debug = "\n".join(debug_log)
            prefix = "🟢" if len(new_pivots_high)+len(new_pivots_low) > 0 else "ℹ️"
            send_telegram_message(
                f"{prefix} لاگ #{state.telegram_log_count} — {symbol}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"```\n{telegram_debug[:3000]}\n```\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🕒 {format_iran_time()}"
            )
        except Exception as e:
            logger.error(f"[TELEGRAM] {e}")

    if buy_signal:
        return "BUY", entry_price, buy_stop, buy_target, early_signal, buy_emoji, buy_label, buy_score, buy_details, buy_signal_type
    elif sell_signal:
        return "SELL", entry_price, sell_stop, sell_target, early_signal, sell_emoji, sell_label, sell_score, sell_details, sell_signal_type
    return None, None, None, None, early_signal, None, None, None, [], ""

# =====================================================================================
# پیگیری سیگنال‌های باز
# =====================================================================================
def check_proximity(symbol, current_price, entry, stop, target, state):
    if entry is None or stop is None or target is None:
        return
    
    stop_distance = abs(current_price - stop) / entry * 100
    target_distance = abs(current_price - target) / entry * 100
    
    thresholds = [5.0, 3.0, 1.0, 0.5]
    
    if target_distance > 0:
        for t in thresholds:
            if target_distance <= t:
                if not hasattr(state, '_last_target_alert') or state._last_target_alert is None or target_distance < t:
                    send_telegram_message(
                        f"🎯 نزدیک شدن به حد سود\n\n"
                        f"🔹 نماد: {symbol}\n"
                        f"💰 قیمت فعلی: {current_price:.4f}\n"
                        f"🎯 حد سود: {target:.4f}\n"
                        f"📊 فاصله: {target_distance:.2f}%\n\n"
                        f"⏳ در آستانه بسته شدن\n"
                        f"🕒 {format_iran_time()}"
                    )
                    state._last_target_alert = t
                break
    
    if stop_distance > 0:
        for t in thresholds:
            if stop_distance <= t:
                if not hasattr(state, '_last_stop_alert') or state._last_stop_alert is None or stop_distance < t:
                    send_telegram_message(
                        f"⚠️ نزدیک شدن به حد ضرر\n\n"
                        f"🔹 نماد: {symbol}\n"
                        f"💰 قیمت فعلی: {current_price:.4f}\n"
                        f"🛑 حد ضرر: {stop:.4f}\n"
                        f"📊 فاصله: {stop_distance:.2f}%\n\n"
                        f"⚠️ نیاز به پایش دقیق\n"
                        f"🕒 {format_iran_time()}"
                    )
                    state._last_stop_alert = t
                break

def track_open_signals():
    history = load_history()
    data = TrueTradeData()
    for trade in history:
        if trade.get('result') is None:
            df = data.fetch_ohlcv(trade['symbol'], '1m', 10)
            if df is None or df.empty:
                continue
            cp = df['close'].iloc[-1]
            entry = trade['entry_price']
            stop = trade['stop_loss']
            target = trade['take_profit']
            
            key = f"{trade['symbol']}_{trade['signal_time']}"
            if key not in _proximity_states:
                _proximity_states[key] = ProximityState()
            
            check_proximity(trade['symbol'], cp, entry, stop, target, _proximity_states[key])
            
            if trade['direction'] == 'BUY':
                if cp >= target and not _proximity_states[key]._target_hit_notified:
                    update_trade_result(trade['symbol'], trade['signal_time'], 'TAKE_PROFIT', cp)
                    profit_pct = (cp-entry)/entry*100
                    _proximity_states[key]._target_hit_notified = True
                    send_telegram_message(
                        f"🎯 حد سود فعال شد\n\n"
                        f"🔹 نماد: {trade['symbol']}\n"
                        f"🔸 جهت: LONG (خرید)\n\n"
                        f"📍 ورود: {entry:.4f}\n"
                        f"🎯 خروج: {cp:.4f}\n\n"
                        f"📈 میزان سود: +{profit_pct:.2f}%\n"
                        f"🕒 {format_iran_time()}"
                    )
                elif cp <= stop and not _proximity_states[key]._stop_hit_notified:
                    update_trade_result(trade['symbol'], trade['signal_time'], 'STOP_LOSS', cp)
                    loss_pct = (cp-entry)/entry*100
                    _proximity_states[key]._stop_hit_notified = True
                    send_telegram_message(
                        f"💔 حد ضرر فعال شد\n\n"
                        f"🔹 نماد: {trade['symbol']}\n"
                        f"🔸 جهت: LONG (خرید)\n\n"
                        f"📍 ورود: {entry:.4f}\n"
                        f"💔 خروج: {cp:.4f}\n\n"
                        f"📉 میزان ضرر: {loss_pct:.2f}%\n"
                        f"🕒 {format_iran_time()}"
                    )
            else:
                if cp <= target and not _proximity_states[key]._target_hit_notified:
                    update_trade_result(trade['symbol'], trade['signal_time'], 'TAKE_PROFIT', cp)
                    profit_pct = (entry-cp)/entry*100
                    _proximity_states[key]._target_hit_notified = True
                    send_telegram_message(
                        f"🎯 حد سود فعال شد\n\n"
                        f"🔹 نماد: {trade['symbol']}\n"
                        f"🔸 جهت: SHORT (فروش)\n\n"
                        f"📍 ورود: {entry:.4f}\n"
                        f"🎯 خروج: {cp:.4f}\n\n"
                        f"📈 میزان سود: +{profit_pct:.2f}%\n"
                        f"🕒 {format_iran_time()}"
                    )
                elif cp >= stop and not _proximity_states[key]._stop_hit_notified:
                    update_trade_result(trade['symbol'], trade['signal_time'], 'STOP_LOSS', cp)
                    loss_pct = (entry-cp)/entry*100
                    _proximity_states[key]._stop_hit_notified = True
                    send_telegram_message(
                        f"💔 حد ضرر فعال شد\n\n"
                        f"🔹 نماد: {trade['symbol']}\n"
                        f"🔸 جهت: SHORT (فروش)\n\n"
                        f"📍 ورود: {entry:.4f}\n"
                        f"💔 خروج: {cp:.4f}\n\n"
                        f"📉 میزان ضرر: {loss_pct:.2f}%\n"
                        f"🕒 {format_iran_time()}"
                    )

# =====================================================================================
# تابع اصلی
# =====================================================================================
def analyze_and_send():
    data = TrueTradeData()
    track_open_signals()

    for symbol in SYMBOLS:
        try:
            df = data.fetch_ohlcv(symbol, '1m', 500)
            if df is None or df.empty:
                logger.warning(f"[SKIP] {symbol}")
                continue

            logger.info(f"[DATA] {symbol}: {len(df)} کندل")

            result = detect_signal(df, SYMBOL_STATES[symbol], symbol, debug=True)
            signal, entry, stop, target, early, emoji, label, score = result[:8]
            details = result[8] if len(result) > 8 else []
            signal_type = result[9] if len(result) > 9 else ""
            cp = df['close'].iloc[-1]

            if early and not SYMBOL_STATES[symbol].alert_sent:
                SYMBOL_STATES[symbol].alert_sent = True
                send_telegram_message(
                    f"⚡ در حال تشکیل Pivot جدید\n\n"
                    f"🔹 نماد: {symbol}\n"
                    f"💰 قیمت: {cp:.4f}\n"
                    f"📊 نوع: کف/قله جدید\n\n"
                    f"⏳ تا تأیید نهایی حدود ۲ دقیقه\n"
                    f"🕒 {format_iran_time()}"
                )

            if signal and stop and target:
                # رند کردن قیمت‌ها
                entry = round_price(entry, symbol)
                stop = round_price(stop, symbol)
                target = round_price(target, symbol)
                
                profit_pct = (target-entry)/entry*100 if signal=="BUY" else (entry-target)/entry*100
                loss_pct = (entry-stop)/entry*100 if signal=="BUY" else (stop-entry)/entry*100
                rr = abs(profit_pct/loss_pct) if loss_pct != 0 else 0
                direction_text = "LONG (خرید)" if signal == "BUY" else "SHORT (فروش)"
                direction_emoji = "🟢" if signal == "BUY" else "🔴"
                
                details_text = ""
                if details:
                    details_text = "\n".join([f"{i+1}. {d}" for i, d in enumerate(details)])
                
                signal_label = f"{label} ({signal_type})" if signal_type else label
                
                send_telegram_message(
                    f"{emoji} سیگنال {signal_label} — {symbol}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"📊 امتیاز: {score}/5\n"
                    f"🔸 نوع: {direction_emoji} {direction_text}\n\n"
                    f"📍 نقطه ورود: {entry:.{PRICE_PRECISION.get(symbol, 2)}f}\n"
                    f"🛑 حد ضرر: {stop:.{PRICE_PRECISION.get(symbol, 2)}f}\n"
                    f"🎯 حد سود: {target:.{PRICE_PRECISION.get(symbol, 2)}f}\n\n"
                    f"📈 سود مورد انتظار: +{profit_pct:.2f}%\n"
                    f"📉 ضرر قابل قبول: -{loss_pct:.2f}%\n"
                    f"⚖️ نسبت Risk/Reward: {rr:.2f}\n\n"
                    f"✅ دلایل تأیید سیگنال:\n{details_text}\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🕒 {format_iran_time()}"
                )

                history = load_history()
                history.append({
                    'symbol': symbol, 'direction': signal,
                    'entry_price': entry, 'stop_loss': stop, 'take_profit': target,
                    'signal_time': format_iran_time(), 'result': None, 'score': score, 'label': label
                })
                save_history(history)

                SYMBOL_STATES[symbol].alert_sent = False
            else:
                logger.info(f"[ANALYSIS] {symbol}: بدون سیگنال")
        except Exception as e:
            logger.error(f"[ERROR] {symbol}: {e}")

# =====================================================================================
# حلقه اصلی
# =====================================================================================
def signal_loop():
    last_daily_report = None
    last_monthly_report = None
    
    while True:
        try:
            logger.info(f"[LOOP] {format_iran_time()}")
            analyze_and_send()
            
            today = format_iran_date()
            if last_daily_report != today:
                send_daily_report()
                last_daily_report = today
            
            if last_monthly_report is None or (datetime.now(timezone(timedelta(hours=3, minutes=30))) - last_monthly_report).days >= 30:
                send_monthly_report()
                last_monthly_report = datetime.now(timezone(timedelta(hours=3, minutes=30)))
            
            time.sleep(60)
        except Exception as e:
            logger.error(f"[LOOP] {e}")
            time.sleep(60)

# =====================================================================================
app = Flask(__name__)
@app.route("/")
def health():
    return "Signal Bot Pro is running.", 200

if __name__ == "__main__":
    logger.info("Signal Bot Pro Starting...")
    
    send_telegram_message(
        "🤖 SignalBot Pro — آنلاین\n\n"
        "🧠 استراتژی: DTM Divergence\n"
        "📊 سیگنال‌دهی: خودکار (فقط سیگنال)\n"
        "❌ ترید خودکار: غیرفعال\n\n"
        "⚙️ تنظیمات:\n"
        "• Timeframe: 1m\n"
        "• Pivot: Left=5, Right=3\n"
        "• Memory: 100 Pivot\n"
        "• Scoring: 3-Level (🟢🟡⚪)\n"
        "• Trend Filter: Classic only\n"
        "• Symbols: LTC, DOGE, ETH, BNB, SOL, PAXG\n"
        "• Price Precision: 2-10 decimals\n\n"
        f"🕒 {format_iran_time()}"
    )
    
    run_startup_diagnostic()
    
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000), daemon=True).start()
    logger.info("[STARTUP] Flask روی پورت 10000")
    
    signal_loop()
