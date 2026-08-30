# -*- coding: utf-8 -*-
"""
strategy.py  —  بازنویسی کامل (صفر تا صد) بر اساس استراتژی PDH / EQ / PDL
==========================================================================
طبق درخواست صریح کاربر، تمام منطق قبلی تصمیم‌گیری این فایل (dynamic v2،
liquidity sweep، structure flip، trend/breakout/mean-reversion قدیمی و…)
کنار گذاشته شده و با یک موتور واحد در ماژول `pdh_eq_pdl_engine.py`
جایگزین شده است که ۱۲ سناریوی B1..B6 / S1..S6 فایل استراتژی کاربر را
هم‌زمان ارزیابی و بهترین‌شان را بر اساس امتیاز انتخاب می‌کند.

نگاشت تایم‌فریم → منبع سطح مرجع (طبق درخواست کاربر):
    5min , 15min  → PDH/PDL/EQ روزانه
    1hour, 4hour  → PWH/PWL/EQ هفتگی

این فایل، امضای (signature) و خروجی توابعی که `bot.py`، `ui.py`،
`backtest.py` و `v3_backtest.py` از آن‌ها استفاده می‌کنند را کاملاً حفظ
کرده تا نیازی به تغییر بقیه‌ی پروژه نباشد؛ فقط «مغز» تصمیم‌گیری عوض شده.
"""

import numpy as np
import pandas as pd

from pdh_eq_pdl_engine import (
    ENGINE_DEFAULTS,
    LEVEL_SOURCE_BY_TIMEFRAME,
    evaluate_scenarios,
    compute_prev_day_levels,
    compute_prev_week_levels,
    compute_prev_month_levels,
    get_reference_levels,
    structural_htf_trend,
)

# کتابخانه جدید تشخیص سوینگ (رجکشن سه‌کندلی / فراکتال کلاسیک / ساختار بازار
# BOS-ChoCH) — به‌صورت کاملاً اختیاری و افزودنی به پروژه اضافه شده است.
# پیش‌فرض تمام سوییچ‌های مربوط به آن در STRATEGY_DEFAULTS خاموش (False) است،
# یعنی رفتار موتور اصلی PDH/EQ/PDL دقیقاً مثل قبل باقی می‌ماند مگر کاربر
# صراحتاً یکی از قابلیت‌های زیر را فعال کند.
try:
    from swing_detection import (
        analyze_swings as _sw_analyze_swings,
        SwingDetectionError as _SwingDetectionError,
    )
    _SWING_LIB_AVAILABLE = True
except Exception:  # ماژول اختیاری است؛ نبودش نباید کل بات را خراب کند
    _SWING_LIB_AVAILABLE = False


# ============================================================================
# ابزارهای عمومی (بدون تغییر نسبت به نسخه قبلی، مورد استفاده در چند تابع)
# ============================================================================

def _safe_float(value, default=0.0):
    try:
        x = float(value)
        return x if np.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _cfg(config):
    return config if isinstance(config, dict) else STRATEGY_DEFAULTS


def _flt(filters):
    return filters if isinstance(filters, dict) else FILTER_DEFAULTS


# ============================================================================
# گرید لگاریتمی (بدون تغییر - فقط برای نمایش/کمک تصمیم، وابسته به هیچ استراتژی نیست)
# ============================================================================

def compute_log_grid_levels(df, base_steps=20, lookback=None):
    """گرید لگاریتمی متعادل بدون تکیه بر سقف/کف بیات کل تاریخچه."""
    if df is None or df.empty or len(df) < 2:
        return []
    d = df.tail(int(lookback)) if lookback and int(lookback) > 1 else df
    chart_low = float(pd.to_numeric(d['low'], errors='coerce').min())
    chart_high = float(pd.to_numeric(d['high'], errors='coerce').max())
    if not np.isfinite(chart_low) or not np.isfinite(chart_high) or chart_low <= 0 or chart_high <= chart_low:
        return []
    n_intervals = max(1, int(base_steps) * 2)
    ratio = (chart_high / chart_low) ** (1.0 / n_intervals)
    return [{'step': i / 2.0, 'price': chart_low * (ratio ** i)} for i in range(n_intervals + 1)]


def nearest_grid_level(price, levels):
    """نزدیک‌ترین سطح شبکه به یک قیمت مشخص: (level_dict, فاصله به‌درصد)."""
    if not levels or price is None or price <= 0:
        return None, None
    best = min(levels, key=lambda lv: abs(lv['price'] - price))
    dist_pct = abs(best['price'] - price) / price * 100.0
    return best, dist_pct


FILTER_DEFAULTS = {
    "volume_filter": True,
    "trailing_stop": True,
    "candlestick_filter": True,
    "no_short_filter": True,
    "no_buy_filter": False,
}


def compute_swing_stop(df, is_long, lookback=12, buffer_atr=0.40, confirm_candles=2, buffer_wick_pct=0.0015):
    """
    استاپ‌لاس بر اساس آخرین سوینگ معاملاتی تاییدشده (نه فاصله ثابت ATR)، به‌اضافه‌ی
    یک بافر ایمنی پشت سوینگ که مانع استاپ‌اوت با نویز/دم‌های عادی بازار می‌شود.

    بافر نهایی = بزرگ‌تر از (ATR × buffer_atr) و (قیمت سوینگ × buffer_wick_pct)؛
    یعنی هم نوسان مطلق بازار (ATR) و هم نوسان نسبی دم کندل‌ها (wick %) لحاظ
    می‌شود تا یک دم کوچک معمولی باعث خروج زودهنگام از معامله نشود.

    این تابع مستقل از موتور سناریو است و توسط bot.py هم مستقیماً برای
    مدیریت تریلینگ‌استاپ پوزیشن‌های باز استفاده می‌شود.

    خروجی: (sl, swing_level) یا (None, None) اگر داده کافی نبود.
    """
    if df is None or df.empty:
        return None, None
    need = lookback + confirm_candles
    if len(df) < need + 1:
        return None, None
    if "atr" not in df.columns:
        return None, None
    atr = pd.to_numeric(df["atr"], errors="coerce").iloc[-1]
    if not np.isfinite(atr) or atr <= 0:
        return None, None
    end = -confirm_candles if confirm_candles > 0 else None
    start = -(lookback + confirm_candles)
    window = df.iloc[start:end]
    if window.empty:
        return None, None
    if is_long:
        swing = float(pd.to_numeric(window["low"], errors="coerce").min())
        if not np.isfinite(swing):
            return None, None
        buffer_dist = max(atr * buffer_atr, swing * float(buffer_wick_pct))
        sl = swing - buffer_dist
    else:
        swing = float(pd.to_numeric(window["high"], errors="coerce").max())
        if not np.isfinite(swing):
            return None, None
        buffer_dist = max(atr * buffer_atr, swing * float(buffer_wick_pct))
        sl = swing + buffer_dist
    return float(sl), float(swing)


