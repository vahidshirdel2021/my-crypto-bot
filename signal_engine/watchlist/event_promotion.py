# -*- coding: utf-8 -*-
"""
signal_engine.watchlist.event_promotion
==========================================
پیاده‌سازی بخش ۱۳ سند: رویدادهایی که می‌توانند یک نماد را به Event/Hot
ترفیع دهند، باید صریحاً کانفیگ شده باشند و دقیقاً با schema مستند
موتورهای بالادستی (که در این پروژه از پیش در signal_engine.confluence.
adapters.EventEnvelope نرمال شده‌اند) مطابقت داشته باشند — این ماژول
هرگز رویداد جعلی اختراع نمی‌کند (تأکید صریح سند، بخش ۱۳، آخر).
"""

from __future__ import annotations

from typing import Optional

DEFAULT_EVENT_PROMOTION_CONFIG = {
    "enabled": True,
    "triggers": {
        "BOS": True,
        "CHoCH": True,
        "key_level_interaction": True,  # هر SetupEvent از KLSDE (BOF/TST/BPB/BP/CPB)
        "breakout": True,  # micro_breakout از MCDE، یا الگوهای PRE با confirmation_status=confirmed
        "breakout_failure": True,  # BOF از KLSDE
        "abnormal_activity": True,  # از MarketSnapshot.volume_acceleration
        "volatility_expansion": True,  # از MarketSnapshot.atr_pct نسبت به baseline
    },
    "ttl_bars": 60,  # طبق سند مثال «۶۰ دقیقه»؛ اینجا بر حسب کندل تایم‌فریم اجرا نگه داشته می‌شود تا با بازپخش قطعی سازگار باشد
    "urgency_by_trigger": {
        "BOS": 1.0,
        "CHoCH": 0.7,  # طبق SDE spec: CHoCH سیگنال ضعیف‌تر/پیشرو است
        "key_level_interaction": 0.85,
        "breakout": 0.8,
        "breakout_failure": 0.75,
        "abnormal_activity": 0.6,
        "volatility_expansion": 0.55,
        # طبق بخش ۱ سند اصلاحی (LMP) — این‌ها فوریت *اولیه و موقت* هستند؛
        # اگر ۵ موتور طی fast TTL چیزی تأیید نکنند، به Dormant برمی‌گردد.
        "lmp_volume_anomaly": 0.5,
        "lmp_range_expansion": 0.5,
        "lmp_key_level_probe": 0.55,
    },
    "abnormal_activity_min_acceleration": 2.0,
    "volatility_expansion_min_atr_pct_ratio": 1.8,  # نسبت ATR فعلی به ATR پایه
}


def classify_promotion_trigger(
    envelope_source_engine: Optional[str],
    envelope_native_event_type: Optional[str],
    config: Optional[dict] = None,
) -> Optional[str]:
    """یک EventEnvelope (از signal_engine.confluence.adapters، یا معادل
    آن از هر ۵ موتور) را می‌گیرد و اگر با یکی از triggerهای فعال مطابقت
    داشت، نام trigger منطقی (طبق تاکسونومی این سند) را برمی‌گرداند،
    وگرنه None.
    """
    cfg = {**DEFAULT_EVENT_PROMOTION_CONFIG, **(config or {})}
    if not cfg["enabled"]:
        return None
    triggers = cfg["triggers"]

    if envelope_source_engine == "SDE":
        if envelope_native_event_type == "BOS" and triggers.get("BOS"):
            return "BOS"
        if envelope_native_event_type == "CHoCH" and triggers.get("CHoCH"):
            return "CHoCH"

    if envelope_source_engine == "KLSDE":
        if envelope_native_event_type == "BOF" and triggers.get("breakout_failure"):
            return "breakout_failure"
        if envelope_native_event_type in ("TST", "BPB", "BP", "CPB") and triggers.get("key_level_interaction"):
            return "key_level_interaction"

    if envelope_source_engine == "MCDE" and envelope_native_event_type == "micro_breakout" and triggers.get("breakout"):
        return "breakout"

    if envelope_source_engine == "PRE" and triggers.get("breakout"):
        return "breakout"

    return None


def urgency_for_trigger(trigger: str, config: Optional[dict] = None) -> float:
    cfg = {**DEFAULT_EVENT_PROMOTION_CONFIG, **(config or {})}
    return float(cfg["urgency_by_trigger"].get(trigger, 0.5))


def check_market_data_triggers(
    volume_acceleration: Optional[float],
    atr_pct: Optional[float],
    baseline_atr_pct: Optional[float],
    config: Optional[dict] = None,
) -> Optional[str]:
    """طبق سند: «فعالیت غیرعادی» و «انبساط نوسان» هم می‌توانند trigger
    باشند، ولی این‌ها از داده‌ی بازار خام (نه رویداد یک موتور) می‌آیند —
    پس جداگانه چک می‌شوند، نه از EventEnvelope.
    """
    cfg = {**DEFAULT_EVENT_PROMOTION_CONFIG, **(config or {})}
    triggers = cfg["triggers"]

    if triggers.get("abnormal_activity") and volume_acceleration is not None:
        if volume_acceleration >= cfg["abnormal_activity_min_acceleration"]:
            return "abnormal_activity"

    if triggers.get("volatility_expansion") and atr_pct is not None and baseline_atr_pct:
        if atr_pct / max(baseline_atr_pct, 1e-9) >= cfg["volatility_expansion_min_atr_pct_ratio"]:
            return "volatility_expansion"

    return None
