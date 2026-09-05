# -*- coding: utf-8 -*-
"""
signal_engine.bridge
======================
پل سازگاری بین موتور جدید (signal_engine.confluence) و رابط قدیمی
strategy.py که bot.py/backtest.py به آن وابسته‌اند.

طراحی عمدی: این ماژول entry/sl/tp نهایی را می‌سازد و آن‌ها را دقیقاً در
همان قالب دیکشنری «best» قدیمی (که evaluate_scenarios در
pdh_eq_pdl_engine.py تولید می‌کرد) برمی‌گرداند — تا تمام فیوزهای ایمنی
موجود در strategy.build_trade_plan (سقف SL بر حسب ATR، حداقل R:R، حداقل
امتیاز، چک «هدف واقعاً جلوتر از ورود») دقیقاً همان‌طور که هستند روی
خروجی موتور جدید هم اجرا شوند — بدون این‌که این فیوزها را در جای دیگری
تکرار یا دور بزنیم.

طبق سند Unified Confluence Layer، بخش ۷: TradeSignal فقط reference_levels
خام (از موتورهای پایین‌دستی) را forward می‌کند و خودش حد سود/ضرر تعیین
نمی‌کند — ساخت entry/sl/tp واقعی وظیفه‌ی همین «لایه‌ی Setup» (که در این
پروژه strategy.py/bridge.py است) است، دقیقاً طبق مرز مسئولیتی که در آن
سند صراحتاً مشخص شده.

فعال‌سازی این پل کاملاً پشت یک فلگ کانفیگ (`use_new_signal_engine`) است.
طبق تأیید صریح کاربر، این فلگ اکنون پیش‌فرض `True` است و موتور جدید
(KLSDE/Confluence) به‌صورت پیش‌فرض روی همه‌ی سشن‌ها فعال است؛ موتور قدیمی
(evaluate_scenarios در pdh_eq_pdl_engine.py) دیگر به‌صورت پیش‌فرض
فراخوانی نمی‌شود، هرچند فایل pdh_eq_pdl_engine.py به‌خاطر توابع مشترک
سطح/روند HTF (structural_htf_trend، compute_prev_*_levels) که هر دو
مسیر به آن‌ها وابسته‌اند حذف نشده است.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from signal_engine.common.atr import compute_atr, latest_atr
from signal_engine.confluence.layer import generate_trade_signals
from signal_engine.confluence.selector import TradeSignal
from signal_engine.confluence.invalidation import check_structural_invalidation

# طبق بخش ۲ سند اصلاحی (Architectural Addendum): برای این‌که بتوان در
# طول زمان (نه فقط در لحظه‌ی تولید سیگنال) قیمت را با سطح ابطال ساختاری
# مقایسه کرد، آخرین TradeSignal واقعی هر نماد این‌جا نگه داشته می‌شود.
# این state جداگانه از دیکشنری «best» قدیمی است که به strategy.py
# برمی‌گردد — چون آن دیکشنری فقط یک عکس لحظه‌ای است و نمی‌تواند
# status را در طول زمان mutate کند.
_ACTIVE_TRADE_SIGNALS: dict = {}


def _best_reference_price(signal: TradeSignal, key_candidates) -> Optional[float]:
    for k in key_candidates:
        v = signal.reference_levels.get(k)
        if v is not None and np.isfinite(v):
            return float(v)
    return None



def _nearest_ahead_level(signal: TradeSignal, entry: float, is_buy: bool) -> Optional[float]:
    levels = getattr(signal, "reference_levels", {}) or {}
    candidates = []
    for name, value in levels.items():
        if name == "klsde_level_price" or name in {"structural_stop_reference", "structural_target_reference"}:
            continue
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(price):
            continue
        if (is_buy and price > entry) or ((not is_buy) and price < entry):
            candidates.append((abs(price - entry), price))
    if not candidates:
        return None
    return min(candidates, key=lambda x: x[0])[1]

def _construct_entry_sl_tp(
    signal: TradeSignal,
    df: pd.DataFrame,
    live_price: Optional[float] = None,
    sl_atr_multiple: float = 1.5,
    tp_atr_multiple: float = 3.0,
) -> Optional[dict]:
    """طبق مرز مسئولیت سند USCL (بخش ۷): این تابع entry/sl/tp را از روی
    reference_levels خامِ همان موتوری که anchor بوده می‌سازد؛ اگر سطح
    ساختاری مناسبی در دسترس نبود، به ATR ساده فال‌بک می‌کند (سقف نهایی
    منطقی‌بودن SL/TP همچنان توسط فیوزهای build_trade_plan در strategy.py
    بررسی می‌شود، نه اینجا).
    """
    if df is None or df.empty:
        return None
    entry = float(live_price) if live_price is not None else float(df["close"].iloc[-1])
    atr = latest_atr(df, period=14)
    if not np.isfinite(atr) or atr <= 0:
        return None

    is_buy = signal.direction == "bullish"

    # اولویت سطح ساختاری: سطح شکسته‌شده‌ی KLSDE، سپس سطح breakout پرچم/مثلث،
    # سپس فال‌بک ATR ساده.
    structural_stop_ref = _best_reference_price(
        signal, ["klsde_level_price", "horizontal_level", "breakout_level", "rim_level"]
    )
    # KLSDE carries the complete Key-Level map. Prefer the nearest valid
    # structural target in the trade direction (1H/4H/DAY/WEEK/MONTH), then
    # fall back to an explicit measured target if one exists. This keeps TP
    # tied to the same levels that triggered the setup instead of defaulting
    # to a blind ATR target whenever measured_move_target is absent.
    structural_target_ref = _nearest_ahead_level(signal, entry, is_buy)
    if structural_target_ref is None:
        structural_target_ref = _best_reference_price(signal, ["measured_move_target"])

    if structural_stop_ref is not None:
        buffer = 0.3 * atr
        sl = structural_stop_ref - buffer if is_buy else structural_stop_ref + buffer
        # اگر سطح ساختاری عملاً از entry فاصله‌ی معناداری نداشت (خیلی نزدیک)،
        # به فال‌بک ATR سقوط کن تا risk_dist صفر/منفی نشود.
        if abs(entry - sl) < 0.2 * atr:
            sl = entry - sl_atr_multiple * atr if is_buy else entry + sl_atr_multiple * atr
    else:
        sl = entry - sl_atr_multiple * atr if is_buy else entry + sl_atr_multiple * atr

    if structural_target_ref is not None and (
        (is_buy and structural_target_ref > entry) or (not is_buy and structural_target_ref < entry)
    ):
        tp = structural_target_ref
    else:
        tp = entry + tp_atr_multiple * atr if is_buy else entry - tp_atr_multiple * atr

    return {"entry": entry, "sl": sl, "tp": tp}


def run_new_engine_as_best(
    df: pd.DataFrame,
    timeframe: str,
    symbol: str = "",
    config: Optional[dict] = None,
    live_price: Optional[float] = None,
    btc_context: Optional[dict] = None,
    asset_taxonomy: Optional[dict] = None,
    defer_quality_gate: bool = False,
) -> Optional[dict]:
    """نقطه‌ی ورود بریج: موتور جدید را اجرا می‌کند، آخرین سیگنال فعال را
    انتخاب می‌کند (اگر باشد) و آن را در قالب دیکشنری «best» قدیمی
    برمی‌گرداند — دقیقاً همان چیزی که evaluate_scenarios قدیم برمی‌گرداند
    (code, direction, entry, sl, tp, total_score, base_score, bonus, penalty).

    خروجی None یعنی «هیچ ستاپی» — دقیقاً مثل نسخه‌ی قدیمی.
    """
    signals = generate_trade_signals(
        df, timeframe, symbol=symbol, config=config,
        lookback_cap_bars=(config or {}).get("new_engine_lookback_cap_bars", 300),
        btc_context=btc_context, asset_taxonomy=asset_taxonomy,
        min_confluence_score_to_emit=0.0 if defer_quality_gate else None,
    )
    if not signals:
        return None

    # آخرین سیگنالی که هنوز active/updated است (نه retired/expired) —
    # طبق سند بخش ۶: فقط یک سیگنال فعال به‌ازای هر نماد باید در نظر گرفته شود.
    active_signals = [s for s in signals if s.status in ("active", "updated")]
    if not active_signals:
        return None
    best_signal = max(active_signals, key=lambda s: s.created_at_index)

    plan_prices = _construct_entry_sl_tp(best_signal, df, live_price=live_price)
    if plan_prices is None:
        return None

    # طبق بخش ۲.۲ سند اصلاحی: نام‌گذاری متعارف سطح ابطال ساختاری — این
    # همان sl واقعی است که همین بریج الان محاسبه کرد (نه یک سطح خام
    # موتور پیش از بافر ATR)، چون این دقیقاً همان چیزی است که اگر قیمت
    # از آن عبور کند، ستاپ دیگر معنایی ندارد.
    best_signal.reference_levels["structural_stop_reference"] = plan_prices["sl"]
    best_signal.reference_levels["structural_target_reference"] = plan_prices["tp"]
    _ACTIVE_TRADE_SIGNALS[symbol or best_signal.symbol] = best_signal

    direction = "BUY" if best_signal.direction == "bullish" else "SELL"
    score_100 = round(best_signal.confluence_score * 100)

    reason_text = (
        f"{direction} از ادغام سیگنال موتور جدید: anchor={best_signal.anchor_source_engine}:"
        f"{best_signal.anchor_native_event_type}، confluence_score={best_signal.confluence_score}، "
        f"{len(best_signal.supporting_evidence)} شاهد پشتیبان"
    )

    return {
        "code": f"{best_signal.anchor_source_engine}:{best_signal.anchor_native_event_type}",
        "direction": direction,
        "entry": plan_prices["entry"],
        "sl": plan_prices["sl"],
        "tp": plan_prices["tp"],
        "total_score": score_100,
        "base_score": score_100,
        "bonus": 0,
        "penalty": 0,
        "reasons": [reason_text],
        "level_label": best_signal.anchor_native_event_type,
        "level_name": best_signal.reference_levels.get("level_name"),
        "level_price": best_signal.reference_levels.get("klsde_level_price"),
        "signal_id": best_signal.signal_id,
        "n_supporting_evidence": len(best_signal.supporting_evidence),
        "taxonomy": best_signal.taxonomy,
    }


def check_signal_invalidation(symbol: str, current_price: float, time_index: int) -> Optional[dict]:
    """طبق بخش ۲ سند اصلاحی: نقطه‌ی ورودی که bot.py باید در حلقه‌ی
    پایش قیمت زنده (یا هر بار قبل از تلاش برای پر کردن سفارش) صدا بزند.
    اگر آخرین سیگنالِ ردیابی‌شده‌ی این نماد از مرز ابطال ساختاری‌اش عبور
    کرده باشد، رویداد signal_invalidated (طبق schema دقیق سند اصلاحی)
    را برمی‌گرداند و status سیگنال را به‌طور دائم "invalidated" می‌کند؛
    وگرنه None. این تابع هیچ سفارشی لغو نمی‌کند — طبق بخش ۲.۲.۴ سند
    اصلاحی، آن مسئولیت صریحاً به لایه‌ی اجرا (کد فراخواننده) واگذار شده.
    """
    signal = _ACTIVE_TRADE_SIGNALS.get(symbol)
    if signal is None:
        return None
    event = check_structural_invalidation(signal, current_price, time_index)
    return event.to_dict() if event else None
