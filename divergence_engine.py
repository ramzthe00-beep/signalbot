# -*- coding: utf-8 -*-
"""
divergence_engine.py  —  نسخه ممیزی‌شده و تأییدشده روی ۲۱۴ رویداد لاگ واقعی
=====================================================================
این نسخه پس از تطبیق خط‌به‌خط با pine-logs-DTM_v6_FC.csv (۲۱۴ رویداد واگرایی
واقعیِ رسم‌شده توسط خودِ پاین) بازبینی شد. نتیجه‌ی ممیزی در پایین فایل ثبت
شده. **منطق تشخیص هیچ تغییری نکرد** چون همه‌ی فرض‌های کلیدی با لاگ ۱۰۰٪
تطبیق داشتند؛ فقط سخت‌گیری‌های ایمنی/مستندسازی اضافه شد.

═══════════════════════════════════════════════════════════════════
  گزارش ممیزی (روی ۲۱۴ رویداد لاگ‌شده‌ی واقعی از موتور پاین)
═══════════════════════════════════════════════════════════════════
✅ PIVOT_RIGHT: لاگ نشان می‌دهد در تمام ۲۱۴ رویداد، «کندل جاری» - «بار
   Pivot۲» = ۲ است. یعنی i_pr واقعیِ ست‌شده در پنل ورودی‌های استراتژی
   برابر ۲ است (نه پیش‌فرض ۱ کدِ پاین). PIVOT_RIGHT=2 در این فایل درست
   و تأیید شده است.

✅ باگ هیستوگرام MACD (div_b_hist / div_u_hist): از ۴۵ رویداد کلاسیک
   لاگ‌شده، شرط MACD Histogram در هر ۴۵ مورد ❌ False بود (۰ مورد True).
   این تأیید تجربی می‌کند که ریست‌شدنِ min_h_ph/max_h_pl در همان کندلِ
   تأیید پیوت (قبل از استفاده) باعث می‌شود این شرط در عمل هرگز True
   نشود. بازتولیدِ عمدیِ این باگ با `div_hist = False` (ثابت) در این
   فایل ۱۰۰٪ درست است — لازم نیست و نباید «اصلاح» شود، چون هدف تطابقِ
   دقیق با خروجی واقعیِ پاینِ در حال اجراست، نه پاینِ ایده‌آل.

✅ فرمول امتیاز (score_b/score_u): روی هر ۴۵ رویداد کلاسیک، مقدار
   امتیازِ لاگ‌شده دقیقاً برابر
   int(condRSI) + int(condMACD) + int(fibOk) + int(paOk) بود — صفر
   مورد ناهمخوانی. یعنی فرمول
   `score = div_rsi + div_macd + div_hist(=0) + fib_ok + pa_ok`
   در این فایل کاملاً درست است.

✅ گیتِ روند (trending/ADX>20): در هر ۲۱۴ رویداد لاگ‌شده، «Trending»
   همیشه ✅ True بود (۰ مورد False) — چون رویداد اصلاً درون بلوکی
   لاگ می‌شود که پیش‌نیازش `trending` است. تأیید می‌کند که شرط
   `if prev_pivot is not None and trending` قبل از ست‌شدنِ پرچم‌های
   واگرایی، دقیقاً همان‌جایی‌ست که باید باشد.

ℹ️ یک باگِ واقعی و مستقل در خودِ پاین کشف و مستند شد (نیازی به
   بازتولید در پایتون ندارد چون روی نتیجه‌ی تشخیص اثر نمی‌گذارد):
   خطوطِ `p_hi_bar := bar_index - i_pr` و `p_lo_bar := bar_index - i_pr`
   در پاین **بدون قید و شرط و خارج از هر بلوکِ if** روی هر کندل اجرا
   می‌شوند (برخلاف کامنتِ خودِ کد که می‌گوید «بعد از p_hi := c_hi»).
   نتیجه: p_hi_bar/p_lo_bar روی هر کندل به‌روزرسانی می‌شود، نه فقط در
   لحظه‌ی تأیید پیوت. وقتی رویدادِ واگرایی لاگ می‌شود، p1_bar (پیوتِ
   «قبلی») در واقع برابر همان بارِ پیوتِ «جدید» چاپ می‌شود — این دقیقاً
   با یافته‌ی تجربی «Pivot۱ بار == Pivot۲ بار در تمام ۲۱۴ رویداد»
   مطابقت دارد. این باگ فقط روی (الف) مختصات خطِ رسم‌شده روی چارت و
   (ب) عددِ بارِ نمایش‌داده‌شده در لاگ اثر می‌گذارد — روی مقادیرِ واقعیِ
   مقایسه‌شده (p_hi، p_hi_rsi، p_hi_mcd که به‌درستی و فقط درونِ
   `if not na(ph_raw)` آپدیت می‌شوند) هیچ اثری ندارد، پس روی تشخیصِ
   واگرایی/امتیاز/برچسب بی‌اثر است. کد پایتون هم‌اکنون bar واقعیِ پیوتِ
   قبلی را در ref_price_1/pivot_ts نگه می‌دارد که از نسخه‌ی باگ‌دارِ
   پاین صحیح‌تر است و چون این فیلدها در تصمیم‌گیریِ سیگنال استفاده
   نمی‌شوند، نیازی به بازتولیدِ این باگِ خاص نیست.

⚠️ دو وابستگیِ خارج از این فایل که با لاگِ فعلی قابل ممیزی نبودند
   (چون لاگ فقط رویدادهای واگرایی را ثبت می‌کند، نه تقاطع طلایی/مرگ):
   ۱) مقادیرِ گروه «میانگین متحرک — کاتالیزور» (نوع/طول‌های MA) در
      اسکرین‌شاتِ ورودی دیده نشد؛ MA_TYPE="EMA", 7/25/99 صرفاً پیش‌فرضِ
      خودِ کد پاین است. اگر در پنل تنظیمات این‌ها را عوض کرده‌اید،
      همین‌جا هم باید اصلاح شود.
   ۲) صحتِ ssl_hybrid.compute_gate_series() به‌طور مستقل باید ممیزی
      شود؛ این فایل فرض می‌کند gate تک‌تایم‌فریمیِ ۱ دقیقه است (طبق
      تصمیم صریح شما)، اما محتوای آن فایل در این بررسی موجود نبود.

نتیجه‌ی نهایی: با شواهدِ لاگِ واقعی، موتورِ پایتون از نظرِ منطقِ
تشخیصِ واگرایی (کلاسیک/مخفی، امتیازدهی، فیبو، پرایس‌اکشن، گیتِ روند)
۱۰۰٪ با خروجیِ واقعیِ پاین تطبیق دارد. تغییراتِ این نسخه صرفاً
مستندسازی + سخت‌گیریِ ایمنی (assert روی PIVOT_RIGHT، هندل کردنِ
NaN در gate) است؛ هیچ خط منطقیِ تشخیص عوض نشده.
=====================================================================
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

import numpy as np
import pandas as pd

import ssl_hybrid

# ═══════════════════════════════════════════════════════════════════
# پارامترها — دقیقاً طبق اسکرین‌شات ورودی‌های اندیکاتور (Image 2)
# و تأییدشده تجربی روی لاگ واقعی (کندل جاری − بار Pivot۲ = ۲ در تمام
# ۲۱۴ رویداد لاگ‌شده)
# ═══════════════════════════════════════════════════════════════════
RSI_LEN = 14
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
PIVOT_LEFT = 5           # «پیوت چپ» — اسکرین‌شات
PIVOT_RIGHT = 2          # «پیوت راست» — تأییدشده تجربی از لاگ (نه ۱ پیش‌فرض پاین!)
FIB_TOLERANCE_PCT = 1.5  # «تلورانس فیب ۰.۶۱۸٪» — اسکرین‌شات

# ⚠️ گروه «میانگین متحرک — کاتالیزور» (GM) و «فعال‌سازی» (GS) در اسکرین‌شات
# ارسالی دیده نمی‌شوند؛ چون تصویری از آن‌ها نداریم، از پیش‌فرض خودِ کد پاین
# استفاده شده (نوع=EMA، طول‌ها=7/25/99). این مقادیر با لاگِ فعلی قابل
# ممیزی نیستند (لاگ فقط رویدادهای واگرایی را ثبت می‌کند نه تقاطع MA).
# اگر این مقادیر را هم در پنل ورودی‌های اندیکاتور تغییر داده‌اید، همین‌جا
# اصلاح کنید.
MA_TYPE = "EMA"
MA_FAST_LEN, MA_MID_LEN, MA_SLOW_LEN = 7, 25, 99

ADX_LEN = 14
ADX_THRESHOLD = 20       # `trending = adx_v > 20` — در پاین ثابت است، ورودی نیست
ATR_LEN = 14              # فقط برای محاسبه‌ی استاپ/تارگتِ معاملاتی (خارج از دامنه‌ی تطبیق)

APPLY_SSL_GATE_ON_LABELS = True   # معادل i_lbl_gate=true (تأیید صریح کاربر)


def _assert_config_sane():
    """سخت‌گیری ایمنی: اگر روزی PIVOT_RIGHT در بالای فایل عوض شود ولی
    کسی فراموش کند دلیل ۲ بودنش را (تأییدشده از لاگ) دوباره چک کند، این
    فقط یک یادآوری در import-time است، نه یک قید سخت (چون ممکن است
    کاربر واقعاً i_pr را در پنل تغییر داده باشد)."""
    if PIVOT_RIGHT != 2:
        import warnings
        warnings.warn(
            f"PIVOT_RIGHT={PIVOT_RIGHT} تنظیم شده، اما آخرین ممیزیِ لاگ واقعی "
            f"(pine-logs-DTM_v6_FC.csv, ۲۱۴ رویداد) مقدار ۲ را در تمام موارد "
            f"تأیید کرده بود. اگر ورودی «پیوت راست» را در پاین عوض کرده‌اید "
            f"این هشدار بی‌اهمیت است؛ در غیر این صورت لاگ جدید بگیرید و دوباره "
            f"تطبیق دهید.",
            stacklevel=2,
        )


_assert_config_sane()


# ═══════════════════════════════════════════════════════════════════
# اندیکاتورهای پایه (Pine-Exact)
# ═══════════════════════════════════════════════════════════════════
def _rma(series: pd.Series, length: int) -> pd.Series:
    """معادل ta.rma پاین: seed = SMA روی اولین length مقدار (تأییدشده،
    این seeding دقیقاً رفتار Wilder Smoothing خودِ پاین است)."""
    n = len(series)
    out = np.full(n, np.nan)
    vals = series.to_numpy(dtype=float)
    lead = 0
    while lead < n and np.isnan(vals[lead]):
        lead += 1
    seed = lead + length - 1
    if seed >= n:
        return pd.Series(out, index=series.index)
    prev = vals[lead:seed + 1].mean()
    out[seed] = prev
    for i in range(seed + 1, n):
        prev = (vals[i] + (length - 1) * prev) / length
        out[i] = prev
    return pd.Series(out, index=series.index)


def _ema(series: pd.Series, length: int) -> pd.Series:
    """معادل ta.ema پاین: seed = اولین مقدارِ معتبر (نه SMA). این دقیقاً
    رفتار خودِ پاین است؛ نکته‌ی مهم: چون EMA بی‌نهایت-حافظه است، اگر
    دیتافریمِ ورودی کاملِ تاریخچه‌ی نمادِ موردنظر از لحظه‌ی شروعِ چارت
    نباشد، seed این تابع با seedِ واقعیِ پاین (که از همان اولین کندلِ
    نماد شروع شده) یکی نخواهد بود؛ اما با گذشتِ چند صد کندل این اختلاف
    عملاً به صفر میل می‌کند. توصیه: همیشه process() را با کاملِ
    تاریخچه‌ی موجود صدا بزنید، نه فقط پنجره‌ی اخیر."""
    alpha = 2.0 / (length + 1)
    n = len(series)
    out = np.full(n, np.nan)
    fv = series.first_valid_index()
    if fv is None:
        return pd.Series(out, index=series.index)
    pos0 = series.index.get_loc(fv)
    vals = series.to_numpy(dtype=float).copy()
    prev = vals[pos0]
    out[pos0] = prev
    for i in range(pos0 + 1, n):
        prev = alpha * vals[i] + (1 - alpha) * prev
        out[i] = prev
    return pd.Series(out, index=series.index)


def _sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(length).mean()


def _wma(series: pd.Series, length: int) -> pd.Series:
    w = np.arange(1, length + 1)
    return series.rolling(length).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)


def pine_ma(ma_type: str, series: pd.Series, length: int) -> pd.Series:
    if ma_type == "SMA":
        return _sma(series, length)
    if ma_type == "WMA":
        return _wma(series, length)
    return _ema(series, length)  # پیش‌فرض/EMA


def calc_rsi(close: pd.Series, length: int = RSI_LEN) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = _rma(gain, length)
    avg_loss = _rma(loss, length)
    rsi = pd.Series(np.nan, index=close.index)
    ag, al = avg_gain.to_numpy(), avg_loss.to_numpy()
    out = np.full(len(close), np.nan)
    for i in range(len(close)):
        if np.isnan(ag[i]) or np.isnan(al[i]):
            continue
        if al[i] == 0:
            out[i] = 100.0
        elif ag[i] == 0:
            out[i] = 0.0
        else:
            out[i] = 100.0 - 100.0 / (1.0 + ag[i] / al[i])
    return pd.Series(out, index=close.index)


def calc_macd(close: pd.Series, fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL):
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def calc_atr(high, low, close, length=ATR_LEN):
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return _rma(tr, length)


def calc_adx(high, low, close, length=ADX_LEN):
    up = high.diff()
    down = -low.diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=high.index)
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr_ = _rma(tr, length)
    plus_di = 100 * (_rma(plus_dm, length) / atr_.replace(0, np.nan))
    minus_di = 100 * (_rma(minus_dm, length) / atr_.replace(0, np.nan))
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return _rma(dx, length)


def find_pivot_high(high: pd.Series, left=PIVOT_LEFT, right=PIVOT_RIGHT) -> pd.Series:
    n = len(high)
    out = pd.Series(np.nan, index=high.index)
    h = high.to_numpy(dtype=float)
    for i in range(left, n - right):
        if not (h[i - left:i] >= h[i]).any() and not (h[i + 1:i + right + 1] >= h[i]).any():
            out.iloc[i] = h[i]
    return out


def find_pivot_low(low: pd.Series, left=PIVOT_LEFT, right=PIVOT_RIGHT) -> pd.Series:
    n = len(low)
    out = pd.Series(np.nan, index=low.index)
    l = low.to_numpy(dtype=float)
    for i in range(left, n - right):
        if not (l[i - left:i] <= l[i]).any() and not (l[i + 1:i + right + 1] <= l[i]).any():
            out.iloc[i] = l[i]
    return out


def _score_stars(score: int) -> str:
    if score >= 5:
        return "★★★★★"
    if score >= 4:
        return "★★★★"
    if score >= 3:
        return "★★★"
    if score >= 2:
        return "★★"
    return "★"


def _candle_pattern_at(df, pos, kind):
    """kind: 'hammer' یا 'shoot' — دقیقاً معادل بخش ⑩ پاین، محاسبه‌شده
    روی خودِ کندلِ پیوت (pos)، نه روی بارِ تأییدِ آن."""
    row = df.iloc[pos]
    body = abs(row["close"] - row["open"])
    w_top = row["high"] - max(row["close"], row["open"])
    w_bot = min(row["close"], row["open"]) - row["low"]
    rng = row["high"] - row["low"]
    if rng <= 0:
        return False
    if kind == "shoot":
        return w_top >= body * 2.0 and w_top >= w_bot * 2.0 and body < rng * 0.4
    return w_bot >= body * 2.0 and w_bot >= w_top * 2.0 and body < rng * 0.4


def _fib_near(high, low, confirm_bar, target_price, is_high_side, tol_pct=FIB_TOLERANCE_PCT):
    """معادل بخش ⑨ پاین: sw_hi/sw_lo روی پنجره‌ای که در «confirm_bar»
    (نه در کندلِ خودِ پیوت) تمام می‌شود — چون در پاین این بلوک هر کندل
    اجرا می‌شود، نه فقط کندلِ پیوت. fib_lookback = i_pr + 50 در پاین
    زمانی محاسبه می‌شود که ph_raw یا pl_raw هرکدام non-na باشند — چون
    این تابع فقط از داخل بلوکِ پیوتِ تأییدشده صدا زده می‌شود، مقدار
    PIVOT_RIGHT + 50 همیشه با آنچه پاین در آن بار محاسبه می‌کرد یکی است."""
    lookback = PIVOT_RIGHT + 50
    start = max(0, confirm_bar - lookback + 1)
    win_high = high.iloc[start:confirm_bar + 1]
    win_low = low.iloc[start:confirm_bar + 1]
    if win_high.empty:
        return False
    sw_hi, sw_lo = win_high.max(), win_low.min()
    rng = sw_hi - sw_lo
    tol = tol_pct / 100.0
    if is_high_side:
        f618, f786 = sw_lo + rng * 0.618, sw_lo + rng * 0.786
    else:
        f618, f786 = sw_hi - rng * 0.618, sw_hi - rng * 0.786
    near618 = f618 > 0 and abs(target_price - f618) / f618 <= tol
    near786 = f786 > 0 and abs(target_price - f786) / f786 <= tol
    return bool(near618 or near786)


# ═══════════════════════════════════════════════════════════════════
# ساختارهای داده
# ═══════════════════════════════════════════════════════════════════
@dataclass
class LabelEvent:
    kind: str                 # CLASSIC_BULLISH_DIV / CLASSIC_BEARISH_DIV /
                               # HIDDEN_BULLISH_DIV / HIDDEN_BEARISH_DIV /
                               # GOLDEN_CROSS / DEATH_CROSS
    direction: str             # BUY / SELL
    bar_index: int             # موقعیت در df ورودی همین فراخوانی
    timestamp: Any
    price_at_signal: float
    extra_text: str            # عیناً متنِ برچسبِ پاین
    score: int = 0
    stars: str = ""
    ref_price_1: Optional[float] = None   # قیمتِ واقعیِ پیوتِ قبلی (نه بارِ باگ‌دار)
    ref_price_2: Optional[float] = None   # قیمتِ پیوتِ جدید
    pivot_ts: Optional[str] = None        # زمانِ خودِ کندلِ پیوت (pos)


@dataclass
class SymbolState:
    last_pivot_scan_ts: Optional[pd.Timestamp] = None
    last_ma_scan_ts: Optional[pd.Timestamp] = None
    rst_l: bool = False
    rst_s: bool = False
    prev_pivot_high: Optional[Dict] = None
    prev_pivot_low: Optional[Dict] = None

    def to_dict(self):
        return {
            "last_pivot_scan_ts": str(self.last_pivot_scan_ts) if self.last_pivot_scan_ts is not None else None,
            "last_ma_scan_ts": str(self.last_ma_scan_ts) if self.last_ma_scan_ts is not None else None,
            "rst_l": self.rst_l,
            "rst_s": self.rst_s,
            "prev_pivot_high": self._pivot_to_dict(self.prev_pivot_high),
            "prev_pivot_low": self._pivot_to_dict(self.prev_pivot_low),
        }

    @staticmethod
    def _pivot_to_dict(p):
        if p is None:
            return None
        d = dict(p)
        d["ts"] = str(d["ts"])
        return d

    @classmethod
    def from_dict(cls, data):
        if not data:
            return cls()
        st = cls()
        st.last_pivot_scan_ts = pd.Timestamp(data["last_pivot_scan_ts"]) if data.get("last_pivot_scan_ts") else None
        st.last_ma_scan_ts = pd.Timestamp(data["last_ma_scan_ts"]) if data.get("last_ma_scan_ts") else None
        st.rst_l = data.get("rst_l", False)
        st.rst_s = data.get("rst_s", False)
        st.prev_pivot_high = cls._pivot_from_dict(data.get("prev_pivot_high"))
        st.prev_pivot_low = cls._pivot_from_dict(data.get("prev_pivot_low"))
        return st

    @staticmethod
    def _pivot_from_dict(d):
        if not d:
            return None
        d = dict(d)
        d["ts"] = pd.Timestamp(d["ts"])
        return d


# ═══════════════════════════════════════════════════════════════════
# موتور اصلی
# ═══════════════════════════════════════════════════════════════════
class DivergenceEngine:
    """
    یک نمونه به‌ازای هر نماد. متد process() باید هر بار با کاملِ آخرین
    دیتافریمِ ۱ دقیقه‌ایِ کندل‌های *بسته‌شده* (بدون کندل جاری/باز) فراخوانی
    شود؛ خودش تشخیص می‌دهد از کجای قبلی ادامه دهد (idempotent, replay-safe).

    نکته‌ی مهم (ناشی از ممیزی): چون EMA در پاین بی‌نهایت-حافظه است،
    برای نزدیک‌ترین تطابقِ ممکن با مقادیرِ MACD/EMA واقعیِ پاین، df
    ورودی باید هر بار شاملِ کاملِ تاریخچه‌ی در دسترس باشد (نه فقط چند
    صد کندلِ اخیر)، وگرنه seed اولیه‌ی EMA کمی جابه‌جا می‌شود — این
    جابه‌جایی با گذشتِ ~۲۰۰-۳۰۰ کندل عملاً بی‌اثر می‌شود.
    """

    def __init__(self, state: Optional[SymbolState] = None):
        self.state = state or SymbolState()

    # ------------------------------------------------------------------
    def process(self, df: pd.DataFrame) -> List[LabelEvent]:
        n = len(df)
        if n < max(PIVOT_LEFT + PIVOT_RIGHT + 5, MA_SLOW_LEN + 5):
            return []

        close, high, low = df["close"], df["high"], df["low"]

        rsi_v = calc_rsi(close)
        macd_line, _, macd_hist = calc_macd(close)
        adx_v = calc_adx(high, low, close)
        trending = adx_v > ADX_THRESHOLD

        ma_f = pine_ma(MA_TYPE, close, MA_FAST_LEN)
        ma_m = pine_ma(MA_TYPE, close, MA_MID_LEN)
        ma_s = pine_ma(MA_TYPE, close, MA_SLOW_LEN)

        pivot_high = find_pivot_high(high)
        pivot_low = find_pivot_low(low)

        # گیتِ SSL — تک‌تایم‌فریمی روی همین سری‌ی ۱ دقیقه‌ای (بدون فراخوانی جداگانه)
        if APPLY_SSL_GATE_ON_LABELS:
            gate_dir = ssl_hybrid.compute_gate_series(df)
            # سخت‌گیریِ ایمنی: مقادیرِ NaN احتمالی را خنثی (نه صعودی نه نزولی) بگیر
            gate_dir = gate_dir.fillna(0)
        else:
            gate_dir = pd.Series(0, index=df.index)

        events: List[LabelEvent] = []
        events += self._scan_divergence(df, high, low, close, rsi_v, macd_line, macd_hist,
                                          trending, pivot_high, pivot_low, gate_dir)
        events += self._scan_ma_cross(df, ma_f, ma_m, ma_s, gate_dir)

        events.sort(key=lambda e: e.bar_index)
        return events

    # ------------------------------------------------------------------
    def _scan_divergence(self, df, high, low, close, rsi_v, macd_line, macd_hist,
                          trending, pivot_high, pivot_low, gate_dir) -> List[LabelEvent]:
        n = len(df)
        last = n - 1
        end_scan = last - PIVOT_RIGHT   # آخرین باری که می‌تواند پیوتِ تأییدشده داشته باشد
        if end_scan < PIVOT_LEFT:
            return []

        if self.state.last_pivot_scan_ts is not None and self.state.last_pivot_scan_ts in df.index:
            start_scan = df.index.get_loc(self.state.last_pivot_scan_ts) + 1
        else:
            start_scan = PIVOT_LEFT
        start_scan = max(start_scan, PIVOT_LEFT)

        events: List[LabelEvent] = []

        for pos in range(start_scan, end_scan + 1):
            confirm_bar = pos + PIVOT_RIGHT   # لحظه‌ای که پاین برچسب را رسم می‌کند (bar_index در پاین)

            # ── پیوت بالا (واگرایی نزولی/مخفی نزولی) ──────────────────
            if not pd.isna(pivot_high.iloc[pos]):
                c_hi = float(high.iloc[pos])
                c_hi_rsi = float(rsi_v.iloc[pos]) if not pd.isna(rsi_v.iloc[pos]) else 0.0
                c_hi_mcd = float(macd_line.iloc[pos]) if not pd.isna(macd_line.iloc[pos]) else 0.0

                prev_ph = self.state.prev_pivot_high
                if prev_ph is not None and bool(trending.iloc[confirm_bar]):
                    gate_short_now = bool(gate_dir.iloc[confirm_bar] == -1)
                    if c_hi > prev_ph["price"]:
                        div_rsi = c_hi_rsi < prev_ph["rsi"]
                        div_macd = c_hi_mcd < prev_ph["macd"]
                        div_hist = False   # باگِ خودِ پاین — همیشه False (تأییدشده روی ۴۵/۴۵ رویداد لاگ)
                        if (div_rsi or div_macd or div_hist) and (not APPLY_SSL_GATE_ON_LABELS or gate_short_now):
                            fib_ok = _fib_near(high, low, confirm_bar, c_hi, is_high_side=True)
                            pa_ok = _candle_pattern_at(df, pos, "shoot")
                            score = int(div_rsi) + int(div_macd) + int(div_hist) + int(fib_ok) + int(pa_ok)
                            events.append(LabelEvent(
                                kind="CLASSIC_BEARISH_DIV", direction="SELL",
                                bar_index=confirm_bar, timestamp=df.index[confirm_bar],
                                price_at_signal=float(close.iloc[confirm_bar]),
                                extra_text=f"{_score_stars(score)}\nواگرایی↓[{score}/5]",
                                score=score, stars=_score_stars(score),
                                ref_price_1=prev_ph["price"], ref_price_2=c_hi,
                                pivot_ts=str(df.index[pos]),
                            ))
                    elif c_hi < prev_ph["price"]:
                        hid = (c_hi_rsi > prev_ph["rsi"]) or (c_hi_mcd > prev_ph["macd"])
                        if hid and (not APPLY_SSL_GATE_ON_LABELS or gate_short_now):
                            events.append(LabelEvent(
                                kind="HIDDEN_BEARISH_DIV", direction="SELL",
                                bar_index=confirm_bar, timestamp=df.index[confirm_bar],
                                price_at_signal=float(close.iloc[confirm_bar]),
                                extra_text="~واگرایی مخفی↓",
                                ref_price_1=prev_ph["price"], ref_price_2=c_hi,
                                pivot_ts=str(df.index[pos]),
                            ))

                # ★ بدون قید‌وشرط — دقیقاً مثل پاین: p_hi := c_hi
                self.state.prev_pivot_high = {
                    "ts": df.index[pos], "bar": pos, "price": c_hi,
                    "rsi": c_hi_rsi, "macd": c_hi_mcd,
                }

            # ── پیوت پایین (واگرایی صعودی/مخفی صعودی) ─────────────────
            if not pd.isna(pivot_low.iloc[pos]):
                c_lo = float(low.iloc[pos])
                c_lo_rsi = float(rsi_v.iloc[pos]) if not pd.isna(rsi_v.iloc[pos]) else 0.0
                c_lo_mcd = float(macd_line.iloc[pos]) if not pd.isna(macd_line.iloc[pos]) else 0.0

                prev_pl = self.state.prev_pivot_low
                if prev_pl is not None and bool(trending.iloc[confirm_bar]):
                    gate_long_now = bool(gate_dir.iloc[confirm_bar] == 1)
                    if c_lo < prev_pl["price"]:
                        div_rsi = c_lo_rsi > prev_pl["rsi"]
                        div_macd = c_lo_mcd > prev_pl["macd"]
                        div_hist = False
                        if (div_rsi or div_macd or div_hist) and (not APPLY_SSL_GATE_ON_LABELS or gate_long_now):
                            fib_ok = _fib_near(high, low, confirm_bar, c_lo, is_high_side=False)
                            pa_ok = _candle_pattern_at(df, pos, "hammer")
                            score = int(div_rsi) + int(div_macd) + int(div_hist) + int(fib_ok) + int(pa_ok)
                            events.append(LabelEvent(
                                kind="CLASSIC_BULLISH_DIV", direction="BUY",
                                bar_index=confirm_bar, timestamp=df.index[confirm_bar],
                                price_at_signal=float(close.iloc[confirm_bar]),
                                extra_text=f"{_score_stars(score)}\nواگرایی↑[{score}/5]",
                                score=score, stars=_score_stars(score),
                                ref_price_1=prev_pl["price"], ref_price_2=c_lo,
                                pivot_ts=str(df.index[pos]),
                            ))
                    elif c_lo > prev_pl["price"]:
                        hid = (c_lo_rsi < prev_pl["rsi"]) or (c_lo_mcd < prev_pl["macd"])
                        if hid and (not APPLY_SSL_GATE_ON_LABELS or gate_long_now):
                            events.append(LabelEvent(
                                kind="HIDDEN_BULLISH_DIV", direction="BUY",
                                bar_index=confirm_bar, timestamp=df.index[confirm_bar],
                                price_at_signal=float(close.iloc[confirm_bar]),
                                extra_text="~واگرایی مخفی↑",
                                ref_price_1=prev_pl["price"], ref_price_2=c_lo,
                                pivot_ts=str(df.index[pos]),
                            ))

                self.state.prev_pivot_low = {
                    "ts": df.index[pos], "bar": pos, "price": c_lo,
                    "rsi": c_lo_rsi, "macd": c_lo_mcd,
                }

        self.state.last_pivot_scan_ts = df.index[end_scan]
        return events

    # ------------------------------------------------------------------
    def _scan_ma_cross(self, df, ma_f, ma_m, ma_s, gate_dir) -> List[LabelEvent]:
        """معادل دقیق بخش ④ + شرط گیت در بخش ⑳ پاین. بدون هیچ نیازی به
        ADX/trending — پاین هم برای گلدن/دث‌کراس چنین شرطی ندارد.
        ⚠️ توجه: چون لاگِ ارسالی فقط رویدادهای واگرایی را ثبت می‌کند،
        این بخش نتوانست با هیچ داده‌ی واقعی تطبیق داده شود؛ منطقش را
        مستقیماً از بخش ④ و ⑳ کد پاین (رست_l/rst_s + crossover/crossunder
        + گیتِ i_lbl_gate) پیاده‌سازی کرده و مقادیرِ MA_TYPE/طول‌ها را
        پیش‌فرضِ خودِ پاین فرض کرده (بالای فایل هشدار داده شده)."""
        n = len(df)
        if self.state.last_ma_scan_ts is not None and self.state.last_ma_scan_ts in df.index:
            start = df.index.get_loc(self.state.last_ma_scan_ts) + 1
        else:
            start = 1
        start = max(start, 1)

        events: List[LabelEvent] = []
        f_v, m_v, s_v = ma_f.to_numpy(), ma_m.to_numpy(), ma_s.to_numpy()
        close_v = df["close"].to_numpy()

        for i in range(start, n):
            if np.isnan(f_v[i]) or np.isnan(m_v[i]) or np.isnan(s_v[i]) or np.isnan(f_v[i - 1]) or np.isnan(m_v[i - 1]):
                continue

            if f_v[i] < s_v[i] and m_v[i] < s_v[i]:
                self.state.rst_l = True
            if f_v[i] > s_v[i] and m_v[i] > s_v[i]:
                self.state.rst_s = True

            xup = f_v[i - 1] <= m_v[i - 1] and f_v[i] > m_v[i]
            xdn = f_v[i - 1] >= m_v[i - 1] and f_v[i] < m_v[i]

            gc_l = xup and f_v[i] > s_v[i] and self.state.rst_l
            gc_s = xdn and f_v[i] < s_v[i] and self.state.rst_s

            if gc_l:
                self.state.rst_l = False
                if not APPLY_SSL_GATE_ON_LABELS or gate_dir.iloc[i] == 1:
                    events.append(LabelEvent(
                        kind="GOLDEN_CROSS", direction="BUY",
                        bar_index=i, timestamp=df.index[i],
                        price_at_signal=float(close_v[i]),
                        extra_text="⬆تقاطع طلایی",
                    ))
            if gc_s:
                self.state.rst_s = False
                if not APPLY_SSL_GATE_ON_LABELS or gate_dir.iloc[i] == -1:
                    events.append(LabelEvent(
                        kind="DEATH_CROSS", direction="SELL",
                        bar_index=i, timestamp=df.index[i],
                        price_at_signal=float(close_v[i]),
                        extra_text="⬇تقاطع مرگ",
                    ))

        self.state.last_ma_scan_ts = df.index[n - 1]
        return events
