# -*- coding: utf-8 -*-
"""
Signal Bot Pro - TheTrueTrade
====================================================================
ربات سیگنال‌دهی پیشرفته با سیستم امتیازدهی ۳ سطحی (سبز، زرد، سفید)
بر اساس واگرایی RSI، MACD، هیستوگرام، فیبوناچی و پرایس‌اکشن
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
TELEGRAM_BOT_TOKEN = "8681448214:AAG4Ve-8GUTtQQS3wb5V9FDcuTeOoGbA4oM"
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
# توابع محاسباتی استراتژی
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

def detect_fibonacci_retracement(pivot1_price, pivot2_price, current_price):
    """محاسبه سطح فیبوناچی ریتریسمنت"""
    if pivot1_price == pivot2_price:
        return None
    
    diff = pivot2_price - pivot1_price
    levels = {
        '0.236': pivot1_price + 0.236 * diff,
        '0.382': pivot1_price + 0.382 * diff,
        '0.5': pivot1_price + 0.5 * diff,
        '0.618': pivot1_price + 0.618 * diff,
        '0.786': pivot1_price + 0.786 * diff
    }
    
    # بررسی نزدیک بودن قیمت فعلی به سطح ۰.۶۱۸ یا ۰.۷۸۶ (با تلرانس ۰.۵%)
    tolerance = 0.005
    for level_name, level_price in levels.items():
        if level_name in ['0.618', '0.786']:
            if abs(current_price - level_price) / level_price < tolerance:
                return level_name
    return None

def detect_price_action(df, direction):
    """تشخیص الگوهای پرایس‌اکشن (Pin Bar، Engulfing، کندل بزرگ)"""
    if len(df) < 3:
        return False
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    # کندل بزرگ (حداقل ۲ برابر میانگین)
    avg_range = (df['high'] - df['low']).rolling(10).mean().iloc[-1]
    candle_range = last['high'] - last['low']
    
    if candle_range > avg_range * 2:
        return True
    
    # Pin Bar
    body = abs(last['close'] - last['open'])
    upper_wick = last['high'] - max(last['open'], last['close'])
    lower_wick = min(last['open'], last['close']) - last['low']
    
    if direction == "BUY":
        if lower_wick > body * 2 and upper_wick < body * 0.5:
            return True
    else:
        if upper_wick > body * 2 and lower_wick < body * 0.5:
            return True
    
    # Engulfing
    if direction == "BUY":
        if last['close'] > last['open'] and prev['close'] < prev['open'] and last['close'] > prev['open'] and last['open'] < prev['close']:
            return True
    else:
        if last['close'] < last['open'] and prev['close'] > prev['open'] and last['close'] < prev['open'] and last['open'] > prev['close']:
            return True
    
    return False

def calculate_divergence_score(pivot1, pivot2, direction, df, current_price):
    """
    محاسبه امتیاز واگرایی بر اساس ۵ معیار
    بازگشت: (score, details)
    """
    score = 0
    details = []
    
    # 1. RSI واگرایی
    if direction == "BUY":
        if pivot2['price'] < pivot1['price'] and pivot2['rsi'] > pivot1['rsi']:
            score += 1
            details.append("✅ RSI واگرایی")
        elif pivot2['price'] > pivot1['price'] and pivot2['rsi'] < pivot1['rsi']:
            score += 1
            details.append("✅ RSI واگرایی (مخفی)")
        else:
            details.append("❌ RSI واگرایی ندارد")
    else:  # SELL
        if pivot2['price'] > pivot1['price'] and pivot2['rsi'] < pivot1['rsi']:
            score += 1
            details.append("✅ RSI واگرایی")
        elif pivot2['price'] < pivot1['price'] and pivot2['rsi'] > pivot1['rsi']:
            score += 1
            details.append("✅ RSI واگرایی (مخفی)")
        else:
            details.append("❌ RSI واگرایی ندارد")
    
    # 2. خط MACD واگرایی
    if direction == "BUY":
        if pivot2['price'] < pivot1['price'] and pivot2['macdline'] > pivot1['macdline']:
            score += 1
            details.append("✅ خط MACD واگرایی")
        elif pivot2['price'] > pivot1['price'] and pivot2['macdline'] < pivot1['macdline']:
            score += 1
            details.append("✅ خط MACD واگرایی (مخفی)")
        else:
            details.append("❌ خط MACD واگرایی ندارد")
    else:  # SELL
        if pivot2['price'] > pivot1['price'] and pivot2['macdline'] < pivot1['macdline']:
            score += 1
            details.append("✅ خط MACD واگرایی")
        elif pivot2['price'] < pivot1['price'] and pivot2['macdline'] > pivot1['macdline']:
            score += 1
            details.append("✅ خط MACD واگرایی (مخفی)")
        else:
            details.append("❌ خط MACD واگرایی ندارد")
    
    # 3. هیستوگرام MACD واگرایی + تغییر رنگ
    hist_divergence = False
    if direction == "BUY":
        if pivot2['price'] < pivot1['price'] and pivot2['hist'] > pivot1['hist']:
            hist_divergence = True
        elif pivot2['price'] > pivot1['price'] and pivot2['hist'] < pivot1['hist']:
            hist_divergence = True
    else:  # SELL
        if pivot2['price'] > pivot1['price'] and pivot2['hist'] < pivot1['hist']:
            hist_divergence = True
        elif pivot2['price'] < pivot1['price'] and pivot2['hist'] > pivot1['hist']:
            hist_divergence = True
    
    # بررسی تغییر رنگ هیستوگرام
    color_changed = (pivot1['hist'] < 0 and pivot2['hist'] > 0) or (pivot1['hist'] > 0 and pivot2['hist'] < 0)
    
    if hist_divergence and color_changed:
        score += 1
        details.append("✅ هیستوگرام MACD واگرایی + تغییر رنگ")
    elif hist_divergence:
        details.append("⚠️ هیستوگرام MACD واگرایی (بدون تغییر رنگ)")
    else:
        details.append("❌ هیستوگرام MACD واگرایی ندارد")
    
    # 4. فیبوناچی
    fib_level = detect_fibonacci_retracement(pivot1['price'], pivot2['price'], current_price)
    if fib_level:
        score += 1
        details.append(f"✅ فیبوناچی ({fib_level})")
    else:
        details.append("❌ فیبوناچی ندارد")
    
    # 5. کندل تأییدیه پرایس‌اکشن
    pa_signal = detect_price_action(df, direction)
    if pa_signal:
        score += 1
        details.append("✅ کندل تأییدیه پرایس‌اکشن")
    else:
        details.append("❌ کندل تأییدیه ندارد")
    
    return score, details

def classify_signal(score, details, direction):
    """طبقه‌بندی سیگنال بر اساس امتیاز"""
    if score >= 5:
        return "🟢", "ایده‌آل (Ideal)", score, details
    elif score >= 4:
        return "🟡", "سفارشی (Custom)", score, details
    elif score >= 3:
        return "⚪", "حداقل مجاز (Minimal)", score, details
    else:
        return None, None, score, details

# =====================================================================================
# کلاس وضعیت (برای نگهداری قله‌ها و کف‌ها)
# =====================================================================================
class SymbolState:
    def __init__(self):
        self.pivot_highs = []
        self.pivot_lows = []
        self.last_processed_bar = 0
        self.alert_sent = False

# =====================================================================================
# مدیریت تاریخچه معاملات
# =====================================================================================
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    return []

def save_history(history):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f, indent=2)

def update_trade_result(symbol, signal_time, result, price):
    history = load_history()
    for trade in history:
        if trade['symbol'] == symbol and trade['signal_time'] == signal_time:
            trade['result'] = result
            trade['close_price'] = price
            trade['close_time'] = format_iran_time()
            break
    save_history(history)

# =====================================================================================
# تابع تشخیص سیگنال با سیستم امتیازدهی
# =====================================================================================
def detect_signal(df, state, symbol):
    """تشخیص سیگنال با سیستم امتیازدهی ۳ سطحی"""
    closed_df = df.iloc[:-1].reset_index(drop=True)
    n = len(closed_df)
    if n < 5 + 3 + 20 + 5:
        return None, None, None, None, False, None, None, None

    close = closed_df["close"]
    high = closed_df["high"]
    low = closed_df["low"]

    rsi_val = calc_rsi(close, 14)
    macd_line, signal_line, hist_line = calc_macd(close, 12, 26, 9)
    atr14 = calc_atr(high, low, close, 14)
    pivot_high = find_pivot_high(high, 5, 3)
    pivot_low = find_pivot_low(low, 5, 3)

    last_i = n - 1
    
    # پیدا کردن همه Pivotهای جدید از آخرین پردازش
    new_pivots_high = []
    new_pivots_low = []
    
    start_bar = state.last_processed_bar
    for i in range(start_bar, last_i + 1):
        if not pd.isna(pivot_high.iloc[i]):
            new_pivots_high.append({
                'price': pivot_high.iloc[i],
                'bar': i,
                'rsi': rsi_val.iloc[i],
                'macdline': macd_line.iloc[i],
                'hist': hist_line.iloc[i]
            })
        if not pd.isna(pivot_low.iloc[i]):
            new_pivots_low.append({
                'price': pivot_low.iloc[i],
                'bar': i,
                'rsi': rsi_val.iloc[i],
                'macdline': macd_line.iloc[i],
                'hist': hist_line.iloc[i]
            })
    
    state.last_processed_bar = last_i + 1
    state.pivot_highs.extend(new_pivots_high)
    state.pivot_lows.extend(new_pivots_low)
    
    if len(state.pivot_highs) > 50:
        state.pivot_highs = state.pivot_highs[-50:]
    if len(state.pivot_lows) > 50:
        state.pivot_lows = state.pivot_lows[-50:]
    
    # هشدار زودهنگام
    early_signal = False
    if len(new_pivots_high) > 0 or len(new_pivots_low) > 0:
        early_signal = True
    
    entry_price = close.iloc[last_i]
    current_price = df['close'].iloc[-1]
    
    # بررسی سیگنال خرید (کلاسیک و مخفی)
    buy_signal = None
    sell_signal = None
    
    if len(state.pivot_lows) >= 2:
        pl_1 = state.pivot_lows[-2]
        pl_2 = state.pivot_lows[-1]
        
        # شرط قیمت برای واگرایی کلاسیک خرید
        classic_price_lower = pl_2['price'] < pl_1['price']
        # شرط قیمت برای واگرایی مخفی خرید
        hidden_price_higher = pl_2['price'] > pl_1['price']
        
        # بررسی وجود حداقل یکی از دو شرط
        if classic_price_lower or hidden_price_higher:
            # بررسی روند
            trend_ok_bullish = is_trending_down(close, pl_1['bar'], 20, 0.05)
            
            if trend_ok_bullish:
                score, details = calculate_divergence_score(pl_1, pl_2, "BUY", df, current_price)
                emoji, label, final_score, _ = classify_signal(score, details, "BUY")
                
                if emoji is not None and final_score >= 3:  # حداقل امتیاز ۳
                    # محاسبه استاپ و تارگت
                    levels = compute_stop_and_targets({
                        'pl_price_1': pl_1['price'],
                        'pl_price_2': pl_2['price'],
                        'pl_bar_1': pl_1['bar'],
                        'pl_bar_2': pl_2['bar'],
                        'ph_price_1': None,
                        'ph_price_2': None,
                        'ph_bar_1': None,
                        'ph_bar_2': None
                    }, "long", closed_df, atr14.iloc[last_i])
                    
                    if levels:
                        target = resolve_final_target(entry_price, levels["stop"], levels["tp1_raw"], "long")
                        return "BUY", entry_price, levels["stop"], target, early_signal, emoji, label, final_score
    
    if len(state.pivot_highs) >= 2:
        ph_1 = state.pivot_highs[-2]
        ph_2 = state.pivot_highs[-1]
        
        # شرط قیمت برای واگرایی کلاسیک فروش
        classic_price_higher = ph_2['price'] > ph_1['price']
        # شرط قیمت برای واگرایی مخفی فروش
        hidden_price_lower = ph_2['price'] < ph_1['price']
        
        if classic_price_higher or hidden_price_lower:
            trend_ok_bearish = is_trending_up(close, ph_1['bar'], 20, 0.05)
            
            if trend_ok_bearish:
                score, details = calculate_divergence_score(ph_1, ph_2, "SELL", df, current_price)
                emoji, label, final_score, _ = classify_signal(score, details, "SELL")
                
                if emoji is not None and final_score >= 3:
                    levels = compute_stop_and_targets({
                        'pl_price_1': None,
                        'pl_price_2': None,
                        'pl_bar_1': None,
                        'pl_bar_2': None,
                        'ph_price_1': ph_1['price'],
                        'ph_price_2': ph_2['price'],
                        'ph_bar_1': ph_1['bar'],
                        'ph_bar_2': ph_2['bar']
                    }, "short", closed_df, atr14.iloc[last_i])
                    
                    if levels:
                        target = resolve_final_target(entry_price, levels["stop"], levels["tp1_raw"], "short")
                        return "SELL", entry_price, levels["stop"], target, early_signal, emoji, label, final_score
    
    return None, None, None, None, early_signal, None, None, None

# =====================================================================================
# توابع کمکی (از پروژه قبلی)
# =====================================================================================
def compute_stop_and_targets(state, direction, df, atr_val):
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
# بررسی نزدیکی به تارگت یا استاپ
# =====================================================================================
def check_proximity(symbol, current_price, entry, stop, target):
    if entry is None or stop is None or target is None:
        return
    
    stop_distance = abs(current_price - stop) / entry * 100
    target_distance = abs(current_price - target) / entry * 100
    
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
    history = load_history()
    data = TrueTradeData()
    
    for trade in history:
        if trade.get('result') is None:
            symbol = trade['symbol']
            df = data.fetch_ohlcv(symbol, '1m', 10)
            if df is None or df.empty:
                continue
            
            current_price = df['close'].iloc[-1]
            entry = trade['entry_price']
            stop = trade['stop_loss']
            target = trade['take_profit']
            
            check_proximity(symbol, current_price, entry, stop, target)
            
            if trade['direction'] == 'BUY':
                if current_price >= target:
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
                elif current_price <= stop:
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
            elif trade['direction'] == 'SELL':
                if current_price <= target:
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
                elif current_price >= stop:
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

# =====================================================================================
# گزارش روزانه و ماهانه
# =====================================================================================
def send_daily_report():
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
    
    for i, trade in enumerate(today_trades[-5:], 1):
        result_emoji = "✅" if trade.get('result') == 'TAKE_PROFIT' else "❌" if trade.get('result') == 'STOP_LOSS' else "⏳"
        message += (
            f"\n{i}. {trade['symbol']} {trade['direction']} {result_emoji}"
            f" | Entry: {trade['entry_price']:.4f}"
            f" | SL: {trade['stop_loss']:.4f}"
            f" | TP: {trade['take_profit']:.4f}"
        )
    
    send_telegram_message(message)

def send_monthly_report():
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
    data = TrueTradeData()
    symbols = ["LTCUSDT", "DOGEUSDT", "ETHUSDT"]
    states = {symbol: SymbolState() for symbol in symbols}
    
    track_open_signals()
    
    for symbol in symbols:
        try:
            df = data.fetch_ohlcv(symbol, '1m', 500)
            if df is None or df.empty:
                print(f"[SKIP] {symbol}: داده‌ای دریافت نشد")
                continue
            
            print(f"[DATA] {symbol}: {len(df)} کندل دریافت شد")
            
            signal, entry_price, stop_loss, take_profit, early_signal, emoji, label, score = detect_signal(df, states[symbol], symbol)
            current_price = df['close'].iloc[-1]
            
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
                iran_time = format_iran_time()
                direction_text = "🟢 خرید (BUY)" if signal == "BUY" else "🔴 فروش (SELL)"
                
                if signal == "BUY":
                    potential_profit = (take_profit - entry_price) / entry_price * 100
                    potential_loss = (entry_price - stop_loss) / entry_price * 100
                else:
                    potential_profit = (entry_price - take_profit) / entry_price * 100
                    potential_loss = (stop_loss - entry_price) / entry_price * 100
                
                message = (
                    f"{emoji} **سیگنال معاملاتی - {label}**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🔹 **نماد:** {symbol}\n"
                    f"🔸 **نوع:** {direction_text}\n"
                    f"💰 **قیمت فعلی:** {current_price:.4f}\n"
                    f"📊 **امتیاز:** {score}/5\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📍 **نقطه ورود:** {entry_price:.4f}\n"
                    f"🛑 **حد ضرر (Stop Loss):** {stop_loss:.4f}\n"
                    f"🎯 **حد سود (Take Profit):** {take_profit:.4f}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📈 **سود احتمالی:** {potential_profit:.2f}%\n"
                    f"📉 **ضرر احتمالی:** {potential_loss:.2f}%\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🕒 **زمان ایران:** {iran_time}\n"
                    f"🤖 **ربات:** SignalBot Pro (فقط سیگنال)\n"
                    f"💡 **توجه:** سیگنال با سیستم امتیازدهی ۳ سطحی تولید شده است."
                )
                
                send_telegram_message(message)
                print(f"[SIGNAL] {symbol}: {signal} | Score: {score}/5 | Label: {label}")
                
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
                    'close_time': None,
                    'score': score,
                    'label': label
                })
                save_history(history)
                states[symbol].alert_sent = False
                
            else:
                print(f"[ANALYSIS] {symbol}: بدون سیگنال")
                
        except Exception as e:
            print(f"[ERROR] {symbol}: {e}")

# =====================================================================================
# حلقه اصلی
# =====================================================================================
def signal_loop():
    last_daily_report = None
    last_monthly_report = None
    
    while True:
        try:
            print("[LOOP] شروع یک دور جدید بررسی...")
            analyze_and_send()
            print("[LOOP] پایان دور بررسی، ۶۰ ثانیه مکث...")
            
            today = datetime.now().date()
            if last_daily_report != today:
                send_daily_report()
                last_daily_report = today
            
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
    send_telegram_message(
        "🤖 **ربات سیگنال‌دهی حرفه‌ای (SignalBot Pro) راه‌اندازی شد!**\n"
        "📊 در حال دریافت داده و تحلیل بازار...\n"
        "⚠️ **توجه:** این ربات فقط سیگنال ارسال می‌کند و هیچ معامله‌ای انجام نمی‌دهد.\n"
        "💡 **قابلیت‌های جدید:**\n"
        "• سیستم امتیازدهی ۳ سطحی (سبز، زرد، سفید)\n"
        "• واگرایی RSI، MACD و هیستوگرام\n"
        "• فیبوناچی ریتریسمنت (۰.۶۱۸ و ۰.۷۸۶)\n"
        "• پرایس‌اکشن (Pin Bar، Engulfing، کندل بزرگ)\n"
        "• هشدار آماده باش ۲ دقیقه قبل از سیگنال\n"
        "• پیگیری تارگت/استاپ\n"
        "• گزارش‌های روزانه و ماهانه"
    )
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("[STARTUP] وب‌سرور Flask روی پورت 10000 راه‌اندازی شد.")
    
    print("[STARTUP] شروع حلقه دریافت و تحلیل داده...")
    signal_loop()
