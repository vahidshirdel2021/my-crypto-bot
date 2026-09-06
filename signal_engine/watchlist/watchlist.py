# -*- coding: utf-8 -*-
"""
signal_engine.watchlist.watchlist
====================================
نقطه‌ی ورود اصلی «Adaptive Crypto Watchlist» — طبق سند
adaptive_crypto_watchlist_v2.md. این کلاس تمام زیرسیستم‌ها (فیلتر سخت،
امتیاز فرصت، اولویت توجه، ماشین‌حالت، ترفیع رویدادمحور، زمان‌بند) را به
هم وصل می‌کند.

مرزهای حیاتی (بخش ۳۱ سند) — این کلاس هرگز:
    - سفارش نمی‌گذارد یا تغییر نمی‌دهد
    - حجم پوزیشن تعیین نمی‌کند
    - موجودی/ریسک حساب را نمی‌داند
    - TradeSignal تولید نمی‌کند
    - امتیاز USCL را override نمی‌کند
    - منطق داخلی ۵ موتور را تغییر نمی‌دهد یا بازپیاده‌سازی نمی‌کند
"""

from __future__ import annotations

from typing import Dict, List, Optional

from signal_engine.watchlist.models import MarketSnapshot, WatchlistEntry, WatchlistEvent
from signal_engine.watchlist.hard_filters import apply_hard_filters, DEFAULT_HARD_FILTER_CONFIG
from signal_engine.watchlist.opportunity_score import compute_opportunity_score, DEFAULT_OPPORTUNITY_CONFIG
from signal_engine.watchlist.attention_priority import (
    compute_attention_priority, compute_transition_urgency, DEFAULT_ATTENTION_CONFIG,
)
from signal_engine.watchlist.event_promotion import (
    classify_promotion_trigger, urgency_for_trigger, check_market_data_triggers,
    DEFAULT_EVENT_PROMOTION_CONFIG,
)
from signal_engine.watchlist.state_machine import (
    evaluate_ordinary_transition, promote_to_event_hot, expire_event_hot_if_needed,
    is_core, sort_entries_deterministically, DEFAULT_STATE_CONFIG,
)
from signal_engine.watchlist.scheduler import build_schedule, ScheduledTask, DEFAULT_SCHEDULER_CONFIG
from signal_engine.watchlist.lmp import detect_pulse, minutes_to_bars, LMPTrigger, DEFAULT_LMP_CONFIG


DEFAULT_WATCHLIST_CONFIG = {
    "hard_filters": DEFAULT_HARD_FILTER_CONFIG,
    "opportunity": DEFAULT_OPPORTUNITY_CONFIG,
    "attention": DEFAULT_ATTENTION_CONFIG,
    "event_promotion": DEFAULT_EVENT_PROMOTION_CONFIG,
    "states": DEFAULT_STATE_CONFIG,
    "scheduler": DEFAULT_SCHEDULER_CONFIG,
    "lmp": DEFAULT_LMP_CONFIG,
}


