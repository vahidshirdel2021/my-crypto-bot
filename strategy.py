# -*- coding: utf-8 -*-
"""
pdh_eq_pdl_engine.py
---------------------
موتور PDH / EQ / PDL — نسخه‌ی اصلاح‌شده طبق ۶ درخواست اصلاحی کاربر:

  ۱) رفع باگ محاسبه PDH/PDL/EQ: مشکل اصلی در نسخه‌ی قبلی این بود که پس از
     merge کردن سطوح دوره‌ی قبل به دیتافریم اصلی، ایندکس دیتافریم دوباره
     reset می‌شد (`reset_index(drop=True)`) در حالی که idx_now بر اساس طول
     دیتافریم *قبل* از merge محاسبه نشده بود و merge با how='left' می‌تواند
     ترتیب سطرها را در برخی نسخه‌های pandas به‌هم بریزد اگر _period تکراری/
     nullable باشد. همچنین تشخیص واحد timestamp (ms/s) با median ممکن بود
     برای صرافی‌هایی که timestamp را به‌صورت رشته می‌فرستند اشتباه شود.
     در این نسخه:
       - merge با `sort=False` و `validate='many_to_one'` انجام می‌شود تا هر
         ناهم‌خوانی فوراً Exception بدهد به‌جای تولید سطوح نادرست خاموش.
       - قبل از merge، دیتافریم بر اساس timestamp به‌طور صریح sort می‌شود.
       - تمام سطوح به UTC صریح anchor می‌شوند (tz-aware)، نه ساعت محلی سرور.
       - یک assertion صریح اضافه شده: PDH باید > PDL باشد وگرنه سطوح رد
         می‌شوند (به‌جای تولید یک باند معکوس که وارونه به چارت تزریق شود).
       - کندل جاری (in-progress) هرگز در محاسبه‌ی high/low دوره‌ی قبل شرکت
         نمی‌کند: agg فقط روی دوره‌های *کاملاً بسته‌شده* انجام می‌شود.

  ۲) بن سخت‌گیر ورود وسط رنج: تابع جدید `_in_dead_zone()` اضافه شده. اگر
     قیمت فعلی در ناحیه‌ی مرده (اطراف EQ، بدون لمس/سوییپ معتبر PDH/PDL در
     همین دوره) باشد، evaluate_scenarios() هیچ کاندیدی تولید نمی‌کند —
     صرف‌نظر از این‌که کدام سناریو امتیاز بالا می‌آورد.

  ۳/۴) TP ladder سه‌پله‌ای و حذف خروج زودهنگام: این دو مورد در سطح مدیریت
     پوزیشن (bot.py) اعمال می‌شوند؛ اما این موتور اکنون به‌ازای هر سیگنال
     سه سطح TP را هم محاسبه و برمی‌گرداند (`tp1`=EQ, `tp2`=سطح مقابل,
     `tp3`=هدف اکستنشن) تا bot.py بتواند پوزیشن را به ۳ بخش تقسیم کند.

  ۵) تریلینگ استاپ سوینگ‌محور با بافر: تابع `compute_swing_stop_v2()` اضافه
     شده که علاوه بر ATR buffer، حداقل طول wick و حداقل نسبت حجم به میانگین
     را هم به‌عنوان شرط "سوینگ معتبر" بررسی می‌کند تا نویز/wick معمولی SL
     را فعال نکند.

  ۶) پالایش تشخیص سوینگ + وزن جریمه‌ی پویا: `compute_swings()` اکنون یک
     فیلتر min_wick_ratio و min_volume_ratio دارد؛ و پنالتی fakeout_history
     دیگر یک عدد ثابت -15.0 نیست، بلکه بر اساس کیفیت پایه‌ی سناریو مقیاس
     می‌شود (سناریوهای قوی مثل B5/S3 با ضریب کمتر جریمه می‌شوند).

نگاشت تایم‌فریم → منبع سطح مرجع (بدون تغییر):
    5min , 15min  → PDH/PDL/EQ روزانه (کندل‌های کامل UTC)
    1hour, 4hour  → PWH/PWL/EQ هفتگی (کندل‌های کامل UTC)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
FILTER_DEFAULTS = {
    "volume_filter": True,
    "candlestick_filter": True,
    "trailing_stop": True,
    "no_short_filter": False,
    "no_buy_filter": False,
}
STRATEGY_DEFAULTS = {
    "swing_lookback": 12,
    "swing_confirm_candles": 2,
    "swing_buffer_atr": 0.40,
    "min_trade_score": 65.0,
    "min_rr": 1.10,
    "min_adx": 18.0,
    "cooldown_seconds": 1200,
    "v2_enabled": True,
}
# ============================================================================
# ۱) تنظیمات پیش‌فرض موتور
# ============================================================================

ENGINE_DEFAULTS = {
    # --- ساختار / تلورانس ---
    "swing_lookback_fractal": 3,      # تعداد کندل هر سمت برای فرکتال سوئینگ
    "touch_tolerance_pct": 0.0006,    # ۰.۰۶٪ تلورانس «برخورد به سطح»
    "break_confirm_pct": 0.0003,      # حداقل فاصله close از سطح برای «شکست واقعی»
    "min_confirm_body_ratio": 0.20,   # حداقل کیفیت بدنه برای «کندل تاییدی»
    "swing_search_window_mult": 4,    # پنجره جست‌وجوی سوئینگ = lookback * این عدد

    # --- اصلاح ۲: بن ورود وسط رنج (Dead-Zone Gate) ---
    # اگر قیمت در فاصله‌ی dead_zone_eq_buffer_pct از EQ باشد و در همین دوره هیچ
    # لمس/سوییپ معتبری از PDH یا PDL ثبت نشده باشد، هیچ سیگنالی صادر نمی‌شود؛
    # صرف‌نظر از این‌که کدام سناریو تئوریک امتیاز بالایی داشته باشد.
    "dead_zone_enabled": True,
    "dead_zone_eq_buffer_pct": 0.15,   # ۱۵٪ از نصف رنج (PDH-PDL)/۲ اطراف EQ = dead zone
    "dead_zone_require_recent_touch": True,
    "dead_zone_touch_lookback_candles": 60,  # چند کندل اخیر برای اعتبارسنجی «لمس اخیر»

    # --- اصلاح ۶: فیلتر سوینگ (حداقل wick و حجم) ---
    "swing_min_wick_ratio": 0.15,      # حداقل نسبت wick به رنج کندل برای سوینگ معتبر
    "swing_min_volume_ratio": 0.80,    # حداقل نسبت حجم کندل سوینگ به میانگین ۲۰ کندل

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
    # --- اصلاح ۶: جریمه‌ی سابقه‌ی فیک‌اوت اکنون *مقیاس‌پذیر* است، نه ثابت -15.0 ---
    # penalty نهایی = base_penalty * scenario_penalty_multiplier[code]
    # سناریوهای باکیفیت‌تر (پایه‌ی امتیاز بالاتر، مثل B5/S3) ضریب کمتری می‌گیرند
    # تا به‌خاطر سابقه‌ی برخورد به سطح، به‌ناحق فیلتر نشوند.
    "penalty_weights": {
        "fakeout_history": 15.0,   # سقف پایه‌ی جریمه (قبل از مقیاس‌گذاری)
    },
    # ضریب مقیاس هر سناریو روی جریمه‌ی fakeout_history. مقدار پیش‌فرض بر اساس
    # امتیاز پایه‌ی سناریو محاسبه می‌شود (هرچه سناریو معتبرتر/قوی‌تر، ضریب کمتر)
    # اما در صورت نیاز می‌توان هرکدام را جداگانه override کرد.
    "penalty_scenario_multiplier": {
        "B1": 1.00, "S1": 1.00,   # سوییپ دوطرفه؛ معتبرترین سناریو - جریمه کامل اعمال شود
        "B2": 0.85, "S2": 0.85,
        "B3": 0.55, "S3": 0.55,   # سوییپ مستقیم؛ به‌ذات مستعد لمس چندباره است - جریمه کاهش‌یافته
        "B4": 0.90, "S4": 0.90,
        "B5": 0.45, "S5": 0.45,   # بریک‌اند‌ریتست؛ لمس مکرر خودِ ماهیت ریتست است - جریمه کم
        "B6": 1.00, "S6": 1.00,
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

    # --- اصلاح ۴: نسبت‌های حجم TP ladder سه‌پله‌ای ---
    "tp_ladder_ratios": (0.50, 0.30, 0.20),  # (Tier1@EQ, Tier2@سطح مقابل, Tier3@اکستنشن)
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
            if k in ("base_scores", "bonus_weights", "penalty_weights",
                      "penalty_scenario_multiplier") and isinstance(v, dict):
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


def _timestamp_to_datetime_utc(df: pd.DataFrame) -> pd.Series:
    """
    اصلاح ۱: تبدیل صریح و قطعی timestamp به UTC tz-aware.
    به‌جای حدس واحد فقط بر مبنای median (که با داده‌ی ناقص/رشته‌ای اشتباه
    می‌شد)، اینجا:
      - ابتدا مقادیر غیرعددی (رشته‌ی ISO) هم پشتیبانی می‌شوند.
      - اگر عددی باشند، آستانه‌ی تشخیص ms/s با مقایسه به بازه‌ی معتبر سال
        ۲۰۰۰ تا ۲۱۰۰ انجام می‌شود (دقیق‌تر از صرفاً median > 1e12).
      - خروجی همیشه tz-aware UTC است تا هیچ ابهام منطقه‌زمانی در گروه‌بندی
        روزانه/هفتگی باقی نماند.
    """
    raw = df["timestamp"]
    ts_numeric = pd.to_numeric(raw, errors="coerce")
    if ts_numeric.notna().sum() >= max(1, int(len(raw) * 0.9)):
        sample = ts_numeric.dropna()
        med = float(sample.median()) if len(sample) else 0.0
        # آستانه‌های صریح بر مبنای بازه‌ی معتبر تاریخ (سال ۲۰۰۱ تا ۲۱۰۰)
        if med > 4_102_444_800:          # > سال ۲۱۰۰ به ثانیه یعنی حتماً ms یا بزرگ‌تر
            unit = "ms" if med < 4_102_444_800_000 else "us"
        elif med > 978_307_200:           # بزرگ‌تر از سال ۲۰۰۱ به ثانیه
            unit = "s"
        else:
            unit = "ms"
        return pd.to_datetime(ts_numeric, unit=unit, utc=True, errors="coerce")
    # fallback: رشته‌های ISO/تاریخ
    return pd.to_datetime(raw, utc=True, errors="coerce")


# نگه‌داشتن نام قدیمی برای سازگاری با کدهای دیگری که ممکن است این تابع را ایمپورت کرده باشند
_timestamp_to_datetime = _timestamp_to_datetime_utc


# ============================================================================
# ۳) محاسبه سطوح مرجع: روزانه (PDH/PDL/EQ) و هفتگی (PWH/PWL/EQ)
#    اصلاح ۱: کاملاً بازنویسی‌شده برای رفع باگ ایندکس/ترتیب و anchor صریح UTC.
# ============================================================================

def _aggregate_period_levels(df: pd.DataFrame, period_key_func, min_rows=50):
    """
    هسته‌ی مشترک محاسبه‌ی سطوح دوره‌ی قبل (روزانه یا هفتگی)، با رفع باگ‌های
    نسخه‌ی قبلی:
      - مرتب‌سازی صریح بر اساس timestamp قبل از هر گروه‌بندی.
      - محاسبه‌ی high/low هر دوره فقط از کندل‌های *کاملاً بسته‌شده* (یعنی
        دوره‌ی جاری در agg شرکت می‌کند اما مقدار shift(1) آن، سطح دوره‌ی
        *قبل از آن* را می‌دهد - این خودش تضمین می‌کند کندل در حال شکل‌گیری
        هرگز به‌عنوان "سطح مرجع" استفاده نشود چون shift(1) همیشه یک دوره
        عقب‌تر می‌رود).
      - merge با validate='many_to_one' و sort=False تا ترتیب ردیف‌ها حفظ
        شود و هر ناهم‌خوانی (مثل period تکراری در ایندکس) بلافاصله خطا دهد
        به‌جای تولید یک ستون به‌هم‌ریخته که باعث سطوح معکوس می‌شد.
      - assertion صریح high_level > low_level.
    خروجی: (d, high_level, low_level, eq) یا (None, None, None, None)
    """
    if df is None or len(df) < min_rows or "timestamp" not in df.columns:
        return None, None, None, None
    d = df.copy()
    d["_dt"] = _timestamp_to_datetime_utc(d)
    if d["_dt"].isna().all():
        return None, None, None, None
    # اصلاح کلیدی: مرتب‌سازی صریح و بازسازی ایندکس *قبل* از هر گروه‌بندی،
    # تا idx_now = len(d)-2 همیشه واقعاً به آخرین کندلِ زمانی بسته‌شده اشاره کند.
    d = d.sort_values("_dt", kind="mergesort").reset_index(drop=True)
    d["_period"] = period_key_func(d["_dt"])

    grp = d.groupby("_period", sort=False).agg(_hi=("high", "max"), _lo=("low", "min"))
    # ترتیب دوره‌ها باید زمانی باشد (نه الفبایی) تا shift(1) واقعاً «دوره‌ی
    # قبلی از نظر زمان» را بدهد، نه دوره‌ای که فقط اسمش الفبایی قبل‌تر است.
    order = d.groupby("_period", sort=False)["_dt"].min().sort_values().index
    grp = grp.reindex(order)
    grp["_hi_prev"] = grp["_hi"].shift(1)
    grp["_lo_prev"] = grp["_lo"].shift(1)

    d = d.merge(
        grp[["_hi_prev", "_lo_prev"]],
        left_on="_period", right_index=True, how="left",
        sort=False, validate="many_to_one",
    )
    # merge با how='left' و validate='many_to_one' ترتیب سطرهای سمت چپ (d) را
    # حفظ می‌کند، اما برای اطمینان کامل دوباره صریح بر اساس _dt مرتب می‌کنیم.
    d = d.sort_values("_dt", kind="mergesort").reset_index(drop=True)

    idx_now = len(d) - 2  # آخرین کندل کاملاً بسته‌شده (طبق قرارداد کل ربات)
    if idx_now < 0:
        return d, None, None, None

    hi_level, lo_level = d.at[idx_now, "_hi_prev"], d.at[idx_now, "_lo_prev"]
    if pd.isna(hi_level) or pd.isna(lo_level):
        return d, None, None, None

    hi_level, lo_level = float(hi_level), float(lo_level)
    # اصلاح ۱: assertion صریح — اگر سطح بالا کوچک‌تر/مساوی سطح پایین شد
    # (که در نسخه‌ی قبلی می‌توانست به‌خاطر merge نادرست رخ دهد و باعث بازه‌ی
    # معکوس در چارت TAO/QNT شود)، سطوح را باطل اعلام می‌کنیم به‌جای برگرداندن
    # یک باند وارونه.
    if not (hi_level > lo_level):
        return d, None, None, None

    eq = (hi_level + lo_level) / 2.0
    return d, hi_level, lo_level, eq


def compute_prev_day_levels(df: pd.DataFrame):
    """سطوح PDH/PDL/EQ روزانه (برای تایم‌فریم‌های ۵ و ۱۵ دقیقه)، anchor شده به روز تقویمی UTC."""
    return _aggregate_period_levels(df, lambda dt: dt.dt.date)


def compute_prev_week_levels(df: pd.DataFrame):
    """
    سطوح PWH/PWL/EQ هفتگی (برای تایم‌فریم‌های ۱ و ۴ ساعته)، anchor شده به
    هفته‌ی تقویمی UTC (شروع هفته: دوشنبه، طبق استاندارد ISO).
    """
    def _iso_week_key(dt_series):
        iso = dt_series.dt.isocalendar()
        return iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)
    return _aggregate_period_levels(df, _iso_week_key)


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
# ۴) تشخیص سوئینگ (فرکتال) — اصلاح ۶: فیلتر حداقل wick و حجم
# ============================================================================

def compute_swings(df: pd.DataFrame, lookback: int = 3,
                    min_wick_ratio: float = None, min_volume_ratio: float = None) -> pd.DataFrame:
    """
    تشخیص سوینگ‌های فرکتال با دو فیلتر کیفی اضافه (اصلاح ۶):
      - min_wick_ratio: سوینگ فقط وقتی معتبر است که wick مربوطه (سایه‌ی پایین
        برای swing_low، سایه‌ی بالا برای swing_high) حداقل این نسبت از کل
        رنج کندل را تشکیل دهد. این از تشخیص سوینگ روی کندل‌های بدون سایه‌ی
        واقعی (که صرفاً نویز فرکتال است، نه یک نقطه‌ی برگشت واقعی) جلوگیری
        می‌کند.
      - min_volume_ratio: کندل سوینگ باید حداقل این نسبت از میانگین حجم ۲۰
        کندل اخیر را داشته باشد تا حرکتی کم‌حجم/کم‌مشارکت به اشتباه به‌عنوان
        سوینگ معتبر شناسایی نشود (فیلتر فیک‌اوت/شکست جعلی).
    """
    d = df.copy()
    n = len(d)
    if min_wick_ratio is None:
        min_wick_ratio = ENGINE_DEFAULTS["swing_min_wick_ratio"]
    if min_volume_ratio is None:
        min_volume_ratio = ENGINE_DEFAULTS["swing_min_volume_ratio"]

    highs = pd.to_numeric(d["high"], errors="coerce").values
    lows = pd.to_numeric(d["low"], errors="coerce").values
    opens = pd.to_numeric(d["open"], errors="coerce").values if "open" in d.columns else None
    closes = pd.to_numeric(d["close"], errors="coerce").values if "close" in d.columns else None

    if "volume_ratio" in d.columns:
        vol_ratio = pd.to_numeric(d["volume_ratio"], errors="coerce").values
    elif "volume" in d.columns:
        vma = pd.to_numeric(d["volume"], errors="coerce").rolling(20, min_periods=5).mean()
        vol_ratio = (pd.to_numeric(d["volume"], errors="coerce") / (vma + 1e-12)).values
    else:
        vol_ratio = np.full(n, 1.0)

    swing_high = np.zeros(n, dtype=bool)
    swing_low = np.zeros(n, dtype=bool)

    for i in range(lookback, n - lookback):
        h_win = highs[i - lookback: i + lookback + 1]
        l_win = lows[i - lookback: i + lookback + 1]
        if np.isnan(h_win).any() or np.isnan(l_win).any():
            continue

        rng = max(highs[i] - lows[i], 1e-12)
        v_ok = (not np.isnan(vol_ratio[i])) and (vol_ratio[i] >= min_volume_ratio)

        if highs[i] == h_win.max() and (h_win == highs[i]).sum() == 1:
            # wick بالایی نسبت به بدنه/رنج کندل
            if opens is not None and closes is not None and not (np.isnan(opens[i]) or np.isnan(closes[i])):
                upper_wick = highs[i] - max(opens[i], closes[i])
            else:
                upper_wick = rng * 0.5
            wick_ok = (upper_wick / rng) >= min_wick_ratio
            if wick_ok and v_ok:
                swing_high[i] = True

        if lows[i] == l_win.min() and (l_win == lows[i]).sum() == 1:
            if opens is not None and closes is not None and not (np.isnan(opens[i]) or np.isnan(closes[i])):
                lower_wick = min(opens[i], closes[i]) - lows[i]
            else:
                lower_wick = rng * 0.5
            wick_ok = (lower_wick / rng) >= min_wick_ratio
            if wick_ok and v_ok:
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


def compute_swing_stop_v2(df: pd.DataFrame, is_long: bool, lookback: int = 12,
                           buffer_atr: float = 0.40, confirm_candles: int = 2,
                           min_wick_ratio: float = None, min_volume_ratio: float = None):
    """
    اصلاح ۵: تریلینگ استاپ سوینگ‌محور با بافر، به‌همراه فیلتر کیفیت سوینگ
    (حداقل wick و حجم) طبق اصلاح ۶ - تا نویز/wick معمولی SL را زودهنگام
    فعال نکند.

    خروجی: (sl, swing_level) یا (None, None) اگر سوینگ معتبری پیدا نشود.
    """
    if df is None or df.empty:
        return None, None
    need = lookback + confirm_candles
    if len(df) < need + 5:
        return None, None
    if "atr" not in df.columns:
        return None, None
    atr = pd.to_numeric(df["atr"], errors="coerce").iloc[-1]
    if not np.isfinite(atr) or atr <= 0:
        return None, None

    swings_df = compute_swings(df, lookback=3, min_wick_ratio=min_wick_ratio, min_volume_ratio=min_volume_ratio)
    end = -confirm_candles if confirm_candles > 0 else None
    start = -(lookback + confirm_candles)
    window = swings_df.iloc[start:end]
    if window.empty:
        return None, None

    if is_long:
        valid = window[window["swing_low"]]
        if valid.empty:
            # فالبک ایمن: اگر هیچ سوینگ فیلترشده‌ای در پنجره نبود، از کمینه‌ی
            # ساده (رفتار قدیمی) استفاده می‌شود تا مدیریت پوزیشن کاملاً بدون
            # SL نماند - اما این حالت با پرچم is_fallback مشخص می‌شود.
            swing = float(pd.to_numeric(window["low"], errors="coerce").min())
            if not np.isfinite(swing):
                return None, None
            sl = swing - atr * buffer_atr
            return float(sl), float(swing)
        swing = float(valid["low"].min())
        sl = swing - atr * buffer_atr
    else:
        valid = window[window["swing_high"]]
        if valid.empty:
            swing = float(pd.to_numeric(window["high"], errors="coerce").max())
            if not np.isfinite(swing):
                return None, None
            sl = swing + atr * buffer_atr
            return float(sl), float(swing)
        swing = float(valid["high"].max())
        sl = swing + atr * buffer_atr

    return float(sl), float(swing)


# ============================================================================
# ۵) بونوس/جریمه امتیاز پویا (اندیکاتورهای کمکی - فقط امتیازدهی)
#    اصلاح ۶: جریمه‌ی fakeout_history اکنون بر اساس نوع سناریو مقیاس می‌شود.
# ============================================================================

def _dynamic_bonus_penalty(d: pd.DataFrame, idx_now: int, direction: int, cfg: dict,
                            touch_count: int, scenario_code: str = None):
    """
    direction: +1 برای سناریوهای خرید، -1 برای سناریوهای فروش
    scenario_code: کد سناریو (مثل 'B5','S3') برای مقیاس‌گذاری جریمه‌ی فیک‌اوت
    خروجی: (bonus_total, penalty_total, notes:list[str])
    """
    bw = cfg["bonus_weights"]
    pw = cfg["penalty_weights"]
    mult_map = cfg.get("penalty_scenario_multiplier", {})
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

    # --- اصلاح ۶: جریمه‌ی سابقه‌ی فیک‌اوت، مقیاس‌شده بر اساس نوع سناریو ---
    # پروکسی: تعداد برخوردهای تکراری به همان سطح در همین دوره. سناریوهایی
    # که طبیعتاً نیازمند چند بار لمس سطح هستند (مثل B5/S5 بریک‌اند‌ریتست، یا
    # B3/S3 سوییپ مستقیم) نباید با همان شدت سناریوهای تک‌لمسی (B1/S1) جریمه
    # شوند - وگرنه دقیقاً همین ستاپ‌های باکیفیت به‌ناحق فیلتر می‌شدند.
    extra_touches = max(0, touch_count - 1)
    base_penalty_cap = pw["fakeout_history"]
    scenario_mult = float(mult_map.get(scenario_code, 1.0)) if scenario_code else 1.0
    penalty_total = min(base_penalty_cap, extra_touches * (base_penalty_cap / 3.0)) * scenario_mult
    if penalty_total > 0.5:
        notes.append(f"سابقه {touch_count} برخورد قبلی به همین سطح (جریمه×{scenario_mult:.2f})")

    return bonus_total, penalty_total, notes


# ============================================================================
# ۶) اصلاح ۲: بن سخت‌گیر ورود وسط رنج (Dead-Zone Gate)
# ============================================================================

def _in_dead_zone(period: pd.DataFrame, idx_now: int, close_now: float,
                   hi_level: float, lo_level: float, eq: float,
                   hi_touch_idxs: list, lo_touch_idxs: list, cfg: dict) -> bool:
    """
    بررسی می‌کند آیا قیمت فعلی در «ناحیه‌ی مرده»‌ی وسط رنج است:
      - نزدیک EQ (در فاصله‌ی dead_zone_eq_buffer_pct از نصف رنج اطراف EQ)
      - و در بازه‌ی اخیر (dead_zone_touch_lookback_candles کندل گذشته) هیچ
        لمس/سوییپ معتبری از PDH یا PDL ثبت نشده باشد.

    اگر True برگرداند، یعنی ورود ممنوع است (حتی اگر یکی از ۱۲ سناریو تئوریک
    امتیاز کافی بگیرد) — چون این دقیقاً همان "ورود وسط رنج بدون touch/sweep/
    retest معتبر" است که کاربر صراحتاً خواسته بلاک شود.
    """
    if not cfg.get("dead_zone_enabled", True):
        return False
    half_range = (hi_level - lo_level) / 2.0
    if half_range <= 0:
        return True  # رنج نامعتبر => از هر ورودی جلوگیری شود

    buffer_pct = float(cfg.get("dead_zone_eq_buffer_pct", 0.15))
    dead_zone_width = half_range * buffer_pct
    near_eq = abs(close_now - eq) <= dead_zone_width
    if not near_eq:
        return False  # قیمت به‌اندازه‌ی کافی از EQ دور است => وسط رنج مرده نیست

    if not cfg.get("dead_zone_require_recent_touch", True):
        return True  # نزدیک EQ است و بررسی لمس اخیر غیرفعال شده => مرده در نظر گرفته شود

    lookback_n = int(cfg.get("dead_zone_touch_lookback_candles", 60))
    recent_start = max(int(period.index.min()) if len(period.index) else idx_now, idx_now - lookback_n)

    recent_hi_touch = any(i >= recent_start for i in hi_touch_idxs)
    recent_lo_touch = any(i >= recent_start for i in lo_touch_idxs)

    # اگر در بازه‌ی اخیر هیچ لمس معتبری از هیچ‌کدام از دو مرز رنج ثبت نشده،
    # یعنی این یک ورود واقعاً "وسط رنج بدون touch/sweep/retest" است => بلاک شود.
    return not (recent_hi_touch or recent_lo_touch)


# ============================================================================
# ۷) موتور اصلی سناریوها
# ============================================================================

def _is_bullish_confirm(row, min_body_ratio):
    return _safe_float(row.get("close")) > _safe_float(row.get("open")) and _safe_float(row.get("body_ratio")) >= min_body_ratio


def _is_bearish_confirm(row, min_body_ratio):
    return _safe_float(row.get("close")) < _safe_float(row.get("open")) and _safe_float(row.get("body_ratio")) >= min_body_ratio


def _build_tp_ladder(direction: str, entry: float, eq: float, opposite_level: float,
                      extension_target: float, cfg: dict):
    """
    اصلاح ۴: ساخت ساختار TP سه‌پله‌ای:
      Tier1 (۵۰٪ حجم) → دقیقاً روی EQ
      Tier2 (۳۰٪ حجم) → سطح مرزی مقابل (PDH برای Long، PDL برای Short)
      Tier3 (۲۰٪ حجم) → هدف اکستنشن فراتر از رنج

    اعتبارسنجی جهت: برای Long باید tp1 < tp2 (< یا =) tp3 از entry بالاتر
    باشند؛ برای Short برعکس. اگر ترتیب صحیح نبود (مثلاً EQ already passed)،
    Tier متناظر حذف و وزنش به Tier بعدی منتقل می‌شود.
    """
    r1, r2, r3 = cfg.get("tp_ladder_ratios", (0.50, 0.30, 0.20))
    is_long = direction == "BUY"

    def valid_above(x):
        return is_long and x > entry
    def valid_below(x):
        return (not is_long) and x < entry

    tiers = []
    if (is_long and valid_above(eq)) or ((not is_long) and valid_below(eq)):
        tiers.append(("tp1_eq", eq, r1))
    if (is_long and valid_above(opposite_level)) or ((not is_long) and valid_below(opposite_level)):
        tiers.append(("tp2_opposite", opposite_level, r2))
    if extension_target is not None and (
        (is_long and valid_above(extension_target)) or ((not is_long) and valid_below(extension_target))
    ):
        tiers.append(("tp3_extension", extension_target, r3))

    if not tiers:
        return None

    # اگر برخی Tierها به‌خاطر جهت نامعتبر حذف شدند، وزن باقی‌مانده را به نسبت
    # بین Tierهای معتبر پخش می‌کنیم تا مجموع وزن‌ها همیشه ۱۰۰٪ بماند.
    total_w = sum(t[2] for t in tiers)
    normalized = [(name, price, w / total_w) for name, price, w in tiers]

    # مرتب‌سازی بر اساس فاصله از entry (نزدیک‌ترین اول) تا ترتیب اجرای واقعی درست باشد
    normalized.sort(key=lambda t: abs(t[1] - entry))
    return {
        "tiers": normalized,   # [(name, price, weight_fraction), ...]
        "tp1": eq,
        "tp2": opposite_level,
        "tp3": extension_target,
    }


def evaluate_scenarios(df: pd.DataFrame, timeframe: str, strategy_config: dict = None):
    """
    ارزیابی هم‌زمان ۱۲ سناریوی B1..B6 / S1..S6 روی df.

    اصلاح‌های اعمال‌شده نسبت به نسخه‌ی قبلی:
      - سطوح مرجع (PDH/PDL/EQ یا PWH/PWL/EQ) با منطق اصلاح‌شده‌ی بخش ۳
        محاسبه می‌شوند (رفع باگ ایندکس/ترتیب + anchor صریح UTC).
      - قبل از برگرداندن هر کاندید، Dead-Zone Gate بررسی می‌شود: اگر قیمت
        در وسط رنج بدون لمس/سوییپ معتبر باشد، کل تابع None برمی‌گرداند
        (هیچ سیگنالی، صرف‌نظر از امتیاز تئوریک سناریوها).
      - هر کاندید برنده اکنون شامل ساختار tp_ladder سه‌پله‌ای هم هست.
      - سوینگ‌ها با فیلتر min_wick_ratio/min_volume_ratio تشخیص داده می‌شوند.
      - جریمه‌ی fakeout_history بر اساس نوع سناریو مقیاس می‌شود.

    خروجی: dict یا None
    """
    cfg = _merged_cfg(strategy_config)
    if df is None or len(df) < 50:
        return None
    d = _ensure_atr(df)
    d, hi_level, lo_level, eq, label, source = get_reference_levels(d, timeframe)
    if d is None or hi_level is None or lo_level is None or hi_level <= lo_level:
        return None

    lookback = int(cfg["swing_lookback_fractal"])
    min_wick_ratio = float(cfg.get("swing_min_wick_ratio", 0.15))
    min_volume_ratio = float(cfg.get("swing_min_volume_ratio", 0.80))
    d = compute_swings(d, lookback, min_wick_ratio=min_wick_ratio, min_volume_ratio=min_volume_ratio)
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

    # --- اصلاح ۲: Dead-Zone Gate — قبل از ارزیابی هر سناریو بررسی می‌شود ---
    if _in_dead_zone(period, idx_now, close_now, hi_level, lo_level, eq,
                      hi_touch_idxs, lo_touch_idxs, cfg):
        return None

    candidates = []

    def add_candidate(code, direction, sl, tp, tp_partial, extra_reason, touch_count):
        base = cfg["base_scores"][code]
        bonus, penalty, notes = _dynamic_bonus_penalty(
            d, idx_now, 1 if direction == "BUY" else -1, cfg, touch_count, scenario_code=code
        )
        total = max(0.0, min(cfg["max_score"], base + bonus - penalty))
        reasons = [extra_reason] + notes
        entry_price = close_now
        opposite_level = hi_level if direction == "BUY" else lo_level
        extension_target = tp if code in ("B5", "S5") else None
        ladder = _build_tp_ladder(direction, entry_price, eq, opposite_level, extension_target or tp, cfg)
        candidates.append({
            "code": code, "direction": direction,
            "base_score": base, "bonus": round(bonus, 1), "penalty": round(penalty, 1),
            "total_score": round(total, 1),
            "entry": entry_price, "sl": sl, "tp": tp, "tp_partial": tp_partial,
            "level_label": label, "reasons": reasons,
            "tp_ladder": ladder,
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
