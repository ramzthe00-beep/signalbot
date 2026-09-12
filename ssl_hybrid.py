# -*- coding: utf-8 -*-
"""
ssl_hybrid.py
=====================================================================
ترجمه‌ی دقیق (Pine-Exact) اندیکاتور «فیلتر روند SSL Hybrid (Mihkel00)»
از بخش ⑮.۵ کد پاین DTM·v6·FC:
    f_rssl_calc / f_rssl_ma / f_rssl_tema / f_rssl_ssf2 / f_rssl_ssf3 /
    f_rssl_atrsmooth

هدف این فایل فقط یک چیز است: تولیدِ همان مقداری که پاین با نامِ
gate_long / gate_short در بخش ⑯ (کاتالیزور) و ⑳ (برچسب‌ها) استفاده
می‌کند — چون i_lbl_gate=true است، *برچسب‌های واگرایی و تقاطع طلایی/مرگ
فقط وقتی ظاهر می‌شوند که gate هم‌جهت باشد*.

═══════════════════════════════════════════════════════════════════
★★★ نکته‌ی تعیین‌کننده (override صریح کاربر برای این پروژه) ★★★
═══════════════════════════════════════════════════════════════════
در پاین:
    both_mode  = i_rssl_mode == "هماهنگی هر دو تایم‌فریم"
    gate_long  = both_mode ? (dir1==1  and dir2==1)  : dir1 == 1
    gate_short = both_mode ? (dir1==-1 and dir2==-1) : dir1 == -1
کاربر صراحتاً خواسته این پروژه با «فقط تایم فریم ۱» و tf1 = "1" (۱ دقیقه
— هم‌تایم‌فریم با چارت اصلی بات) کار کند، نه ۵ دقیقه‌ی اسکرین‌شات و نه
حالت دوتایم‌فریمی. بنابراین اینجا فقط dir1 لازم است، و چون tf1 دقیقاً
همان تایم‌فریمی است که خودِ بات رویش کندل می‌گیرد (۱ دقیقه)،
request.security(symbol, "1", f_rssl_calc(), lookahead_on) از نظر
ریاضی معادل است با: «محاسبه‌ی معمولیِ Hlv روی همان سری‌ی ۱ دقیقه‌ای،
سپس یک بار shift(1)» — چون خودِ f_rssl_calc همیشه Hlv[1] را برمی‌گرداند.
این معادل‌سازی دقیقاً همان چیزی است که compute_gate_series() در پایین
انجام می‌دهد؛ هیچ فراخوانی شبکه/ری‌سمپل جداگانه‌ای لازم نیست.

★ نکته‌ی فنیِ مهمِ دوم:
Hlv فقط و فقط از رویِ «Baseline» ساخته می‌شود:
    emaHigh = f_rssl_ma(baseline_type, high, baseline_len)
    emaLow  = f_rssl_ma(baseline_type, low,  baseline_len)
    Hlv := close > emaHigh ? 1 : close < emaLow ? -1 : Hlv   (var — sticky)
یعنی SSL2 / کانال Baseline / ATR-continuation / خط خروج هیچ‌کدام روی
gate اثر ندارند (rssl_base*/rssl_cont* در کل پاین‌اسکریپت بعد از
destructuring هرگز جای دیگری استفاده نمی‌شوند). با این حال، کل
f_rssl_calc عیناً پیاده‌سازی شده تا اندیکاتور کامل (برای گزارش‌گیری یا
توسعه‌ی آینده) در دسترس باشد.

═══════════════════════════════════════════════════════════════════
پارامترها — دقیقاً طبق اسکرین‌شات تنظیمات واقعیِ کاربر (نه پیش‌فرض کد پاین)
═══════════════════════════════════════════════════════════════════
"""

import numpy as np
import pandas as pd

# ─────────────────────────────────────────────────────────────────
# پارامترها — عیناً از روی اسکرین‌شات ورودی‌های اندیکاتور
# ─────────────────────────────────────────────────────────────────
BASELINE_TYPE     = "HMA"
BASELINE_LEN      = 34
CHANNEL_MULT      = 0.2
USE_TRUE_RANGE    = True

SSL2_TYPE         = "JMA"
SSL2_LEN          = 5
ATR_CONT_CRIT     = 1.2

EXIT_TYPE         = "HMA"
EXIT_LEN          = 21

ATR_LEN           = 14
ATR_MULT          = 1.5
ATR_SMOOTHING     = "WMA"

