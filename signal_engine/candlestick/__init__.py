# -*- coding: utf-8 -*-
"""
signal_engine.candlestick
============================
پیاده‌سازی کامل سند «Candlestick Pattern Detection Engine».
نقطه‌ی ورود اصلی: detect_all(df, timeframe, symbol, config) -> List[CandlestickPatternEvent]
"""

from .detectors import (
    CandlestickPatternEvent,
    detect_hammer_family,
    detect_doji_family,
    detect_harami,
    detect_dark_cloud_cover,
    detect_three_soldiers_crows,
    detect_three_methods,
    detect_engulfing,
    detect_marubozu,
    detect_piercing_line,
    detect_morning_star,
    detect_evening_star,
    detect_all,
    DEFAULT_CONFIG,
)

__all__ = [
    "CandlestickPatternEvent",
    "detect_hammer_family", "detect_doji_family", "detect_harami",
    "detect_dark_cloud_cover", "detect_three_soldiers_crows", "detect_three_methods",
    "detect_engulfing", "detect_marubozu", "detect_piercing_line",
    "detect_morning_star", "detect_evening_star",
    "detect_all", "DEFAULT_CONFIG",
]
