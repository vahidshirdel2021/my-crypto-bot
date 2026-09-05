# -*- coding: utf-8 -*-
"""
signal_engine.swing_structure.mtf_alignment
=============================================
پیاده‌سازی بخش ۷ سند: هر رویداد ساختاری روی تایم‌فریم پایین (مثلاً ۵m)
با روند فعلی تایم‌فریم بالا (مثلاً ۱۵m) در همان لحظه (بدون نگاه به آینده
حتی بین تایم‌فریم‌ها) برچسب می‌خورد: aligned / counter_trend / neutral.

این ماژول تصمیم نمی‌گیرد کدام سیگنال معتبرتر است — فقط تگ می‌زند؛
تصمیم‌گیری روی این تگ به‌عهده‌ی لایه‌ی بالادستی (Unified Signal Layer) است.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal

from signal_engine.swing_structure.structure import StructureEvent, trend_state_from_swings
from signal_engine.swing_structure.swings import SwingPoint

AlignmentLabel = Literal["aligned", "counter_trend", "neutral"]


@dataclass
class AlignedContext:
    lower_tf_event_id: str
    lower_tf_timeframe: str
    higher_tf_timeframe: str
    higher_tf_trend_at_event_time: str
    alignment: AlignmentLabel


def align_timeframes(
    lower_tf_events: List[StructureEvent],
    lower_tf_event_times,  # Sequence هم‌طول با lower_tf_events: timestamp هر رویداد
    higher_tf_swings: List[SwingPoint],
    higher_tf_swing_times,  # Sequence هم‌طول با higher_tf_swings: timestamp confirmed_at هر سوئینگ
    lower_tf_label: str,
    higher_tf_label: str,
) -> List[AlignedContext]:
    """برای هر رویداد ساختاری تایم‌فریم پایین، روند تایم‌فریم بالا را *تا
    همان لحظه* (نه بعدتر) محاسبه و مقایسه می‌کند.

    Parameters
    ----------
    lower_tf_event_times / higher_tf_swing_times : باید timestamp قابل
        مقایسه (مثلاً pandas.Timestamp یا epoch seconds) باشند — این
        تابع عمداً از epoch/index داخلی df استفاده نمی‌کند چون دو
        تایم‌فریم index مستقل دارند؛ فقط timestamp واقعی قابل تطبیق است.
    """
    results: List[AlignedContext] = []

    # سوئینگ‌های تایم‌فریم بالا را بر اساس زمان تأیید مرتب می‌کنیم تا برای
    # هر رویداد بتوانیم فقط سوئینگ‌های «تا همان لحظه» را در نظر بگیریم.
    higher_paired = sorted(zip(higher_tf_swing_times, higher_tf_swings), key=lambda x: x[0])

    for event, event_time in zip(lower_tf_events, lower_tf_event_times):
        visible_higher_swings = [sw for t, sw in higher_paired if t <= event_time]
        higher_trend = trend_state_from_swings(visible_higher_swings) if visible_higher_swings else "range"

        if higher_trend == "range":
            alignment: AlignmentLabel = "neutral"
        elif (higher_trend == "uptrend" and event.direction == "bullish") or \
             (higher_trend == "downtrend" and event.direction == "bearish"):
            alignment = "aligned"
        else:
            alignment = "counter_trend"

        results.append(AlignedContext(
            lower_tf_event_id=event.id,
            lower_tf_timeframe=lower_tf_label,
            higher_tf_timeframe=higher_tf_label,
            higher_tf_trend_at_event_time=higher_trend,
            alignment=alignment,
        ))

    return results