JMA_PHASE         = 3
JMA_POWER         = 1
KIJUN_DIVIDER     = 1
VAMA_LOOKBACK     = 10
BETA              = 0.8
FEEDBACK          = False
FEEDBACK_Z        = 0.5
EDSMA_FILT_LEN    = 20
EDSMA_FILT_POLES  = 2

# ★ override صریح کاربر: تک‌تایم‌فریمی، روی همان تایم‌فریم اصلی بات (۱ دقیقه)
SSL_GATE_MODE = "single"   # پاین: "فقط تایم فریم ۱"
SSL_TF1 = "5"              # ۱ دقیقه


# ═══════════════════════════════════════════════════════════════════
# توابع پایه
# ═══════════════════════════════════════════════════════════════════
def _sma(s: pd.Series, length: int) -> pd.Series:
    return s.rolling(length).mean()


def _ema(s: pd.Series, length: int) -> pd.Series:
    """معادل ta.ema پاین: بذر = اولین مقدار سری، نه SMA."""
    alpha = 2.0 / (length + 1)
    n = len(s)
    out_vals = np.full(n, np.nan)
    fv = s.first_valid_index()
    if fv is None:
        return pd.Series(out_vals, index=s.index)
    pos0 = s.index.get_loc(fv)
    vals = s.to_numpy(dtype=float).copy()
    prev = vals[pos0]
    out_vals[pos0] = prev
    for i in range(pos0 + 1, n):
        prev = alpha * vals[i] + (1 - alpha) * prev
        out_vals[i] = prev
    return pd.Series(out_vals, index=s.index)


def _rma(s: pd.Series, length: int) -> pd.Series:
    """معادل ta.rma پاین (Wilder)."""
    n = len(s)
    out = pd.Series(np.nan, index=s.index)
    if n == 0:
        return out
    alpha = 1.0 / length
    vals = s.to_numpy(dtype=float)
    lead = 0
    while lead < n and np.isnan(vals[lead]):
        lead += 1
    seed_idx = lead + length - 1
    if seed_idx >= n:
        return out
    prev = vals[lead:seed_idx + 1].mean()
    out_vals = out.to_numpy(dtype=float)
    out_vals[seed_idx] = prev
    for i in range(seed_idx + 1, n):
        prev = alpha * vals[i] + (1 - alpha) * prev
        out_vals[i] = prev
    return pd.Series(out_vals, index=s.index)


def _wma(s: pd.Series, length: int) -> pd.Series:
    w = np.arange(1, length + 1)
    return s.rolling(length).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)


def _hma(s: pd.Series, length: int) -> pd.Series:
    half = max(1, int(length / 2))
    sq = max(1, int(round(np.sqrt(length))))
    diff = 2 * _wma(s, half) - _wma(s, length)
    return _wma(diff, sq)


def _dema(s: pd.Series, length: int) -> pd.Series:
    e = _ema(s, length)
    return 2 * e - _ema(e, length)


def _tema(s: pd.Series, length: int) -> pd.Series:
    e1 = _ema(s, length)
    e2 = _ema(e1, length)
    e3 = _ema(e2, length)
    return 3 * e1 - 3 * e2 + e3


def _lsma(s: pd.Series, length: int) -> pd.Series:
    """معادل ta.linreg(src, len, 0)."""
    idx = np.arange(length)

    def _f(win):
        y = win
        xm = idx.mean()
        ym = y.mean()
        denom = ((idx - xm) ** 2).sum()
        if denom == 0:
            return y[-1]
        slope = ((idx - xm) * (y - ym)).sum() / denom
        intercept = ym - slope * xm
        return intercept + slope * (length - 1)

    return s.rolling(length).apply(_f, raw=True)


def _tma(s: pd.Series, length: int) -> pd.Series:
    return _sma(_sma(s, int(np.ceil(length / 2))), int(np.floor(length / 2)) + 1)


def _vama(s: pd.Series, length: int, lookback: int) -> pd.Series:
    mid = _ema(s, length)
    dev = s - mid
    vol_up = dev.rolling(lookback).max()
    vol_down = dev.rolling(lookback).min()
    return mid + (vol_up + vol_down) / 2.0


def _kijun_v2(high: pd.Series, low: pd.Series, length: int, divider: int) -> pd.Series:
    ll = low.rolling(length).min()
    hh = high.rolling(length).max()
    kijun = (ll + hh) / 2.0
    ll2 = low.rolling(max(1, int(length / divider))).min()
    hh2 = high.rolling(max(1, int(length / divider))).max()
    conv = (ll2 + hh2) / 2.0
    return (kijun + conv) / 2.0


