# -*- coding: utf-8 -*-
"""
signal_engine.candlestick.detectors
======================================
پیاده‌سازی خط‌به‌خط سند «Candlestick Pattern Detection Engine». هر تابع
دقیقاً طبق نسبت‌های هندسیِ صریح سند (نه آستانه‌ی مبهم) پیاده شده و پیش
از بررسی هندسه، پیش‌شرط روند (Section 4 سند) را از سرویس مشترک
trend_context می‌گیرد.

طبق سند: الگوهای هارامی اینجا هم استفاده می‌شوند اما پیاده‌سازی مشترک
باید از pattern_recognition وارد شود تا تکراری نباشد — چون
pattern_recognition هنوز ساخته نشده، فعلاً پیاده‌سازی هارامی همین‌جاست
و signal_engine.pattern_recognition وقتی ساخته شد از همین‌جا وارد
می‌کند (نه برعکس) — این ترتیب در کامنت‌های مربوطه صراحتاً ثبت شده تا در
حین ساخت موتور بعدی فراموش نشود.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

import pandas as pd

from signal_engine.common.atr import compute_atr
from signal_engine.common.candle_geometry import compute_candle_geometry, compute_candle_geometry_batch
from signal_engine.common.trend_context import combined_trend_context

Direction = Literal["bullish", "bearish", "neutral"]

DEFAULT_CONFIG = {
    "trend_lookback": 10,
    "atr_period": 14,
    "hammer_shadow_multiple": 2.0,
    "hammer_upper_shadow_max_pct": 0.1,
    "hammer_body_position_min_pct": 0.6,
    "bullish_color_bonus": 0.05,
    "doji_body_max_pct": 0.08,
    "gravestone_upper_shadow_min_pct": 0.6,
    "dragonfly_lower_shadow_min_pct": 0.6,
    "long_legged_balance_tolerance_pct": 0.2,
    "harami_candle1_min_atr_multiple": 1.0,
    "dark_cloud_candle1_min_atr_multiple": 0.8,
    "dark_cloud_volume_spike_multiple": 1.3,
    "three_soldiers_max_lower_shadow_pct": 0.15,
    "three_methods_containment": "body_only",  # یا "full_range"
    "marubozu_max_shadow_pct": 0.05,
    "star_middle_max_body_pct": 0.3,
    "star_penetration_min_pct": 0.5,
}


@dataclass
class CandlestickPatternEvent:
    pattern_name: str
    category: Literal["single_candle", "doji", "two_candle", "three_candle"]
    direction: Direction
    type: Literal["reversal", "continuation", "indecision"]
    timeframe: str
    symbol: str
    candle_indices: List[int]
    confidence: float
    confirmation_status: Literal["confirmed", "unconfirmed", "not_applicable"]
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "pattern_name": self.pattern_name, "category": self.category, "direction": self.direction,
            "type": self.type, "timeframe": self.timeframe, "symbol": self.symbol,
            "candle_indices": self.candle_indices, "confidence": self.confidence,
            "confirmation_status": self.confirmation_status, "evidence": self.evidence,
        }


def _trend_before(df: pd.DataFrame, idx: int, lookback: int) -> str:
    start = max(0, idx - lookback)
    sub = df.iloc[start:idx]
    if len(sub) < 3:
        return "range"
    # ema_period باید متناسب با پنجره‌ی lookback باشد، وگرنه (طبق پیش‌فرض
    # سراسری ema_period=20) با lookback کوچک‌تر (پیش‌فرض سند: ۱۰) هرگز
    # داده‌ی کافی برای EMA نخواهد بود و trend همیشه "range" برمی‌گردد.
    fitted_ema_period = max(3, len(sub) // 2)
    return combined_trend_context(sub, ema_period=fitted_ema_period).trend


# ---------------------------------------------------------------------------
# الگوهای تک‌کندلی: Hammer / Inverted Hammer / Hanging Man / Shooting Star
# ---------------------------------------------------------------------------


def detect_hammer_family(
    df: pd.DataFrame, timeframe: str, symbol: str = "", config: Optional[dict] = None
) -> List[CandlestickPatternEvent]:
    """هر ۴ الگو (Hammer، Inverted Hammer، Hanging Man، Shooting Star) در
    یک پاس بررسی می‌شوند چون هندسه‌شان دو-به-دو مشترک است — فقط پیش‌شرط
    روند تفاوت آن‌ها را مشخص می‌کند (طبق سند، بخش ۵.۱).

    نسخه‌ی برداری‌شده: هندسه‌ی همه‌ی کندل‌ها یک‌بار با numpy محاسبه می‌شود
    (compute_candle_geometry_batch) به‌جای فراخوانی اسکالر به ازای هر
    کندل — طبق پروفایل واقعی عملکرد، این حلقه گلوگاه اصلی CPDE بود.
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    events: List[CandlestickPatternEvent] = []
    n = len(df)
    if n <= cfg["trend_lookback"]:
        return events

    geo = compute_candle_geometry_batch(df)
    body_bottom, body_size = geo["body_bottom"], geo["body_size"]
    upper_shadow, lower_shadow = geo["upper_shadow"], geo["lower_shadow"]
    is_bullish = geo["is_bullish"]
    low_price = body_bottom - lower_shadow

    for i in range(cfg["trend_lookback"], n):
        bs = body_size[i]
        if bs <= 0 or pd.isna(bs):
            continue
        trend = _trend_before(df, i, cfg["trend_lookback"])
        if trend not in ("uptrend", "downtrend"):
            continue

        lower_ok = (
            lower_shadow[i] >= cfg["hammer_shadow_multiple"] * bs
            and upper_shadow[i] <= cfg["hammer_upper_shadow_max_pct"] * bs
            and body_bottom[i] >= low_price[i] + cfg["hammer_body_position_min_pct"] * geo["range_size"][i]
        )
        upper_ok = (
            upper_shadow[i] >= cfg["hammer_shadow_multiple"] * bs
            and lower_shadow[i] <= cfg["hammer_upper_shadow_max_pct"] * bs
            and upper_shadow[i] >= cfg["hammer_body_position_min_pct"] * geo["range_size"][i]
        )

        if lower_ok and trend == "downtrend":
            conf = 0.55 + (0.05 if is_bullish[i] else 0.0) + 0.1 * min(lower_shadow[i] / bs / cfg["hammer_shadow_multiple"], 2.0) / 2.0
            events.append(CandlestickPatternEvent(
                pattern_name="hammer", category="single_candle", direction="bullish", type="reversal",
                timeframe=timeframe, symbol=symbol, candle_indices=[i], confidence=round(min(conf, 1.0), 3),
                confirmation_status="unconfirmed",
                evidence={"prior_trend": trend, "is_bullish_candle": bool(is_bullish[i]),
                          "lower_shadow_to_body_ratio": round(float(lower_shadow[i] / bs), 2)},
            ))
        elif lower_ok and trend == "uptrend":
            conf = 0.5 + 0.1 * min(lower_shadow[i] / bs / cfg["hammer_shadow_multiple"], 2.0) / 2.0
            events.append(CandlestickPatternEvent(
                pattern_name="hanging_man", category="single_candle", direction="bearish", type="reversal",
                timeframe=timeframe, symbol=symbol, candle_indices=[i], confidence=round(min(conf, 1.0), 3),
                confirmation_status="unconfirmed",
                evidence={"prior_trend": trend, "lower_shadow_to_body_ratio": round(float(lower_shadow[i] / bs), 2)},
            ))

        if upper_ok and trend == "downtrend":
            conf = 0.5 + 0.1 * min(upper_shadow[i] / bs / cfg["hammer_shadow_multiple"], 2.0) / 2.0
            events.append(CandlestickPatternEvent(
                pattern_name="inverted_hammer", category="single_candle", direction="bullish", type="reversal",
                timeframe=timeframe, symbol=symbol, candle_indices=[i], confidence=round(min(conf, 1.0), 3),
                confirmation_status="unconfirmed",
                evidence={"prior_trend": trend, "upper_shadow_to_body_ratio": round(float(upper_shadow[i] / bs), 2)},
            ))
        elif upper_ok and trend == "uptrend":
            conf = 0.55 + 0.1 * min(upper_shadow[i] / bs / cfg["hammer_shadow_multiple"], 2.0) / 2.0
            events.append(CandlestickPatternEvent(
                pattern_name="shooting_star", category="single_candle", direction="bearish", type="reversal",
                timeframe=timeframe, symbol=symbol, candle_indices=[i], confidence=round(min(conf, 1.0), 3),
                confirmation_status="unconfirmed",
                evidence={"prior_trend": trend, "upper_shadow_to_body_ratio": round(float(upper_shadow[i] / bs), 2)},
            ))
    return events


