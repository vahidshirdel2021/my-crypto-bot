# -*- coding: utf-8 -*-
"""
signal_engine.common
======================
ابزارهای مشترک بین همه‌ی موتورهای signal_engine: ATR، سرویس تشخیص روند،
و هندسه‌ی کندل. هر موتور دیگر در این پروژه باید این‌ها را از اینجا
ایمپورت کند، نه اینکه دوباره پیاده‌سازی کند (طبق تأکید صریح تمام ۶ سند
طراحی این پروژه).
"""

from .atr import compute_atr, latest_atr, true_range, min_bars_for_atr
from .trend_context import (
    TrendContext,
    trend_from_swings,
    trend_from_ema_slope,
    combined_trend_context,
)
from .candle_geometry import CandleGeometry, compute_candle_geometry, compute_candle_geometry_batch

__all__ = [
    "compute_atr", "latest_atr", "true_range", "min_bars_for_atr",
    "TrendContext", "trend_from_swings", "trend_from_ema_slope", "combined_trend_context",
    "CandleGeometry", "compute_candle_geometry", "compute_candle_geometry_batch",
]
