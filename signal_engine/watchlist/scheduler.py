# -*- coding: utf-8 -*-
"""
signal_engine.watchlist.scheduler
====================================
پیاده‌سازی بخش‌های ۱۶، ۱۷، ۲۹ سند: زمان‌بند اولویت. این ماژول فقط تعیین
می‌کند «چقدر عمیق تحلیل کنیم»، هرگز «آیا معامله کنیم» (مرز حیاتی سند،
بخش ۱۷، آخر).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal

from signal_engine.watchlist.models import WatchlistEntry
from signal_engine.watchlist.state_machine import sort_entries_deterministically

AnalysisFrequency = Literal["immediate_deep", "high_frequency", "normal", "reduced", "minimal"]

DEFAULT_SCHEDULER_CONFIG = {
    "frequency_bands": [
        (0.95, "immediate_deep"),
        (0.80, "high_frequency"),
        (0.60, "normal"),
        (0.35, "reduced"),
        (0.0, "minimal"),
    ],
    "resource_limits": {
        "max_concurrent_symbol_analysis": 30,
        "max_concurrent_engine_tasks": 150,
    },
    # طبق بخش ۲۹ سند: ترتیب اولویت هنگام اشباع منابع
    "priority_order": ["CORE", "EVENT_HOT", "ACTIVE", "EMERGING", "DORMANT"],
}


@dataclass
class ScheduledTask:
    symbol: str
    state: str
    attention_priority: float
    frequency: AnalysisFrequency
    admitted: bool  # آیا در محدودیت منابع فعلی جا شد یا صف/backpressure خورد


def frequency_for_attention(attention_priority: float, config=None) -> AnalysisFrequency:
    cfg = {**DEFAULT_SCHEDULER_CONFIG, **(config or {})}
    for threshold, label in cfg["frequency_bands"]:
        if attention_priority >= threshold:
            return label
    return "minimal"


def build_schedule(
    entries: List[WatchlistEntry],
    config=None,
) -> List[ScheduledTask]:
    """طبق سند بخش ۲۹: وقتی منابع کافی نیست، اولویت باید حفظ شود:
    Core > Event/Hot > بالاترین Attention در Active > بقیه‌ی Active >
    Emerging > Dormant — و هرگز رویداد پراولویت به‌صورت خاموش drop نشود
    (این‌جا با admitted=False صریحاً علامت می‌خورد، نه حذف بی‌صدا).
    """
    cfg = {**DEFAULT_SCHEDULER_CONFIG, **(config or {})}
    max_concurrent = cfg["resource_limits"]["max_concurrent_symbol_analysis"]
    priority_order = {state: i for i, state in enumerate(cfg["priority_order"])}

    def sort_key(e: WatchlistEntry):
        state_rank = priority_order.get(e.state, len(priority_order))
        base = deterministic_key = None
        # طبق بخش ۲۳: تای‌بریک قطعی بعد از اولویت حالت
        from signal_engine.watchlist.state_machine import deterministic_sort_key
        return (state_rank,) + deterministic_sort_key(e, e.updated_at or 0)

    ordered = sorted(entries, key=sort_key)

    tasks: List[ScheduledTask] = []
    for i, entry in enumerate(ordered):
        admitted = i < max_concurrent
        tasks.append(ScheduledTask(
            symbol=entry.symbol, state=entry.state, attention_priority=entry.attention_priority,
            frequency=frequency_for_attention(entry.attention_priority, cfg),
            admitted=admitted,
        ))
    return tasks
