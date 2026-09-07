# -*- coding: utf-8 -*-
"""
signal_engine.confluence.adapters
====================================
پیاده‌سازی بخش ۳ سند «Unified Signal & Setup Confluence Layer»: پنج
آداپتور نازک که خروجی هرکدام از ۵ موتور را به یک پاکت نرمال‌شده‌ی
مشترک (EventEnvelope) تبدیل می‌کنند. هیچ منطق تجاری اینجا نیست — فقط
ترجمه‌ی direction/confidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Literal, Optional

Direction = Literal["bullish", "bearish", "neutral"]
SourceEngine = Literal["PRE", "SDE", "MCDE", "CPDE", "KLSDE"]


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


def adapt_pre_events(events, timeframe: str, symbol: str) -> List[EventEnvelope]:
    out = []
    for i, e in enumerate(events):
        out.append(EventEnvelope(
            envelope_id=f"env_PRE_{timeframe}_{i:06d}", source_engine="PRE", native_event_type=e.pattern_name,
            symbol=symbol, timeframe=timeframe, event_index=e.end_index,
            direction=e.direction, confidence=e.confidence, native_payload=e,
        ))
    return out


def adapt_sde_structure_events(events, timeframe: str, symbol: str) -> List[EventEnvelope]:
    out = []
    for i, e in enumerate(events):
        out.append(EventEnvelope(
            envelope_id=f"env_SDE_{timeframe}_{i:06d}", source_engine="SDE", native_event_type=e.event_type,
            symbol=symbol, timeframe=timeframe, event_index=e.trigger_index,
            direction=e.direction, confidence=e.confidence, native_payload=e,
        ))
    return out


def adapt_mcde_macro_events(events, timeframe: str, symbol: str) -> List[EventEnvelope]:
    """طبق سند بخش ۳.۲: فازهای کلان هرگز anchor نیستند و direction آن‌ها
    فقط برای شواهد پشتیبان/جریمه استفاده می‌شود (بخش ۴.۳ و ۵.۳ سند).
    markup/بازگشایی صعودی → bullish، markdown → bearish، بقیه → neutral.
    """
    out = []
    for i, e in enumerate(events):
        direction: Direction = "bullish" if e.phase == "markup" else ("bearish" if e.phase == "markdown" else "neutral")
        out.append(EventEnvelope(
            envelope_id=f"env_MCDE_macro_{timeframe}_{i:06d}", source_engine="MCDE", native_event_type=f"macro_{e.phase}",
            symbol=symbol, timeframe=timeframe, event_index=e.end_index if e.end_index is not None else e.start_index,
            direction=direction, confidence=e.confidence, native_payload=e,
        ))
    return out


def adapt_mcde_micro_events(events, timeframe: str, symbol: str) -> List[EventEnvelope]:
    out = []
    for i, e in enumerate(events):
        dom_dir = e.evidence.get("dominant_direction", "neutral")
        direction: Direction = "bullish" if (e.stage == "breakout" and dom_dir == "bullish") else \
                                "bearish" if (e.stage == "breakout" and dom_dir == "bearish") else "neutral"
        out.append(EventEnvelope(
            envelope_id=f"env_MCDE_micro_{timeframe}_{i:06d}", source_engine="MCDE", native_event_type=f"micro_{e.stage}",
            symbol=symbol, timeframe=timeframe, event_index=e.end_index,
            direction=direction, confidence=e.confidence, native_payload=e,
        ))
    return out


def adapt_cpde_events(events, timeframe: str, symbol: str) -> List[EventEnvelope]:
    out = []
    for i, e in enumerate(events):
        out.append(EventEnvelope(
            envelope_id=f"env_CPDE_{timeframe}_{i:06d}", source_engine="CPDE", native_event_type=e.pattern_name,
            symbol=symbol, timeframe=timeframe, event_index=max(e.candle_indices),
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