def _mcginley(s: pd.Series, length: int) -> pd.Series:
    n = len(s)
    out = np.full(n, np.nan)
    vals = s.to_numpy(dtype=float)
    fv = s.first_valid_index()
    if fv is None:
        return pd.Series(out, index=s.index)
    start = s.index.get_loc(fv)
    ema0 = _ema(s, length).to_numpy(dtype=float)
    mg = ema0[start]
    out[start] = mg
    for i in range(start + 1, n):
        if mg == 0 or np.isnan(mg):
            mg = ema0[i]
        else:
            mg = mg + (vals[i] - mg) / (length * (vals[i] / mg) ** 4)
        out[i] = mg
    return pd.Series(out, index=s.index)


def _jma(s: pd.Series, length: int, phase: int, power: int) -> pd.Series:
    n = len(s)
    vals = s.to_numpy(dtype=float)
    out = np.zeros(n)
    e0 = np.zeros(n)
    e1 = np.zeros(n)
    e2 = np.zeros(n)

    if phase < -100:
        phase_ratio = 0.5
    elif phase > 100:
        phase_ratio = 2.5
    else:
        phase_ratio = phase / 100 + 1.5

    beta = 0.45 * (length - 1) / (0.45 * (length - 1) + 2)
    alpha = beta ** power

    for i in range(n):
        src = vals[i]
        prev_e0 = e0[i - 1] if i > 0 else 0.0
        prev_e1 = e1[i - 1] if i > 0 else 0.0
        prev_e2 = e2[i - 1] if i > 0 else 0.0
        prev_jma = out[i - 1] if i > 0 else 0.0

        e0[i] = (1 - alpha) * src + alpha * prev_e0
        e1[i] = (src - e0[i]) * (1 - beta) + beta * prev_e1
        e2[i] = (e0[i] + phase_ratio * e1[i] - prev_jma) * (1 - alpha) ** 2 + alpha ** 2 * prev_e2
        out[i] = e2[i] + prev_jma

    return pd.Series(out, index=s.index)


def _true_range(high, low, close):
    prev_close = close.shift(1)
    return pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)


def _ssf2(s: pd.Series, length: int) -> pd.Series:
    n = len(s)
    vals = s.to_numpy(dtype=float)
    out = np.zeros(n)
    PI = 2 * np.arcsin(1)
    arg = np.sqrt(2) * PI / length
    a1 = np.exp(-arg)
    b1 = 2 * a1 * np.cos(arg)
    c2 = b1
    c3 = -(a1 ** 2)
    c1 = 1 - c2 - c3
    for i in range(n):
        p1 = out[i - 1] if i >= 1 else 0.0
        p2 = out[i - 2] if i >= 2 else 0.0
        out[i] = c1 * vals[i] + c2 * p1 + c3 * p2
    return pd.Series(out, index=s.index)


def _ssf3(s: pd.Series, length: int) -> pd.Series:
    n = len(s)
    vals = s.to_numpy(dtype=float)
    out = np.zeros(n)
    PI = 2 * np.arcsin(1)
    arg = PI / length
    a1 = np.exp(-arg)
    b1 = 2 * a1 * np.cos(1.738 * arg)
    c1p = a1 ** 2
    coef2 = b1 + c1p
    coef3 = -(c1p + b1 * c1p)
    coef4 = c1p ** 2
    coef1 = 1 - coef2 - coef3 - coef4
    for i in range(n):
        p1 = out[i - 1] if i >= 1 else 0.0
        p2 = out[i - 2] if i >= 2 else 0.0
        p3 = out[i - 3] if i >= 3 else 0.0
        out[i] = coef1 * vals[i] + coef2 * p1 + coef3 * p2 + coef4 * p3
    return pd.Series(out, index=s.index)


def _edsma(s: pd.Series, length: int, filt_len: int, poles: int) -> pd.Series:
    n = len(s)
    vals = s.to_numpy(dtype=float)
    zeros = s - s.shift(2)
    avg_zeros = (zeros + zeros.shift(1)) / 2.0
    ssf = _ssf2(avg_zeros, filt_len) if poles == 2 else _ssf3(avg_zeros, filt_len)
    stdev = ssf.rolling(length).std(ddof=0)
    scaled = pd.Series(np.where(stdev.to_numpy() != 0, ssf.to_numpy() / stdev.to_numpy(), 0.0), index=s.index)
    alpha_e = 5 * scaled.abs() / length
    alpha_vals = alpha_e.to_numpy(dtype=float)
    out = np.zeros(n)
    for i in range(n):
        a = alpha_vals[i] if not np.isnan(alpha_vals[i]) else 0.0
        prev = out[i - 1] if i >= 1 else 0.0
        src = vals[i] if not np.isnan(vals[i]) else prev
        out[i] = a * src + (1 - a) * prev
    return pd.Series(out, index=s.index)


