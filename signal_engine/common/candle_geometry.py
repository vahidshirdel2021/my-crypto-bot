# -*- coding: utf-8 -*-
"""
signal_engine.common.candle_geometry
======================================
پرایمیتیوهای مشترک هندسه‌ی کندل — طبق سند Candlestick Pattern Engine
(بخش ۳) و سند Market Cycle Engine (بخش ۵.۱، مدل ۴موجی ال بروکس)، هر دو
باید از همین یک پیاده‌سازی استفاده کنند، نه اینکه هرکدام دوباره بسازند.

هیچ منطق تشخیص روند/الگو اینجا نیست — فقط اعداد و برچسب‌های هندسیِ خام
یک کندل. تصمیم‌گیری (این کندل یعنی چکش است؟ یعنی trend_leg است؟) در
موتورهای بالادستی خودشان انجام می‌شود.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CandlePrimitive = Literal["large_body", "long_shadow", "doji", "small_body"]


@dataclass(frozen=True)
class CandleGeometry:
    body_top: float
    body_bottom: float
    body_size: float
    range_size: float
    upper_shadow: float
    lower_shadow: float
    is_bullish: bool
    is_bearish: bool
    body_to_range_ratio: float  # NaN اگر range_size == 0
    primitive: CandlePrimitive


def compute_candle_geometry(
    open_: float, high: float, low: float, close: float,
    *,
    large_body_threshold: float = 0.6,
    long_shadow_threshold: float = 1.5,  # نسبت به body_size
    doji_threshold: float = 0.10,
) -> CandleGeometry:
    """هندسه‌ی یک کندل را محاسبه و آن را به یکی از ۴ پرایمیتیو طبقه‌بندی
    می‌کند: large_body، long_shadow، doji، small_body.

    Parameters
    ----------
    large_body_threshold : حداقل body_to_range_ratio برای «بدنه‌ی بزرگ».
    long_shadow_threshold : حداقل نسبت (سایه / بدنه) برای «سایه‌ی بلند».
    doji_threshold : حداکثر body_to_range_ratio برای «دوجی».

    این آستانه‌ها دقیقاً همان مقادیر پیش‌فرض دو سند طراحی هستند (قابل
    override به‌ازای هر کالر — مثلاً CPDE می‌تواند doji_threshold را
    per-instrument (بر اساس نوسان‌پذیری واقعی نماد) تنظیم کند، دقیقاً طبق
    توصیه‌ی صریح سند در مورد بازارهای پرنوسان مثل کریپتو).
    """
    body_top = max(open_, close)
    body_bottom = min(open_, close)
    body_size = body_top - body_bottom
    range_size = high - low
    upper_shadow = high - body_top
    lower_shadow = body_bottom - low
    is_bullish = close > open_
    is_bearish = close < open_

    if range_size <= 0:
        # کندل صاف/بی‌رنج (نادر ولی باید بدون کرش هندل شود) — طبق سند
        # Pattern Recognition Engine، این حالت به‌عنوان دوجی منحط تلقی می‌شود.
        return CandleGeometry(
            body_top=body_top, body_bottom=body_bottom, body_size=body_size,
            range_size=0.0, upper_shadow=0.0, lower_shadow=0.0,
            is_bullish=is_bullish, is_bearish=is_bearish,
            body_to_range_ratio=float("nan"), primitive="doji",
        )

    ratio = body_size / range_size

    # اولویت: دوجی (بدنه‌ی کوچک نسبت به کل رنج) ابتدا بررسی می‌شود — دقیقاً
    # طبق تعریف صریح سند Candlestick Pattern Engine (که همین ratio را برای
    # تشخیص Gravestone/Dragonfly/Long-Legged Doji به کار می‌برد؛ این‌ها
    # می‌توانند سایه‌ی بسیار بلندی هم داشته باشند، پس اولویت‌دادن به
    # long_shadow قبل از doji باعث می‌شد این الگوهای دوجیِ رایج هرگز به‌عنوان
    # دوجی شناسایی نشوند). موتورهای دیگر (مثل Market Cycle Engine) که به
    # تمایز ظریف‌تری بین «سایه‌ی بلند اصلاحی» و «دوجیِ بی‌تصمیمی» نیاز دارند
    # باید منطق تشخیص مکمل خودشان را روی همین اعداد خام (upper_shadow/
    # lower_shadow/body_size) پیاده کنند، نه این‌که اولویت این فیلد مشترک
    # را برای همه‌ی مصرف‌کننده‌ها به نفع خودشان تغییر دهند.
    if ratio <= doji_threshold:
        primitive: CandlePrimitive = "doji"
    elif body_size > 0 and max(upper_shadow, lower_shadow) >= long_shadow_threshold * body_size:
        primitive = "long_shadow"
    elif ratio >= large_body_threshold:
        primitive = "large_body"
    else:
        primitive = "small_body"

    return CandleGeometry(
        body_top=body_top, body_bottom=body_bottom, body_size=body_size,
        range_size=range_size, upper_shadow=upper_shadow, lower_shadow=lower_shadow,
        is_bullish=is_bullish, is_bearish=is_bearish,
        body_to_range_ratio=ratio, primitive=primitive,
    )


def compute_candle_geometry_batch(
    df,
    *,
    large_body_threshold: float = 0.6,
    long_shadow_threshold: float = 1.5,
    doji_threshold: float = 0.10,
):
    """نسخه‌ی برداری (vectorized) همان منطق compute_candle_geometry، برای
    وقتی که یک موتور نیاز به هندسه‌ی *همه‌ی* کندل‌های یک سری دارد (مثل
    CPDE که برای هر کندل چک می‌کند آیا چکش/دوجی است). طبق پروفایل واقعی
    عملکرد این پروژه، فراخوانی نسخه‌ی اسکالر (تک‌کندلی) به ازای هر ردیف
    یک df بزرگ، گلوگاه اصلی بود؛ این تابع همان محاسبات را یک‌بار با
    numpy روی کل سری انجام می‌دهد.

    خروجی: دیکشنری از آرایه‌های numpy هم‌طول با df (نه لیستی از
    CandleGeometry — برای پرهیز از هزینه‌ی ساخت آبجکت به ازای هر ردیف).
    """
    import numpy as _np

    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)

    body_top = _np.maximum(o, c)
    body_bottom = _np.minimum(o, c)
    body_size = body_top - body_bottom
    range_size = h - l
    upper_shadow = h - body_top
    lower_shadow = body_bottom - l
    is_bullish = c > o
    is_bearish = c < o

    with _np.errstate(divide="ignore", invalid="ignore"):
        ratio = _np.where(range_size > 0, body_size / _np.where(range_size > 0, range_size, 1.0), _np.nan)

    max_shadow = _np.maximum(upper_shadow, lower_shadow)
    is_doji = ratio <= doji_threshold
    is_long_shadow = (~is_doji) & (body_size > 0) & (max_shadow >= long_shadow_threshold * _np.where(body_size > 0, body_size, 1.0))
    is_large_body = (~is_doji) & (~is_long_shadow) & (ratio >= large_body_threshold)
    # بقیه (نه doji، نه long_shadow، نه large_body) → small_body
    zero_range = range_size <= 0

    primitive = _np.full(len(df), "small_body", dtype=object)
    primitive[is_long_shadow] = "long_shadow"
    primitive[is_doji] = "doji"
    primitive[is_large_body] = "large_body"
    primitive[zero_range] = "doji"  # طبق نسخه‌ی اسکالر: کندل بی‌رنج → دوجی منحط

    return {
        "body_top": body_top, "body_bottom": body_bottom, "body_size": body_size,
        "range_size": range_size, "upper_shadow": upper_shadow, "lower_shadow": lower_shadow,
        "is_bullish": is_bullish, "is_bearish": is_bearish,
        "body_to_range_ratio": ratio, "primitive": primitive,
    }
