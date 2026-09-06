# -*- coding: utf-8 -*-
"""
signal_engine.confluence.correlation
=======================================
پیاده‌سازی بخش ۴ سند: گروه‌بندی EventEnvelope ها به «زمینه‌ی هم‌گرایی»
(Confluence Context) بر اساس هم‌نمادی و مجاورت زمانی (بر حسب ایندکس
کندل تایم‌فریم اجرا)، و انتخاب anchor طبق اولویت صریح سند بخش ۴.۲.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from signal_engine.confluence.adapters import EventEnvelope

# اولویت anchor طبق سند، بخش ۴.۲ — اولین منبع موجود در این ترتیب anchor می‌شود.
_ANCHOR_PRIORITY = [
    ("KLSDE", None),  # هر SetupEvent از KLSDE
    ("SDE", "BOS"),
    ("SDE", "CHoCH"),
    ("CPDE", None),  # کندل استیکِ confirmed در ادامه فیلتر می‌شود
    ("PRE", None),
    ("MCDE", "micro_breakout"),
]


@dataclass
class ConfluenceContext:
    context_id: str
    symbol: str
    anchor: EventEnvelope
    supporting_events: List[EventEnvelope] = field(default_factory=list)
    window_start_index: int = 0
    window_end_index: int = 0


def _is_anchor_candidate(env: EventEnvelope) -> bool:
    if env.source_engine == "KLSDE":
        return True
    if env.source_engine == "SDE" and env.native_event_type in ("BOS", "CHoCH"):
        return True
    if env.source_engine == "CPDE":
        payload = env.native_payload
        return getattr(payload, "confirmation_status", "unconfirmed") in ("confirmed", "not_applicable")
    if env.source_engine == "PRE":
        payload = env.native_payload
        return getattr(payload, "confirmation_status", "unconfirmed") == "confirmed"
    if env.source_engine == "MCDE" and env.native_event_type == "micro_breakout":
        return True
    return False


def _anchor_priority_rank(env: EventEnvelope) -> int:
    if env.source_engine == "KLSDE":
        return 0
    if env.source_engine == "SDE" and env.native_event_type == "BOS":
        return 1
    if env.source_engine == "SDE" and env.native_event_type == "CHoCH":
        return 2
    if env.source_engine == "CPDE":
        return 3
    if env.source_engine == "PRE":
        return 4
    if env.source_engine == "MCDE":
        return 5
    return 99


def build_confluence_contexts(
    all_events: List[EventEnvelope],
    correlation_window_max_bars: int = 20,
) -> List[ConfluenceContext]:
    """طبق سند، بخش ۴.۱ و ۴.۲: برای هر نماد جدا عمل می‌کند؛ هر anchor
    (به ترتیب زمانی ظهور) یک context جدید باز می‌کند و همه‌ی رویدادهای
    هر دو موتور (هر تایم‌فریم) که در بازه‌ی زمانی مجاورت (بر حسب ایندکس
    کندل) قرار دارند، supporting می‌شوند.
    """
    by_symbol: dict = {}
    for env in all_events:
        by_symbol.setdefault(env.symbol, []).append(env)

    contexts: List[ConfluenceContext] = []
    counter = 0

    for symbol, events in by_symbol.items():
        events_sorted = sorted(events, key=lambda e: e.event_index)
        anchor_candidates = sorted(
            [e for e in events_sorted if _is_anchor_candidate(e)],
            key=lambda e: (e.event_index, _anchor_priority_rank(e)),
        )
        used_as_supporting = set()

        for anchor in anchor_candidates:
            if anchor.envelope_id in used_as_supporting:
                continue
            window_start = anchor.event_index - correlation_window_max_bars
            window_end = anchor.event_index + correlation_window_max_bars
            supporting = [
                e for e in events_sorted
                if e.envelope_id != anchor.envelope_id
                and window_start <= e.event_index <= window_end
            ]
            counter += 1
            contexts.append(ConfluenceContext(
                context_id=f"ctx_{counter:06d}", symbol=symbol, anchor=anchor,
                supporting_events=supporting, window_start_index=window_start, window_end_index=window_end,
            ))
            for s in supporting:
                if s.source_engine != "MCDE":  # فازهای کلان/ریز هرگز anchor یک context دیگر نمی‌شوند، پس نیازی به مصرف‌شدن ندارند
                    used_as_supporting.add(s.envelope_id)

    return contexts
