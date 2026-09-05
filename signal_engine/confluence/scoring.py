# -*- coding: utf-8 -*-
"""
signal_engine.confluence.scoring
===================================
پیاده‌سازی بخش ۵ سند اصلی + بخش ۳ سند اصلاحی (Architectural Addendum):
امتیازدهی هم‌گرایی (confluence_score) با نرمال‌سازی ریاضی صریح.

طبق بخش ۳ سند اصلاحی: بدون یک مخرج نرمال‌سازی صریح، اندازه‌ی
weighted_agreement_score به تعداد موتورهایی که در آن پنجره‌ی همبستگی
اتفاقاً رویداد تولید کرده‌اند بستگی دارد — اگر موتوری خراب/غایب باشد،
وزن‌های خام نرمال‌نشده باعث «گرسنگی سیگنال» یا «رانش امتیاز» بین
بک‌تست‌های مختلف می‌شود. فرمول جدید:

    weighted_agreement_score = Σ(W_i × C_i for i in E_agree) / Σ(W_j for j in E_active)

که E_active مجموعه‌ی موتورهای *واقعاً فعال* در همین context است (نه کل
موتورهای کانفیگ‌شده‌ی پروژه)، و E_agree زیرمجموعه‌ای از آن‌هاست که جهتشان
با anchor یکی است. این تضمین می‌کند صرف‌نظر از این‌که ۲، ۳ یا هر ۵ موتور
مشارکت کرده باشند، quantity قبل از کسر جریمه‌ها همیشه در [0,1] است.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from signal_engine.confluence.correlation import ConfluenceContext

DEFAULT_ENGINE_WEIGHTS = {
    "KLSDE": 1.0, "SDE": 0.9, "CPDE": 0.5, "PRE": 0.6, "MCDE": 0.4,
}

DEFAULT_PENALTIES = {
    "directional_conflict": 0.25,
    "regime_mismatch": 0.2,
    "counter_trend_alignment": 0.15,
    "stale_anchor": 0.1,
    # طبق بخش ۴.۲ سند اصلاحی: واگرایی از رژیم کلان BTC (وقتی BTC در
    # markdown/BOS نزولی ۱۵m است ولی یک آلت‌کوین سیگنال صعودی می‌دهد).
    "systemic_macro_divergence": 0.20,
}


@dataclass
class ScoredContext:
    context: ConfluenceContext
    confluence_score: float
    directional_tally: dict
    penalties_applied: List[dict] = field(default_factory=list)
    weighted_agreement_score: float = 0.0  # قبل از کسر جریمه‌ها — برای شفافیت/آدیت (بخش ۳.۳ سند اصلاحی)
    active_engines: List[str] = field(default_factory=list)


def _anchor_confirmation_is_stale(anchor) -> bool:
    payload = anchor.native_payload
    status = getattr(payload, "confirmation_status", None) or getattr(payload, "status", None)
    return status in ("unconfirmed", "pending")


def _regime_mismatch(context: ConfluenceContext) -> bool:
    """طبق سند بخش ۵.۳: فاز distribution + anchor صعودی، یا accumulation +
    anchor نزولی → جریمه (این دو فاز مستعد شکست کاذب‌اند، طبق MCDE بخش ۴).
    """
    anchor_dir = context.anchor.direction
    for s in context.supporting_events:
        if s.source_engine == "MCDE" and s.native_event_type.startswith("macro_"):
            phase = s.native_event_type.replace("macro_", "")
            if phase == "distribution" and anchor_dir == "bullish":
                return True
            if phase == "accumulation" and anchor_dir == "bearish":
                return True
    return False


def _counter_trend_alignment(context: ConfluenceContext) -> bool:
    """طبق سند: اگر یک رویداد SDE پشتیبان با تگ هم‌راستایی counter_trend
    وجود داشته باشد (از AlignedContext که در signal_engine.swing_structure
    تولید می‌شود)، جریمه اعمال شود. چون AlignedContext مستقیماً envelope
    نمی‌شود (طبق طراحی این پروژه، به‌عنوان متادیتای همراه SDE ذخیره
    می‌شود)، این تابع فیلد اختیاری alignment را در native_payload بررسی
    می‌کند اگر بالادستی آن را ضمیمه کرده باشد.
    """
    for s in context.supporting_events:
        if s.source_engine == "SDE":
            alignment = getattr(s.native_payload, "alignment", None)
            if alignment == "counter_trend":
                return True
    return False


def _systemic_macro_divergence(context: ConfluenceContext, btc_context: dict = None) -> bool:
    """طبق بخش ۴.۲ سند اصلاحی: اگر context برای BTC خودش نیست، و anchor
    صعودی است در حالی که فاز کلان BTC (MCDE) در markdown است یا ساختار
    ۱۵m آن (SDE) اخیراً BOS نزولی داده، جریمه اعمال شود (و برعکس برای
    anchor نزولی + BTC در markup/BOS صعودی).

    btc_context (اختیاری، از بیرون تزریق می‌شود — طبق طراحی این پروژه که
    هیچ موتوری نباید نمادهای دیگر را مستقیماً بخواند): دیکشنری با کلیدهای
    'macro_phase' (str) و 'structure_direction_15m' (str|None).
    """
    if not btc_context or context.symbol.upper().startswith("BTC"):
        return False
    anchor_dir = context.anchor.direction
    macro_phase = btc_context.get("macro_phase")
    structure_dir = btc_context.get("structure_direction_15m")

    if anchor_dir == "bullish" and (macro_phase == "markdown" or structure_dir == "bearish"):
        return True
    if anchor_dir == "bearish" and (macro_phase == "markup" or structure_dir == "bullish"):
        return True
    return False


def score_context(
    context: ConfluenceContext,
    engine_weights: dict = None,
    penalties: dict = None,
    btc_context: dict = None,
) -> ScoredContext:
    weights = {**DEFAULT_ENGINE_WEIGHTS, **(engine_weights or {})}
    pen = {**DEFAULT_PENALTIES, **(penalties or {})}

    anchor_dir = context.anchor.direction
    tally = {"bullish": 0, "bearish": 0, "neutral": 0}
    tally[anchor_dir] = tally.get(anchor_dir, 0) + 1

    # --- طبق بخش ۳.۲ سند اصلاحی: تجمیع به‌ازای «موتور فعال»، نه به‌ازای
    # رویداد خام. اگر یک موتور چند رویداد هم‌جهت با anchor دارد، بهترین
    # (بیشترین اطمینان) آن‌ها نماینده‌ی آن موتور در صورت‌کسر می‌شود. ---
    best_agreeing_confidence_by_engine = {context.anchor.source_engine: context.anchor.confidence}
    active_engines = {context.anchor.source_engine}
    penalties_applied = []
    total_penalty = 0.0

    for ev in context.supporting_events:
        tally[ev.direction] = tally.get(ev.direction, 0) + 1
        active_engines.add(ev.source_engine)
        if ev.direction == anchor_dir:
            prev = best_agreeing_confidence_by_engine.get(ev.source_engine, 0.0)
            best_agreeing_confidence_by_engine[ev.source_engine] = max(prev, ev.confidence)
        elif ev.direction != "neutral":
            penalty_amount = pen["directional_conflict"] * ev.confidence
            total_penalty += penalty_amount
            penalties_applied.append({"type": "directional_conflict", "amount": round(penalty_amount, 3), "source": ev.envelope_id})

    numerator = sum(
        weights.get(engine, 0.3) * conf
        for engine, conf in best_agreeing_confidence_by_engine.items()
    )
    denominator = sum(weights.get(engine, 0.3) for engine in active_engines)
    weighted_agreement_score = numerator / max(denominator, 1e-9)
    # طبق بخش ۳.۳ سند اصلاحی: تضمین ریاضی [0,1] پیش از کسر جریمه‌ها —
    # چون هر C_i در [0,1] است و این یک میانگین وزن‌دار از زیرمجموعه‌ای از
    # همان موتورهاست، سقف اضافی دیگری لازم نیست؛ فقط برای اطمینان clamp می‌شود.
    weighted_agreement_score = max(0.0, min(1.0, weighted_agreement_score))

    if _regime_mismatch(context):
        total_penalty += pen["regime_mismatch"]
        penalties_applied.append({"type": "regime_mismatch", "amount": pen["regime_mismatch"]})

    if _counter_trend_alignment(context):
        total_penalty += pen["counter_trend_alignment"]
        penalties_applied.append({"type": "counter_trend_alignment", "amount": pen["counter_trend_alignment"]})

    if _anchor_confirmation_is_stale(context.anchor):
        total_penalty += pen["stale_anchor"]
        penalties_applied.append({"type": "stale_anchor", "amount": pen["stale_anchor"]})

    if _systemic_macro_divergence(context, btc_context):
        total_penalty += pen["systemic_macro_divergence"]
        penalties_applied.append({"type": "systemic_macro_divergence", "amount": pen["systemic_macro_divergence"]})

    score = max(0.0, min(1.0, weighted_agreement_score - total_penalty))

    return ScoredContext(
        context=context, confluence_score=round(score, 3), directional_tally=tally,
        penalties_applied=penalties_applied,
        weighted_agreement_score=round(weighted_agreement_score, 3),
        active_engines=sorted(active_engines),
    )


def score_all(
    contexts: List[ConfluenceContext],
    engine_weights: dict = None,
    penalties: dict = None,
    btc_context: dict = None,
) -> List[ScoredContext]:
    return [score_context(c, engine_weights, penalties, btc_context) for c in contexts]