# ============================================================================
# compute_swing_stop_v2 / get_swing_confluence
# لایه اختیاری ادغام کتابخانه swing_detection.py با موتور فعلی.
# امضا و خروجی compute_swing_stop_v2 عیناً مطابق compute_swing_stop قدیمی
# است: (sl, swing_level) یا (None, None) — تا بتواند بدون تغییر در محل
# فراخوانی (bot.py) جایگزین آن شود.
# ============================================================================

def compute_swing_stop_v2(df, is_long, atr_period=14, atr_buffer_mult=0.25, pct_buffer=0.0015):
    """
    نسخه پیشرفته‌ی compute_swing_stop با استفاده از کتابخانه swing_detection:
    به‌جای کمینه/بیشینه‌ی یک پنجره‌ی ثابت (lookback)، آخرین سوینگ *واقعی و
    تاییدشده* (رجکشن سه‌کندلی یا فراکتال کلاسیک، هرکدام جدیدتر بود) را پیدا
    کرده و SL را با بافر max(ATR×ضریب, قیمت×درصد) پشت آن قرار می‌دهد.

    خروجی کاملاً سازگار با compute_swing_stop قدیمی: (sl, swing_level) یا
    (None, None) در صورت نبود داده کافی/سوینگ معتبر/عدم دسترسی به کتابخانه.
    این تابع هرگز exception پرتاب نمی‌کند (مناسب حلقه زنده بات).
    """
    if not _SWING_LIB_AVAILABLE:
        return None, None
    if df is None or df.empty or len(df) < 5:
        return None, None
    try:
        payload = _sw_analyze_swings(
            df,
            include_structural=False,
            atr_period=int(atr_period),
            atr_buffer_mult=float(atr_buffer_mult),
            pct_buffer=float(pct_buffer),
        )
    except Exception:
        return None, None

    if not payload.get("ok"):
        return None, None

    direction = "long" if is_long else "short"
    for sig in payload.get("signals", []):  # جدیدترین سیگنال‌ها اول هستند
        if sig.get("valid") and sig.get("direction") == direction:
            sl = sig.get("stop_loss")
            swing_price = (sig.get("source") or {}).get("price")
            if sl is None or swing_price is None:
                continue
            if not (np.isfinite(sl) and np.isfinite(swing_price)):
                continue
            return float(sl), float(swing_price)

    return None, None


def get_swing_confluence(df, is_long, lookback_bars=5):
    """
    بررسی صرفاً اطلاعاتی (بدون اثر بر تصمیم‌گیری) اینکه آیا نزدیک‌ترین رویداد
    ساختاری (BOS یا ChoCH) در N کندل اخیر هم‌جهت با سیگنال فعلی بوده یا نه.

    خروجی: dict {"aligned": bool, "event_type": str|None, "event_direction": str|None}
    هرگز exception پرتاب نمی‌کند؛ در نبود کتابخانه/داده کافی aligned=False برمی‌گرداند.
    """
    out = {"aligned": False, "event_type": None, "event_direction": None}
    if not _SWING_LIB_AVAILABLE:
        return out
    if df is None or df.empty or len(df) < 5:
        return out
    try:
        payload = _sw_analyze_swings(df, include_rejection=False, include_classic=False, include_structural=True)
    except Exception:
        return out
    if not payload.get("ok"):
        return out

    events = payload.get("structural_events", [])
    if not events:
        return out

    wanted_dir = "bullish" if is_long else "bearish"
    for ev in reversed(events[-max(1, int(lookback_bars)):]):
        if ev.get("direction") == wanted_dir:
            out["aligned"] = True
            out["event_type"] = ev.get("event")
            out["event_direction"] = ev.get("direction")
            return out
    return out


# ============================================================================
# STRATEGY_DEFAULTS / presetهای هر تایم‌فریم
# کلیدهایی که bot.py مستقیماً (خارج از این فایل) برای مدیریت پوزیشن می‌خواند
# عیناً حفظ شده‌اند: swing_lookback, swing_confirm_candles, swing_buffer_atr،
# swing_buffer_wick_pct, cooldown_seconds, tp_tier_pct.
#
# توجه: مدیریت هوشمند/زودهنگام پوزیشن باز (weakness_exit_*،
# early_loss_weakness_exit_*، atr_early_exit_*) طبق درخواست صریح کاربر کاملاً
# حذف شده است. تنها راه خروج از معامله باز اکنون این‌هاست: برخورد به یکی از
# پله‌های TP، برخورد به SL (که پس از پله‌ی اول به Break-even و سپس با سوینگ
# ساختاری تریل می‌شود)، یا بستن اجباری پایان‌روز برای تایم‌فریم‌های ۵/۱۵ دقیقه
# (که مربوط به قانون rollover است، نه «مدیریت هوشمند»).
# ============================================================================

