# -*- coding: utf-8 -*-
"""
signal_engine.key_level_setup
================================
پیاده‌سازی کامل سند «Key-Level Setup Detection Engine»:
    - compute_key_levels     → ۱۲ سطح مرجع (P4H/P4L/P4EQ, PDH/PDL/PDEQ, PWH/PWL/PWEQ, PMH/PML/PMEQ)
    - get_reference_levels / min_klines_for_levels → سازگار با bot.py قدیمی (بیت‌به‌بیت تست‌شده)
    - detect_interactions    → پنجره‌ی برخورد با هر سطح (تلورانس ATR-normalized)
    - classify_setup / classify_all → درخت تصمیم BOF/TST/BPB/BP/CPB

هیچ‌کدام سفارش نمی‌گذارند یا حد سود/ضرر تعیین می‌کنند (طبق بخش ۱ سند).
"""

from .levels import (
    LevelSet, LevelInfo, compute_key_levels,
    get_reference_levels, min_klines_for_levels,
    compute_prev_1h_levels, compute_prev_4h_levels,
    compute_prev_day_levels, compute_prev_week_levels, compute_prev_month_levels,
)
from .interactions import InteractionWindow, detect_interactions, LEVEL_TIER
from .confluence import ConfluenceZone, detect_level_confluence, DEFAULT_CONFLUENCE_CONFIG
from .setups import SetupEvent, classify_setup, classify_all, DEFAULT_SETUP_CONFIG

__all__ = [
    "LevelSet", "LevelInfo", "compute_key_levels",
    "get_reference_levels", "min_klines_for_levels",
    "compute_prev_1h_levels", "compute_prev_4h_levels",
    "compute_prev_day_levels", "compute_prev_week_levels", "compute_prev_month_levels",
    "InteractionWindow", "detect_interactions", "LEVEL_TIER",
    "ConfluenceZone", "detect_level_confluence", "DEFAULT_CONFLUENCE_CONFIG",
    "SetupEvent", "classify_setup", "classify_all", "DEFAULT_SETUP_CONFIG",
]
