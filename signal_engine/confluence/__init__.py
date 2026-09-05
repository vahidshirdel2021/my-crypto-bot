# -*- coding: utf-8 -*-
"""
signal_engine.confluence
===========================
پیاده‌سازی سند «Unified Signal & Setup Confluence Layer» — نقطه‌ی
اتصال نهایی ۵ موتور مستقل پروژه به یک TradeSignal واحد.

نقطه‌ی ورود اصلی: generate_trade_signals(df, timeframe, symbol, config)
"""

from .adapters import EventEnvelope
from .correlation import ConfluenceContext, build_confluence_contexts
from .scoring import ScoredContext, score_context, score_all
from .selector import TradeSignal, select_signals
from .invalidation import SignalInvalidatedEvent, check_structural_invalidation, is_invalidation_candidate
from .layer import generate_trade_signals

__all__ = [
    "EventEnvelope",
    "ConfluenceContext", "build_confluence_contexts",
    "ScoredContext", "score_context", "score_all",
    "TradeSignal", "select_signals",
    "SignalInvalidatedEvent", "check_structural_invalidation", "is_invalidation_candidate",
    "generate_trade_signals",
]
