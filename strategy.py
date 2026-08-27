# -*- coding: utf-8 -*-
"""
strategy.py  —  بازنویسی کامل (صفر تا صد) بر اساس استراتژی PDH / EQ / PDL
==========================================================================
طبق درخواست صریح کاربر، تمام منطق قبلی تصمیم‌گیری این فایل (dynamic v2،
liquidity sweep، structure flip، trend/breakout/mean-reversion قدیمی و…)
کنار گذاشته شده و با یک موتور واحد در ماژول `pdh_eq_pdl_engine.py`
جایگزین شده است که ۱۰ سناریوی B1..B5 / S1..S5 فایل استراتژی کاربر را
هم‌زمان ارزیابی و بهترین‌شان را بر اساس امتیاز انتخاب می‌کند.

نگاشت تایم‌فریم → منبع سطح مرجع (طبق درخواست کاربر):
    5min , 15min  → PDH/PDL/EQ روزانه
    1hour, 4hour  → PWH/PWL/EQ هفتگی

این فایل، امضای (signature) و خروجی توابعی که `bot.py`، `ui.py`،
`backtest.py` و `v3_backtest.py` از آن‌ها استفاده می‌کنند را کاملاً حفظ
کرده تا نیازی به تغییر بقیه‌ی پروژه نباشد؛ فقط «مغز» تصمیم‌گیری عوض شده.
"""

import numpy as np
import pandas as pd

from pdh_eq_pdl_engine import (
    ENGINE_DEFAULTS,
    LEVEL_SOURCE_BY_TIMEFRAME,
    evaluate_scenarios,
    compute_prev_day_levels,
    compute_prev_week_levels,
    get_reference_levels,
    compute_swings,
)


# ============================================================================
# ابزارهای عمومی (بدون تغییر نسبت به نسخه قبلی، مورد استفاده در چند تابع)
# ============================================================================

def _safe_float(value, default=0.0):
    try:
        x = float(value)
        return x if np.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _cfg(config):
    return config if isinstance(config, dict) else STRATEGY_DEFAULTS


def _flt(filters):
    return filters if isinstance(filters, dict) else FILTER_DEFAULTS


# ============================================================================
# گرید لگاریتمی (بدون تغییر - فقط برای نمایش/کمک تصمیم، وابسته به هیچ استراتژی نیست)
# ============================================================================

def compute_log_grid_levels(df, base_steps=20, lookback=None):
    """گرید لگاریتمی متعادل بدون تکیه بر سقف/کف بیات کل تاریخچه."""
    if df is None or df.empty or len(df) < 2:
        return []
    d = df.tail(int(lookback)) if lookback and int(lookback) > 1 else df
    chart_low = float(pd.to_numeric(d['low'], errors='coerce').min())
    chart_high = float(pd.to_numeric(d['high'], errors='coerce').max())
    if not np.isfinite(chart_low) or not np.isfinite(chart_high) or chart_low <= 0 or chart_high <= chart_low:
        return []
    n_intervals = max(1, int(base_steps) * 2)
    ratio = (chart_high / chart_low) ** (1.0 / n_intervals)
    return [{'step': i / 2.0, 'price': chart_low * (ratio ** i)} for i in range(n_intervals + 1)]


def nearest_grid_level(price, levels):
    """نزدیک‌ترین سطح شبکه به یک قیمت مشخص: (level_dict, فاصله به‌درصد)."""
    if not levels or price is None or price <= 0:
        return None, None
    best = min(levels, key=lambda lv: abs(lv['price'] - price))
    dist_pct = abs(best['price'] - price) / price * 100.0
    return best, dist_pct


FILTER_DEFAULTS = {
    "volume_filter": True,
    "trailing_stop": True,
    "candlestick_filter": True,
    "no_short_filter": True,
    "no_buy_filter": False,
}


