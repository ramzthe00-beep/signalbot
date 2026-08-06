# -*- coding: utf-8 -*-
"""
Signal Bot Pro - TheTrueTrade
====================================================================
ربات سیگنال‌دهی پیشرفته با هشدارهای هوشمند، پیگیری معاملات و گزارش‌های دوره‌ای
"""

import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
import threading
from flask import Flask
import json
import os

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
# فایل ذخیره تاریخچه معاملات
# =====================================================================================
HISTORY_FILE = "trades_history.json"

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
# توابع ارسال پیام به تلگرام (با قالب‌های جذاب)
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
# توابع محاسباتی استراتژی (دقیقاً از پروژه قبلی)
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
    """محاسبه حد ضرر و حد سود"""
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
    """محاسبه حد سود نهایی با نسبت ریسک به ریوارد"""
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
        
        # برای تشخیص سیگنال نزدیک
        self.last_check_price = None
        self.alert_sent = False

# =====================================================================================
# مدیریت تاریخچه معاملات
# =====================================================================================
def load_history():
    """بارگذاری تاریخچه معاملات از فایل"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    return []

def save_history(history):
    """ذخیره تاریخچه معاملات در فایل"""
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f, indent=2)

def update_trade_result(symbol, signal_time, result, price):
    """به‌روزرسانی نتیجه یک معامله (تارگت یا استاپ)"""
    history = load_history()
    for trade in history:
        if trade['symbol'] == symbol and trade['signal_time'] == signal_time:
            trade['result'] = result
            trade['close_price'] = price
            trade['close_time'] = format_iran_time()
            break
    save_history(history)

# =====================================================================================
# تابع تشخیص سیگنال کامل (با قابلیت هشدار زودهنگام)
# =====================================================================================
def detect_signal(df, state, symbol):
    """تشخیص سیگنال با هشدار زودهنگام در RIGHT_BARS=2"""
    closed_df = df.iloc[:-1].reset_index(drop=True)
    n = len(closed_df)
    if n < 5 + 3 + 20 + 5:
        return None, None, None, None, False

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
    
    # هشدار زودهنگام (در RIGHT_BARS=2)
    early_check_i = last_i - 2
    early_signal = False
    
    if early_check_i >= 5:
        early_high = not pd.isna(pivot_high.iloc[early_check_i])
        early_low = not pd.isna(pivot_low.iloc[early_check_i])
        if early_high or early_low:
            early_signal = True

    if pivot_check_i < 5:
        return None, None, None, None, early_signal

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
    current_price = df['close'].iloc[-1]

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
            return "BUY", entry_price, levels["stop"], target, early_signal

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
            return "SELL", entry_price, levels["stop"], target, early_signal

    return None, None, None, None, early_signal

# =====================================================================================
# بررسی نزدیکی به تارگت یا استاپ
# =====================================================================================
def check_proximity(symbol, current_price, entry, stop, target):
    """بررسی نزدیکی قیمت به تارگت یا استاپ و ارسال هشدار"""
    if entry is None or stop is None or target is None:
        return
    
    # محاسبه فاصله درصدی
    stop_distance = abs(current_price - stop) / entry * 100
    target_distance = abs(current_price - target) / entry * 100
    
    # اگر قیمت به تارگت نزدیک شد (کمتر از 5%)
    if target_distance < 5 and target_distance > 0:
        message = (
            f"🎯 **هشدار نزدیکی به تارگت**\n"
            f"🔹 **نماد:** {symbol}\n"
            f"💰 **قیمت فعلی:** {current_price:.4f}\n"
            f"🎯 **تارگت:** {target:.4f}\n"
            f"📊 **فاصله:** {target_distance:.2f}%\n"
            f"🕒 **زمان ایران:** {format_iran_time()}\n"
            f"💡 **وضعیت:** در آستانه رسیدن به تارگت!"
        )
        send_telegram_message(message)
        print(f"[PROXIMITY] {symbol}: نزدیک به تارگت! فاصله: {target_distance:.2f}%")
    
    # اگر قیمت به استاپ نزدیک شد (کمتر از 5%)
    elif stop_distance < 5 and stop_distance > 0:
        message = (
            f"🛑 **هشدار نزدیکی به استاپ**\n"
            f"🔹 **نماد:** {symbol}\n"
            f"💰 **قیمت فعلی:** {current_price:.4f}\n"
            f"🛑 **استاپ:** {stop:.4f}\n"
            f"📊 **فاصله:** {stop_distance:.2f}%\n"
            f"🕒 **زمان ایران:** {format_iran_time()}\n"
            f"💡 **وضعیت:** در آستانه رسیدن به استاپ!"
        )
        send_telegram_message(message)
        print(f"[PROXIMITY] {symbol}: نزدیک به استاپ! فاصله: {stop_distance:.2f}%")

# =====================================================================================
# پیگیری سیگنال‌های باز
# =====================================================================================
def track_open_signals():
    """پیگیری سیگنال‌های باز و تشخیص تارگت یا استاپ"""
    history = load_history()
    data = TrueTradeData()
    
    for trade in history:
        if trade.get('result') is None:  # معامله هنوز باز است
            symbol = trade['symbol']
            df = data.fetch_ohlcv(symbol, '1m', 10)
            if df is None or df.empty:
                continue
            
            current_price = df['close'].iloc[-1]
            entry = trade['entry_price']
            stop = trade['stop_loss']
            target = trade['take_profit']
            
            # بررسی نزدیکی به تارگت یا استاپ
            check_proximity(symbol, current_price, entry, stop, target)
            
            # بررسی رسیدن به تارگت
            if trade['direction'] == 'BUY' and current_price >= target:
                update_trade_result(symbol, trade['signal_time'], 'TAKE_PROFIT', current_price)
                message = (
                    f"🎉 **تارگت محقق شد!**\n"
                    f"🔹 **نماد:** {symbol}\n"
                    f"💰 **قیمت فعلی:** {current_price:.4f}\n"
                    f"🎯 **تارگت:** {target:.4f}\n"
                    f"📈 **سود:** {(current_price - entry) / entry * 100:.2f}%\n"
                    f"🕒 **زمان ایران:** {format_iran_time()}"
                )
                send_telegram_message(message)
                print(f"[RESULT] {symbol}: تارگت خورد! قیمت: {current_price:.4f}")
                
            elif trade['direction'] == 'SELL' and current_price <= target:
                update_trade_result(symbol, trade['signal_time'], 'TAKE_PROFIT', current_price)
                message = (
                    f"🎉 **تارگت محقق شد!**\n"
                    f"🔹 **نماد:** {symbol}\n"
                    f"💰 **قیمت فعلی:** {current_price:.4f}\n"
                    f"🎯 **تارگت:** {target:.4f}\n"
                    f"📈 **سود:** {(entry - current_price) / entry * 100:.2f}%\n"
                    f"🕒 **زمان ایران:** {format_iran_time()}"
                )
                send_telegram_message(message)
                print(f"[RESULT] {symbol}: تارگت خورد! قیمت: {current_price:.4f}")
                
            # بررسی رسیدن به استاپ
            elif trade['direction'] == 'BUY' and current_price <= stop:
                update_trade_result(symbol, trade['signal_time'], 'STOP_LOSS', current_price)
                message = (
                    f"💔 **استاپ خورد!**\n"
                    f"🔹 **نماد:** {symbol}\n"
                    f"💰 **قیمت فعلی:** {current_price:.4f}\n"
                    f"🛑 **استاپ:** {stop:.4f}\n"
                    f"📉 **ضرر:** {(current_price - entry) / entry * 100:.2f}%\n"
                    f"🕒 **زمان ایران:** {format_iran_time()}"
                )
                send_telegram_message(message)
                print(f"[RESULT] {symbol}: استاپ خورد! قیمت: {current_price:.4f}")
                
            elif trade['direction'] == 'SELL' and current_price >= stop:
                update_trade_result(symbol, trade['signal_time'], 'STOP_LOSS', current_price)
                message = (
                    f"💔 **استاپ خورد!**\n"
                    f"🔹 **نماد:** {symbol}\n"
                    f"💰 **قیمت فعلی:** {current_price:.4f}\n"
                    f"🛑 **استاپ:** {stop:.4f}\n"
                    f"📉 **ضرر:** {(entry - current_price) / entry * 100:.2f}%\n"
                    f"🕒 **زمان ایران:** {format_iran_time()}"
                )
                send_telegram_message(message)
                print(f"[RESULT] {symbol}: استاپ خورد! قیمت: {current_price:.4f}")

# =====================================================================================
# گزارش روزانه و ماهانه
# =====================================================================================
def send_daily_report():
    """ارسال گزارش روزانه"""
    history = load_history()
    if not history:
        send_telegram_message("📋 **گزارش روزانه**\nامروز هیچ معامله‌ای انجام نشده است.")
        return
    
    today = datetime.now().date()
    today_trades = [t for t in history if datetime.fromisoformat(t['signal_time']).date() == today]
    
    if not today_trades:
        send_telegram_message("📋 **گزارش روزانه**\nامروز هیچ معامله‌ای انجام نشده است.")
        return
    
    total = len(today_trades)
    wins = len([t for t in today_trades if t.get('result') == 'TAKE_PROFIT'])
    losses = len([t for t in today_trades if t.get('result') == 'STOP_LOSS'])
    open_trades = len([t for t in today_trades if t.get('result') is None])
    
    message = (
        f"📅 **گزارش روزانه ({format_iran_time().split()[0]})**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 **معاملات امروز:** {total} عدد\n"
        f"✅ **موفق (تارگت):** {wins} عدد\n"
        f"❌ **ناموفق (استاپ):** {losses} عدد\n"
        f"⏳ **باز:** {open_trades} عدد\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 **نرخ موفقیت:** {wins/total*100 if total > 0 else 0:.1f}%\n"
    )
    
    # اضافه کردن جزئیات معاملات
    for i, trade in enumerate(today_trades[-5:], 1):  # آخرین ۵ معامله
        result_emoji = "✅" if trade.get('result') == 'TAKE_PROFIT' else "❌" if trade.get('result') == 'STOP_LOSS' else "⏳"
        message += (
            f"\n{i}. {trade['symbol']} {trade['direction']} {result_emoji}"
            f" | Entry: {trade['entry_price']:.4f}"
            f" | SL: {trade['stop_loss']:.4f}"
            f" | TP: {trade['take_profit']:.4f}"
        )
    
    send_telegram_message(message)

def send_monthly_report():
    """ارسال گزارش ماهانه"""
    history = load_history()
    if not history:
        send_telegram_message("📊 **گزارش ماهانه**\nاین ماه هیچ معامله‌ای انجام نشده است.")
        return
    
    today = datetime.now()
    month_ago = today - timedelta(days=30)
    month_trades = [t for t in history if datetime.fromisoformat(t['signal_time']) >= month_ago]
    
    if not month_trades:
        send_telegram_message("📊 **گزارش ماهانه**\nاین ماه هیچ معامله‌ای انجام نشده است.")
        return
    
    total = len(month_trades)
    wins = len([t for t in month_trades if t.get('result') == 'TAKE_PROFIT'])
    losses = len([t for t in month_trades if t.get('result') == 'STOP_LOSS'])
    open_trades = len([t for t in month_trades if t.get('result') is None])
    
    message = (
        f"📊 **گزارش ماهانه (۳۰ روز گذشته)**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 **کل معاملات:** {total} عدد\n"
        f"✅ **موفق (تارگت):** {wins} عدد\n"
        f"❌ **ناموفق (استاپ):** {losses} عدد\n"
        f"⏳ **باز:** {open_trades} عدد\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 **نرخ موفقیت:** {wins/total*100 if total > 0 else 0:.1f}%\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 **میانگین سود/ضرر روزانه:** {(wins - losses) / 30:.2f} معامله\n"
    )
    
    send_telegram_message(message)

# =====================================================================================
# تابع اصلی تحلیل و ارسال سیگنال
# =====================================================================================
def analyze_and_send():
    """دریافت داده، تحلیل و ارسال سیگنال به تلگرام با هشدار زودهنگام"""
    data = TrueTradeData()
    symbols = ["LTCUSDT", "DOGEUSDT", "ETHUSDT"]
    
    states = {symbol: SymbolState() for symbol in symbols}
    
    # پیگیری سیگنال‌های باز
    track_open_signals()
    
    for symbol in symbols:
        try:
            df = data.fetch_ohlcv(symbol, '1m', 500)
            if df is None or df.empty:
                print(f"[SKIP] {symbol}: داده‌ای دریافت نشد")
                continue
            
            print(f"[DATA] {symbol}: {len(df)} کندل دریافت شد")
            
            signal, entry_price, stop_loss, take_profit, early_signal = detect_signal(df, states[symbol], symbol)
            
            current_price = df['close'].iloc[-1]
            
            # هشدار زودهنگام
            if early_signal and not states[symbol].alert_sent:
                message = (
                    f"⚠️ **هشدار آماده باش!**\n"
                    f"🔹 **نماد:** {symbol}\n"
                    f"💰 **قیمت فعلی:** {current_price:.4f}\n"
                    f"🕒 **زمان ایران:** {format_iran_time()}\n"
                    f"💡 **وضعیت:** احتمال تشکیل قله/کف جدید!\n"
                    f"⏳ **زمان تا سیگنال نهایی:** ~۲ دقیقه"
                )
                send_telegram_message(message)
                states[symbol].alert_sent = True
                print(f"[EARLY] {symbol}: هشدار آماده باش ارسال شد")
            
            if signal is not None:
                # ارسال سیگنال اصلی
                iran_time = format_iran_time()
                direction_text = "🟢 خرید (BUY)" if signal == "BUY" else "🔴 فروش (SELL)"
                direction_emoji = "🟢" if signal == "BUY" else "🔴"
                
                # تخمین سود و ضرر
                if signal == "BUY":
                    potential_profit = (take_profit - entry_price) / entry_price * 100
                    potential_loss = (entry_price - stop_loss) / entry_price * 100
                else:
                    potential_profit = (entry_price - take_profit) / entry_price * 100
                    potential_loss = (stop_loss - entry_price) / entry_price * 100
                
                message = (
                    f"📊 **سیگنال معاملاتی - ربات سیگنال‌دهی حرفه‌ای**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🔹 **نماد:** {symbol}\n"
                    f"🔸 **نوع:** {direction_text}\n"
                    f"💰 **قیمت فعلی:** {current_price:.4f}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📍 **نقطه ورود:** {entry_price:.4f}\n"
                    f"🛑 **حد ضرر (Stop Loss):** {stop_loss:.4f}\n"
                    f"🎯 **حد سود (Take Profit):** {take_profit:.4f}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📈 **سود احتمالی:** {potential_profit:.2f}%\n"
                    f"📉 **ضرر احتمالی:** {potential_loss:.2f}%\n"
                    f"📊 **نسبت ریسک به ریوارد:** 1:{take_profit - entry_price / (entry_price - stop_loss):.2f}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🕒 **زمان ایران:** {iran_time}\n"
                    f"🤖 **ربات:** SignalBot Pro (فقط سیگنال، بدون معامله)\n"
                    f"💡 **توجه:** این سیگنال با استراتژی DTM Divergence تولید شده است."
                )
                
                send_telegram_message(message)
                print(f"[SIGNAL] {symbol}: {signal} | Entry: {entry_price:.4f} | SL: {stop_loss:.4f} | TP: {take_profit:.4f}")
                
                # ذخیره سیگنال در تاریخچه
                history = load_history()
                history.append({
                    'symbol': symbol,
                    'direction': signal,
                    'entry_price': entry_price,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'signal_time': format_iran_time(),
                    'result': None,
                    'close_price': None,
                    'close_time': None
                })
                save_history(history)
                
                # ریست هشدار
                states[symbol].alert_sent = False
                
            else:
                print(f"[ANALYSIS] {symbol}: بدون سیگنال")
                
        except Exception as e:
            print(f"[ERROR] {symbol}: {e}")

# =====================================================================================
# حلقه اصلی
# =====================================================================================
def signal_loop():
    """حلقه بررسی مداوم"""
    # متغیرهای کنترل گزارش
    last_daily_report = None
    last_monthly_report = None
    
    while True:
        try:
            print("[LOOP] شروع یک دور جدید بررسی...")
            analyze_and_send()
            print("[LOOP] پایان دور بررسی، ۶۰ ثانیه مکث...")
            
            # بررسی گزارش روزانه
            today = datetime.now().date()
            if last_daily_report != today:
                send_daily_report()
                last_daily_report = today
            
            # بررسی گزارش ماهانه
            if last_monthly_report is None or (datetime.now() - last_monthly_report).days >= 30:
                send_monthly_report()
                last_monthly_report = datetime.now()
            
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
    return "Signal Bot Pro is running.", 200

def run_flask():
    app.run(host="0.0.0.0", port=10000)

# =====================================================================================
# اجرای اصلی
# =====================================================================================
if __name__ == "__main__":
    # ارسال پیام استارت
    send_telegram_message(
        "🤖 **ربات سیگنال‌دهی حرفه‌ای (SignalBot Pro) راه‌اندازی شد!**\n"
        "📊 در حال دریافت داده و تحلیل بازار...\n"
        "⚠️ **توجه:** این ربات فقط سیگنال ارسال می‌کند و هیچ معامله‌ای انجام نمی‌دهد.\n"
        "💡 **قابلیت‌ها:**\n"
        "• هشدار آماده باش ۲ دقیقه قبل از سیگنال\n"
        "• پیگیری تارگت/استاپ\n"
        "• گزارش‌های روزانه و ماهانه\n"
        "• هشدار نزدیک شدن به تارگت/استاپ"
    )
    
    # اجرای Flask در یک ترد جداگانه
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("[STARTUP] وب‌سرور Flask روی پورت 10000 راه‌اندازی شد.")
    
    # شروع حلقه اصلی
    print("[STARTUP] شروع حلقه دریافت و تحلیل داده...")
    signal_loop()
