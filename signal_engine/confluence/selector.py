# -*- coding: utf-8 -*-
"""
signal_engine.confluence.selector
====================================
پیاده‌سازی بخش ۶ و ۷ سند: از بین همه‌ی ConfluenceContext های امتیازدهی‌شده
(ScoredContext)، حداکثر یک TradeSignal فعال به‌ازای هر نماد در هر لحظه
انتخاب می‌شود — با قوانین صریح تقویت/رد/جایگزینی (نه صرفاً بیشترین امتیاز).

این نسخه batch/replay است: کل جریان زمانی رویدادها را یک‌بار پیمایش
می‌کند و لاگ کامل سیگنال‌ها (فعال/به‌روزشده/بازنشسته/منقضی) را تولید
می‌کند — دقیقاً هدف «قابل بازپخش برای بک‌تست» طبق سند بخش ۲.۱.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

from signal_engine.confluence.scoring import ScoredContext

SignalStatus = Literal["active", "updated", "retired", "expired", "invalidated"]

DEFAULT_MIN_CONFLUENCE_SCORE_TO_EMIT = 0.6
DEFAULT_CONFLICT_OVERRIDE_MARGIN = 0.15
DEFAULT_EXPIRY_MULTIPLE_OF_ANCHOR_WINDOW = 3


@dataclass
class TradeSignal:
    signal_id: str
    symbol: str
    direction: str
    confluence_score: float
    created_at_index: int
    expires_at_index: int
    status: SignalStatus
    anchor_source_engine: str
    anchor_native_event_type: str
    supporting_evidence: List[dict] = field(default_factory=list)
    penalties_applied: List[dict] = field(default_factory=list)
    reference_levels: dict = field(default_factory=dict)
    # طبق بخش ۴.۲.۲ سند اصلاحی: متادیتای طبقه‌بندی دارایی/ریسک سیستمیک —
    # هرگز برای تصمیم‌گیری معاملاتی توسط این پروژه استفاده نمی‌شود؛ فقط
    # به لایه‌ی اجرا (بیرون از این پروژه) اجازه می‌دهد محدودیت‌های
    # پرتفوی/خوشه را پیاده کند (بخش ۴.۲.۳).
    taxonomy: dict = field(default_factory=dict)
    history: List[dict] = field(default_factory=list)  # لاگ رویدادهای چرخه‌ی عمر (created/updated/retired/expired)

    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id, "symbol": self.symbol, "direction": self.direction,
            "confluence_score": self.confluence_score,
            "created_at_index": self.created_at_index, "expires_at_index": self.expires_at_index,
            "status": self.status,
            "anchor": {"source_engine": self.anchor_source_engine, "setup_type": self.anchor_native_event_type},
            "supporting_evidence": self.supporting_evidence,
            "penalties_applied": self.penalties_applied,
            "reference_levels": self.reference_levels,
            "taxonomy": self.taxonomy,
        }


def _extract_reference_levels(context) -> dict:
    """طبق سند، بخش ۷: فقط سطوح از قبل محاسبه‌شده توسط موتورهای پایین‌دستی
    را forward می‌کند — هرگز خودش سطح جدید حساب نمی‌کند.
    """
    payload = context.anchor.native_payload
    levels = {}
    kl = getattr(payload, "key_levels", None)
    if kl:
        levels.update(kl)
    lvl_price = getattr(payload, "level_price", None)
    if lvl_price is not None:
        levels["klsde_level_price"] = lvl_price
    return levels


def _build_taxonomy(sc: ScoredContext, asset_taxonomy: Optional[dict]) -> dict:
    """طبق بخش ۴.۲.۲ سند اصلاحی: taxonomy ثابت دارایی (asset_class/
    sector/btc_correlation_30d) از بیرون تزریق می‌شود (چون این پروژه
    نباید طبقه‌بندی دارایی یا همبستگی را خودش محاسبه کند — این داده‌ای
    است که در جای دیگری از سیستم نگه‌داری می‌شود)؛ فقط macro_regime_aligned
    از روی penalties_applied همین context محاسبه می‌شود.
    """
    base = dict(asset_taxonomy or {})
    divergence_flagged = any(p.get("type") == "systemic_macro_divergence" for p in sc.penalties_applied)
    base["macro_regime_aligned"] = not divergence_flagged
    return base


def select_signals(
    scored_contexts: List[ScoredContext],
    min_confluence_score_to_emit: float = DEFAULT_MIN_CONFLUENCE_SCORE_TO_EMIT,
    conflict_override_margin: float = DEFAULT_CONFLICT_OVERRIDE_MARGIN,
    expiry_multiple_of_anchor_window: int = DEFAULT_EXPIRY_MULTIPLE_OF_ANCHOR_WINDOW,
    default_anchor_window_bars: int = 20,
    asset_taxonomy: Optional[dict] = None,
) -> List[TradeSignal]:
    """پیمایش زمانی همه‌ی زمینه‌های امتیازدهی‌شده (به ترتیب ایندکس anchor)
    و اعمال قوانین mutual exclusion بخش ۶.۲ سند. خروجی: کل تاریخچه‌ی
    سیگنال‌ها (هر ورودی وضعیت نهایی یک signal_id را نشان می‌دهد؛ history
    داخل هر TradeSignal چرخه‌ی کامل عمرش را ثبت می‌کند).
    """
    eligible = sorted(
        [sc for sc in scored_contexts if sc.confluence_score >= min_confluence_score_to_emit],
        key=lambda sc: sc.context.anchor.event_index,
    )

    active_by_symbol: Dict[str, TradeSignal] = {}
    all_signals: List[TradeSignal] = []
    counter = 0

    for sc in eligible:
        ctx = sc.context
        symbol = ctx.symbol
        anchor_index = ctx.anchor.event_index
        active = active_by_symbol.get(symbol)

        # طبق سند بخش ۶.۳: منقضی‌کردن سیگنال‌های قدیمی قبل از تصمیم‌گیری جدید
        if active is not None and anchor_index > active.expires_at_index:
            active.status = "expired"
            active.history.append({"event": "signal_expired", "at_index": anchor_index})
            active_by_symbol.pop(symbol, None)
            active = None

        if active is None:
            counter += 1
            sig = TradeSignal(
                signal_id=f"sig_{counter:06d}", symbol=symbol, direction=ctx.anchor.direction,
                confluence_score=sc.confluence_score, created_at_index=anchor_index,
                expires_at_index=anchor_index + default_anchor_window_bars * expiry_multiple_of_anchor_window,
                status="active", anchor_source_engine=ctx.anchor.source_engine,
                anchor_native_event_type=ctx.anchor.native_event_type,
                supporting_evidence=[e.to_dict() for e in ctx.supporting_events],
                penalties_applied=sc.penalties_applied,
                reference_levels=_extract_reference_levels(ctx),
                taxonomy=_build_taxonomy(sc, asset_taxonomy),
            )
            sig.history.append({"event": "signal_created", "at_index": anchor_index})
            active_by_symbol[symbol] = sig
            all_signals.append(sig)
            continue

        if ctx.anchor.direction == active.direction:
            # طبق سند: شواهد تقویت‌کننده — سیگنال فعال را به‌روزرسانی کن، سیگنال جدید نساز
            active.confluence_score = max(active.confluence_score, sc.confluence_score)
            active.supporting_evidence.extend(e.to_dict() for e in ctx.supporting_events)
            active.taxonomy = _build_taxonomy(sc, asset_taxonomy or active.taxonomy)
            active.status = "updated"
            active.history.append({"event": "signal_updated", "at_index": anchor_index, "reinforcing_context": ctx.context_id})
            continue

        # جهت مخالف — طبق سند بخش ۶.۲: فقط اگر امتیاز جدید به‌اندازه‌ی کافی
        # (conflict_override_margin) از سیگنال فعال بیشتر باشد، جایگزین کن.
        if sc.confluence_score - active.confluence_score >= conflict_override_margin:
            active.status = "retired"
            active.history.append({"event": "signal_retired", "at_index": anchor_index, "reason": "superseded_by_conflicting_signal"})
            active_by_symbol.pop(symbol, None)

            counter += 1
            sig = TradeSignal(
                signal_id=f"sig_{counter:06d}", symbol=symbol, direction=ctx.anchor.direction,
                confluence_score=sc.confluence_score, created_at_index=anchor_index,
                expires_at_index=anchor_index + default_anchor_window_bars * expiry_multiple_of_anchor_window,
                status="active", anchor_source_engine=ctx.anchor.source_engine,
                anchor_native_event_type=ctx.anchor.native_event_type,
                supporting_evidence=[e.to_dict() for e in ctx.supporting_events],
                penalties_applied=sc.penalties_applied,
                reference_levels=_extract_reference_levels(ctx),
                taxonomy=_build_taxonomy(sc, asset_taxonomy),
            )
            sig.history.append({"event": "signal_created", "at_index": anchor_index, "superseded": active.signal_id})
            active_by_symbol[symbol] = sig
            all_signals.append(sig)
        else:
            # طبق سند: نه رد کن نه جایگزین — فقط یک پرچم احتیاط لاگ کن
            active.history.append({
                "event": "signal_caution_flag", "at_index": anchor_index,
                "conflicting_context": ctx.context_id, "conflicting_score": sc.confluence_score,
            })

    return all_signals