def compute_swing_stop(df, is_long, lookback=12, buffer_atr=0.40, confirm_candles=2):
    """Return a trailing stop behind the latest *validated* structural swing.
    Swings must pass the engine's wick/volume quality gates and must be fully
    confirmed before they can move an existing stop."""
    if df is None or df.empty or "atr" not in df.columns:
        return None, None
    if len(df) < lookback + confirm_candles + 3:
        return None, None
    cfg = STRATEGY_DEFAULTS if 'STRATEGY_DEFAULTS' in globals() else ENGINE_DEFAULTS
    d = compute_swings(
        df,
        lookback=max(2, min(int(lookback // 3 or 3), 8)),
        min_wick_atr=float(cfg.get("min_swing_wick_atr", 0.20)),
        min_wick_pct=float(cfg.get("min_swing_wick_pct", 0.0008)),
        min_volume_ratio=float(cfg.get("min_swing_volume_ratio", 1.05)),
        require_volume=bool(cfg.get("require_swing_volume", True)),
    )
    idx_now = len(d) - 2
    if idx_now <= 0:
        return None, None
    # A fractal at i is only tradable after `lookback` candles to its right
    # have closed.  Never use the still-forming latest candle as structure.
    confirmed_hi = [i for i in d.index if i <= idx_now - max(1, int(lookback)) and bool(d.at[i, "swing_high"])]
    confirmed_lo = [i for i in d.index if i <= idx_now - max(1, int(lookback)) and bool(d.at[i, "swing_low"])]
    candidates = confirmed_lo if is_long else confirmed_hi
    if not candidates:
        return None, None

    # Structure-aware trailing: a Long may only advance behind a new Higher Low;
    # a Short may only advance behind a new Lower High. This prevents a fresh but
    # insignificant fractal from ratcheting the stop.
    valid = []
    prev_level = None
    for ci in candidates:
        level = float(d.at[ci, "low"] if is_long else d.at[ci, "high"])
        if prev_level is None:
            valid.append(ci)
        elif (is_long and level > prev_level) or ((not is_long) and level < prev_level):
            valid.append(ci)
        prev_level = level
    if not valid:
        return None, None
    i = valid[-1]
    # Require the selected pivot to have a non-trivial structural score.
    structure_score = float(d.at[i, "swing_structure_score"]) if "swing_structure_score" in d.columns else 1.0
    if structure_score < 1.0:
        return None, None
    atr = float(pd.to_numeric(d.at[idx_now, "atr"], errors="coerce"))
    if not np.isfinite(atr) or atr <= 0:
        return None, None
    swing = float(d.at[i, "low"] if is_long else d.at[i, "high"])
    sl = swing - atr * float(buffer_atr) if is_long else swing + atr * float(buffer_atr)
    return float(sl), float(swing)


# ============================================================================
# STRATEGY_DEFAULTS / presetهای هر تایم‌فریم
# کلیدهایی که bot.py مستقیماً (خارج از این فایل) برای مدیریت پوزیشن می‌خواند
# عیناً حفظ شده‌اند: swing_lookback, swing_confirm_candles, swing_buffer_atr,
# ============================================================================

STRATEGY_DEFAULTS = {
    # --- آستانه‌های موتور سناریو PDH/EQ/PDL ---
    "min_trade_score": ENGINE_DEFAULTS["min_score_to_trade"],
    "min_rr": ENGINE_DEFAULTS["min_rr"],
    "swing_lookback_fractal": ENGINE_DEFAULTS["swing_lookback_fractal"],
    "touch_tolerance_pct": ENGINE_DEFAULTS["touch_tolerance_pct"],
    "break_confirm_pct": ENGINE_DEFAULTS["break_confirm_pct"],
    "min_confirm_body_ratio": ENGINE_DEFAULTS["min_confirm_body_ratio"],
    "sl_atr_buffer": ENGINE_DEFAULTS["sl_atr_buffer"],
    "sl_atr_buffer_tight": ENGINE_DEFAULTS["sl_atr_buffer_tight"],
    "extension_atr_mult": ENGINE_DEFAULTS["extension_atr_mult"],
    "base_scores": dict(ENGINE_DEFAULTS["base_scores"]),
    "bonus_weights": dict(ENGINE_DEFAULTS["bonus_weights"]),
     "penalty_weights": dict(ENGINE_DEFAULTS["penalty_weights"]),
    "min_swing_wick_atr": ENGINE_DEFAULTS["min_swing_wick_atr"],
    "min_swing_wick_pct": ENGINE_DEFAULTS["min_swing_wick_pct"],
    "min_swing_volume_ratio": ENGINE_DEFAULTS["min_swing_volume_ratio"],
    "require_swing_volume": ENGINE_DEFAULTS["require_swing_volume"],
    "max_entry_event_age_bars": ENGINE_DEFAULTS["max_entry_event_age_bars"],
    "tp1_pct": 50.0, "tp2_pct": 30.0, "tp3_pct": 20.0,

    "max_sl_atr": 4.0,           # سقف مطلق فاصله SL بر حسب ATR (فیوز ایمنی، نه بخشی از سناریوها)
    "min_sl_percent": 0.005,
    "max_fee_risk_ratio": 0.20,
    "cooldown_seconds": 1200,

    # --- استاپ‌لاس بر اساس سوینگ ساختاری (برای تریلینگ در bot.py) ---
    "swing_lookback": 12,
    "swing_confirm_candles": 2,
    "swing_buffer_atr": 0.40,

    "v2_enabled": False,  # موتور قدیمی v2 کاملاً غیرفعال است؛ فقط برای سازگاری با کد قدیمی نگه داشته شده
}

# presetهای مخصوص هر تایم‌فریم — نگاشت سطح مرجع دقیقاً طبق درخواست کاربر:
#   5min/15min → روزانه (PDH/PDL)   |   1hour/4hour → هفتگی (PWH/PWL)
TIMEFRAME_STRATEGY_PRESETS = {
    "5min": {
        "level_source": "daily",
        "min_trade_score": 62.0, "min_rr": 1.05,
        "cooldown_seconds": 900,
    },
    "15min": {
        "level_source": "daily",
        "min_trade_score": 63.0, "min_rr": 1.10,
        "cooldown_seconds": 1200,
    },
    "1hour": {
        "level_source": "weekly",
        "min_trade_score": 65.0, "min_rr": 1.15,
        "cooldown_seconds": 1800,
    },
    "4hour": {
        "level_source": "weekly",
        "min_trade_score": 65.0, "min_rr": 1.20,
        "cooldown_seconds": 3600,
    },
}

TIMEFRAME_PARAM_ADJUST = TIMEFRAME_STRATEGY_PRESETS


def get_timeframe_preset(timeframe):
    return {**STRATEGY_DEFAULTS, **TIMEFRAME_STRATEGY_PRESETS.get(timeframe, {})}


def get_strategy_params(strategy_config=None):
    return {**STRATEGY_DEFAULTS, **(_cfg(strategy_config) or {})}


# ============================================================================
# calculate_indicators — بدون تغییر نسبت به نسخه قبلی.
# bot.py این تابع را در چندین جای مستقل (چارت، تشخیص رژیم بازار، تریلینگ‌استاپ،
# ============================================================================

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df.copy()
    df = df.copy()
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        return df
    for col in required:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    if len(df) < 60:
        return df

    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()

    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["tr"] = tr
    df["atr"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    plus_sm = plus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    minus_sm = minus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    plus_di = 100 * plus_sm / (df["atr"] + 1e-12)
    minus_di = 100 * minus_sm / (df["atr"] + 1e-12)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-12)
    df["plus_di"] = plus_di
    df["minus_di"] = minus_di
    df["adx"] = dx.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = avg_gain / (avg_loss + 1e-12)
    df["rsi"] = 100 - (100 / (1 + rs))

    df["channel_high"] = df["high"].rolling(20, min_periods=20).max().shift(1)
    df["channel_low"] = df["low"].rolling(20, min_periods=20).min().shift(1)
    df["volume_ma20"] = df["volume"].rolling(20, min_periods=20).mean()
    df["volume_ratio"] = df["volume"] / (df["volume_ma20"] + 1e-12)
    df["candle_body"] = (df["close"] - df["open"]).abs()
    df["candle_range"] = (df["high"] - df["low"]).clip(lower=1e-12)
    df["body_ratio"] = df["candle_body"] / df["candle_range"]
    return df


# ============================================================================
# _compute_prev_day_levels — امضای قدیمی حفظ شده (bot.py مستقیماً ایمپورت می‌کند)
# ============================================================================

def _compute_prev_day_levels(df):
    d, pdh, pdl, _eq = compute_prev_day_levels(df)
    return d, pdh, pdl


# ============================================================================
# build_trade_plan — امضای قدیمی کاملاً حفظ شده؛ محتوا صفر تا صد جدید.
# ============================================================================

def build_trade_plan(df, signal, strategy_config=None, strategy_type="dynamic",
                      strategy_timeframe="5min", grid_levels=None, setup_index=None,
                      live_price=None, market_data_dict=None, filters=None, regime=None,
                      defer_quality_gate=False):
    if df is None or len(df) < 50 or signal not in ("BUY", "SELL"):
        return None, "داده کافی برای طراحی معامله وجود ندارد"

    cfg = {**STRATEGY_DEFAULTS, **(_cfg(strategy_config) or {})}
    best = _run_engine(df, strategy_timeframe, cfg)
    if not best or best["direction"] != signal:
        return None, "سناریوی برنده با سیگنال هم‌خوانی ندارد؛ معامله رد شد"

    entry = _safe_float(best["entry"])
    sl = _safe_float(best["sl"])
    tp = _safe_float(best["tp"])
    if entry <= 0 or sl <= 0 or tp <= 0:
        return None, "سطوح قیمتی سناریو نامعتبر است"

    risk_dist = (entry - sl) if signal == "BUY" else (sl - entry)
    if risk_dist <= 0 or not np.isfinite(risk_dist):
        return None, "فاصله حد ضرر معتبر نیست (SL در سمت اشتباه قیمت ورود قرار دارد)"

    # فیوز ایمنی: سقف مطلق فاصله SL بر حسب ATR (مستقل از منطق سناریوها)
    atr = _safe_float(df.iloc[-2].get("atr")) if "atr" in df.columns else 0.0
    max_sl_atr = float(cfg.get("max_sl_atr", 4.0))
    if atr > 0 and risk_dist > atr * max_sl_atr:
        return None, f"فاصله حد ضرر بیش از سقف مجاز است ({risk_dist / atr:.2f}× ATR > {max_sl_atr:.2f}× ATR)"

    min_sl_pct = float(cfg.get("min_sl_percent", 0.005))
    if risk_dist / entry < min_sl_pct:
        if signal == "BUY":
            sl = entry * (1.0 - min_sl_pct)
        else:
            sl = entry * (1.0 + min_sl_pct)
        risk_dist = abs(entry - sl)

    rr = abs(tp - entry) / risk_dist
    min_rr = float(cfg.get("min_rr", ENGINE_DEFAULTS["min_rr"]))
    if rr < min_rr:
        return None, f"R:R کافی نیست ({rr:.2f}R < {min_rr:.2f}R) برای سناریوی {best['code']}"

    min_score = float(cfg.get("min_trade_score", ENGINE_DEFAULTS["min_score_to_trade"]))
    if best["total_score"] < min_score:
        return None, f"امتیاز سناریو {best['code']} کافی نیست ({best['total_score']}/100 < {min_score:.0f})"

    quality_label = ("عالی" if best["total_score"] >= 90 else
                      "خوب" if best["total_score"] >= 78 else
                      "قابل قبول" if best["total_score"] >= min_score else "ضعیف")

    # Explicit three-tier target ladder.  TP1 is exactly EQ, TP2 is the
    # opposite reference boundary, TP3 is the range-extension target.
    # `tp` remains the legacy final target field (TP3) for compatibility.
    tp1 = _safe_float(best.get("tp1"), best.get("tp_partial", 0.0))
    tp2 = _safe_float(best.get("tp2"), hi_level if signal == "BUY" else lo_level) if "hi_level" in locals() else _safe_float(best.get("tp2"))
    tp3 = _safe_float(best.get("tp3"), tp)
    plan = {
        "entry": entry, "sl": float(sl), "tp": float(tp3),
        "tp1": tp1, "tp1_pct": 50.0,
        "tp2": tp2, "tp2_pct": 30.0,
        "tp3": tp3, "tp3_pct": 20.0,
        "score": int(round(best["total_score"])),
        "quality_label": quality_label,
        "rr": float(rr),
        "target_r": float(rr),
        "risk_atr": float(risk_dist / atr) if atr > 0 else None,
        "atr": atr,
        "scenario_code": best["code"],
        "level_source": "weekly" if LEVEL_SOURCE_BY_TIMEFRAME.get(strategy_timeframe) == "weekly" else "daily",
        "swing_level": None,
        "structural_target": True,  # هدف، سطح ساختاری (PDH/PDL یا PWH/PWL) است نه RR ثابت
        "setup_family": f"pdh_eq_pdl_{best['code']}",
        "reason": _format_reason(best),
    }
    return plan, plan["reason"]


# ============================================================================
# strategy_trend_following / strategy_breakout / strategy_mean_reversion
# این سه تابع فقط در دستور دستی «/analyze» به‌صورت تشخیصی استفاده می‌شوند
# (bot.py هر سه را صدا می‌زند و نتیجه‌شان را OR می‌کند). طبق درخواست کاربر
# هر سه اکنون از همان موتور واحد PDH/EQ/PDL استفاده می‌کنند تا نتیجه‌ی
# «/analyze» هم دقیقاً منعکس‌کننده‌ی منطق واقعی ورود ربات باشد.
# ============================================================================

def _infer_timeframe_from_df(df):
    """برای strategy_breakout/strategy_mean_reversion که ورودی timeframe ندارند."""
    try:
        ts = pd.to_numeric(df["timestamp"], errors="coerce").dropna()
        if len(ts) < 3:
            return "5min"
        unit = "ms" if float(ts.median()) > 1e12 else "s"
        dt = pd.to_datetime(ts, unit=unit, utc=True)
        delta_minutes = dt.diff().median().total_seconds() / 60.0
        if delta_minutes <= 7:
            return "5min"
        if delta_minutes <= 20:
            return "15min"
        if delta_minutes <= 90:
            return "1hour"
        return "4hour"
    except Exception:
        return "5min"


def strategy_trend_following(df, timeframe="5min", filters=None, strategy_config=None):
    return get_signal_with_reason(df, None, "single", timeframe, "dynamic", filters, strategy_config)


def strategy_breakout(df, filters=None, strategy_config=None):
    tf = _infer_timeframe_from_df(df) if df is not None else "5min"
    return get_signal_with_reason(df, None, "single", tf, "dynamic", filters, strategy_config)


def strategy_mean_reversion(df, filters=None, strategy_config=None):
    tf = _infer_timeframe_from_df(df) if df is not None else "5min"
    return get_signal_with_reason(df, None, "single", tf, "dynamic", filters, strategy_config)


# ============================================================================
# لایه‌ی سازگاری با اسکریپت قدیمی v3_backtest.py (موتور legacy v2 حذف شده).
# این توابع فقط برای جلوگیری از خطای Import هستند؛ v3_backtest.py دیگر
# استراتژی واقعی ربات را شبیه‌سازی نمی‌کند — به‌جای آن از backtest.py
# استفاده کنید که به‌طور کامل با موتور جدید سازگار است (به README مراجعه کنید).
# ============================================================================

def get_v2_config(strategy_config=None):
    return {**STRATEGY_DEFAULTS, **(_cfg(strategy_config) or {}), "v2_enabled": False}


def detect_market_regime(df, strategy_config=None):
    return "mixed"


def _select_v2_setup(df_primary, market_data_dict=None, timeframe="5min", filters=None,
                      strategy_config=None, regime=None, grid_levels=None, live_price=None,
                      defer_quality_gate=False):
    return None, None, "موتور legacy v2 حذف شده؛ از get_signal_with_reason/build_trade_plan جدید استفاده کنید"
def get_signal_with_reason(df, md, mode, timeframe, strategy_name, filters, strategy_config, regime=None, live_price=None):
    from pdh_eq_pdl_engine import evaluate_scenarios
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
