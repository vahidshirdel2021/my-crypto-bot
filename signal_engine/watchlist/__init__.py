# -*- coding: utf-8 -*-
"""
signal_engine.watchlist
=========================
پیاده‌سازی کامل سند «Adaptive Crypto Watchlist v2» — سیستم مدیریت توجه
تحلیلی، بالادست ۵ موتور و USCL. این زیرسیستم هرگز TradeSignal تولید
نمی‌کند؛ فقط تعیین می‌کند کجا و چقدر عمیق نگاه کنیم.

نقطه‌ی ورود اصلی: AdaptiveWatchlist (در watchlist.py).
"""

from .models import (
    WatchlistState, OpportunityComponents, AttentionComponents,
    PromotionInfo, WatchlistEntry, WatchlistEvent, WatchlistEventType, MarketSnapshot,
)
from .hard_filters import apply_hard_filters, DEFAULT_HARD_FILTER_CONFIG
from .opportunity_score import compute_opportunity_score, DEFAULT_OPPORTUNITY_CONFIG
from .attention_priority import compute_attention_priority, DEFAULT_ATTENTION_CONFIG
from .event_promotion import classify_promotion_trigger, DEFAULT_EVENT_PROMOTION_CONFIG
from .state_machine import DEFAULT_STATE_CONFIG
from .scheduler import build_schedule, ScheduledTask, frequency_for_attention, DEFAULT_SCHEDULER_CONFIG
from .lmp import detect_pulse, detect_pulses_for_universe, minutes_to_bars, LMPTrigger, DEFAULT_LMP_CONFIG
from .watchlist import AdaptiveWatchlist, DEFAULT_WATCHLIST_CONFIG

__all__ = [
    "WatchlistState", "OpportunityComponents", "AttentionComponents",
    "PromotionInfo", "WatchlistEntry", "WatchlistEvent", "WatchlistEventType", "MarketSnapshot",
    "apply_hard_filters", "DEFAULT_HARD_FILTER_CONFIG",
    "compute_opportunity_score", "DEFAULT_OPPORTUNITY_CONFIG",
    "compute_attention_priority", "DEFAULT_ATTENTION_CONFIG",
    "classify_promotion_trigger", "DEFAULT_EVENT_PROMOTION_CONFIG",
    "DEFAULT_STATE_CONFIG",
    "build_schedule", "ScheduledTask", "frequency_for_attention", "DEFAULT_SCHEDULER_CONFIG",
    "detect_pulse", "detect_pulses_for_universe", "minutes_to_bars", "LMPTrigger", "DEFAULT_LMP_CONFIG",
    "AdaptiveWatchlist", "DEFAULT_WATCHLIST_CONFIG",
]
