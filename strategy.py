import pandas as pd
import numpy as np

FILTER_DEFAULTS = {
    "volume_filter": True,
    "trailing_stop": True,
    "candlestick_filter": True,
    "no_short_filter": False,
    "no_buy_filter": False,
}

STRATEGY_DEFAULTS = {
    "min_adx": 20.0,
    "sl_multiplier": 1.5,
    "tp_multiplier": 2.0,
}

# Legacy compatibility only. Production code passes per-user dictionaries.
FILTERS = FILTER_DEFAULTS.copy()
STRATEGY_CONFIG = STRATEGY_DEFAULTS.copy()


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


def get_strategy_params(timeframe="5min", strategy_config=None):
    c = _cfg(strategy_config)
    return {
        "adx": float(c.get("min_adx", 20.0)),
        "sl": float(c.get("sl_multiplier", 1.5)),
        "tp": float(c.get("tp_multiplier", 2.0)),
    }


def get_strategy_description(timeframe="5min", strategy_config=None, filters=None):
    p = get_strategy_params(timeframe, strategy_config)
    f = _flt(filters)
    return (
        f"📊 *استراتژی فعال ({'مولتی' if timeframe == 'multi' else timeframe})*\n\n"
        f"• ADX: `{p['adx']:.1f}`\n"
        f"• SL: `{p['sl']:.1f} ATR`\n"
        f"• TP: `{p['tp']:.1f} ATR`\n"
        f"• حجم: `{'🟢' if f.get('volume_filter', True) else '🔴'}`\n"
        f"• کندل: `{'🟢' if f.get('candlestick_filter', True) else '🔴'}`\n"
        f"• حد ضرر دنبال‌کننده: `{'🟢' if f.get('trailing_stop', True) else '🔴'}`"
    )


def check_volume(df, index=-2, filters=None, minimum_ratio=1.0):
    f = _flt(filters)
    if not f.get("volume_filter", True):
        return True, "فیلتر حجم خاموش است"
    if "volume_ratio" not in df.columns:
        return True, "داده حجم در دسترس نیست"
    ratio = _safe_float(df.iloc[index].get("volume_ratio"), 0)
    if ratio < minimum_ratio:
        return False, f"حجم کم است ({ratio:.2f}x)"
    return True, f"حجم تأیید شد ({ratio:.2f}x)"


def check_candlestick_confirmation(df, filters=None):
    f = _flt(filters)
    curr = df.iloc[-2]
    prev = df.iloc[-3]
    vol_ok, vol_reason = check_volume(df, -2, f, 1.0)
    if not vol_ok:
        return None, vol_reason
    if not f.get("candlestick_filter", True):
        return "CONFIRMED", "فیلتر کندلی خاموش است"

    body = _safe_float(curr["candle_body"], abs(curr["close"] - curr["open"]))
    rng = max(_safe_float(curr["candle_range"], curr["high"] - curr["low"]), 1e-12)
    upper = curr["high"] - max(curr["close"], curr["open"])
    lower = min(curr["close"], curr["open"]) - curr["low"]
    bullish_pin = lower >= 2 * max(body, 1e-12) and upper <= max(body * 1.2, 1e-12) and curr["close"] > curr["open"]
    bearish_pin = upper >= 2 * max(body, 1e-12) and lower <= max(body * 1.2, 1e-12) and curr["close"] < curr["open"]
    prev_body = abs(prev["close"] - prev["open"])
    bull_engulf = prev["close"] < prev["open"] and curr["close"] > curr["open"] and curr["close"] >= prev["open"] and curr["open"] <= prev["close"] and body > prev_body
    bear_engulf = prev["close"] > prev["open"] and curr["close"] < curr["open"] and curr["close"] <= prev["open"] and curr["open"] >= prev["close"] and body > prev_body
    strong_bull = curr["close"] > curr["open"] and body / rng >= 0.60
    strong_bear = curr["close"] < curr["open"] and body / rng >= 0.60

    if bullish_pin or bull_engulf or strong_bull:
        name = "پین‌بار صعودی" if bullish_pin else "انگالفینگ صعودی" if bull_engulf else "کندل صعودی قدرتمند"
        return "BUY_CONFIRMED", name
    if bearish_pin or bear_engulf or strong_bear:
        name = "پین‌بار نزولی" if bearish_pin else "انگالفینگ نزولی" if bear_engulf else "کندل نزولی قدرتمند"
        return "SELL_CONFIRMED", name
    return None, "کندل تأیید معتبر نبود"


