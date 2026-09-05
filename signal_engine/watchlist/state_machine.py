# -*- coding: utf-8 -*-
"""
signal_engine.watchlist.state_machine
========================================
پیاده‌سازی بخش‌های ۵، ۱۴، ۱۵، ۲۲-۲۳ سند: ماشین‌حالت صریح و قطعی
(deterministic) با ۵ حالت، هیسترزیس مجزا برای ترفیع/تنزل، TTL برای
Event/Hot، و محافظت CORE در برابر تنزل معمولی.

طبق بخش ۲۳ سند: با ورودی یکسان، همیشه باید خروجی یکسان تولید شود —
هیچ رفتار وابسته به زمان واقعی سیستم (wall-clock) یا ترتیب غیرقطعی در
این ماژول وجود ندارد؛ همه‌چیز بر اساس `time_index` (ایندکس کندل/تیک)
که از بیرون داده می‌شود کار می‌کند.
"""

from __future__ import annotations

from typing import List, Optional

from signal_engine.watchlist.models import WatchlistEntry, WatchlistEvent, WatchlistState, PromotionInfo

DEFAULT_STATE_CONFIG = {
    "active": {"promote_threshold": 0.72, "demote_threshold": 0.58},
    "emerging": {"promote_threshold": 0.72, "demote_threshold": 0.40},
    "core_symbols": [],  # لیست صریح نمادهایی که همیشه CORE هستند (مثلاً BTC/ETH)
}


def is_core(symbol: str, config: dict) -> bool:
    return symbol in (config.get("core_symbols") or [])


def _emit(events: List[WatchlistEvent], event_type, entry: WatchlistEntry, previous_state, reason, trigger_event_id, time_index, expires_at=None):
    events.append(WatchlistEvent(
        event_type=event_type, symbol=entry.symbol, previous_state=previous_state, new_state=entry.state,
        opportunity_score=entry.opportunity_score, attention_priority=entry.attention_priority,
        reason=reason, trigger_event_id=trigger_event_id, created_at=time_index, expires_at=expires_at,
    ))


def evaluate_ordinary_transition(
    entry: WatchlistEntry,
    time_index: int,
    config: Optional[dict] = None,
) -> List[WatchlistEvent]:
    """طبق بخش ۵ و ۱۵ سند: گذارهای معمولی (نه رویدادمحور) بین
    CORE/ACTIVE/EMERGING/DORMANT، با هیسترزیس مجزا برای ترفیع/تنزل تا از
    نوسان مداوم (churn) جلوگیری شود. CORE هرگز با این مسیر تنزل نمی‌کند
    (فقط فیلترهای سخت/کیفیت داده می‌توانند CORE را غیرفعال کنند — بخش
    ۴.۱ سند، خارج از دامنه‌ی این تابع).

    فقط زمانی فراخوانی شود که نماد در EVENT_HOT نباشد (آن حالت چرخه‌ی
    عمر جدای خودش را در expire_event_hot دارد).
    """
    cfg = {**DEFAULT_STATE_CONFIG, **(config or {})}
    events: List[WatchlistEvent] = []

    if entry.state == "CORE":
        return events  # طبق سند بخش ۴.۱: محافظت‌شده از تنزل معمولی

    if entry.state == "EVENT_HOT":
        return events  # چرخه‌ی عمر مجزا

    score = entry.opportunity_score
    prev = entry.state

    if entry.state in ("ACTIVE",):
        if score < cfg["active"]["demote_threshold"]:
            entry.state = "EMERGING"
    elif entry.state in ("EMERGING",):
        if score >= cfg["emerging"]["promote_threshold"]:
            entry.state = "ACTIVE"
        elif score < cfg["emerging"]["demote_threshold"]:
            entry.state = "DORMANT"
    elif entry.state in ("DORMANT",):
        if score >= cfg["emerging"]["promote_threshold"]:
            entry.state = "ACTIVE"
        elif score >= cfg["active"]["demote_threshold"]:
            # طبق سند بخش ۴.۳: Emerging جلوی این را می‌گیرد که فرصت‌ها فقط
            # وقتی کاملاً آشکار شدند کشف شوند — یک نماد Dormant با امتیاز
            # رو به بهبود مستقیم به Emerging می‌رود، نه مستقیم Active.
            entry.state = "EMERGING"

    if entry.state != prev:
        _emit(events, "watchlist_state_changed", entry, prev, "opportunity_score_threshold", None, time_index)
        event_type = "watchlist_promoted" if _rank(entry.state) > _rank(prev) else "watchlist_demoted"
        _emit(events, event_type, entry, prev, "opportunity_score_threshold", None, time_index)

    return events


