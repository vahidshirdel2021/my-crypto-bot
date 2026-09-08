# -*- coding: utf-8 -*-
"""
signal_engine.common.trend_context
====================================
سرویس مشترک تشخیص روند — طبق تمام اسناد طراحی («اکثر الگوها به تشخیص
روند قبلی نیاز دارند؛ یک سرویس مشترک ساخته شود، نه اینکه هر موتور مال
خودش را دوباره بسازد»).

دو روش پیاده‌سازی شده که هر دو پشت یک اینترفیس مشترک در دسترس‌اند:
    1) swing_structure  — بر اساس توالی سوئینگ‌های تأییدشده (HH/HL یا
       LH/LL). این روش دقیق‌تر و ساختاری است اما نیاز به جریان سوئینگ
       (از signal_engine.swing_structure) دارد.
    2) ema_slope         — بر اساس شیب یک EMA (پیش‌فرض دوره ۲۰) — روش
       ساده‌تر و مستقل از موتور سوئینگ، برای جاهایی که فقط قیمت خام در
       دسترس است (یا به‌عنوان تأیید مکمل کنار روش اول).

خروجی هر دو روش یک TrendContext با فیلد trend در {"uptrend","downtrend",
"range"} و یک عدد strength در [0, 1] است — تا موتورهای بالادستی بتوانند
هم به مقدار گسسته و هم به شدت آن برای امتیازدهی confidence نگاه کنند.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal, Optional, Sequence

import numpy as np
import pandas as pd

TrendLabel = Literal["uptrend", "downtrend", "range"]


@dataclass(frozen=True)
class TrendContext:
    trend: TrendLabel
    strength: float  # در بازه‌ی [0, 1] — هرچه بزرگ‌تر، روند «قطعی‌تر»
    method: str  # "swing_structure" | "ema_slope"
    evidence: dict


# ---------------------------------------------------------------------------
# روش ۱: بر اساس ساختار سوئینگ (HH/HL یا LH/LL)
# ---------------------------------------------------------------------------

def trend_from_swings(
    swing_prices: Sequence[float],
    swing_types: Sequence[Literal["high", "low"]],
    lookback_swings: int = 4,
) -> TrendContext:
    """روند را از روی آخرین چند سوئینگ تأییدشده تشخیص می‌دهد.

    swing_prices / swing_types باید هم‌طول باشند و به ترتیب زمانی
    (قدیمی → جدید) مرتب شده باشند — این دقیقاً همان قراردادی است که
    signal_engine.swing_structure برای جریان سوئینگ‌های تأییدشده تولید
    می‌کند.

    قانون (طبق سند Swing Detection Engine، بخش ۶.۱):
        uptrend   : دو swing high آخر صعودی هستند AND دو swing low آخر
                    صعودی هستند (Higher-High / Higher-Low)
        downtrend : حالت آینه‌ای (Lower-High / Lower-Low)
        range     : هیچ‌کدام برقرار نیست
    """
    if len(swing_prices) != len(swing_types):
        raise ValueError("swing_prices و swing_types باید هم‌طول باشند")

    highs = [p for p, t in zip(swing_prices, swing_types) if t == "high"]
    lows = [p for p, t in zip(swing_prices, swing_types) if t == "low"]

    highs = highs[-2:]
    lows = lows[-2:]

    if len(highs) < 2 or len(lows) < 2:
        return TrendContext(
            trend="range", strength=0.0, method="swing_structure",
            evidence={"reason": "insufficient_confirmed_swings", "n_highs": len(highs), "n_lows": len(lows)},
        )

    higher_highs = highs[-1] > highs[-2]
    higher_lows = lows[-1] > lows[-2]
    lower_highs = highs[-1] < highs[-2]
    lower_lows = lows[-1] < lows[-2]

    if higher_highs and higher_lows:
        # شدت روند: نسبت پیشرفت (چقدر HH از HL بیشتر/کمتر پیش رفته) به‌عنوان
        # سنجه‌ی ساده‌ی همبستگی/تمیزی روند استفاده می‌شود.
        hh_pct = (highs[-1] - highs[-2]) / max(abs(highs[-2]), 1e-9)
        hl_pct = (lows[-1] - lows[-2]) / max(abs(lows[-2]), 1e-9)
        strength = float(np.clip(min(hh_pct, hl_pct) * 20.0, 0.2, 1.0))
        return TrendContext(
            trend="uptrend", strength=strength, method="swing_structure",
            evidence={"last_two_highs": highs, "last_two_lows": lows},
        )

    if lower_highs and lower_lows:
        lh_pct = (highs[-2] - highs[-1]) / max(abs(highs[-2]), 1e-9)
        ll_pct = (lows[-2] - lows[-1]) / max(abs(lows[-2]), 1e-9)
        strength = float(np.clip(min(lh_pct, ll_pct) * 20.0, 0.2, 1.0))
        return TrendContext(
            trend="downtrend", strength=strength, method="swing_structure",
            evidence={"last_two_highs": highs, "last_two_lows": lows},
        )

    return TrendContext(
        trend="range", strength=0.0, method="swing_structure",
        evidence={"last_two_highs": highs, "last_two_lows": lows},
    )


# ---------------------------------------------------------------------------
# روش ۲: بر اساس شیب EMA (مستقل از موتور سوئینگ)
# ---------------------------------------------------------------------------

def trend_from_ema_slope(
    df: pd.DataFrame,
    ema_period: int = 20,
    slope_lookback: int = 5,
    flat_slope_threshold_pct: float = 0.0005,
) -> TrendContext:
    """روند را از روی شیب یک EMA تشخیص می‌دهد — بدون نیاز به سوئینگ.

    slope در واحد «درصد تغییر EMA به‌ازای هر کندل» سنجیده می‌شود تا بین
    نمادها/تایم‌فریم‌های با مقیاس قیمتی متفاوت قابل مقایسه باشد.
    """
    if df is None or df.empty or "close" not in df.columns:
        return TrendContext(trend="range", strength=0.0, method="ema_slope",
                             evidence={"reason": "no_data"})
    if len(df) < ema_period + slope_lookback:
        return TrendContext(trend="range", strength=0.0, method="ema_slope",
                             evidence={"reason": "insufficient_bars"})

    ema = df["close"].astype(float).ewm(span=ema_period, adjust=False).mean()
    recent = ema.iloc[-slope_lookback:]
    slope_pct_per_bar = (recent.iloc[-1] - recent.iloc[0]) / max(abs(recent.iloc[0]), 1e-9) / max(slope_lookback, 1)

    if slope_pct_per_bar > flat_slope_threshold_pct:
        strength = float(np.clip(slope_pct_per_bar / (flat_slope_threshold_pct * 10.0), 0.2, 1.0))
        return TrendContext(trend="uptrend", strength=strength, method="ema_slope",
                             evidence={"ema_period": ema_period, "slope_pct_per_bar": slope_pct_per_bar})
    if slope_pct_per_bar < -flat_slope_threshold_pct:
        strength = float(np.clip(abs(slope_pct_per_bar) / (flat_slope_threshold_pct * 10.0), 0.2, 1.0))
        return TrendContext(trend="downtrend", strength=strength, method="ema_slope",
                             evidence={"ema_period": ema_period, "slope_pct_per_bar": slope_pct_per_bar})
    return TrendContext(trend="range", strength=0.0, method="ema_slope",
                         evidence={"ema_period": ema_period, "slope_pct_per_bar": slope_pct_per_bar})


def combined_trend_context(
    df: pd.DataFrame,
    swing_prices: Optional[Sequence[float]] = None,
    swing_types: Optional[Sequence[Literal["high", "low"]]] = None,
    ema_period: int = 20,
) -> TrendContext:
    """اگر جریان سوئینگ در دسترس باشد از روش swing_structure استفاده
    می‌کند (دقیق‌تر و اولویت‌دار طبق تمام اسناد طراحی)، وگرنه به
    ema_slope سقوط می‌کند. این تابعی است که بقیه‌ی موتورهای پروژه باید
    صدا بزنند، نه توابع سطح پایین‌تر بالا را مستقیماً.
    """
    if swing_prices and swing_types and len(swing_prices) >= 2:
        return trend_from_swings(swing_prices, swing_types)
    return trend_from_ema_slope(df, ema_period=ema_period)
