# -*- coding: utf-8 -*-
"""
signal_engine.pattern_recognition
====================================
پیاده‌سازی سند «Pattern Recognition Engine» — الگوهای کلاسیک نموداری.
نقطه‌ی ورود اصلی: detect_all(df, timeframe, symbol, config) -> List[PatternEvent]
هارامی از signal_engine.candlestick وارد می‌شود (بدون تکرار پیاده‌سازی).
"""

from .detectors import (
    PatternEvent,
    detect_flag_pennant,
    detect_ascending_triangle,
    detect_descending_triangle,
    detect_cup_and_handle,
    detect_inverted_cup_and_handle,
    detect_three_rising_valleys,
    detect_three_declining_peaks,
    detect_harami_via_candlestick_engine,
    detect_all,
    DEFAULT_CONFIG,
)

__all__ = [
    "PatternEvent",
    "detect_flag_pennant", "detect_ascending_triangle", "detect_descending_triangle",
    "detect_cup_and_handle", "detect_inverted_cup_and_handle",
    "detect_three_rising_valleys", "detect_three_declining_peaks",
    "detect_harami_via_candlestick_engine", "detect_all", "DEFAULT_CONFIG",
]