# ---------------------------------------------------------------------------
# خانواده‌ی دوجی: Gravestone / Dragonfly / Long-Legged (+ Spinning-Top tolerance band)
# ---------------------------------------------------------------------------

def detect_doji_family(
    df: pd.DataFrame, timeframe: str, symbol: str = "", config: Optional[dict] = None
) -> List[CandlestickPatternEvent]:
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    events: List[CandlestickPatternEvent] = []
    n = len(df)
    if n <= cfg["trend_lookback"]:
        return events

    geo = compute_candle_geometry_batch(df, doji_threshold=cfg["doji_body_max_pct"])
    upper_shadow, lower_shadow = geo["upper_shadow"], geo["lower_shadow"]
    ratio, range_size, primitive = geo["body_to_range_ratio"], geo["range_size"], geo["primitive"]

    for i in range(cfg["trend_lookback"], n):
        if primitive[i] != "doji" or range_size[i] <= 0 or pd.isna(ratio[i]):
            continue
        trend = _trend_before(df, i, cfg["trend_lookback"])
        variant = "doji" if ratio[i] <= cfg["doji_body_max_pct"] * 0.3 else "spinning_top"
        rs = range_size[i]

        is_gravestone = (
            upper_shadow[i] >= cfg["gravestone_upper_shadow_min_pct"] * rs
            and lower_shadow[i] <= (1 - cfg["gravestone_upper_shadow_min_pct"]) * 0.3 * rs
        )
        is_dragonfly = (
            lower_shadow[i] >= cfg["dragonfly_lower_shadow_min_pct"] * rs
            and upper_shadow[i] <= (1 - cfg["dragonfly_lower_shadow_min_pct"]) * 0.3 * rs
        )
        is_long_legged = (
            not is_gravestone and not is_dragonfly
            and abs(upper_shadow[i] - lower_shadow[i]) <= cfg["long_legged_balance_tolerance_pct"] * rs
            and upper_shadow[i] > 0.2 * rs and lower_shadow[i] > 0.2 * rs
        )

        if is_gravestone:
            reversal_valid = trend == "uptrend"
            events.append(CandlestickPatternEvent(
                pattern_name="gravestone_doji", category="doji",
                direction="bearish" if reversal_valid else "neutral", type="reversal" if reversal_valid else "indecision",
                timeframe=timeframe, symbol=symbol, candle_indices=[i],
                confidence=round(0.5 if reversal_valid else 0.25, 3), confirmation_status="not_applicable",
                evidence={"prior_trend": trend, "reversal_context_valid": reversal_valid, "variant": variant},
            ))
        elif is_dragonfly:
            reversal_valid = trend == "downtrend"
            events.append(CandlestickPatternEvent(
                pattern_name="dragonfly_doji", category="doji",
                direction="bullish" if reversal_valid else "neutral", type="reversal" if reversal_valid else "indecision",
                timeframe=timeframe, symbol=symbol, candle_indices=[i],
                confidence=round(0.5 if reversal_valid else 0.25, 3), confirmation_status="not_applicable",
                evidence={"prior_trend": trend, "reversal_context_valid": reversal_valid, "variant": variant},
            ))
        elif is_long_legged:
            events.append(CandlestickPatternEvent(
                pattern_name="long_legged_doji", category="doji", direction="neutral", type="indecision",
                timeframe=timeframe, symbol=symbol, candle_indices=[i], confidence=0.35,
                confirmation_status="not_applicable",
                evidence={"prior_trend": trend, "variant": variant},
            ))
    return events


