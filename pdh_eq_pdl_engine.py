# -*- coding: utf-8 -*-
"""
pdh_eq_pdl_engine.py
---------------------
موتور PDH / EQ / PDL — نسخه‌ی استاندارد و اصلاح‌شده
"""

from __future__ import annotations

import numpy as np
import pandas as pd


ENGINE_DEFAULTS = {
    "swing_lookback_fractal": 3,
    "touch_tolerance_pct": 0.0006,
    "break_confirm_pct": 0.0003,
    "min_confirm_body_ratio": 0.20,
    "swing_search_window_mult": 4,
    "dead_zone_enabled": True,
    "dead_zone_eq_buffer_pct": 0.15,
    "dead_zone_require_recent_touch": True,
    "dead_zone_touch_lookback_candles": 60,
    "swing_min_wick_ratio": 0.15,
    "swing_min_volume_ratio": 0.80,
    "base_scores": {
        "B1": 95, "B2": 90, "B3": 80, "B4": 75, "B5": 70, "B6": 60,
        "S1": 95, "S2": 90, "S3": 80, "S4": 75, "S5": 70, "S6": 60,
    },
    "bonus_weights": {
        "volume": 10.0,
        "candle_body": 5.0,
        "swing_clarity": 5.0,
        "rsi_alignment": 5.0,
        "trend_alignment": 5.0,
    },
    "penalty_weights": {
        "fakeout_history": 15.0,
    },
    "penalty_scenario_multiplier": {
        "B1": 1.00, "S1": 1.00,
        "B2": 0.85, "S2": 0.85,
        "B3": 0.55, "S3": 0.55,
        "B4": 0.90, "S4": 0.90,
        "B5": 0.45, "S5": 0.45,
        "B6": 1.00, "S6": 1.00,
    },
    "rsi_oversold": 35.0,
    "rsi_overbought": 65.0,
    "max_score": 100.0,
    "min_score_to_trade": 65.0,
    "atr_period": 14,
    "sl_atr_buffer": 0.35,
    "sl_atr_buffer_tight": 0.20,
    "extension_atr_mult": 0.50,
    "min_rr": 1.10,
    "tp_ladder_ratios": (0.50, 0.30, 0.20),
}


def _safe_float(v, default=0.0):
    try:
        x = float(v)
        return x if np.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _merged_cfg(strategy_config=None):
    cfg = dict(ENGINE_DEFAULTS)
    if isinstance(strategy_config, dict):
        for k, v in strategy_config.items():
            if k in ("base_scores", "bonus_weights", "penalty_weights",
                      "penalty_scenario_multiplier") and isinstance(v, dict):
                merged = dict(cfg.get(k, {}))
                merged.update(v)
                cfg[k] = merged
            else:
                cfg[k] = v
    return cfg


