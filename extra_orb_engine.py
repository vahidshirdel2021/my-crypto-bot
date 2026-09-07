# -*- coding: utf-8 -*-
"""
extra_orb_engine.py — استراتژی «اکسترا» (کاملاً مستقل از pdh_eq_pdl_engine.py)
================================================================================
این موتور به‌جای تکیه به یک سطح ثابت از پیش تعیین‌شده (PDH/PDL روزانه)،
بر پایه‌ی «زمان سشن + ساختار بازار» تصمیم می‌گیرد. یعنی می‌تواند وسط رنج
روزانه هم سیگنال بدهد — دقیقاً همان فرصت‌هایی که موتور PDH/EQ/PDL آن‌ها را
با گیت dead_zone_no_touch رد می‌کند.

منطق (کاملاً استاندارد در ادبیات ICT، نه اختراعی):

۱) Opening Range: در ابتدای هر Killzone (لندن یا نیویورک به وقت UTC)، رنج
   N دقیقه‌ی اول به‌عنوان محدوده مرجع سشن ثبت می‌شود.
۲) Judas Swing: بعد از شکل‌گیری Opening Range، قیمت یک طرف آن را می‌شکند
   (لیکوییدیتی سشن را می‌گیرد) — این «حرکت فریبنده»ی اولیه‌ی سشن است.
۳) MSS (Market Structure Shift): تأیید نهایی وقتی می‌آید که قیمت آخرین
   سوینگ مینور در جهت مخالف Judas Swing را بشکند — یعنی ساختار واقعاً عوض
   شده، نه فقط یک ویک تصادفی.
۴) ورود روی همان کندل تأییدیه (MSS)، با بونوس امتیاز اگر یک Fair Value Gap
   (نابرابری قیمتی سه‌کندلی) هم همراهش باشد.

خروجی این ماژول دقیقاً هم‌شکل خروجی evaluate_scenarios در
pdh_eq_pdl_engine.py است (dict با کلیدهای code/direction/total_score/...)
تا بتواند بدون تغییر در بقیه‌ی پروژه، جایگزین همان تابع در مسیر «استراتژی
اکسترا» شود.
"""

import numpy as np
import pandas as pd

from pdh_eq_pdl_engine import _ensure_atr, compute_swings  # noqa: reuse همان زیرساخت کیفی


EXTRA_ENGINE_DEFAULTS = {
    # بازه‌های Killzone به وقت UTC (استاندارد ICT). قابل تنظیم از strategy_config.
    "killzones": {
        "london": (7, 10),
        "new_york": (12, 15),
    },
    "orb_minutes": {"5min": 30, "15min": 60},
    "min_score_to_trade": 65.0,
    "min_rr": 1.20,
    "sweep_min_atr_ratio": 0.10,     # حداقل نفوذ ویک نسبت به ATR تا Judas Swing معتبر شمرده شود
    "sl_atr_buffer": 0.25,           # بافر اضافه پشت اکسترمم Judas Swing
    "fvg_bonus": 8.0,
    "volume_bonus": 6.0,
    "late_killzone_penalty_after_min": 45,  # بعد از این‌همه دقیقه از شروع KZ، جریمه دیرکرد
    "late_killzone_penalty": 10.0,
    "swing_lookback_fractal": 3,
}


def _merged_cfg(strategy_config):
    cfg = dict(EXTRA_ENGINE_DEFAULTS)
    if isinstance(strategy_config, dict):
        for k, v in strategy_config.items():
            if k in EXTRA_ENGINE_DEFAULTS:
                if isinstance(EXTRA_ENGINE_DEFAULTS[k], dict) and isinstance(v, dict):
                    merged = dict(EXTRA_ENGINE_DEFAULTS[k]); merged.update(v); cfg[k] = merged
                else:
                    cfg[k] = v
    return cfg


def _timestamp_to_datetime(df: pd.DataFrame) -> pd.Series:
    ts = pd.to_numeric(df["timestamp"], errors="coerce")
    unit = "ms" if float(ts.dropna().median() or 0) > 1e12 else "s"
    return pd.to_datetime(ts, unit=unit, utc=True)


def _active_killzone(dt, killzones):
    """اسم Killzone فعال در لحظه dt (UTC) یا None."""
    hour = dt.hour + dt.minute / 60.0
    for name, (start_h, end_h) in killzones.items():
        if start_h <= hour < end_h:
            return name, start_h
    return None, None


