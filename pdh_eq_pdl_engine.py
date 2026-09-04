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

# کتابخانه تشخیص سوینگ (swing_detection.py) — موتور شناسایی سوینگ اصلی این
# فایل اکنون از این کتابخانه استفاده می‌کند (به‌جای فرکتال سادهٔ قدیمی خودش).
# ایمپورت اختیاری/دفاعی: اگر فایل موجود نباشد یا خطا بدهد، موتور به‌صورت
# خودکار و بی‌صدا روی همان فرکتال قدیمی (legacy) fallback می‌کند تا هیچ‌وقت
# کل ربات به‌خاطر این ماژول از کار نیفتد.
try:
    from swing_detection import (
        detect_three_bar_rejection_swings as _sw_detect_rejection,
        detect_classic_three_bar_swings as _sw_detect_classic,
        SwingType as _SwingType,
        SwingDetectionError as _SwingDetectionError,
    )
    _SWING_LIB_AVAILABLE = True
except Exception:
    _SWING_LIB_AVAILABLE = False


# ============================================================================
# ۱) تنظیمات پیش‌فرض موتور (این‌ها از strategy.py هم قابل بازنویسی/override اند)
# ============================================================================

ENGINE_DEFAULTS = {
    # --- ساختار / تلورانس ---
    "swing_lookback_fractal": 3,      # تعداد کندل هر سمت برای فرکتال سوئینگ
    "touch_tolerance_pct": 0.0006,    # ۰.۰۶٪ تلورانس «برخورد به سطح»
    "break_confirm_pct": 0.0003,      # حداقل فاصله close از سطح برای «شکست واقعی»
    "min_confirm_body_ratio": 0.20,   # حداقل کیفیت بدنه برای «کندل تاییدی»
    "min_confirm_volume_ratio": 0.35,  # حداقل نسبت حجم کندل تاییدی به میانگین۲۰ (گیت ملایم/غیرسخت‌گیرانه؛ قبلاً فقط بونوس بود)
    "swing_search_window_mult": 4,    # پنجره جست‌وجوی سوئینگ = lookback * این عدد
    "swing_min_wick_atr_ratio": 0.15,  # حداقل دم کندل سوئینگ نسبت به ATR (فیلتر فیک‌اوت)
    "swing_min_volume_ratio": 0.60,    # حداقل نسبت حجم کندل سوئینگ به میانگین ۲۰ کندل

    # اگر True باشد، B1/B3 (و معادل Sell: S1/S3) علاوه بر کندل تاییدی، ملزم به
    # ری‌کلیم واقعی سطح هستند: کلوز کندل تاییدی باید دوباره بالای PDL/PWL
    # (برای Buy) یا پایین PDH/PWH (برای Sell) قرار گرفته باشد — نه فقط یک
    # کندل سبز/قرمز با بدنه کافی جایی که هنوز عمیقاً آن‌طرف سطح است. سراسری
    # روی هر ۴ تایم‌فریم اعمال می‌شود (طبق تصمیم کاربر)؛ در صورت نیاز بعداً از
    # طریق TIMEFRAME_STRATEGY_PRESETS قابل override به‌ازای هر تایم‌فریم است.
    "require_reclaim_confirm": True,

    # --- روش تشخیص سوینگ ---
    # "advanced": از کتابخانه swing_detection.py استفاده می‌شود؛ کندلی سوینگ
    #   شناخته می‌شود که هم در پنجره lookback اکسترمم باشد (مثل قبل) و هم با
    #   یکی از دو الگوی «فراکتال کلاسیک» یا «ریجکشن/ویک سه‌کندلی» کتابخانه
    #   جدید منطبق باشد. فیلترهای کیفیت قبلی (wick/ATR و حجم) هم‌چنان اعمال
    #   می‌شوند. اگر کتابخانه در دسترس نباشد یا خطا بدهد، به‌طور خودکار به
    #   "legacy" برمی‌گردد.
    # "legacy": همان فرکتال ساده‌ی قدیمی (بدون وابستگی به swing_detection.py).
    "swing_detection_mode": "advanced",

    # --- امتیاز پایه سناریوها (دقیقاً از فایل استراتژی) ---
    "base_scores": {
        "B1": 95, "B2": 90, "B3": 80, "B4": 75, "B5": 70, "B6": 60,
        "S1": 95, "S2": 90, "S3": 80, "S4": 75, "S5": 70, "S6": 60,
        # B7/S7: ادامه‌ی مومنتوم بدون ری‌تست (پامپ/دامپ) — پایین‌ترین امتیاز
        # پایه‌ی خانواده، چون بر خلاف B1..B5 هیچ لمس/ری‌تست واقعی به سطح
        # ندارد و صرفاً بر پایه فاصله + مومنتوم + یک پولبک کوتاه بنا شده.
        "B7": 55, "S7": 55,
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

    # --- ضریب کاهش جریمه‌ی فیک‌اوت به تفکیک سناریو ---
    # برخی ستاپ‌های باکیفیت (B5/S5: بریک‌اند‌ریتست، B3/S3: سوییپ مستقیم بدون
    # عبور قبلی، B2/S2: پولبک مضاعف) ذاتاً نیازمند چند برخورد متوالی به همان
    # سطح هستند (رفتار طبیعی و مثبت ستاپ، نه ریسک فیک‌اوت). جریمه‌ی ثابت -15
    # این ستاپ‌های معتبر را به‌ناحق زیر آستانه‌ی ورود (min_score_to_trade)
    # می‌انداخت. این ضرایب جریمه‌ی نهایی هر کد را کم می‌کنند (1.0 = بدون تغییر).
    "penalty_scale_by_code": {
        "B5": 0.35, "S5": 0.35,
        "B3": 0.65, "S3": 0.65,
        "B2": 0.60, "S2": 0.60,
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

    # --- B7/S7: ادامه مومنتوم پامپ/دامپ بدون ری‌تست ---
    "momentum_dist_atr_mult": 1.5,   # حداقل فاصله از سطح = این‌ضریب × ATR ...
    "momentum_dist_pct": 0.012,      # ... یا این‌درصد از سطح، هرکدام بزرگ‌تر بود (۱.۲٪)
    "momentum_tp_atr_mult": 2.5,     # هدف سود = قیمت فعلی ± این‌ضریب × ATR (چون سطح ساختاری جلوتری در کار نیست)
    "momentum_sl_max_atr_mult": 1.2, # سقف فاصله‌ی ریسک B7/S7 بر حسب ATR (جلوگیری از RR بد وقتی کندل پولبک بزرگ است)
    # --- فیکس جدید (بر اساس آدیت واقعی ۵ و ۱۵ دقیقه، شهریور ۱۴۰۵): سقف ریسک
    # به‌تنهایی مشکل RR را حل کرد اما مشکل اصلی‌تر را حل نکرده بود — «چه‌جور
    # پولبکی واقعاً یعنی ادامه‌ی مومنتوم» تعریف نشده بود. قبلاً هر کندل مخالف
    # جهت (حتی یک کندل بازگشتی قوی و پرحجم) به‌عنوان «پولبک کوتاه» پذیرفته
    # می‌شد؛ یعنی دقیقاً همان لحظه‌ای که مومنتوم واقعاً در حال برگشتن بود هم
    # سیگنال ادامه صادر می‌کرد. این دو فیلتر جدید این نقص را می‌بندند:
    "momentum_pullback_max_body_ratio": 0.35,  # پولبک باید کم‌بدنه/مکث باشد، نه کندل بازگشتی قوی
    "momentum_rsi_exhaustion_high": 78.0,       # B7: اگر RSI از این بالاتر باشد یعنی حرکت احتمالاً ته کشیده — رد می‌شود
    "momentum_rsi_exhaustion_low": 22.0,        # S7: اگر RSI از این پایین‌تر باشد یعنی حرکت احتمالاً ته کشیده — رد می‌شود

    # --- B7/S7 روشن/خاموش ---
    # طبق بررسی مشترک قبلی با کاربر روی داده‌ی معاملات واقعی، این دو سناریو
    # (پایین‌ترین امتیاز پایه‌ی خانواده) بیشترین سهم رد شدن به‌خاطر RR
    # ناکافی و بیشترین نرخ باخت (DASH/ZEC/ENA همه با SL) را داشتند؛ به همین
    # دلیل قبلاً موقتاً خاموش نگه داشته شده بود. سقف ریسک (momentum_sl_max_atr_mult)
    # فقط نیمی از مشکل بود؛ آدیت جدید (۷۹ معامله واقعی پیپر، شهریور ۱۴۰۵) با
    # پیش‌فرض «روشن» نشان داد B7 هنوز هم روی هر دو تایم‌فریم ۵ و ۱۵ دقیقه به‌طور
    # مستقل ضررده بود (وین‌ریت ~۱۶٪، مجموعاً −۲۸ دلار روی ۱۹ معامله). دو فیلتر
    # بالا (پولبک کم‌بدنه + رد فیلتر اشباع RSI) ریشه‌ی واقعی مشکل — ورود روی
    # کندل بازگشتی قوی یا حرکت از قبل ته‌کشیده — را می‌بندند. با این حال، طبق
    # همان شواهد، پیش‌فرض به‌صورت محافظه‌کارانه به «خاموش» برگردانده شده تا
    # داده‌ی جدید (با فیلترهای تازه) قبل از هر تصمیم دیگری جمع‌آوری شود —
    # کاربر می‌تواند از منوی «مدیریت روند معاملات» در bot.py (کلید session
    # سطح‌بالا b7_s7_enabled) آن را دستی روشن کند.
    "b7_s7_enabled": False,

    # --- B3/S3: سوییپ مستقیم بدون عبور قبلی از مرز مقابل ---
    # آدیت جدید نشان داد این خانواده (به‌خصوص S3: ۱۲ معامله، وین‌ریت ۱۶.۷٪،
    # −۲۶.۹۳ دلار) با تعریف «ری‌کلیم» فعلی بیش از حد سهل‌گیرانه سیگنال می‌داد:
    # long_reclaimed/short_reclaimed قبلاً فقط بررسی می‌کرد close حداکثر
    # touch_tolerance_pct آن‌طرف‌تر سطح نباشد — یعنی کلوزی که هنوز عملاً کمی
    # زیر/بالای سطح بود هم به‌اشتباه «ری‌کلیم موفق» شمرده می‌شد. دو پارامتر
    # زیر یک ری‌کلیم قاطع‌تر و یک کندل تاییدی باکیفیت‌تر مخصوص همین دو کد
    # (نه بقیه‌ی خانواده) الزامی می‌کنند:
    "direct_sweep_min_reclaim_margin_pct": 0.0015,  # کلوز باید حداقل این‌درصد *فراتر* از سطح باشد (نه فقط داخل تلورانس لمس)
    "direct_sweep_min_confirm_body_ratio": 0.35,    # کندل تاییدی B3/S3 باید بدنه‌ی محکم‌تری از حداقل عمومی (۰.۲۰) داشته باشد

    # --- خاموش/روشن کردن دستی هر ستاپ (منوی «ستاپ‌های معاملاتی» در bot.py) ---
    # لیستی از کدهای ستاپ (مثلاً ["B1","S3"]) که کاربر صریحاً خاموش کرده؛ هر
    # کاندیدی با این کد قبل از انتخاب «بهترین» کاندید حذف می‌شود. پیش‌فرض
    # خالی یعنی همه‌ی ۱۴ ستاپ مثل قبل فعال هستند (بدون تغییر رفتار).
    "disabled_setups": [],
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


def _infer_bar_seconds(d: pd.DataFrame) -> float:
    """میانه فاصله بین کندل‌ها بر حسب ثانیه؛ برای برآورد تعداد کندل موردانتظار هر دوره."""
    diffs = d["_dt"].diff().dropna()
    if diffs.empty:
        return 0.0
    return float(diffs.dt.total_seconds().median() or 0.0)


# حداقل نسبت کندل‌های موجود یک دوره (روز/هفته) نسبت به تعداد موردانتظار تا آن دوره
# «کامل» در نظر گرفته شود. اگر داده کافی برای دوره‌ی قبلی موجود نباشد (مثلاً به این
# دلیل که پنجره‌ی دریافتی kline خیلی کوتاه بوده)، سطح PDH/PDL/PWH/PWL به‌جای یک
# مقدار نادرست/بریده‌شده، None برمی‌گردد تا هیچ سیگنالی بر مبنای سطح غلط ساخته نشود.
MIN_PERIOD_COMPLETENESS_RATIO = 0.85


# ============================================================================
# ۳) محاسبه سطوح مرجع: روزانه (PDH/PDL/EQ) و هفتگی (PWH/PWL/EQ)
# ============================================================================
#
# نکته حیاتی (رفع باگ سطوح نادرست/معکوس روی چارت‌های TAO/QNT و مشابه):
# اگر دیتافریم ورودی به‌اندازه‌ی کافی کندل نداشته باشد (کمتر از یک روز/هفته کامل
# برای دوره‌ی «قبلی»)، گروه‌بندی بر اساس تاریخ ممکن است دوره‌ی قبلی را به‌صورت
# بریده (truncated) ببیند؛ در نتیجه PDH/PDL محاسبه‌شده واقعاً high/low کل روز/هفته
# قبل نیست بلکه فقط بخشی از آن است و می‌تواند نسبت به کندل‌های زنده معکوس/غلط
# به نظر برسد. برای همین، پیش از اعتماد به هر دوره‌ی «قبلی»، تعداد کندل‌های آن با
# تعداد موردانتظار (بر اساس فاصله واقعی بین کندل‌ها و طول دوره) مقایسه می‌شود.
# ============================================================================

def compute_prev_day_levels(df: pd.DataFrame):
    """سطوح PDH/PDL/EQ روزانه (برای تایم‌فریم‌های ۵ و ۱۵ دقیقه).

    سطوح همیشه بر اساس کندل‌های ۲۴ ساعته‌ی *کامل و بسته‌شده* UTC روز قبل
    محاسبه می‌شوند. اگر دیتای کافی برای اثبات کامل بودن روز قبل وجود نداشته
    باشد، (None, None, None) برگردانده می‌شود تا هیچ سطح نادرستی وارد تصمیم‌گیری
    نشود.
    """
    if df is None or len(df) < 50 or "timestamp" not in df.columns:
        return None, None, None, None
    d = df.copy()
    d["_dt"] = _timestamp_to_datetime(d)
    if d["_dt"].isna().all():
        return None, None, None, None
    d = d.sort_values("_dt").reset_index(drop=True)
    # سشن روزانه دقیقاً روی مرز نیمه‌شب UTC ریست می‌شود (بدون آفست تایم‌زون محلی).
    d["_period"] = d["_dt"].dt.floor("D").dt.date
    bar_seconds = _infer_bar_seconds(d)
    grp = d.groupby("_period").agg(_hi=("high", "max"), _lo=("low", "min"), _n=("high", "size"))
    grp["_pdh"] = grp["_hi"].shift(1)
    grp["_pdl"] = grp["_lo"].shift(1)
    grp["_prev_n"] = grp["_n"].shift(1)
    if bar_seconds > 0:
        expected_bars = max(1.0, 86400.0 / bar_seconds)
        grp["_prev_complete"] = grp["_prev_n"] >= expected_bars * MIN_PERIOD_COMPLETENESS_RATIO
    else:
        grp["_prev_complete"] = False
    d = d.merge(grp[["_pdh", "_pdl", "_prev_complete"]], left_on="_period", right_index=True, how="left")
    d = d.reset_index(drop=True)
    idx_now = len(d) - 2  # آخرین کندل بسته‌شده (مطابق قرارداد کل ربات)
    if idx_now < 0:
        return d, None, None, None
    pdh, pdl = d.at[idx_now, "_pdh"], d.at[idx_now, "_pdl"]
    if pd.isna(pdh) or pd.isna(pdl) or not bool(d.at[idx_now, "_prev_complete"]):
        return d, None, None, None
    pdh, pdl = float(pdh), float(pdl)
    if pdh <= pdl:
        return d, None, None, None
    eq = (pdh + pdl) / 2.0
    return d, pdh, pdl, eq


def compute_prev_week_levels(df: pd.DataFrame):
    """سطوح PWH/PWL/EQ هفتگی (برای تایم‌فریم‌های ۱ و ۴ ساعته).

    مشابه compute_prev_day_levels: اگر هفته‌ی قبل به‌طور کامل در داده موجود
    نباشد، (None, None, None) برگردانده می‌شود.
    """
    if df is None or len(df) < 50 or "timestamp" not in df.columns:
        return None, None, None, None
    d = df.copy()
    d["_dt"] = _timestamp_to_datetime(d)
    if d["_dt"].isna().all():
        return None, None, None, None
    d = d.sort_values("_dt").reset_index(drop=True)
    bar_seconds = _infer_bar_seconds(d)
    # شروع هفته را دوشنبه ۰۰:۰۰ UTC در نظر می‌گیریم (ISO week، هفته کریپتویی ۲۴/۷).
    iso = d["_dt"].dt.isocalendar()
    d["_period"] = iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)
    grp = d.groupby("_period", sort=False).agg(_hi=("high", "max"), _lo=("low", "min"), _n=("high", "size"))
    # ترتیب دوره‌ها باید زمانی باشد نه الفبایی؛ با اولین timestamp هر دوره مرتب می‌کنیم
    order = d.groupby("_period", sort=False)["_dt"].min().sort_values().index
    grp = grp.reindex(order)
    grp["_pwh"] = grp["_hi"].shift(1)
    grp["_pwl"] = grp["_lo"].shift(1)
    grp["_prev_n"] = grp["_n"].shift(1)
    if bar_seconds > 0:
        expected_bars = max(1.0, (7 * 86400.0) / bar_seconds)
        grp["_prev_complete"] = grp["_prev_n"] >= expected_bars * MIN_PERIOD_COMPLETENESS_RATIO
    else:
        grp["_prev_complete"] = False
    d = d.merge(grp[["_pwh", "_pwl", "_prev_complete"]], left_on="_period", right_index=True, how="left")
    d = d.reset_index(drop=True)
    idx_now = len(d) - 2
    if idx_now < 0:
        return d, None, None, None
    pwh, pwl = d.at[idx_now, "_pwh"], d.at[idx_now, "_pwl"]
    if pd.isna(pwh) or pd.isna(pwl) or not bool(d.at[idx_now, "_prev_complete"]):
        return d, None, None, None
    pwh, pwl = float(pwh), float(pwl)
    if pwh <= pwl:
        return d, None, None, None
    eq = (pwh + pwl) / 2.0
    return d, pwh, pwl, eq


def compute_prev_month_levels(df: pd.DataFrame):
    """سطوح PMH/PML/EQ ماه قبل (فال‌بک سوم برای ۵ و ۱۵ دقیقه، وقتی نه روزانه و نه
    هفتگی ستاپ معتبری نداشته باشند). دقیقاً همان منطق compute_prev_week_levels،
    فقط با گروه‌بندی بر اساس ماه تقویمی (UTC) به‌جای هفته‌ی ISO.
    """
    if df is None or len(df) < 50 or "timestamp" not in df.columns:
        return None, None, None, None
    d = df.copy()
    d["_dt"] = _timestamp_to_datetime(d)
    if d["_dt"].isna().all():
        return None, None, None, None
    d = d.sort_values("_dt").reset_index(drop=True)
    bar_seconds = _infer_bar_seconds(d)
    d["_period"] = d["_dt"].dt.strftime("%Y-%m")
    grp = d.groupby("_period", sort=False).agg(_hi=("high", "max"), _lo=("low", "min"), _n=("high", "size"))
    order = d.groupby("_period", sort=False)["_dt"].min().sort_values().index
    grp = grp.reindex(order)
    grp["_pmh"] = grp["_hi"].shift(1)
    grp["_pml"] = grp["_lo"].shift(1)
    grp["_prev_n"] = grp["_n"].shift(1)
    # ماه‌ها طول متغیر دارند (۲۸ تا ۳۱ روز)؛ برای معیار کامل‌بودن، ۲۸ روز
    # (کمینه‌ی محتاطانه) به‌عنوان مبنای انتظار در نظر گرفته می‌شود.
    if bar_seconds > 0:
        expected_bars = max(1.0, (28 * 86400.0) / bar_seconds)
        grp["_prev_complete"] = grp["_prev_n"] >= expected_bars * MIN_PERIOD_COMPLETENESS_RATIO
    else:
        grp["_prev_complete"] = False
    d = d.merge(grp[["_pmh", "_pml", "_prev_complete"]], left_on="_period", right_index=True, how="left")
    d = d.reset_index(drop=True)
    idx_now = len(d) - 2
    if idx_now < 0:
        return d, None, None, None
    pmh, pml = d.at[idx_now, "_pmh"], d.at[idx_now, "_pml"]
    if pd.isna(pmh) or pd.isna(pml) or not bool(d.at[idx_now, "_prev_complete"]):
        return d, None, None, None
    pmh, pml = float(pmh), float(pml)
    if pmh <= pml:
        return d, None, None, None
    eq = (pmh + pml) / 2.0
    return d, pmh, pml, eq


LEVEL_SOURCE_BY_TIMEFRAME = {
    "5min": "daily",
    "15min": "daily",
    "1hour": "weekly",
    "4hour": "weekly",
}

# حداقل تعداد کندلی که هر تایم‌فریم باید از صرافی بگیرد تا دوره‌ی «قبلی»
# (روز کامل قبل برای 5m/15m، هفته‌ی کامل قبل برای 1h/4h) به‌طور کامل در پنجره‌ی
# دریافتی جا بگیرد و PDH/PDL/EQ به‌جای بریده‌شدن به‌درستی محاسبه شود. bot.py هر
# جایی که df می‌سازد که قرار است وارد evaluate_scenarios شود باید حداقل همین
# مقدار را از get_klines/get_klines_async درخواست کند. اعداد با کمی حاشیه‌ی
# اطمینان (نسبت به دقیقاً ۲ دوره) انتخاب شده‌اند تا نوسان جزئی در timestampها
# یا کندل‌های ازدست‌رفته باعث ناقص دیده‌شدن دوره‌ی قبل نشود.
MIN_KLINES_FOR_LEVELS = {
    "5min": 3 * 288 + 20,   # ~3 روز کامل (۲۸۸ کندل ۵دقیقه‌ای در روز) + حاشیه
    "15min": 3 * 96 + 20,   # ~3 روز کامل (۹۶ کندل ۱۵دقیقه‌ای در روز) + حاشیه
    "1hour": 3 * 168 + 20,  # ~3 هفته کامل (۱۶۸ کندل ۱ساعته در هفته) + حاشیه
    "4hour": 3 * 42 + 20,   # ~3 هفته کامل (۴۲ کندل ۴ساعته در هفته) + حاشیه
}


def min_klines_for_levels(timeframe: str) -> int:
    return int(MIN_KLINES_FOR_LEVELS.get(timeframe, 300))


def get_reference_levels(df: pd.DataFrame, timeframe: str, level_override=None):
    """
    سطوح مرجع مناسب تایم‌فریم را برمی‌گرداند.
    خروجی: (d, high_level, low_level, eq, label, level_source)
    label یکی از 'PDH/PDL'، 'PWH/PWL' یا 'PMH/PML' برای نمایش در دلیل سیگنال.

    level_override: اختیاری، (source:'weekly'|'monthly', hi, lo, eq) — برای
    فال‌بک چندسطحی ۵ و ۱۵ دقیقه (طبق تصمیم مشترک با کاربر): وقتی سطح پیش‌فرض
    (روزانه) هیچ ستاپ معتبری نداشته، تشخیص سوئینگ/تاچ همچنان روی همین df
    (پرایمری) انجام می‌شود، فقط مرزهای hi/lo/eq از سطح بزرگ‌تر (هفتگی/ماهانه
    خودِ نماد، از‌پیش محاسبه‌شده روی دیتای روزانه) جایگزین می‌شوند.
    """
    source_default = LEVEL_SOURCE_BY_TIMEFRAME.get(timeframe, "daily")
    if level_override is not None:
        src, hi, lo, eq = level_override
        d, _, _, _ = (
            compute_prev_week_levels(df) if source_default == "weekly" else compute_prev_day_levels(df)
        )
        label = {"daily": "PDH/PDL", "weekly": "PWH/PWL", "monthly": "PMH/PML"}.get(src, "PDH/PDL")
        return d, hi, lo, eq, label, src
    source = source_default
    if source == "weekly":
        d, hi, lo, eq = compute_prev_week_levels(df)
        return d, hi, lo, eq, "PWH/PWL", source
    d, hi, lo, eq = compute_prev_day_levels(df)
    return d, hi, lo, eq, "PDH/PDL", source


# ============================================================================
# ۴) تشخیص سوئینگ (فرکتال ساده)
# ============================================================================

def compute_swings(df: pd.DataFrame, lookback: int = 3,
                    min_wick_atr_ratio: float = 0.15,
                    min_volume_ratio: float = 0.60,
                    mode: str = "advanced") -> pd.DataFrame:
    """تشخیص سوئینگ (نقطه ورود موتور).

    mode="advanced" (پیش‌فرض): از کتابخانه swing_detection.py استفاده
        می‌کند — کندلی swing_high/swing_low شناخته می‌شود که:
          (الف) در پنجره‌ی ±lookback کندل، اکسترمم منحصربه‌فرد باشد (دقیقاً
                همان شرط ساختاری قبلی، برای حفظ معنای cfg["swing_lookback_fractal"]
                و پنجره‌های جست‌وجوی وابسته به آن)، **و**
          (ب) با حداقل یکی از دو الگوی کتابخانه منطبق باشد: «فراکتال کلاسیک
                سه‌کندلی» یا «ریجکشن/ویک سه‌کندلی» (که سخت‌گیرانه‌تر است و
                اگر رخ دهد، برچسب سوینگ به‌جای classic روی rejection ست
                می‌شود).
        سپس دقیقاً همان دو فیلتر کیفیت قبلی (نسبت دم به ATR، نسبت حجم) روی
        این کاندیدها اعمال می‌شود — یعنی خروجی این تابع در بدترین حالت
        زیرمجموعه‌ای از خروجی legacy است (چون شرط (ب) یک قید اضافه است)،
        و در نتیجه سیگنال‌ها دقیق‌تر/کم‌نویزتر می‌شوند نه برعکس.
        اگر کتابخانه در دسترس نباشد یا با خطا مواجه شود، به‌صورت خودکار و
        بی‌صدا به mode="legacy" سقوط می‌کند (fallback ایمن).

    mode="legacy": فرکتال ساده‌ی قدیمی (بدون وابستگی به swing_detection.py):
        صرفاً اکسترمم‌بودن در پنجره‌ی lookback + همان فیلترهای کیفیت.

    خروجی در هر دو حالت: همان DataFrame ورودی به‌علاوه دو ستون بولی
    ``swing_high`` / ``swing_low`` (دقیقاً همان قرارداد قبلی، بدون تغییر
    برای کد پایین‌دستی مثل ``_recent_confirmed_swings``). در حالت advanced
    یک ستون اضافه‌ی صرفاً اطلاعاتی ``swing_pattern`` هم اضافه می‌شود
    (مقدار: "classic_three_bar" یا "three_bar_rejection" یا None).
    """
    if mode == "advanced":
        out = _compute_swings_advanced(df, lookback, min_wick_atr_ratio, min_volume_ratio)
        if out is not None:
            return out
        # کتابخانه در دسترس نبود/شکست خورد → سقوط ایمن به فرکتال قدیمی
    return _compute_swings_legacy(df, lookback, min_wick_atr_ratio, min_volume_ratio)


def _compute_swings_advanced(df: pd.DataFrame, lookback: int,
                              min_wick_atr_ratio: float,
                              min_volume_ratio: float):
    """پیاده‌سازی mode="advanced" برای compute_swings. در صورت هر مشکلی
    (کتابخانه در دسترس نبودن، دیتای نامعتبر، ناهم‌ترازی طول) None برمی‌گرداند
    تا caller به‌صورت خودکار به legacy سقوط کند — هرگز exception پرتاب نمی‌کند.
    """
    if not _SWING_LIB_AVAILABLE:
        return None
    if df is None or df.empty:
        return None

    d = df.copy()
    n = len(d)
    if n < 3:
        return None

    try:
        rejection_swings = _sw_detect_rejection(df, max_body_ratio=0.5, require_full_confirmation=True)
        classic_swings = _sw_detect_classic(df, strict=True)
    except _SwingDetectionError:
        return None
    except Exception:
        return None

    highs = pd.to_numeric(d["high"], errors="coerce").values
    lows = pd.to_numeric(d["low"], errors="coerce").values
    opens = pd.to_numeric(d["open"], errors="coerce").values
    closes = pd.to_numeric(d["close"], errors="coerce").values
    atr = pd.to_numeric(d["atr"], errors="coerce").values if "atr" in d.columns else np.full(n, np.nan)
    vol_ratio = pd.to_numeric(d["volume_ratio"], errors="coerce").values if "volume_ratio" in d.columns else np.full(n, np.nan)

    # اگر هر یک از اندیس‌های برگشتی از کتابخانه خارج از بازه‌ی df باشد یعنی
    # کتابخانه (به‌خاطر ردیف نامعتبر) طول/تراز متفاوتی تولید کرده؛ برای
    # جلوگیری از هر گونه ناهم‌ترازی احتمالی، ایمن‌ترین کار سقوط به legacy است.
    for sp in rejection_swings + classic_swings:
        if sp.index < 0 or sp.index >= n:
            return None

    def _quality_ok(i: int, is_low: bool) -> bool:
        atr_i = atr[i] if np.isfinite(atr[i]) else 0.0
        vr_i = vol_ratio[i] if np.isfinite(vol_ratio[i]) else 1.0
        volume_ok = (not np.isfinite(vol_ratio[i])) or (vr_i >= min_volume_ratio)
        body_top = max(opens[i], closes[i])
        body_bottom = min(opens[i], closes[i])
        if is_low:
            lower_wick = body_bottom - lows[i]
            wick_ok = (atr_i <= 0) or (lower_wick >= atr_i * min_wick_atr_ratio)
        else:
            upper_wick = highs[i] - body_top
            wick_ok = (atr_i <= 0) or (upper_wick >= atr_i * min_wick_atr_ratio)
        return bool(wick_ok and volume_ok)

    def _window_extreme_ok(i: int, is_low: bool) -> bool:
        # دقیقاً همان بازه‌ی legacy: فقط کندل‌هایی با پنجره‌ی کامل ±lookback
        # (بدون کوتاه‌شدن نزدیک ابتدا/انتهای دیتافریم) واجد شرایط‌اند، تا
        # نتیجه با legacy در مرزها هم‌تراز/زیرمجموعه بماند.
        if i < lookback or i >= n - lookback:
            return False
        lo_b = i - lookback
        hi_b = i + lookback + 1
        if is_low:
            win = lows[lo_b:hi_b]
            return bool(np.isfinite(win).all() and lows[i] == win.min() and (win == lows[i]).sum() == 1)
        else:
            win = highs[lo_b:hi_b]
            return bool(np.isfinite(win).all() and highs[i] == win.max() and (win == highs[i]).sum() == 1)

    # اولویت برچسب: اگر یک کندل هم classic و هم rejection باشد (rejection
    # شرط سخت‌گیرانه‌تری‌ست)، برچسب rejection غالب می‌شود.
    candidates: dict = {}
    for sp in classic_swings:
        is_low = sp.swing_type == _SwingType.LOW
        candidates[(sp.index, is_low)] = "classic_three_bar"
    for sp in rejection_swings:
        is_low = sp.swing_type == _SwingType.LOW
        candidates[(sp.index, is_low)] = "three_bar_rejection"

    swing_high = np.zeros(n, dtype=bool)
    swing_low = np.zeros(n, dtype=bool)
    swing_pattern = np.array([None] * n, dtype=object)

    for (i, is_low), label in candidates.items():
        if _window_extreme_ok(i, is_low) and _quality_ok(i, is_low):
            if is_low:
                swing_low[i] = True
            else:
                swing_high[i] = True
            swing_pattern[i] = label

    d["swing_high"] = swing_high
    d["swing_low"] = swing_low
    d["swing_pattern"] = swing_pattern
    return d


def _compute_swings_legacy(df: pd.DataFrame, lookback: int = 3,
                            min_wick_atr_ratio: float = 0.15,
                            min_volume_ratio: float = 0.60) -> pd.DataFrame:
    """تشخیص سوئینگ فرکتال + دو فیلتر کیفیت برای حذف سوئینگ‌های نویزی/فیک
    (پیاده‌سازی قدیمی/اصلی، مستقل از swing_detection.py):

    - min_wick_atr_ratio: کندل سوئینگ باید حداقل یک دم (wick) به این نسبت از
      ATR داشته باشد (سمت مرتبط: پایین برای swing_low، بالا برای swing_high).
      یک فرکتال با دم بسیار کوچک معمولاً نشانه‌ی یک نوسان بی‌اهمیت/نویز است و
      نباید مبنای سوئیپ/سوئینگ برای سناریوهای ورود قرار گیرد.
    - min_volume_ratio: کندل سوئینگ باید حداقل این نسبت از میانگین حجم ۲۰
      کندل اخیر را داشته باشد؛ سوئینگ‌هایی که با حجم بسیار کم شکل گرفته‌اند
      قابل‌اتکا نیستند و زمینه‌ساز breakoutهای فیک هستند.
    """
    d = df.copy()
    n = len(d)
    highs = pd.to_numeric(d["high"], errors="coerce").values
    lows = pd.to_numeric(d["low"], errors="coerce").values
    opens = pd.to_numeric(d["open"], errors="coerce").values
    closes = pd.to_numeric(d["close"], errors="coerce").values
    atr = pd.to_numeric(d["atr"], errors="coerce").values if "atr" in d.columns else np.full(n, np.nan)
    vol_ratio = pd.to_numeric(d["volume_ratio"], errors="coerce").values if "volume_ratio" in d.columns else np.full(n, np.nan)
    swing_high = np.zeros(n, dtype=bool)
    swing_low = np.zeros(n, dtype=bool)
    for i in range(lookback, n - lookback):
        h_win = highs[i - lookback: i + lookback + 1]
        l_win = lows[i - lookback: i + lookback + 1]
        if np.isnan(h_win).any() or np.isnan(l_win).any():
            continue
        atr_i = atr[i] if np.isfinite(atr[i]) else 0.0
        vr_i = vol_ratio[i] if np.isfinite(vol_ratio[i]) else 1.0
        # حجم کافی طبق فیلتر بالا (اگر داده حجم موجود نباشد، این فیلتر عبور می‌کند)
        volume_ok = (not np.isfinite(vol_ratio[i])) or (vr_i >= min_volume_ratio)
        body_top = max(opens[i], closes[i])
        body_bottom = min(opens[i], closes[i])
        upper_wick = highs[i] - body_top
        lower_wick = body_bottom - lows[i]
        if highs[i] == h_win.max() and (h_win == highs[i]).sum() == 1:
            wick_ok = (atr_i <= 0) or (upper_wick >= atr_i * min_wick_atr_ratio)
            if wick_ok and volume_ok:
                swing_high[i] = True
        if lows[i] == l_win.min() and (l_win == lows[i]).sum() == 1:
            wick_ok = (atr_i <= 0) or (lower_wick >= atr_i * min_wick_atr_ratio)
            if wick_ok and volume_ok:
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
# روند ساختاری تایم بالاتر (HTF) — صرفاً از روی سوئینگ فرکتال، نه اندیکاتور
# ============================================================================
# طبق تصمیم صریح کاربر: «اندیکاتورها بیشتر تاییدکننده‌اند نه جهت‌دهنده؛ جهت
# روند باید با همون منطق ساختاری خودِ استراتژی (سوئینگ) مشخص بشه». این تابع
# مستقل از EMA/ADX/RSI است و فقط از آخرین دو سوئینگ های/لوی تاییدشده روی
# دیتافریم ورودی (که می‌تواند تایم‌فریم بالاتر خودِ نماد، یا هفتگیِ resample
# شده از روزانه باشد) استفاده می‌کند.
def structural_htf_trend(df: pd.DataFrame, lookback: int = 3):
    """
    HH + HL (سقف بالاتر از قبلی و کف بالاتر از قبلی) → 'BULLISH'
    LH + LL (سقف پایین‌تر و کف پایین‌تر)            → 'BEARISH'
    هر ترکیب دیگر (مثل HH+LL) یا داده/سوئینگ ناکافی  → None (خنثی، بدون بلاک)
    """
    if df is None or df.empty:
        return None
    d = df.reset_index(drop=True)
    if len(d) < lookback * 2 + 8:
        return None
    required = {"open", "high", "low", "close"}
    if not required.issubset(d.columns):
        return None
    try:
        d = compute_swings(d, lookback=lookback)
    except Exception:
        return None
    highs_idx = [i for i in d.index if bool(d.at[i, "swing_high"])]
    lows_idx = [i for i in d.index if bool(d.at[i, "swing_low"])]
    if len(highs_idx) < 2 or len(lows_idx) < 2:
        return None
    h1 = _safe_float(d.at[highs_idx[-2], "high"])
    h2 = _safe_float(d.at[highs_idx[-1], "high"])
    l1 = _safe_float(d.at[lows_idx[-2], "low"])
    l2 = _safe_float(d.at[lows_idx[-1], "low"])
    if h2 > h1 and l2 > l1:
        return "BULLISH"
    if h2 < h1 and l2 < l1:
        return "BEARISH"
    return None


# ============================================================================
# ۵) بونوس/جریمه امتیاز پویا (اندیکاتورهای کمکی - فقط امتیازدهی)
# ============================================================================

def _dynamic_bonus_penalty(d: pd.DataFrame, idx_now: int, direction: int, cfg: dict, touch_count: int, code: str = ""):
    """
    direction: +1 برای سناریوهای خرید، -1 برای سناریوهای فروش
    code: کد سناریو (B1..B6/S1..S6) برای اعمال ضریب کاهش جریمه‌ی مخصوص آن ستاپ
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
    raw_penalty = min(pw["fakeout_history"], extra_touches * (pw["fakeout_history"] / 3.0))
    scale = float(cfg.get("penalty_scale_by_code", {}).get(str(code), 1.0))
    penalty_total = raw_penalty * scale
    if penalty_total > 0.5:
        note = f"سابقه {touch_count} برخورد قبلی به همین سطح (ریسک فیک‌اوت)"
        if scale < 1.0:
            note += f" — جریمه با ضریب {scale:.2f} برای ستاپ {code} کاهش یافت"
        notes.append(note)

    return bonus_total, penalty_total, notes


# ============================================================================
# ۶) موتور اصلی سناریوها
# ============================================================================

def _is_bullish_confirm(row, min_body_ratio, min_volume_ratio=0.0):
    vr = _safe_float(row.get("volume_ratio"), 1.0)
    volume_ok = vr >= min_volume_ratio
    return (_safe_float(row.get("close")) > _safe_float(row.get("open"))
            and _safe_float(row.get("body_ratio")) >= min_body_ratio
            and volume_ok)


def _is_bearish_confirm(row, min_body_ratio, min_volume_ratio=0.0):
    vr = _safe_float(row.get("volume_ratio"), 1.0)
    volume_ok = vr >= min_volume_ratio
    return (_safe_float(row.get("close")) < _safe_float(row.get("open"))
            and _safe_float(row.get("body_ratio")) >= min_body_ratio
            and volume_ok)


def evaluate_scenarios(df: pd.DataFrame, timeframe: str, strategy_config: dict = None, level_override=None, diag: dict = None):
    """
    ارزیابی هم‌زمان ۱۴ سناریوی B1..B7 / S1..S7 روی df (که باید ستون‌های
    open/high/low/close/volume/timestamp داشته باشد؛ اندیکاتورها در صورت نبود
    به‌صورت خودکار ساخته می‌شوند).

    level_override: اختیاری، (source:'weekly'|'monthly', hi, lo, eq) — نگاه کنید
    get_reference_levels برای توضیح کامل (فال‌بک چندسطحی ۵/۱۵ دقیقه).

    diag: اختیاری، دیکشنری خالی که در جا (in-place) با جزئیات تشخیصی پر می‌شود
    (چرا None برگشت، چند سوینگ high/low در دوره جاری پیدا شد و غیره). امضای
    بازگشتی تابع (dict یا None) دست‌نخورده می‌ماند تا کدهای موجود که این
    خروجی را بدون تغییر مصرف می‌کنند نشکنند؛ diag فقط برای مصرف‌کنندگان جدید
    (لاگ/آدیت) است.

    خروجی: dict یا None
        {
          'code': 'B1', 'direction': 'BUY'/'SELL', 'total_score': float,
          'base_score': float, 'bonus': float, 'penalty': float,
          'entry': float, 'sl': float, 'tp': float, 'tp_partial': float|None,
          'level_label': 'PDH/PDL'|'PWH/PWL'|'PMH/PML', 'reasons': [str,...]
        }
    اگر هیچ سناریویی شرایط را کامل نکند: None
    """
    if diag is not None:
        diag.clear()
        diag['level_source'] = (level_override[0] if level_override else 'daily')
    cfg = _merged_cfg(strategy_config)
    if df is None or len(df) < 50:
        if diag is not None:
            diag['gate'] = 'insufficient_data'
        return None
    d = _ensure_atr(df)
    d, hi_level, lo_level, eq, label, source = get_reference_levels(d, timeframe, level_override=level_override)
    if d is None or hi_level is None or lo_level is None or hi_level <= lo_level:
        if diag is not None:
            diag['gate'] = 'invalid_levels'
        return None

    lookback = int(cfg["swing_lookback_fractal"])
    d = compute_swings(
        d, lookback,
        min_wick_atr_ratio=float(cfg.get("swing_min_wick_atr_ratio", 0.15)),
        min_volume_ratio=float(cfg.get("swing_min_volume_ratio", 0.60)),
        mode=str(cfg.get("swing_detection_mode", "advanced")),
    )
    idx_now = len(d) - 2  # آخرین کندل بسته‌شده
    if idx_now < lookback * 3:
        if diag is not None:
            diag['gate'] = 'insufficient_data'
        return None

    tol = float(cfg["touch_tolerance_pct"])
    brk = float(cfg["break_confirm_pct"])
    min_body = float(cfg["min_confirm_body_ratio"])
    min_confirm_vol = float(cfg.get("min_confirm_volume_ratio", 0.35))
    search_back = lookback * int(cfg["swing_search_window_mult"])
    atr_now = _safe_float(d.at[idx_now, "atr"])
    if atr_now <= 0:
        if diag is not None:
            diag['gate'] = 'invalid_atr'
        return None

    # --- محدوده دوره جاری (روز جاری یا هفته جاری، بسته به تایم‌فریم) ---
    period_col = "_period"
    period_val = d.at[idx_now, period_col]
    period_mask = d[period_col] == period_val
    start_idx = int(d.index[period_mask][0])
    period = d.loc[start_idx:idx_now]

    if diag is not None:
        diag['swing_high_count'] = int(period['swing_high'].sum()) if 'swing_high' in period.columns else 0
        diag['swing_low_count'] = int(period['swing_low'].sum()) if 'swing_low' in period.columns else 0

    hi_touch_idxs = [i for i in period.index if _safe_float(period.at[i, "high"]) >= hi_level * (1 - tol)]
    lo_touch_idxs = [i for i in period.index if _safe_float(period.at[i, "low"]) <= lo_level * (1 + tol)]
    hi_break_idxs = [i for i in period.index if _safe_float(period.at[i, "close"]) > hi_level * (1 + brk)]
    lo_break_idxs = [i for i in period.index if _safe_float(period.at[i, "close"]) < lo_level * (1 - brk)]

    first_hi = hi_touch_idxs[0] if hi_touch_idxs else None
    first_lo = lo_touch_idxs[0] if lo_touch_idxs else None

    curr_row = d.loc[idx_now]
    close_now = _safe_float(curr_row.get("close"))
    high_now = _safe_float(curr_row.get("high"))
    low_now = _safe_float(curr_row.get("low"))

    # ------------------------------------------------------------------
    # دروازه‌ی سخت‌گیرانه‌ی ممنوعیت ورود میان‌رنج (dead-zone gate)
    # ------------------------------------------------------------------
    # طبق قانون هسته‌ی استراتژی، هیچ ورودی بدون برخورد/سوییپ/ریتست واقعی به
    # PDH یا PDL (یا PWH/PWL) مجاز نیست. اگر در طول کل دوره‌ی جاری (از شروع
    # روز/هفته تا کندل فعلی) هیچ لمس یا شکستی به هیچ‌کدام از دو مرز رخ نداده
    # باشد، و کندل فعلی هم خودش دقیقاً روی مرز نباشد، یعنی قیمت هنوز کاملاً
    # وسط رنج (dead-zone) است؛ در این حالت هیچ سناریویی ارزیابی نمی‌شود و
    # تابع فوراً None برمی‌گرداند — صرف‌نظر از فاصله تا EQ یا جهت قیمت.
    range_touched_this_period = bool(hi_touch_idxs) or bool(lo_touch_idxs) or bool(hi_break_idxs) or bool(lo_break_idxs)
    touching_boundary_now = (
        high_now >= hi_level * (1 - tol) or low_now <= lo_level * (1 + tol) or
        close_now >= hi_level * (1 - tol) or close_now <= lo_level * (1 + tol)
    )
    if not range_touched_this_period and not touching_boundary_now:
        if diag is not None:
            diag['gate'] = 'dead_zone_no_touch'
            diag['range_touched'] = False
        return None
    if diag is not None:
        diag['range_touched'] = True

    candidates = []

    def add_candidate(code, direction, sl, tp, tp_partial, extra_reason, touch_count):
        base = cfg["base_scores"][code]
        bonus, penalty, notes = _dynamic_bonus_penalty(d, idx_now, 1 if direction == "BUY" else -1, cfg, touch_count, code)
        total = max(0.0, min(cfg["max_score"], base + bonus - penalty))
        reasons = [extra_reason] + notes
        candidates.append({
            "code": code, "direction": direction,
            "base_score": base, "bonus": round(bonus, 1), "penalty": round(penalty, 1),
            "total_score": round(total, 1),
            "entry": close_now, "sl": sl, "tp": tp, "tp_partial": tp_partial,
            "level_label": label, "reasons": reasons,
            # سطوح خام رنج، برای ساخت پلکان سه‌مرحله‌ای TP (Tier1=EQ/Tier2=مرز
            # مقابل/Tier3=اکستنشن) در strategy.build_trade_plan
            "range_hi": hi_level, "range_lo": lo_level, "range_eq": eq,
            "extension_atr_mult": float(cfg.get("extension_atr_mult", 0.50)),
        })

    # ------------------------------------------------------------------
    # سناریوهای خرید (BUY)
    # ------------------------------------------------------------------
    recent_swing_lows = _recent_confirmed_swings(d, idx_now, lookback, "swing_low", search_back)
    bullish_confirm_now = _is_bullish_confirm(curr_row, min_body, min_confirm_vol)
    # ری‌کلیم واقعی: کلوز کندل تاییدی باید دوباره بالای PDL/PWL برگشته باشد
    # (نه صرفاً یک کندل سبز جایی که قیمت هنوز عمیقاً زیر سطح است).
    require_reclaim = bool(cfg.get("require_reclaim_confirm", True))
    long_reclaimed = (not require_reclaim) or (close_now >= lo_level * (1 - tol))

    # ------------------------------------------------------------------
    # B1 (نسخه ارتقایافته): سوییپ PDH/PWH سپس سوییپ PDL/PWL، تشکیل سوئینگ حمایتی و بازگشت
    # ------------------------------------------------------------------
    if first_hi is not None and first_lo is not None and first_hi < first_lo and bullish_confirm_now and long_reclaimed and recent_swing_lows:
        # ۱. محاسبه عمیق‌ترین نفوذ زیر کف مرجع در طول سوییپ (شکار نقدینگی واقعی)
        sweep_bars = period.loc[first_lo:idx_now]
        deepest_low = _safe_float(sweep_bars["low"].min())
        sweep_depth = (lo_level - deepest_low) if deepest_low < lo_level else 0.0
        min_sweep_depth = atr_now * float(cfg.get("sweep_min_atr_ratio", 0.10))

        # ۲. ارزیابی آخرین سوئینگ کف شکل‌گرفته
        swing_idx = recent_swing_lows[-1]
        swing_price = _safe_float(d.at[swing_idx, "low"])
        is_fresh_swing = (idx_now - swing_idx <= lookback + 4)

        # سوئینگ کف باید یا بالای PDL تثبیت شده باشد یا با تلورانس بسیار جزئی در محدوده PDL باشد
        swing_holds_support = swing_price >= lo_level * (1 - tol * 2)

        # ۳. اطمینان از اینکه هنوز تا تارگت اول (EQ) فضای کافی R:R وجود دارد (عدم تعقیب قیمت در اوج)
        has_room_to_eq = close_now < eq - (atr_now * 0.20)

        if sweep_depth >= min_sweep_depth and is_fresh_swing and swing_holds_support and has_room_to_eq:
            # حد ضرر ایمن: زیر سوئینگ تاییدشده یا عمیق‌ترین نقطه سوییپ
            structural_base = min(swing_price, deepest_low, lo_level)
            sl = structural_base - atr_now * cfg["sl_atr_buffer"]

            add_candidate(
                "B1", "BUY", sl, hi_level, eq,
                f"سوییپ سقف سپس سوییپ کف ({sweep_depth:.5g} نفوذ) + تشکیل سوئینگ تثبیتی بالای {label.split('/')[1]} و تایید صعودی",
                len(lo_touch_idxs)
            )

    # B3: سوییپ مستقیم PDL/PWL بدون عبور قبلی از PDH/PWH
    # فیکس (آدیت شهریور ۱۴۰۵): علاوه بر ری‌کلیم عمومی، این کد مشخصاً به یک
    # ری‌کلیم قاطع‌تر (فراتر از سطح، نه فقط داخل تلورانس لمس) و یک کندل
    # تاییدی باکیفیت‌تر نیاز دارد — چون بر خلاف B1، هیچ سوییپ دوطرفه‌ای
    # (تاییدیه اضافه) ندارد و ذاتاً کم‌سوادترین عضو خانواده برای فیک‌اوت است.
    direct_reclaim_margin = float(cfg.get("direct_sweep_min_reclaim_margin_pct", 0.0015))
    direct_confirm_body = float(cfg.get("direct_sweep_min_confirm_body_ratio", 0.35))
    b3_decisive_reclaim = close_now >= lo_level * (1 + direct_reclaim_margin)
    b3_strong_confirm = _safe_float(curr_row.get("body_ratio")) >= direct_confirm_body
    if (first_lo is not None and (first_hi is None or first_hi > first_lo)
            and bullish_confirm_now and b3_decisive_reclaim and b3_strong_confirm and recent_swing_lows):

        # ۱. محاسبه عمق نفوذ زیر کف (حداقل شکار نقدینگی معتبر)
        sweep_bars = period.loc[first_lo:idx_now]
        deepest_low = _safe_float(sweep_bars["low"].min())
        sweep_depth = (lo_level - deepest_low) if deepest_low < lo_level else 0.0
        min_sweep_depth = atr_now * float(cfg.get("sweep_min_atr_ratio", 0.10))

        # ۲. سرعت بازگشت (عدم ماندگاری طولانی زیر سطح - شرط کلیدی BOF)
        bars_closed_below = sum(1 for i in sweep_bars.index if _safe_float(sweep_bars.at[i, "close"]) < lo_level)
        fast_reversal = bars_closed_below <= int(cfg.get("max_bars_below_pdl", 3))

        # ۳. ارزیابی سوئینگ کف و تازگی آن
        swing_idx = recent_swing_lows[-1]
        swing_price = _safe_float(d.at[swing_idx, "low"])
        is_fresh_swing = (idx_now - swing_idx <= lookback + 3)

        # ۴. حفظ تناسب R:R تا خط میانی (ورود نباید بالای خط EQ باشد)
        has_room_to_eq = close_now < eq - (atr_now * 0.20)

        if sweep_depth >= min_sweep_depth and fast_reversal and is_fresh_swing and has_room_to_eq:
            # حد ضرر: پشت کمترین قیمت سوییپ‌شده (نوک ویک هانت) با بافر ATR
            sl_anchor = min(swing_price, deepest_low)
            sl = sl_anchor - atr_now * cfg["sl_atr_buffer"]

            add_candidate(
                "B3", "BUY", sl, hi_level, eq,
                f"ستاپ BOF مستقیم: سوییپ کف {label.split('/')[1]} ({sweep_depth:.5g} نفوذ) + ری‌کلیم سریع ({bars_closed_below} کندل) با تاییدیه بدنه قوی",
                len(lo_touch_idxs)
            )

    # ------------------------------------------------------------------
    # B4 (نسخه ارتقایافته - ستاپ BPB روی EQ): شکست EQ به بالا + پولبک و تثبیت حمایتی روی EQ
    # ------------------------------------------------------------------
    if first_lo is not None and bullish_confirm_now:
        # ۱. پیدا کردن اولین شکست پرقدرت EQ به سمت بالا بعد از سوییپ کف
        eq_break_idxs = [
            i for i in period.index
            if i > first_lo and _safe_float(d.at[i - 1, "close"]) < eq and _safe_float(d.at[i, "close"]) > eq * (1 + tol)
        ]

        if eq_break_idxs:
            first_eq_break = eq_break_idxs[0]
            # بررسی رفتار قیمت پس از شکست EQ
            post_break_bars = period.loc[first_eq_break:idx_now]

            # سوئینگ‌های کفی که بعد از شکست EQ و روی/بالای EQ شکل گرفته‌اند
            swings_on_eq = [
                i for i in recent_swing_lows
                if i >= first_eq_break and _safe_float(d.at[i, "low"]) >= eq * (1 - tol * 3)
            ]

            # آیا پولبک یا تستی به محدوده EQ خورده است؟ (Low در محدوده EQ اما Close بالای EQ)
            retested_eq = any(
                _safe_float(post_break_bars.at[i, "low"]) <= eq * (1 + tol * 2) and
                _safe_float(post_break_bars.at[i, "close"]) >= eq * (1 - tol)
                for i in post_break_bars.index
            )

            # بررسی تازگی و کلوز معتبر فعلی
            is_above_eq = close_now > eq
            # اطمینان از وجود فضای سود حداقل ۰.۴ ATR تا سقف PDH
            has_room_to_hi = (hi_level - close_now) >= (atr_now * 0.40)

            if (swings_on_eq or retested_eq) and is_above_eq and has_room_to_hi:
                # محاسبه سطح سوئینگ حمایتی روی EQ
                if swings_on_eq:
                    swing_idx = swings_on_eq[-1]
                    eq_swing_low = _safe_float(d.at[swing_idx, "low"])
                else:
                    eq_swing_low = _safe_float(post_break_bars["low"].min())

                # حد ضرر طبق تصویر: دقیقاً پشت سوئینگ پولبک زیر EQ (نه زیر کف کل رنج!)
                sl = min(eq_swing_low, eq) - atr_now * cfg["sl_atr_buffer_tight"]

                # بررسی اینکه R:R حداقل معتبر باشد
                if (close_now - sl) > 0:
                    add_candidate(
                        "B4", "BUY", sl, hi_level, None,
                        f"ستاپ BPB روی EQ: ری‌کلیم و تثبیت حمایتی بالای EQ ({eq_swing_low:.5g}) پس از سوییپ کف و حرکت به سمت {label.split('/')[0]}",
                        len(lo_touch_idxs)
                    )

    # ------------------------------------------------------------------
    # B2 (نسخه ارتقایافته - ستاپ CPB): سوییپ سقف، پولبک مضاعف با Higher Low و حمله مجدد به PDH
    # ------------------------------------------------------------------
    if first_hi is not None and bullish_confirm_now:
        # سوئینگ‌های کفی که پس از سوییپ سقف تشکیل شده‌اند
        swings_after = [i for i in recent_swing_lows if i > first_hi]
        if len(swings_after) >= 2:
            pb1_idx = swings_after[-2]
            pb2_idx = swings_after[-1]
            pb1_low = _safe_float(d.at[pb1_idx, "low"])
            pb2_low = _safe_float(d.at[pb2_idx, "low"])

            # شرط CPB: کف دوم باید بالاتر از کف اول باشد (Higher Low)
            is_higher_low = pb2_low > pb1_low
            # کف دوم باید معتبر و تازه باشد
            is_fresh_pb2 = (idx_now - pb2_idx <= lookback + 4)
            # فاصله زمانی معنادار بین دو پولبک (جلوگیری از نویز دو کندل مجاور)
            meaningful_spacing = (pb2_idx - pb1_idx) >= max(3, lookback)

            # کف دوم باید در محدوده مناسب رنج باشد (بالای EQ یا با فاصله امن از PDL)
            pb2_in_upper_half = pb2_low >= eq * (1 - tol)

            # فضای سود تا سقف PDH (حداقل ۰.۴ ATR فضا تا سقف PDH برای توجیه ورود)
            has_room_to_hi = (hi_level - close_now) >= (atr_now * 0.40)

            if is_higher_low and is_fresh_pb2 and meaningful_spacing and pb2_in_upper_half and has_room_to_hi:
                # حد ضرر ایمن: پشت سوئینگ کف دوم (Pullback 2)
                sl = pb2_low - atr_now * cfg["sl_atr_buffer"]

                # تارگت اول سقف PDH، تارگت اکستنشن به عنوان TP3 در build_trade_plan
                add_candidate(
                    "B2", "BUY", sl, hi_level, None,
                    f"ستاپ CPB صعودی: سوییپ مقاومت + پولبک مضاعف با کف بالاتر ({pb2_low:.5g} > {pb1_low:.5g}) بالای EQ",
                    len(hi_touch_idxs)
                )

    # ------------------------------------------------------------------
    # B5 (نسخه ارتقایافته - ستاپ BPB روی مقاومت): شکست معتبر سقف + ریتست و حمایت روی PDH
    # ------------------------------------------------------------------
    if hi_break_idxs and bullish_confirm_now:
        first_break = hi_break_idxs[0]
        after_break = period.loc[first_break:idx_now]

        # ۱. تایید اینکه شکست فرسایشی نشده و هیچ کلوزی دوباره به عمق رنج بازنگشته است
        min_close_after = _safe_float(after_break["close"].min()) if len(after_break) else None
        no_deep_reentry = min_close_after is not None and min_close_after >= hi_level * (1 - tol)

        # ۲. تایید لمس یا تست محدوده سطح شکسته شده از بالا (Pullback to S/R Flip)
        retested = any(
            _safe_float(after_break.at[i, "low"]) <= hi_level * (1 + tol * 1.5) and
            _safe_float(after_break.at[i, "close"]) >= hi_level * (1 - tol)
            for i in after_break.index
        )

        # ۳. عدم ورود در قیمت‌های پرت و پرتاب‌شده (فاصله ورود تا سطح PDH نباید بیش از ۰.۸ ATR باشد)
        dist_from_break = close_now - hi_level
        not_chasing = 0 < dist_from_break <= (atr_now * float(cfg.get("max_retest_entry_dist_atr", 0.85)))

        # ۴. پیدا کردن پایین‌ترین سوئینگ یا شدو در بازگشت به PDH برای لنگر کردن استاپ
        swings_on_retest = [
            i for i in recent_swing_lows
            if i >= first_break and _safe_float(d.at[i, "low"]) >= hi_level * (1 - tol * 3)
        ]

        if retested and no_deep_reentry and not_chasing:
            if swings_on_retest:
                retest_low = _safe_float(d.at[swings_on_retest[-1], "low"])
            else:
                retest_low = _safe_float(after_break["low"].min())

            # حد ضرر فشرده: زیر سوئینگ ریتست و پشت سطح PDH
            sl_anchor = min(retest_low, hi_level)
            sl = sl_anchor - atr_now * cfg["sl_atr_buffer_tight"]

            # تارگت بر اساس اکستنشن رنج (حرکت پرقدرت ترند به سمت سطوح اکستنشن ۱، ۲ و ۳)
            range_width = (hi_level - lo_level)
            tp_ext = hi_level + range_width * cfg["extension_atr_mult"]

            if (close_now - sl) > 0:
                add_candidate(
                    "B5", "BUY", sl, tp_ext, None,
                    f"ستاپ BPB خارجی: شکست سقف {label.split('/')[0]} + ریتست موفق و تبدیل به حمایت (ورود در فاصله {dist_from_break:.5g})",
                    len(hi_touch_idxs)
                )

    # ------------------------------------------------------------------
    # B6 (نسخه بازنویسی‌شده و ارتقایافته): چرخش در ناحیه دیسکانت (زیر EQ) بدون لمس PDL
    # ------------------------------------------------------------------
    if bullish_confirm_now and recent_swing_lows:
        # ۱. آخرین سوئینگ کف باید در نیمه پایینی (Discount) و بالاتر از PDL باشد
        swing_idx = recent_swing_lows[-1]
        swing_price = _safe_float(d.at[swing_idx, "low"])

        range_height = (hi_level - lo_level)
        # سوئینگ باید در ناحیه دیسکانت (بین ۲۵٪ تا ۴۵٪ از کف رنج) تشکیل شده باشد
        is_in_discount = (swing_price > lo_level * (1 + tol * 2)) and (swing_price < eq - (range_height * 0.05))
        is_fresh_swing = (idx_now - swing_idx <= lookback + 3)

        # ۲. قیمت فعلی ورود باید هنوز زیر EQ باشد تا فضای سود تا TP1 حفظ شود
        has_room_to_eq = (eq - close_now) >= (atr_now * 0.35)

        # ۳. عدم شکست قبلی PDL در این لگ نزولی (هنوز کفی شکسته نشده)
        if is_in_discount and is_fresh_swing and has_room_to_eq:
            # حد ضرر ایمن: پشت سوئینگ کف دیسکانت
            sl = swing_price - atr_now * cfg["sl_atr_buffer"]

            # تارگت اول خط میانی EQ و تارگت دوم سقف رنج PDH
            add_candidate(
                "B6", "BUY", sl, hi_level, eq,
                f"ستاپ دیسکانت: چرخش صعودی از عمق رنج ({swing_price:.5g}) بدون لمس {label.split('/')[1]} به سمت EQ و {label.split('/')[0]}",
                len(lo_touch_idxs)
            )

    # ------------------------------------------------------------------
    # سناریوهای فروش (SELL) — دقیقاً معکوس سناریوهای خرید
    # ------------------------------------------------------------------
    recent_swing_highs = _recent_confirmed_swings(d, idx_now, lookback, "swing_high", search_back)
    bearish_confirm_now = _is_bearish_confirm(curr_row, min_body, min_confirm_vol)
    # ری‌کلیم واقعی: کلوز کندل تاییدی باید دوباره پایین PDH/PWH برگشته باشد.
    short_reclaimed = (not require_reclaim) or (close_now <= hi_level * (1 + tol))

    # ------------------------------------------------------------------
    # S1 (نسخه ارتقایافته): سوییپ PDL/PWL سپس سوییپ PDH/PWH، تشکیل سوئینگ مقاومتی و بازگشت
    # ------------------------------------------------------------------
    if first_lo is not None and first_hi is not None and first_lo < first_hi and bearish_confirm_now and short_reclaimed and recent_swing_highs:
        # ۱. محاسبه بالاترین نفوذ بالای سقف مرجع در طول سوییپ
        sweep_bars = period.loc[first_hi:idx_now]
        highest_high = _safe_float(sweep_bars["high"].max())
        sweep_depth = (highest_high - hi_level) if highest_high > hi_level else 0.0
        min_sweep_depth = atr_now * float(cfg.get("sweep_min_atr_ratio", 0.10))

        # ۲. ارزیابی آخرین سوئینگ سقف شکل‌گرفته
        swing_idx = recent_swing_highs[-1]
        swing_price = _safe_float(d.at[swing_idx, "high"])
        is_fresh_swing = (idx_now - swing_idx <= lookback + 4)

        # سوئینگ سقف باید زیر PDH تثبیت شده باشد یا با تلورانس جزئی در محدوده PDH باشد
        swing_holds_resistance = swing_price <= hi_level * (1 + tol * 2)

        # ۳. اطمینان از اینکه هنوز تا تارگت اول (EQ) فضای کافی وجود دارد
        has_room_to_eq = close_now > eq + (atr_now * 0.20)

        if sweep_depth >= min_sweep_depth and is_fresh_swing and swing_holds_resistance and has_room_to_eq:
            # حد ضرر ایمن: بالای سوئینگ تاییدشده یا بالاترین نقطه سوییپ
            structural_base = max(swing_price, highest_high, hi_level)
            sl = structural_base + atr_now * cfg["sl_atr_buffer"]

            add_candidate(
                "S1", "SELL", sl, lo_level, eq,
                f"سوییپ کف سپس سوییپ سقف ({sweep_depth:.5g} نفوذ) + تشکیل سوئینگ تثبیتی زیر {label.split('/')[0]} و تایید نزولی",
                len(hi_touch_idxs)
            )

    # S3: سوییپ مستقیم PDH/PWH بدون عبور قبلی از PDL/PWL
    # همان فیکس B3 (بالا)، آینه‌ای برای سمت فروش. آدیت نشان داد S3 حتی
    # ضعیف‌تر از B3 عمل کرده (۱۲ معامله، وین‌ریت ۱۶.۷٪) — این ممکن است هم به
    # همین سهل‌گیری در تعریف ری‌کلیم برگردد و هم به عدم‌تقارن رفتار بازار
    # (سوییپ‌های بالای رنج در کریپتو با ریسک اسکوییز/تداوم صعودی بیشتری همراهند
    # و برخلاف سوییپ‌های پایین رنج به همان اندازه قابل‌اعتماد برنمی‌گردند)؛
    # فیلتر سخت‌گیرانه‌تر زیر روی هر دو طرف یکسان اعمال می‌شود تا رفتار
    # واقعی داده (نه یک عدد PnL خاص) قضاوت شود.
    s3_decisive_reclaim = close_now <= hi_level * (1 - direct_reclaim_margin)
    s3_strong_confirm = _safe_float(curr_row.get("body_ratio")) >= direct_confirm_body
    if (first_hi is not None and (first_lo is None or first_lo > first_hi)
            and bearish_confirm_now and s3_decisive_reclaim and s3_strong_confirm and recent_swing_highs):

        # ۱. محاسبه عمق نفوذ بالای سقف (شکار نقدینگی معتبر)
        sweep_bars = period.loc[first_hi:idx_now]
        highest_high = _safe_float(sweep_bars["high"].max())
        sweep_depth = (highest_high - hi_level) if highest_high > hi_level else 0.0
        min_sweep_depth = atr_now * float(cfg.get("sweep_min_atr_ratio", 0.10))

        # ۲. سرعت بازگشت (عدم ماندگاری و تثبیت در بالای PDH)
        bars_closed_above = sum(1 for i in sweep_bars.index if _safe_float(sweep_bars.at[i, "close"]) > hi_level)
        fast_reversal = bars_closed_above <= int(cfg.get("max_bars_above_pdh", 3))

        # ۳. ارزیابی سوئینگ سقف و تازگی آن
        swing_idx = recent_swing_highs[-1]
        swing_price = _safe_float(d.at[swing_idx, "high"])
        is_fresh_swing = (idx_now - swing_idx <= lookback + 3)

        # ۴. حفظ تناسب R:R تا خط میانی (ورود نباید زیر خط EQ باشد)
        has_room_to_eq = close_now > eq + (atr_now * 0.20)

        if sweep_depth >= min_sweep_depth and fast_reversal and is_fresh_swing and has_room_to_eq:
            # حد ضرر: بالای بیشترین قیمت سوییپ‌شده (نوک ویک هانت) با بافر ATR
            sl_anchor = max(swing_price, highest_high)
            sl = sl_anchor + atr_now * cfg["sl_atr_buffer"]

            add_candidate(
                "S3", "SELL", sl, lo_level, eq,
                f"ستاپ BOF مستقیم: سوییپ سقف {label.split('/')[0]} ({sweep_depth:.5g} نفوذ) + ری‌کلیم سریع ({bars_closed_above} کندل) با تاییدیه بدنه قوی",
                len(hi_touch_idxs)
            )

    # ------------------------------------------------------------------
    # S4 (نسخه ارتقایافته - ستاپ BPB زیر EQ): شکست EQ به پایین + پولبک و تثبیت مقاومتی زیر EQ
    # ------------------------------------------------------------------
    if first_hi is not None and bearish_confirm_now:
        # ۱. پیدا کردن اولین شکست پرقدرت EQ به سمت پایین بعد از سوییپ سقف
        eq_break_idxs = [
            i for i in period.index
            if i > first_hi and _safe_float(d.at[i - 1, "close"]) > eq and _safe_float(d.at[i, "close"]) < eq * (1 - tol)
        ]

        if eq_break_idxs:
            first_eq_break = eq_break_idxs[0]
            # بررسی رفتار قیمت پس از شکست EQ
            post_break_bars = period.loc[first_eq_break:idx_now]

            # سوئینگ‌های سقفی که بعد از شکست EQ و زیر/روی EQ شکل گرفته‌اند
            swings_on_eq = [
                i for i in recent_swing_highs
                if i >= first_eq_break and _safe_float(d.at[i, "high"]) <= eq * (1 + tol * 3)
            ]

            # آیا پولبک یا تستی به محدوده EQ خورده است؟ (High در محدوده EQ اما Close زیر EQ)
            retested_eq = any(
                _safe_float(post_break_bars.at[i, "high"]) >= eq * (1 - tol * 2) and
                _safe_float(post_break_bars.at[i, "close"]) <= eq * (1 + tol)
                for i in post_break_bars.index
            )

            # بررسی تثبیت زیر EQ
            is_below_eq = close_now < eq
            # اطمینان از وجود فضای سود حداقل ۰.۴ ATR تا کف PDL
            has_room_to_lo = (close_now - lo_level) >= (atr_now * 0.40)

            if (swings_on_eq or retested_eq) and is_below_eq and has_room_to_lo:
                # محاسبه سطح سوئینگ مقاومتی روی EQ
                if swings_on_eq:
                    swing_idx = swings_on_eq[-1]
                    eq_swing_high = _safe_float(d.at[swing_idx, "high"])
                else:
                    eq_swing_high = _safe_float(post_break_bars["high"].max())

                # حد ضرر طبق تصویر: دقیقاً پشت سوئینگ پولبک بالای EQ (نه بالای سقف کل رنج!)
                sl = max(eq_swing_high, eq) + atr_now * cfg["sl_atr_buffer_tight"]

                # بررسی اینکه R:R حداقل معتبر باشد
                if (sl - close_now) > 0:
                    add_candidate(
                        "S4", "SELL", sl, lo_level, None,
                        f"ستاپ BPB زیر EQ: ری‌کلیم و تثبیت مقاومتی زیر EQ ({eq_swing_high:.5g}) پس از سوییپ سقف و حرکت به سمت {label.split('/')[1]}",
                        len(hi_touch_idxs)
                    )

    # ------------------------------------------------------------------
    # S2 (نسخه ارتقایافته - ستاپ CPB): سوییپ کف، پولبک مضاعف با Lower High و حمله مجدد به PDL
    # ------------------------------------------------------------------
    if first_lo is not None and bearish_confirm_now:
        # سوئینگ‌های سقفی که پس از سوییپ کف تشکیل شده‌اند
        swings_after = [i for i in recent_swing_highs if i > first_lo]
        if len(swings_after) >= 2:
            pb1_idx = swings_after[-2]
            pb2_idx = swings_after[-1]
            pb1_high = _safe_float(d.at[pb1_idx, "high"])
            pb2_high = _safe_float(d.at[pb2_idx, "high"])

            # شرط CPB: سقف دوم باید پایین‌تر از سقف اول باشد (Lower High)
            is_lower_high = pb2_high < pb1_high
            # سقف دوم باید معتبر و تازه باشد
            is_fresh_pb2 = (idx_now - pb2_idx <= lookback + 4)
            # فاصله زمانی معنادار بین دو پولبک (جلوگیری از نویز)
            meaningful_spacing = (pb2_idx - pb1_idx) >= max(3, lookback)

            # سقف دوم باید در محدوده مناسب رنج باشد (پایین‌تر از EQ یا متمایل به PDL)
            pb2_in_lower_half = pb2_high <= eq * (1 + tol)

            # فضای سود تا کف PDL (حداقل ۰.۴ ATR فضا تا کف PDL)
            has_room_to_lo = (close_now - lo_level) >= (atr_now * 0.40)

            if is_lower_high and is_fresh_pb2 and meaningful_spacing and pb2_in_lower_half and has_room_to_lo:
                # حد ضرر ایمن: پشت سوئینگ سقف دوم (Pullback 2)
                sl = pb2_high + atr_now * cfg["sl_atr_buffer"]

                add_candidate(
                    "S2", "SELL", sl, lo_level, None,
                    f"ستاپ CPB نزولی: سوییپ حمایت + پولبک مضاعف با سقف پایین‌تر ({pb2_high:.5g} < {pb1_high:.5g}) زیر EQ",
                    len(lo_touch_idxs)
                )

    # ------------------------------------------------------------------
    # S5 (نسخه ارتقایافته - ستاپ BPB روی حمایت): شکست معتبر کف + ریتست و مقاومت زیر PDL
    # ------------------------------------------------------------------
    if lo_break_idxs and bearish_confirm_now:
        first_break = lo_break_idxs[0]
        after_break = period.loc[first_break:idx_now]

        # ۱. تایید اینکه هیچ کلوزی دوباره به عمق رنج بازنگشته است
        max_close_after = _safe_float(after_break["close"].max()) if len(after_break) else None
        no_deep_reentry = max_close_after is not None and max_close_after <= lo_level * (1 + tol)

        # ۲. تایید لمس یا تست محدوده سطح شکسته شده از پایین (Pullback to S/R Flip)
        retested = any(
            _safe_float(after_break.at[i, "high"]) >= lo_level * (1 - tol * 1.5) and
            _safe_float(after_break.at[i, "close"]) <= lo_level * (1 + tol)
            for i in after_break.index
        )

        # ۳. عدم ورود در قیمت‌های پرت و پرتاب‌شده به پایین
        dist_from_break = lo_level - close_now
        not_chasing = 0 < dist_from_break <= (atr_now * float(cfg.get("max_retest_entry_dist_atr", 0.85)))

        # ۴. پیدا کردن بالاترین سوئینگ یا شدو در بازگشت به PDL برای لنگر کردن استاپ
        swings_on_retest = [
            i for i in recent_swing_highs
            if i >= first_break and _safe_float(d.at[i, "high"]) <= lo_level * (1 + tol * 3)
        ]

        if retested and no_deep_reentry and not_chasing:
            if swings_on_retest:
                retest_high = _safe_float(d.at[swings_on_retest[-1], "high"])
            else:
                retest_high = _safe_float(after_break["high"].max())

            # حد ضرر فشرده: بالای سوئینگ ریتست و پشت سطح PDL
            sl_anchor = max(retest_high, lo_level)
            sl = sl_anchor + atr_now * cfg["sl_atr_buffer_tight"]

            # تارگت اکستنشن به سمت پایین
            range_width = (hi_level - lo_level)
            tp_ext = lo_level - range_width * cfg["extension_atr_mult"]

            if (sl - close_now) > 0:
                add_candidate(
                    "S5", "SELL", sl, tp_ext, None,
                    f"ستاپ BPB خارجی: شکست کف {label.split('/')[1]} + ریتست موفق و تبدیل به مقاومت (ورود در فاصله {dist_from_break:.5g})",
                    len(lo_touch_idxs)
                )

    # ------------------------------------------------------------------
    # S6 (نسخه بازنویسی‌شده و ارتقایافته): چرخش در ناحیه پریمیوم (بالای EQ) بدون لمس PDH
    # ------------------------------------------------------------------
    if bearish_confirm_now and recent_swing_highs:
        # ۱. آخرین سوئینگ سقف باید در نیمه بالایی (Premium) و پایین‌تر از PDH باشد
        swing_idx = recent_swing_highs[-1]
        swing_price = _safe_float(d.at[swing_idx, "high"])

        range_height = (hi_level - lo_level)
        # سوئینگ باید در ناحیه پریمیوم (بین ۵۵٪ تا ۷۵٪ از کف رنج) تشکیل شده باشد
        is_in_premium = (swing_price < hi_level * (1 - tol * 2)) and (swing_price > eq + (range_height * 0.05))
        is_fresh_swing = (idx_now - swing_idx <= lookback + 3)

        # ۲. قیمت فعلی ورود باید هنوز بالای EQ باشد
        has_room_to_eq = (close_now - eq) >= (atr_now * 0.35)

        if is_in_premium and is_fresh_swing and has_room_to_eq:
            # حد ضرر ایمن: بالای سوئینگ سقف پریمیوم
            sl = swing_price + atr_now * cfg["sl_atr_buffer"]

            # تارگت اول خط میانی EQ و تارگت دوم کف رنج PDL
            add_candidate(
                "S6", "SELL", sl, lo_level, eq,
                f"ستاپ پریمیوم: چرخش نزولی از اوج رنج ({swing_price:.5g}) بدون لمس {label.split('/')[0]} به سمت EQ و {label.split('/')[1]}",
                len(hi_touch_idxs)
            )

    # ------------------------------------------------------------------
    # B7/S7: ادامه‌ی مومنتوم پامپ/دامپ — بدون نیاز به ری‌تست سطح شکسته
    # ------------------------------------------------------------------
    # پوشش حالتی که در بررسی مشترک با کاربر مشخص شد: وقتی قیمت با یک پامپ/
    # دامپ شدید از PDH/PDL فاصله می‌گیرد و هرگز برای ری‌تست برنمی‌گردد، هیچ‌کدام
    # از B1..B5/S1..S5 سیگنالی نمی‌دهند (B5/S5 صریحاً منتظر ری‌تست‌اند). این
    # دو سناریو، با سه معیار مستقل، مومنتوم رو به‌جای ری‌تست معتبر می‌دانند:
    #   ۱) فاصله: قیمت حداقل max(momentum_dist_atr_mult×ATR, momentum_dist_pct×سطح)
    #      از PDH (برای B7) یا PDL (برای S7) دورتر رفته باشد.
    #   ۲) پولبک کوتاه: کندل قبلی خلاف جهت مومنتوم بوده (نه یک کندل تصادفی
    #      وسط روند، بلکه حداقل یک وقفه/نفس کوتاه) — طبق تصمیم کاربر، به‌جای
    #      ورود آنی یا صبر برای ری‌تست کامل به سطح.
    #   ۳) هم‌جهتی با EMA50 (فیلتر مومنتوم واقعی، نه فقط نویز).
    # SL پشت همان کندل پولبک (با بافر ATR استاندارد) + TP بر اساس اکستنشن ATR
    # (چون دیگر مرز مقابل رنج به‌عنوان هدف معتبر جلوتر از قیمت وجود ندارد).
    # SL پشت همان کندل پولبک (با بافر ATR استاندارد)، اما با یک سقف ATR روی
    # فاصله‌ی ریسک (momentum_sl_max_atr_mult) — طبق شواهد واقعی معاملات (بررسی
    # مشترک با کاربر): وقتی کندل پولبک بدنه/دم بزرگی داشت، فاصله‌ی SL می‌توانست
    # چند برابر ATR شود در حالی که TP ثابت (بر مبنای ATR) بود، و همین باعث رد
    # شدن ~۹۰٪ کاندیدهای B7 به‌خاطر RR ناکافی (میانه‌ی RR رد‌شده تنها ۰.۶R) شده
    # بود. اکنون ریسک هرگز از این سقف بیشتر نمی‌شود (نزدیک‌ترین/تنگ‌ترین سطح
    # انتخاب می‌شود)، و TP هم کمی افزایش یافته تا فضای پاداش واقعی‌تر باشد.
    prev_row = d.loc[idx_now - 1] if (idx_now - 1) in d.index else None
    ema50_now = _safe_float(curr_row.get("ema50"), close_now)
    rsi_now = _safe_float(curr_row.get("rsi"), 50.0)

    # ------------------------------------------------------------------
    # B7 (نسخه ارتقایافته - ستاپ BP در روند بر مبنای اکستنشن ساختاری)
    # ------------------------------------------------------------------
    range_width = (hi_level - lo_level)
    ext_level_1_up = hi_level + (range_width * cfg.get("extension_atr_mult", 0.50))
    ext_level_2_up = hi_level + range_width

    if prev_row is not None:
        # ۱. قیمت از PDH فاصله گرفته ولی هنوز به سقف اکستنشن اول یا دوم نرسیده و فضا دارد
        dist_above_hi = close_now - hi_level
        min_break_dist = max(atr_now * 1.0, hi_level * 0.008)
        has_extension_room = (ext_level_1_up - close_now) >= (atr_now * 0.50)

        # ۲. بررسی پولبک کم‌عمق در روند (کندل قبلی قرمز و کم‌بدنه / مکث واقعی)
        prev_is_pullback = (
            _safe_float(prev_row.get("close")) < _safe_float(prev_row.get("open")) and
            _safe_float(prev_row.get("body_ratio")) <= float(cfg.get("momentum_pullback_max_body_ratio", 0.35))
        )

        # ۳. عدم اشباع شدید خرید و هم‌جهتی کامل با EMA50
        not_exhausted_up = rsi_now <= float(cfg.get("momentum_rsi_exhaustion_high", 78.0))
        trend_aligned = close_now > ema50_now

        if (dist_above_hi >= min_break_dist and bullish_confirm_now and
                prev_is_pullback and trend_aligned and not_exhausted_up and has_extension_room):

            # حد ضرر: پشت کف کندل پولبک با سقف ایمنی ATR
            pullback_low = _safe_float(prev_row.get("low"))
            sl_by_pullback = pullback_low - (atr_now * cfg["sl_atr_buffer_tight"])
            sl_by_cap = close_now - (atr_now * float(cfg.get("momentum_sl_max_atr_mult", 1.2)))
            sl = max(sl_by_pullback, sl_by_cap)

            # تارگت ساختاری: سطح اول اکستنشن رنج (TP1) و سطح دوم اکستنشن (TP2)
            tp = ext_level_1_up

            if (close_now - sl) > 0 and (tp - close_now) / (close_now - sl) >= float(cfg.get("min_rr", 1.10)):
                add_candidate(
                    "B7", "BUY", sl, tp, None,
                    f"ستاپ BP مومنتوم: پولبک کم‌بدنه پس از شکست {label.split('/')[0]} و هدف‌گیری اکستنشن رنج ({tp:.5g})",
                    0
                )

    # ------------------------------------------------------------------
    # S7 (نسخه ارتقایافته - ستاپ BP در روند نزولی بر مبنای اکستنشن ساختاری)
    # ------------------------------------------------------------------
    ext_level_1_down = lo_level - (range_width * cfg.get("extension_atr_mult", 0.50))
    ext_level_2_down = lo_level - range_width

    if prev_row is not None:
        # ۱. قیمت از PDL فاصله گرفته ولی هنوز به کف اکستنشن اول نرسیده است
        dist_below_lo = lo_level - close_now
        min_break_dist = max(atr_now * 1.0, lo_level * 0.008)
        has_extension_room = (close_now - ext_level_1_down) >= (atr_now * 0.50)

        # ۲. بررسی پولبک کم‌عمق در روند نزولی (کندل قبلی سبز و کم‌بدنه / مکث روند)
        prev_is_pullback = (
            _safe_float(prev_row.get("close")) > _safe_float(prev_row.get("open")) and
            _safe_float(prev_row.get("body_ratio")) <= float(cfg.get("momentum_pullback_max_body_ratio", 0.35))
        )

        # ۳. عدم اشباع شدید فروش و هم‌جهتی کامل با روند نزولی EMA50
        not_exhausted_down = rsi_now >= float(cfg.get("momentum_rsi_exhaustion_low", 22.0))
        trend_aligned = close_now < ema50_now

        if (dist_below_lo >= min_break_dist and bearish_confirm_now and
                prev_is_pullback and trend_aligned and not_exhausted_down and has_extension_room):

            # حد ضرر: پشت سقف کندل پولبک با سقف ایمنی ATR
            pullback_high = _safe_float(prev_row.get("high"))
            sl_by_pullback = pullback_high + (atr_now * cfg["sl_atr_buffer_tight"])
            sl_by_cap = close_now + (atr_now * float(cfg.get("momentum_sl_max_atr_mult", 1.2)))
            sl = min(sl_by_pullback, sl_by_cap)

            # تارگت ساختاری: سطح اول اکستنشن پایین رنج (TP1)
            tp = ext_level_1_down

            if (sl - close_now) > 0 and (close_now - tp) / (sl - close_now) >= float(cfg.get("min_rr", 1.10)):
                add_candidate(
                    "S7", "SELL", sl, tp, None,
                    f"ستاپ BP مومنتوم: پولبک کم‌بدنه پس از شکست {label.split('/')[1]} و هدف‌گیری اکستنشن رنج ({tp:.5g})",
                    0
                )

    # --- فیلتر ستاپ‌های خاموش‌شده‌ی دستی (منوی «ستاپ‌های معاملاتی») ---
    # این فیلتر بعد از تولید همه‌ی کاندیدها و قبل از انتخاب بهترین اعمال
    # می‌شود؛ یعنی هر منطق تشخیص/امتیازدهی بالا دست‌نخورده می‌ماند، فقط
    # کدهای خاموش‌شده اجازه‌ی رقابت برای «بهترین کاندید» را ندارند.
    disabled_setups = set(cfg.get("disabled_setups") or [])
    if disabled_setups and candidates:
        candidates = [c for c in candidates if c["code"] not in disabled_setups]

    if not candidates:
        if diag is not None:
            diag['gate'] = 'no_scenario_matched' if not disabled_setups else 'all_candidates_disabled'
        return None

    best = max(candidates, key=lambda c: c["total_score"])
    if diag is not None:
        diag['gate'] = 'candidate_found'
        diag['best_code'] = best['code']
        diag['best_score'] = best['total_score']
        diag['candidate_count'] = len(candidates)
    return best
