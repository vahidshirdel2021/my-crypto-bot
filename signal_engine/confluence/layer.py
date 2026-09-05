# -*- coding: utf-8 -*-
"""
signal_engine.confluence.layer
=================================
نقطه‌ی ورود اصلی و یکپارچه‌ساز نهایی کل پروژه. تابع `generate_trade_signals`
هر ۵ موتور را روی df اجرا می‌کند، خروجی‌شان را نرمال‌سازی (adapters)،
هم‌بسته‌سازی (correlation)، امتیازدهی (scoring) و انتخاب نهایی (selector)
می‌کند و یک لیست از TradeSignal برمی‌گرداند.

این تابع دقیقاً همان چیزی است که در نهایت باید جایگزین
`strategy.get_signal_with_reason` شود (طبق نقشه‌ی راه مهاجرت).
"""

from __future__ import annotations

from typing import List, Optional

import pandas as pd

from signal_engine.pattern_recognition.detectors import detect_all as pre_detect_all
from signal_engine.swing_structure.swings import detect_swings
from signal_engine.swing_structure.structure import detect_structure_events
from signal_engine.market_cycle.macro import classify_macro_cycle
from signal_engine.market_cycle.micro import classify_micro_cycle
from signal_engine.candlestick.detectors import detect_all as cpde_detect_all
from signal_engine.key_level_setup.levels import compute_key_levels
from signal_engine.key_level_setup.interactions import detect_interactions
from signal_engine.key_level_setup.setups import classify_all as klsde_classify_all

from signal_engine.confluence.adapters import (
    adapt_pre_events, adapt_sde_structure_events, adapt_mcde_macro_events,
    adapt_mcde_micro_events, adapt_cpde_events, adapt_klsde_events,
)
from signal_engine.confluence.correlation import build_confluence_contexts
from signal_engine.confluence.scoring import score_all
from signal_engine.confluence.selector import select_signals, TradeSignal


def _shift_index(envelopes, offset: int):
    """ایندکس‌های نسبی-به-d_recent را به مقیاس df کامل برمی‌گرداند (فقط
    وقتی lookback_cap_bars فعال است offset > 0 می‌شود؛ در غیر این صورت
    بی‌اثر است).
    """
    if offset:
        for env in envelopes:
            env.event_index += offset
    return envelopes