def _mf(s: pd.Series, length: int, feedback: bool, z: float, beta: float) -> pd.Series:
    n = len(s)
    vals = s.to_numpy(dtype=float)
    ts = np.zeros(n)
    b = np.zeros(n)
    c = np.zeros(n)
    os_ = np.zeros(n)
    alpha = 2.0 / (length + 1)
    for i in range(n):
        prev_ts = ts[i - 1] if i >= 1 else vals[i]
        prev_b = b[i - 1] if i >= 1 else vals[i]
        prev_c = c[i - 1] if i >= 1 else vals[i]
        prev_os = os_[i - 1] if i >= 1 else 0.0
        a = z * vals[i] + (1 - z) * prev_ts if feedback else vals[i]
        cand_b = alpha * a + (1 - alpha) * prev_b
        b[i] = a if a > cand_b else cand_b
        cand_c = alpha * a + (1 - alpha) * prev_c
        c[i] = a if a < cand_c else cand_c
        if a == b[i]:
            os_[i] = 1
        elif a == c[i]:
            os_[i] = 0
        else:
            os_[i] = prev_os
        upper_f = beta * b[i] + (1 - beta) * c[i]
        lower_f = beta * c[i] + (1 - beta) * b[i]
        ts[i] = os_[i] * upper_f + (1 - os_[i]) * lower_f
    return pd.Series(ts, index=s.index)


def pine_ma(ma_type: str, src: pd.Series, length: int, high=None, low=None) -> pd.Series:
    """معادل دقیقِ سوییچ f_rssl_ma در پاین."""
    if ma_type == "SMA":
        return _sma(src, length)
    if ma_type == "EMA":
        return _ema(src, length)
    if ma_type == "WMA":
        return _wma(src, length)
    if ma_type == "DEMA":
        return _dema(src, length)
    if ma_type == "TEMA":
        return _tema(src, length)
    if ma_type == "HMA":
        return _hma(src, length)
    if ma_type == "LSMA":
        return _lsma(src, length)
    if ma_type == "TMA":
        return _tma(src, length)
    if ma_type == "VAMA":
        return _vama(src, length, VAMA_LOOKBACK)
    if ma_type == "Kijun v2":
        return _kijun_v2(high, low, length, KIJUN_DIVIDER)
    if ma_type == "McGinley":
        return _mcginley(src, length)
    if ma_type == "JMA":
        return _jma(src, length, JMA_PHASE, JMA_POWER)
    if ma_type == "MF":
        return _mf(src, length, FEEDBACK, FEEDBACK_Z, BETA)
    if ma_type == "EDSMA":
        return _edsma(src, length, EDSMA_FILT_LEN, EDSMA_FILT_POLES)
    raise ValueError(f"Unknown MA type: {ma_type}")


def _atr_smoothed(high, low, close, length, smoothing):
    tr = _true_range(high, low, close)
    if smoothing == "RMA":
        return _rma(tr, length)
    if smoothing == "SMA":
        return _sma(tr, length)
    if smoothing == "EMA":
        return _ema(tr, length)
    return _wma(tr, length)  # پیش‌فرض/انتخاب کاربر: WMA