# ---------------------------------------------------------------------------
# هارامی صعودی/نزولی (طبق سند: باید مشترک با pattern_recognition باشد —
# اینجا پیاده‌سازی «منبع حقیقت» است؛ pattern_recognition بعداً از همین
# ایمپورت می‌کند تا تکراری نشود)
# ---------------------------------------------------------------------------

def detect_harami(
    df: pd.DataFrame, timeframe: str, symbol: str = "", config: Optional[dict] = None
) -> List[CandlestickPatternEvent]:
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    d = compute_atr(df.reset_index(drop=True), period=cfg["atr_period"])
    events: List[CandlestickPatternEvent] = []
    n = len(d)
    for i in range(max(cfg["trend_lookback"], 1), n):
        atr_val = d["atr"].iloc[i - 1]
        if pd.isna(atr_val) or atr_val <= 0:
            continue
        c1 = d.iloc[i - 1]
        c2 = d.iloc[i]
        g1 = compute_candle_geometry(c1["open"], c1["high"], c1["low"], c1["close"])
        g2 = compute_candle_geometry(c2["open"], c2["high"], c2["low"], c2["close"])
        if g1.body_size < cfg["harami_candle1_min_atr_multiple"] * atr_val:
            continue
        contained = g2.body_top <= g1.body_top and g2.body_bottom >= g1.body_bottom
        if not contained:
            continue
        trend = _trend_before(df, i - 1, cfg["trend_lookback"])

        if g1.is_bearish and g2.is_bullish and trend == "downtrend":
            events.append(CandlestickPatternEvent(
                pattern_name="bullish_harami", category="two_candle", direction="bullish", type="reversal",
                timeframe=timeframe, symbol=symbol, candle_indices=[i - 1, i], confidence=0.6,
                confirmation_status="unconfirmed",
                evidence={"prior_trend": trend, "candle1_body_atr": round(g1.body_size / atr_val, 2)},
            ))
        elif g1.is_bullish and g2.is_bearish and trend == "uptrend":
            events.append(CandlestickPatternEvent(
                pattern_name="bearish_harami", category="two_candle", direction="bearish", type="reversal",
                timeframe=timeframe, symbol=symbol, candle_indices=[i - 1, i], confidence=0.6,
                confirmation_status="unconfirmed",
                evidence={"prior_trend": trend, "candle1_body_atr": round(g1.body_size / atr_val, 2)},
            ))
    return events


