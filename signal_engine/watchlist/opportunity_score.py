# -*- coding: utf-8 -*-
"""
signal_engine.watchlist.opportunity_score
============================================
پیاده‌سازی بخش‌های ۸-۱۰ سند: امتیاز فرصت (Opportunity Score) — «آیا این
بازار ارزش دیده‌شدن دارد؟». عمداً بدون‌جهت (direction-neutral، بخش ۱۰):
هیچ‌کدام از اجزا نباید بگویند «صعودی» یا «نزولی»، فقط «جالب توجه است یا
نه».

طبق تأکید صریح سند (بخش‌های ۸.۴ و ۸.۶): ورودی‌های «ساختار تایم‌فریم
بالا» و «نزدیکی به سطح کلیدی» باید از خروجی مستند SDE/KLSDE گرفته شوند؛
این ماژول هرگز swing/level detection را از نو پیاده نمی‌کند.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from signal_engine.watchlist.models import MarketSnapshot, OpportunityComponents

DEFAULT_WEIGHTS = {
    "liquidity": 0.20,
    "market_activity": 0.20,
    "higher_tf_structure": 0.20,
    "volatility_suitability": 0.15,
    "key_level_proximity": 0.15,
    "early_setup_evidence": 0.10,
}

DEFAULT_OPPORTUNITY_CONFIG = {
    "weights": DEFAULT_WEIGHTS,
    "liquidity_dollar_volume_ceiling": 50_000_000.0,  # فراتر از این، امتیاز نقدینگی اشباع می‌شود
    "activity_relative_volume_ceiling": 5.0,
    "volatility_sweet_spot_atr_pct": 0.02,  # نقطه‌ی ایده‌آل نوسان (۲٪ ATR نسبت به قیمت) — قابل‌تنظیم به‌ازای هر نماد/بازار
    "volatility_tolerance_atr_pct": 0.02,   # پهنای منحنی حول نقطه‌ی ایده‌آل
    "key_level_proximity_atr_ceiling": 3.0,  # فراتر از ۳ ATR فاصله، امتیاز نزدیکی صفر می‌شود
}


def _normalize_ceiling(value: Optional[float], ceiling: float) -> float:
    """نگاشت خطی [0, ceiling] -> [0, 1]، با clamp — برای معیارهایی که
    «هرچه بیشتر بهتر ولی با اشباع» هستند (نقدینگی، فعالیت).
    """
    if value is None or ceiling <= 0:
        return 0.0
    return float(np.clip(value / ceiling, 0.0, 1.0))


def _liquidity_score(snapshot: MarketSnapshot, cfg: dict) -> float:
    """طبق سند، بخش ۸.۲: حجم بالا به‌تنهایی به معنای فرصت بالا نیست —
    این‌جا صرفاً یک سنجه‌ی «آیا بازار برای تحلیل/اجرا قابل‌اتکاست»
    محاسبه می‌شود، نه سیگنال مطلوبیت.
    """
    dv_score = _normalize_ceiling(snapshot.dollar_volume, cfg["liquidity_dollar_volume_ceiling"])
    spread_penalty = 0.0
    if snapshot.spread_pct is not None:
        spread_penalty = float(np.clip(snapshot.spread_pct / 0.01, 0.0, 1.0))  # اسپرد ۱٪ یعنی جریمه‌ی کامل
    return float(np.clip(dv_score * (1.0 - 0.5 * spread_penalty), 0.0, 1.0))


def _activity_score(snapshot: MarketSnapshot, cfg: dict) -> float:
    """طبق سند، بخش ۸.۳."""
    rel_vol_score = _normalize_ceiling(snapshot.relative_volume, cfg["activity_relative_volume_ceiling"])
    accel_bonus = 0.0
    if snapshot.volume_acceleration is not None and snapshot.volume_acceleration > 0:
        accel_bonus = float(np.clip(snapshot.volume_acceleration / 2.0, 0.0, 0.3))
    return float(np.clip(rel_vol_score + accel_bonus, 0.0, 1.0))


def _higher_tf_structure_score(snapshot: MarketSnapshot) -> float:
    """طبق سند، بخش ۸.۴: از خروجی SDE گرفته می‌شود (htf_trend/strength/
    recent_structure_event)، نه محاسبه‌ی جدید سوئینگ/ساختار.
    """
    score = 0.0
    if snapshot.htf_trend in ("uptrend", "downtrend"):
        score += 0.5 * (snapshot.htf_trend_strength if snapshot.htf_trend_strength is not None else 0.5)
    if snapshot.recent_structure_event_type in ("BOS", "CHoCH"):
        bars_ago = snapshot.recent_structure_event_bars_ago
        recency = 1.0 if bars_ago is None else float(np.clip(1.0 - bars_ago / 20.0, 0.0, 1.0))
        weight = 0.5 if snapshot.recent_structure_event_type == "BOS" else 0.35  # CHoCH سیگنال ضعیف‌تر (طبق SDE spec)
        score += weight * recency
    return float(np.clip(score, 0.0, 1.0))


def _volatility_suitability_score(snapshot: MarketSnapshot, cfg: dict) -> float:
    """طبق سند، بخش ۸.۵: نه «هرچه بیشتر بهتر» — یک منحنی زنگوله‌ای حول
    یک نقطه‌ی ایده‌آل. هم خیلی‌کم (بی‌فرصت) و هم خیلی‌زیاد (اجرای ناپایدار)
    جریمه می‌شوند.
    """
    if snapshot.atr_pct is None:
        return 0.0
    sweet_spot = cfg["volatility_sweet_spot_atr_pct"]
    tolerance = max(cfg["volatility_tolerance_atr_pct"], 1e-9)
    z = (snapshot.atr_pct - sweet_spot) / tolerance
    return float(np.clip(np.exp(-0.5 * z * z), 0.0, 1.0))  # منحنی گاوسی حول نقطه‌ی ایده‌آل


def _key_level_proximity_score(snapshot: MarketSnapshot, cfg: dict) -> float:
    """طبق سند، بخش ۸.۶: از خروجی KLSDE (فاصله تا نزدیک‌ترین سطح بر حسب
    ATR) گرفته می‌شود — هرچه فاصله کمتر، امتیاز بیشتر.
    """
    d = snapshot.nearest_key_level_distance_atr
    if d is None:
        return 0.0
    ceiling = cfg["key_level_proximity_atr_ceiling"]
    return float(np.clip(1.0 - (d / ceiling), 0.0, 1.0))


def _early_setup_score(snapshot: MarketSnapshot) -> float:
    """طبق سند، بخش ۸.۷: عمداً ضعیف‌تر از confluence USCL — هرگز نباید
    به‌عنوان TradeSignal تفسیر شود؛ صرفاً یک ورودیِ از پیش نرمال‌شده
    می‌پذیرد (تولیدشده توسط موتورهای دیگر یا یک هیوریستیک سبک بالادستی).
    """
    if snapshot.early_setup_score_raw is None:
        return 0.0
    return float(np.clip(snapshot.early_setup_score_raw, 0.0, 1.0))


def compute_opportunity_score(
    snapshot: MarketSnapshot,
    config: Optional[dict] = None,
) -> tuple:
    """خروجی: (opportunity_score: float in [0,1], components: OpportunityComponents)

    طبق سند بخش ۹: جمع وزن‌دار اجزا، سپس clamp نهایی. بخش ۱۰: بدون‌جهت.
    """
    cfg = {**DEFAULT_OPPORTUNITY_CONFIG, **(config or {})}
    weights = {**DEFAULT_WEIGHTS, **(cfg.get("weights") or {})}

    components = OpportunityComponents(
        liquidity=_liquidity_score(snapshot, cfg),
        market_activity=_activity_score(snapshot, cfg),
        higher_tf_structure=_higher_tf_structure_score(snapshot),
        volatility_suitability=_volatility_suitability_score(snapshot, cfg),
        key_level_proximity=_key_level_proximity_score(snapshot, cfg),
        early_setup_evidence=_early_setup_score(snapshot),
    )

    total_weight = sum(weights.values()) or 1.0
    raw_score = (
        components.liquidity * weights["liquidity"]
        + components.market_activity * weights["market_activity"]
        + components.higher_tf_structure * weights["higher_tf_structure"]
        + components.volatility_suitability * weights["volatility_suitability"]
        + components.key_level_proximity * weights["key_level_proximity"]
        + components.early_setup_evidence * weights["early_setup_evidence"]
    ) / total_weight

    score = float(np.clip(raw_score, 0.0, 1.0))
    return score, components
