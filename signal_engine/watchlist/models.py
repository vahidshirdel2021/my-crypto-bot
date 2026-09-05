# -*- coding: utf-8 -*-
"""
signal_engine.watchlist.models
=================================
مدل‌های داده‌ی «Adaptive Crypto Watchlist» طبق سند
adaptive_crypto_watchlist_v2.md. این واچ‌لیست هرگز TradeSignal تولید
نمی‌کند — فقط تعیین می‌کند کجا و چقدر عمیق نگاه کنیم (بخش ۱، «قانون
اصلی» سند).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

WatchlistState = Literal["CORE", "ACTIVE", "EMERGING", "EVENT_HOT", "DORMANT", "DATA_DEGRADED"]


@dataclass
class OpportunityComponents:
    """طبق سند، بخش ۸.۱ — هر جزء در [0,1]."""
    liquidity: float = 0.0
    market_activity: float = 0.0
    higher_tf_structure: float = 0.0
    volatility_suitability: float = 0.0
    key_level_proximity: float = 0.0
    early_setup_evidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "liquidity": self.liquidity, "market_activity": self.market_activity,
            "higher_tf_structure": self.higher_tf_structure,
            "volatility_suitability": self.volatility_suitability,
            "key_level_proximity": self.key_level_proximity,
            "early_setup_evidence": self.early_setup_evidence,
        }


@dataclass
class AttentionComponents:
    """طبق سند، بخش ۱۱."""
    baseline_priority: float = 0.0
    opportunity_component: float = 0.0
    event_urgency: float = 0.0
    transition_urgency: float = 0.0
    freshness_urgency: float = 0.0
    coverage_urgency: float = 0.0

    def to_dict(self) -> dict:
        return {
            "baseline_priority": self.baseline_priority,
            "opportunity_component": self.opportunity_component,
            "event_urgency": self.event_urgency,
            "transition_urgency": self.transition_urgency,
            "freshness_urgency": self.freshness_urgency,
            "coverage_urgency": self.coverage_urgency,
        }


@dataclass
class PromotionInfo:
    """طبق سند، بخش ۱۴ — هر ترفیع Event/Hot باید این ۴ فیلد را داشته باشد."""
    reason: Optional[str] = None
    trigger_event_id: Optional[str] = None
    promoted_at: Optional[int] = None  # ایندکس زمانی (کندل/تیک) برای قطعیت بازپخش
    expires_at: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "reason": self.reason, "trigger_event_id": self.trigger_event_id,
            "promoted_at": self.promoted_at, "expires_at": self.expires_at,
        }


@dataclass
class WatchlistEntry:
    """طبق سند، بخش ۲۵ — مدل داده‌ی داخلی یک نماد در واچ‌لیست."""
    symbol: str
    state: WatchlistState = "DORMANT"
    opportunity_score: float = 0.0
    attention_priority: float = 0.0
    scores: OpportunityComponents = field(default_factory=OpportunityComponents)
    attention: AttentionComponents = field(default_factory=AttentionComponents)
    promotion: PromotionInfo = field(default_factory=PromotionInfo)
    last_deep_analysis_at: Optional[int] = None
    last_event_at: Optional[int] = None
    data_freshness_ok: bool = True
    hard_filter_failures: List[str] = field(default_factory=list)
    updated_at: Optional[int] = None
    # برای تشخیص تغییرات ساختاری اخیر (transition_urgency) بدون تکرار منطق SDE:
    last_known_htf_trend: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol, "state": self.state,
            "opportunity_score": round(self.opportunity_score, 4),
            "attention_priority": round(self.attention_priority, 4),
            "scores": self.scores.to_dict(), "attention": self.attention.to_dict(),
            "promotion": self.promotion.to_dict(),
            "last_deep_analysis_at": self.last_deep_analysis_at,
            "last_event_at": self.last_event_at,
            "data_freshness_ok": self.data_freshness_ok,
            "hard_filter_failures": list(self.hard_filter_failures),
            "updated_at": self.updated_at,
        }


WatchlistEventType = Literal[
    "watchlist_added", "watchlist_promoted", "watchlist_demoted",
    "watchlist_state_changed", "watchlist_event_promoted", "watchlist_event_expired",
    "watchlist_score_updated", "attention_priority_updated",
]


@dataclass
class WatchlistEvent:
    """طبق سند، بخش ۲۴ — قرارداد رویداد واچ‌لیست (کاملاً auditable، بخش ۳۵)."""
    event_type: WatchlistEventType
    symbol: str
    previous_state: Optional[WatchlistState]
    new_state: Optional[WatchlistState]
    opportunity_score: float
    attention_priority: float
    reason: Optional[str]
    trigger_event_id: Optional[str]
    created_at: int
    expires_at: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type, "symbol": self.symbol,
            "previous_state": self.previous_state, "new_state": self.new_state,
            "opportunity_score": round(self.opportunity_score, 4),
            "attention_priority": round(self.attention_priority, 4),
            "reason": self.reason, "trigger_event_id": self.trigger_event_id,
            "created_at": self.created_at, "expires_at": self.expires_at,
        }


@dataclass
class MarketSnapshot:
    """ورودی خامِ هر نماد در یک لحظه — طبق سند، بخش ۸ («ورودی‌های
    بالقوه»). این ماژول هرگز این مقادیر را از صفر محاسبه نمی‌کند؛ همه از
    فیدهای بازار یا خروجی مستندِ ۵ موتور پروژه (SDE/KLSDE/...) گرفته
    می‌شوند — طبق تأکید صریح سند در بخش‌های ۸.۴ و ۸.۶ («نباید منطق SDE/
    KLSDE را بازپیاده‌سازی کند»).
    """
    symbol: str
    time_index: int  # ایندکس زمانی یکنواخت (برای no-look-ahead و بازپخش قطعی)
    # نقدینگی
    volume: Optional[float] = None
    dollar_volume: Optional[float] = None
    spread_pct: Optional[float] = None
    order_book_depth: Optional[float] = None
    # فعالیت بازار
    relative_volume: Optional[float] = None  # نسبت به میانگین پایه
    volume_acceleration: Optional[float] = None
    # نوسان‌پذیری
    atr_pct: Optional[float] = None  # ATR به‌عنوان درصدی از قیمت
    # ساختار تایم‌فریم بالا — از SDE گرفته می‌شود، نه اینجا محاسبه می‌شود
    htf_trend: Optional[str] = None  # "uptrend"|"downtrend"|"range"
    htf_trend_strength: Optional[float] = None
    recent_structure_event_type: Optional[str] = None  # مثلاً "BOS"/"CHoCH"
    recent_structure_event_bars_ago: Optional[int] = None
    # نزدیکی به سطوح کلیدی — از KLSDE گرفته می‌شود
    nearest_key_level_distance_atr: Optional[float] = None
    # شواهد اولیه‌ی ضعیف (بخش ۸.۷) — از موتورهای دیگر یا هیوریستیک سبک
    early_setup_score_raw: Optional[float] = None  # از قبل در [0,1] نرمال شده
    # عمر نماد (برای فیلتر سخت «کمتر از حداقل تاریخچه»)
    listing_age_days: Optional[float] = None
    data_valid: bool = True