# ---------------------------------------------------------------------------
# ابر سیاه (Dark Cloud Cover)
# ---------------------------------------------------------------------------

def detect_dark_cloud_cover(
    df: pd.DataFrame, timeframe: str, symbol: str = "", config: Optional[dict] = None
) -> List[CandlestickPatternEvent]:
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    d = compute_atr(df.reset_index(drop=True), period=cfg["atr_period"])
    events: List[CandlestickPatternEvent] = []
    n = len(d)
    has_volume = "volume" in d.columns
    for i in range(max(cfg["trend_lookback"], 1), n):
        atr_val = d["atr"].iloc[i - 1]
        if pd.isna(atr_val) or atr_val <= 0:
            continue
        c1, c2 = d.iloc[i - 1], d.iloc[i]
        g1 = compute_candle_geometry(c1["open"], c1["high"], c1["low"], c1["close"])
        g2 = compute_candle_geometry(c2["open"], c2["high"], c2["low"], c2["close"])
        trend = _trend_before(df, i - 1, cfg["trend_lookback"])
        if trend != "uptrend" or not g1.is_bullish or not g2.is_bearish:
            continue
        if g1.body_size < cfg["dark_cloud_candle1_min_atr_multiple"] * atr_val:
            continue
        gapped_above = c2["open"] >= c1["high"] or c2["open"] >= c1["close"]
        midpoint = g1.body_bottom + 0.5 * g1.body_size
        penetrates_midpoint = c2["close"] < midpoint
        if not (gapped_above and penetrates_midpoint):
            continue
        high_volume = False
        if has_volume:
            avg_vol = d["volume"].iloc[max(0, i - 20): i].mean()
            high_volume = bool(avg_vol and c2["volume"] > cfg["dark_cloud_volume_spike_multiple"] * avg_vol)
        events.append(CandlestickPatternEvent(
            pattern_name="dark_cloud_cover", category="two_candle", direction="bearish", type="reversal",
            timeframe=timeframe, symbol=symbol, candle_indices=[i - 1, i],
            confidence=round(0.55 + (0.1 if high_volume else 0.0), 3),
            confirmation_status="unconfirmed",
            evidence={"prior_trend": trend, "high_volume_context": high_volume,
                      "pending_third_candle_confirmation": True},
        ))
    return events


# ---------------------------------------------------------------------------
# سه سرباز صعودی / سه کلاغ سیاه
# ---------------------------------------------------------------------------

