# -*- coding: utf-8 -*-
"""
Signal Bot - TheTrueTrade
====================================================================
ربات دریافت داده و ارسال سیگنال به تلگرام با محاسبه نقاط ورود، حد ضرر و حد سود
(بدون معامله خودکار) - منطق استراتژی دقیقاً از پروژه قبلی کپی شده است
"""

import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
import threading
from flask import Flask

# =====================================================================================
# تنظیمات تلگرام
# =====================================================================================
TELEGRAM_BOT_TOKEN = "8514469828:AAFC76EiVA7I4TFiX08jJ5N6-eKtOLMKitE"
TELEGRAM_CHAT_ID = "7402770612"

# =====================================================================================
# تنظیمات صرافی
# =====================================================================================
BASE_URL = "https://apiv2.thetruetrade.io"

# =====================================================================================
# کلاس دریافت داده بدون نیاز به احراز هویت
# =====================================================================================
class TrueTradeData:
    def __init__(self):
        self.base_url = BASE_URL

    def fetch_ohlcv(self, symbol, timeframe='1m', limit=500):
        """دریافت داده‌های تاریخچه قیمت بدون نیاز به کلید API"""
        symbol_clean = symbol.upper()
        
        resolution_map = {
            "1m": "1",
            "5m": "5",
            "15m": "15",
            "30m": "30",
            "1h": "60",
            "4h": "240",
            "1d": "D",
            "1w": "W",
            "1M": "M"
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
            print(f"[FETCH ERROR] {symbol}: {e}")
            return None

# =====================================================================================
# توابع ارسال پیام به تلگرام
# =====================================================================================
def send_telegram_message(message: str):
    """ارسال پیام به تلگرام"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
    except Exception as e:
        print(f"[TELEGRAM ERROR] {e}")

def get_iran_time():
    """دریافت زمان ایران (UTC+3:30)"""
    return datetime.now(timezone(timedelta(hours=3, minutes=30)))

def format_iran_time(dt=None):
    """فرمت‌سازی زمان ایران"""
    if dt is None:
        dt = get_iran_time()
    return dt.strftime('%Y-%m-%d %H:%M:%S')

# =====================================================================================
# توابع محاسباتی استراتژی (دقیقاً از پروژه قبلی کپی شده)
# =====================================================================================
def calc_rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)

def calc_ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()

def calc_macd(close: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = calc_ema(close, fast)
    ema_slow = calc_ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    hist_line = macd_line - signal_line
    return macd_line, signal_line, hist_line

def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()

def find_pivot_high(high: pd.Series, left_bars: int = 5, right_bars: int = 3):
    n = len(high)
    result = pd.Series(np.nan, index=high.index)
    for i in range(left_bars, n - right_bars):
        window_left = high.iloc[i - left_bars:i]
        window_right = high.iloc[i + 1:i + right_bars + 1]
        center = high.iloc[i]
        if not (window_left >= center).any() and not (window_right >= center).any():
            result.iloc[i] = center
    return result

def find_pivot_low(low: pd.Series, left_bars: int = 5, right_bars: int = 3):
    n = len(low)
    result = pd.Series(np.nan, index=low.index)
    for i in range(left_bars, n - right_bars):
        window_left = low.iloc[i - left_bars:i]
        window_right = low.iloc[i + 1:i + right_bars + 1]
        center = low.iloc[i]
        if not (window_left <= center).any() and not (window_right <= center).any():
            result.iloc[i] = center
    return result

def check_color_change(hist_line: pd.Series, bar_start: int, bar_end: int, need_red_phase: bool) -> bool:
    if bar_start is None or bar_end is None or bar_end <= bar_start:
        return False
    segment = hist_line.iloc[bar_start + 1:bar_end]
    return (segment < 0).any() if need_red_phase else (segment > 0).any()

def is_trending_up(close: pd.Series, ref_bar: int, lookback: int = 20, slope_min_pct: float = 0.05) -> bool:
    if ref_bar is None or ref_bar - lookback < 0:
        return False
    y = close.iloc[ref_bar - lookback:ref_bar + 1].values
    if len(y) < 2:
        return False
    x = np.arange(len(y))
    slope = np.polyfit(x, y, 1)[0]
    avg = y.mean()
    if avg == 0:
        return False
    return (slope / avg) * 100 > slope_min_pct

def is_trending_down(close: pd.Series, ref_bar: int, lookback: int = 20, slope_min_pct: float = 0.05) -> bool:
    if ref_bar is None or ref_bar - lookback < 0:
        return False
    y = close.iloc[ref_bar - lookback:ref_bar + 1].values
    if len(y) < 2:
        return False
    x = np.arange(len(y))
    slope = np.polyfit(x, y, 1)[0]
    avg = y.mean()
    if avg == 0:
        return False
    return (slope / avg) * 100 < -slope_min_pct

def compute_stop_and_targets(state, direction, df, atr_val):
    """محاسبه حد ضرر و حد سود - دقیقاً از پروژه قبلی"""
    if direction == "long":
        if state['pl_price_1'] is None or state['pl_price_2'] is None:
            return None
        stop_price = min(state['pl_price_1'], state['pl_price_2']) - 0.05 * atr_val

        bar1, bar2 = state['pl_bar_1'], state['pl_bar_2']
        if bar1 is None or bar2 is None or bar2 <= bar1:
            return None
        mid_peak = df["high"].iloc[bar1 + 1:bar2].max() if bar2 > bar1 + 1 else df["high"].iloc[bar1:bar2 + 1].max()
        if pd.isna(mid_peak):
            return None
        return {"stop": stop_price, "tp1_raw": mid_peak}

    elif direction == "short":
        if state['ph_price_1'] is None or state['ph_price_2'] is None:
            return None
        stop_price = max(state['ph_price_1'], state['ph_price_2']) + 0.05 * atr_val

        bar1, bar2 = state['ph_bar_1'], state['ph_bar_2']
        if bar1 is None or bar2 is None or bar2 <= bar1:
            return None
        mid_trough = df["low"].iloc[bar1 + 1:bar2].min() if bar2 > bar1 + 1 else df["low"].iloc[bar1:bar2 + 1].min()
        if pd.isna(mid_trough):
            return None
        return {"stop": stop_price, "tp1_raw": mid_trough}

    return None

def resolve_final_target(entry_price: float, stop_price: float, tp1_raw: float, direction: str, min_rr_ratio: float = 2.0) -> float:
    """محاسبه حد سود نهایی با نسبت ریسک به ریوارد - دقیقاً از پروژه قبلی"""
    risk_dist = abs(entry_price - stop_price)
    if risk_dist <= 0:
        return tp1_raw
    reward_dist = abs(tp1_raw - entry_price)
    rr = reward_dist / risk_dist
    if rr >= min_rr_ratio:
        return tp1_raw
    if direction == "long":
        return entry_price + risk_dist * min_rr_ratio
    else:
        return entry_price - risk_dist * min_rr_ratio

# =====================================================================================
# کلاس وضعیت (برای نگهداری قله‌ها و کف‌ها)
# =====================================================================================
class SymbolState:
    def __init__(self):
        self.ph_price_2 = self.ph_price_1 = None
        self.ph_bar_2 = self.ph_bar_1 = None
        self.ph_rsi_2 = self.ph_rsi_1 = None
        self.ph_macdline_2 = self.ph_macdline_1 = None
        self.ph_hist_2 = self.ph_hist_1 = None

        self.pl_price_2 = self.pl_price_1 = None
        self.pl_bar_2 = self.pl_bar_1 = None
        self.pl_rsi_2 = self.pl_rsi_1 = None
        self.pl_macdline_2 = self.pl_macdline_1 = None
        self.pl_hist_2 = self.pl_hist_1 = None

# =====================================================================================
# تابع تشخیص سیگنال کامل (دقیقاً از پروژه قبلی)
# =====================================================================================
def detect_signal(df, state):
    """تشخیص سیگنال با استفاده از منطق کامل DTM - دقیقاً از پروژه قبلی"""
    closed_df = df.iloc[:-1].reset_index(drop=True)
    n = len(closed_df)
    if n < 5 + 3 + 20 + 5:
        return None, None, None, None

    close = closed_df["close"]
    high = closed_df["high"]
    low = closed_df["low"]

    rsi_val = calc_rsi(close, 14)
    macd_line, signal_line, hist_line = calc_macd(close, 12, 26, 9)
    atr14 = calc_atr(high, low, close, 14)
    pivot_high = find_pivot_high(high, 5, 3)
    pivot_low = find_pivot_low(low, 5, 3)

    last_i = n - 1
    pivot_check_i = last_i - 3
    if pivot_check_i < 5:
        return None, None, None, None

    new_pivot_high = not pd.isna(pivot_high.iloc[pivot_check_i])
    new_pivot_low = not pd.isna(pivot_low.iloc[pivot_check_i])

    if new_pivot_high:
        state.ph_price_1, state.ph_bar_1 = state.ph_price_2, state.ph_bar_2
        state.ph_rsi_1, state.ph_macdline_1, state.ph_hist_1 = state.ph_rsi_2, state.ph_macdline_2, state.ph_hist_2
        state.ph_price_2 = pivot_high.iloc[pivot_check_i]
        state.ph_bar_2 = pivot_check_i
        state.ph_rsi_2 = rsi_val.iloc[pivot_check_i]
        state.ph_macdline_2 = macd_line.iloc[pivot_check_i]
        state.ph_hist_2 = hist_line.iloc[pivot_check_i]

    if new_pivot_low:
        state.pl_price_1, state.pl_bar_1 = state.pl_price_2, state.pl_bar_2
        state.pl_rsi_1, state.pl_macdline_1, state.pl_hist_1 = state.pl_rsi_2, state.pl_macdline_2, state.pl_hist_2
        state.pl_price_2 = pivot_low.iloc[pivot_check_i]
        state.pl_bar_2 = pivot_check_i
        state.pl_rsi_2 = rsi_val.iloc[pivot_check_i]
        state.pl_macdline_2 = macd_line.iloc[pivot_check_i]
        state.pl_hist_2 = hist_line.iloc[pivot_check_i]

    macd_color_changed_highs = check_color_change(hist_line, state.ph_bar_1, state.ph_bar_2, True) if new_pivot_high and state.ph_bar_1 is not None else False
    macd_color_changed_lows = check_color_change(hist_line, state.pl_bar_1, state.pl_bar_2, False) if new_pivot_low and state.pl_bar_1 is not None else False

    trend_ok_bearish = is_trending_up(close, state.ph_bar_1, 20, 0.05) if new_pivot_high and state.ph_bar_1 is not None else False
    trend_ok_bullish = is_trending_down(close, state.pl_bar_1, 20, 0.05) if new_pivot_low and state.pl_bar_1 is not None else False

    price_higher_high = new_pivot_high and state.ph_price_1 is not None and state.ph_price_2 > state.ph_price_1
    rsi_lower_high = new_pivot_high and state.ph_rsi_1 is not None and state.ph_rsi_2 < state.ph_rsi_1
    macdline_lower_high = new_pivot_high and state.ph_macdline_1 is not None and state.ph_macdline_2 < state.ph_macdline_1
    hist_lower_high = new_pivot_high and state.ph_hist_1 is not None and state.ph_hist_2 < state.ph_hist_1
    both_peaks_green = new_pivot_high and state.ph_hist_1 is not None and state.ph_hist_1 > 0 and state.ph_hist_2 > 0
    classic_bearish = price_higher_high and rsi_lower_high and macdline_lower_high and hist_lower_high and both_peaks_green and macd_color_changed_highs and trend_ok_bearish

    price_lower_low = new_pivot_low and state.pl_price_1 is not None and state.pl_price_2 < state.pl_price_1
    rsi_higher_low = new_pivot_low and state.pl_rsi_1 is not None and state.pl_rsi_2 > state.pl_rsi_1
    macdline_higher_low = new_pivot_low and state.pl_macdline_1 is not None and state.pl_macdline_2 > state.pl_macdline_1
    hist_higher_low = new_pivot_low and state.pl_hist_1 is not None and state.pl_hist_2 > state.pl_hist_1
    both_troughs_red = new_pivot_low and state.pl_hist_1 is not None and state.pl_hist_1 < 0 and state.pl_hist_2 < 0
    classic_bullish = price_lower_low and rsi_higher_low and macdline_higher_low and hist_higher_low and both_troughs_red and macd_color_changed_lows and trend_ok_bullish

    price_higher_low = new_pivot_low and state.pl_price_1 is not None and state.pl_price_2 > state.pl_price_1
    rsi_lower_low = new_pivot_low and state.pl_rsi_1 is not None and state.pl_rsi_2 < state.pl_rsi_1
    macdline_lower_low = new_pivot_low and state.pl_macdline_1 is not None and state.pl_macdline_2 < state.pl_macdline_1
    hist_lower_low = new_pivot_low and state.pl_hist_1 is not None and state.pl_hist_2 < state.pl_hist_1
    hidden_bullish = price_higher_low and rsi_lower_low and macdline_lower_low and hist_lower_low and both_troughs_red and macd_color_changed_lows

    price_lower_high = new_pivot_high and state.ph_price_1 is not None and state.ph_price_2 < state.ph_price_1
    rsi_higher_high = new_pivot_high and state.ph_rsi_1 is not None and state.ph_rsi_2 > state.ph_rsi_1
    macdline_higher_high = new_pivot_high and state.ph_macdline_1 is not None and state.ph_macdline_2 > state.ph_macdline_1
    hist_higher_high = new_pivot_high and state.ph_hist_1 is not None and state.ph_hist_2 > state.ph_hist_1
    hidden_bearish = price_lower_high and rsi_higher_high and macdline_higher_high and hist_higher_high and both_peaks_green and macd_color_changed_highs

    entry_price = close.iloc[last_i]

    if classic_bullish or hidden_bullish:
        levels = compute_stop_and_targets({
            'pl_price_1': state.pl_price_1,
            'pl_price_2': state.pl_price_2,
            'pl_bar_1': state.pl_bar_1,
            'pl_bar_2': state.pl_bar_2,
            'ph_price_1': state.ph_price_1,
            'ph_price_2': state.ph_price_2,
            'ph_bar_1': state.ph_bar_1,
            'ph_bar_2': state.ph_bar_2
        }, "long", closed_df, atr14.iloc[last_i])
        if levels:
            target = resolve_final_target(entry_price, levels["stop"], levels["tp1_raw"], "long")
            return "BUY", entry_price, levels["stop"], target

    if classic_bearish or hidden_bearish:
        levels = compute_stop_and_targets({
            'pl_price_1': state.pl_price_1,
            'pl_price_2': state.pl_price_2,
            'pl_bar_1': state.pl_bar_1,
            'pl_bar_2': state.pl_bar_2,
            'ph_price_1': state.ph_price_1,
            'ph_price_2': state.ph_price_2,
            'ph_bar_1': state.ph_bar_1,
            'ph_bar_2': state.ph_bar_2
        }, "short", closed_df, atr14.iloc[last_i])
        if levels:
            target = resolve_final_target(entry_price, levels["stop"], levels["tp1_raw"], "short")
            return "SELL", entry_price, levels["stop"], target

    return None, None, None, None

# =====================================================================================
# تابع اصلی تحلیل و ارسال سیگنال
# =====================================================================================
def analyze_and_send():
    """دریافت داده، تحلیل و ارسال سیگنال به تلگرام با نقاط ورود، استاپ و تارگت"""
    data = TrueTradeData()
    symbols = ["LTCUSDT", "DOGEUSDT", "ETHUSDT"]
    
    # وضعیت هر نماد (برای نگهداری قله‌ها و کف‌ها)
    states = {symbol: SymbolState() for symbol in symbols}
    
    for symbol in symbols:
        try:
            df = data.fetch_ohlcv(symbol, '1m', 500)
            if df is None or df.empty:
                print(f"[SKIP] {symbol}: داده‌ای دریافت نشد")
                continue
            
            print(f"[DATA] {symbol}: {len(df)} کندل دریافت شد")
            
            signal, entry_price, stop_loss, take_profit = detect_signal(df, states[symbol])
            
            if signal is not None:
                iran_time = format_iran_time()
                
                # تعیین جهت سیگنال
                direction_text = "🟢 خرید (BUY)" if signal == "BUY" else "🔴 فروش (SELL)"
                direction_emoji = "🟢" if signal == "BUY" else "🔴"
                
                message = f"📊 **سیگنال معاملاتی - ربات سیگنال‌دهی**\n"
                message += f"🔹 **نماد:** {symbol}\n"
                message += f"🔸 **نوع:** {direction_text}\n"
                message += f"💰 **قیمت فعلی:** {df['close'].iloc[-1]:.4f}\n"
                message += f"📍 **نقطه ورود:** {entry_price:.4f}\n"
                message += f"🛑 **حد ضرر (Stop Loss):** {stop_loss:.4f}\n"
                message += f"🎯 **حد سود (Take Profit):** {take_profit:.4f}\n"
                message += f"🕒 **زمان ایران:** {iran_time}\n"
                message += f"📊 **استراتژی:** DTM Divergence\n"
                message += f"🤖 **ربات:** SignalBot (فقط سیگنال، بدون معامله)"
                
                send_telegram_message(message)
                print(f"[SIGNAL] {symbol}: {signal} | Entry: {entry_price:.4f} | SL: {stop_loss:.4f} | TP: {take_profit:.4f}")
            else:
                print(f"[ANALYSIS] {symbol}: بدون سیگنال")
                
        except Exception as e:
            print(f"[ERROR] {symbol}: {e}")

# =====================================================================================
# حلقه اصلی
# =====================================================================================
def signal_loop():
    """حلقه بررسی مداوم"""
    while True:
        try:
            print("[LOOP] شروع یک دور جدید بررسی...")
            analyze_and_send()
            print("[LOOP] پایان دور بررسی، ۶۰ ثانیه مکث...")
            time.sleep(60)
            
        except Exception as e:
            print(f"[LOOP ERROR] {e}")
            time.sleep(60)

# =====================================================================================
# راه‌اندازی Flask (برای Health Check)
# =====================================================================================
app = Flask(__name__)

@app.route("/")
def health_check():
    return "Signal Bot is running.", 200

def run_flask():
    app.run(host="0.0.0.0", port=10000)

# =====================================================================================
# اجرای اصلی
# =====================================================================================
if __name__ == "__main__":
    # ارسال پیام استارت
    send_telegram_message("🤖 **ربات سیگنال‌دهی DTM (SignalBot) راه‌اندازی شد!**\n📊 در حال دریافت داده و تحلیل بازار...\n⚠️ **توجه:** این ربات فقط سیگنال ارسال می‌کند و هیچ معامله‌ای انجام نمی‌دهد.")
    
    # اجرای Flask در یک ترد جداگانه
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("[STARTUP] وب‌سرور Flask روی پورت 10000 راه‌اندازی شد.")
    
    # شروع حلقه اصلی
    print("[STARTUP] شروع حلقه دریافت و تحلیل داده...")
    signal_loop()
