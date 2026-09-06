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
from signal_engine.swing_structure.swings import detect_swings
from signal_engine.key_level_setup.levels import compute_key_levels

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



def _execution_target_levels(timeframe: str, is_buy: bool, level_set):
    """سطوح هدف اجرایی را از سطوح مناسب تایم‌فریم انتخاب می‌کند.

    5m/15m: PDH/PDL سپس PWH/PWL سپس PMH/PML.
    1h/4h: PWH/PWL سپس PMH/PML.
    سطوح P1H/P4H برای confluence مفیدند اما نباید صرفاً به‌عنوان نزدیک‌ترین
    TP باعث فشرده‌شدن RR معامله‌ی تایم‌فریم پایین شوند.
    """
    if level_set is None:
        return []
    levels = getattr(level_set, "levels", {}) or {}
    if timeframe in ("5min", "15min"):
        names = ["PDH", "PWH", "PMH"] if is_buy else ["PDL", "PWL", "PML"]
    else:
        names = ["PWH", "PMH"] if is_buy else ["PWL", "PML"]
    out = []
    for name in names:
        info = levels.get(name)
        price = getattr(info, "price", None) if info is not None else None
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            price = None
        if price is not None and np.isfinite(price):
            out.append((name, price))
    return out



def _b5_retest_swing_stop(signal: TradeSignal, df: pd.DataFrame, entry: float, is_buy: bool, atr: float, timeframe: str = "5min"):
    """Return (stop, swing_price) for the B5/S5 breakout-retest variant.

    The swing is restricted to candles between the confirmed breakout and the
    confirmed resumption, so an old HTF swing cannot silently become the SL.
    Falls back to the recorded retest candle when the swing detector has no
    usable point.
    """
    try:
        evidence = dict(signal.reference_levels.get("klsde_setup_evidence") or {})
        if not evidence.get("b5_variant"):
            return None, None
        start = int(evidence.get("breakout_confirm_index"))
        end = int(evidence.get("resumption_index"))
        retest_idx = int(evidence.get("retest_swing_index"))
        if start < 0 or end < start or end >= len(df):
            return None, None
        # The retest swing must be before the confirmation candle.
        retest_end = min(max(retest_idx, start), end - 1) if end > start else start
        if retest_end < start:
            return None, None
        segment = df.iloc[start:retest_end + 1]
        if segment.empty:
            return None, None

        # V16: the B5/S5 stop must use the project's confirmed swing engine,
        # not simply the absolute low/high of the whole retest segment.
        # This prevents one noisy wick from silently becoming the structural
        # stop.  A swing is eligible only if it was confirmed no later than
        # the B5/S5 resumption candle (strict no-lookahead boundary).
        swing_cfg = dict((signal.reference_levels.get("swing_structure_config") or evidence.get("swing_structure_config") or {}))
        try:
            all_swings = detect_swings(
                df.reset_index(drop=True),
                timeframe=timeframe,
                symbol=getattr(signal, "symbol", ""),
                config_overrides=swing_cfg,
            )
        except Exception:
            all_swings = []

        wanted_type = "swing_low" if is_buy else "swing_high"
        eligible = [
            s for s in all_swings
            if s.type == wanted_type
            and s.status == "confirmed"
            and s.confirmed_at_index is not None
            and int(s.confirmed_at_index) <= end
            and start <= int(s.candle_index) <= retest_end
            and s.quality_score is not None
            and float(s.quality_score) >= float(swing_cfg.get("b5_min_swing_quality", 45.0))
        ]

        # Prefer a significant swing. Confirmed-but-not-significant is a
        # controlled fallback; weak swings are never used for B5/S5 SL.
        significant = [s for s in eligible if s.quality_label == "significant"]
        pool = significant or eligible
        if pool:
            chosen = min(pool, key=lambda s: abs(int(s.candle_index) - retest_idx))
            swing_price = float(chosen.price)
            swing_quality = float(chosen.quality_score)
            swing_label = chosen.quality_label
            swing_index = int(chosen.candle_index)
        else:
            # Strict V16 rule: a B5/S5 structural SL is never allowed to be
            # created from an unclassified wick/extreme. If no confirmed
            # quality swing exists by the resumption boundary, let the caller
            # fall back to its normal structural/ATR stop logic instead.
            evidence["b5_sl_swing_source"] = "no_eligible_confirmed_swing"
            evidence["b5_sl_lookahead_safe"] = True
            signal.reference_levels["klsde_setup_evidence"] = evidence
            return None, None

        if not np.isfinite(swing_price):
            return None, None
        buffer = max(float(atr) * 0.25, abs(swing_price) * 0.001)
        stop = swing_price - buffer if is_buy else swing_price + buffer
        if (is_buy and stop >= entry) or ((not is_buy) and stop <= entry):
            return None, None

        # Attach auditable selection metadata to the signal evidence.
        evidence["b5_sl_swing_source"] = swing_label
        evidence["b5_sl_swing_index"] = swing_index
        evidence["b5_sl_swing_quality_score"] = swing_quality
        evidence["b5_sl_swing_quality_label"] = swing_label
        evidence["b5_sl_lookahead_safe"] = True
        signal.reference_levels["klsde_setup_evidence"] = evidence
        return float(stop), float(swing_price)
    except Exception:
        return None, None