def detect_three_soldiers_crows(
    df: pd.DataFrame, timeframe: str, symbol: str = "", config: Optional[dict] = None
) -> List[CandlestickPatternEvent]:
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    events: List[CandlestickPatternEvent] = []
    n = len(df)
    for i in range(2, n):
        c0, c1, c2 = df.iloc[i - 2], df.iloc[i - 1], df.iloc[i]
        g0 = compute_candle_geometry(c0["open"], c0["high"], c0["low"], c0["close"])
        g1 = compute_candle_geometry(c1["open"], c1["high"], c1["low"], c1["close"])
        g2 = compute_candle_geometry(c2["open"], c2["high"], c2["low"], c2["close"])

        if g0.is_bullish and g1.is_bullish and g2.is_bullish:
            opens_ok = (g0.body_bottom <= c1["open"] <= g0.body_top) and (g1.body_bottom <= c2["open"] <= g1.body_top)
            closes_ok = c1["close"] > c0["close"] and c2["close"] > c1["close"]
            if opens_ok and closes_ok:
                shadow_quality = sum(
                    1 for g in (g0, g1, g2)
                    if g.body_size > 0 and g.lower_shadow <= cfg["three_soldiers_max_lower_shadow_pct"] * g.body_size
                ) / 3.0
                events.append(CandlestickPatternEvent(
                    pattern_name="three_white_soldiers", category="three_candle", direction="bullish",
                    type="continuation", timeframe=timeframe, symbol=symbol, candle_indices=[i - 2, i - 1, i],
                    confidence=round(0.5 + 0.3 * shadow_quality, 3), confirmation_status="confirmed",
                    evidence={"shadow_quality_score": round(shadow_quality, 2)},
                ))

        if g0.is_bearish and g1.is_bearish and g2.is_bearish:
            opens_ok = (g0.body_bottom <= c1["open"] <= g0.body_top) and (g1.body_bottom <= c2["open"] <= g1.body_top)
            closes_ok = c1["close"] < c0["close"] and c2["close"] < c1["close"]
            if opens_ok and closes_ok:
                shadow_quality = sum(
                    1 for g in (g0, g1, g2)
                    if g.body_size > 0 and g.upper_shadow <= cfg["three_soldiers_max_lower_shadow_pct"] * g.body_size
                ) / 3.0
                events.append(CandlestickPatternEvent(
                    pattern_name="three_black_crows", category="three_candle", direction="bearish",
                    type="continuation", timeframe=timeframe, symbol=symbol, candle_indices=[i - 2, i - 1, i],
                    confidence=round(0.5 + 0.3 * shadow_quality, 3), confirmation_status="confirmed",
                    evidence={"shadow_quality_score": round(shadow_quality, 2)},
                ))
    return events


# ---------------------------------------------------------------------------
# Rising / Falling Three Methods (پنج‌کندلی)
# ---------------------------------------------------------------------------

def detect_three_methods(
    df: pd.DataFrame, timeframe: str, symbol: str = "", config: Optional[dict] = None
) -> List[CandlestickPatternEvent]:
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    events: List[CandlestickPatternEvent] = []
    n = len(df)
    for i in range(4, n):
        c1, c2, c3, c4, c5 = (df.iloc[i - 4 + j] for j in range(5))
        g1 = compute_candle_geometry(c1["open"], c1["high"], c1["low"], c1["close"])
        g5 = compute_candle_geometry(c5["open"], c5["high"], c5["low"], c5["close"])
        mids = [compute_candle_geometry(c["open"], c["high"], c["low"], c["close"]) for c in (c2, c3, c4)]
        trend = _trend_before(df, i - 4, cfg["trend_lookback"])

        def _contained(gm, ref):
            if cfg["three_methods_containment"] == "full_range":
                return ref["low"] <= gm.body_bottom and gm.body_top <= ref["high"]
            return ref["low"] <= gm.body_bottom and gm.body_top <= ref["high"]  # همان full_range به‌عنوان محافظه‌کارانه‌ترین حالت پیش‌فرض

        if trend == "uptrend" and g1.is_bullish and all(g.is_bearish for g in mids) and g5.is_bullish:
            if all(_contained(g, c1) for g in mids) and c5["close"] > c1["high"]:
                events.append(CandlestickPatternEvent(
                    pattern_name="rising_three_methods", category="three_candle", direction="bullish",
                    type="continuation", timeframe=timeframe, symbol=symbol,
                    candle_indices=[i - 4, i - 3, i - 2, i - 1, i], confidence=0.6, confirmation_status="confirmed",
                    evidence={"prior_trend": trend, "containment": cfg["three_methods_containment"]},
                ))

        if trend == "downtrend" and g1.is_bearish and all(g.is_bullish for g in mids) and g5.is_bearish:
            if all(_contained(g, c1) for g in mids) and c5["close"] < c1["low"]:
                events.append(CandlestickPatternEvent(
                    pattern_name="falling_three_methods", category="three_candle", direction="bearish",
                    type="continuation", timeframe=timeframe, symbol=symbol,
                    candle_indices=[i - 4, i - 3, i - 2, i - 1, i], confidence=0.6, confirmation_status="confirmed",
                    evidence={"prior_trend": trend, "containment": cfg["three_methods_containment"]},
                ))
    return events


