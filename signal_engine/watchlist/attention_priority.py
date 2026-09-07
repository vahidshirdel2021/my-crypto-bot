# -*- coding: utf-8 -*-
"""
signal_engine.watchlist.attention_priority
=============================================
پیاده‌سازی بخش‌های ۱۱-۱۲ سند: اولویت توجه — کاملاً مستقل از Opportunity
Score (بخش ۳ سند: «هرگز این دو را در یک عدد ادغام نکن»). Event Urgency
می‌تواند رتبه‌بندی عادی را کاملاً بازنویسی کند (بخش ۱۲، مثال SOL/سناریوی
B).
"""

from __future__ import annotations

from typing import Literal, Optional

import numpy as np

from signal_engine.watchlist.models import AttentionComponents, WatchlistState

DEFAULT_ATTENTION_CONFIG = {
    "weights": {
        "event_urgency": 0.35,
        "opportunity": 0.30,
        "transition": 0.15,
        "freshness": 0.10,
        "coverage": 0.10,
    },
    "baseline_by_state": {
        "CORE": 0.5, "ACTIVE": 0.35, "EMERGING": 0.2, "EVENT_HOT": 0.6, "DORMANT": 0.05,
        "DATA_DEGRADED": 0.0,
    },
    "freshness_stale_after_bars": 50,  # بعد از این تعداد کندل بدون تحلیل عمیق، فوریت freshness به حداکثر می‌رسد
    "coverage_target_bars": 20,  # فاصله‌ی «عادی» بین دو تحلیل عمیق برای این نماد
}


def compute_transition_urgency(
    previous_htf_trend: Optional[str],
    current_htf_trend: Optional[str],
) -> float:
    """طبق سند: «شدت گذار ساختاری» — وقتی روند تایم‌فریم بالا عوض می‌شود
    (مثلاً از range به uptrend، یا uptrend به downtrend)، این فوریت را
    بالا می‌برد. از خروجی SDE گرفته می‌شود، نه محاسبه‌ی مجدد سوئینگ.
    """
    if previous_htf_trend is None or current_htf_trend is None:
        return 0.0
    if previous_htf_trend == current_htf_trend:
        return 0.0
    # گذار کامل بین دو روند مخالف (uptrend<->downtrend) از گذار به/از range فوری‌تر است.
    if {previous_htf_trend, current_htf_trend} == {"uptrend", "downtrend"}:
        return 1.0
    return 0.5


def compute_freshness_urgency(
    bars_since_last_deep_analysis: Optional[int],
    stale_after_bars: int,
) -> float:
    """طبق سند: هرچه مدت بیشتری از آخرین تحلیل عمیق گذشته باشد، فوریت
    بیشتر می‌شود — تا نمادی که مدت‌ها نادیده گرفته شده فراموش نشود.
    """
    if bars_since_last_deep_analysis is None:
        return 1.0  # هرگز تحلیل نشده -> بالاترین فوریت
    return float(np.clip(bars_since_last_deep_analysis / max(stale_after_bars, 1), 0.0, 1.0))


def compute_coverage_urgency(
    bars_since_last_deep_analysis: Optional[int],
    target_bars: int,
) -> float:
    """طبق سند: فشار برای رعایت یک نرخ پوشش «عادی» — ملایم‌تر از
    freshness_urgency (که برای حالت‌های افراطیِ فراموش‌شده است).
    """
    if bars_since_last_deep_analysis is None:
        return 0.5
    return float(np.clip(bars_since_last_deep_analysis / max(target_bars, 1) - 1.0, 0.0, 1.0))


def compute_attention_priority(
    state: WatchlistState,
    opportunity_score: float,
    event_urgency: float,
    transition_urgency: float,
    bars_since_last_deep_analysis: Optional[int],
    config: Optional[dict] = None,
) -> tuple:
    """خروجی: (attention_priority: float in [0,1], components: AttentionComponents)

    طبق سند بخش ۱۱، فرمول مفهومی:
        attention = baseline + opportunity_component + event_urgency
                    + transition_urgency + freshness_urgency + coverage_urgency
    سپس clamp به [0,1]. همه‌ی ضرایب قابل‌تنظیم‌اند (بخش ۱۱، آخر).
    """
    cfg = {**DEFAULT_ATTENTION_CONFIG, **(config or {})}
    weights = {**DEFAULT_ATTENTION_CONFIG["weights"], **(cfg.get("weights") or {})}
    baseline = cfg["baseline_by_state"].get(state, 0.1)

    freshness = compute_freshness_urgency(bars_since_last_deep_analysis, cfg["freshness_stale_after_bars"])
    coverage = compute_coverage_urgency(bars_since_last_deep_analysis, cfg["coverage_target_bars"])

    components = AttentionComponents(
        baseline_priority=baseline,
        opportunity_component=opportunity_score * weights["opportunity"],
        event_urgency=event_urgency * weights["event_urgency"],
        transition_urgency=transition_urgency * weights["transition"],
        freshness_urgency=freshness * weights["freshness"],
        coverage_urgency=coverage * weights["coverage"],
    )

    total = (
        components.baseline_priority + components.opportunity_component + components.event_urgency
        + components.transition_urgency + components.freshness_urgency + components.coverage_urgency
    )
    return float(np.clip(total, 0.0, 1.0)), components
