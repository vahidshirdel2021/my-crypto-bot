# -*- coding: utf-8 -*-
"""
pdh_eq_pdl_engine.py
---------------------
پیاده‌سازی کامل و مستقل استراتژی «PDH / EQ / PDL» (۶ سناریوی خرید B1..B6 و
۶ سناریوی فروش S1..S6) طبق فایل استراتژی کاربر، به‌صورتی که این ماژول
جایگزین کامل منطق قدیمی ربات می‌شود.

نکات کلیدی طبق درخواست کاربر:
  - تایم‌فریم‌های ۵ و ۱۵ دقیقه: سطوح مرجع از PDH/PDL/EQ *روزانه* گرفته می‌شود.
  - تایم‌فریم‌های ۱ و ۴ ساعته: سطوح مرجع از PWH/PWL/EQ *هفتگی* گرفته می‌شود
    (دقیقاً همان منطق PDH/PDL روزانه، فقط روی دوره‌ی هفتگی).
  - همه‌ی ۱۲ سناریو در هر بار بررسی، هم‌زمان ارزیابی می‌شوند و سناریویی که
    بیشترین امتیاز نهایی (پایه + بونوس اندیکاتورها − جریمه‌ی سابقه فیک‌اوت)
    را داشته باشد انتخاب می‌شود؛ دقیقاً طبق pseudocode بخش ۴ فایل استراتژی.
  - اندیکاتورهای کمکی (حجم، بدنه کندل نسبت به ATR، RSI، هم‌جهتی با EMA50)
    هرگز شرط سخت‌گیرانه (فیلتر) نیستند؛ فقط روی امتیاز نهایی اثر می‌گذارند.

این ماژول کاملاً بدون وابستگی به کد قدیمی strategy.py نوشته شده تا مطابق
درخواست کاربر ("به استراتژی الان ربات توجه نکن، خودت صفر تا صد بازنویسی
کن") هیچ اثری از منطق قبلی در تصمیم‌گیری باقی نماند.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ============================================================================
# ۱) تنظیمات پیش‌فرض موتور (این‌ها از strategy.py هم قابل بازنویسی/override اند)
# ============================================================================

ENGINE_DEFAULTS = {
    # --- ساختار / تلورانس ---
    "swing_lookback_fractal": 3,      # تعداد کندل هر سمت برای فرکتال سوئینگ
    "touch_tolerance_pct": 0.0006,    # ۰.۰۶٪ تلورانس «برخورد به سطح»
    "break_confirm_pct": 0.0003,      # حداقل فاصله close از سطح برای «شکست واقعی»
    "min_confirm_body_ratio": 0.20,   # حداقل کیفیت بدنه برای «کندل تاییدی»
    "swing_search_window_mult": 4,    # پنجره جست‌وجوی سوئینگ = lookback * این عدد

    # --- امتیاز پایه سناریوها (دقیقاً از فایل استراتژی) ---
    "base_scores": {
        "B1": 95, "B2": 90, "B3": 80, "B4": 75, "B5": 70, "B6": 60,
        "S1": 95, "S2": 90, "S3": 80, "S4": 75, "S5": 70, "S6": 60,
    },

    # --- وزن بونوس‌ها (جمع حداکثر = ۱۰+۵+۵+۵+۵ = ۳۰) ---
    "bonus_weights": {
        "volume": 10.0,
        "candle_body": 5.0,
        "swing_clarity": 5.0,
        "rsi_alignment": 5.0,
        "trend_alignment": 5.0,
    },
    # --- جریمه سابقه فیک‌اوت (پروکسی: تعداد برخوردهای تکراری به همان سطح در همین دوره) ---
    "penalty_weights": {
        "fakeout_history": 15.0,
    },

    "rsi_oversold": 35.0,
    "rsi_overbought": 65.0,

    "max_score": 100.0,
    "min_score_to_trade": 65.0,

    # --- مدیریت ریسک پیش‌فرض (در نبود سوئینگ قابل‌اتکا) ---
    "atr_period": 14,
    "sl_atr_buffer": 0.35,       # بافر پشت سوئینگ/سطح بر حسب ATR
    "sl_atr_buffer_tight": 0.20,  # بافر کوچک‌تر برای B5/S5 (بریک‌اند‌ریتست)
    "extension_atr_mult": 0.50,  # ضریب اکستنشن برای اهداف فراتر از رنج (B5/S5)
    "min_rr": 1.10,               # حداقل نسبت ریسک به ریوارد قابل قبول
}


# ============================================================================
# ۲) ابزارهای عمومی
# ============================================================================

def _safe_float(v, default=0.0):
    try:
        x = float(v)
        return x if np.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _merged_cfg(strategy_config=None):
    cfg = dict(ENGINE_DEFAULTS)
    if isinstance(strategy_config, dict):
        for k, v in strategy_config.items():
            if k in ("base_scores", "bonus_weights", "penalty_weights") and isinstance(v, dict):
                merged = dict(cfg.get(k, {}))
                merged.update(v)
                cfg[k] = merged
            else:
                cfg[k] = v
    return cfg


def _ensure_atr(df: pd.DataFrame) -> pd.DataFrame:
    """اگر calculate_indicators قبلاً روی df اجرا نشده باشد، حداقل ستون‌های لازم را می‌سازد."""
    if df is None or df.empty:
        return df
    need = {"atr", "rsi", "ema50", "volume_ratio", "body_ratio"}
    if need.issubset(df.columns):
        return df
    d = df.copy()
    for col in ("open", "high", "low", "close", "volume"):
        if col in d.columns:
            d[col] = pd.to_numeric(d[col], errors="coerce")
    prev_close = d["close"].shift(1)
    tr = pd.concat([
        d["high"] - d["low"],
        (d["high"] - prev_close).abs(),
        (d["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    delta = d["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = avg_gain / (avg_loss + 1e-12)
    d["rsi"] = 100 - (100 / (1 + rs))
    d["ema50"] = d["close"].ewm(span=50, adjust=False).mean()
    d["volume_ma20"] = d["volume"].rolling(20, min_periods=20).mean()
    d["volume_ratio"] = d["volume"] / (d["volume_ma20"] + 1e-12)
    d["candle_body"] = (d["close"] - d["open"]).abs()
    d["candle_range"] = (d["high"] - d["low"]).clip(lower=1e-12)
    d["body_ratio"] = d["candle_body"] / d["candle_range"]
    return d


def _timestamp_to_datetime(df: pd.DataFrame) -> pd.Series:
    ts = pd.to_numeric(df["timestamp"], errors="coerce")
    unit = "ms" if float(ts.dropna().median() or 0) > 1e12 else "s"
    return pd.to_datetime(ts, unit=unit, utc=True)


# ============================================================================
# ۳) محاسبه سطوح مرجع: روزانه (PDH/PDL/EQ) و هفتگی (PWH/PWL/EQ)
# ============================================================================

def compute_prev_day_levels(df: pd.DataFrame):
    """سطوح PDH/PDL/EQ روزانه (برای تایم‌فریم‌های ۵ و ۱۵ دقیقه)."""
    if df is None or len(df) < 50 or "timestamp" not in df.columns:
        return None, None, None, None
    d = df.copy()
    d["_dt"] = _timestamp_to_datetime(d)
    if d["_dt"].isna().all():
        return None, None, None, None
    d["_period"] = d["_dt"].dt.date
    grp = d.groupby("_period").agg(_hi=("high", "max"), _lo=("low", "min"))
    grp["_pdh"] = grp["_hi"].shift(1)
    grp["_pdl"] = grp["_lo"].shift(1)
    d = d.merge(grp[["_pdh", "_pdl"]], left_on="_period", right_index=True, how="left")
    d = d.reset_index(drop=True)
    idx_now = len(d) - 2  # آخرین کندل بسته‌شده (مطابق قرارداد کل ربات)
    if idx_now < 0:
        return d, None, None, None
    pdh, pdl = d.at[idx_now, "_pdh"], d.at[idx_now, "_pdl"]
    if pd.isna(pdh) or pd.isna(pdl):
        return d, None, None, None
    pdh, pdl = float(pdh), float(pdl)
    eq = (pdh + pdl) / 2.0
    return d, pdh, pdl, eq


def compute_prev_week_levels(df: pd.DataFrame):
    """سطوح PWH/PWL/EQ هفتگی (برای تایم‌فریم‌های ۱ و ۴ ساعته)."""
    if df is None or len(df) < 50 or "timestamp" not in df.columns:
        return None, None, None, None
    d = df.copy()
    d["_dt"] = _timestamp_to_datetime(d)
    if d["_dt"].isna().all():
        return None, None, None, None
    # شروع هفته را دوشنبه در نظر می‌گیریم (قابل تغییر در صورت نیاز به هفته کریپتویی یکشنبه‌شروع)
    iso = d["_dt"].dt.isocalendar()
    d["_period"] = iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)
    grp = d.groupby("_period", sort=False).agg(_hi=("high", "max"), _lo=("low", "min"))
    # ترتیب دوره‌ها باید زمانی باشد نه الفبایی؛ با اولین timestamp هر دوره مرتب می‌کنیم
    order = d.groupby("_period", sort=False)["_dt"].min().sort_values().index
    grp = grp.reindex(order)
    grp["_pwh"] = grp["_hi"].shift(1)
    grp["_pwl"] = grp["_lo"].shift(1)
    d = d.merge(grp[["_pwh", "_pwl"]], left_on="_period", right_index=True, how="left")
    d = d.reset_index(drop=True)
    idx_now = len(d) - 2
    if idx_now < 0:
        return d, None, None, None
    pwh, pwl = d.at[idx_now, "_pwh"], d.at[idx_now, "_pwl"]
    if pd.isna(pwh) or pd.isna(pwl):
        return d, None, None, None
    pwh, pwl = float(pwh), float(pwl)
    eq = (pwh + pwl) / 2.0
    return d, pwh, pwl, eq


LEVEL_SOURCE_BY_TIMEFRAME = {
    "5min": "daily",
    "15min": "daily",
    "1hour": "weekly",
    "4hour": "weekly",
}


def get_reference_levels(df: pd.DataFrame, timeframe: str):
    """
    سطوح مرجع مناسب تایم‌فریم را برمی‌گرداند.
    خروجی: (d, high_level, low_level, eq, label, level_source)
    label یکی از 'PDH/PDL' یا 'PWH/PWL' برای نمایش در دلیل سیگنال.
    """
    source = LEVEL_SOURCE_BY_TIMEFRAME.get(timeframe, "daily")
    if source == "weekly":
        d, hi, lo, eq = compute_prev_week_levels(df)
        return d, hi, lo, eq, "PWH/PWL", source
    d, hi, lo, eq = compute_prev_day_levels(df)
    return d, hi, lo, eq, "PDH/PDL", source


# ============================================================================
# ۴) تشخیص سوئینگ (فرکتال ساده)
# ============================================================================

def compute_swings(df: pd.DataFrame, lookback: int = 3) -> pd.DataFrame:
    d = df.copy()
    n = len(d)
    highs = pd.to_numeric(d["high"], errors="coerce").values
    lows = pd.to_numeric(d["low"], errors="coerce").values
    swing_high = np.zeros(n, dtype=bool)
    swing_low = np.zeros(n, dtype=bool)
    for i in range(lookback, n - lookback):
        h_win = highs[i - lookback: i + lookback + 1]
        l_win = lows[i - lookback: i + lookback + 1]
        if np.isnan(h_win).any() or np.isnan(l_win).any():
            continue
        if highs[i] == h_win.max() and (h_win == highs[i]).sum() == 1:
            swing_high[i] = True
        if lows[i] == l_win.min() and (l_win == lows[i]).sum() == 1:
            swing_low[i] = True
    d["swing_high"] = swing_high
    d["swing_low"] = swing_low
    return d


def _recent_confirmed_swings(d: pd.DataFrame, idx_now: int, lookback: int, col: str, search_back: int):
    """اندیس‌های سوئینگ‌های تاییدشده (col='swing_low'/'swing_high') در بازه‌ی [idx_now-search_back, idx_now-lookback]."""
    lo = max(0, idx_now - search_back)
    hi = idx_now - lookback  # باید حداقل lookback کندل بعدش بسته شده باشد تا تایید شود
    if hi < lo:
        return []
    sub = d.loc[lo:hi]
    return [i for i in sub.index if bool(sub.at[i, col])]


# ============================================================================
# ۵) بونوس/جریمه امتیاز پویا (اندیکاتورهای کمکی - فقط امتیازدهی)
# ============================================================================

def _dynamic_bonus_penalty(d: pd.DataFrame, idx_now: int, direction: int, cfg: dict, touch_count: int):
    """
    direction: +1 برای سناریوهای خرید، -1 برای سناریوهای فروش
    خروجی: (bonus_total, penalty_total, notes:list[str])
    """
    bw = cfg["bonus_weights"]
    pw = cfg["penalty_weights"]
    row = d.loc[idx_now]
    notes = []

    vr = _safe_float(row.get("volume_ratio"), 1.0)
    volume_bonus = max(0.0, min(bw["volume"], (vr - 1.0) * bw["volume"]))
    if volume_bonus > 0.5:
        notes.append(f"حجم {vr:.2f}× میانگین")

    body_ratio = _safe_float(row.get("body_ratio"), 0.0)
    candle_bonus = max(0.0, min(bw["candle_body"], (body_ratio / 0.65) * bw["candle_body"]))
    if candle_bonus > 0.5:
        notes.append(f"کیفیت بدنه کندل {body_ratio:.2f}")

    rsi = _safe_float(row.get("rsi"), 50.0)
    if direction > 0:
        rsi_bonus = max(0.0, min(bw["rsi_alignment"], (cfg["rsi_oversold"] - rsi) / cfg["rsi_oversold"] * bw["rsi_alignment"]))
    else:
        rsi_bonus = max(0.0, min(bw["rsi_alignment"], (rsi - cfg["rsi_overbought"]) / (100 - cfg["rsi_overbought"]) * bw["rsi_alignment"]))
    if rsi_bonus > 0.5:
        notes.append(f"هم‌جهتی RSI ({rsi:.1f})")

    ema50 = _safe_float(row.get("ema50"), row.get("close"))
    close = _safe_float(row.get("close"))
    if direction > 0:
        trend_bonus = bw["trend_alignment"] if close > ema50 else 0.0
    else:
        trend_bonus = bw["trend_alignment"] if close < ema50 else 0.0
    if trend_bonus > 0:
        notes.append("هم‌جهت با روند EMA50")

    bonus_total = volume_bonus + candle_bonus + rsi_bonus + trend_bonus

    # جریمه سابقه فیک‌اوت: پروکسی = تعداد برخوردهای تکراری به همان سطح در همین دوره
    # (هرچه یک سطح بیشتر لمس شده باشد بدون شکست قطعی، احتمال فیک‌اوت بعدی بیشتر است)
    extra_touches = max(0, touch_count - 1)
    penalty_total = min(pw["fakeout_history"], extra_touches * (pw["fakeout_history"] / 3.0))
    if penalty_total > 0.5:
        notes.append(f"سابقه {touch_count} برخورد قبلی به همین سطح (ریسک فیک‌اوت)")

    return bonus_total, penalty_total, notes


# ============================================================================
# ۶) موتور اصلی سناریوها
# ============================================================================

def _is_bullish_confirm(row, min_body_ratio):
    return _safe_float(row.get("close")) > _safe_float(row.get("open")) and _safe_float(row.get("body_ratio")) >= min_body_ratio


def _is_bearish_confirm(row, min_body_ratio):
    return _safe_float(row.get("close")) < _safe_float(row.get("open")) and _safe_float(row.get("body_ratio")) >= min_body_ratio


def evaluate_scenarios(df: pd.DataFrame, timeframe: str, strategy_config: dict = None):
    """
    ارزیابی هم‌زمان ۱۲ سناریوی B1..B6 / S1..S6 روی df (که باید ستون‌های
    open/high/low/close/volume/timestamp داشته باشد؛ اندیکاتورها در صورت نبود
    به‌صورت خودکار ساخته می‌شوند).

    خروجی: dict یا None
        {
          'code': 'B1', 'direction': 'BUY'/'SELL', 'total_score': float,
          'base_score': float, 'bonus': float, 'penalty': float,
          'entry': float, 'sl': float, 'tp': float, 'tp_partial': float|None,
          'level_label': 'PDH/PDL'|'PWH/PWL', 'reasons': [str,...]
        }
    اگر هیچ سناریویی شرایط را کامل نکند: None
    """
    cfg = _merged_cfg(strategy_config)
    if df is None or len(df) < 50:
        return None
    d = _ensure_atr(df)
    d, hi_level, lo_level, eq, label, source = get_reference_levels(d, timeframe)
    if d is None or hi_level is None or lo_level is None or hi_level <= lo_level:
        return None

    lookback = int(cfg["swing_lookback_fractal"])
    d = compute_swings(d, lookback)
    idx_now = len(d) - 2  # آخرین کندل بسته‌شده
    if idx_now < lookback * 3:
        return None

    tol = float(cfg["touch_tolerance_pct"])
    brk = float(cfg["break_confirm_pct"])
    min_body = float(cfg["min_confirm_body_ratio"])
    search_back = lookback * int(cfg["swing_search_window_mult"])
    atr_now = _safe_float(d.at[idx_now, "atr"])
    if atr_now <= 0:
        return None

    # --- محدوده دوره جاری (روز جاری یا هفته جاری، بسته به تایم‌فریم) ---
    period_col = "_period"
    period_val = d.at[idx_now, period_col]
    period_mask = d[period_col] == period_val
    start_idx = int(d.index[period_mask][0])
    period = d.loc[start_idx:idx_now]

    hi_touch_idxs = [i for i in period.index if _safe_float(period.at[i, "high"]) >= hi_level * (1 - tol)]
    lo_touch_idxs = [i for i in period.index if _safe_float(period.at[i, "low"]) <= lo_level * (1 + tol)]
    hi_break_idxs = [i for i in period.index if _safe_float(period.at[i, "close"]) > hi_level * (1 + brk)]
    lo_break_idxs = [i for i in period.index if _safe_float(period.at[i, "close"]) < lo_level * (1 - brk)]

    first_hi = hi_touch_idxs[0] if hi_touch_idxs else None
    first_lo = lo_touch_idxs[0] if lo_touch_idxs else None

    curr_row = d.loc[idx_now]
    close_now = _safe_float(curr_row.get("close"))

    candidates = []

    def add_candidate(code, direction, sl, tp, tp_partial, extra_reason, touch_count):
        base = cfg["base_scores"][code]
        bonus, penalty, notes = _dynamic_bonus_penalty(d, idx_now, 1 if direction == "BUY" else -1, cfg, touch_count)
        total = max(0.0, min(cfg["max_score"], base + bonus - penalty))
        reasons = [extra_reason] + notes
        candidates.append({
            "code": code, "direction": direction,
            "base_score": base, "bonus": round(bonus, 1), "penalty": round(penalty, 1),
            "total_score": round(total, 1),
            "entry": close_now, "sl": sl, "tp": tp, "tp_partial": tp_partial,
            "level_label": label, "reasons": reasons,
        })

    # ------------------------------------------------------------------
    # سناریوهای خرید (BUY)
    # ------------------------------------------------------------------
    recent_swing_lows = _recent_confirmed_swings(d, idx_now, lookback, "swing_low", search_back)
    bullish_confirm_now = _is_bullish_confirm(curr_row, min_body)

    # B1: سوییپ PDH/PWH سپس سوییپ PDL/PWL و بازگشت
    if first_hi is not None and first_lo is not None and first_hi < first_lo and bullish_confirm_now and recent_swing_lows:
        swing_idx = recent_swing_lows[-1]
        swing_price = _safe_float(d.at[swing_idx, "low"])
        if swing_price <= lo_level * (1 + tol * 5) and idx_now - swing_idx <= lookback + 3:
            sl = min(swing_price, lo_level) - atr_now * cfg["sl_atr_buffer"]
            add_candidate("B1", "BUY", sl, hi_level, eq,
                           f"سوییپ {label.split('/')[0]} سپس سوییپ {label.split('/')[1]} و بازگشت صعودی",
                           len(lo_touch_idxs))

    # B3: سوییپ مستقیم PDL/PWL بدون عبور قبلی از PDH/PWH
    if first_lo is not None and (first_hi is None or first_hi > first_lo) and bullish_confirm_now and recent_swing_lows:
        swing_idx = recent_swing_lows[-1]
        swing_price = _safe_float(d.at[swing_idx, "low"])
        if swing_price <= lo_level * (1 + tol * 5) and idx_now - swing_idx <= lookback + 3:
            sl = min(swing_price, lo_level) - atr_now * cfg["sl_atr_buffer"]
            add_candidate("B3", "BUY", sl, hi_level, eq,
                           f"سوییپ مستقیم {label.split('/')[1]} بدون عبور قبلی از {label.split('/')[0]}",
                           len(lo_touch_idxs))

    # B4: ری‌کلیم EQ پس از سوییپ PDL/PWL
    if first_lo is not None:
        eq_cross_idxs = [i for i in period.index if i > start_idx and i > first_lo
                          and _safe_float(d.at[i - 1, "close"]) < eq <= _safe_float(d.at[i, "close"])]
        if eq_cross_idxs and eq_cross_idxs[-1] >= idx_now - 1 and bullish_confirm_now:
            swing_idx = recent_swing_lows[-1] if recent_swing_lows else None
            swing_price = _safe_float(d.at[swing_idx, "low"]) if swing_idx is not None else eq
            sl = min(swing_price, eq) - atr_now * cfg["sl_atr_buffer"]
            add_candidate("B4", "BUY", sl, hi_level, None,
                           "ری‌کلیم تاییدشده EQ به سمت بالا پس از سوییپ کف رنج",
                           len(lo_touch_idxs))

    # B2: سوییپ PDH/PWH، پولبک مضاعف، سوئینگ (کف بالاتر) نزدیک مقاومت
    if first_hi is not None and bullish_confirm_now:
        swings_after = [i for i in recent_swing_lows if i > first_hi]
        if len(swings_after) >= 2 and _safe_float(d.at[swings_after[-1], "low"]) > _safe_float(d.at[swings_after[-2], "low"]):
            if idx_now - swings_after[-1] <= lookback + 3:
                swing_price = _safe_float(d.at[swings_after[-1], "low"])
                sl = swing_price - atr_now * cfg["sl_atr_buffer"]
                add_candidate("B2", "BUY", sl, hi_level, None,
                               "سوییپ مقاومت + پولبک مضاعف با کف بالاتر (سوئینگ نزدیک مقاومت)",
                               len(hi_touch_idxs))

    # B5: بریک‌اند‌ریتست PDH/PWH (شکسته‌شدن مقاومت و تبدیل آن به حمایت)
    if hi_break_idxs and bullish_confirm_now:
        first_break = hi_break_idxs[0]
        after_break = period.loc[first_break:idx_now]
        min_close_after = _safe_float(after_break["close"].min()) if len(after_break) else None
        retested = any(_safe_float(after_break.at[i, "low"]) <= hi_level * (1 + tol) for i in after_break.index)
        if retested and min_close_after is not None and min_close_after >= hi_level * (1 - tol):
            sl = hi_level - atr_now * cfg["sl_atr_buffer_tight"]
            tp_ext = hi_level + (hi_level - lo_level) * cfg["extension_atr_mult"]
            add_candidate("B5", "BUY", sl, tp_ext, None,
                           f"بریک‌اند‌ریتست {label.split('/')[0]} (تبدیل مقاومت شکسته به حمایت)",
                           len(hi_touch_idxs))

    # B6: ورود دیسکانت (زیر EQ) بدون لمس دقیق PDL/PWL
    if first_lo is None and close_now < eq and bullish_confirm_now and recent_swing_lows:
        swing_idx = recent_swing_lows[-1]
        swing_price = _safe_float(d.at[swing_idx, "low"])
        if lo_level < swing_price < eq and idx_now - swing_idx <= lookback + 3:
            sl = swing_price - atr_now * cfg["sl_atr_buffer"]
            add_candidate("B6", "BUY", sl, hi_level, eq,
                           "ورود در ناحیه دیسکانت (زیر EQ) بدون لمس دقیق کف رنج",
                           len(lo_touch_idxs))

    # ------------------------------------------------------------------
    # سناریوهای فروش (SELL) — دقیقاً معکوس سناریوهای خرید
    # ------------------------------------------------------------------
    recent_swing_highs = _recent_confirmed_swings(d, idx_now, lookback, "swing_high", search_back)
    bearish_confirm_now = _is_bearish_confirm(curr_row, min_body)

    # S1: سوییپ PDL/PWL سپس سوییپ PDH/PWH و بازگشت
    if first_lo is not None and first_hi is not None and first_lo < first_hi and bearish_confirm_now and recent_swing_highs:
        swing_idx = recent_swing_highs[-1]
        swing_price = _safe_float(d.at[swing_idx, "high"])
        if swing_price >= hi_level * (1 - tol * 5) and idx_now - swing_idx <= lookback + 3:
            sl = max(swing_price, hi_level) + atr_now * cfg["sl_atr_buffer"]
            add_candidate("S1", "SELL", sl, lo_level, eq,
                           f"سوییپ {label.split('/')[1]} سپس سوییپ {label.split('/')[0]} و بازگشت نزولی",
                           len(hi_touch_idxs))

    # S3: سوییپ مستقیم PDH/PWH بدون عبور قبلی از PDL/PWL
    if first_hi is not None and (first_lo is None or first_lo > first_hi) and bearish_confirm_now and recent_swing_highs:
        swing_idx = recent_swing_highs[-1]
        swing_price = _safe_float(d.at[swing_idx, "high"])
        if swing_price >= hi_level * (1 - tol * 5) and idx_now - swing_idx <= lookback + 3:
            sl = max(swing_price, hi_level) + atr_now * cfg["sl_atr_buffer"]
            add_candidate("S3", "SELL", sl, lo_level, eq,
                           f"سوییپ مستقیم {label.split('/')[0]} بدون عبور قبلی از {label.split('/')[1]}",
                           len(hi_touch_idxs))

    # S4: ری‌کلیم EQ پس از سوییپ PDH/PWH
    if first_hi is not None:
        eq_cross_idxs = [i for i in period.index if i > start_idx and i > first_hi
                          and _safe_float(d.at[i - 1, "close"]) > eq >= _safe_float(d.at[i, "close"])]
        if eq_cross_idxs and eq_cross_idxs[-1] >= idx_now - 1 and bearish_confirm_now:
            swing_idx = recent_swing_highs[-1] if recent_swing_highs else None
            swing_price = _safe_float(d.at[swing_idx, "high"]) if swing_idx is not None else eq
            sl = max(swing_price, eq) + atr_now * cfg["sl_atr_buffer"]
            add_candidate("S4", "SELL", sl, lo_level, None,
                           "ری‌کلیم تاییدشده EQ به سمت پایین پس از سوییپ سقف رنج",
                           len(hi_touch_idxs))

    # S2: سوییپ PDL/PWL، پولبک مضاعف، سوئینگ (سقف پایین‌تر) نزدیک حمایت
    if first_lo is not None and bearish_confirm_now:
        swings_after = [i for i in recent_swing_highs if i > first_lo]
        if len(swings_after) >= 2 and _safe_float(d.at[swings_after[-1], "high"]) < _safe_float(d.at[swings_after[-2], "high"]):
            if idx_now - swings_after[-1] <= lookback + 3:
                swing_price = _safe_float(d.at[swings_after[-1], "high"])
                sl = swing_price + atr_now * cfg["sl_atr_buffer"]
                add_candidate("S2", "SELL", sl, lo_level, None,
                               "سوییپ حمایت + پولبک مضاعف با سقف پایین‌تر (سوئینگ نزدیک حمایت)",
                               len(lo_touch_idxs))

    # S5: بریک‌اند‌ریتست PDL/PWL (شکسته‌شدن حمایت و تبدیل آن به مقاومت)
    if lo_break_idxs and bearish_confirm_now:
        first_break = lo_break_idxs[0]
        after_break = period.loc[first_break:idx_now]
        max_close_after = _safe_float(after_break["close"].max()) if len(after_break) else None
        retested = any(_safe_float(after_break.at[i, "high"]) >= lo_level * (1 - tol) for i in after_break.index)
        if retested and max_close_after is not None and max_close_after <= lo_level * (1 + tol):
            sl = lo_level + atr_now * cfg["sl_atr_buffer_tight"]
            tp_ext = lo_level - (hi_level - lo_level) * cfg["extension_atr_mult"]
            add_candidate("S5", "SELL", sl, tp_ext, None,
                           f"بریک‌اند‌ریتست {label.split('/')[1]} (تبدیل حمایت شکسته به مقاومت)",
                           len(lo_touch_idxs))

    # S6: ورود پریمیوم (بالای EQ) بدون لمس دقیق PDH/PWH
    if first_hi is None and close_now > eq and bearish_confirm_now and recent_swing_highs:
        swing_idx = recent_swing_highs[-1]
        swing_price = _safe_float(d.at[swing_idx, "high"])
        if eq < swing_price < hi_level and idx_now - swing_idx <= lookback + 3:
            sl = swing_price + atr_now * cfg["sl_atr_buffer"]
            add_candidate("S6", "SELL", sl, lo_level, eq,
                           "ورود در ناحیه پریمیوم (بالای EQ) بدون لمس دقیق سقف رنج",
                           len(hi_touch_idxs))

    if not candidates:
        return None

    best = max(candidates, key=lambda c: c["total_score"])
    return best