# ---------------------------------------------------------------------------
# Engulfing صعودی/نزولی (طبق سند، بخش ۶ — قبلاً stub بود)
# ---------------------------------------------------------------------------

def detect_engulfing(
    df: pd.DataFrame, timeframe: str, symbol: str = "", config: Optional[dict] = None
) -> List[CandlestickPatternEvent]:
    """برخلاف هارامی (که بدنه‌ی کندل دوم داخل بدنه‌ی کندل اول محصور
    می‌شود)، در Engulfing دقیقاً برعکس است: بدنه‌ی کندل دوم به‌طور کامل
    بدنه‌ی کندل اول را می‌بلعد (body_top و body_bottom کندل دوم هر دو
    فراتر از کندل اول).
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    d = compute_atr(df.reset_index(drop=True), period=cfg["atr_period"])
    events: List[CandlestickPatternEvent] = []
    n = len(d)
    for i in range(max(cfg["trend_lookback"], 1), n):
        atr_val = d["atr"].iloc[i - 1]
        if pd.isna(atr_val) or atr_val <= 0:
            continue
        c1, c2 = d.iloc[i - 1], d.iloc[i]
        g1 = compute_candle_geometry(c1["open"], c1["high"], c1["low"], c1["close"])
        g2 = compute_candle_geometry(c2["open"], c2["high"], c2["low"], c2["close"])
        engulfs = g2.body_top >= g1.body_top and g2.body_bottom <= g1.body_bottom and g2.body_size > g1.body_size
        if not engulfs:
            continue
        trend = _trend_before(df, i - 1, cfg["trend_lookback"])

        if g1.is_bearish and g2.is_bullish and trend == "downtrend":
            events.append(CandlestickPatternEvent(
                pattern_name="bullish_engulfing", category="two_candle", direction="bullish", type="reversal",
                timeframe=timeframe, symbol=symbol, candle_indices=[i - 1, i],
                confidence=round(min(1.0, 0.55 + 0.15 * min(g2.body_size / max(g1.body_size, 1e-9) - 1.0, 1.0)), 3),
                confirmation_status="unconfirmed",
                evidence={"prior_trend": trend, "engulf_ratio": round(g2.body_size / max(g1.body_size, 1e-9), 2)},
            ))
        elif g1.is_bullish and g2.is_bearish and trend == "uptrend":
            events.append(CandlestickPatternEvent(
                pattern_name="bearish_engulfing", category="two_candle", direction="bearish", type="reversal",
                timeframe=timeframe, symbol=symbol, candle_indices=[i - 1, i],
                confidence=round(min(1.0, 0.55 + 0.15 * min(g2.body_size / max(g1.body_size, 1e-9) - 1.0, 1.0)), 3),
                confirmation_status="unconfirmed",
                evidence={"prior_trend": trend, "engulf_ratio": round(g2.body_size / max(g1.body_size, 1e-9), 2)},
            ))
    return events


# ---------------------------------------------------------------------------
# Marubozu (طبق سند، بخش ۶)
# ---------------------------------------------------------------------------

def detect_marubozu(
    df: pd.DataFrame, timeframe: str, symbol: str = "", config: Optional[dict] = None
) -> List[CandlestickPatternEvent]:
    """کندل با بدنه‌ی بسیار بزرگ و سایه‌های ناچیز در هر دو طرف — نشانه‌ی
    اعتماد جهت‌دار قوی. برخلاف الگوهای بازگشتی، پیش‌شرط روند خاصی ندارد؛
    جهت خودِ کندل، جهت الگو را مشخص می‌کند.
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    marubozu_max_shadow_pct = cfg.get("marubozu_max_shadow_pct", 0.05)
    events: List[CandlestickPatternEvent] = []
    n = len(df)
    for i in range(n):
        row = df.iloc[i]
        g = compute_candle_geometry(row["open"], row["high"], row["low"], row["close"])
        if g.range_size <= 0 or g.body_size <= 0:
            continue
        if g.upper_shadow <= marubozu_max_shadow_pct * g.range_size and g.lower_shadow <= marubozu_max_shadow_pct * g.range_size and g.body_to_range_ratio >= 0.9:
            direction: Direction = "bullish" if g.is_bullish else "bearish"
            events.append(CandlestickPatternEvent(
                pattern_name="marubozu", category="single_candle", direction=direction, type="continuation",
                timeframe=timeframe, symbol=symbol, candle_indices=[i],
                confidence=round(0.5 + 0.3 * g.body_to_range_ratio, 3), confirmation_status="not_applicable",
                evidence={"body_to_range_ratio": round(g.body_to_range_ratio, 3)},
            ))
    return events


