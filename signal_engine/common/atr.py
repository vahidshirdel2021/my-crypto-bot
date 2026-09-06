# -*- coding: utf-8 -*-
"""
signal_engine.common.atr
=========================
یگانه محل محاسبه‌ی ATR (Average True Range) در کل پروژه‌ی signal_engine.

طبق تمام ۶ سند طراحی (Pattern Recognition، Swing/Structure، Market Cycle،
Candlestick، Key-Level Setup، Unified Confluence Layer): «یک ابزار ATR
مشترک در کل پروژه استفاده شود، نه اینکه هر موتور مال خودش را دوباره
پیاده‌سازی کند». این ماژول همان نقطه‌ی مشترک است.

این تابع کاملاً بدون‌حالت (stateless) و idempotent است: روی یک DataFrame
با ستون‌های استاندارد OHLC اجرا می‌شود و ستون `atr` را (اگر نبود) اضافه
می‌کند؛ اگر از قبل با همان دوره محاسبه شده باشد، دوباره از صفر حساب
نمی‌کند مگر force=True داده شود.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

REQUIRED_OHLC_COLUMNS = ("open", "high", "low", "close")


def _validate_ohlc(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_OHLC_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"signal_engine.common.atr: ستون‌های OHLC ناقص است، کم است: {missing}"
        )


def true_range(df: pd.DataFrame) -> pd.Series:
    """محاسبه‌ی True Range خام (بدون میانگین‌گیری) برای هر کندل.

    True Range = max(
        high - low,
        abs(high - prev_close),
        abs(low  - prev_close),
    )

    ردیف اول (که close قبلی ندارد) صرفاً high-low آن کندل است — این رفتار
    استاندارد و مورد انتظار در همه‌ی پیاده‌سازی‌های رایج ATR است.
    """
    _validate_ohlc(df)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    prev_close = df["close"].astype(float).shift(1)

    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    # ردیف اول: prev_close وجود ندارد → NaN در دو ستون آخر → fillna با high-low
    tr.iloc[0] = float(high.iloc[0] - low.iloc[0])
    return tr


def compute_atr(df: pd.DataFrame, period: int = 14, *, force: bool = False,
                 column: str = "atr") -> pd.DataFrame:
    """ستون ATR را به df اضافه می‌کند و همان DataFrame (کپی) را برمی‌گرداند.

    Parameters
    ----------
    df : DataFrame با ستون‌های OHLC استاندارد (open/high/low/close).
    period : دوره‌ی میانگین‌گیری (پیش‌فرض پروژه: 14 — طبق کانفیگ همه‌ی
        اسناد طراحی).
    force : اگر True باشد، حتی اگر ستون از قبل موجود بود، دوباره محاسبه
        می‌شود (مثلاً وقتی period عوض شده).
    column : نام ستون خروجی (پیش‌فرض 'atr').

    خروجی: کپی از df با ستون [column] اضافه/به‌روزشده.

    از میانگین متحرک نمایی (Wilder's smoothing / RMA) استفاده می‌شود که
    استاندارد صنعتی محاسبه‌ی ATR است (نه SMA ساده)، چون به تغییرات
    نوسان اخیر سریع‌تر واکنش نشان می‌دهد در حالی که هنوز نسبتاً پایدار
    است — همان رفتاری که در همه‌ی موتورهای این پروژه (فیلتر نویز سوئینگ،
    تلورانس برخورد سطوح کلیدی، آستانه‌ی هارامی/کندل‌استیک و...) لازم است.
    """
    if period <= 0:
        raise ValueError("period باید عدد صحیح مثبت باشد")
    if df is None or df.empty:
        raise ValueError("df نمی‌تواند خالی/None باشد")

    out = df.copy()
    if column in out.columns and not force:
        return out

    tr = true_range(out)
    # Wilder's smoothing == EMA با alpha = 1/period
    atr = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    out[column] = atr
    return out


def latest_atr(df: pd.DataFrame, period: int = 14) -> float:
    """آخرین مقدار معتبر ATR را برمی‌گرداند (float)، یا NaN اگر داده کافی
    نبود. برای فراخوانی‌های سریع/نقطه‌ای (مثلاً «فاصله‌ی این برخورد از
    سطح چند ATR است؟») بدون نیاز به نگه‌داشتن کل DataFrame تغییریافته.
    """
    d = compute_atr(df, period=period)
    val = d["atr"].iloc[-1]
    return float(val) if pd.notna(val) else float("nan")


def min_bars_for_atr(period: int = 14) -> int:
    """حداقل تعداد کندل لازم برای یک مقدار ATR معتبر (نه NaN).

    Wilder's smoothing با min_periods=period پیاده شده، پس دقیقاً `period`
    کندل برای اولین مقدار غیر-NaN لازم است. کالرها (مثلاً KLSDE هنگام
    محاسبه‌ی حداقل تعداد کندل لازم برای سطوح) باید این تابع را صدا بزنند
    تا مقدار به‌صورت هاردکد در چند جای پروژه تکرار نشود.
    """
    return int(period)
