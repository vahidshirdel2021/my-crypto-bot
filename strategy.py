# -*- coding: utf-8 -*-
"""
strategy.py
-----------
موتور یکپارچه‌ی استراتژی و مدیریت ریسک هماهنگ با bot.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pdh_eq_pdl_engine import (
    evaluate_scenarios, 
    compute_swing_stop_v2, 
    _ensure_atr, 
    compute_prev_day_levels, 
    compute_prev_week_levels, 
    get_reference_levels
)

FILTER_DEFAULTS = {
    "volume_filter": True,
    "candlestick_filter": True,
    "trailing_stop": True,
    "no_short_filter": False,
    "no_buy_filter": False,
}

STRATEGY_DEFAULTS = {
    "swing_lookback": 12,
    "swing_confirm_candles": 2,
    "swing_buffer_atr": 0.40,
    "min_trade_score": 65.0,
    "min_rr": 1.10,
    "min_adx": 18.0,
    "cooldown_seconds": 1200,
    "v2_enabled": True,
}

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    return _ensure_atr(df)

def get_timeframe_preset(timeframe: str):
    cfg = dict(STRATEGY_DEFAULTS)
    if timeframe == '5min':
        cfg.update({"swing_lookback": 10, "min_trade_score": 65.0, "min_rr": 1.10})
    elif timeframe == '15min':
        cfg.update({"swing_lookback": 12, "min_trade_score": 68.0, "min_rr": 1.20})
    elif timeframe == '1hour':
        cfg.update({"swing_lookback": 14, "min_trade_score": 70.0, "min_rr": 1.30})
    elif timeframe == '4hour':
        cfg.update({"swing_lookback": 16, "min_trade_score": 72.0, "min_rr": 1.40})
    return cfg

def get_signal_with_reason(df, md, mode, timeframe, strategy_name, filters, strategy_config, regime=None, live_price=None):
    best = evaluate_scenarios(df, timeframe, strategy_config)
    if not best:
        return None, "بدون ستاپ (یا مسدودشده توسط Dead-Zone Gate)"
    score = float(best.get("total_score", 0.0))
    min_score = float(strategy_config.get("min_score_to_trade", 65.0))
    if score < min_score:
        return None, f"امتیاز کیفیت پایین ({score}/{min_score})"
    direction = best.get("direction")
    code = best.get("code")
    reasons = " | ".join(best.get("reasons", []))
    if regime:
        if regime == 'BULLISH' and direction == 'SELL':
            return None, "محافظ رژیم بازار: ورود شورت در روند صعودی مسدود است"
        if regime == 'BEARISH' and direction == 'BUY':
            return None, "محافظ رژیم بازار: ورود لانگ در روند نزولی مسدود است"
    reason_str = f"[{code}] کیفیت {score}/100 ({best.get('level_label','PDH/PDL')}) | {reasons}"
    return direction, reason_str

def build_trade_plan(df, signal_direction, strategy_config, strategy_type, strategy_timeframe='5min', **kwargs):
    best = evaluate_scenarios(df, strategy_timeframe, strategy_config)
    if not best or best.get("direction") != signal_direction:
        return None, "طرح معامله: سناریوی متناظر پیدا نشد"
    entry = float(best["entry"])
    sl = float(best["sl"])
    tp = float(best["tp"])
    ladder = best.get("tp_ladder")
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    if risk <= 0 or reward <= 0:
        return None, "طرح معامله: فاصله حد سود یا حد ضرر نامعتبر است"
    rr = reward / risk
    min_rr = float(strategy_config.get("min_rr", 1.10))
    if rr < min_rr:
        return None, f"طرح معامله: نسبت R:R کافی نیست ({rr:.2f} < {min_rr})"
    plan = {
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "tp_ladder": ladder,
        "planned_rr": round(rr, 2),
        "setup_family": best.get("code"),
    }
    return plan, f"طرح معامله تایید شد | R:R {rr:.2f}R"

def compute_swing_stop(df, is_long, lookback=12, buffer_atr=0.40, confirm_candles=2):
    return compute_swing_stop_v2(df, is_long, lookback, buffer_atr, confirm_candles)

def strategy_trend_following(df, timeframe, filters, strategy_config):
    res = evaluate_scenarios(df, timeframe, strategy_config)
    if res:
        return res.get("direction"), "Trend following via scenario"
    return None, "No trend signal"

def strategy_breakout(df, filters, strategy_config):
    return None, "Breakout legacy wrapped"

def strategy_mean_reversion(df, filters, strategy_config):
    return None, "Mean reversion legacy wrapped"

def evaluate_trend_weakness(df, side, strategy_config):
    return False, 0.0, []

def compute_log_grid_levels(df, steps=20):
    return []

def nearest_grid_level(price, levels):
    return price