# ---------------------------------------------------------------------------
# Piercing Line (آینه‌ی صعودی Dark Cloud Cover — طبق سند، بخش ۶)
# ---------------------------------------------------------------------------

def detect_piercing_line(
    df: pd.DataFrame, timeframe: str, symbol: str = "", config: Optional[dict] = None
) -> List[CandlestickPatternEvent]:
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    d = compute_atr(df.reset_index(drop=True), period=cfg["atr_period"])
    events: List[CandlestickPatternEvent] = []
    n = len(d)
    has_volume = "volume" in d.columns
    for i in range(max(cfg["trend_lookback"], 1), n):
        atr_val = d["atr"].iloc[i - 1]
        if pd.isna(atr_val) or atr_val <= 0:
            continue
        c1, c2 = d.iloc[i - 1], d.iloc[i]
        g1 = compute_candle_geometry(c1["open"], c1["high"], c1["low"], c1["close"])
        g2 = compute_candle_geometry(c2["open"], c2["high"], c2["low"], c2["close"])
        trend = _trend_before(df, i - 1, cfg["trend_lookback"])
        if trend != "downtrend" or not g1.is_bearish or not g2.is_bullish:
            continue
        if g1.body_size < cfg["dark_cloud_candle1_min_atr_multiple"] * atr_val:
            continue
        gapped_below = c2["open"] <= c1["low"] or c2["open"] <= c1["close"]
        midpoint = g1.body_bottom + 0.5 * g1.body_size
        penetrates_midpoint = c2["close"] > midpoint
        if not (gapped_below and penetrates_midpoint):
            continue
        high_volume = False
        if has_volume:
            avg_vol = d["volume"].iloc[max(0, i - 20): i].mean()
            high_volume = bool(avg_vol and c2["volume"] > cfg["dark_cloud_volume_spike_multiple"] * avg_vol)
        events.append(CandlestickPatternEvent(
            pattern_name="piercing_line", category="two_candle", direction="bullish", type="reversal",
            timeframe=timeframe, symbol=symbol, candle_indices=[i - 1, i],
            confidence=round(0.55 + (0.1 if high_volume else 0.0), 3),
            confirmation_status="unconfirmed",
            evidence={"prior_trend": trend, "high_volume_context": high_volume,
                      "pending_third_candle_confirmation": True},
        ))
    return events


# ---------------------------------------------------------------------------
# Morning Star / Evening Star (طبق سند، بخش ۶)
# ---------------------------------------------------------------------------