STRATEGY_DEFAULTS = {
    # --- آستانه‌های موتور سناریو PDH/EQ/PDL ---
    "min_trade_score": ENGINE_DEFAULTS["min_score_to_trade"],
    "min_rr": ENGINE_DEFAULTS["min_rr"],
    "swing_lookback_fractal": ENGINE_DEFAULTS["swing_lookback_fractal"],
    "touch_tolerance_pct": ENGINE_DEFAULTS["touch_tolerance_pct"],
    "break_confirm_pct": ENGINE_DEFAULTS["break_confirm_pct"],
    "min_confirm_body_ratio": ENGINE_DEFAULTS["min_confirm_body_ratio"],
    "sl_atr_buffer": ENGINE_DEFAULTS["sl_atr_buffer"],
    "sl_atr_buffer_tight": ENGINE_DEFAULTS["sl_atr_buffer_tight"],
    "extension_atr_mult": ENGINE_DEFAULTS["extension_atr_mult"],
    "base_scores": dict(ENGINE_DEFAULTS["base_scores"]),
    "bonus_weights": dict(ENGINE_DEFAULTS["bonus_weights"]),
    "penalty_weights": dict(ENGINE_DEFAULTS["penalty_weights"]),
    "penalty_scale_by_code": dict(ENGINE_DEFAULTS["penalty_scale_by_code"]),
    "swing_min_wick_atr_ratio": ENGINE_DEFAULTS["swing_min_wick_atr_ratio"],
    "swing_min_volume_ratio": ENGINE_DEFAULTS["swing_min_volume_ratio"],

    "max_sl_atr": 4.0,           # سقف مطلق فاصله SL بر حسب ATR (فیوز ایمنی، نه بخشی از سناریوها)
    "min_sl_percent": 0.005,
    "max_fee_risk_ratio": 0.20,
    "cooldown_seconds": 1200,

    # --- استاپ‌لاس بر اساس سوینگ ساختاری (برای تریلینگ در bot.py) ---
    "swing_lookback": 12,
    "swing_confirm_candles": 2,
    "swing_buffer_atr": 0.40,
    "swing_buffer_wick_pct": 0.0015,  # بافر نسبی (٪ از قیمت سوینگ) در کنار بافر ATR

    # --- پلکان سه‌مرحله‌ای TP (Tier1=EQ/میانه، Tier2=مرز مقابل، Tier3=اکستنشن) ---
    "tp_tier_pct": [0.50, 0.30, 0.20],

    "v2_enabled": False,  # موتور قدیمی v2 کاملاً غیرفعال است؛ فقط برای سازگاری با کد قدیمی نگه داشته شده

    # --- فیلتر روند ساختاری تایم بالاتر (HTF) — طبق تصمیم مشترک با کاربر ---
    # سخت‌گیر: سیگنال خلاف روند ساختاری HTF (از سوئینگ، نه اندیکاتور) بلاک
    # می‌شود، مگر ستاپ «استثنایی» باشد (امتیاز و RR بالا، هم‌راستا با همان
    # آستانه‌های same_direction_guard در bot.py).
    "htf_trend_filter_enabled": True,
    "htf_trend_exception_score": 80.0,
    "htf_trend_exception_rr": 1.60,

    # --- فال‌بک چندسطحی برای ۵/۱۵ دقیقه (هفتگی/ماهانه، طبق تصمیم مشترک) ---
    "multi_level_source_fallback_enabled": True,
    "monthly_level_fallback_enabled": True,

    # --- کتابخانه جدید تشخیص سوینگ (swing_detection.py) ---
    # use_advanced_swing_stop: اگر True باشد، تریلینگ‌استاپ پوزیشن باز
    #   (_check_swing_trailing_stop در bot.py) به‌جای compute_swing_stop قدیمی
    #   (پنجره ثابت lookback) از compute_swing_stop_v2 استفاده می‌کند که SL را
    #   بر اساس آخرین سوینگ *واقعی* تاییدشده (رجکشن سه‌کندلی یا فراکتال
    #   کلاسیک) محاسبه می‌کند، نه صرفاً کمینه/بیشینه یک پنجره ثابت.
    #   نسخه‌ی قدیمی (پیش‌فرض قبلی) صرفاً کمینه/بیشینه‌ی یک پنجره‌ی غلتان
    #   N-کندلی بود، نه یک سوینگ واقعی — پنجره هر اسکن سر می‌خورد و می‌تواند
    #   SL را فقط به‌خاطر بیرون افتادن یک کندل عمیق از پنجره تنگ‌تر کند، حتی
    #   وقتی معامله هرگز سود نکرده. این دقیقاً همان علتی بود که باعث استاپ
    #   زودهنگام معامله‌ی XLM شد (mfe_r=0 اما trailing_activated=true؛
    #   بررسی مشترک با کاربر). به همین دلیل پیش‌فرض به True تغییر کرد.
    "use_advanced_swing_stop": True,
    "advanced_swing_atr_period": 14,
    "advanced_swing_atr_buffer_mult": 0.25,
    "advanced_swing_pct_buffer": 0.0015,

    # --- قفل‌سود پله‌ای بر مبنای R + تریلینگ ATR فعال ---
    # جایگزین سبک‌تر PROFIT_LADDERS_R قدیمی (که قبلاً به درخواست کاربر حذف
    # شده بود)، این‌بار بر پایه‌ی شواهد واقعی: معاملاتی با سود شناور تا
    # +۱.۵/+۲.۵R، در نبود قفل سود پیش از TP1، تقریباً کل سود را پس می‌دادند
    # (حتی به ضرر کامل تبدیل می‌شدند). فرمت ladder: [(آستانه‌ی R, مقدار قفل‌شده به R), ...]
    "profit_lock_r_ladder": [(0.5, 0.0), (1.0, 0.30), (1.5, 0.70), (2.0, 1.10)],
    "atr_trail_start_r": 0.8,   # از این مقدار R به بعد، تریلینگ ATR فعال هم کنار قفل پله‌ای فعال می‌شود
    "atr_trail_mult": 1.8,      # ضریب ATR برای فاصله‌ی SL از قیمت لحظه‌ای در تریلینگ فعال

    # use_swing_confluence_info: اگر True باشد، build_trade_plan یک فیلد
    #   اطلاعاتیِ صرف "swing_confluence" به خروجی پلن اضافه می‌کند که نشان
    #   می‌دهد آخرین رویداد ساختاری (BOS/ChoCH) هم‌جهت با سیگنال بوده یا نه.
    #   این فیلد صرفاً نمایشی/گزارشی است و روی امتیاز، جهت یا رد/قبول شدن
    #   معامله هیچ تاثیری ندارد (طبق همان اصل حفظ رفتار موتور اصلی).
    "use_swing_confluence_info": False,
    "swing_confluence_lookback_bars": 5,
}

