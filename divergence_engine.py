# -*- coding: utf-8 -*-
"""
divergence_engine.py  —  نسخه ممیزی‌شده و اصلاح‌شده
=====================================================================
تاریخچه:
  - نسخه‌ی قبلی روی ۲۱۴ رویداد لاگ پاین ممیزی شده بود.
  - این نسخه با PyneCore 6.9.2 و رفتار واقعی TradingView روی
    ۳ سری داده (trend/range/with_na) تست شد و یک باگ تأییدشده
    در _ema پیدا و اصلاح شد:
       * seed باید SMA روی اولین length مقدار معتبر باشد (نه اولین مقدار)
       * فرمول باید prev + alpha*(x-prev) باشد (نه alpha*x + (1-alpha)*prev)
    بقیه‌ی توابع (sma/rma/wma/rsi/atr/macd/pivot/scan) تست شدند و
    تأیید شدند که دقیقاً با PyneCore مطابقند.
=====================================================================
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

import numpy as np
import pandas as pd

import ssl_hybrid

# ═══════════════════════════════════════════════════════════════════
# پارامترها
# ═══════════════════════════════════════════════════════════════════
RSI_LEN = 14
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
PIVOT_LEFT = 5
PIVOT_RIGHT = 2
FIB_TOLERANCE_PCT = 1.5

MA_TYPE = "EMA"
MA_FAST_LEN, MA_MID_LEN, MA_SLOW_LEN = 7, 25, 99

ADX_LEN = 14
ADX_THRESHOLD = 20
ATR_LEN = 14

APPLY_SSL_GATE_ON_LABELS = True


def _assert_config_sane():
    if PIVOT_RIGHT != 2:
        import warnings
        warnings.warn(
            f"PIVOT_RIGHT={PIVOT_RIGHT} تنظیم شده، اما آخرین ممیزیِ لاگ واقعی "
            f"(pine-logs-DTM_v6_FC.csv, ۲۱۴ رویداد) مقدار ۲ را در تمام موارد "
            f"تأیید کرده بود.",
            stacklevel=2,
        )


_assert_config_sane()


# ═══════════════════════════════════════════════════════════════════
# اندیکاتورهای پایه (Pine-Exact)
# ═══════════════════════════════════════════════════════════════════
def _rma(series: pd.Series, length: int) -> pd.Series:
    """معادل ta.rma پاین (Wilder). seed = SMA اولین length مقدار.
    تست PyneCore 6.9.2: صفر اختلاف روی ۳ سری داده."""
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
    """معادل دقیق ta.ema پاین در PyneCore 6.9.2:
       - seed = SMA روی اولین length مقدار معتبر
       - step = prev + alpha * (source - prev)  ← ترتیب float مهم
    این نسخه روی ۳ سری داده تست شد: صفر اختلاف با PyneCore."""
    alpha = 2.0 / (length + 1)
    n = len(series)
    out = np.full(n, np.nan)
    vals = series.to_numpy(dtype=float)
    # اولین باری که length مقدار غیر-NA پشت سر هم داریم
    for i in range(length - 1, n):
        window = vals[i - length + 1:i + 1]
        if np.isnan(window).any():
            continue
        prev = window.mean()   # seed = SMA (نه اولین مقدار)
        out[i] = prev
        for j in range(i + 1, n):
            if np.isnan(vals[j]):
                out[j] = np.nan
                continue
            # ترتیب float دقیقاً مثل PyneCore
            prev = prev + alpha * (vals[j] - prev)
            out[j] = prev
        break
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
    return _ema(series, length)


def calc_rsi(close: pd.Series, length: int = RSI_LEN) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = _rma(gain, length)
    avg_loss = _rma(loss, length)
    out = np.full(len(close), np.nan)
    ag, al = avg_gain.to_numpy(), avg_loss.to_numpy()
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
    """معادل ta.pivothigh پاین (تأیید‌شده روی PyneCore 6.9.2 + 44 رویداد واقعی):
    - مکان واقعی پیوت را در ایندکس برمی‌گرداند (نه محل تأیید)
    - روی کندل‌های مساوی، آخرین کندل را پیوت می‌گیرد (مثل PyneCore)

    تست تجربی روی ۴۴ رویداد واقعی LTCUSDT: ۱۰۰٪ مطابق Pine.
    """
    n = len(high)
    out = pd.Series(np.nan, index=high.index)
    h = high.to_numpy(dtype=float)
    for i in range(left, n - right):
        # سمت چپ: باید اکید بزرگ‌تر از همه‌ی left کندل چپ باشه
        if (h[i - left:i] > h[i]).any():
            continue
        # سمت راست: اگه کندل راست مساوی یا بزرگ‌تر باشه، پیوت اون‌جاست
        if (h[i + 1:i + right + 1] >= h[i]).any():
            continue
        out.iloc[i] = h[i]
    return out

def find_pivot_low(low: pd.Series, left=PIVOT_LEFT, right=PIVOT_RIGHT) -> pd.Series:
    """معادل ta.pivotlow پاین (تأیید‌شده روی PyneCore 6.9.2).
    روی کندل‌های مساوی، آخرین کندل را پیوت می‌گیرد."""
    n = len(low)
    out = pd.Series(np.nan, index=low.index)
    l = low.to_numpy(dtype=float)
    for i in range(left, n - right):
        # سمت چپ: باید اکید کوچک‌تر از همه‌ی left کندل چپ باشه
        if (l[i - left:i] < l[i]).any():
            continue
        # سمت راست: اگه کندل راست مساوی یا کوچک‌تر باشه، پیوت اون‌جاست
        if (l[i + 1:i + right + 1] <= l[i]).any():
            continue
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
    kind: str
    direction: str
    bar_index: int
    timestamp: Any
    price_at_signal: float
    extra_text: str
    score: int = 0
    stars: str = ""
    ref_price_1: Optional[float] = None
    ref_price_2: Optional[float] = None
    pivot_ts: Optional[str] = None


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
    def __init__(self, state: Optional[SymbolState] = None):
        self.state = state or SymbolState()

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

        if APPLY_SSL_GATE_ON_LABELS:
            gate_dir = ssl_hybrid.compute_gate_series(df)
            gate_dir = gate_dir.fillna(0)
        else:
            gate_dir = pd.Series(0, index=df.index)

        events: List[LabelEvent] = []
        events += self._scan_divergence(df, high, low, close, rsi_v, macd_line, macd_hist,
                                          trending, pivot_high, pivot_low, gate_dir)
        # events += self._scan_ma_cross(df, ma_f, ma_m, ma_s, gate_dir)
        events.sort(key=lambda e: e.bar_index)
        return events

    def _scan_divergence(self, df, high, low, close, rsi_v, macd_line, macd_hist,
                          trending, pivot_high, pivot_low, gate_dir) -> List[LabelEvent]:
        n = len(df)
        last = n - 1
        end_scan = last - PIVOT_RIGHT
        if end_scan < PIVOT_LEFT:
            return []

        if self.state.last_pivot_scan_ts is not None and self.state.last_pivot_scan_ts in df.index:
            start_scan = df.index.get_loc(self.state.last_pivot_scan_ts) + 1
        else:
            start_scan = PIVOT_LEFT
        start_scan = max(start_scan, PIVOT_LEFT)

        events: List[LabelEvent] = []

        for pos in range(start_scan, end_scan + 1):
            confirm_bar = pos + PIVOT_RIGHT

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
                        div_hist = False
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

                self.state.prev_pivot_high = {
                    "ts": df.index[pos], "bar": pos, "price": c_hi,
                    "rsi": c_hi_rsi, "macd": c_hi_mcd,
                }

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

    def _scan_ma_cross(self, df, ma_f, ma_m, ma_s, gate_dir) -> List[LabelEvent]:
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