def _detect_star(df, timeframe, symbol, cfg, direction: Direction) -> List[CandlestickPatternEvent]:
    d = compute_atr(df.reset_index(drop=True), period=cfg["atr_period"])
    events: List[CandlestickPatternEvent] = []
    n = len(d)
    star_max_body_pct = cfg.get("star_middle_max_body_pct", 0.3)
    penetration_min_pct = cfg.get("star_penetration_min_pct", 0.5)

    for i in range(max(cfg["trend_lookback"], 2), n):
        atr_val = d["atr"].iloc[i - 2]
        if pd.isna(atr_val) or atr_val <= 0:
            continue
        c1, c2, c3 = d.iloc[i - 2], d.iloc[i - 1], d.iloc[i]
        g1 = compute_candle_geometry(c1["open"], c1["high"], c1["low"], c1["close"])
        g2 = compute_candle_geometry(c2["open"], c2["high"], c2["low"], c2["close"])
        g3 = compute_candle_geometry(c3["open"], c3["high"], c3["low"], c3["close"])
        trend = _trend_before(df, i - 2, cfg["trend_lookback"])

        if g1.body_size < cfg["dark_cloud_candle1_min_atr_multiple"] * atr_val:
            continue
        # ستاره (کندل میانی): بدنه‌ی کوچک، با گپ از کندل اول
        star_small = pd.notna(g2.body_to_range_ratio) and g2.body_size <= star_max_body_pct * g1.body_size

        if direction == "bullish":
            if trend != "downtrend" or not g1.is_bearish or not g3.is_bullish or not star_small:
                continue
            gapped_down = max(c2["open"], c2["close"]) <= g1.body_bottom
            midpoint = g1.body_bottom + 0.5 * g1.body_size
            penetrates = c3["close"] > g1.body_bottom + penetration_min_pct * g1.body_size
            if gapped_down and penetrates:
                events.append(CandlestickPatternEvent(
                    pattern_name="morning_star", category="three_candle", direction="bullish", type="reversal",
                    timeframe=timeframe, symbol=symbol, candle_indices=[i - 2, i - 1, i],
                    confidence=round(0.6 + 0.15 * (1 - g2.body_size / max(g1.body_size, 1e-9)), 3),
                    confirmation_status="confirmed",
                    evidence={"prior_trend": trend, "star_body_ratio": round(g2.body_size / max(g1.body_size, 1e-9), 2)},
                ))
        else:
            if trend != "uptrend" or not g1.is_bullish or not g3.is_bearish or not star_small:
                continue
            gapped_up = min(c2["open"], c2["close"]) >= g1.body_top
            penetrates = c3["close"] < g1.body_top - penetration_min_pct * g1.body_size
            if gapped_up and penetrates:
                events.append(CandlestickPatternEvent(
                    pattern_name="evening_star", category="three_candle", direction="bearish", type="reversal",
                    timeframe=timeframe, symbol=symbol, candle_indices=[i - 2, i - 1, i],
                    confidence=round(0.6 + 0.15 * (1 - g2.body_size / max(g1.body_size, 1e-9)), 3),
                    confirmation_status="confirmed",
                    evidence={"prior_trend": trend, "star_body_ratio": round(g2.body_size / max(g1.body_size, 1e-9), 2)},
                ))
    return events


def detect_morning_star(df, timeframe, symbol="", config=None) -> List[CandlestickPatternEvent]:
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    return _detect_star(df, timeframe, symbol, cfg, "bullish")


def detect_evening_star(df, timeframe, symbol="", config=None) -> List[CandlestickPatternEvent]:
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    return _detect_star(df, timeframe, symbol, cfg, "bearish")


def detect_all(
    df: pd.DataFrame, timeframe: str, symbol: str = "", config: Optional[dict] = None
) -> List[CandlestickPatternEvent]:
    """نقطه‌ی ورود واحد — همه‌ی الگوهای این موتور را روی df اجرا می‌کند."""
    events: List[CandlestickPatternEvent] = []
    events += detect_hammer_family(df, timeframe, symbol, config)
    events += detect_doji_family(df, timeframe, symbol, config)
    events += detect_harami(df, timeframe, symbol, config)
    events += detect_dark_cloud_cover(df, timeframe, symbol, config)
    events += detect_three_soldiers_crows(df, timeframe, symbol, config)
    events += detect_three_methods(df, timeframe, symbol, config)
    events += detect_engulfing(df, timeframe, symbol, config)
    events += detect_marubozu(df, timeframe, symbol, config)
    events += detect_piercing_line(df, timeframe, symbol, config)
    events += detect_morning_star(df, timeframe, symbol, config)
    events += detect_evening_star(df, timeframe, symbol, config)
    return events