def _construct_entry_sl_tp(
    signal: TradeSignal,
    df: pd.DataFrame,
    live_price: Optional[float] = None,
    sl_atr_multiple: float = 1.5,
    tp_atr_multiple: float = 3.0,
    timeframe: str = "5min",
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
    b5_stop, b5_swing = _b5_retest_swing_stop(signal, df, entry, is_buy, atr, timeframe=timeframe)
    # KLSDE carries the complete Key-Level map. Prefer the nearest valid
    # structural target in the trade direction (1H/4H/DAY/WEEK/MONTH), then
    # fall back to an explicit measured target if one exists. This keeps TP
    # tied to the same levels that triggered the setup instead of defaulting
    # to a blind ATR target whenever measured_move_target is absent.
    # روی 5m/15m، نزدیک‌ترین P1H/P4H نباید به‌صورت خودکار TP شود.
    # این سطوح می‌توانند confluence/شاهد باشند، اما هدف اجرایی باید از
    # ساختار مناسب تایم‌فریم گرفته شود تا RR مصنوعی به حوالی 1R فشرده نشود.
    level_set = None
    try:
        level_set = compute_key_levels(df, symbol=getattr(signal, "symbol", ""))
    except Exception:
        pass
    target_candidates = _execution_target_levels(timeframe, is_buy, level_set)
    ahead_candidates = [(name, price) for name, price in target_candidates
                        if (is_buy and price > entry) or ((not is_buy) and price < entry)]
    if ahead_candidates:
        # Keep the full execution-timeframe ladder. The nearest level is a
        # useful TP1, but the planner should not collapse TP3/RR to ~1R when
        # higher valid structural levels are available.
        structural_target_name, structural_target_ref = ahead_candidates[-1]
    else:
        structural_target_ref = _best_reference_price(signal, ["measured_move_target"])
        structural_target_name = "measured_move_target" if structural_target_ref is not None else None

    if b5_stop is not None:
        sl = b5_stop
    elif structural_stop_ref is not None:
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

    return {"entry": entry, "sl": sl, "tp": tp, "target_level_name": structural_target_name,
            "target_level_source": "execution_timeframe_structure" if structural_target_name else None,
            "target_level_candidates": ahead_candidates,
            "swing_level": b5_swing, "swing_sl_buffer": (abs(b5_swing - b5_stop) if b5_stop is not None and b5_swing is not None else None),
            "swing_quality_score": (dict(signal.reference_levels.get("klsde_setup_evidence") or {}).get("b5_sl_swing_quality_score")),
            "swing_quality_label": (dict(signal.reference_levels.get("klsde_setup_evidence") or {}).get("b5_sl_swing_quality_label")),
            "swing_index": (dict(signal.reference_levels.get("klsde_setup_evidence") or {}).get("b5_sl_swing_index")),
            "sl_mode": "b5_retest_swing" if b5_stop is not None else "structural_or_atr"}


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
    # Prefer the strongest active KLSDE setup. B5/S5 is first-class, but we
    # still let confluence score decide when several levels interact at once.
    # This preserves the "check every key level" behavior while preventing a
    # merely newer weak level from replacing a stronger confirmed setup.
    setup_priority = {"B5": 2, "S5": 2, "BOF": 1, "TST": 1, "BPB": 1, "BP": 1, "CPB": 1}
    best_signal = max(
        active_signals,
        key=lambda s: (setup_priority.get(s.anchor_native_event_type, 0), s.confluence_score, s.created_at_index),
    )

    plan_prices = _construct_entry_sl_tp(best_signal, df, live_price=live_price, timeframe=timeframe)
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
        "target_level_name": plan_prices.get("target_level_name"),
        "target_level_source": plan_prices.get("target_level_source"),
        "target_level_candidates": plan_prices.get("target_level_candidates", []),
        "swing_level": plan_prices.get("swing_level"),
        "swing_sl_buffer": plan_prices.get("swing_sl_buffer"),
        "sl_mode": plan_prices.get("sl_mode"),
        "klsde_setup_evidence": best_signal.reference_levels.get("klsde_setup_evidence", {}),
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
