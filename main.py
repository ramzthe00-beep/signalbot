# -*- coding: utf-8 -*-
"""
main.py — DTM v6·FC Bot (نسخه‌ی اصلاح‌شده — سازگار با exchange_client.py جدید)
=====================================================================
این فایل فقط «چسبِ» پروژه است: داده می‌گیرد (exchange_client)، به موتور
تشخیص می‌دهد (divergence_engine که خودش ssl_hybrid را برای گیت به‌کار
می‌برد)، نتیجه را به تلگرام می‌فرستد (telegram_logger) و در صورت اتصال
صرافی، معامله می‌کند.

★ طبق تأکید صریح کاربر: تنها بخشی که باید «۱۰۰٪ منطبق با پاین» باشد
منطقِ ظهورِ برچسبِ واگرایی/تقاطع است (divergence_engine.py + ssl_hybrid.py).
منطقِ اینجا (حجم معامله، استاپ/تارگت، ریسک‌فری و ...) عمداً ساده و
مستقل نگه داشته شده چون کاربر گفته «کاری به منطق ورود ندارم».

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  تغییرات این نسخه نسبت به قبل (به‌دلیل تغییرِ exchange_client.py):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ۱) امضای fetch_ohlcv عوض شده: قبلاً (symbol, "1m", limit) بود، الان
     (symbol, timeframe="1") است و history_bars از سازنده‌ی MarketData
     می‌آید. هر فراخوانیِ قدیمی این‌جا آپدیت شد.

  ۲) 🔴 رفع یک ناهماهنگیِ واقعی: divergence_engine.py رویِ لاگِ واقعیِ
     پاین (نماد BINANCE:ETHUSDT — یعنی چارتِ پاین از فیدِ بایننس
     می‌خواند) ممیزی و «۱۰۰٪ منطبق» تأیید شده بود. اما نسخه‌ی قبلیِ این
     فایل، df ورودیِ engine.process() را از market.fetch_ohlcv() یعنی
     صرافیِ TheTrueTrade می‌گرفت — نه بایننس. این یعنی ادعای «Pine-Exact»
     دیگر برقرار نبود، چون کندل‌های TheTrueTrade با کندل‌های بایننس (که
     خودِ پاین رویشان اجرا شده) لزوماً یکی نیستند.
     رفع شد با همان الگویی که در پروژه‌ی موازیِ کاربر (fetch_ohlcv_binance
     برای سیگنال + fetch_ohlcv برای اجرا) دیده شد:
       • df_signal = market.fetch_ohlcv_binance(...)  → ورودیِ موتور تشخیص
       • لنگرِ قیمتِ ورود/اجرا از market.fetch_current_price(...) که خودِ
         TheTrueTrade است (چون سفارش واقعاً رویِ آن صرافی اجرا می‌شود و
         قیمتِ ورودِ واقعی باید مالِ همان بازار باشد، نه بایننس).
"""

import os
import json
import time
import threading
import logging

import pandas as pd
from flask import Flask

import exchange_client as ex
import divergence_engine as de
import ssl_hybrid  # noqa: F401  (وابستگیِ غیرمستقیم از طریق divergence_engine)
from telegram_logger import TelegramNotifier, setup_logging, format_iran_time, format_iran_date

logger = setup_logging()

# ═══════════════════════════════════════════════════════════════════
# تنظیمات محیطی
# ═══════════════════════════════════════════════════════════════════
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
BASE_URL = os.getenv("BASE_URL", "https://apiv2.thetruetrade.io")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not API_KEY or not API_SECRET:
    raise RuntimeError("API_KEY / API_SECRET باید به‌عنوان متغیر محیطی ست شوند.")
if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID باید به‌عنوان متغیر محیطی ست شوند.")

STATE_FILE = "engine_state.json"
HISTORY_FILE = "trades_history.json"
HISTORY_BARS = 500          # کندل‌های ۱ دقیقه‌ای برای هر چرخه‌ی تحلیل
LOOP_SLEEP_SEC = 60
SIGNAL_TIMEFRAME = "1"      # ← فرمتِ جدید: عددِ خامِ دقیقه (نه "1m")

# ── تنظیمات معاملاتی (خارج از دامنه‌ی «تطابق ۱۰۰٪ با پاین») ──────────
TARGET_RISK_USDT = 3.5
TARGET_RR = 3.0
STOP_BUFFER_TICKS = 5
CROSS_ATR_STOP_MULT = 2.0

notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, logger=logger)
market = ex.MarketData(BASE_URL, history_bars=HISTORY_BARS)
exchange = ex.PrivateExchange(API_KEY, API_SECRET, BASE_URL)