def generate_trade_signals(
    df: pd.DataFrame,
    timeframe: str,
    symbol: str = "",
    config: Optional[dict] = None,
    lookback_cap_bars: Optional[int] = 800,
    btc_context: Optional[dict] = None,
    asset_taxonomy: Optional[dict] = None,
    min_confluence_score_to_emit: Optional[float] = None,
) -> List[TradeSignal]:
    """اجرای کامل خط لوله: ۵ موتور → آداپتور → همبستگی → امتیازدهی →
    انتخاب سیگنال. df باید ستون‌های استاندارد OHLC(V) داشته باشد و برای
    KLSDE ستون timestamp هم لازم است (برای محاسبه‌ی سطوح روز/هفته/ماه).

    lookback_cap_bars: طبق اندازه‌گیری واقعی عملکرد (نه حدس)، چهار موتور
    PRE/SDE/MCDE/CPDE برای صحت خودشان به چند صد کندل بیشتر نیاز ندارند —
    این‌ها فقط الگو/سوئینگ/فاز اخیر را می‌بینند، نه تاریخچه‌ی هفته‌ها. اما
    KLSDE برای محاسبه‌ی صحیح PWH/PWL/PMH/PML به کل تاریخچه نیاز دارد. پس
    این سقف *فقط* روی ورودی آن ۴ موتور اعمال می‌شود، نه روی df کامل که به
    KLSDE می‌رود — این تفکیک دقیقاً از پروفایل واقعی عملکرد (CPDE و PRE
    گلوگاه اصلی بودند با O(n) به ازای هر کندل، نه محاسبه‌ی سطوح که ارزان
    است) استخراج شده، نه یک حدس کلی. مقدار None یعنی بدون سقف (رفتار
    قدیمی/کامل، برای تست‌های دقیق‌تر یا داده‌ی کوچک).

    btc_context (طبق بخش ۴ سند اصلاحی — Architectural Addendum): دیکشنری
    اختیاری با کلیدهای 'macro_phase' و 'structure_direction_15m' که وضعیت
    فعلی BTC را نشان می‌دهد؛ اگر داده شود، جریمه‌ی واگرایی از رژیم کلان
    BTC (systemic_macro_divergence) روی نمادهای غیر-BTC اعمال می‌شود.
    این پروژه هرگز خودش نمادهای دیگر را نمی‌خواند — این دیکشنری باید از
    بیرون (مثلاً از اجرای همین pipeline روی BTCUSDT) تزریق شود.

    asset_taxonomy (طبق بخش ۴.۲.۲ سند اصلاحی): متادیتای ثابت دارایی
    (asset_class/sector/btc_correlation_30d) که مستقیماً در خروجی
    TradeSignal.taxonomy قرار می‌گیرد — این پروژه این مقادیر را خودش
    محاسبه نمی‌کند، فقط منتقل می‌کند.
    """
    cfg = config or {}
    d = df.reset_index(drop=True)
    d_recent = d.tail(lookback_cap_bars).reset_index(drop=True) if lookback_cap_bars else d

    # --- اجرای مستقل هر ۵ موتور (هرکدام black-box، بدون دانستن از بقیه) ---
    pre_events = pre_detect_all(d_recent, timeframe, symbol, cfg.get("pattern_recognition"))

    swings = detect_swings(d_recent, timeframe=timeframe, symbol=symbol, config_overrides=cfg.get("swing_structure"))
    structure_events = detect_structure_events(d_recent, swings, timeframe=timeframe, symbol=symbol)

    macro_events = classify_macro_cycle(d_recent, timeframe=timeframe, symbol=symbol, config=cfg.get("market_cycle_macro"))
    micro_events = classify_micro_cycle(d_recent, timeframe=timeframe, symbol=symbol, config=cfg.get("market_cycle_micro"))

    cpde_events = cpde_detect_all(d_recent, timeframe, symbol, cfg.get("candlestick"))

    klsde_signal_events = []
    if "timestamp" in d.columns:
        levels = compute_key_levels(d, symbol=symbol)  # عمداً df کامل (ارزان: طبق پروفایل، <0.3s)
        # پنجره‌ی برخورد را هم روی همان df کامل می‌سازیم چون یک برخورد با
        # PWH/PML ممکن است چند روز طول بکشد؛ اگر اینجا هم d_recent کوچک
        # استفاده می‌شد، بخشی از پنجره‌ی برخورد ناقص می‌ماند.
        windows = detect_interactions(d, levels, symbol=symbol, timeframe=timeframe)
        klsde_signal_events = klsde_classify_all(windows, d, timeframe=timeframe, config=cfg.get("key_level_setup"))

    # --- نرمال‌سازی (بخش ۳ سند) ---
    # نکته‌ی حیاتی: PRE/SDE/MCDE/CPDE روی d_recent (بریده‌شده) اجرا شدند، پس
    # ایندکس‌های خروجی‌شان نسبت به d_recent است، نه df کامل. برای این‌که
    # همبستگی (correlation.py) بتواند این رویدادها را با رویدادهای KLSDE
    # (که نسبت به df کامل ایندکس دارند) درست مقایسه کند، باید همان افستِ
    # برش را به عقب اضافه کنیم.
    index_offset = len(d) - len(d_recent)

    envelopes = []
    envelopes += _shift_index(adapt_pre_events(pre_events, timeframe, symbol), index_offset)
    envelopes += _shift_index(adapt_sde_structure_events(structure_events, timeframe, symbol), index_offset)
    envelopes += _shift_index(adapt_mcde_macro_events(macro_events, timeframe, symbol), index_offset)
    envelopes += _shift_index(adapt_mcde_micro_events(micro_events, timeframe, symbol), index_offset)
    envelopes += _shift_index(adapt_cpde_events(cpde_events, timeframe, symbol), index_offset)
    envelopes += adapt_klsde_events(klsde_signal_events, timeframe, symbol)  # قبلاً نسبت به df کامل است

    # --- همبستگی (بخش ۴) ---
    contexts = build_confluence_contexts(
        envelopes, correlation_window_max_bars=cfg.get("correlation_window_max_bars", 20)
    )

    # --- امتیازدهی (بخش ۵ + بخش ۴ سند اصلاحی: جریمه‌ی واگرایی از رژیم کلان BTC) ---
    scored = score_all(contexts, engine_weights=cfg.get("engine_weights"), penalties=cfg.get("penalties"),
                        btc_context=btc_context)

    # KLSDE is the sole SETUP/ENTRY anchor. The other engines remain active
    # as confirmation/evidence only; they are never allowed to create an
    # independent trade signal. This prevents PRE/SDE/CPDE/MCDE from bypassing
    # the required key-level interaction -> KLSDE setup sequence.
    scored = [sc for sc in scored if sc.context.anchor.source_engine == "KLSDE"]

    # --- انتخاب نهایی: فقط KLSDE می‌تواند Anchor/Trade Signal تولید کند. ---
    # SDE/PRE/CPDE/MCDE همچنان در scored/context حضور دارند و فقط به‌عنوان
    # supporting evidence/confluence استفاده می‌شوند؛ هیچ‌کدام به‌تنهایی
    # مجاز به ساخت Live Entry نیستند.
    klsde_anchored = [sc for sc in scored if sc.context.anchor.source_engine == "KLSDE"]
    signals = select_signals(
        klsde_anchored,
        min_confluence_score_to_emit=(cfg.get("min_confluence_score_to_emit", 0.6)
                                      if min_confluence_score_to_emit is None else min_confluence_score_to_emit),
        conflict_override_margin=cfg.get("conflict_override_margin", 0.15),
        asset_taxonomy=asset_taxonomy,
    )
    return signals
