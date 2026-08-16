import pandas as pd
import numpy as np

FILTER_DEFAULTS = {
    "volume_filter": True,
    "trailing_stop": True,
    "candlestick_filter": True,
    # V24.1: استراتژی dynamic به‌صورت خودکار بین Long/Short سوییچ می‌کند (بر اساس رژیم بازار)،
    # پس فیلتر مسدودکننده SHORT دیگر به‌صورت پیش‌فرض روشن نیست.
    "no_short_filter": False,
    "no_buy_filter": False,
}

STRATEGY_DEFAULTS = {
    "min_adx": 24.0,
    "sl_multiplier": 1.5,
    "tp_multiplier": 2.0,
    # Dynamic exits use these as safe bounds/baselines rather than fixed exits.
    "dynamic_exits": True,
    "min_trade_score": 82.0,
    "min_rr": 1.35,
    "max_sl_atr": 2.50,
    "min_target_r": 1.35,
    "max_target_r": 1.8,
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


def build_trade_plan(df, signal, strategy_config=None, strategy_type="dynamic"):
    """Build a volatility + market-structure exit plan and a 0-100 trade-quality score.

    This is a decision filter, not a probability forecast.  The plan uses the closed
    candle only, ATR for volatility, recent swing structure for invalidation, and
    a dynamic reward target.  A trade is rejected when the resulting R:R is below
    the configured floor or the quality score is too low.
    """
    if df is None or len(df) < 30 or signal not in ("BUY", "SELL"):
        return None, "داده کافی برای طراحی معامله وجود ندارد"
    c = df.iloc[-2]
    try:
        entry = float(c["close"]); atr = float(c["atr"])
    except Exception:
        return None, "ATR یا قیمت ورود نامعتبر است"
    if not np.isfinite(entry) or entry <= 0 or not np.isfinite(atr) or atr <= 0:
        return None, "ATR یا قیمت ورود نامعتبر است"

    cfg = {**STRATEGY_DEFAULTS, **(_cfg(strategy_config) or {})}
    min_score = float(cfg.get("min_trade_score", 68.0))
    min_rr = float(cfg.get("min_rr", 1.30))
    min_r = max(min_rr, float(cfg.get("min_target_r", 1.30)))
    max_r = max(min_r, float(cfg.get("max_target_r", 2.20)))
    max_sl_atr = max(1.5, float(cfg.get("max_sl_atr", 2.50)))

    adx = _safe_float(c.get("adx"), 0)
    rsi = _safe_float(c.get("rsi"), 50)
    vr = _safe_float(c.get("volume_ratio"), 1)
    body_ratio = _safe_float(c.get("body_ratio"), 0)
    ema20 = _safe_float(c.get("ema20"), entry)
    ema50 = _safe_float(c.get("ema50"), entry)
    plus_di = _safe_float(c.get("plus_di"), 0)
    minus_di = _safe_float(c.get("minus_di"), 0)

    # Volatility regime is relative to recent ATR, not a hard-coded % that
    # would behave badly across BTC, altcoins and different timeframes.
    recent_atr = pd.to_numeric(df["atr"].iloc[-32:-2], errors="coerce").dropna()
    atr_ratio = atr / max(float(recent_atr.median()) if len(recent_atr) else atr, 1e-12)

    trend_ok = (entry > ema20 > ema50 and plus_di > minus_di) if signal == "BUY" else (entry < ema20 < ema50 and minus_di > plus_di)
    direction_di = plus_di > minus_di if signal == "BUY" else minus_di > plus_di
    rsi_ok = (48 <= rsi <= 68) if signal == "BUY" else (32 <= rsi <= 52)

    if strategy_type == "mean_reversion":
        # Mean reversion intentionally prefers a non-trending regime and RSI extremes.
        trend_score = 22.0 if adx < float(cfg.get("min_adx",20.0)) else 0.0
        rsi_score = 10.0 if ((signal == "BUY" and rsi <= 35) or (signal == "SELL" and rsi >= 65)) else 2.0
    else:
        trend_score = 25.0 if trend_ok else (12.0 if direction_di else 0.0)
        rsi_score = 10.0 if rsi_ok else max(0.0, 10.0 - abs(rsi - (58 if signal == "BUY" else 42)) * 0.25)
    adx_score = min(20.0, max(0.0, (adx - 15.0) * 1.0))
    volume_score = min(15.0, max(0.0, (vr - 0.85) * 25.0))
    candle_score = min(15.0, max(0.0, body_ratio * 18.0))
    vol_score = 15.0 * max(0.0, 1.0 - min(abs(np.log(max(atr_ratio, 1e-9))), 1.0))
    score = int(round(max(0.0, min(100.0, trend_score + adx_score + volume_score + candle_score + rsi_score + vol_score))))

    # Adaptive stop: start from ATR, then respect the most recent structural
    # invalidation.  The cap prevents a distant swing from creating oversized risk.
    lookback = df.iloc[-12:-2]
    if signal == "BUY":
        swing = float(pd.to_numeric(lookback["low"], errors="coerce").min())
        base_mult = float(cfg.get("sl_multiplier", 1.5))
        if atr_ratio > 1.35: base_mult += 0.20
        elif atr_ratio < 0.80: base_mult -= 0.10
        base_mult = max(1.25, min(max_sl_atr, base_mult))
        atr_sl = entry - atr * base_mult
        structure_sl = swing - atr * 0.15 if np.isfinite(swing) else atr_sl
        sl = min(atr_sl, structure_sl)
        if entry - sl > atr * max_sl_atr:
            sl = entry - atr * max_sl_atr
        risk_dist = entry - sl
        resistance = _safe_float(c.get("channel_high"), 0)
        if resistance <= entry + risk_dist * min_r:
            resistance = 0
        direction = 1
    else:
        swing = float(pd.to_numeric(lookback["high"], errors="coerce").max())
        base_mult = float(cfg.get("sl_multiplier", 1.5))
        if atr_ratio > 1.35: base_mult += 0.20
        elif atr_ratio < 0.80: base_mult -= 0.10
        base_mult = max(1.25, min(max_sl_atr, base_mult))
        atr_sl = entry + atr * base_mult
        structure_sl = swing + atr * 0.15 if np.isfinite(swing) else atr_sl
        sl = max(atr_sl, structure_sl)
        if sl - entry > atr * max_sl_atr:
            sl = entry + atr * max_sl_atr
        risk_dist = sl - entry
        support = _safe_float(c.get("channel_low"), 0)
        if support >= entry - risk_dist * min_r:
            support = 0
        resistance = support
        direction = -1

    if risk_dist <= 0 or not np.isfinite(risk_dist):
        return None, "فاصله حد ضرر معتبر نیست"

    # Stronger setups earn a larger target, but never below the configured floor.
    target_r = min_r + (max_r - min_r) * (score / 100.0)
    target_r = max(min_r, min(max_r, target_r))
    tp = entry + direction * risk_dist * target_r

    # If a meaningful structure level lies before the target, use it only when
    # it still leaves enough reward. Otherwise keep the volatility-based target.
    if direction == 1 and resistance > entry:
        candidate = resistance - atr * 0.10
        if candidate > entry and (candidate - entry) / risk_dist >= min_rr:
            tp = min(tp, candidate)
    elif direction == -1 and resistance > 0 and resistance < entry:
        candidate = resistance + atr * 0.10
        if candidate < entry and (entry - candidate) / risk_dist >= min_rr:
            tp = max(tp, candidate)

    rr = abs(tp - entry) / risk_dist
    if rr < min_rr:
        return None, f"R:R کافی نیست ({rr:.2f}R < {min_rr:.2f}R)"
    quality_label = "عالی" if score >= 85 else "خوب" if score >= 75 else "قابل قبول" if score >= min_score else "ضعیف"
    if score < min_score:
        return None, f"امتیاز کیفیت پایین است ({score}/100)"

    plan = {
        "entry": entry, "sl": float(sl), "tp": float(tp), "score": score,
        "quality_label": quality_label, "rr": float(rr),
        "risk_atr": float(risk_dist / atr), "target_r": float(rr),
        "atr": atr, "atr_ratio": float(atr_ratio), "adx": adx,
        "rsi": rsi, "volume_ratio": vr,
        "reason": f"کیفیت {score}/100 ({quality_label}) | ADX {adx:.1f} | ATR نسبت به میانه {atr_ratio:.2f}x | R:R {rr:.2f}R"
    }
    return plan, plan["reason"]


def get_strategy_description(timeframe="5min", strategy_config=None, filters=None, simple=False):
    p=get_strategy_params(timeframe,strategy_config)
    f=_flt(filters)
    if simple:
        return "📊 *استراتژی فعال*\n\n🤖 ربات قدرت روند، نوسان، حرکت قیمت و حجم را پشت صحنه بررسی می‌کند.\n\n🎯 حد سود و ضرر با شرایط بازار هماهنگ می‌شوند.\n⚖️ کیفیت و نسبت سود به ریسک قبل از ورود بررسی می‌شود.\n\n💡 لازم نیست ADX یا ATR را بدانید؛ ربات از آن‌ها به‌عنوان ابزار داخلی استفاده می‌کند."
    return (f"📊 *استراتژی فعال ({'مولتی' if timeframe == 'multi' else timeframe})*\n\n"
            f"• ADX: `{p['adx']:.1f}`\n• SL: `{p['sl']:.1f} ATR`\n• TP: `{p['tp']:.1f} ATR`\n• حجم: `{'🟢' if f.get('volume_filter',True) else '🔴'}`\n• کندل: `{'🟢' if f.get('candlestick_filter',True) else '🔴'}`")


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

    if bullish_pin or strong_bull:
        name = "پین‌بار صعودی" if bullish_pin else "کندل صعودی قدرتمند"
        return "BUY_CONFIRMED", name
    if bearish_pin or strong_bear:
        name = "پین‌بار نزولی" if bearish_pin else "کندل نزولی قدرتمند"
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
    trend_buy = curr["close"] > curr["ema20"] > curr["ema50"] and curr["plus_di"] > curr["minus_di"]
    trend_sell = curr["close"] < curr["ema20"] < curr["ema50"] and curr["minus_di"] > curr["plus_di"]
    bull = curr["close"] > curr["channel_high"] and prev["close"] <= prev.get("channel_high", np.inf) and trend_buy and adx >= 24.0
    bear = curr["close"] < curr["channel_low"] and prev["close"] >= prev.get("channel_low", -np.inf) and trend_sell and adx >= 24.0
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


def strategy_dynamic(df_primary, market_data_dict=None, timeframe="5min", filters=None, strategy_config=None, regime=None):
    # V4: keep only the strongest observed regime from the baseline tests: bullish breakout
    # with a strong candle (Long) mirrored for confirmed bearish markets (Short).
    # جهت معامله را رژیم قطعی بازار (تشخیص‌داده‌شده از هم‌راستایی BTC/ETH) تعیین می‌کند؛
    # اگر رژیم نامشخص (NEUTRAL) باشد، اصلاً سیگنالی صادر نمی‌شود (NO TRADE).
    break_sig, break_reason = strategy_breakout(df_primary, filters, strategy_config)
    if regime == "BULLISH" and break_sig == "BUY":
        return "BUY", f"[شکست-قوی] {break_reason}"
    if regime == "BEARISH" and break_sig == "SELL":
        return "SELL", f"[شکست-قوی] {break_reason}"
    if regime not in ("BULLISH", "BEARISH"):
        return None, "رژیم بازار قطعی نیست (NEUTRAL) — بدون معامله"
    return None, break_reason if break_reason else "No strong breakout aligned with market regime"


def get_signal_with_reason(df_primary, market_data_dict=None, timeframe_mode="single", timeframe="5min", strategy_type="trend", filters=None, strategy_config=None, regime=None):
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
        return strategy_dynamic(df_primary, market_data_dict, timeframe, filters, strategy_config, regime)
    return strategy_trend_following(df_primary, timeframe, filters, strategy_config)


def get_signal(df_primary, market_data_dict=None, timeframe_mode="single", timeframe="5min", strategy_type="trend", filters=None, strategy_config=None, regime=None):
    sig, _ = get_signal_with_reason(df_primary, market_data_dict, timeframe_mode, timeframe, strategy_type, filters, strategy_config, regime)
    return sig