# ═══════════════════════════════════════════════════════════════════
# پایداری وضعیت (State persistence)
# ═══════════════════════════════════════════════════════════════════
def load_engines():
    engines = {s: de.DivergenceEngine() for s in ex.SYMBOLS}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
            for s in ex.SYMBOLS:
                if s in data:
                    engines[s] = de.DivergenceEngine(de.SymbolState.from_dict(data[s]))
            logger.info(f"[STATE] بارگذاری شد از {STATE_FILE}")
        except Exception as e:
            logger.error(f"[STATE] خطا در بارگذاری: {e}")
    return engines


def save_engines(engines):
    data = {s: engines[s].state.to_dict() for s in ex.SYMBOLS}
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE) as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_history(h):
    with open(HISTORY_FILE, "w") as f:
        json.dump(h, f, indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════
# محاسبه‌ی استاپ/تارگت (غیرِ Pine-exact — فقط زیرساخت اجرای معامله)
# ═══════════════════════════════════════════════════════════════════
def compute_stop_target(event: de.LabelEvent, entry_price: float, atr_now: float, symbol: str):
    tick = ex.TICK_SIZES.get(symbol.upper(), 0.01)
    buf = tick * STOP_BUFFER_TICKS

    if event.kind in ("CLASSIC_BEARISH_DIV", "HIDDEN_BEARISH_DIV"):
        highest_peak = max(event.ref_price_1, event.ref_price_2)
        stop = highest_peak + buf
        risk = stop - entry_price
        if risk <= 0:
            return None, None
        target = entry_price - risk * TARGET_RR
        return stop, target

    if event.kind in ("CLASSIC_BULLISH_DIV", "HIDDEN_BULLISH_DIV"):
        lowest_valley = min(event.ref_price_1, event.ref_price_2)
        stop = lowest_valley - buf
        risk = entry_price - stop
        if risk <= 0:
            return None, None
        target = entry_price + risk * TARGET_RR
        return stop, target

    if event.kind == "GOLDEN_CROSS":
        stop = entry_price - atr_now * CROSS_ATR_STOP_MULT
        risk = entry_price - stop
        target = entry_price + risk * TARGET_RR
        return stop, target

    if event.kind == "DEATH_CROSS":
        stop = entry_price + atr_now * CROSS_ATR_STOP_MULT
        risk = stop - entry_price
        target = entry_price - risk * TARGET_RR
        return stop, target

    return None, None


# ═══════════════════════════════════════════════════════════════════
# پیام تلگرام دقیقاً با متنِ برچسبِ پاین
# ═══════════════════════════════════════════════════════════════════
LABEL_TITLE = {
    "CLASSIC_BEARISH_DIV": "🔴 واگرایی کلاسیک نزولی",
    "CLASSIC_BULLISH_DIV": "🟢 واگرایی کلاسیک صعودی",
    "HIDDEN_BEARISH_DIV": "🟠 واگرایی مخفی نزولی",
    "HIDDEN_BULLISH_DIV": "🔵 واگرایی مخفی صعودی",
    "GOLDEN_CROSS": "⬆️ تقاطع طلایی",
    "DEATH_CROSS": "⬇️ تقاطع مرگ",
}


def format_signal_message(symbol, event: de.LabelEvent, entry=None, stop=None, target=None,
                           signal_number=None, informational=False):
    dir_txt = "LONG" if event.direction == "BUY" else "SHORT"
    dir_emoji = "🟢" if event.direction == "BUY" else "🔴"
    title = LABEL_TITLE.get(event.kind, event.kind)
    tag = f" #Signal_{signal_number}" if signal_number else ""

    lines = [
        f"{dir_emoji} *{title}* — `{symbol}`{tag}",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"🔸 جهت: *{dir_txt}*",
        f"📝 برچسبِ پاین: {event.extra_text.replace(chr(10), ' | ')}",
        f"🕐 زمانِ دقیقِ ظهور برچسب (بایننس): `{format_iran_time(event.timestamp)}`",
    ]
    if entry is not None and stop is not None and target is not None:
        prec = ex.PRICE_PRECISION.get(symbol, 2)
        lines += [
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"📍 ورود (لنگرِ صرافیِ اجرا): `{entry:.{prec}f}`",
            f"🛑 حد ضرر: `{stop:.{prec}f}`",
            f"🎯 حد سود: `{target:.{prec}f}`",
        ]
    if informational:
        lines.append("⚠️ *حالت اولین اجرا — فقط نمایشی، بدون معامله*")
    lines += ["━━━━━━━━━━━━━━━━━━━━━━", f"🕒 {format_iran_time()}"]
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# پیگیری معاملات باز (TP/SL/ریسک‌فری)
# ═══════════════════════════════════════════════════════════════════
def track_open_trades():
    history = load_history()
    open_trades = [t for t in history if t.get("result") is None]
    if not open_trades:
        return
    changed = False
    for t in open_trades:
        symbol, direction = t["symbol"], t["direction"]
        cp = market.fetch_current_price(symbol)   # قیمتِ لحظه‌ایِ صرافیِ اجرا (TheTrueTrade)
        if cp is None:
            continue
        entry, stop, target = t["entry"], t["stop"], t["target"]

        hit_tp = (cp >= target) if direction == "BUY" else (cp <= target)
        hit_sl = (cp <= stop) if direction == "BUY" else (cp >= stop)

        if hit_tp:
            t["result"] = "TAKE_PROFIT"
            t["close_price"] = cp
            t["close_time"] = format_iran_time()
            changed = True
            notifier.send(f"🎯 *حد سود فعال شد* — `{symbol}` #{t.get('signal_number','?')}\n🕒 {format_iran_time()}")
        elif hit_sl:
            t["result"] = "STOP_LOSS"
            t["close_price"] = cp
            t["close_time"] = format_iran_time()
            changed = True
            notifier.send(f"💔 *حد ضرر فعال شد* — `{symbol}` #{t.get('signal_number','?')}\n🕒 {format_iran_time()}")
        elif exchange.connected and not t.get("risk_free_done") and t.get("position_id"):
            risk_dist = abs(entry - stop)
            if risk_dist > 0:
                hit_1r = (cp >= entry + risk_dist) if direction == "BUY" else (cp <= entry - risk_dist)
                if hit_1r:
                    try:
                        exchange.update_position_sl(t["position_id"], symbol, entry, take_profit=target)
                        t["risk_free_done"] = True
                        t["stop"] = entry
                        changed = True
                        notifier.send(f"🛡️ *ریسک‌فری فعال شد* — `{symbol}` #{t.get('signal_number','?')}\n🕒 {format_iran_time()}")
                    except Exception as e:
                        logger.error(f"[RISK-FREE] {symbol}: {e}")
    if changed:
        save_history(history)


# ═══════════════════════════════════════════════════════════════════
# چرخه‌ی اصلی
# ═══════════════════════════════════════════════════════════════════
_first_run = True
_signal_counter = 0


def _next_signal_number():
    global _signal_counter
    _signal_counter += 1
    return _signal_counter


def process_symbol(symbol, engine: de.DivergenceEngine):
    global _first_run

    # ── منبع سیگنال: بایننس (همان چیزی که divergence_engine.py رویش
    #    ممیزی و ۱۰۰٪ منطبق تأیید شده — نماد لاگ پاین BINANCE:ETHUSDT بود) ──
    df_signal = market.fetch_ohlcv_binance(symbol, SIGNAL_TIMEFRAME)
    if df_signal is None or df_signal.empty:
        logger.warning(f"[SKIP] {symbol}: داده‌ی بایننس دریافت نشد")
        return

    events = engine.process(df_signal)
    if not events:
        return

    if _first_run and len(events) > 2:
        logger.info(f"[FIRST_RUN] {symbol}: {len(events)} رویداد یافت شد — فقط ۲ تای آخر نمایش داده می‌شود")
        events = events[-2:]

    atr_series = de.calc_atr(df_signal["high"], df_signal["low"], df_signal["close"])
    balance = exchange.fetch_balance() or 0.0
    history = load_history()

    for event in events:
        # ── لنگرِ قیمتِ ورودِ واقعی: از خودِ صرافیِ اجرا (TheTrueTrade)،
        #    نه از قیمتِ بایننس در لحظه‌ی رویداد — چون سفارش واقعاً روی
        #    همان صرافی اجرا می‌شود و قیمت بازار می‌تواند کمی فرق داشته باشد.
        #    اگر به هر دلیلی قیمتِ لحظه‌ای صرافیِ اجرا در دسترس نبود،
        #    برای امنیت به همان قیمتِ لحظه‌ی رویداد در بایننس برمی‌گردیم. ──
        exec_anchor = market.fetch_current_price(symbol)
        entry_price = exec_anchor if exec_anchor is not None else event.price_at_signal
        if exec_anchor is None:
            logger.warning(
                f"[ANCHOR] {symbol}: قیمتِ لحظه‌ایِ صرافیِ اجرا در دسترس نبود — "
                f"از قیمتِ بایننس ({event.price_at_signal}) به‌عنوان جایگزین استفاده شد."
            )

        atr_now = float(atr_series.iloc[event.bar_index]) if not pd.isna(atr_series.iloc[event.bar_index]) else 0.0
        stop, target = compute_stop_target(event, entry_price, atr_now, symbol)

        if _first_run or stop is None or target is None:
            notifier.send(format_signal_message(symbol, event, entry_price, stop, target, informational=True))
            continue

        signal_number = _next_signal_number()
        notifier.send(format_signal_message(symbol, event, entry_price, stop, target, signal_number))

        prec = ex.PRICE_PRECISION.get(symbol, 2)
        stop_pct = abs(entry_price - stop) / entry_price
        leverage = ex.LEVERAGE_MAP.get(symbol, 50)
        needed_lev = 1.0 / stop_pct if stop_pct > 0 else leverage
        used_lev = min(needed_lev, leverage)
        required_capital = TARGET_RISK_USDT / stop_pct / used_lev if stop_pct > 0 else TARGET_RISK_USDT
        capital = required_capital if balance >= required_capital else balance * 0.98

        trade = {
            "symbol": symbol, "direction": event.direction,
            "entry": round(entry_price, prec), "stop": round(stop, prec), "target": round(target, prec),
            "signal_time": format_iran_time(event.timestamp), "result": None,
            "type": event.kind, "capital": capital, "leverage": int(used_lev),
            "signal_number": signal_number, "position_id": None, "risk_free_done": False,
        }
        history.append(trade)
        save_history(history)

        if exchange.connected:
            try:
                side = "BUY" if event.direction == "BUY" else "SELL"
                result = exchange.create_order(symbol, side, capital, int(used_lev), stop, target)
                trade["position_id"] = result.get("position_id")
                save_history(history)
                notifier.send(
                    f"✅ *سفارش ثبت شد* — `{symbol}` #{signal_number}\n"
                    f"💰 {capital:.{prec}f} USDT | 🔧 {int(used_lev)}x\n"
                    f"🕒 {format_iran_time()}"
                )
            except Exception as e:
                logger.error(f"[ORDER] {symbol}: {e}")
                notifier.send(f"❌ *خطا در ثبت سفارش* — `{symbol}` #{signal_number}\n📝 {str(e)[:200]}")


def analyze_and_execute(engines):
    global _first_run
    conn = exchange.test_connection()
    if not hasattr(analyze_and_execute, "_last_conn"):
        analyze_and_execute._last_conn = conn
        notifier.send(f"📡 وضعیت صرافی: {'✅ متصل' if conn else '⚠️ قطع'}\n🕒 {format_iran_time()}")
    elif analyze_and_execute._last_conn != conn:
        analyze_and_execute._last_conn = conn
        notifier.send(f"🔄 تغییر وضعیت صرافی: {'✅ متصل شد' if conn else '⚠️ قطع شد'}\n🕒 {format_iran_time()}")

    track_open_trades()

    for symbol in ex.SYMBOLS:
        try:
            process_symbol(symbol, engines[symbol])
        except Exception as e:
            logger.error(f"[SYMBOL] {symbol}: {e}", exc_info=True)

    save_engines(engines)
    if _first_run:
        _first_run = False
        logger.info("[FIRST_RUN] پایان یافت — بات وارد حالت عادی می‌شود")


def main_loop():
    engines = load_engines()
    notifier.send(
        f"🤖 *DTM Bot — آنلاین*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧠 سیگنال‌ها: واگرایی کلاسیک/مخفی + تقاطع طلایی/مرگ (Pine-Exact)\n"
        f"📡 منبعِ دادهٔ سیگنال: بایننس (اسپات، عمومی)\n"
        f"💱 صرافیِ اجرا: TheTrueTrade\n"
        f"🔷 گیت SSL Hybrid: تک‌تایم‌فریمی روی ۱ دقیقه\n"
        f"⚙️ Pivot: {de.PIVOT_LEFT}/{de.PIVOT_RIGHT} | RSI({de.RSI_LEN}) | MACD({de.MACD_FAST},{de.MACD_SLOW},{de.MACD_SIGNAL})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n🕒 {format_iran_time()}"
    )
    while True:
        try:
            logger.info(f"[LOOP] {format_iran_time()}")
            analyze_and_execute(engines)
            time.sleep(LOOP_SLEEP_SEC)
        except Exception as e:
            logger.error(f"[LOOP] {e}", exc_info=True)
            time.sleep(LOOP_SLEEP_SEC)


app = Flask(__name__)


@app.route("/")
def health():
    return "OK", 200


if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000), daemon=True).start()
    main_loop()
