# -*- coding: utf-8 -*-
"""
signal_engine.confluence.invalidation
========================================
پیاده‌سازی بخش ۲ سند اصلاحی (Architectural Addendum): ابطال ساختاری
پویا. طبق بخش ۲.۱ سند اصلاحی، طول عمر سیگنال فعلاً فقط با گذشت زمان
(`expires_at`)، تقویت امتیاز، یا جایگزینی با سیگنال متضاد مدیریت
می‌شد — که در بازار پرنوسان کریپتو، قیمت می‌تواند خیلی زودتر از این
سه اتفاق، از مرز ابطال ستاپ (structural_stop_reference) عبور کند. اگر
سیگنال همچنان «فعال» علامت بخورد، لایه‌ی اجرا ممکن است روی یک وضعیت
منسوخ/باطل عمل کند.

طبق بخش ۲.۲: این تابع فقط قیمت لحظه‌ای را با سطح ساختاری مقایسه می‌کند
— هیچ تصمیم اجرایی (لغو سفارش و غیره) اینجا گرفته نمی‌شود؛ آن مسئولیت
صریحاً طبق سند به «لایه‌ی اجرا» (خارج از این پروژه) واگذار شده است.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from signal_engine.confluence.selector import TradeSignal

INVALIDATION_REASON = "structural_stop_breached"


@dataclass
class SignalInvalidatedEvent:
    """طبق بخش ۲.۲.۳ سند اصلاحی — دقیقاً همان فیلدهای مثال JSON آن بخش."""
    signal_id: str
    event_type: str
    symbol: str
    reason: str
    trigger_price: float
    structural_level: float
    time_index: int  # معادل timestamp سند؛ طبق قرارداد کل این پروژه (بازپخش قطعی)، بر حسب ایندکس کندل نگه داشته می‌شود

    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id, "event_type": self.event_type, "symbol": self.symbol,
            "reason": self.reason, "trigger_price": self.trigger_price,
            "structural_level": self.structural_level, "time_index": self.time_index,
        }


def is_invalidation_candidate(signal: TradeSignal) -> bool:
    """طبق بخش ۲.۲.۱: فقط سیگنال‌های فعلاً «فعال» (active/updated) قابل
    ابطال‌اند — سیگنال قبلاً retired/expired/invalidated دوباره بررسی
    نمی‌شود (idempotent).
    """
    return signal.status in ("active", "updated")


def check_structural_invalidation(
    signal: TradeSignal,
    current_price: float,
    time_index: int,
) -> Optional[SignalInvalidatedEvent]:
    """طبق بخش ۲.۲.۲ سند اصلاحی — دقیقاً همان نامساوی‌ها:

        Bullish: اگر current_price <= structural_stop_reference  → باطل
        Bearish: اگر current_price >= structural_stop_reference  → باطل

    اگر structural_stop_reference در reference_levels موجود نباشد (مثلاً
    anchor engine سطح ساختاری‌ای گزارش نکرده)، این تابع محافظه‌کارانه
    None برمی‌گرداند — هرگز سیگنالی را بدون مرجع صریح باطل نمی‌کند.

    در صورت وقوع ابطال: signal.status به‌طور مستقیم به "invalidated"
    تغییر می‌کند (mutation درجا، هماهنگ با این‌که TradeSignal در این
    پروژه یک شیء زنده و قابل‌ردیابی در طول عمرش است) و رویداد برگردانده
    می‌شود؛ کالر مسئول است این رویداد را emit/لاگ کند.
    """
    if not is_invalidation_candidate(signal):
        return None

    stop = signal.reference_levels.get("structural_stop_reference")
    if stop is None:
        return None

    triggered = False
    if signal.direction == "bullish" and current_price <= stop:
        triggered = True
    elif signal.direction == "bearish" and current_price >= stop:
        triggered = True

    if not triggered:
        return None

    signal.status = "invalidated"
    signal.history.append({
        "event": "signal_invalidated", "at_index": time_index,
        "reason": INVALIDATION_REASON, "trigger_price": current_price, "structural_level": stop,
    })

    return SignalInvalidatedEvent(
        signal_id=signal.signal_id, event_type="signal_invalidated", symbol=signal.symbol,
        reason=INVALIDATION_REASON, trigger_price=current_price, structural_level=stop,
        time_index=time_index,
    )