def _ensure_atr(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    need = {"atr", "rsi", "ema50", "volume_ratio", "body_ratio"}
    if need.issubset(df.columns):
        return df
    d = df.copy()
    for col in ("open", "high", "low", "close", "volume"):
        if col in d.columns:
            d[col] = pd.to_numeric(d[col], errors="coerce")
    prev_close = d["close"].shift(1)
    tr = pd.concat([
        d["high"] - d["low"],
        (d["high"] - prev_close).abs(),
        (d["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    delta = d["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = avg_gain / (avg_loss + 1e-12)
    d["rsi"] = 100 - (100 / (1 + rs))
    d["ema50"] = d["close"].ewm(span=50, adjust=False).mean()
    d["volume_ma20"] = d["volume"].rolling(20, min_periods=20).mean()
    d["volume_ratio"] = d["volume"] / (d["volume_ma20"] + 1e-12)
    d["candle_body"] = (d["close"] - d["open"]).abs()
    d["candle_range"] = (d["high"] - d["low"]).clip(lower=1e-12)
    d["body_ratio"] = d["candle_body"] / d["candle_range"]
    return d


def _timestamp_to_datetime_utc(df: pd.DataFrame) -> pd.Series:
    raw = df["timestamp"]
    ts_numeric = pd.to_numeric(raw, errors="coerce")
    if ts_numeric.notna().sum() >= max(1, int(len(raw) * 0.9)):
        sample = ts_numeric.dropna()
        med = float(sample.median()) if len(sample) else 0.0
        if med > 4_102_444_800:
            unit = "ms" if med < 4_102_444_800_000 else "us"
        elif med > 978_307_200:
            unit = "s"
        else:
            unit = "ms"
        return pd.to_datetime(ts_numeric, unit=unit, utc=True, errors="coerce")
    return pd.to_datetime(raw, utc=True, errors="coerce")


_timestamp_to_datetime = _timestamp_to_datetime_utc


def _aggregate_period_levels(df: pd.DataFrame, period_key_func, min_rows=50):
    if df is None or len(df) < min_rows or "timestamp" not in df.columns:
        return None, None, None, None
    d = df.copy()
    d["_dt"] = _timestamp_to_datetime_utc(d)
    if d["_dt"].isna().all():
        return None, None, None, None
    d = d.sort_values("_dt", kind="mergesort").reset_index(drop=True)
    d["_period"] = period_key_func(d["_dt"])

    grp = d.groupby("_period", sort=False).agg(_hi=("high", "max"), _lo=("low", "min"))
    order = d.groupby("_period", sort=False)["_dt"].min().sort_values().index
    grp = grp.reindex(order)
    grp["_hi_prev"] = grp["_hi"].shift(1)
    grp["_lo_prev"] = grp["_lo"].shift(1)

    d = d.merge(
        grp[["_hi_prev", "_lo_prev"]],
        left_on="_period", right_index=True, how="left",
        sort=False, validate="many_to_one",
    )
    d = d.sort_values("_dt", kind="mergesort").reset_index(drop=True)

    idx_now = len(d) - 2
    if idx_now < 0:
        return d, None, None, None

    hi_level, lo_level = d.at[idx_now, "_hi_prev"], d.at[idx_now, "_lo_prev"]
    if pd.isna(hi_level) or pd.isna(lo_level):
        return d, None, None, None

    hi_level, lo_level = float(hi_level), float(lo_level)
    if not (hi_level > lo_level):
        return d, None, None, None

    eq = (hi_level + lo_level) / 2.0
    return d, hi_level, lo_level, eq


def compute_prev_day_levels(df: pd.DataFrame):
    return _aggregate_period_levels(df, lambda dt: dt.dt.date)


def compute_prev_week_levels(df: pd.DataFrame):
    def _iso_week_key(dt_series):
        iso = dt_series.dt.isocalendar()
        return iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)
    return _aggregate_period_levels(df, _iso_week_key)


LEVEL_SOURCE_BY_TIMEFRAME = {
    "5min": "daily",
    "15min": "daily",
    "1hour": "weekly",
    "4hour": "weekly",
}


def get_reference_levels(df: pd.DataFrame, timeframe: str):
    source = LEVEL_SOURCE_BY_TIMEFRAME.get(timeframe, "daily")
    if source == "weekly":
        d, hi, lo, eq = compute_prev_week_levels(df)
        return d, hi, lo, eq, "PWH/PWL", source
    d, hi, lo, eq = compute_prev_day_levels(df)
    return d, hi, lo, eq, "PDH/PDL", source


def compute_swings(df: pd.DataFrame, lookback: int = 3,
                    min_wick_ratio: float = None, min_volume_ratio: float = None) -> pd.DataFrame:
    d = df.copy()
    n = len(d)
    if min_wick_ratio is None:
        min_wick_ratio = ENGINE_DEFAULTS["swing_min_wick_ratio"]
    if min_volume_ratio is None:
        min_volume_ratio = ENGINE_DEFAULTS["swing_min_volume_ratio"]

    highs = pd.to_numeric(d["high"], errors="coerce").values
    lows = pd.to_numeric(d["low"], errors="coerce").values
    opens = pd.to_numeric(d["open"], errors="coerce").values if "open" in d.columns else None
    closes = pd.to_numeric(d["close"], errors="coerce").values if "close" in d.columns else None

    if "volume_ratio" in d.columns:
        vol_ratio = pd.to_numeric(d["volume_ratio"], errors="coerce").values
    elif "volume" in d.columns:
        vma = pd.to_numeric(d["volume"], errors="coerce").rolling(20, min_periods=5).mean()
        vol_ratio = (pd.to_numeric(d["volume"], errors="coerce") / (vma + 1e-12)).values
    else:
        vol_ratio = np.full(n, 1.0)

    swing_high = np.zeros(n, dtype=bool)
    swing_low = np.zeros(n, dtype=bool)

    for i in range(lookback, n - lookback):
        h_win = highs[i - lookback: i + lookback + 1]
        l_win = lows[i - lookback: i + lookback + 1]
        if np.isnan(h_win).any() or np.isnan(l_win).any():
            continue

        rng = max(highs[i] - lows[i], 1e-12)
        v_ok = (not np.isnan(vol_ratio[i])) and (vol_ratio[i] >= min_volume_ratio)

        if highs[i] == h_win.max() and (h_win == highs[i]).sum() == 1:
            if opens is not None and closes is not None and not (np.isnan(opens[i]) or np.isnan(closes[i])):
                upper_wick = highs[i] - max(opens[i], closes[i])
            else:
                upper_wick = rng * 0.5
            wick_ok = (upper_wick / rng) >= min_wick_ratio
            if wick_ok and v_ok:
                swing_high[i] = True

        if lows[i] == l_win.min() and (l_win == lows[i]).sum() == 1:
            if opens is not None and closes is not None and not (np.isnan(opens[i]) or np.isnan(closes[i])):
                lower_wick = min(opens[i], closes[i]) - lows[i]
            else:
                lower_wick = rng * 0.5
            wick_ok = (lower_wick / rng) >= min_wick_ratio
            if wick_ok and v_ok:
                swing_low[i] = True

    d["swing_high"] = swing_high
    d["swing_low"] = swing_low
    return d


def _recent_confirmed_swings(d: pd.DataFrame, idx_now: int, lookback: int, col: str, search_back: int):
    lo = max(0, idx_now - search_back)
    hi = idx_now - lookback
    if hi < lo:
        return []
    sub = d.loc[lo:hi]
    return [i for i in sub.index if bool(sub.at[i, col])]


def compute_swing_stop_v2(df: pd.DataFrame, is_long: bool, lookback: int = 12,
                           buffer_atr: float = 0.40, confirm_candles: int = 2,
                           min_wick_ratio: float = None, min_volume_ratio: float = None):
    if df is None or df.empty:
        return None, None
    need = lookback + confirm_candles
    if len(df) < need + 5:
        return None, None
    if "atr" not in df.columns:
        return None, None
    atr = pd.to_numeric(df["atr"], errors="coerce").iloc[-1]
    if not np.isfinite(atr) or atr <= 0:
        return None, None

    swings_df = compute_swings(df, lookback=3, min_wick_ratio=min_wick_ratio, min_volume_ratio=min_volume_ratio)
    end = -confirm_candles if confirm_candles > 0 else None
    start = -(lookback + confirm_candles)
    window = swings_df.iloc[start:end]
    if window.empty:
        return None, None

    if is_long:
        valid = window[window["swing_low"]]
        if valid.empty:
            swing = float(pd.to_numeric(window["low"], errors="coerce").min())
            if not np.isfinite(swing):
                return None, None
            sl = swing - atr * buffer_atr
            return float(sl), float(swing)
        swing = float(valid["low"].min())
        sl = swing - atr * buffer_atr
    else:
        valid = window[window["swing_high"]]
        if valid.empty:
            swing = float(pd.to_numeric(window["high"], errors="coerce").max())
            if not np.isfinite(swing):
                return None, None
            sl = swing + atr * buffer_atr
            return float(sl), float(swing)
        swing = float(valid["high"].max())
        sl = swing + atr * buffer_atr

    return float(sl), float(swing)


def _dynamic_bonus_penalty(d: pd.DataFrame, idx_now: int, direction: int, cfg: dict,
                            touch_count: int, scenario_code: str = None):
    bw = cfg["bonus_weights"]
    pw = cfg["penalty_weights"]
    mult_map = cfg.get("penalty_scenario_multiplier", {})
    row = d.loc[idx_now]
    notes = []

    vr = _safe_float(row.get("volume_ratio"), 1.0)
    volume_bonus = max(0.0, min(bw["volume"], (vr - 1.0) * bw["volume"]))
    if volume_bonus > 0.5:
        notes.append(f"حجم {vr:.2f}× میانگین")

    body_ratio = _safe_float(row.get("body_ratio"), 0.0)
    candle_bonus = max(0.0, min(bw["candle_body"], (body_ratio / 0.65) * bw["candle_body"]))
    if candle_bonus > 0.5:
        notes.append(f"کیفیت بدنه کندل {body_ratio:.2f}")

    rsi = _safe_float(row.get("rsi"), 50.0)
    if direction > 0:
        rsi_bonus = max(0.0, min(bw["rsi_alignment"], (cfg["rsi_oversold"] - rsi) / cfg["rsi_oversold"] * bw["rsi_alignment"]))
    else:
        rsi_bonus = max(0.0, min(bw["rsi_alignment"], (rsi - cfg["rsi_overbought"]) / (100 - cfg["rsi_overbought"]) * bw["rsi_alignment"]))
    if rsi_bonus > 0.5:
        notes.append(f"هم‌جهتی RSI ({rsi:.1f})")

    ema50 = _safe_float(row.get("ema50"), row.get("close"))
    close = _safe_float(row.get("close"))
    if direction > 0:
        trend_bonus = bw["trend_alignment"] if close > ema50 else 0.0
    else:
        trend_bonus = bw["trend_alignment"] if close < ema50 else 0.0
    if trend_bonus > 0:
        notes.append("هم‌جهت با روند EMA50")

    bonus_total = volume_bonus + candle_bonus + rsi_bonus + trend_bonus

    extra_touches = max(0, touch_count - 1)
    base_penalty_cap = pw["fakeout_history"]
    scenario_mult = float(mult_map.get(scenario_code, 1.0)) if scenario_code else 1.0
    penalty_total = min(base_penalty_cap, extra_touches * (base_penalty_cap / 3.0)) * scenario_mult
    if penalty_total > 0.5:
        notes.append(f"سابقه {touch_count} برخورد قبلی به همین سطح (جریمه×{scenario_mult:.2f})")

    return bonus_total, penalty_total, notes


def _in_dead_zone(period: pd.DataFrame, idx_now: int, close_now: float,
                   hi_level: float, lo_level: float, eq: float,
                   hi_touch_idxs: list, lo_touch_idxs: list, cfg: dict) -> bool:
    if not cfg.get("dead_zone_enabled", True):
        return False
    half_range = (hi_level - lo_level) / 2.0
    if half_range <= 0:
        return True

    buffer_pct = float(cfg.get("dead_zone_eq_buffer_pct", 0.15))
    dead_zone_width = half_range * buffer_pct
    near_eq = abs(close_now - eq) <= dead_zone_width
    if not near_eq:
        return False

    if not cfg.get("dead_zone_require_recent_touch", True):
        return True

    lookback_n = int(cfg.get("dead_zone_touch_lookback_candles", 60))
    recent_start = max(int(period.index.min()) if len(period.index) else idx_now, idx_now - lookback_n)

    recent_hi_touch = any(i >= recent_start for i in hi_touch_idxs)
    recent_lo_touch = any(i >= recent_start for i in lo_touch_idxs)

    return not (recent_hi_touch or recent_lo_touch)


def _is_bullish_confirm(row, min_body_ratio):
    return _safe_float(row.get("close")) > _safe_float(row.get("open")) and _safe_float(row.get("body_ratio")) >= min_body_ratio


def _is_bearish_confirm(row, min_body_ratio):
    return _safe_float(row.get("close")) < _safe_float(row.get("open")) and _safe_float(row.get("body_ratio")) >= min_body_ratio


def _build_tp_ladder(direction: str, entry: float, eq: float, opposite_level: float,
                      extension_target: float, cfg: dict):
    r1, r2, r3 = cfg.get("tp_ladder_ratios", (0.50, 0.30, 0.20))
    is_long = direction == "BUY"

    def valid_above(x):
        return is_long and x > entry
    def valid_below(x):
        return (not is_long) and x < entry

    tiers = []
    if (is_long and valid_above(eq)) or ((not is_long) and valid_below(eq)):
        tiers.append(("tp1_eq", eq, r1))
    if (is_long and valid_above(opposite_level)) or ((not is_long) and valid_below(opposite_level)):
        tiers.append(("tp2_opposite", opposite_level, r2))
    if extension_target is not None and (
        (is_long and valid_above(extension_target)) or ((not is_long) and valid_below(extension_target))
    ):
        tiers.append(("tp3_extension", extension_target, r3))

    if not tiers:
        return None

    total_w = sum(t[2] for t in tiers)
    normalized = [(name, price, w / total_w) for name, price, w in tiers]
    normalized.sort(key=lambda t: abs(t[1] - entry))
    return {
        "tiers": normalized,
        "tp1": eq,
        "tp2": opposite_level,
        "tp3": extension_target,
    }


def evaluate_scenarios(df: pd.DataFrame, timeframe: str, strategy_config: dict = None):
    cfg = _merged_cfg(strategy_config)
    if df is None or len(df) < 50:
        return None
    d = _ensure_atr(df)
    d, hi_level, lo_level, eq, label, source = get_reference_levels(d, timeframe)
    if d is None or hi_level is None or lo_level is None or hi_level <= lo_level:
        return None

    lookback = int(cfg["swing_lookback_fractal"])
    min_wick_ratio = float(cfg.get("swing_min_wick_ratio", 0.15))
    min_volume_ratio = float(cfg.get("swing_min_volume_ratio", 0.80))
    d = compute_swings(d, lookback, min_wick_ratio=min_wick_ratio, min_volume_ratio=min_volume_ratio)
    idx_now = len(d) - 2
    if idx_now < lookback * 3:
        return None

    tol = float(cfg["touch_tolerance_pct"])
    brk = float(cfg["break_confirm_pct"])
    min_body = float(cfg["min_confirm_body_ratio"])
    search_back = lookback * int(cfg["swing_search_window_mult"])
    atr_now = _safe_float(d.at[idx_now, "atr"])
    if atr_now <= 0:
        return None

    period_col = "_period"
    period_val = d.at[idx_now, period_col]
    period_mask = d[period_col] == period_val
    start_idx = int(d.index[period_mask][0])
    period = d.loc[start_idx:idx_now]

    hi_touch_idxs = [i for i in period.index if _safe_float(period.at[i, "high"]) >= hi_level * (1 - tol)]
    lo_touch_idxs = [i for i in period.index if _safe_float(period.at[i, "low"]) <= lo_level * (1 + tol)]
    hi_break_idxs = [i for i in period.index if _safe_float(period.at[i, "close"]) > hi_level * (1 + brk)]
    lo_break_idxs = [i for i in period.index if _safe_float(period.at[i, "close"]) < lo_level * (1 - brk)]

    first_hi = hi_touch_idxs[0] if hi_touch_idxs else None
    first_lo = lo_touch_idxs[0] if lo_touch_idxs else None

    curr_row = d.loc[idx_now]
    close_now = _safe_float(curr_row.get("close"))

    if _in_dead_zone(period, idx_now, close_now, hi_level, lo_level, eq,
                      hi_touch_idxs, lo_touch_idxs, cfg):
        return None

    candidates = []

    def add_candidate(code, direction, sl, tp, tp_partial, extra_reason, touch_count):
        base = cfg["base_scores"][code]
        bonus, penalty, notes = _dynamic_bonus_penalty(
            d, idx_now, 1 if direction == "BUY" else -1, cfg, touch_count, scenario_code=code
        )
        total = max(0.0, min(cfg["max_score"], base + bonus - penalty))
        reasons = [extra_reason] + notes
        entry_price = close_now
        opposite_level = hi_level if direction == "BUY" else lo_level
        extension_target = tp if code in ("B5", "S5") else None
        ladder = _build_tp_ladder(direction, entry_price, eq, opposite_level, extension_target or tp, cfg)
        candidates.append({
            "code": code, "direction": direction,
            "base_score": base, "bonus": round(bonus, 1), "penalty": round(penalty, 1),
            "total_score": round(total, 1),
            "entry": entry_price, "sl": sl, "tp": tp, "tp_partial": tp_partial,
            "level_label": label, "reasons": reasons,
            "tp_ladder": ladder,
        })

    recent_swing_lows = _recent_confirmed_swings(d, idx_now, lookback, "swing_low", search_back)
    bullish_confirm_now = _is_bullish_confirm(curr_row, min_body)

    if first_hi is not None and first_lo is not None and first_hi < first_lo and bullish_confirm_now and recent_swing_lows:
        swing_idx = recent_swing_lows[-1]
        swing_price = _safe_float(d.at[swing_idx, "low"])
        if swing_price <= lo_level * (1 + tol * 5) and idx_now - swing_idx <= lookback + 3:
            sl = min(swing_price, lo_level) - atr_now * cfg["sl_atr_buffer"]
            add_candidate("B1", "BUY", sl, hi_level, eq,
                           f"سوییپ {label.split('/')[0]} سپس سوییپ {label.split('/')[1]} و بازگشت صعودی",
                           len(lo_touch_idxs))

    if first_lo is not None and (first_hi is None or first_hi > first_lo) and bullish_confirm_now and recent_swing_lows:
        swing_idx = recent_swing_lows[-1]
        swing_price = _safe_float(d.at[swing_idx, "low"])
        if swing_price <= lo_level * (1 + tol * 5) and idx_now - swing_idx <= lookback + 3:
            sl = min(swing_price, lo_level) - atr_now * cfg["sl_atr_buffer"]
            add_candidate("B3", "BUY", sl, hi_level, eq,
                           f"سوییپ مستقیم {label.split('/')[1]} بدون عبور قبلی از {label.split('/')[0]}",
                           len(lo_touch_idxs))

    if first_lo is not None:
        eq_cross_idxs = [i for i in period.index if i > start_idx and i > first_lo
                          and _safe_float(d.at[i - 1, "close"]) < eq <= _safe_float(d.at[i, "close"])]
        if eq_cross_idxs and eq_cross_idxs[-1] >= idx_now - 1 and bullish_confirm_now:
            swing_idx = recent_swing_lows[-1] if recent_swing_lows else None
            swing_price = _safe_float(d.at[swing_idx, "low"]) if swing_idx is not None else eq
            sl = min(swing_price, eq) - atr_now * cfg["sl_atr_buffer"]
            add_candidate("B4", "BUY", sl, hi_level, None,
                           "ری‌کلیم تاییدشده EQ به سمت بالا پس از سوییپ کف رنج",
                           len(lo_touch_idxs))

    if first_hi is not None and bullish_confirm_now:
        swings_after = [i for i in recent_swing_lows if i > first_hi]
        if len(swings_after) >= 2 and _safe_float(d.at[swings_after[-1], "low"]) > _safe_float(d.at[swings_after[-2], "low"]):
            if idx_now - swings_after[-1] <= lookback + 3:
                swing_price = _safe_float(d.at[swings_after[-1], "low"])
                sl = swing_price - atr_now * cfg["sl_atr_buffer"]
                add_candidate("B2", "BUY", sl, hi_level, None,
                               "سوییپ مقاومت + پولبک مضاعف با کف بالاتر (سوئینگ نزدیک مقاومت)",
                               len(hi_touch_idxs))

    if hi_break_idxs and bullish_confirm_now:
        first_break = hi_break_idxs[0]
        after_break = period.loc[first_break:idx_now]
        min_close_after = _safe_float(after_break["close"].min()) if len(after_break) else None
        retested = any(_safe_float(after_break.at[i, "low"]) <= hi_level * (1 + tol) for i in after_break.index)
        if retested and min_close_after is not None and min_close_after >= hi_level * (1 - tol):
            sl = hi_level - atr_now * cfg["sl_atr_buffer_tight"]
            tp_ext = hi_level + (hi_level - lo_level) * cfg["extension_atr_mult"]
            add_candidate("B5", "BUY", sl, tp_ext, None,
                           f"بریک‌اند‌ریتست {label.split('/')[0]} (تبدیل مقاومت شکسته به حمایت)",
                           len(hi_touch_idxs))

    if first_lo is None and close_now < eq and bullish_confirm_now and recent_swing_lows:
        swing_idx = recent_swing_lows[-1]
        swing_price = _safe_float(d.at[swing_idx, "low"])
        if lo_level < swing_price < eq and idx_now - swing_idx <= lookback + 3:
            sl = swing_price - atr_now * cfg["sl_atr_buffer"]
            add_candidate("B6", "BUY", sl, hi_level, eq,
                           "ورود در ناحیه دیسکانت (زیر EQ) بدون لمس دقیق کف رنج",
                           len(lo_touch_idxs))

    recent_swing_highs = _recent_confirmed_swings(d, idx_now, lookback, "swing_high", search_back)
    bearish_confirm_now = _is_bearish_confirm(curr_row, min_body)

    if first_lo is not None and first_hi is not None and first_lo < first_hi and bearish_confirm_now and recent_swing_highs:
        swing_idx = recent_swing_highs[-1]
        swing_price = _safe_float(d.at[swing_idx, "high"])
        if swing_price >= hi_level * (1 - tol * 5) and idx_now - swing_idx <= lookback + 3:
            sl = max(swing_price, hi_level) + atr_now * cfg["sl_atr_buffer"]
            add_candidate("S1", "SELL", sl, lo_level, eq,
                           f"سوییپ {label.split('/')[1]} سپس سوییپ {label.split('/')[0]} و بازگشت نزولی",
                           len(hi_touch_idxs))

    if first_hi is not None and (first_lo is None or first_lo > first_hi) and bearish_confirm_now and recent_swing_highs:
        swing_idx = recent_swing_highs[-1]
        swing_price = _safe_float(d.at[swing_idx, "high"])
        if swing_price >= hi_level * (1 - tol * 5) and idx_now - swing_idx <= lookback + 3:
            sl = max(swing_price, hi_level) + atr_now * cfg["sl_atr_buffer"]
            add_candidate("S3", "SELL", sl, lo_level, eq,
                           f"سوییپ مستقیم {label.split('/')[0]} بدون عبور قبلی از {label.split('/')[1]}",
                           len(hi_touch_idxs))

    if first_hi is not None:
        eq_cross_idxs = [i for i in period.index if i > start_idx and i > first_hi
                          and _safe_float(d.at[i - 1, "close"]) > eq >= _safe_float(d.at[i, "close"])]
        if eq_cross_idxs and eq_cross_idxs[-1] >= idx_now - 1 and bearish_confirm_now:
            swing_idx = recent_swing_highs[-1] if recent_swing_highs else None
            swing_price = _safe_float(d.at[swing_idx, "high"]) if swing_idx is not None else eq
            sl = max(swing_price, eq) + atr_now * cfg["sl_atr_buffer"]
            add_candidate("S4", "SELL", sl, lo_level, None,
                           "ری‌کلیم تاییدشده EQ به سمت پایین پس از سوییپ سقف رنج",
                           len(hi_touch_idxs))

    if first_lo is not None and bearish_confirm_now:
        swings_after = [i for i in recent_swing_highs if i > first_lo]
        if len(swings_after) >= 2 and _safe_float(d.at[swings_after[-1], "high"]) < _safe_float(d.at[swings_after[-2], "high"]):
            if idx_now - swings_after[-1] <= lookback + 3:
                swing_price = _safe_float(d.at[swings_after[-1], "high"])
                sl = swing_price + atr_now * cfg["sl_atr_buffer"]
                add_candidate("S2", "SELL", sl, lo_level, None,
                               "سوییپ حمایت + پولبک مضاعف با سقف پایین‌تر (سوئینگ نزدیک حمایت)",
                               len(lo_touch_idxs))

    if lo_break_idxs and bearish_confirm_now:
        first_break = lo_break_idxs[0]
        after_break = period.loc[first_break:idx_now]
        max_close_after = _safe_float(after_break["close"].max()) if len(after_break) else None
        retested = any(_safe_float(after_break.at[i, "high"]) >= lo_level * (1 - tol) for i in after_break.index)
        if retested and max_close_after is not None and max_close_after <= lo_level * (1 + tol):
            sl = lo_level + atr_now * cfg["sl_atr_buffer_tight"]
            tp_ext = lo_level - (hi_level - lo_level) * cfg["extension_atr_mult"]
            add_candidate("S5", "SELL", sl, tp_ext, None,
                           f"بریک‌اند‌ریتست {label.split('/')[1]} (تبدیل حمایت شکسته به مقاومت)",
                           len(lo_touch_idxs))

    if first_hi is None and close_now > eq and bearish_confirm_now and recent_swing_highs:
        swing_idx = recent_swing_highs[-1]
        swing_price = _safe_float(d.at[swing_idx, "high"])
        if eq < swing_price < hi_level and idx_now - swing_idx <= lookback + 3:
            sl = swing_price + atr_now * cfg["sl_atr_buffer"]
            add_candidate("S6", "SELL", sl, lo_level, eq,
                           "ورود در ناحیه پریمیوم (بالای EQ) بدون لمس دقیق سقف رنج",
                           len(hi_touch_idxs))

    if not candidates:
        return None

    best = max(candidates, key=lambda c: c["total_score"])
    return best