class AdaptiveWatchlist:
    """طبق بخش ۲۱ سند: محاسبه‌ی افزایشی — این کلاس state کامل هر نماد را
    نگه می‌دارد تا هر تیک فقط یک به‌روزرسانی افزایشی باشد، نه بازتحلیل
    کامل تاریخچه.

    طبق بخش ۲۲: تمام متدها فقط بر اساس `time_index` (نه wall-clock) کار
    می‌کنند، برای بازپخش قطعی و بدون look-ahead.
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = {**DEFAULT_WATCHLIST_CONFIG, **(config or {})}
        self._entries: Dict[str, WatchlistEntry] = {}

    # ------------------------------------------------------------------
    # دسترسی به state
    # ------------------------------------------------------------------

    def get_entry(self, symbol: str) -> Optional[WatchlistEntry]:
        return self._entries.get(symbol)

    def all_entries(self) -> List[WatchlistEntry]:
        return list(self._entries.values())

    def mark_core(self, symbols: List[str]) -> None:
        """طبق بخش ۴.۱ سند: تعیین صریح نمادهای همیشه-CORE (مثلاً BTC/ETH)."""
        core_list = set(self.config["states"].get("core_symbols") or [])
        core_list.update(symbols)
        self.config["states"]["core_symbols"] = list(core_list)
        for s in symbols:
            entry = self._entries.setdefault(s, WatchlistEntry(symbol=s))
            entry.state = "CORE"

    def _get_or_create(self, symbol: str) -> WatchlistEntry:
        if symbol not in self._entries:
            self._entries[symbol] = WatchlistEntry(symbol=symbol, state="DORMANT")
        return self._entries[symbol]

    # ------------------------------------------------------------------
    # به‌روزرسانی دوره‌ای (Periodic Refresh — بخش ۲۰.۱ سند)
    # ------------------------------------------------------------------

    def update_symbol(self, snapshot: MarketSnapshot) -> List[WatchlistEvent]:
        """طبق بخش ۷-۱۰، ۱۱، ۱۵ سند: فیلتر سخت -> امتیاز فرصت -> اولویت
        توجه -> گذار حالت معمولی (با هیسترزیس). فقط با اطلاعات موجود تا
        همین `snapshot.time_index` کار می‌کند (بدون look-ahead).
        """
        events: List[WatchlistEvent] = []
        entry = self._get_or_create(snapshot.symbol)
        is_new = entry.updated_at is None

        passed, failures = apply_hard_filters(snapshot, self.config["hard_filters"])
        entry.hard_filter_failures = failures
        entry.data_freshness_ok = snapshot.data_valid

        if not passed and entry.state != "CORE":
            previous = entry.state
            if entry.state != "DATA_DEGRADED":
                entry.state = "DATA_DEGRADED"
                events.append(WatchlistEvent(
                    event_type="watchlist_state_changed", symbol=entry.symbol,
                    previous_state=previous, new_state="DATA_DEGRADED",
                    opportunity_score=entry.opportunity_score, attention_priority=entry.attention_priority,
                    reason=f"hard_filter_failed:{failures}", trigger_event_id=None, created_at=snapshot.time_index,
                ))
            entry.updated_at = snapshot.time_index
            return events

        score, components = compute_opportunity_score(snapshot, self.config["opportunity"])
        entry.opportunity_score = score
        entry.scores = components

        # اگر تا الان DATA_DEGRADED بود و حالا فیلتر سخت رد شد، به Dormant برگرد
        # تا دوباره وارد چرخه‌ی عادی ارزیابی شود (طبق بخش ۲۸ سند: recovery یا Dormant).
        if entry.state == "DATA_DEGRADED":
            entry.state = "DORMANT"

        if is_core(snapshot.symbol, self.config["states"]) and entry.state != "CORE":
            entry.state = "CORE"
        if entry.state == "CORE" and not is_core(snapshot.symbol, self.config["states"]):
            # اگر صریحاً از core_symbols حذف شده، اجازه بده دوباره طبق امتیاز رتبه‌بندی شود.
            entry.state = "ACTIVE" if score >= self.config["states"]["active"]["promote_threshold"] else "EMERGING"

        # نکته‌ی حیاتی ترتیب: ابتدا هر Event/Hot منقضی‌شده و سپس گذار
        # معمولی حل می‌شوند تا attention_priority زیر بر اساس state
        # *به‌روز* محاسبه شود، نه state قدیمی (مثلاً EVENT_HOT که تازه
        # منقضی شده ولی هنوز جایگزین نشده).
        state_before_transitions = entry.state
        transition_events: List[WatchlistEvent] = []
        transition_events += expire_event_hot_if_needed(entry, snapshot.time_index, self.config["states"])
        transition_events += evaluate_ordinary_transition(entry, snapshot.time_index, self.config["states"])

        bars_since = None if entry.last_deep_analysis_at is None else (snapshot.time_index - entry.last_deep_analysis_at)
        transition_urgency = compute_transition_urgency(entry.last_known_htf_trend, snapshot.htf_trend)
        entry.last_known_htf_trend = snapshot.htf_trend or entry.last_known_htf_trend

        attention, attn_components = compute_attention_priority(
            state=entry.state, opportunity_score=score, event_urgency=0.0,
            transition_urgency=transition_urgency, bars_since_last_deep_analysis=bars_since,
            config=self.config["attention"],
        )
        entry.attention_priority = attention
        entry.attention = attn_components
        entry.updated_at = snapshot.time_index

        if is_new:
            events.append(WatchlistEvent(
                event_type="watchlist_added", symbol=entry.symbol, previous_state=None, new_state=entry.state,
                opportunity_score=score, attention_priority=attention, reason="initial_scan",
                trigger_event_id=None, created_at=snapshot.time_index,
            ))

        events.append(WatchlistEvent(
            event_type="watchlist_score_updated", symbol=entry.symbol, previous_state=state_before_transitions, new_state=entry.state,
            opportunity_score=score, attention_priority=attention, reason=None, trigger_event_id=None,
            created_at=snapshot.time_index,
        ))
        events += transition_events

        return events

    # ------------------------------------------------------------------
    # ترفیع رویدادمحور (Event-Driven Refresh — بخش ۲۰.۲، ۱۳ سند)
    # ------------------------------------------------------------------

    def handle_market_pulse(
        self,
        symbol: str,
        trigger: LMPTrigger,
        time_index: int,
        timeframe_minutes: float = 5.0,
    ) -> List[WatchlistEvent]:
        """طبق بخش ۱ سند اصلاحی (LMP): راه‌حل حلقه‌ی وابستگی دوری —
        حتی نمادی که هرگز توسط ۵ موتور سنگین بررسی نشده (چون Dormant
        بوده و موتورها رویش اجرا نمی‌شدند)، می‌تواند از همین مسیر
        *ارزان* به EVENT_HOT با یک TTL سریع (پیش‌فرض ۱۰ دقیقه) ترفیع
        بگیرد — این خودش بودجه‌ی محاسباتی برای اجرای واقعی ۵ موتور را
        باز می‌کند (طبق زمان‌بند/get_schedule). اگر طی این TTL سریع
        هیچ موتوری ساختار واقعی تأیید نکرد (یعنی هیچ handle_engine_event
        دیگری این نماد را دوباره ترفیع نکرد)، همان چرخه‌ی معمول انقضای
        Event/Hot (expire_event_hot_if_needed) آن را خودکار به
        Dormant/Emerging برمی‌گرداند — دقیقاً طبق بخش ۱.۲.۳ سند اصلاحی.
        """
        entry = self._get_or_create(symbol)
        if entry.state == "CORE":
            entry.last_event_at = time_index
            return []

        lmp_cfg = self.config.get("lmp", {})
        fast_ttl_bars = minutes_to_bars(lmp_cfg.get("fast_ttl_minutes", 10), timeframe_minutes)
        trigger_name = f"lmp_{trigger.trigger_type}"
        urgency = self.config["event_promotion"]["urgency_by_trigger"].get(trigger_name, 0.5)

        from signal_engine.watchlist.state_machine import promote_to_event_hot
        events = promote_to_event_hot(entry, trigger_name, None, time_index, fast_ttl_bars)
        attention, attn_components = compute_attention_priority(
            state=entry.state, opportunity_score=entry.opportunity_score, event_urgency=urgency,
            transition_urgency=0.0, bars_since_last_deep_analysis=0, config=self.config["attention"],
        )
        entry.attention_priority = attention
        entry.attention = attn_components
        events.append(WatchlistEvent(
            event_type="watchlist_market_pulse_triggered", symbol=symbol, previous_state=entry.state,
            new_state=entry.state, opportunity_score=entry.opportunity_score, attention_priority=attention,
            reason=trigger_name, trigger_event_id=None, created_at=time_index,
            expires_at=time_index + fast_ttl_bars,
        ))
        return events

    def scan_for_market_pulses(
        self,
        snapshots: Dict[str, "object"],
        key_levels_by_symbol: Optional[dict] = None,
        time_index: int = 0,
        timeframe_minutes: float = 5.0,
    ) -> List[WatchlistEvent]:
        """طبق بخش ۱.۲.۱ سند اصلاحی: نقطه‌ی ورود توصیه‌شده برای اجرای
        LMP روی *کل* دامنه (از جمله نمادهای Dormant) در هر چرخه — قبل
        از هر تصمیم به اجرای ۵ موتور سنگین.
        """
        all_events: List[WatchlistEvent] = []
        for symbol, df in snapshots.items():
            trig = detect_pulse(df, symbol, (key_levels_by_symbol or {}).get(symbol), self.config.get("lmp"))
            if trig is not None:
                all_events += self.handle_market_pulse(symbol, trig, time_index, timeframe_minutes)
        return all_events

    def handle_engine_event(
        self,
        symbol: str,
        source_engine: str,
        native_event_type: str,
        trigger_event_id: Optional[str],
        time_index: int,
    ) -> List[WatchlistEvent]:
        """طبق بخش ۱۳ سند: یک EventEnvelope از هر کدام از ۵ موتور
        (source_engine/native_event_type دقیقاً همان مقادیری هستند که
        signal_engine.confluence.adapters تولید می‌کند — این‌جا فقط
        classify می‌شوند، نه بازتولید).
        """
        trigger = classify_promotion_trigger(source_engine, native_event_type, self.config["event_promotion"])
        if trigger is None:
            return []
        entry = self._get_or_create(symbol)
        if entry.state == "CORE":
            # CORE از قبل بالاترین اولویت پایه را دارد؛ فقط رویداد را برای
            # قابلیت رهگیری (auditability) ثبت می‌کنیم، بدون تغییر state.
            entry.last_event_at = time_index
            return []
        urgency = urgency_for_trigger(trigger, self.config["event_promotion"])
        ttl_bars = self.config["event_promotion"]["ttl_bars"]
        events = promote_to_event_hot(entry, trigger, trigger_event_id, time_index, ttl_bars)
        attention, attn_components = compute_attention_priority(
            state=entry.state, opportunity_score=entry.opportunity_score, event_urgency=urgency,
            transition_urgency=0.0, bars_since_last_deep_analysis=0, config=self.config["attention"],
        )
        entry.attention_priority = attention
        entry.attention = attn_components
        events.append(WatchlistEvent(
            event_type="attention_priority_updated", symbol=symbol, previous_state=entry.state, new_state=entry.state,
            opportunity_score=entry.opportunity_score, attention_priority=attention, reason=trigger,
            trigger_event_id=trigger_event_id, created_at=time_index,
        ))
        return events

    def handle_market_data_trigger(
        self, symbol: str, volume_acceleration: Optional[float],
        atr_pct: Optional[float], baseline_atr_pct: Optional[float], time_index: int,
    ) -> List[WatchlistEvent]:
        """طبق بخش ۱۳: triggerهای مبتنی بر داده‌ی خام بازار (نه رویداد
        یک موتور تحلیلی) — فعالیت غیرعادی، انبساط نوسان.
        """
        trigger = check_market_data_triggers(volume_acceleration, atr_pct, baseline_atr_pct, self.config["event_promotion"])
        if trigger is None:
            return []
        return self.handle_engine_event(symbol, source_engine="market_data", native_event_type=trigger,
                                         trigger_event_id=None, time_index=time_index)

    def mark_deep_analysis_done(self, symbol: str, time_index: int) -> None:
        """کالر (لایه‌ی بالادستی که واقعاً ۵ موتور را اجرا می‌کند) بعد از
        هر تحلیل عمیق واقعی این را صدا می‌زند تا freshness/coverage
        urgency درست محاسبه شود.
        """
        entry = self._get_or_create(symbol)
        entry.last_deep_analysis_at = time_index

    # ------------------------------------------------------------------
    # زمان‌بند (بخش ۱۶-۱۷ سند)
    # ------------------------------------------------------------------

    def get_schedule(self) -> List[ScheduledTask]:
        return build_schedule(self.all_entries(), self.config["scheduler"])

    def get_ranked_symbols(self) -> List[str]:
        """طبق بخش ۲۳ سند: ترتیب قطعی (نه تصادفی) برای هر مصرف‌کننده‌ای
        که فقط لیست رتبه‌بندی‌شده‌ی نمادها را می‌خواهد.
        """
        return [e.symbol for e in sort_entries_deterministically(self.all_entries())]
