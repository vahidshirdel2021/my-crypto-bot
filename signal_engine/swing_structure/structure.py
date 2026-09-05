# -*- coding: utf-8 -*-
"""
signal_engine.swing_structure.structure
=========================================
پیاده‌سازی بخش ۶ سند Swing Detection & Market Structure Engine: تشخیص
روند، Break of Structure (BOS) و Change of Character (CHoCH) — منحصراً
روی جریان سوئینگ‌های تأییدشده (خروجی swings.py)، بدون بازخوانی کندل خام
برای منطق اصلی (طبق تأکید صریح سند: «این مرحله نباید کندل خام را دوباره
بخواند»؛ کندل خام فقط برای گرفتن قیمت بسته‌شدن لحظه‌ای لازم است تا BOS/
CHoCH را در لحظه‌ی وقوع تشخیص دهیم).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional

import pandas as pd

from signal_engine.swing_structure.swings import SwingPoint

TrendState = Literal["uptrend", "downtrend", "range"]
StructureEventType = Literal["BOS", "CHoCH"]
Direction = Literal["bullish", "bearish"]


@dataclass
class StructureEvent:
    id: str
    timeframe: str
    symbol: str
    event_type: StructureEventType
    direction: Direction
    trigger_price: float
    trigger_index: int
    broken_swing_id: str
    prior_trend: TrendState
    new_trend: TrendState
    confidence: float = 0.5
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "timeframe": self.timeframe, "symbol": self.symbol,
            "event_type": self.event_type, "direction": self.direction,
            "trigger_price": self.trigger_price, "trigger_index": self.trigger_index,
            "broken_swing_id": self.broken_swing_id,
            "prior_trend": self.prior_trend, "new_trend": self.new_trend,
            "confidence": self.confidence, "evidence": self.evidence,
        }


def trend_state_from_swings(swings: List[SwingPoint], lookback: int = 4) -> TrendState:
    """طبق سند، بخش ۶.۱: HH/HL → uptrend، LH/LL → downtrend، وگرنه range.
    فقط از آخرین ۴ سوئینگ تأییدشده (پیش‌فرض) استفاده می‌شود.
    """
    ordered = sorted([s for s in swings if s.status == "confirmed"], key=lambda s: s.candle_index)
    recent = ordered[-lookback:]
    highs = [s.price for s in recent if s.type == "swing_high"]
    lows = [s.price for s in recent if s.type == "swing_low"]
    if len(highs) < 2 or len(lows) < 2:
        return "range"
    if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
        return "uptrend"
    if highs[-1] < highs[-2] and lows[-1] < lows[-2]:
        return "downtrend"
    return "range"


def _latest_swing_of_type(swings: List[SwingPoint], swing_type: str, before_index: int) -> Optional[SwingPoint]:
    candidates = [s for s in swings if s.type == swing_type and s.status == "confirmed" and s.candle_index < before_index]
    if not candidates:
        return None
    return max(candidates, key=lambda s: s.candle_index)


def detect_structure_events(
    df: pd.DataFrame,
    swings: List[SwingPoint],
    timeframe: str,
    symbol: str = "",
    trend_lookback: int = 4,
) -> List[StructureEvent]:
    """پیمایش کندل به کندل (روی df) برای تشخیص لحظه‌ی دقیق BOS/CHoCH —
    یعنی لحظه‌ای که close یک کندل از آخرین سوئینگ مرتبط عبور می‌کند.

    منطق (طبق سند، بخش ۶.۲ و ۶.۳):
        - روند فعلی را از سوئینگ‌های تأییدشده‌ی *تا همین لحظه* (بدون
          نگاه به آینده) می‌گیریم.
        - uptrend + close > آخرین swing_high تأییدشده  → Bullish BOS
        - downtrend + close < آخرین swing_low تأییدشده → Bearish BOS
        - downtrend + close > آخرین swing_high (که بخشی از توالی LH بود)
          → Bullish CHoCH (سیگنال ضعیف‌تر و پیشرو)
        - uptrend + close < آخرین swing_low (بخشی از توالی HL) → Bearish CHoCH
    """
    if df is None or df.empty or not swings:
        return []

    df_reset = df.reset_index(drop=True)
    events: List[StructureEvent] = []
    already_broken_swing_ids: set = set()

    n = len(df_reset)
    for i in range(n):
        close_price = float(df_reset["close"].iloc[i])
        # فقط سوئینگ‌هایی که تا این لحظه (بدون نگاه به آینده) confirmed شده‌اند
        swings_so_far = [s for s in swings if s.confirmed_at_index is not None and s.confirmed_at_index <= i]
        if not swings_so_far:
            continue

        prior_trend = trend_state_from_swings(swings_so_far, lookback=trend_lookback)
        last_high = _latest_swing_of_type(swings_so_far, "swing_high", before_index=i + 1)
        last_low = _latest_swing_of_type(swings_so_far, "swing_low", before_index=i + 1)

        if prior_trend == "uptrend" and last_high is not None and last_high.id not in already_broken_swing_ids:
            if close_price > last_high.price:
                events.append(StructureEvent(
                    id=f"struct_{timeframe}_{len(events):06d}", timeframe=timeframe, symbol=symbol,
                    event_type="BOS", direction="bullish", trigger_price=close_price, trigger_index=i,
                    broken_swing_id=last_high.id, prior_trend=prior_trend, new_trend="uptrend",
                    confidence=0.7, evidence={"broken_price": last_high.price},
                ))
                already_broken_swing_ids.add(last_high.id)
                continue

        if prior_trend == "downtrend" and last_low is not None and last_low.id not in already_broken_swing_ids:
            if close_price < last_low.price:
                events.append(StructureEvent(
                    id=f"struct_{timeframe}_{len(events):06d}", timeframe=timeframe, symbol=symbol,
                    event_type="BOS", direction="bearish", trigger_price=close_price, trigger_index=i,
                    broken_swing_id=last_low.id, prior_trend=prior_trend, new_trend="downtrend",
                    confidence=0.7, evidence={"broken_price": last_low.price},
                ))
                already_broken_swing_ids.add(last_low.id)
                continue

        # CHoCH: شکست اولین سوئینگِ *خلاف جهت* روند فعلی — سیگنال پیشرو و
        # ضعیف‌تر از BOS (طبق سند، بخش ۶.۳).
        if prior_trend == "downtrend" and last_high is not None and last_high.id not in already_broken_swing_ids:
            if close_price > last_high.price:
                events.append(StructureEvent(
                    id=f"struct_{timeframe}_{len(events):06d}", timeframe=timeframe, symbol=symbol,
                    event_type="CHoCH", direction="bullish", trigger_price=close_price, trigger_index=i,
                    broken_swing_id=last_high.id, prior_trend=prior_trend, new_trend="range",
                    confidence=0.4, evidence={"broken_price": last_high.price, "note": "leading_reversal_signal"},
                ))
                already_broken_swing_ids.add(last_high.id)
                continue

        if prior_trend == "uptrend" and last_low is not None and last_low.id not in already_broken_swing_ids:
            if close_price < last_low.price:
                events.append(StructureEvent(
                    id=f"struct_{timeframe}_{len(events):06d}", timeframe=timeframe, symbol=symbol,
                    event_type="CHoCH", direction="bearish", trigger_price=close_price, trigger_index=i,
                    broken_swing_id=last_low.id, prior_trend=prior_trend, new_trend="range",
                    confidence=0.4, evidence={"broken_price": last_low.price, "note": "leading_reversal_signal"},
                ))
                already_broken_swing_ids.add(last_low.id)
                continue

    return events