# presetهای مخصوص هر تایم‌فریم — نگاشت سطح مرجع دقیقاً طبق درخواست کاربر:
#   5min/15min → روزانه (PDH/PDL)   |   1hour/4hour → هفتگی (PWH/PWL)
TIMEFRAME_STRATEGY_PRESETS = {
    "5min": {
        "level_source": "daily",
        "min_trade_score": 62.0, "min_rr": 1.05,
        "cooldown_seconds": 900,
    },
    "15min": {
        "level_source": "daily",
        "min_trade_score": 63.0, "min_rr": 1.10,
        "cooldown_seconds": 1200,
        # --- تنظیم دقیق مخصوص ۱۵ دقیقه (درخواست کاربر) ---
        # بافر SL بزرگ‌تر از پیش‌فرض سراسری (۰.۳۵) برای جلوگیری از استاپ‌اوت
        # زودهنگام روی دم‌های نویزی نسبت به تایم‌فریم‌های کوتاه‌تر (۵ دقیقه).
        "sl_atr_buffer": 0.45,
        # آستانه حجم سخت‌گیرانه‌تر از پیش‌فرض سراسری (۰.۶۰) برای تایید سوییپ
        # نقدینگی روی ۱۵ دقیقه؛ سوئینگ‌هایی با حجم کمتر از ۱.۲× میانگین ۲۰
        # کندل دیگر مبنای سوییپ/ورود قرار نمی‌گیرند.
        "swing_min_volume_ratio": 1.2,
    },
    "1hour": {
        "level_source": "weekly",
        "min_trade_score": 65.0, "min_rr": 1.15,
        "cooldown_seconds": 1800,
    },
    "4hour": {
        "level_source": "weekly",
        "min_trade_score": 65.0, "min_rr": 1.20,
        "cooldown_seconds": 3600,
    },
}

TIMEFRAME_PARAM_ADJUST = TIMEFRAME_STRATEGY_PRESETS


def get_timeframe_preset(timeframe):
    return {**STRATEGY_DEFAULTS, **TIMEFRAME_STRATEGY_PRESETS.get(timeframe, {})}


def get_strategy_params(strategy_config=None):
    return {**STRATEGY_DEFAULTS, **(_cfg(strategy_config) or {})}


# ============================================================================
# calculate_indicators — بدون تغییر نسبت به نسخه قبلی.
# bot.py این تابع را در چندین جای مستقل (چارت، تشخیص رژیم بازار، تریلینگ‌استاپ،
# evaluate_trend_weakness) صدا می‌زند؛ ستون‌های خروجی باید همان‌ها بمانند.
# ============================================================================

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df.copy()
    df = df.copy()
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        return df
    for col in required:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    if len(df) < 60:
        return df

    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()

    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["tr"] = tr
    df["atr"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    plus_sm = plus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    minus_sm = minus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    plus_di = 100 * plus_sm / (df["atr"] + 1e-12)
    minus_di = 100 * minus_sm / (df["atr"] + 1e-12)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-12)
    df["plus_di"] = plus_di
    df["minus_di"] = minus_di
    df["adx"] = dx.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = avg_gain / (avg_loss + 1e-12)
    df["rsi"] = 100 - (100 / (1 + rs))

    df["channel_high"] = df["high"].rolling(20, min_periods=20).max().shift(1)
    df["channel_low"] = df["low"].rolling(20, min_periods=20).min().shift(1)
    df["volume_ma20"] = df["volume"].rolling(20, min_periods=20).mean()
    df["volume_ratio"] = df["volume"] / (df["volume_ma20"] + 1e-12)
    df["candle_body"] = (df["close"] - df["open"]).abs()
    df["candle_range"] = (df["high"] - df["low"]).clip(lower=1e-12)
    df["body_ratio"] = df["candle_body"] / df["candle_range"]
    return df


# ============================================================================
# _compute_prev_day_levels — امضای قدیمی حفظ شده (bot.py مستقیماً ایمپورت می‌کند)
# ============================================================================
#
# رفع باگ (بند ۱ درخواست کاربر - چارت‌های TAO/QNT): موتور جدید ستون دوره‌ی
# روزانه را `_period` نام‌گذاری می‌کند، اما مصرف‌کننده‌ی قدیمی این تابع در
# bot.py (تابع chart) به‌دنبال ستونی به نام `_date` می‌گشت. چون این ستون هرگز
# وجود نداشت، شرط فیلتر «فقط کندل‌های امروز» همیشه false می‌شد و چارت به‌جای
# کندل‌های واقعی همان روز/سشن جاری، صرفاً ۶۰ کندل آخر خام را نشان می‌داد — که
# می‌توانست باعث دیده‌شدن PDH/PDL به‌صورت نامتناسب/معکوس با کندل‌های چارت شود.
# اینجا یک ستون `_date` (برابر با `_period`) هم اضافه می‌شود تا مصرف‌کننده‌ی
# قدیمی بدون نیاز به تغییر در بقیه‌ی bot.py درست کار کند.

def _compute_prev_day_levels(df):
    d, pdh, pdl, _eq = compute_prev_day_levels(df)
    if d is not None and "_period" in d.columns and "_date" not in d.columns:
        d = d.copy()
        d["_date"] = d["_period"]
    return d, pdh, pdl


# ============================================================================
# evaluate_trend_weakness حذف شد (طبق درخواست کاربر، بند ۳): این تابع صرفاً
# برای منطق «مدیریت هوشمند/خروج زودهنگام» پوزیشن باز استفاده می‌شد که کاملاً
# حذف شده. bot.py دیگر آن را ایمپورت نمی‌کند.
# ============================================================================
# هسته‌ی جدید تصمیم‌گیری: یک بار موتور سناریو را اجرا می‌کند و بین
# get_signal_with_reason و build_trade_plan به اشتراک گذاشته می‌شود
# (به‌جای کش کردن، هر بار دوباره محاسبه می‌شود تا هیچ ریسک ناهم‌خوانی
# بین سیگنال و پلن معامله وجود نداشته باشد؛ محاسبه سبک و سریع است).
# ============================================================================