def strategy_trend_following(df, timeframe="5min", filters=None, strategy_config=None):
    curr, prev = df.iloc[-2], df.iloc[-3]
    p = get_strategy_params(timeframe, strategy_config)
    adx, atr = _safe_float(curr.get("adx")), _safe_float(curr.get("atr"))
    if atr <= 0 or adx < p["adx"]:
        return None, f"روند ضعیف است (ADX={adx:.1f})"
    up = curr["close"] > curr["ema50"] and curr["ema20"] > curr["ema50"] and curr["plus_di"] > curr["minus_di"]
    down = curr["close"] < curr["ema50"] and curr["ema20"] < curr["ema50"] and curr["minus_di"] > curr["plus_di"]
    ema = _safe_float(prev["ema20"])
    touch_buy = prev["low"] <= ema + atr * 0.25 and prev["high"] >= ema - atr * 0.5
    touch_sell = prev["high"] >= ema - atr * 0.25 and prev["low"] <= ema + atr * 0.5
    f = _flt(filters)

    if up and touch_buy and curr["close"] > curr["ema20"]:
        if not f.get("candlestick_filter", True):
            ok, reason = check_volume(df, -2, f)
            return ("BUY", f"روندی خرید | {reason}") if ok else (None, reason)
        sig, reason = check_candlestick_confirmation(df, f)
        return ("BUY", f"روندی خرید + {reason}") if sig in ("BUY_CONFIRMED", "CONFIRMED") else (None, reason)
    if down and touch_sell and curr["close"] < curr["ema20"]:
        if not f.get("candlestick_filter", True):
            ok, reason = check_volume(df, -2, f)
            return ("SELL", f"روندی فروش | {reason}") if ok else (None, reason)
        sig, reason = check_candlestick_confirmation(df, f)
        return ("SELL", f"روندی فروش + {reason}") if sig in ("SELL_CONFIRMED", "CONFIRMED") else (None, reason)
    return None, "شرایط روندی برقرار نیست"


def strategy_breakout(df, filters=None, strategy_config=None):
    curr, prev = df.iloc[-2], df.iloc[-3]
    if pd.isna(curr.get("channel_high")) or pd.isna(curr.get("channel_low")):
        return None, "کانال آماده نیست"
    f = _flt(filters)
    p = get_strategy_params("5min", strategy_config)
    adx = _safe_float(curr.get("adx"))
    if adx < max(15.0, p["adx"] - 5):
        return None, f"ADX پایین است ({adx:.1f})"
    vr = _safe_float(curr.get("volume_ratio"), 0)
    if f.get("volume_filter", True) and vr < 1.15:
        return None, f"حجم شکست کافی نیست ({vr:.2f}x)"
    if _safe_float(curr.get("body_ratio"), 0) < 0.55:
        return None, "قدرت بدنه کافی نیست"
    bull = curr["close"] > curr["channel_high"] and prev["close"] <= prev.get("channel_high", np.inf)
    bear = curr["close"] < curr["channel_low"] and prev["close"] >= prev.get("channel_low", -np.inf)
    if not (bull or bear):
        return None, "شکست جدیدی ثبت نشد"
    if not f.get("candlestick_filter", True):
        return ("BUY", "شکست صعودی تأیید شد") if bull else ("SELL", "شکست نزولی تأیید شد")
    sig, reason = check_candlestick_confirmation(df, f)
    if bull and sig in ("BUY_CONFIRMED", "CONFIRMED"):
        return "BUY", f"شکست صعودی + {reason}"
    if bear and sig in ("SELL_CONFIRMED", "CONFIRMED"):
        return "SELL", f"شکست نزولی + {reason}"
    return None, reason


def strategy_mean_reversion(df, filters=None, strategy_config=None):
    curr = df.iloc[-2]
    rsi, adx = _safe_float(curr.get("rsi"), 50), _safe_float(curr.get("adx"), 50)
    p = get_strategy_params("5min", strategy_config)
    if adx >= p["adx"]:
        return None, f"روند برای Mean Reversion قوی است (ADX={adx:.1f})"
    atr = _safe_float(curr.get("atr"), 0)
    if abs(curr["close"] - curr["ema20"]) > max(atr * 1.5, 1e-12):
        return None, "قیمت از محدوده میانگین دور است"
    ok, reason = check_volume(df, -2, _flt(filters), 0.8)
    if not ok:
        return None, reason
    f = _flt(filters)
    if rsi < 30:
        if f.get("candlestick_filter", True):
            sig, desc = check_candlestick_confirmation(df, f)
            if sig not in ("BUY_CONFIRMED", "CONFIRMED"):
                return None, f"RSI اشباع فروش ولی برگشت تأیید نشده ({desc})"
        return "BUY", f"بازگشت به میانگین خرید | RSI={rsi:.1f}"
    if rsi > 70:
        if f.get("candlestick_filter", True):
            sig, desc = check_candlestick_confirmation(df, f)
            if sig not in ("SELL_CONFIRMED", "CONFIRMED"):
                return None, f"RSI اشباع خرید ولی برگشت تأیید نشده ({desc})"
        return "SELL", f"بازگشت به میانگین فروش | RSI={rsi:.1f}"
    return None, f"RSI خنثی است ({rsi:.1f})"


