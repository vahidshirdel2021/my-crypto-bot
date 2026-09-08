# -*- coding: utf-8 -*-
"""
signal_engine.confluence.adapters
====================================
پیاده‌سازی بخش ۳ سند «Unified Signal & Setup Confluence Layer»: آداپتورهای
نازکی که خروجی هرکدام از موتورهای فعال پروژه را به یک پاکت نرمال‌شده‌ی
مشترک (EventEnvelope) تبدیل می‌کنند. هیچ منطق تجاری اینجا نیست — فقط
ترجمه‌ی direction/confidence.

توجه: آداپتورهای PRE/CPDE/MCDE (pattern_recognition/candlestick/
market_cycle) طبق درخواست صریح کاربر به‌طور کامل حذف شده‌اند؛ فقط SDE
(swing_structure) و KLSDE (key_level_setup) باقی مانده‌اند.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Literal, Optional

Direction = Literal["bullish", "bearish", "neutral"]
SourceEngine = Literal["SDE", "KLSDE"]


@dataclass
class EventEnvelope:
    envelope_id: str
    source_engine: SourceEngine
    native_event_type: str
    symbol: str
    timeframe: str
    event_index: int  # ایندکس کندل (به‌جای timestamp واقعی، برای سادگی‌ی batch mode این پروژه)
    direction: Direction
    confidence: float
    native_payload: Any = field(default=None)

    def to_dict(self) -> dict:
        return {
            "envelope_id": self.envelope_id, "source_engine": self.source_engine,
            "native_event_type": self.native_event_type, "symbol": self.symbol,
            "timeframe": self.timeframe, "event_index": self.event_index,
            "direction": self.direction, "confidence": self.confidence,
        }


def adapt_sde_structure_events(events, timeframe: str, symbol: str) -> List[EventEnvelope]:
    out = []
    for i, e in enumerate(events):
        out.append(EventEnvelope(
            envelope_id=f"env_SDE_{timeframe}_{i:06d}", source_engine="SDE", native_event_type=e.event_type,
            symbol=symbol, timeframe=timeframe, event_index=e.trigger_index,
            direction=e.direction, confidence=e.confidence, native_payload=e,
        ))
    return out


def adapt_klsde_events(events, timeframe: str, symbol: str) -> List[EventEnvelope]:
    out = []
    for i, e in enumerate(events):
        out.append(EventEnvelope(
            envelope_id=f"env_KLSDE_{timeframe}_{i:06d}", source_engine="KLSDE", native_event_type=e.setup_type,
            symbol=symbol, timeframe=timeframe, event_index=e.resolved_at_index,
            direction=e.direction, confidence=e.confidence, native_payload=e,
        ))
    return out