def _run_engine(df, timeframe, strategy_config=None):
    return evaluate_scenarios(df, timeframe or "5min", strategy_config)


# ============================================================================
# فال‌بک چندسطحی برای ۵ و ۱۵ دقیقه — طبق تصمیم مشترک با کاربر
# ============================================================================
# روزانه همیشه اولویت اول و پیش‌فرض است (تنها منبعی که واقعاً محک خورده). فقط
# وقتی داده‌ی روزانه هیچ ستاپ معتبری نداشت، هفتگیِ خودِ نماد (از روی همان
# market_data_dict['1d'] که برای فیلتر روند HTF گرفته می‌شود، بدون فراخوانی
# اضافه به صرافی) و در صورت نبود آن هم، ماهانه امتحان می‌شود. رقابت هم‌زمان
# بین منابع در کار نیست — زنجیره‌ی فال‌بک ترتیبی است.
def _run_engine_multi_source(df, timeframe, cfg, market_data_dict=None, diag=None):
    """خروجی: (best_dict_or_None, level_source_used_or_None)

    diag (اختیاری): در جا با تشخیص آخرین منبع سطح که واقعاً امتحان شد پر
    می‌شود (روزانه، یا در صورت فال‌بک، هفتگی/ماهانه) — برای لاگ/آدیت دقیق‌تر
    دلیل «no_signal» به‌جای پیام کلی قبلی.
    """
    best = evaluate_scenarios(df, timeframe or "5min", cfg, diag=diag)
    if best:
        return best, LEVEL_SOURCE_BY_TIMEFRAME.get(timeframe, "daily")
    if timeframe not in ("5min", "15min") or not bool(cfg.get("multi_level_source_fallback_enabled", True)):
        return None, None
    daily = (market_data_dict or {}).get("1d")
    if daily is None or daily.empty:
        return None, None
    _, pwh, pwl, weq = compute_prev_week_levels(daily)
    if pwh is not None and pwl is not None and pwh > pwl:
        cand = evaluate_scenarios(df, timeframe, cfg, level_override=("weekly", pwh, pwl, weq), diag=diag)
        if cand:
            return cand, "weekly"
    if bool(cfg.get("monthly_level_fallback_enabled", True)):
        _, pmh, pml, meq = compute_prev_month_levels(daily)
        if pmh is not None and pml is not None and pmh > pml:
            cand = evaluate_scenarios(df, timeframe, cfg, level_override=("monthly", pmh, pml, meq), diag=diag)
            if cand:
                return cand, "monthly"
    return None, None


def _format_reason(best):
    if not best:
        return ""
    parts = [
        f"{best['code']}",
        f"امتیاز {best['total_score']}/100 (پایه {best['base_score']} + بونوس {best['bonus']} − جریمه {best['penalty']})",
        best["reasons"][0] if best.get("reasons") else "",
    ]
    if best.get("tp_partial"):
        hi_lbl, lo_lbl = best["level_label"].split("/")
        final_lbl = hi_lbl if best["direction"] == "BUY" else lo_lbl
        parts.append(f"TP پله‌ای: EQ={best['tp_partial']:.10g} سپس {final_lbl}={best['tp']:.10g}")
    extra_notes = best["reasons"][1:]
    if extra_notes:
        parts.append(" | ".join(extra_notes))
    return " | ".join([p for p in parts if p])