def strategy_multi_tf(df_primary, market_data_dict, timeframe="5min", filters=None, strategy_config=None):
    required = ["1d", "4h", "1h", "15m"]
    missing = [x for x in required if (market_data_dict or {}).get(x) is None or (market_data_dict or {}).get(x).empty]
    if missing:
        return None, f"تایم‌فریم‌های لازم موجود نیست: {', '.join(missing)}"
    c = df_primary.iloc[-2]
    up = c["close"] > c["ema50"] and c["ema20"] > c["ema50"] and c["plus_di"] > c["minus_di"]
    down = c["close"] < c["ema50"] and c["ema20"] < c["ema50"] and c["minus_di"] > c["plus_di"]
    if not (up or down):
        return None, "روند تایم اصلی مشخص نیست"
    for tf in required:
        h = market_data_dict[tf].iloc[-2]
        h_adx = _safe_float(h.get("adx"))
        if h_adx < max(15.0, get_strategy_params(timeframe, strategy_config)["adx"] - 5):
            return None, f"ADX تایم {tf} ضعیف است ({h_adx:.1f})"
        if up and not (h["close"] > h["ema50"] and h["ema20"] >= h["ema50"] and h["plus_di"] >= h["minus_di"]):
            return None, f"عدم هم‌راستایی Long در {tf}"
        if down and not (h["close"] < h["ema50"] and h["ema20"] <= h["ema50"] and h["minus_di"] >= h["plus_di"]):
            return None, f"عدم هم‌راستایی Short در {tf}"
    sig, reason = strategy_trend_following(df_primary, timeframe, filters, strategy_config)
    return (sig, f"چندزمانه | {reason}") if sig else (None, reason)


def strategy_dynamic(df_primary, market_data_dict=None, timeframe="5min", filters=None, strategy_config=None):
    c = df_primary.iloc[-2]
    adx = _safe_float(c.get("adx"), 20)
    min_adx = get_strategy_params(timeframe, strategy_config)["adx"]
    if market_data_dict:
        # In multi mode, first require full alignment before taking any directional signal.
        if timeframe == "5min" and all((market_data_dict.get(k) is not None and not market_data_dict[k].empty) for k in ["1d", "4h", "1h", "15m"]):
            multi_sig, multi_reason = strategy_multi_tf(df_primary, market_data_dict, timeframe, filters, strategy_config)
            if multi_sig:
                return multi_sig, f"[پویا-چندزمانه] {multi_reason}"
    break_sig, break_reason = strategy_breakout(df_primary, filters, strategy_config)
    if break_sig:
        return break_sig, f"[شکست] {break_reason}"
    if adx >= min_adx + 5:
        sig, reason = strategy_trend_following(df_primary, timeframe, filters, strategy_config)
        return sig, f"[رونددار] {reason}"
    if adx < min_adx:
        sig, reason = strategy_mean_reversion(df_primary, filters, strategy_config)
        return sig, f"[رنج] {reason}"
    return None, f"[گذار] ADX={adx:.1f}"


def get_signal_with_reason(df_primary, market_data_dict=None, timeframe_mode="single", timeframe="5min", strategy_type="trend", filters=None, strategy_config=None):
    if df_primary is None or df_primary.empty or len(df_primary) < 60:
        return None, "داده کافی نیست"
    st = strategy_type
    if st == "trend":
        return strategy_trend_following(df_primary, timeframe, filters, strategy_config)
    if st == "breakout":
        return strategy_breakout(df_primary, filters, strategy_config)
    if st == "mean_reversion":
        return strategy_mean_reversion(df_primary, filters, strategy_config)
    if st == "multi":
        return strategy_multi_tf(df_primary, market_data_dict, timeframe, filters, strategy_config)
    if st == "dynamic":
        return strategy_dynamic(df_primary, market_data_dict, timeframe, filters, strategy_config)
    return strategy_trend_following(df_primary, timeframe, filters, strategy_config)


def get_signal(df_primary, market_data_dict=None, timeframe_mode="single", timeframe="5min", strategy_type="trend", filters=None, strategy_config=None):
    sig, _ = get_signal_with_reason(df_primary, market_data_dict, timeframe_mode, timeframe, strategy_type, filters, strategy_config)
    return sig
