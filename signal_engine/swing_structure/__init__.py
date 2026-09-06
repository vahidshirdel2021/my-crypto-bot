# -*- coding: utf-8 -*-
"""
signal_engine.swing_structure
================================
پیاده‌سازی کامل سند «Swing Detection & Market Structure Engine»:
    - detect_swings          → Stage 1-4 (سوئینگ‌های واقعی، فیلترشده از نویز)
    - detect_structure_events → BOS / CHoCH روی سوئینگ‌های تأییدشده
    - align_timeframes        → تگ‌گذاری aligned/counter_trend/neutral بین ۵m و ۱۵m

هیچ‌کدام از این توابع سفارش نمی‌گذارند یا از موجودی/پوزیشن خبر دارند —
فقط رویداد ساختاری تولید می‌کنند (طبق بخش ۸ سند).
"""

from .swings import SwingPoint, detect_swings, swings_as_arrays, DEFAULT_SWING_CONFIG
from .structure import StructureEvent, detect_structure_events, trend_state_from_swings
from .mtf_alignment import AlignedContext, align_timeframes

__all__ = [
    "SwingPoint", "detect_swings", "swings_as_arrays", "DEFAULT_SWING_CONFIG",
    "StructureEvent", "detect_structure_events", "trend_state_from_swings",
    "AlignedContext", "align_timeframes",
]