# ============================================================================
# فیلتر روند ساختاری تایم بالاتر (HTF) — طبق تصمیم مشترک با کاربر
# ============================================================================
# داده‌ی هفتگی جدا از صرافی گرفته نمی‌شود؛ از همان کندل‌های روزانه‌ای که در
# htf_specs (bot.py) fetch می‌شوند با resample ساخته می‌شود (سبک‌تر و بدون
# نیاز به تغییر لایه‌ی دریافت داده).
def _resample_weekly_from_daily(daily_df):
    if daily_df is None or daily_df.empty or "timestamp" not in daily_df.columns:
        return None
    d = daily_df[["timestamp", "open", "high", "low", "close"]].copy()
    d["timestamp"] = pd.to_numeric(d["timestamp"], errors="coerce")
    d = d.dropna(subset=["timestamp"])
    if d.empty:
        return None
    # واحد timestamp همیشه یکسان نیست: bot.py (زنده) ثانیه می‌دهد، اما
    # backtest.py (ccxt) میلی‌ثانیه. تشخیص خودکار برای سازگاری با هر دو.
    unit = "ms" if d["timestamp"].median() > 10**12 else "s"
    d["_dt"] = pd.to_datetime(d["timestamp"], unit=unit, utc=True)
    d = d.set_index("_dt").sort_index()
    w = d.resample("W-MON", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()
    if len(w) < 8:
        return None
    return w.reset_index(drop=True)


def _resolve_htf_trend(timeframe, market_data_dict):
    """
    روند ساختاری تایم بالاتر خودِ همین نماد را برمی‌گرداند ('BULLISH'/'BEARISH'/None).
    فقط وقتی دو منبع مستقل (نه دو محاسبه‌ی روی یک داده) هم‌رای باشند، جهت
    قطعی برگردانده می‌شود؛ در غیر این صورت خنثی (None، یعنی بدون بلاک):
        5min/15min → روزانه + هفتگیِ resample‌شده از روزانه
        1hour      → ۴ساعته + روزانه
        4hour      → روزانه + هفتگیِ resample‌شده از روزانه
    """
    md = market_data_dict or {}
    daily = md.get("1d")
    if timeframe in ("5min", "15min", "4hour"):
        t1 = structural_htf_trend(daily) if daily is not None else None
        weekly = _resample_weekly_from_daily(daily) if daily is not None else None
        t2 = structural_htf_trend(weekly) if weekly is not None else None
    elif timeframe == "1hour":
        t1 = structural_htf_trend(daily) if daily is not None else None
        t2 = structural_htf_trend(md.get("4h"))
    else:
        return None
    if t1 and t2 and t1 == t2:
        return t1
    return None


# ============================================================================
# get_signal_with_reason — امضای قدیمی کاملاً حفظ شده؛ محتوا صفر تا صد جدید.
# ============================================================================

def get_signal_with_reason(df_primary, market_data_dict=None, timeframe_mode="single",
                            timeframe="5min", strategy_type="dynamic", filters=None,
                            strategy_config=None, regime=None, live_price=None,
                            defer_quality_gate=False, diag_out=None):
    """
    سیگنال نهایی بر اساس موتور سناریوهای PDH/EQ/PDL (یا PWH/PWL/EQ برای ۱ و ۴
    ساعته). پارامترهای strategy_type/regime/live_price در تصمیم‌گیری اثر
    ندارند (طبق درخواست کاربر: صرف‌نظر از استراتژی انتخاب‌شده در منو، همیشه
    همین موتور واحد اجرا می‌شود). market_data_dict دیگر بی‌اثر نیست: از آن
    برای فیلتر روند ساختاری تایم بالاتر خودِ نماد استفاده می‌شود (طبق تصمیم
    مشترک با کاربر — نه اندیکاتور، بلکه سوئینگ ساختاری HTF).

    diag_out: اختیاری، دیکشنری خالی که کالر پاس می‌دهد و در جا با جزئیات
    تشخیصی موتور (گیت رد شدن، تعداد سوینگ high/low شناسایی‌شده در دوره جاری،
    منبع سطح امتحان‌شده) پر می‌شود — برای لاگ/آدیت دقیق‌تر، بدون تغییر
    امضای بازگشتی قدیمی (signal, reason) که سایر کدها (bot.py/backtest.py)
    به آن وابسته‌اند.

    خروجی: (signal: 'BUY'|'SELL'|None, reason: str)
    """
    cfg = {**STRATEGY_DEFAULTS, **(_cfg(strategy_config) or {})}
    diag = {}
    best, level_source_used = _run_engine_multi_source(df_primary, timeframe, cfg, market_data_dict, diag=diag)
    if diag_out is not None:
        diag_out.update(diag)
    if not best:
        gate = diag.get('gate', 'unknown')
        swing_hc = diag.get('swing_high_count')
        swing_lc = diag.get('swing_low_count')
        swings_txt = ""
        if swing_hc is not None or swing_lc is not None:
            swings_txt = f" (سوینگ‌های شناسایی‌شده در دوره جاری: {swing_hc or 0} سقف، {swing_lc or 0} کف)"
        if gate == 'dead_zone_no_touch':
            return None, (
                "قیمت هنوز وسط رنج است و به PDH/PDL (یا معادل هفتگی/ماهانه) برخورد یا شکستی نداشته — "
                f"dead-zone{swings_txt}"
            )
        if gate == 'no_scenario_matched':
            return None, (
                "قیمت به سطح برخورد کرده اما هیچ‌کدام از ۱۴ سناریوی PDH/EQ/PDL با سوینگ‌های موجود تطبیق نداد"
                f"{swings_txt}"
            )
        if gate in ('insufficient_data', 'invalid_levels', 'invalid_atr'):
            return None, f"داده/سطوح کافی برای ارزیابی سناریوها در دسترس نبود ({gate})"
        return None, "هیچ‌کدام از ۱۴ سناریوی PDH/EQ/PDL (یا PWH/PWL/EQ، یا فال‌بک هفتگی/ماهانه) تایید نشد"
    min_score = float(cfg.get("min_trade_score", ENGINE_DEFAULTS["min_score_to_trade"]))
    if best["total_score"] < min_score:
        return None, f"بهترین سناریو {best['code']} بود اما امتیاز کافی نبود ({best['total_score']}/100 < {min_score:.0f})"

    if bool(cfg.get("htf_trend_filter_enabled", True)):
        htf_trend = _resolve_htf_trend(timeframe, market_data_dict)
        is_counter_trend = (
            (best["direction"] == "SELL" and htf_trend == "BULLISH") or
            (best["direction"] == "BUY" and htf_trend == "BEARISH")
        )
        if is_counter_trend:
            approx_risk = abs(_safe_float_local(best["entry"]) - _safe_float_local(best["sl"]))
            approx_reward = abs(_safe_float_local(best["tp"]) - _safe_float_local(best["entry"]))
            approx_rr = (approx_reward / approx_risk) if approx_risk > 0 else 0.0
            exceptional = (
                best["total_score"] >= float(cfg.get("htf_trend_exception_score", 80.0)) and
                approx_rr >= float(cfg.get("htf_trend_exception_rr", 1.60))
            )
            if not exceptional:
                return None, (
                    f"سیگنال {best['code']} ({best['direction']}) خلاف روند ساختاری تایم بالاتر "
                    f"({htf_trend}) بود و بلاک شد — امتیاز/RR کافی برای استثنا نبود"
                )

    return best["direction"], _format_reason(best)


def _safe_float_local(v, default=0.0):
    try:
        f = float(v)
        return f if f == f else default  # NaN check
    except Exception:
        return default


# ============================================================================
# build_trade_plan — امضای قدیمی کاملاً حفظ شده؛ محتوا صفر تا صد جدید.
# ============================================================================

def build_trade_plan(df, signal, strategy_config=None, strategy_type="dynamic",
                      strategy_timeframe="5min", grid_levels=None, setup_index=None,
                      live_price=None, market_data_dict=None, filters=None, regime=None,
                      defer_quality_gate=False):
    if df is None or len(df) < 50 or signal not in ("BUY", "SELL"):
        return None, "داده کافی برای طراحی معامله وجود ندارد"

    cfg = {**STRATEGY_DEFAULTS, **(_cfg(strategy_config) or {})}
    best, level_source_used = _run_engine_multi_source(df, strategy_timeframe, cfg, market_data_dict)
    if not best or best["direction"] != signal:
        return None, "سناریوی برنده با سیگنال هم‌خوانی ندارد؛ معامله رد شد"

    entry = _safe_float(best["entry"])
    sl = _safe_float(best["sl"])
    tp = _safe_float(best["tp"])
    if entry <= 0 or sl <= 0 or tp <= 0:
        return None, "سطوح قیمتی سناریو نامعتبر است"

    risk_dist = (entry - sl) if signal == "BUY" else (sl - entry)
    if risk_dist <= 0 or not np.isfinite(risk_dist):
        return None, "فاصله حد ضرر معتبر نیست (SL در سمت اشتباه قیمت ورود قرار دارد)"

    # فیوز ایمنی: سقف مطلق فاصله SL بر حسب ATR (مستقل از منطق سناریوها)
    atr = _safe_float(df.iloc[-2].get("atr")) if "atr" in df.columns else 0.0
    max_sl_atr = float(cfg.get("max_sl_atr", 4.0))
    if atr > 0 and risk_dist > atr * max_sl_atr:
        return None, f"فاصله حد ضرر بیش از سقف مجاز است ({risk_dist / atr:.2f}× ATR > {max_sl_atr:.2f}× ATR)"

    min_sl_pct = float(cfg.get("min_sl_percent", 0.005))
    if risk_dist / entry < min_sl_pct:
        if signal == "BUY":
            sl = entry * (1.0 - min_sl_pct)
        else:
            sl = entry * (1.0 + min_sl_pct)
        risk_dist = abs(entry - sl)

    # فیوز ایمنی: هدف (tp) باید واقعاً *جلوتر* از قیمت ورود در جهت معامله باشد.
    # محاسبه‌ی rr با abs() این جهت را نادیده می‌گرفت؛ در نتیجه اگر (به‌ندرت، مثلاً
    # در B5/S5 با یک کندل تاییدِ خیلی بزرگ) هدف محاسبه‌شده عملاً پشت سر قیمت
    # ورود بیفتد، معامله‌ای با هدف نامعتبر (بدون پاداش واقعی) رد نمی‌شد. این
    # دقیقاً همان پیش‌نیازی است که ساخت پلکان سه‌مرحله‌ای TP هم به آن متکی است.
    target_ahead = (tp > entry) if signal == "BUY" else (tp < entry)
    if not target_ahead:
        return None, f"هدف سناریو {best['code']} جلوتر از قیمت ورود نیست (احتمالاً کندل تایید خیلی بزرگ بوده)؛ معامله رد شد"

    rr = abs(tp - entry) / risk_dist
    min_rr = float(cfg.get("min_rr", ENGINE_DEFAULTS["min_rr"]))
    if rr < min_rr:
        return None, f"R:R کافی نیست ({rr:.2f}R < {min_rr:.2f}R) برای سناریوی {best['code']}"

    min_score = float(cfg.get("min_trade_score", ENGINE_DEFAULTS["min_score_to_trade"]))
    if best["total_score"] < min_score:
        return None, f"امتیاز سناریو {best['code']} کافی نیست ({best['total_score']}/100 < {min_score:.0f})"

    quality_label = ("عالی" if best["total_score"] >= 90 else
                      "خوب" if best["total_score"] >= 78 else
                      "قابل قبول" if best["total_score"] >= min_score else "ضعیف")

    tp1, tp2, tp3, tier_pcts = _build_tp_ladder(entry, tp, signal, best, cfg)

    plan = {
        "entry": entry, "sl": float(sl), "tp": float(tp3),
        "score": int(round(best["total_score"])),
        "quality_label": quality_label,
        "rr": float(rr),
        "target_r": float(rr),
        "risk_atr": float(risk_dist / atr) if atr > 0 else None,
        "atr": atr,
        "scenario_code": best["code"],
        "level_source": "weekly" if LEVEL_SOURCE_BY_TIMEFRAME.get(strategy_timeframe) == "weekly" else "daily",
        "swing_level": None,
        "structural_target": True,  # هدف، سطح ساختاری (PDH/PDL یا PWH/PWL) است نه RR ثابت
        "setup_family": f"pdh_eq_pdl_{best['code']}",
        "reason": _format_reason(best),
        # --- پلکان سه‌مرحله‌ای TP (طبق درخواست کاربر، بند ۴) ---
        # tp1: ۵۰٪ حجم دقیقاً روی EQ (یا نقطه‌ی میانی معادل وقتی EQ پشت سر
        #      گذاشته شده - مثل B5/S5)، سپس SL کل باقی‌مانده روی Break-even.
        # tp2: ۳۰٪ حجم روی مرز مقابل رنج (PDH برای Long / PDL برای Short).
        # tp3: ۲۰٪ باقی‌مانده برای اکستنشن رنج و اهداف بالاتر.
        "tp1": float(tp1), "tp2": float(tp2), "tp3": float(tp3),
        "tp1_pct": tier_pcts[0], "tp2_pct": tier_pcts[1], "tp3_pct": tier_pcts[2],
        "breakeven_after_tp1": True,
    }

    # --- لایه اختیاری/اطلاعاتی confluence سوینگ ساختاری (پیش‌فرض خاموش) ---
    # هیچ تاثیری روی امتیاز/جهت/رد یا قبول شدن معامله بالا ندارد؛ صرفاً یک
    # فیلد گزارشی برای نمایش در پیام تلگرام/لاگ اضافه می‌کند اگر کاربر
    # use_swing_confluence_info را در strategy_config فعال کرده باشد.
    if bool(cfg.get("use_swing_confluence_info", False)):
        try:
            plan["swing_confluence"] = get_swing_confluence(
                df, is_long=(signal == "BUY"),
                lookback_bars=int(cfg.get("swing_confluence_lookback_bars", 5)),
            )
        except Exception:
            plan["swing_confluence"] = {"aligned": False, "event_type": None, "event_direction": None}

    return plan, plan["reason"]


def _build_tp_ladder(entry, boundary_tp, signal, best, cfg):
    """
    پلکان سه‌مرحله‌ای TP را می‌سازد.

    دو حالت متفاوت وجود دارد:

    ۱) حالت عادی (اکثر سناریوها - B1/B2/B3/B4 و معادل Sell): ورود از یک مرز
       رنج انجام شده و هم EQ و هم مرز مقابل واقعاً *جلوتر* از قیمت ورود
       هستند. اینجا:
         tier1 = EQ رنج
         tier2 = مرز مقابل خام رنج (PDH برای Long / PDL برای Short)
         tier3 = اکستنشن فراتر از مرز مقابل (extension_atr_mult × عرض رنج)

    ۲) حالت بریک‌اند‌ریتست (B5/S5): چون ورود *پس از* شکستن مرز و ریتست آن رخ
       می‌دهد، هم مرز خام و هم EQ پشت سر قیمت ورود قرار دارند و دیگر اهداف
       معتبری برای «جلوتر از ورود» نیستند (استفاده از آن‌ها باعث می‌شد tier1
       به‌اشتباه *پشت* قیمت ورود بیفتد - یعنی در همان لحظه‌ی ورود لمس شده
       باشد). در این حالت، `boundary_tp` که موتور سناریو محاسبه کرده همان
       هدف اکستنشن نهایی است؛ کل مسیر entry→هدف نهایی به سه پله‌ی پیش‌رونده
       (۴۰٪ / ۷۰٪ / ۱۰۰٪ مسیر) تقسیم می‌شود تا هر سه پله واقعاً جلوتر از ورود
       باشند.

    خروجی: (tp1, tp2, tp3, [pct1, pct2, pct3])
    """
    is_long = signal == "BUY"
    tier_pcts = list(cfg.get("tp_tier_pct", [0.50, 0.30, 0.20]))
    if len(tier_pcts) != 3 or abs(sum(tier_pcts) - 1.0) > 1e-6:
        tier_pcts = [0.50, 0.30, 0.20]

    range_hi = best.get("range_hi"); range_lo = best.get("range_lo"); range_eq = best.get("range_eq")
    ext_mult = _safe_float(best.get("extension_atr_mult"), 0.50)
    final_target = float(boundary_tp)

    range_width = None
    if range_hi is not None and range_lo is not None and range_hi > range_lo:
        range_width = float(range_hi) - float(range_lo)

    raw_boundary = None
    if is_long and range_hi is not None:
        raw_boundary = float(range_hi)
    elif (not is_long) and range_lo is not None:
        raw_boundary = float(range_lo)

    boundary_ahead = raw_boundary is not None and (
        (is_long and raw_boundary > entry) or ((not is_long) and raw_boundary < entry)
    )
    eq_ahead = range_eq is not None and (
        (is_long and float(range_eq) > entry) or ((not is_long) and float(range_eq) < entry)
    )

    if boundary_ahead and eq_ahead:
        # حالت ۱: پلکان دقیقاً طبق تعریف کاربر (EQ → مرز مقابل → اکستنشن)
        tp2 = raw_boundary
        tp1 = float(range_eq)
        if range_width is not None:
            tp3 = tp2 + range_width * ext_mult if is_long else tp2 - range_width * ext_mult
        else:
            leg = abs(final_target - tp2) or abs(tp2 - entry)
            tp3 = tp2 + leg * ext_mult if is_long else tp2 - leg * ext_mult
    else:
        # حالت ۲ (بریک‌اند‌ریتست B5/S5 یا هر حالت دیگری که EQ/مرز پشت سر
        # گذاشته شده‌اند): سه پله‌ی پیش‌رونده بین entry و هدف نهایی، بدون
        # اتکا به EQ/مرز خام که دیگر جلوتر از قیمت نیستند.
        leg = final_target - entry
        tp1 = entry + leg * 0.40
        tp2 = entry + leg * 0.70
        tp3 = final_target

    return tp1, tp2, tp3, tier_pcts


# ============================================================================
# strategy_trend_following / strategy_breakout / strategy_mean_reversion
# این سه تابع فقط در دستور دستی «/analyze» به‌صورت تشخیصی استفاده می‌شوند
# (bot.py هر سه را صدا می‌زند و نتیجه‌شان را OR می‌کند). طبق درخواست کاربر
# هر سه اکنون از همان موتور واحد PDH/EQ/PDL استفاده می‌کنند تا نتیجه‌ی
# «/analyze» هم دقیقاً منعکس‌کننده‌ی منطق واقعی ورود ربات باشد.
# ============================================================================

def _infer_timeframe_from_df(df):
    """برای strategy_breakout/strategy_mean_reversion که ورودی timeframe ندارند."""
    try:
        ts = pd.to_numeric(df["timestamp"], errors="coerce").dropna()
        if len(ts) < 3:
            return "5min"
        unit = "ms" if float(ts.median()) > 1e12 else "s"
        dt = pd.to_datetime(ts, unit=unit, utc=True)
        delta_minutes = dt.diff().median().total_seconds() / 60.0
        if delta_minutes <= 7:
            return "5min"
        if delta_minutes <= 20:
            return "15min"
        if delta_minutes <= 90:
            return "1hour"
        return "4hour"
    except Exception:
        return "5min"


def strategy_trend_following(df, timeframe="5min", filters=None, strategy_config=None):
    return get_signal_with_reason(df, None, "single", timeframe, "dynamic", filters, strategy_config)


def strategy_breakout(df, filters=None, strategy_config=None):
    tf = _infer_timeframe_from_df(df) if df is not None else "5min"
    return get_signal_with_reason(df, None, "single", tf, "dynamic", filters, strategy_config)


def strategy_mean_reversion(df, filters=None, strategy_config=None):
    tf = _infer_timeframe_from_df(df) if df is not None else "5min"
    return get_signal_with_reason(df, None, "single", tf, "dynamic", filters, strategy_config)


# ============================================================================
# لایه‌ی سازگاری با اسکریپت قدیمی v3_backtest.py (موتور legacy v2 حذف شده).
# این توابع فقط برای جلوگیری از خطای Import هستند؛ v3_backtest.py دیگر
# استراتژی واقعی ربات را شبیه‌سازی نمی‌کند — به‌جای آن از backtest.py
# استفاده کنید که به‌طور کامل با موتور جدید سازگار است (به README مراجعه کنید).
# ============================================================================

def get_v2_config(strategy_config=None):
    return {**STRATEGY_DEFAULTS, **(_cfg(strategy_config) or {}), "v2_enabled": False}


def detect_market_regime(df, strategy_config=None):
    return "mixed"


def _select_v2_setup(df_primary, market_data_dict=None, timeframe="5min", filters=None,
                      strategy_config=None, regime=None, grid_levels=None, live_price=None,
                      defer_quality_gate=False):
    return None, None, "موتور legacy v2 حذف شده؛ از get_signal_with_reason/build_trade_plan جدید استفاده کنید"