def _fvg_present(d, i, direction):
    """FVG سه‌کندلی ساده: بین کندل i-2 و i (شامل i-1 وسط) — استاندارد ICT."""
    if i < 2:
        return False
    if direction == "BUY":
        return float(d["low"].iloc[i]) > float(d["high"].iloc[i - 2])
    else:
        return float(d["high"].iloc[i]) < float(d["low"].iloc[i - 2])


def evaluate_extra_scenarios(df: pd.DataFrame, timeframe: str, strategy_config: dict = None, diag: dict = None):
    """
    ارزیابی سناریوهای X1 (Judas پایین → MSS صعودی → BUY) و
    X2 (Judas بالا → MSS نزولی → SELL) روی آخرین کندل بسته‌شده‌ی df.

    خروجی: همان قرارداد evaluate_scenarios در pdh_eq_pdl_engine.py
    (dict یا None).
    """
    if diag is not None:
        diag.clear()
        diag["level_source"] = "orb_killzone"

    cfg = _merged_cfg(strategy_config)
    if df is None or len(df) < 50 or "timestamp" not in df.columns:
        if diag is not None:
            diag["gate"] = "insufficient_data"
        return None

    d = _ensure_atr(df.copy())
    d["_dt"] = _timestamp_to_datetime(d)
    if d["_dt"].isna().all():
        if diag is not None:
            diag["gate"] = "insufficient_data"
        return None
    d = d.sort_values("_dt").reset_index(drop=True)

    now_dt = d["_dt"].iloc[-1]
    kz_name, kz_start_h = _active_killzone(now_dt, cfg["killzones"])
    if kz_name is None:
        if diag is not None:
            diag["gate"] = "outside_killzone"
        return None

    kz_start_dt = now_dt.normalize() + pd.Timedelta(hours=kz_start_h)
    orb_minutes = int(cfg["orb_minutes"].get(timeframe, 30))
    orb_end_dt = kz_start_dt + pd.Timedelta(minutes=orb_minutes)

    orb_mask = (d["_dt"] >= kz_start_dt) & (d["_dt"] < orb_end_dt)
    orb_bars = d.loc[orb_mask]
    if len(orb_bars) < 2:
        if diag is not None:
            diag["gate"] = "orb_not_formed_yet"
        return None
    orb_hi = float(orb_bars["high"].max())
    orb_lo = float(orb_bars["low"].min())

    post_orb_mask = (d["_dt"] >= orb_end_dt) & (d["_dt"] <= now_dt)
    post_orb = d.loc[post_orb_mask]
    if len(post_orb) < 2:
        if diag is not None:
            diag["gate"] = "no_post_orb_bars_yet"
        return None

    minutes_since_kz_start = (now_dt - kz_start_dt).total_seconds() / 60.0

    # سوینگ‌های مینور برای تأیید MSS (همان کتابخانه‌ی کیفی موتور اصلی)
    lookback = int(cfg["swing_lookback_fractal"])
    d = compute_swings(d, lookback=lookback, mode="advanced")

    last_i = len(d) - 1
    last_close = float(d["close"].iloc[last_i])
    last_atr = float(d["atr"].iloc[last_i]) if pd.notna(d["atr"].iloc[last_i]) else 0.0
    if last_atr <= 0:
        if diag is not None:
            diag["gate"] = "invalid_atr"
        return None

    candidates = []

    # -------- سناریو X1: Judas پایین (سوییپ زیر ORB low) → MSS صعودی → BUY --------
    swept_low = float(post_orb["low"].min())
    judas_down_depth = (orb_lo - swept_low) / last_atr if swept_low < orb_lo else 0.0
    if judas_down_depth >= cfg["sweep_min_atr_ratio"]:
        prior_swing_highs = d.loc[:last_i][d["swing_high"]]
        prior_swing_highs = prior_swing_highs[prior_swing_highs["_dt"] < now_dt]
        if not prior_swing_highs.empty:
            recent_swing_high = float(prior_swing_highs["high"].iloc[-1])
            mss_confirmed = last_close > recent_swing_high
            if mss_confirmed:
                base_score = 78.0
                bonus = 0.0
                reasons = [
                    f"Judas Swing: سوییپ زیر ORB Low ({orb_lo:.6g}) به عمق {judas_down_depth:.2f}×ATR",
                    f"MSS تایید شد: بسته‌شدن بالای آخرین سوینگ ماینور ({recent_swing_high:.6g})",
                ]
                if _fvg_present(d, last_i, "BUY"):
                    bonus += cfg["fvg_bonus"]
                    reasons.append("FVG صعودی همراه با MSS شناسایی شد")
                if float(d["volume_ratio"].iloc[last_i]) >= 1.2:
                    bonus += cfg["volume_bonus"]
                    reasons.append("حجم کندل MSS بالاتر از میانگین")
                penalty = 0.0
                if minutes_since_kz_start > cfg["late_killzone_penalty_after_min"]:
                    penalty += cfg["late_killzone_penalty"]
                    reasons.append("ورود دیرهنگام در Killzone — جریمه اعمال شد")
                sl = swept_low - cfg["sl_atr_buffer"] * last_atr
                risk = last_close - sl
                tp_partial = orb_hi
                tp_final = last_close + max(risk * 2.0, (orb_hi - orb_lo) * 1.5)
                candidates.append({
                    "code": "X1", "direction": "BUY",
                    "total_score": round(min(100.0, max(0.0, base_score + bonus - penalty)), 1),
                    "base_score": base_score, "bonus": round(bonus, 1), "penalty": round(penalty, 1),
                    "entry": last_close, "sl": sl, "tp": tp_final, "tp_partial": tp_partial,
                    "level_label": f"ORB/Judas/MSS ({kz_name})", "reasons": reasons,
                })

    # -------- سناریو X2: Judas بالا (سوییپ بالای ORB high) → MSS نزولی → SELL --------
    swept_high = float(post_orb["high"].max())
    judas_up_depth = (swept_high - orb_hi) / last_atr if swept_high > orb_hi else 0.0
    if judas_up_depth >= cfg["sweep_min_atr_ratio"]:
        prior_swing_lows = d.loc[:last_i][d["swing_low"]]
        prior_swing_lows = prior_swing_lows[prior_swing_lows["_dt"] < now_dt]
        if not prior_swing_lows.empty:
            recent_swing_low = float(prior_swing_lows["low"].iloc[-1])
            mss_confirmed = last_close < recent_swing_low
            if mss_confirmed:
                base_score = 78.0
                bonus = 0.0
                reasons = [
                    f"Judas Swing: سوییپ بالای ORB High ({orb_hi:.6g}) به عمق {judas_up_depth:.2f}×ATR",
                    f"MSS تایید شد: بسته‌شدن پایین آخرین سوینگ ماینور ({recent_swing_low:.6g})",
                ]
                if _fvg_present(d, last_i, "SELL"):
                    bonus += cfg["fvg_bonus"]
                    reasons.append("FVG نزولی همراه با MSS شناسایی شد")
                if float(d["volume_ratio"].iloc[last_i]) >= 1.2:
                    bonus += cfg["volume_bonus"]
                    reasons.append("حجم کندل MSS بالاتر از میانگین")
                penalty = 0.0
                if minutes_since_kz_start > cfg["late_killzone_penalty_after_min"]:
                    penalty += cfg["late_killzone_penalty"]
                    reasons.append("ورود دیرهنگام در Killzone — جریمه اعمال شد")
                sl = swept_high + cfg["sl_atr_buffer"] * last_atr
                risk = sl - last_close
                tp_partial = orb_lo
                tp_final = last_close - max(risk * 2.0, (orb_hi - orb_lo) * 1.5)
                candidates.append({
                    "code": "X2", "direction": "SELL",
                    "total_score": round(min(100.0, max(0.0, base_score + bonus - penalty)), 1),
                    "base_score": base_score, "bonus": round(bonus, 1), "penalty": round(penalty, 1),
                    "entry": last_close, "sl": sl, "tp": tp_final, "tp_partial": tp_partial,
                    "level_label": f"ORB/Judas/MSS ({kz_name})", "reasons": reasons,
                })

    if not candidates:
        if diag is not None:
            diag["gate"] = "no_scenario_matched"
        return None

    best = max(candidates, key=lambda c: c["total_score"])
    if diag is not None:
        diag["gate"] = "candidate_found"
        diag["killzone"] = kz_name
        diag["orb_hi"] = orb_hi
        diag["orb_lo"] = orb_lo
    return best
