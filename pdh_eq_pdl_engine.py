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
  - همه‌ی ۱۰ سناریو در هر بار بررسی، هم‌زمان ارزیابی می‌شوند و سناریویی که
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
    "swing_search_window_mult": 4,
    "min_swing_wick_atr": 0.15,
    "min_swing_wick_pct": 0.0005,
    "min_swing_volume_ratio": 1.02,
    "require_swing_volume": True,
    "max_entry_event_age_bars": 9,  # interaction must be recent, not merely somewhere in today

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
        "fakeout_min_penalty": 2.0,
        "fakeout_decay_touches": 4.0,
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


def _timeframe_minutes(timeframe: str) -> int:
    return {"5min": 5, "15min": 15, "1hour": 60, "4hour": 240}.get(str(timeframe), 5)


def _last_closed_index(d: pd.DataFrame, timeframe: str) -> int:
    """Return the latest candle that is definitely closed.

    Live feeds often append the currently-forming candle.  Historical/backtest
    data normally ends on a closed candle.  We therefore inspect the candle's
    UTC open timestamp against current UTC time rather than blindly using -2.
    """
    if d is None or d.empty or "timestamp" not in d.columns:
        return -1
    ts = pd.to_numeric(d["timestamp"], errors="coerce")
    unit = "ms" if float(ts.dropna().median() or 0) > 1e12 else "s"
    dt = pd.to_datetime(ts, unit=unit, utc=True)
    last_i = len(d) - 1
    if pd.isna(dt.iloc[last_i]):
        return max(-1, last_i - 1)
    close_at = dt.iloc[last_i] + pd.Timedelta(minutes=_timeframe_minutes(timeframe))
    # If the last candle is still forming, use the preceding one; otherwise use it.
    return last_i - 1 if close_at > pd.Timestamp.now(tz="UTC") else last_i


def compute_prev_day_levels(df: pd.DataFrame, timeframe: str = "5min"):
    """PDH/PDL/EQ from the completed UTC calendar day immediately before the
    day containing the latest *closed* intraday candle."""
    if df is None or len(df) < 2 or "timestamp" not in df.columns:
        return None, None, None, None
    d = df.copy()
    d["_dt"] = _timestamp_to_datetime(d)
    d = d.dropna(subset=["_dt"]).reset_index(drop=True)
    if d.empty:
        return d, None, None, None
    for col in ("high", "low"):
        d[col] = pd.to_numeric(d[col], errors="coerce")
    d["_period"] = d["_dt"].dt.strftime("%Y-%m-%d")
    grp = d.groupby("_period", sort=True).agg(_hi=("high", "max"), _lo=("low", "min"))
    grp["_pdh"] = grp["_hi"].shift(1)
    grp["_pdl"] = grp["_lo"].shift(1)
    d = d.merge(grp[["_pdh", "_pdl"]], left_on="_period", right_index=True, how="left")
    idx_now = _last_closed_index(d, timeframe)
    if idx_now < 0:
        return d, None, None, None
    pdh, pdl = d.at[idx_now, "_pdh"], d.at[idx_now, "_pdl"]
    if pd.isna(pdh) or pd.isna(pdl):
        return d, None, None, None
    pdh, pdl = float(pdh), float(pdl)
    return d, pdh, pdl, (pdh + pdl) / 2.0


def compute_prev_week_levels(df: pd.DataFrame, timeframe: str = "1hour"):
    """PWH/PWL/EQ from the completed UTC ISO week immediately before the week
    containing the latest closed candle."""
    if df is None or len(df) < 2 or "timestamp" not in df.columns:
        return None, None, None, None
    d = df.copy()
    d["_dt"] = _timestamp_to_datetime(d)
    d = d.dropna(subset=["_dt"]).reset_index(drop=True)
    if d.empty:
        return d, None, None, None
    for col in ("high", "low"):
        d[col] = pd.to_numeric(d[col], errors="coerce")
    iso = d["_dt"].dt.isocalendar()
    d["_period"] = iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)
    grp = d.groupby("_period", sort=True).agg(_hi=("high", "max"), _lo=("low", "min"))
    grp["_pwh"] = grp["_hi"].shift(1)
    grp["_pwl"] = grp["_lo"].shift(1)
    d = d.merge(grp[["_pwh", "_pwl"]], left_on="_period", right_index=True, how="left")
    idx_now = _last_closed_index(d, timeframe)
    if idx_now < 0:
        return d, None, None, None
    pwh, pwl = d.at[idx_now, "_pwh"], d.at[idx_now, "_pwl"]
    if pd.isna(pwh) or pd.isna(pwl):
        return d, None, None, None
    pwh, pwl = float(pwh), float(pwl)
    return d, pwh, pwl, (pwh + pwl) / 2.0


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
        d, hi, lo, eq = compute_prev_week_levels(df, timeframe)
        return d, hi, lo, eq, "PWH/PWL", source
    d, hi, lo, eq = compute_prev_day_levels(df, timeframe)
    return d, hi, lo, eq, "PDH/PDL", source


