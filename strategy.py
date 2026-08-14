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

# Backward-compatible globals. New code should pass per-user values.
FILTERS = FILTER_DEFAULTS.copy()
STRATEGY_CONFIG = STRATEGY_DEFAULTS.copy()


def _safe_float(value, default=0.0):
    try:
        v = float(value)
        return v if np.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate EMA, Wilder-style ATR/ADX, RSI and breakout channels."""
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df.copy()

    df = df.copy()
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns) or len(df) < 30:
        return df

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["open", "high", "low", "close"]).copy()
    if len(df) < 30:
        return df

    # EMA
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()

    # True Range
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["tr"] = tr

    # Wilder ATR
    df["atr"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    # Wilder Directional Movement
    up_move = df["high"].diff()
    down_move = -df["low"].diff()

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=df.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=df.index,
    )

    atr14 = df["atr"]
    plus_di = 100 * plus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / (atr14 + 1e-12)
    minus_di = 100 * minus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / (atr14 + 1e-12)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-12)
    df["adx"] = dx.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    df["plus_di"] = plus_di
    df["minus_di"] = minus_di

    # RSI - Wilder-style smoothing
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = avg_gain / (avg_loss + 1e-12)
    df["rsi"] = 100 - (100 / (1 + rs))

    # Breakout channel excludes the current candle.
    df["channel_high"] = df["high"].rolling(20, min_periods=20).max().shift(1)
    df["channel_low"] = df["low"].rolling(20, min_periods=20).min().shift(1)

    # Relative volume
    df["volume_ma20"] = df["volume"].rolling(20, min_periods=20).mean()
    df["volume_ratio"] = df["volume"] / (df["volume_ma20"] + 1e-12)

    # Candle metrics
    df["candle_body"] = (df["close"] - df["open"]).abs()
    df["candle_range"] = (df["high"] - df["low"]).clip(lower=1e-12)
    df["body_ratio"] = df["candle_body"] / df["candle_range"]

    return df


def get_strategy_params(timeframe, strategy_config=None):
    cfg = strategy_config or STRATEGY_CONFIG
    return {
        "adx": float(cfg.get("min_adx", STRATEGY_DEFAULTS["min_adx"])),
        "sl": float(cfg.get("sl_multiplier", STRATEGY_DEFAULTS["sl_multiplier"])),
        "tp": float(cfg.get("tp_multiplier", STRATEGY_DEFAULTS["tp_multiplier"])),
    }


def get_strategy_description(timeframe, strategy_config=None, filters=None):
    params = get_strategy_params(timeframe, strategy_config)
    flt = filters or FILTERS
    return (
        f"📊 *تشریح استراتژی و پارامترهای فعال ({timeframe})*\n\n"
        f"• **آستانه قدرت روند (ADX):** `{params['adx']:.1f}`\n"
        f"• **حد ضرر (SL):** `{params['sl']:.1f}` برابر ATR\n"
        f"• **حد سود (TP):** `{params['tp']:.1f}` برابر ATR\n"
        f"• **فیلتر حجم:** `{'🟢 فعال' if flt.get('volume_filter', True) else '🔴 غیرفعال'}`\n"
        f"• **تریلینگ استاپ:** `{'🟢 فعال' if flt.get('trailing_stop', True) else '🔴 غیرفعال'}`\n"
        f"• **تأیید کندلی:** `{'🟢 فعال' if flt.get('candlestick_filter', True) else '🔴 غیرفعال'}`"
    )


def check_volume(df, index=-2, filters=None, minimum_ratio=1.0):
    flt = filters or FILTERS
    if not flt.get("volume_filter", True):
        return True, None
    if "volume_ma20" not in df.columns:
        return True, None
    curr = df.iloc[index]
    avg_vol = _safe_float(curr.get("volume_ma20"), 0.0)
    volume = _safe_float(curr.get("volume"), 0.0)
    if avg_vol <= 0:
        return True, None
    ratio = volume / avg_vol
    if ratio < minimum_ratio:
        return False, f"حجم پایین است (نسبت به میانگین: {ratio:.2f}x)"
    return True, f"حجم تأیید شد ({ratio:.2f}x میانگین)"


def check_candlestick_confirmation(df, filters=None):
    flt = filters or FILTERS
    curr = df.iloc[-2]
    prev = df.iloc[-3]

    vol_ok, vol_reason = check_volume(df, -2, flt, minimum_ratio=1.0)
    if not vol_ok:
        return None, vol_reason

    if not flt.get("candlestick_filter", True):
        return "CONFIRMED", "فیلتر کندلی غیرفعال است"

    body = abs(curr["close"] - curr["open"])
    total_range = max(curr["high"] - curr["low"], 1e-12)
    upper_shadow = curr["high"] - max(curr["close"], curr["open"])
    lower_shadow = min(curr["close"], curr["open"]) - curr["low"]

    is_bullish_pin = (
        lower_shadow >= 2 * max(body, 1e-12)
        and upper_shadow <= max(body * 1.2, 1e-12)
        and curr["close"] > curr["open"]
    )
    is_bearish_pin = (
        upper_shadow >= 2 * max(body, 1e-12)
        and lower_shadow <= max(body * 1.2, 1e-12)
        and curr["close"] < curr["open"]
    )

    prev_body = abs(prev["close"] - prev["open"])
    is_bullish_engulfing = (
        prev["close"] < prev["open"]
        and curr["close"] > curr["open"]
        and curr["close"] >= prev["open"]
        and curr["open"] <= prev["close"]
        and body > prev_body
    )
    is_bearish_engulfing = (
        prev["close"] > prev["open"]
        and curr["close"] < curr["open"]
        and curr["close"] <= prev["open"]
        and curr["open"] >= prev["close"]
        and body > prev_body
    )

    # Strong body fallback: helps trend continuation when no classic pattern exists.
    strong_bull = curr["close"] > curr["open"] and (body / total_range) >= 0.60
    strong_bear = curr["close"] < curr["open"] and (body / total_range) >= 0.60

    if is_bullish_pin or is_bullish_engulfing or strong_bull:
        if is_bullish_pin:
            name = "پین‌بار صعودی"
        elif is_bullish_engulfing:
            name = "انگالفینگ صعودی"
        else:
            name = "کندل صعودی قدرتمند"
        return "BUY_CONFIRMED", name

    if is_bearish_pin or is_bearish_engulfing or strong_bear:
        if is_bearish_pin:
            name = "پین‌بار نزولی"
        elif is_bearish_engulfing:
            name = "انگالفینگ نزولی"
        else:
            name = "کندل نزولی قدرتمند"
        return "SELL_CONFIRMED", name

    return None, "کندل تأیید معتبر ثبت نشد"


def strategy_trend_following(df, timeframe="5min", filters=None, strategy_config=None):
    curr = df.iloc[-2]
    prev = df.iloc[-3]
    params = get_strategy_params(timeframe, strategy_config)

    adx = _safe_float(curr.get("adx"), 0)
    atr = _safe_float(curr.get("atr"), 0)
    if atr <= 0:
        return None, "ATR معتبر نیست"
    if adx < params["adx"]:
        return None, f"رد شد: قدرت روند کم (ADX = {adx:.1f})"

    is_uptrend = curr["close"] > curr["ema50"] and curr["ema20"] > curr["ema50"] and curr.get("plus_di", 0) > curr.get("minus_di", 0)
    is_downtrend = curr["close"] < curr["ema50"] and curr["ema20"] < curr["ema50"] and curr.get("minus_di", 0) > curr.get("plus_di", 0)

    ema_val = _safe_float(prev["ema20"])
    tolerance = atr * 0.25
    touch_ema_buy = prev["low"] <= ema_val + tolerance and prev["high"] >= ema_val - (atr * 0.5)
    touch_ema_sell = prev["high"] >= ema_val - tolerance and prev["low"] <= ema_val + (atr * 0.5)

    flt = filters or FILTERS
    if is_uptrend and touch_ema_buy and curr["close"] > curr["ema20"]:
        if not flt.get("candlestick_filter", True):
            vol_ok, reason = check_volume(df, -2, flt)
            if vol_ok:
                return "BUY", f"خرید Trend: برگشت/تست EMA20 + ADX={adx:.1f}"
            return None, reason or "فیلتر حجم رد کرد"
        candle_signal, pattern_desc = check_candlestick_confirmation(df, flt)
        if candle_signal in ("BUY_CONFIRMED", "CONFIRMED"):
            return "BUY", f"خرید Trend + {pattern_desc}: تست موفق EMA20 و ADX={adx:.1f}"
        return None, f"رد شد (صعودی): {pattern_desc}"

    if is_downtrend and touch_ema_sell and curr["close"] < curr["ema20"]:
        if not flt.get("candlestick_filter", True):
            vol_ok, reason = check_volume(df, -2, flt)
            if vol_ok:
                return "SELL", f"فروش Trend: برگشت/تست EMA20 + ADX={adx:.1f}"
            return None, reason or "فیلتر حجم رد کرد"
        candle_signal, pattern_desc = check_candlestick_confirmation(df, flt)
        if candle_signal in ("SELL_CONFIRMED", "CONFIRMED"):
            return "SELL", f"فروش Trend + {pattern_desc}: تست موفق EMA20 و ADX={adx:.1f}"
        return None, f"رد شد (نزولی): {pattern_desc}"

    return None, "شرایط روندپیروی برقرار نیست."


def strategy_breakout(df, filters=None, strategy_config=None):
    curr = df.iloc[-2]
    prev = df.iloc[-3]
    flt = filters or FILTERS
    adx_threshold = get_strategy_params("5min", strategy_config)["adx"]

    if pd.isna(curr.get("channel_high")) or pd.isna(curr.get("channel_low")):
        return None, "کانال ۲۰ کندلی هنوز آماده نیست."

    vol_ok, vol_reason = check_volume(df, -2, flt, minimum_ratio=1.15)
    if not vol_ok:
        return None, vol_reason or "حجم کافی نیست"

    body_ratio = _safe_float(curr.get("body_ratio"), 0)
    if body_ratio < 0.55:
        return None, "قدرت بدنه برای شکست کافی نیست"

    # Require some trend/expansion context but allow genuine early breakouts.
    if _safe_float(curr.get("adx"), 0) < max(15.0, adx_threshold - 5):
        return None, f"ADX برای شکست کافی نیست ({_safe_float(curr.get('adx'), 0):.1f})"

    bull_break = curr["close"] > curr["channel_high"] and prev["close"] <= prev.get("channel_high", np.inf)
    bear_break = curr["close"] < curr["channel_low"] and prev["close"] >= prev.get("channel_low", -np.inf)

    if not flt.get("candlestick_filter", True):
        if bull_break:
            return "BUY", "خرید Breakout: شکست سقف کانال + حجم/بدنه تأیید شد"
        if bear_break:
            return "SELL", "فروش Breakout: شکست کف کانال + حجم/بدنه تأیید شد"
    else:
        candle_signal, pattern_desc = check_candlestick_confirmation(df, flt)
        # For breakout, a strong directional candle is acceptable; classic reversal candles are optional.
        if bull_break and candle_signal in ("BUY_CONFIRMED", "CONFIRMED"):
            return "BUY", f"خرید Breakout + {pattern_desc}: شکست معتبر سقف کانال"
        if bear_break and candle_signal in ("SELL_CONFIRMED", "CONFIRMED"):
            return "SELL", f"فروش Breakout + {pattern_desc}: شکست معتبر کف کانال"

    return None, "شکست معتبر کانال ثبت نشد."


def strategy_mean_reversion(df, filters=None, strategy_config=None):
    curr = df.iloc[-2]
    rsi = _safe_float(curr.get("rsi"), 50)
    adx = _safe_float(curr.get("adx"), 50)
    flt = filters or FILTERS

    # Avoid fading strong trends.
    min_adx = get_strategy_params("5min", strategy_config)["adx"]
    if adx >= min_adx:
        return None, f"برای Mean Reversion روند بیش از حد قوی است (ADX={adx:.1f})"

    near_ema = abs(curr["close"] - curr["ema20"]) <= max(curr.get("atr", 0) * 1.5, 1e-12)
    if not near_ema:
        return None, "قیمت برای بازگشت به میانگین در محدوده مناسب نیست"

    vol_ok, vol_reason = check_volume(df, -2, flt, minimum_ratio=0.8)
    if not vol_ok:
        return None, vol_reason or "حجم نامناسب"

    if rsi < 30:
        if flt.get("candlestick_filter", True):
            candle_signal, desc = check_candlestick_confirmation(df, flt)
            if candle_signal not in ("BUY_CONFIRMED", "CONFIRMED"):
                return None, f"RSI اشباع فروش است ولی تأیید برگشتی نداریم ({desc})"
        else:
            desc = f"RSI={rsi:.1f}"
        return "BUY", f"خرید Mean Reversion: اشباع فروش + تأیید برگشت ({desc})"

    if rsi > 70:
        if flt.get("candlestick_filter", True):
            candle_signal, desc = check_candlestick_confirmation(df, flt)
            if candle_signal not in ("SELL_CONFIRMED", "CONFIRMED"):
                return None, f"RSI اشباع خرید است ولی تأیید برگشتی نداریم ({desc})"
        else:
            desc = f"RSI={rsi:.1f}"
        return "SELL", f"فروش Mean Reversion: اشباع خرید + تأیید برگشت ({desc})"

    return None, f"محدوده RSI خنثی است ({rsi:.1f})."


def strategy_multi_tf(df_primary, market_data_dict, timeframe="5min", filters=None, strategy_config=None):
    curr = df_primary.iloc[-2]
    close = _safe_float(curr["close"])
    ema50 = _safe_float(curr["ema50"])
    is_uptrend = close > ema50 and curr["ema20"] > curr["ema50"]
    is_downtrend = close < ema50 and curr["ema20"] < curr["ema50"]

    if not is_uptrend and not is_downtrend:
        return None, "روند اولیه در تایم اصلی مشخص نیست."

    alignments = []
    for tf in ["1d", "4h", "1h", "15m"]:
        df_tf = (market_data_dict or {}).get(tf)
        if df_tf is None or df_tf.empty or len(df_tf) < 30:
            continue
        h = df_tf.iloc[-2]
        h_close = _safe_float(h.get("close"))
        h_ema20 = _safe_float(h.get("ema20"))
        h_ema50 = _safe_float(h.get("ema50"))
        h_adx = _safe_float(h.get("adx"))
        if is_uptrend:
            ok = h_close > h_ema50 and h_ema20 >= h_ema50 and h_close >= h_ema20
        else:
            ok = h_close < h_ema50 and h_ema20 <= h_ema50 and h_close <= h_ema20
        if not ok:
            return None, f"رد شد: عدم هم‌راستایی در تایم بالاتر ({tf}, ADX={h_adx:.1f})"
        alignments.append(tf)

    if not alignments:
        return None, "داده کافی برای تأیید Multi-TF وجود ندارد."

    sig, reason = strategy_trend_following(df_primary, timeframe, filters, strategy_config)
    if sig:
        return sig, f"{reason} | تأیید تایم‌های بالاتر: {', '.join(alignments)}"
    return None, reason


def strategy_dynamic(df_primary, market_data_dict=None, timeframe="5min", filters=None, strategy_config=None):
    curr = df_primary.iloc[-2]
    adx = _safe_float(curr.get("adx"), 20)
    cfg = strategy_config or STRATEGY_CONFIG
    min_adx_limit = float(cfg.get("min_adx", 20))

    if market_data_dict:
        # If the primary chart breaks a 20-candle channel with confirmation, prefer breakout.
        breakout_sig, breakout_reason = strategy_breakout(df_primary, filters, strategy_config)
        if breakout_sig:
            return breakout_sig, f"[رژیم شکست | ADX={adx:.1f}] {breakout_reason}"

    if adx > (min_adx_limit + 5):
        sig, reason = strategy_trend_following(df_primary, timeframe, filters, strategy_config)
        return sig, f"[رژیم رونددار | ADX={adx:.1f}] {reason}"
    if adx < min_adx_limit:
        sig, reason = strategy_mean_reversion(df_primary, filters, strategy_config)
        return sig, f"[رژیم رنج | ADX={adx:.1f}] {reason}"
    return None, f"[فاز گذار | ADX={adx:.1f}] انتظار برای تثبیت بازار."


def get_signal_with_reason(
    df_primary,
    market_data_dict=None,
    timeframe_mode="single",
    timeframe="5min",
    strategy_type="trend",
    filters=None,
    strategy_config=None,
):
    if df_primary is None or df_primary.empty or len(df_primary) < 60:
        return None, "داده‌های کافی برای محاسبه اندیکاتورها وجود ندارد."

    if strategy_type == "trend":
        return strategy_trend_following(df_primary, timeframe, filters, strategy_config)
    if strategy_type == "breakout":
        return strategy_breakout(df_primary, filters, strategy_config)
    if strategy_type == "mean_reversion":
        return strategy_mean_reversion(df_primary, filters, strategy_config)
    if strategy_type == "multi":
        return strategy_multi_tf(df_primary, market_data_dict, timeframe, filters, strategy_config)
    if strategy_type == "dynamic":
        return strategy_dynamic(df_primary, market_data_dict, timeframe, filters, strategy_config)
    return strategy_trend_following(df_primary, timeframe, filters, strategy_config)


def get_signal(
    df_primary,
    market_data_dict=None,
    timeframe_mode="single",
    timeframe="5min",
    strategy_type="trend",
    filters=None,
    strategy_config=None,
):
    sig, _ = get_signal_with_reason(
        df_primary,
        market_data_dict,
        timeframe_mode,
        timeframe,
        strategy_type,
        filters,
        strategy_config,
    )
    return sig