_STATE_RANK = {"DORMANT": 0, "EMERGING": 1, "ACTIVE": 2, "EVENT_HOT": 3, "CORE": 4, "DATA_DEGRADED": -1}


def _rank(state: WatchlistState) -> int:
    return _STATE_RANK.get(state, 0)


def promote_to_event_hot(
    entry: WatchlistEntry,
    trigger_reason: str,
    trigger_event_id: Optional[str],
    time_index: int,
    ttl_bars: int,
) -> List[WatchlistEvent]:
    """طبق بخش ۴.۴ و ۱۴ سند: ترفیع موقت — حتی از DORMANT هم می‌تواند رخ
    دهد. CORE نیازی به ترفیع ندارد (از قبل بالاترین اولویت پایه را دارد)
    ولی این تابع همچنان اجازه می‌دهد یک رویداد صریح رخ دهد تا التهاب
    واقعی همیشه در attention_priority منعکس شود.
    """
    events: List[WatchlistEvent] = []
    previous_state = entry.state
    # طبق سند: هر ترفیع جدید TTL را تازه می‌کند (رویداد تازه‌تر، مهلت تازه‌تر).
    entry.state = "EVENT_HOT" if entry.state != "CORE" else "CORE"
    entry.promotion = PromotionInfo(
        reason=trigger_reason, trigger_event_id=trigger_event_id,
        promoted_at=time_index, expires_at=time_index + ttl_bars,
    )
    entry.last_event_at = time_index
    _emit(events, "watchlist_event_promoted", entry, previous_state, trigger_reason, trigger_event_id, time_index,
          expires_at=entry.promotion.expires_at)
    return events


def expire_event_hot_if_needed(
    entry: WatchlistEntry,
    time_index: int,
    config: Optional[dict] = None,
) -> List[WatchlistEvent]:
    """طبق بخش ۱۴ سند: در انقضا، Opportunity/Attention دوباره محاسبه
    می‌شوند (این تابع خودش امتیاز را دوباره حساب نمی‌کند — کالر باید
    entry.opportunity_score را از قبل با مقدار تازه به‌روزرسانی کرده
    باشد) و نماد به ACTIVE/EMERGING/DORMANT مناسب برمی‌گردد — هرگز
    برای همیشه در Event/Hot باقی نمی‌ماند (آنتی‌پترن ۶ سند).
    """
    cfg = {**DEFAULT_STATE_CONFIG, **(config or {})}
    events: List[WatchlistEvent] = []
    if entry.state != "EVENT_HOT":
        return events
    if entry.promotion.expires_at is None or time_index < entry.promotion.expires_at:
        return events

    previous_state = entry.state
    score = entry.opportunity_score
    if score >= cfg["active"]["promote_threshold"]:
        entry.state = "ACTIVE"
    elif score >= cfg["emerging"]["demote_threshold"]:
        entry.state = "EMERGING"
    else:
        entry.state = "DORMANT"
    entry.promotion = PromotionInfo()  # پاک‌سازی — دیگر Event/Hot فعالی وجود ندارد

    _emit(events, "watchlist_event_expired", entry, previous_state, "ttl_expired", None, time_index)
    return events


def deterministic_sort_key(entry: WatchlistEntry, tie_break_time_index: int = 0):
    """طبق بخش ۲۳ سند: ترتیب رتبه‌بندی/تای‌بریک قطعی — هرگز تصادفی.
    اولویت: Attention Priority، سپس Opportunity Score، سپس زمان رویداد،
    سپس شناسه‌ی پایدار نماد (الفبایی).
    """
    return (-entry.attention_priority, -entry.opportunity_score, tie_break_time_index, entry.symbol)


def sort_entries_deterministically(entries: List[WatchlistEntry]) -> List[WatchlistEntry]:
    return sorted(entries, key=lambda e: deterministic_sort_key(e, e.updated_at or 0))