# ============================================================================
# ۴) تشخیص سوئینگ (فرکتال ساده)
# ============================================================================

def compute_swings(df: pd.DataFrame, lookback: int = 3,
                  min_wick_atr: float = 0.15, min_wick_pct: float = 0.0005,
                  min_volume_ratio: float = 1.02, require_volume: bool = True) -> pd.DataFrame:
    """Confirmed fractal swings with minimum wick and meaningful-volume gates."""
    d = _ensure_atr(df)
    n = len(d)
    highs = pd.to_numeric(d["high"], errors="coerce").values
    lows = pd.to_numeric(d["low"], errors="coerce").values
    opens = pd.to_numeric(d["open"], errors="coerce").values
    closes = pd.to_numeric(d["close"], errors="coerce").values
    atrs = pd.to_numeric(d.get("atr", pd.Series(np.nan, index=d.index)), errors="coerce").values
    vrs = pd.to_numeric(d.get("volume_ratio", pd.Series(1.0, index=d.index)), errors="coerce").fillna(1.0).values
    swing_high = np.zeros(n, dtype=bool)
    swing_low = np.zeros(n, dtype=bool)
    for i in range(lookback, n - lookback):
        h_win = highs[i - lookback:i + lookback + 1]
        l_win = lows[i - lookback:i + lookback + 1]
        if np.isnan(h_win).any() or np.isnan(l_win).any():
            continue
        rng = max(highs[i] - lows[i], 1e-12)
        body_hi = max(opens[i], closes[i])
        body_lo = min(opens[i], closes[i])
        upper_wick = max(0.0, highs[i] - body_hi)
        lower_wick = max(0.0, body_lo - lows[i])
        atr = float(atrs[i]) if np.isfinite(atrs[i]) else 0.0
        wick_floor = max(float(min_wick_pct) * max(abs(closes[i]), 1e-12),
                         float(min_wick_atr) * atr if atr > 0 else 0.0)
        volume_ok = (not require_volume) or float(vrs[i]) >= float(min_volume_ratio)
        # A candidate must first pass the local fractal + rejection + volume gates.
        # We also require meaningful displacement away from the candidate. This
        # prevents tiny local pivots from being promoted to structural swings.
        left_hi = float(np.nanmax(h_win[:lookback])) if lookback else highs[i]
        right_hi = float(np.nanmax(h_win[lookback + 1:])) if lookback else highs[i]
        left_lo = float(np.nanmin(l_win[:lookback])) if lookback else lows[i]
        right_lo = float(np.nanmin(l_win[lookback + 1:])) if lookback else lows[i]
        excursion_hi = max(0.0, highs[i] - min(left_hi, right_hi))
        excursion_lo = max(0.0, max(left_lo, right_lo) - lows[i])
        displacement_floor = max(0.25 * atr, float(min_wick_pct) * max(abs(closes[i]), 1e-12) * 2.0)
        high_local = highs[i] == h_win.max() and (h_win == highs[i]).sum() == 1
        low_local = lows[i] == l_win.min() and (l_win == lows[i]).sum() == 1
        if high_local:
            swing_high[i] = (upper_wick >= wick_floor and volume_ok and excursion_hi >= displacement_floor)
        if low_local:
            swing_low[i] = (lower_wick >= wick_floor and volume_ok and excursion_lo >= displacement_floor)
    d["swing_high"] = swing_high
    d["swing_low"] = swing_low

    # Structure-aware validation: keep only pivots that participate in a
    # meaningful HH/HL or LH/LL progression. The first valid pivot of a type
    # is retained as an anchor; subsequent pivots receive a structure score.
    d["swing_structure_score"] = 0.0
    prev_hi = None
    prev_lo = None
    for i in range(n):
        if swing_high[i]:
            if prev_hi is None:
                score = 1.0
            else:
                delta = abs(highs[i] - highs[prev_hi]) / max(float(atrs[i]) if np.isfinite(atrs[i]) and atrs[i] > 0 else 1.0, 1e-12)
                score = 1.0 + min(delta, 3.0)
            d.at[d.index[i], "swing_structure_score"] = max(float(d.at[d.index[i], "swing_structure_score"]), score)
            prev_hi = i
        if swing_low[i]:
            if prev_lo is None:
                score = 1.0
            else:
                delta = abs(lows[i] - lows[prev_lo]) / max(float(atrs[i]) if np.isfinite(atrs[i]) and atrs[i] > 0 else 1.0, 1e-12)
                score = 1.0 + min(delta, 3.0)
            d.at[d.index[i], "swing_structure_score"] = max(float(d.at[d.index[i], "swing_structure_score"]), score)
            prev_lo = i
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
    # Adaptive penalty: first repeat touch is only a light warning; repeated
    # touches increase the penalty with diminishing returns and never erase a
    # high-quality core setup by themselves.
    max_pen = float(pw.get("fakeout_history", 15.0))
    min_pen = float(pw.get("fakeout_min_penalty", 2.0))
    decay = max(1.0, float(pw.get("fakeout_decay_touches", 4.0)))
    penalty_total = 0.0 if extra_touches <= 0 else min(max_pen, min_pen + (max_pen - min_pen) * (1.0 - np.exp(-extra_touches / decay)))
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
    ارزیابی هم‌زمان ۱۰ سناریوی B1..B5 / S1..S5 روی df (که باید ستون‌های
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
    d = compute_swings(d, lookback, cfg.get("min_swing_wick_atr", 0.20), cfg.get("min_swing_wick_pct", 0.0008), cfg.get("min_swing_volume_ratio", 1.05), cfg.get("require_swing_volume", True))
    idx_now = _last_closed_index(d, timeframe)  # آخرین کندل کاملاً بسته‌شده
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

    # HARD DEAD-ZONE GATE:
    # Being touched once earlier in the session is NOT enough.  A signal in the
    # middle of the range must be causally tied to a RECENT boundary interaction
    # (touch/sweep/break). This prevents stale events from authorizing mid-range
    # entries hours later.
    in_dead_zone = (lo_level * (1 + tol) < close_now < hi_level * (1 - tol))
    last_hi_event = max(hi_touch_idxs + hi_break_idxs) if (hi_touch_idxs or hi_break_idxs) else None
    last_lo_event = max(lo_touch_idxs + lo_break_idxs) if (lo_touch_idxs or lo_break_idxs) else None
    event_age = max(1, int(cfg.get("max_entry_event_age_bars", 9)))
    recent_hi_event = last_hi_event is not None and (idx_now - last_hi_event) <= event_age
    recent_lo_event = last_lo_event is not None and (idx_now - last_lo_event) <= event_age
    if in_dead_zone and not (recent_hi_event or recent_lo_event):
        return None

    def recent_event(idx):
        return idx is not None and (idx_now - idx) <= event_age

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
            "tp1": eq, "tp1_pct": 50.0, "tp2": hi_level if direction == "BUY" else lo_level,
            "tp2_pct": 30.0, "tp3": (hi_level + (hi_level - lo_level) * cfg["extension_atr_mult"])
                if direction == "BUY" else (lo_level - (hi_level - lo_level) * cfg["extension_atr_mult"]),
            "tp3_pct": 20.0,
            "level_label": label, "reasons": reasons,
        })

    # ------------------------------------------------------------------
    # سناریوهای خرید (BUY)
    # ------------------------------------------------------------------
    recent_swing_lows = _recent_confirmed_swings(d, idx_now, lookback, "swing_low", search_back)
    bullish_confirm_now = _is_bullish_confirm(curr_row, min_body)

    # B1: سوییپ PDH/PWH سپس سوییپ PDL/PWL و بازگشت
    if first_hi is not None and first_lo is not None and first_hi < first_lo and recent_event(last_lo_event) and bullish_confirm_now and recent_swing_lows:
        swing_idx = recent_swing_lows[-1]
        swing_price = _safe_float(d.at[swing_idx, "low"])
        if swing_price <= lo_level * (1 + tol * 5) and idx_now - swing_idx <= lookback + 3:
            sl = min(swing_price, lo_level) - atr_now * cfg["sl_atr_buffer"]
            add_candidate("B1", "BUY", sl, hi_level, eq,
                           f"سوییپ {label.split('/')[0]} سپس سوییپ {label.split('/')[1]} و بازگشت صعودی",
                           len(lo_touch_idxs))

    # B3: سوییپ مستقیم PDL/PWL بدون عبور قبلی از PDH/PWH
    if first_lo is not None and (first_hi is None or first_hi > first_lo) and recent_event(last_lo_event) and bullish_confirm_now and recent_swing_lows:
        swing_idx = recent_swing_lows[-1]
        swing_price = _safe_float(d.at[swing_idx, "low"])
        if swing_price <= lo_level * (1 + tol * 5) and idx_now - swing_idx <= lookback + 3:
            sl = min(swing_price, lo_level) - atr_now * cfg["sl_atr_buffer"]
            add_candidate("B3", "BUY", sl, hi_level, eq,
                           f"سوییپ مستقیم {label.split('/')[1]} بدون عبور قبلی از {label.split('/')[0]}",
                           len(lo_touch_idxs))

    # B4: ری‌کلیم EQ پس از سوییپ PDL/PWL
    if first_lo is not None and recent_event(last_lo_event):
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
    if first_hi is not None and recent_event(last_hi_event) and bullish_confirm_now:
        swings_after = [i for i in recent_swing_lows if i > first_hi]
        if len(swings_after) >= 2 and _safe_float(d.at[swings_after[-1], "low"]) > _safe_float(d.at[swings_after[-2], "low"]):
            if idx_now - swings_after[-1] <= lookback + 3:
                swing_price = _safe_float(d.at[swings_after[-1], "low"])
                sl = swing_price - atr_now * cfg["sl_atr_buffer"]
                add_candidate("B2", "BUY", sl, hi_level, None,
                               "سوییپ مقاومت + پولبک مضاعف با کف بالاتر (سوئینگ نزدیک مقاومت)",
                               len(hi_touch_idxs))

    # B5: بریک‌اند‌ریتست PDH/PWH (شکسته‌شدن مقاومت و تبدیل آن به حمایت)
    if hi_break_idxs and recent_event(last_hi_event) and bullish_confirm_now:
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

    # ------------------------------------------------------------------
    # سناریوهای فروش (SELL) — دقیقاً معکوس سناریوهای خرید
    # ------------------------------------------------------------------
    recent_swing_highs = _recent_confirmed_swings(d, idx_now, lookback, "swing_high", search_back)
    bearish_confirm_now = _is_bearish_confirm(curr_row, min_body)

    # S1: سوییپ PDL/PWL سپس سوییپ PDH/PWH و بازگشت
    if first_lo is not None and first_hi is not None and first_lo < first_hi and recent_event(last_hi_event) and bearish_confirm_now and recent_swing_highs:
        swing_idx = recent_swing_highs[-1]
        swing_price = _safe_float(d.at[swing_idx, "high"])
        if swing_price >= hi_level * (1 - tol * 5) and idx_now - swing_idx <= lookback + 3:
            sl = max(swing_price, hi_level) + atr_now * cfg["sl_atr_buffer"]
            add_candidate("S1", "SELL", sl, lo_level, eq,
                           f"سوییپ {label.split('/')[1]} سپس سوییپ {label.split('/')[0]} و بازگشت نزولی",
                           len(hi_touch_idxs))

    # S3: سوییپ مستقیم PDH/PWH بدون عبور قبلی از PDL/PWL
    if first_hi is not None and (first_lo is None or first_lo > first_hi) and recent_event(last_hi_event) and bearish_confirm_now and recent_swing_highs:
        swing_idx = recent_swing_highs[-1]
        swing_price = _safe_float(d.at[swing_idx, "high"])
        if swing_price >= hi_level * (1 - tol * 5) and idx_now - swing_idx <= lookback + 3:
            sl = max(swing_price, hi_level) + atr_now * cfg["sl_atr_buffer"]
            add_candidate("S3", "SELL", sl, lo_level, eq,
                           f"سوییپ مستقیم {label.split('/')[0]} بدون عبور قبلی از {label.split('/')[1]}",
                           len(hi_touch_idxs))

    # S4: ری‌کلیم EQ پس از سوییپ PDH/PWH
    if first_hi is not None and recent_event(last_hi_event):
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
    if first_lo is not None and recent_event(last_lo_event) and bearish_confirm_now:
        swings_after = [i for i in recent_swing_highs if i > first_lo]
        if len(swings_after) >= 2 and _safe_float(d.at[swings_after[-1], "high"]) < _safe_float(d.at[swings_after[-2], "high"]):
            if idx_now - swings_after[-1] <= lookback + 3:
                swing_price = _safe_float(d.at[swings_after[-1], "high"])
                sl = swing_price + atr_now * cfg["sl_atr_buffer"]
                add_candidate("S2", "SELL", sl, lo_level, None,
                               "سوییپ حمایت + پولبک مضاعف با سقف پایین‌تر (سوئینگ نزدیک حمایت)",
                               len(lo_touch_idxs))

    # S5: بریک‌اند‌ریتست PDL/PWL (شکسته‌شدن حمایت و تبدیل آن به مقاومت)
    if lo_break_idxs and recent_event(last_lo_event) and bearish_confirm_now:
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

    if not candidates:
        return None

    best = max(candidates, key=lambda c: c["total_score"])
    return best