# ═══════════════════════════════════════════════════════════════════
# f_rssl_calc — معادل کامل بخش ⑮.۵ کد پاین
# ═══════════════════════════════════════════════════════════════════
def compute_ssl_hybrid(df: pd.DataFrame) -> pd.DataFrame:
    """
    ورودی: df با ستون‌های open/high/low/close (ایندکس زمانی، صعودی)
    خروجی: DataFrame هم‌طول df با ستون‌های:
        hlv          → Hlv خام (بدون شیفت پاین) — یعنی «مقدار در همان بار»
        baseline_dir → جهت baseline خام
        cont_dir     → جهت تداوم خام
    این مقادیر «خام» هستند؛ برای معادل دقیق rssl_dir1 پاین (که خودِ
    f_rssl_calc آن را با یک بار [1] شیفت برمی‌گرداند) باید از
    compute_gate_series() استفاده کرد.
    """
    high, low, close = df["high"], df["low"], df["close"]

    baseline_mc = pine_ma(BASELINE_TYPE, close, BASELINE_LEN, high, low)
    range_val = _true_range(high, low, close) if USE_TRUE_RANGE else (high - low)
    range_ema = _ema(range_val, BASELINE_LEN)
    upperk = baseline_mc + range_ema * CHANNEL_MULT
    lowerk = baseline_mc - range_ema * CHANNEL_MULT

    ema_high = pine_ma(BASELINE_TYPE, high, BASELINE_LEN, high, low)
    ema_low = pine_ma(BASELINE_TYPE, low, BASELINE_LEN, high, low)

    n = len(df)
    close_v = close.to_numpy(dtype=float)
    eh_v = ema_high.to_numpy(dtype=float)
    el_v = ema_low.to_numpy(dtype=float)
    hlv = np.zeros(n, dtype=int)
    prev = 0
    for i in range(n):
        if np.isnan(eh_v[i]) or np.isnan(el_v[i]):
            hlv[i] = prev
        elif close_v[i] > eh_v[i]:
            hlv[i] = 1
        elif close_v[i] < el_v[i]:
            hlv[i] = -1
        else:
            hlv[i] = prev
        prev = hlv[i]

    ma_high2 = pine_ma(SSL2_TYPE, high, SSL2_LEN, high, low)
    ma_low2 = pine_ma(SSL2_TYPE, low, SSL2_LEN, high, low)
    mh2 = ma_high2.to_numpy(dtype=float)
    ml2 = ma_low2.to_numpy(dtype=float)
    hlv2 = np.zeros(n, dtype=int)
    prev2 = 0
    ssl_down2 = np.zeros(n, dtype=float)
    for i in range(n):
        if np.isnan(mh2[i]) or np.isnan(ml2[i]):
            hlv2[i] = prev2
        elif close_v[i] > mh2[i]:
            hlv2[i] = 1
        elif close_v[i] < ml2[i]:
            hlv2[i] = -1
        else:
            hlv2[i] = prev2
        prev2 = hlv2[i]
        ssl_down2[i] = mh2[i] if hlv2[i] < 0 else ml2[i]

    atr_s = _atr_smoothed(high, low, close, ATR_LEN, ATR_SMOOTHING)
    atr_v = atr_s.to_numpy(dtype=float)
    bbmc_v = baseline_mc.to_numpy(dtype=float)

    cont_dir = np.zeros(n, dtype=int)
    for i in range(n):
        if np.isnan(atr_v[i]) or np.isnan(ssl_down2[i]) or np.isnan(bbmc_v[i]):
            continue
        upper_half = atr_v[i] * ATR_CONT_CRIT + close_v[i]
        lower_half = close_v[i] - atr_v[i] * ATR_CONT_CRIT
        buy_inatr = lower_half < ssl_down2[i]
        sell_inatr = upper_half > ssl_down2[i]
        sell_cont = close_v[i] < bbmc_v[i] and close_v[i] < ssl_down2[i]
        buy_cont = close_v[i] > bbmc_v[i] and close_v[i] > ssl_down2[i]
        if buy_inatr and buy_cont:
            cont_dir[i] = 1
        elif sell_inatr and sell_cont:
            cont_dir[i] = -1

    upperk_v = upperk.to_numpy(dtype=float)
    lowerk_v = lowerk.to_numpy(dtype=float)
    baseline_dir = np.zeros(n, dtype=int)
    for i in range(n):
        if np.isnan(upperk_v[i]) or np.isnan(lowerk_v[i]):
            continue
        if close_v[i] > upperk_v[i]:
            baseline_dir[i] = 1
        elif close_v[i] < lowerk_v[i]:
            baseline_dir[i] = -1

    return pd.DataFrame(
        {"hlv": hlv, "baseline_dir": baseline_dir, "cont_dir": cont_dir},
        index=df.index,
    )


def compute_gate_series(df: pd.DataFrame) -> pd.Series:
    """
    معادل دقیقِ رشته‌ی «rssl_dir1» پاین در حالت تک‌تایم‌فریمی روی همان
    تایم‌فریمی که df به آن تعلق دارد (در این پروژه: ۱ دقیقه).
    چون f_rssl_calc خودش Hlv[1] برمی‌گرداند، اینجا هم فقط یک shift(1)
    روی Hlv خام کافی است — بدون هیچ فراخوانی شبکه/ری‌سمپلی.
    مقدار در بار i:  1=گیت لانگ فعال | -1=گیت شورت فعال | 0=هیچ‌کدام
    """
    result = compute_ssl_hybrid(df)
    return result["hlv"].shift(1).fillna(0).astype(int)


def gate_flags(df: pd.DataFrame):
    """برمی‌گرداند (gate_long: pd.Series[bool], gate_short: pd.Series[bool])"""
    dir1 = compute_gate_series(df)
    return dir1 == 1, dir1 == -1
