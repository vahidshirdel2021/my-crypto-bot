# -*- coding: utf-8 -*-
"""
signal_engine.market_cycle.micro
===================================
پیاده‌سازی بخش ۵ سند: چرخه‌ی ۴موجی ال بروکس به‌عنوان یک ماشین‌حالت صریح
روی پرایمیتیوهای هندسه‌ی کندل (signal_engine.common.candle_geometry).

توالی کانونیک: trend_leg → pullback → trap_manipulation → breakout → ...
میان‌برهای مجاز (طبق سند ۵.۳): pullback → breakout ،trend_leg → trap_manipulation
میان‌برهای ممنوع: هر گذار روبه‌عقب (breakout → pullback و مشابه).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional

import pandas as pd

from signal_engine.common.candle_geometry import compute_candle_geometry

MicroStage = Literal["trend_leg", "pullback", "trap_manipulation", "breakout"]

DEFAULT_MICRO_CONFIG = {
    "large_body_threshold": 0.6,
    "long_shadow_threshold": 1.5,
    "doji_threshold": 0.15,
    "min_run_length": 2,  # حداقل تعداد کندل متوالی هم‌نوع برای این‌که یک «موج» تلقی شود
}

_CANONICAL_NEXT = {
    "trend_leg": {"pullback", "trap_manipulation"},  # trend_leg -> trap_manipulation میان‌بر مجاز
    "pullback": {"trap_manipulation", "breakout"},   # pullback -> breakout میان‌بر مجاز
    "trap_manipulation": {"breakout"},
    "breakout": {"trend_leg"},
}


@dataclass
class MicroStageEvent:
    id: str
    timeframe: str
    symbol: str
    stage: MicroStage
    start_index: int
    end_index: int
    confidence: float
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "timeframe": self.timeframe, "symbol": self.symbol, "stage": self.stage,
            "start_index": self.start_index, "end_index": self.end_index,
            "confidence": self.confidence, "evidence": self.evidence,
        }


def _primitive_to_stage_bucket(g, long_shadow_threshold: float) -> str:
    """پرایمیتیوهای هندسی خام را به دو گروه معنادار برای تشخیص موج نگاشت
    می‌دهد: 'directional' (پایه‌ی trend_leg/breakout) و 'corrective'
    (پایه‌ی pullback) و 'indecisive' (پایه‌ی trap_manipulation).

    نکته‌ی مهم: از g.primitive به‌تنهایی استفاده نمی‌شود چون آن فیلد
    (طبق تعریف صریح سند Candlestick Pattern Engine) اولویت را به «دوجی»
    می‌دهد حتی وقتی سایه‌ای هم وجود دارد (چون Gravestone/Dragonfly Doji
    دقیقاً همین شکل را دارند و CPDE باید آن‌ها را دوجی بشناسد). از منظر
    مدل ال بروکس اما، یک دوجیِ «یک‌طرفه» (یک سایه به‌وضوح غالب بر سایه‌ی
    دیگر — شکل چکش/سنگ‌قبر، یعنی یک رد کردن واضح) همان معنای اصلاحی
    (pullback) را دارد، در حالی که دوجیِ «متعادل» (دو سایه نزدیک به هم،
    شکل Long-Legged) یا کاملاً فشرده، بی‌تصمیمیِ واقعی (تله) است. این
    تفکیک این‌جا مستقل انجام می‌شود، بدون تغییر اولویت فیلد مشترک.
    """
    if g.primitive == "large_body":
        return "directional"
    if g.primitive == "long_shadow":
        return "corrective"
    if g.primitive == "doji":
        max_shadow = max(g.upper_shadow, g.lower_shadow)
        min_shadow = min(g.upper_shadow, g.lower_shadow)
        lopsided = max_shadow > 0 and min_shadow <= 0.3 * max_shadow
        if lopsided:
            return "corrective"
        return "indecisive"
    return "indecisive"  # small_body


def classify_micro_cycle(
    df: pd.DataFrame, timeframe: str, symbol: str = "", config: Optional[dict] = None,
) -> List[MicroStageEvent]:
    cfg = {**DEFAULT_MICRO_CONFIG, **(config or {})}
    d = df.reset_index(drop=True)
    n = len(d)
    if n < 3:
        return []

    # قدم ۱: هر کندل را به پرایمیتیو و سپس به یکی از سه سطل تبدیل کن.
    buckets = []
    directions = []
    for i in range(n):
        row = d.iloc[i]
        g = compute_candle_geometry(
            row["open"], row["high"], row["low"], row["close"],
            large_body_threshold=cfg["large_body_threshold"],
            long_shadow_threshold=cfg["long_shadow_threshold"],
            doji_threshold=cfg["doji_threshold"],
        )
        buckets.append(_primitive_to_stage_bucket(g, cfg["long_shadow_threshold"]))
        directions.append("bullish" if g.is_bullish else ("bearish" if g.is_bearish else "neutral"))

    # قدم ۲: بر اساس سطل‌ها، runهای متوالی هم‌سطل را پیدا کن (این پایه‌ی
    # اولیه‌ی تفکیک موج‌هاست؛ جهت اصلی هر run هم غالب‌ترین جهت آن است).
    runs = []
    i = 0
    while i < n:
        j = i
        while j + 1 < n and buckets[j + 1] == buckets[i]:
            j += 1
        runs.append({"bucket": buckets[i], "start": i, "end": j})
        i = j + 1

    events: List[MicroStageEvent] = []
    prior_stage: Optional[MicroStage] = None
    event_counter = 0
    trend_direction: Optional[str] = None  # جهت غالب آخرین trend_leg — برای تعیین جهت breakout/pullback

    for run in runs:
        length = run["end"] - run["start"] + 1
        if length < cfg["min_run_length"]:
            continue  # نویز خیلی کوتاه — به‌عنوان موج مستقل حساب نمی‌شود

        run_dirs = directions[run["start"]: run["end"] + 1]
        dominant_dir = max(set(run_dirs), key=run_dirs.count) if run_dirs else "neutral"

        if run["bucket"] == "directional":
            if prior_stage in (None, "breakout"):
                stage: MicroStage = "trend_leg"
                trend_direction = dominant_dir
            else:
                stage = "breakout"  # ادامه‌ی جهت اصلی بعد از pullback/trap
        elif run["bucket"] == "corrective":
            stage = "pullback"
        else:
            stage = "trap_manipulation"

        # اعتبارسنجی توالی: گذار غیرمجاز (رو‌به‌عقب) را رد نکن، فقط با
        # اطمینان پایین‌تر ثبت کن (طبق سند، این باید به‌جای رویداد ساختاری
        # جدید مطرح شود، نه یک ناهنجاری چرخه‌ی خرد — این‌جا محافظه‌کارانه
        # همچنان با confidence کمتر ثبت می‌شود تا اطلاعات از دست نرود).
        transition_ok = prior_stage is None or stage in _CANONICAL_NEXT.get(prior_stage, set()) or stage == prior_stage
        if stage == prior_stage:
            continue  # ادامه‌ی همان موج، نه موج جدید

        event_counter += 1
        confidence = 0.6 if transition_ok else 0.3
        evidence = {"prior_stage": prior_stage, "run_length": length, "dominant_direction": dominant_dir}
        if stage == "pullback" and prior_stage == "trend_leg":
            structure_intact = dominant_dir != trend_direction  # اصلاح باید خلاف جهت روند باشد
            evidence["structure_intact"] = bool(structure_intact)

        events.append(MicroStageEvent(
            id=f"micro_{timeframe}_{event_counter:05d}", timeframe=timeframe, symbol=symbol,
            stage=stage, start_index=run["start"], end_index=run["end"],
            confidence=confidence, evidence=evidence,
        ))
        prior_stage = stage

    return events
