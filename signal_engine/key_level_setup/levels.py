# -*- coding: utf-8 -*-
"""
signal_engine.key_level_setup.levels
=======================================
پیاده‌سازی بخش ۳ سند «Key-Level Setup Detection Engine»: محاسبه‌ی ۹ سطح
مرجع (P4H/P4L/P4EQ، PDH/PDL/PDEQ، PWH/PWL/PWEQ، PMH/PML/PMEQ) از روی *دوره‌ی کاملاً
بسته‌شده‌ی قبلی* (هرگز دوره‌ی در حال شکل‌گیری).

این ماژول جایگزین مستقیم منطق سطوح در pdh_eq_pdl_engine.py (نسخه‌ی
قدیمی) است. برای اطمینان از صفر تغییر رفتاری حین مهاجرت، تابع
`get_reference_levels` و `min_klines_for_levels` دقیقاً همان امضا و
خروجی نسخه‌ی قدیمی را حفظ کرده‌اند (که مستقیماً در bot.py برای رسم
سطوح PDH/PDL روی چارت استفاده می‌شوند) — منطق محاسباتی داخلی هم بیت‌به‌بیت
همان است (همان الگوریتم گروه‌بندی + همان آستانه‌ی کامل‌بودن دوره
MIN_PERIOD_COMPLETENESS_RATIO=0.85)، فقط بازآرایی و مستندسازی شده.

علاوه بر این، `compute_key_levels` تابع جدید و اصلی طبق طرحواره‌ی سند
(بخش ۳.۳ — LevelSet با همه‌ی ۹ سطح هم‌زمان) است که KLSDE و بقیه‌ی موتورهای
جدید باید از این پس از همین استفاده کنند.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import pandas as pd

# نسبت حداقلی کندل‌های موجود یک دوره نسبت به تعداد موردانتظار تا آن دوره
# «کامل» تلقی شود. اگر داده کافی برای دوره‌ی قبلی نباشد، سطح None
# برمی‌گردد تا هیچ سیگنالی روی سطح نادرست/بریده ساخته نشود.
MIN_PERIOD_COMPLETENESS_RATIO = 0.85


def _timestamp_to_datetime(df: pd.DataFrame) -> pd.Series:
    ts = pd.to_numeric(df["timestamp"], errors="coerce")
    unit = "ms" if float(ts.dropna().median() or 0) > 1e12 else "s"
    return pd.to_datetime(ts, unit=unit, utc=True)


def _infer_bar_seconds(d: pd.DataFrame) -> float:
    diffs = d["_dt"].diff().dropna()
    if diffs.empty:
        return 0.0
    return float(diffs.dt.total_seconds().median() or 0.0)


def _compute_period_levels(df: pd.DataFrame, period_key_fn, expected_seconds: float) -> Tuple:
    """پیاده‌سازی مشترک سه دوره (روز/هفته/ماه) — تفاوت فقط در تابع
    period_key_fn (چگونگی گروه‌بندی timestamp به دوره) و طول موردانتظار
    دوره بر حسب ثانیه است.

    خروجی: (d, high, low, eq) — d دیتافریم غنی‌شده با ستون‌های کمکی است
    (برای کالر قدیمی که به آن نیاز دارد)؛ high/low/eq اگر دوره‌ی قبلی
    کامل نبود یا داده کافی نبود، None هستند.
    """
    if df is None or len(df) < 50 or "timestamp" not in df.columns:
        return None, None, None, None
    d = df.copy()
    d["_dt"] = _timestamp_to_datetime(d)
    if d["_dt"].isna().all():
        return None, None, None, None
    d = d.sort_values("_dt").reset_index(drop=True)
    bar_seconds = _infer_bar_seconds(d)

    d["_period"] = period_key_fn(d)
    order = d.groupby("_period", sort=False)["_dt"].min().sort_values().index
    grp = d.groupby("_period", sort=False).agg(_hi=("high", "max"), _lo=("low", "min"), _n=("high", "size"))
    grp = grp.reindex(order)
    grp["_prev_hi"] = grp["_hi"].shift(1)
    grp["_prev_lo"] = grp["_lo"].shift(1)
    grp["_prev_n"] = grp["_n"].shift(1)

    if bar_seconds > 0:
        expected_bars = max(1.0, expected_seconds / bar_seconds)
        grp["_prev_complete"] = grp["_prev_n"] >= expected_bars * MIN_PERIOD_COMPLETENESS_RATIO
    else:
        grp["_prev_complete"] = False

    d = d.merge(grp[["_prev_hi", "_prev_lo", "_prev_complete"]], left_on="_period", right_index=True, how="left")
    d = d.reset_index(drop=True)

    idx_now = len(d) - 2  # آخرین کندل بسته‌شده (طبق قرارداد کل پروژه)
    if idx_now < 0:
        return d, None, None, None
    hi, lo = d.at[idx_now, "_prev_hi"], d.at[idx_now, "_prev_lo"]
    if pd.isna(hi) or pd.isna(lo) or not bool(d.at[idx_now, "_prev_complete"]):
        return d, None, None, None
    hi, lo = float(hi), float(lo)
    if hi <= lo:
        return d, None, None, None
    eq = (hi + lo) / 2.0
    return d, hi, lo, eq


def compute_prev_day_levels(df: pd.DataFrame):
    """PDH/PDL/PDEQ از آخرین شبانه‌روز کامل UTC."""
    return _compute_period_levels(
        df,
        period_key_fn=lambda d: d["_dt"].dt.floor("D").dt.date,
        expected_seconds=86400.0,
    )


def compute_prev_1h_levels(df: pd.DataFrame):
    """P1H/P1L/P1EQ از آخرین ساعت کامل UTC (۰۰:۰۰، ۰۱:۰۰، ...).

    لایه‌ی درون‌روزی‌ترین این پروژه — دقیق‌ترین سطح برای تایم‌فریم‌های
    اجرای کوتاه (۵/۱۵ دقیقه). طبق درخواست کاربر، بین ۴ساعته و خودِ
    تایم‌فریم اجرا قرار می‌گیرد.
    """
    return _compute_period_levels(
        df,
        period_key_fn=lambda d: d["_dt"].dt.floor("1h"),
        expected_seconds=3600.0,
    )


def compute_prev_4h_levels(df: pd.DataFrame):
    """P4H/P4L/P4EQ از آخرین بازه‌ی ۴ساعته‌ی کامل UTC (۰۰:۰۰، ۰۴:۰۰، ۰۸:۰۰، ...).

    طبق درخواست کاربر: یک لایه‌ی میانی بین روزانه و درون‌روزی برای
    تست ستاپ‌های KLSDE — همان تابع مشترک _compute_period_levels با
    period_key_fn=floor('4h') و expected_seconds متناظر با ۴ ساعت.
    pandas.Timestamp.floor('4h') نسبت به مبدأ epoch (۱۹۷۰-۰۱-۰۱ ۰۰:۰۰
    UTC، که خودش مضربی از ۴ ساعت است) گرد می‌شود، پس دقیقاً روی مرزهای
    ۰۰/۰۴/۰۸/۱۲/۱۶/۲۰ ساعت UTC می‌افتد — هماهنگ با قرارداد بقیه‌ی سطوح
    این پروژه (UTC، بدون آفست منطقه‌ای).
    """
    return _compute_period_levels(
        df,
        period_key_fn=lambda d: d["_dt"].dt.floor("4h"),
        expected_seconds=4 * 3600.0,
    )


def compute_prev_week_levels(df: pd.DataFrame):
    """PWH/PWL/PWEQ از آخرین هفته‌ی ISO کامل (شروع هفته: دوشنبه ۰۰:۰۰ UTC، تقویم کریپتویی ۲۴/۷)."""
    def _week_key(d):
        iso = d["_dt"].dt.isocalendar()
        return iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)
    return _compute_period_levels(df, period_key_fn=_week_key, expected_seconds=7 * 86400.0)


def compute_prev_month_levels(df: pd.DataFrame):
    """PMH/PML/PMEQ از آخرین ماه تقویمی کامل (UTC). طول ماه متغیر است؛ ۲۸
    روز (کمینه‌ی محتاطانه) به‌عنوان مبنای «کامل بودن» استفاده می‌شود.
    """
    return _compute_period_levels(
        df,
        period_key_fn=lambda d: d["_dt"].dt.strftime("%Y-%m"),
        expected_seconds=28 * 86400.0,
    )


# ---------------------------------------------------------------------------
# حداقل تعداد کندل لازم به‌ازای هر تایم‌فریم (برای درخواست صحیح از صرافی)
# ---------------------------------------------------------------------------

LEVEL_SOURCE_BY_TIMEFRAME = {
    "5min": "daily",
    "15min": "daily",
    "1hour": "weekly",
    "4hour": "weekly",
}

MIN_KLINES_FOR_LEVELS = {
    "5min": 3 * 288 + 20,
    "15min": 3 * 96 + 20,
    "1hour": 3 * 168 + 20,
    "4hour": 3 * 42 + 20,
}


def min_klines_for_levels(timeframe: str) -> int:
    return int(MIN_KLINES_FOR_LEVELS.get(timeframe, 300))


def get_reference_levels(df: pd.DataFrame, timeframe: str, level_override=None):
    """امضا و رفتار عیناً مطابق نسخه‌ی قدیمی pdh_eq_pdl_engine.py، برای
    سازگاری کامل با bot.py حین مهاجرت (رسم سطوح روی چارت و غیره).

    خروجی: (d, high_level, low_level, eq, label, level_source)
    """
    source_default = LEVEL_SOURCE_BY_TIMEFRAME.get(timeframe, "daily")
    if level_override is not None:
        src, hi, lo, eq = level_override
        d, _, _, _ = (
            compute_prev_week_levels(df) if source_default == "weekly" else compute_prev_day_levels(df)
        )
        label = {"daily": "PDH/PDL", "weekly": "PWH/PWL", "monthly": "PMH/PML"}.get(src, "PDH/PDL")
        return d, hi, lo, eq, label, src
    if source_default == "weekly":
        d, hi, lo, eq = compute_prev_week_levels(df)
        return d, hi, lo, eq, "PWH/PWL", source_default
    d, hi, lo, eq = compute_prev_day_levels(df)
    return d, hi, lo, eq, "PDH/PDL", source_default


# ---------------------------------------------------------------------------
# رابط جدید طبق سند KLSDE، بخش ۳.۳ — LevelSet با هر ۹ سطح هم‌زمان
# ---------------------------------------------------------------------------

@dataclass
class LevelInfo:
    price: Optional[float]
    period_start: Optional[str] = None
    period_end: Optional[str] = None


@dataclass
class LevelSet:
    symbol: str
    as_of_time: Optional[str]
    levels: Dict[str, LevelInfo] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "as_of_time": self.as_of_time,
            "levels": {k: {"price": v.price, "period_start": v.period_start, "period_end": v.period_end}
                       for k, v in self.levels.items()},
        }


def compute_key_levels(df: pd.DataFrame, symbol: str = "") -> LevelSet:
    """هر ۱۵ سطح (P1H/P1L/P1EQ, P4H/P4L/P4EQ, PDH/PDL/PDEQ, PWH/PWL/PWEQ,
    PMH/PML/PMEQ) را هم‌زمان از روی همان df (که باید شامل کل تاریخچه‌ی
    لازم برای هر پنج دوره باشد) محاسبه می‌کند و در قالب LevelSet
    برمی‌گرداند — طبق سند بخش ۳.۳ (۹ سطح اصلی) + لایه‌های ۴ساعته و
    ۱ساعته‌ی اضافه‌شده.

    توجه: این تابع مستقل از تایم‌فریم اجراست (KLSDE این را روی دیتای
    high-enough-resolution صدا می‌زند، نه لزوماً همان تایم‌فریم اجرا).
    """
    h1_d, p1h, p1l, p1eq = compute_prev_1h_levels(df)
    h4_d, p4h, p4l, p4eq = compute_prev_4h_levels(df)
    day_d, pdh, pdl, pdeq = compute_prev_day_levels(df)
    week_d, pwh, pwl, pweq = compute_prev_week_levels(df)
    month_d, pmh, pml, pmeq = compute_prev_month_levels(df)

    as_of = None
    if day_d is not None and not day_d.empty:
        as_of = str(day_d["_dt"].iloc[-1])
    elif h4_d is not None and not h4_d.empty:
        as_of = str(h4_d["_dt"].iloc[-1])
    elif h1_d is not None and not h1_d.empty:
        as_of = str(h1_d["_dt"].iloc[-1])

    levels = {
        "P1H": LevelInfo(p1h),
        "P1L": LevelInfo(p1l),
        "P1EQ": LevelInfo(p1eq),
        "P4H": LevelInfo(p4h),
        "P4L": LevelInfo(p4l),
        "P4EQ": LevelInfo(p4eq),
        "PDH": LevelInfo(pdh),
        "PDL": LevelInfo(pdl),
        "PDEQ": LevelInfo(pdeq),
        "PWH": LevelInfo(pwh),
        "PWL": LevelInfo(pwl),
        "PWEQ": LevelInfo(pweq),
        "PMH": LevelInfo(pmh),
        "PML": LevelInfo(pml),
        "PMEQ": LevelInfo(pmeq),
    }
    return LevelSet(symbol=symbol, as_of_time=as_of, levels=levels)
