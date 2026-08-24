import pandas as pd
import numpy as np


def compute_log_grid_levels(df, base_steps=20, lookback=None):
    """Build a correctly spaced log grid without anchoring it to stale extremes.

    ``base_steps`` is the number of full log steps; half-steps are inserted,
    so the final grid has ``base_steps * 2`` equal log intervals.  When
    ``lookback`` is supplied only the latest completed history is used.  This
    keeps the grid adaptive while avoiding a permanently stale all-time anchor.
    """
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
    """نزدیک‌ترین سطح شبکه به یک قیمت مشخص را برمی‌گرداند: (level_dict, فاصله به‌درصد)."""
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
    """
    استاپ‌لاس را بر اساس آخرین سوینگ معاملاتی (کف/سقف تأییدشده اخیر) محاسبه می‌کند،
    نه یک فاصله ثابت ATR. کندل‌های خیلی اخیر (confirm_candles) کنار گذاشته می‌شوند
    تا سوینگ استفاده‌شده واقعاً «شکل‌گرفته» باشد نه یک نوسان لحظه‌ای.

    خروجی: (sl, swing_level) یا (None, None) اگر داده کافی نبود.
    """
    if df is None or df.empty:
        return None, None
    need = lookback + confirm_candles
    if len(df) < need + 1:
        return None, None
    if "atr" not in df.columns:
        return None, None
    atr = pd.to_numeric(df["atr"], errors="coerce").iloc[-1]
    if not np.isfinite(atr) or atr <= 0:
        return None, None
    end = -confirm_candles if confirm_candles > 0 else None
    start = -(lookback + confirm_candles)
    window = df.iloc[start:end]
    if window.empty:
        return None, None
    if is_long:
        swing = float(pd.to_numeric(window["low"], errors="coerce").min())
        if not np.isfinite(swing):
            return None, None
        sl = swing - atr * buffer_atr
    else:
        swing = float(pd.to_numeric(window["high"], errors="coerce").max())
        if not np.isfinite(swing):
            return None, None
        sl = swing + atr * buffer_atr
    return float(sl), float(swing)


def _candle_metrics(c):
    o, cl, h, l = float(c["open"]), float(c["close"]), float(c["high"]), float(c["low"])
    body = abs(cl - o)
    full_range = max(h - l, 1e-12)
    upper_wick = h - max(cl, o)
    lower_wick = min(cl, o) - l
    return o, cl, h, l, body, full_range, upper_wick, lower_wick


def detect_candlestick_patterns(df):
    """
    الگوهای معروف کندلی را روی آخرین کندل تأییدشده (و ۲ کندل قبل از آن برای الگوهای
    چندکندلی) شناسایی می‌کند. کندل در حال شکل‌گیری (آخرین ردیف df) استفاده نمی‌شود -
    دقیقاً مثل بقیه منطق build_trade_plan که از df.iloc[-2] به‌عنوان کندل تأییدشده استفاده می‌کند.

    خروجی: لیستی از تاپل (نام_فارسی, جهت, قدرت) - جهت: +1 صعودی، -1 نزولی، 0 خنثی/بی‌تصمیم.
    """
    if df is None or len(df) < 4:
        return []
    c0, c1, c2 = df.iloc[-2], df.iloc[-3], df.iloc[-4]
    o0, cl0, h0, l0, body0, range0, uw0, lw0 = _candle_metrics(c0)
    body_ratio0 = body0 / range0
    bull0, bear0 = cl0 > o0, cl0 < o0

    patterns = []

    if body_ratio0 >= 0.85:
        patterns.append(("مارابوزو", 1 if bull0 else -1, 0.55))

    if body_ratio0 <= 0.35 and lw0 >= 2.0 * max(body0, 1e-12) and uw0 <= body0 * 0.6:
        patterns.append(("چکش / پین‌بار صعودی", 1, 0.70))

    if body_ratio0 <= 0.35 and uw0 >= 2.0 * max(body0, 1e-12) and lw0 <= body0 * 0.6:
        patterns.append(("ستاره تیرانداز / پین‌بار نزولی", -1, 0.70))

    if body_ratio0 <= 0.12:
        patterns.append(("دوجی", 0, 0.40))

    o1, cl1, h1, l1, body1, range1, uw1, lw1 = _candle_metrics(c1)
    bull1, bear1 = cl1 > o1, cl1 < o1
    if body1 > 1e-12:
        if bull0 and bear1 and cl0 >= o1 and o0 <= cl1 and body0 > body1:
            patterns.append(("انگالفینگ صعودی", 1, 0.80))
        if bear0 and bull1 and o0 >= cl1 and cl0 <= o1 and body0 > body1:
            patterns.append(("انگالفینگ نزولی", -1, 0.80))

    o2, cl2, h2, l2, body2, range2, uw2, lw2 = _candle_metrics(c2)
    bull2, bear2 = cl2 > o2, cl2 < o2
    if body2 > 1e-12:
        mid_small = body1 <= 0.4 * body2
        if bear2 and mid_small and bull0 and cl0 > (o2 + cl2) / 2.0:
            patterns.append(("ستاره صبحگاهی", 1, 0.75))
        if bull2 and mid_small and bear0 and cl0 < (o2 + cl2) / 2.0:
            patterns.append(("ستاره عصرگاهی", -1, 0.75))

    return patterns


def candle_pattern_score(df, signal, regime="mixed", near_structure=False, max_points=10.0):
    """
    امتیاز کمکی (نه فیلتر سخت) بر اساس الگوهای کندلی شناخته‌شده - همسو با جهت سیگنال و
    منطبق با رژیم فعلی بازار (روند / رنج) وزن می‌گیرد:
      - الگوهای برگشتی (چکش، ستاره تیرانداز، انگالفینگ، مورنینگ/ایونینگ استار) در رژیم رنج
        یا نزدیک یک سطح ساختاری (سوینگ/PDH/PDL) وزن کامل می‌گیرند.
      - همان الگوهای برگشتی وسط یک روند قوی و دور از سطح ساختاری، با احتیاط و وزن نصف
        اعمال می‌شوند (چون می‌توانند تله باشند).
      - الگوی ادامه‌دهنده (مارابوزو هم‌جهت با سیگنال) در رژیم روند/بریک‌اوت وزن کامل می‌گیرد.
      - دوجی در وسط روند قوی (بی‌تصمیمی خلاف تداوم) کمی امتیاز منفی می‌دهد؛ نزدیک سطح
        ساختاری خنثی تا کمی مثبت است.
      - الگوی خلاف جهت سیگنال، امتیاز را کم می‌کند (رد نمی‌کند - فقط هشدار احتیاط).
    خروجی: (امتیاز بین -max_points تا +max_points, نام الگوی غالب یا None)
    """
    patterns = detect_candlestick_patterns(df)
    if not patterns:
        return 0.0, None
    wanted_dir = 1 if signal == "BUY" else -1
    best_name, best_weight = None, 0.0
    for name, direction, strength in patterns:
        if direction == 0:
            weight = 0.3 if near_structure else (-0.3 if regime == "trend" else 0.0)
        elif direction == wanted_dir:
            if regime == "range" or near_structure:
                weight = strength
            elif regime == "trend" and name == "مارابوزو":
                weight = strength
            elif regime == "trend":
                weight = strength * 0.5
            else:
                weight = strength * 0.7
        else:
            weight = -0.4 * strength
        if abs(weight) > abs(best_weight):
            best_name, best_weight = name, weight
    if best_name is None:
        return 0.0, None
    return max(-max_points, min(max_points, best_weight * max_points)), best_name


STRATEGY_DEFAULTS = {
    "min_adx": 20.0,
    "sl_multiplier": 1.5,
    "tp_multiplier": 2.0,
    "dynamic_exits": True,
    "min_trade_score": 65.0,
    "min_rr": 1.35,
    "max_sl_atr": 3.00,
    "grid_lookback_candles": 500,
    "min_target_r": 1.35,
    "max_target_r": 1.8,
    "min_volume_ratio": 1.05,
    "min_body_ratio": 0.45,
    "sweep_min_distance_atr": 0.10,
    "sweep_require_reclaim": True,
    "sweep_require_reversal_candle": True,
    "sweep_stop_buffer_atr": 0.40,
    "sweep_risk_reward": 1.8,
    "sweep_enable_retest_continuation": True,
    "retest_lookback_candles": 48,
    "retest_tolerance_atr": 0.25,
    # فرصت از دست‌رفته: ستاپ معتبرِ اخیر برای مدت کوتاه زنده می‌ماند، اما تعقیب قیمت ممنوع است.
    "active_setup_enabled": True,
    "active_setup_lookback_candles": 3,
    "active_setup_max_age_candles": 3,
    "active_setup_max_distance_atr": 0.80,
    "active_setup_invalidation_atr": 0.25,
    # Active setup only becomes valid after a confirmed PDH/PDL breakout
    # and sufficient distance from the previous-day range.
    "active_setup_require_daily_breakout": True,
    "active_setup_breakout_distance_atr": 0.80,
    "active_setup_breakout_confirm_candles": 1,
    "active_structure_confirmation": True,
    "active_structure_lookback": 8,
    "active_structure_confirm_candles": 2,
    "min_sl_percent": 0.005,
    "max_fee_risk_ratio": 0.20,
    "cooldown_seconds": 1200,
    # --- استاپ‌لاس بر اساس سوینگ ساختاری ---
    "swing_lookback": 12,           # تعداد کندل قبل برای یافتن آخرین سوینگ معاملاتی
    "swing_confirm_candles": 2,     # این تعداد کندل آخر نادیده گرفته می‌شود تا سوینگ «تأییدشده» باشد
    "swing_buffer_atr": 0.40,       # فاصله اضافه (بر حسب ATR) زیر/بالای سوینگ برای جلوگیری از شکار استاپ
    # --- مدیریت هوشمند هدف سود (PDL/PDH) ---
    "extend_tp_to_pdl": True,       # هدف اصلی معامله = سقف/کف روز قبل، به‌جای هدف کوتاه RR ثابت
    "weakness_exit_min_r": 1.0,     # حداقل سود (بر حسب R) قبل از فعال شدن بررسی ضعف روند
    "weakness_exit_score": 55.0,    # آستانه سخت‌تر برای بستن زودهنگام با سود
    "weakness_profit_lock_min_r": 1.0,
    # مدیریت پوزیشن سمت ضرر هم مثل سمت سود روی تایم‌فریم سریع‌تر انجام می‌شود
    # (نگاه کنید به POSITION_MANAGEMENT_TIMEFRAME_MAP در bot.py) و از همان
    # آستانه‌ی زودهنگام (POSITION_MANAGEMENT_MIN_LOSS_R) استفاده می‌کند.
    "early_loss_weakness_exit_enabled": True,
    "use_edge_proxy_gate": False,   # proxy فقط diagnostic است مگر اینکه صراحتاً فعال شود
}

TIMEFRAME_STRATEGY_PRESETS = {
    "5min":  {
        "min_adx": 20.0, "min_volume_ratio": 1.05, "min_body_ratio": 0.45,
        "min_trade_score": 60.0, "min_rr": 1.30, "min_target_r": 1.30, "max_target_r": 1.8,
        "sweep_risk_reward": 1.8, "sweep_stop_buffer_atr": 0.45, "sweep_min_distance_atr": 0.10,
        "min_sl_percent": 0.005, "max_fee_risk_ratio": 0.20, "cooldown_seconds": 1200
    },
    "15min": {
        "min_adx": 20.0, "min_volume_ratio": 1.05, "min_body_ratio": 0.45,
        "min_trade_score": 60.0, "min_rr": 1.30, "min_target_r": 1.30, "max_target_r": 1.9,
        "sweep_risk_reward": 1.8, "sweep_stop_buffer_atr": 0.40, "sweep_min_distance_atr": 0.10,
        "min_sl_percent": 0.005, "max_fee_risk_ratio": 0.20, "cooldown_seconds": 1200
    },
    "1hour": {
        "min_adx": 19.0, "min_volume_ratio": 1.00, "min_body_ratio": 0.42,
        "min_trade_score": 56.0, "min_rr": 1.20, "min_target_r": 1.20, "max_target_r": 2.2,
        "min_sl_percent": 0.006, "max_fee_risk_ratio": 0.20, "cooldown_seconds": 1800
    },
    "4hour": {
        "min_adx": 18.0, "min_volume_ratio": 1.00, "min_body_ratio": 0.40,
        "min_trade_score": 54.0, "min_rr": 1.20, "min_target_r": 1.20, "max_target_r": 2.5,
        "min_sl_percent": 0.008, "max_fee_risk_ratio": 0.20, "cooldown_seconds": 3600
    },
}

TIMEFRAME_PARAM_ADJUST = TIMEFRAME_STRATEGY_PRESETS


def get_timeframe_preset(timeframe):
    return {**STRATEGY_DEFAULTS, **TIMEFRAME_STRATEGY_PRESETS.get(timeframe, {})}


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


def get_strategy_params(strategy_config=None):
    # توجه: این تابع فقط بر اساس strategy_config کار می‌کند (که خودش قبلاً بر اساس
    # تایم‌فریم واقعی جلسه، در get_timeframe_preset ساخته شده)؛ به همین دلیل دیگر
    # آرگومان جداگانه‌ی timeframe نمی‌گیرد تا در فراخوانی‌ها گمراه‌کننده نباشد.
    c = _cfg(strategy_config)
    return {
        "adx": float(c.get("min_adx", 20.0)),
        "sl": float(c.get("sl_multiplier", 1.5)),
        "tp": float(c.get("tp_multiplier", 2.0)),
        "volume_ratio": float(c.get("min_volume_ratio", 1.05)),
        "body_ratio": float(c.get("min_body_ratio", 0.45)),
    }


def build_trade_plan(df, signal, strategy_config=None, strategy_type="dynamic", strategy_timeframe="5min", grid_levels=None, setup_index=None, live_price=None, market_data_dict=None, defer_quality_gate=False, filters=None, regime=None):
    if strategy_type == "dynamic" and get_v2_config(strategy_config).get("v2_enabled", True):
        # Must reuse the SAME context the signal pass used: HTF market data,
        # the caller's filters and the macro `regime` (BULLISH/BEARISH/NEUTRAL).
        # Dropping any of these makes this second candidate-selection run
        # score/gate differently from the first (see get_signal_with_reason_v2),
        # which produced duplicated/inconsistent reason strings and could let a
        # plan through that the original V2 score/RR/directional gates would
        # have rejected (e.g. a counter-trend setup losing its regime penalty).
        effective_filters = filters if isinstance(filters, dict) else FILTER_DEFAULTS
        sig, plan, reason = _select_v2_setup(df, market_data_dict, strategy_timeframe, effective_filters, strategy_config, regime, grid_levels, live_price=live_price)
        if sig == signal and plan:
            return plan, reason
    if strategy_type == "liquidity_sweep" or (strategy_type == "dynamic" and strategy_timeframe in ("5min", "15min")):
        return build_sweep_trade_plan(df, signal, strategy_config, grid_levels=grid_levels, setup_index=setup_index, live_price=live_price)
    if df is None or len(df) < 30 or signal not in ("BUY", "SELL"):
        return None, "داده کافی برای طراحی معامله وجود ندارد"
    c = df.iloc[-2]
    try:
        entry = float(c["close"])
        atr = float(c["atr"])
    except Exception:
        return None, "ATR یا قیمت ورود نامعتبر است"
    if not np.isfinite(entry) or entry <= 0 or not np.isfinite(atr) or atr <= 0:
        return None, "ATR یا قیمت ورود نامعتبر است"

    cfg = {**STRATEGY_DEFAULTS, **(_cfg(strategy_config) or {})}
    min_score = float(cfg.get("min_trade_score", 60.0))
    min_rr = float(cfg.get("min_rr", 1.30))
    min_r = max(min_rr, float(cfg.get("min_target_r", 1.30)))
    max_r = max(min_r, float(cfg.get("max_target_r", 2.20)))
    max_sl_atr = max(1.5, float(cfg.get("max_sl_atr", 3.00)))
    min_sl_pct = float(cfg.get("min_sl_percent", 0.005))
    max_fee_ratio = float(cfg.get("max_fee_risk_ratio", 0.20))

    adx = _safe_float(c.get("adx"), 0)
    rsi = _safe_float(c.get("rsi"), 50)
    vr = _safe_float(c.get("volume_ratio"), 1)
    body_ratio = _safe_float(c.get("body_ratio"), 0)
    ema20 = _safe_float(c.get("ema20"), entry)
    ema50 = _safe_float(c.get("ema50"), entry)
    plus_di = _safe_float(c.get("plus_di"), 0)
    minus_di = _safe_float(c.get("minus_di"), 0)

    recent_atr = pd.to_numeric(df["atr"].iloc[-32:-2], errors="coerce").dropna()
    atr_ratio = atr / max(float(recent_atr.median()) if len(recent_atr) else atr, 1e-12)

    trend_ok = (entry > ema20 > ema50 and plus_di > minus_di) if signal == "BUY" else (entry < ema20 < ema50 and minus_di > plus_di)
    direction_di = plus_di > minus_di if signal == "BUY" else minus_di > plus_di
    rsi_ok = (48 <= rsi <= 68) if signal == "BUY" else (32 <= rsi <= 52)

    swing_lookback_n = int(cfg.get("swing_lookback", 12))
    swing_confirm_n = int(cfg.get("swing_confirm_candles", 2))
    swing_buffer_atr = float(cfg.get("swing_buffer_atr", 0.40))
    swing_sl, swing_level = compute_swing_stop(
        df, signal == "BUY", swing_lookback_n, swing_buffer_atr, swing_confirm_n
    )
    near_structure = swing_level is not None and abs(entry - swing_level) <= atr * 1.2
    regime = "range" if strategy_type == "mean_reversion" else ("trend" if trend_ok else "mixed")

    if strategy_type == "mean_reversion":
        trend_score = 22.0 if adx < float(cfg.get("min_adx", 20.0)) else 0.0
        rsi_score = 10.0 if ((signal == "BUY" and rsi <= 35) or (signal == "SELL" and rsi >= 65)) else 2.0
    else:
        trend_score = 25.0 if trend_ok else (12.0 if direction_di else 0.0)
        rsi_score = 10.0 if rsi_ok else max(0.0, 10.0 - abs(rsi - (58 if signal == "BUY" else 42)) * 0.25)
    adx_score = min(20.0, max(0.0, (adx - 15.0) * 1.0))
    volume_score = min(15.0, max(0.0, (vr - 0.85) * 25.0))
    candle_score = min(10.0, max(0.0, body_ratio * 12.0))
    vol_score = 10.0 * max(0.0, 1.0 - min(abs(np.log(max(atr_ratio, 1e-9))), 1.0))
    pattern_score, pattern_name = candle_pattern_score(df, signal, regime, near_structure, max_points=10.0)
    score = int(round(max(0.0, min(100.0,
        trend_score + adx_score + volume_score + candle_score + rsi_score + vol_score + pattern_score
    ))))

    if signal == "BUY":
        base_mult = float(cfg.get("sl_multiplier", 1.5))
        if atr_ratio > 1.35: base_mult += 0.20
        elif atr_ratio < 0.80: base_mult -= 0.10
        base_mult = max(1.25, min(max_sl_atr, base_mult))
        atr_sl = entry - atr * base_mult
        # اولویت با استاپ ساختاری (زیر آخرین سوینگ) است؛ فقط اگر سوینگ معتبر نبود یا
        # پشت قیمت ورود نبود، به فاصله مبتنی بر ATR برمی‌گردیم.
        sl = swing_sl if (swing_sl is not None and swing_sl < entry) else atr_sl
        if (entry - sl) / entry < min_sl_pct:
            sl = entry * (1.0 - min_sl_pct)
        if swing_sl is not None and swing_sl < entry and entry - sl > atr * max_sl_atr:
            return None, "استاپ ساختاری بیش از حد دور است؛ معامله رد شد"
        if entry - sl > atr * max_sl_atr:
            return None, "فاصله حد ضرر بیش از سقف مجاز است"
        risk_dist = entry - sl
        resistance = _safe_float(c.get("channel_high"), 0)
        if resistance <= entry + risk_dist * min_r:
            resistance = 0
        direction = 1
    else:
        base_mult = float(cfg.get("sl_multiplier", 1.5))
        if atr_ratio > 1.35: base_mult += 0.20
        elif atr_ratio < 0.80: base_mult -= 0.10
        base_mult = max(1.25, min(max_sl_atr, base_mult))
        atr_sl = entry + atr * base_mult
        sl = swing_sl if (swing_sl is not None and swing_sl > entry) else atr_sl
        if (sl - entry) / entry < min_sl_pct:
            sl = entry * (1.0 + min_sl_pct)
        if swing_sl is not None and swing_sl > entry and sl - entry > atr * max_sl_atr:
            return None, "استاپ ساختاری بیش از حد دور است؛ معامله رد شد"
        if sl - entry > atr * max_sl_atr:
            return None, "فاصله حد ضرر بیش از سقف مجاز است"
        risk_dist = sl - entry
        support = _safe_float(c.get("channel_low"), 0)
        if support >= entry - risk_dist * min_r:
            support = 0
        resistance = support
        direction = -1

    if risk_dist <= 0 or not np.isfinite(risk_dist):
        return None, "فاصله حد ضرر معتبر نیست"

    # فیلتر کارمزد به ریسک دلاری
    risk_pct = risk_dist / entry
    est_risk_usdt = 500.0 * risk_pct
    if est_risk_usdt > 0:
        if (0.50 / est_risk_usdt) > max_fee_ratio:
            return None, f"ریسک به کارمزد کوچک است ({est_risk_usdt:.2f}$)"

    target_r = min_r + (max_r - min_r) * (score / 100.0)
    target_r = max(min_r, min(max_r, target_r))
    tp = entry + direction * risk_dist * target_r

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
    if score < min_score and not defer_quality_gate:
        return None, f"امتیاز کیفیت پایین است ({score}/100)"

    plan = {
        "entry": entry, "sl": float(sl), "tp": float(tp), "score": score,
        "quality_label": quality_label, "rr": float(rr),
        "risk_atr": float(risk_dist / atr), "target_r": float(rr),
        "atr": atr, "atr_ratio": float(atr_ratio), "adx": adx,
        "rsi": rsi, "volume_ratio": vr,
        "swing_level": float(swing_level) if swing_level is not None and np.isfinite(swing_level) else None,
        "pattern": pattern_name,
        "reason": f"کیفیت {score}/100 ({quality_label}) | ADX {adx:.1f} | R:R {rr:.2f}R" + (f" | الگو: {pattern_name}" if pattern_name else "")
    }
    return plan, plan["reason"]


def _compute_prev_day_levels(df):
    if df is None or len(df) < 100 or "timestamp" not in df.columns:
        return None, None, None
    d = df.copy()
    ts = pd.to_numeric(d["timestamp"], errors="coerce")
    if ts.isna().all():
        return None, None, None
    unit = "ms" if float(ts.median()) > 1e12 else "s"
    d["_dt"] = pd.to_datetime(ts, unit=unit, utc=True)
    d["_date"] = d["_dt"].dt.date
    daily = d.groupby("_date").agg(_day_high=("high", "max"), _day_low=("low", "min"))
    daily["_pdh"] = daily["_day_high"].shift(1)
    daily["_pdl"] = daily["_day_low"].shift(1)
    d = d.merge(daily[["_pdh", "_pdl"]], left_on="_date", right_index=True, how="left")
    d = d.reset_index(drop=True)
    curr = d.iloc[-2]
    pdh, pdl = curr.get("_pdh"), curr.get("_pdl")
    if pd.isna(pdh) or pd.isna(pdl):
        return d, None, None
    return d, float(pdh), float(pdl)



def _adaptive_intraday_levels(d, before_idx, cfg):
    """Build conservative, non-future intraday liquidity anchors.

    Priority is deliberately lower than PDH/PDL.  We only expose levels that were
    already formed before the signal candle and have enough observations to avoid
    turning every tiny fluctuation into a tradable level.
    """
    if d is None or before_idx < 10 or "_dt" not in d.columns or "_date" not in d.columns:
        return {}
    work = d.iloc[:before_idx].copy()  # strictly before the signal candle
    if work.empty:
        return {}
    today = d.loc[before_idx, "_date"]
    day = work[work["_date"] == today].copy()
    if len(day) < 5:
        return {}

    min_candles = max(3, int(cfg.get("adaptive_min_level_candles", 6)))
    levels = {}

    # UTC session buckets are intentional and configurable.  They are stable for
    # crypto and do not introduce exchange-local DST ambiguity.
    sessions = {
        "ASIA": (0, 8),
        "LONDON": (8, 13),
        "NEW_YORK": (13, 21),
    }
    for name, (h0, h1) in sessions.items():
        part = day[(day["_dt"].dt.hour >= h0) & (day["_dt"].dt.hour < h1)]
        if len(part) >= min_candles:
            levels[f"{name}_HIGH"] = {"price": float(part["high"].max()), "kind": f"{name}_HIGH", "count": len(part)}
            levels[f"{name}_LOW"] = {"price": float(part["low"].min()), "kind": f"{name}_LOW", "count": len(part)}

    # Opening range: first N minutes of the UTC day. It becomes static once formed.
    or_minutes = max(15, int(cfg.get("adaptive_opening_range_minutes", 30)))
    day_start = pd.Timestamp(today, tz="UTC")
    opening = day[(day["_dt"] >= day_start) & (day["_dt"] < day_start + pd.Timedelta(minutes=or_minutes))]
    if len(opening) >= max(3, min_candles // 2) and len(work) >= len(opening) + 2:
        levels["OPENING_RANGE_HIGH"] = {"price": float(opening["high"].max()), "kind": "OPENING_RANGE_HIGH", "count": len(opening)}
        levels["OPENING_RANGE_LOW"] = {"price": float(opening["low"].min()), "kind": "OPENING_RANGE_LOW", "count": len(opening)}

    # Confirmed intraday swings. The last two candles are excluded; a swing must
    # have candles on both sides, so the level is not based on the current move.
    swing_left = max(2, int(cfg.get("adaptive_swing_left", 2)))
    swing_right = max(2, int(cfg.get("adaptive_swing_right", 2)))
    if len(day) >= swing_left + swing_right + 3:
        highs = day["high"].to_numpy(dtype=float)
        lows = day["low"].to_numpy(dtype=float)
        best_h = None; best_l = None
        for i in range(swing_left, len(day) - swing_right):
            if i >= len(day) - 2:
                continue
            if highs[i] >= np.max(highs[i-swing_left:i]) and highs[i] > np.max(highs[i+1:i+1+swing_right]):
                best_h = float(highs[i])
            if lows[i] <= np.min(lows[i-swing_left:i]) and lows[i] < np.min(lows[i+1:i+1+swing_right]):
                best_l = float(lows[i])
        if best_h is not None:
            levels["SWING_HIGH"] = {"price": best_h, "kind": "SWING_HIGH", "count": swing_left + swing_right + 1}
        if best_l is not None:
            levels["SWING_LOW"] = {"price": best_l, "kind": "SWING_LOW", "count": swing_left + swing_right + 1}
    return levels


def _adaptive_anchor_candidates(d, idx, atr, cfg):
    """Return only anchors close enough to be actionable, ranked by hierarchy."""
    if atr <= 0:
        return []
    levels = _adaptive_intraday_levels(d, idx, cfg)
    if not levels:
        return []
    c = float(d.iloc[idx]["close"])
    max_dist = atr * float(cfg.get("adaptive_max_anchor_distance_atr", 1.60))
    min_dist = atr * float(cfg.get("adaptive_min_anchor_distance_atr", 0.20))
    priority = {"LONDON": 3, "NEW_YORK": 3, "ASIA": 2, "OPENING_RANGE": 2, "SWING": 1}
    out = []
    for name, item in levels.items():
        p = float(item["price"])
        dist = abs(c - p)
        if not np.isfinite(p) or p <= 0 or dist > max_dist:
            continue
        # A level immediately under/over price is not useful until it has room to be swept.
        if dist < min_dist:
            continue
        base = next((v for k, v in priority.items() if name.startswith(k)), 1)
        out.append((base, -dist, name, p))
    out.sort(reverse=True)
    return [(name, price) for _, _, name, price in out]


def _adaptive_target_level(d, idx, signal, anchor, atr, cfg):
    """Choose a nearby opposing liquidity target; fall back to the opposite daily level."""
    levels = _adaptive_intraday_levels(d, idx, cfg)
    c = float(d.iloc[idx]["close"])
    min_move = atr * float(cfg.get("adaptive_min_target_distance_atr", 1.20))
    candidates = []
    for name, item in levels.items():
        p = float(item["price"])
        if signal == "SELL" and p < c - min_move:
            candidates.append((c - p, p, name))
        elif signal == "BUY" and p > c + min_move:
            candidates.append((p - c, p, name))
    if not candidates:
        return None, None
    candidates.sort(key=lambda x: x[0])
    _, p, name = candidates[0]
    return p, name

def _detect_adaptive_liquidity(d, idx, cfg):
    """Detect one high-quality intraday sweep or trend retest on a non-daily anchor."""
    if idx < 2:
        return None, None, None
    curr = d.iloc[idx]
    prev = d.iloc[idx - 1]
    atr = _safe_float(curr.get("atr"), 0.0)
    if atr <= 0:
        return None, None, None
    o, c, h, l = map(float, (curr["open"], curr["close"], curr["high"], curr["low"]))
    po, pc, ph, pl = map(float, (prev["open"], prev["close"], prev["high"], prev["low"]))
    vr = _safe_float(curr.get("volume_ratio"), 0.0)
    body = _safe_float(curr.get("body_ratio"), 0.0)
    adx = _safe_float(curr.get("adx"), 0.0)
    candidates = _adaptive_anchor_candidates(d, idx, atr, cfg)
    sweep_min = atr * float(cfg.get("adaptive_sweep_min_distance_atr", 0.15))
    tol = atr * float(cfg.get("adaptive_retest_tolerance_atr", 0.22))
    min_vol = float(cfg.get("adaptive_min_volume_ratio", 1.12))
    min_body = float(cfg.get("adaptive_min_body_ratio", 0.50))
    trend_adx = float(cfg.get("adaptive_trend_adx", 23.0))

    for name, level in candidates:
        # Reversal/sweep: price pierces the anchor and closes back through it.
        if h >= level + sweep_min and c < level and c < o and body >= min_body and vr >= min_vol:
            target, target_name = _adaptive_target_level(d, idx, "SELL", level, atr, cfg)
            target_txt = f"|TARGET={target:.10g}|TARGET_NAME={target_name}" if target is not None else ""
            return "SELL", (f"ADAPTIVE_SWEEP|ADAPTIVE_ANCHOR={name}|ANCHOR={level:.10g}{target_txt}|"
                             f"intraday liquidity sweep + reclaim نزولی | حجم={vr:.2f}x | body={body:.2f}"), atr
        if l <= level - sweep_min and c > level and c > o and body >= min_body and vr >= min_vol:
            target, target_name = _adaptive_target_level(d, idx, "BUY", level, atr, cfg)
            target_txt = f"|TARGET={target:.10g}|TARGET_NAME={target_name}" if target is not None else ""
            return "BUY", (f"ADAPTIVE_SWEEP|ADAPTIVE_ANCHOR={name}|ANCHOR={level:.10g}{target_txt}|"
                            f"intraday liquidity sweep + reclaim صعودی | حجم={vr:.2f}x | body={body:.2f}"), atr

        # Trend continuation: two-step confirmation. The previous candle must already
        # have accepted beyond the anchor; current candle must retest and hold it.
        if adx >= trend_adx and pc > level and c > level and l <= level + tol and c > o and body >= min_body and vr >= min_vol:
            return "BUY", (f"ADAPTIVE_CONTINUATION|ADAPTIVE_ANCHOR={name}|ANCHOR={level:.10g}|"
                            f"breakout acceptance + retest موفق | ADX={adx:.1f} | حجم={vr:.2f}x"), atr
        if adx >= trend_adx and pc < level and c < level and h >= level - tol and c < o and body >= min_body and vr >= min_vol:
            return "SELL", (f"ADAPTIVE_CONTINUATION|ADAPTIVE_ANCHOR={name}|ANCHOR={level:.10g}|"
                             f"breakdown acceptance + retest موفق | ADX={adx:.1f} | حجم={vr:.2f}x"), atr
    return None, None, None

def _find_recent_breakout(d, before_idx, pdh, pdl, lookback):
    start = max(0, before_idx - lookback)
    window = d.iloc[start:before_idx]
    if window.empty:
        return None, None
    today = d.loc[before_idx, "_date"]
    same_day = window[window["_date"] == today]
    if same_day.empty:
        return None, None
    up = same_day[same_day["close"] > pdh]
    down = same_day[same_day["close"] < pdl]
    up_last = up.index.max() if not up.empty else None
    down_last = down.index.max() if not down.empty else None
    if up_last is not None and (down_last is None or up_last > down_last):
        return "UP", pdh
    if down_last is not None:
        return "DOWN", pdl
    return None, None


def _detect_retest_continuation(d, before_idx, pdh, pdl, atr, cfg):
    lookback = int(cfg.get("retest_lookback_candles", 48))
    direction, level = _find_recent_breakout(d, before_idx, pdh, pdl, lookback)
    if direction is None:
        return None, None
    curr = d.iloc[before_idx]
    tol = atr * max(0.0, float(cfg.get("retest_tolerance_atr", 0.25)))
    o, c, h, l = float(curr["open"]), float(curr["close"]), float(curr["high"]), float(curr["low"])
    if direction == "UP":
        touched = l <= level + tol
        held = c > level
        bullish = c > o
        if touched and held and bullish:
            return "BUY", f"شکست معتبر قبلی سقف روز قبل (PDH={level:.6g}) + پولبک موفق + ادامه صعودی"
    else:
        touched = h >= level - tol
        held = c < level
        bearish = c < o
        if touched and held and bearish:
            return "SELL", f"شکست معتبر قبلی کف روز قبل (PDL={level:.6g}) + پولبک موفق + ادامه نزولی"
    return None, None



def _has_confirmed_daily_breakout(d, before_idx, pdh, pdl, signal, atr, cfg):
    """Active setup guard:
    Only allow recovery entries after a real PDH/PDL breakout with enough distance.
    Prevents buying below PDH or selling above PDL from random intraday anchors.
    """
    if not bool(cfg.get("active_setup_require_daily_breakout", True)):
        return True
    if atr <= 0:
        return False

    distance = atr * float(cfg.get("active_setup_breakout_distance_atr", 1.0))
    confirms = max(1, int(cfg.get("active_setup_breakout_confirm_candles", 1)))

    start = max(0, before_idx - 20)
    window = d.iloc[start:before_idx]

    if signal == "BUY":
        # Must have closed above PDH and moved away from it.
        closes = window["close"].tail(confirms)
        if len(closes) < confirms:
            return False
        return bool((closes > pdh).all() and float(closes.iloc[-1]) >= pdh + distance)

    else:
        # Must have closed below PDL and moved away from it.
        closes = window["close"].tail(confirms)
        if len(closes) < confirms:
            return False
        return bool((closes < pdl).all() and float(closes.iloc[-1]) <= pdl - distance)




def _confirm_active_structure(d, idx, signal, cfg):
    """Require a confirmed micro swing after PDH/PDL reclaim before active entry.
    Prevents immediate breakout continuation entries without market structure.
    """
    lookback = int(cfg.get("active_structure_lookback", 8))
    confirm = int(cfg.get("active_structure_confirm_candles", 2))
    if idx < confirm + 2:
        return False
    end = idx
    start = max(0, end - lookback)
    w = d.iloc[start:end+1]
    if len(w) < confirm + 2:
        return False
    recent = w.iloc[:-confirm] if confirm > 0 else w
    last = w.iloc[-1]
    if signal == "BUY":
        swing_low = float(recent["low"].min())
        recent_high = float(recent["high"].max())
        # higher-low style confirmation: price must leave a defended low
        return float(last["close"]) > recent_high and swing_low < float(last["close"])
    else:
        swing_high = float(recent["high"].max())
        recent_low = float(recent["low"].min())
        return float(last["close"]) < recent_low and swing_high > float(last["close"])

def _active_setup_distance_check(live_price, level, atr, max_distance_atr, invalidation_atr, is_buy):
    """Pure decision for the active-setup FOMO/invalidation guard: given how
    far live price has moved from the original PDH/PDL sweep level, is a
    pending active setup now too far to chase, or already invalidated by
    moving the wrong way past the level? Extracted from
    strategy_liquidity_sweep_5m for independent testing of this exact
    anti-FOMO/anti-dead-bot boundary math.

    Returns (too_far, invalidated).
    """
    max_dist = float(atr) * max(0.20, float(max_distance_atr))
    invalid_dist = float(atr) * max(0.05, float(invalidation_atr))
    if is_buy:
        too_far = live_price > level + max_dist
        invalidated = live_price < level - invalid_dist
    else:
        too_far = live_price < level - max_dist
        invalidated = live_price > level + invalid_dist
    return too_far, invalidated


def _is_daily_level_unreachable(live_price, pdh, pdl, atr, activation_distance_atr):
    """Pure decision: has price drifted so far from BOTH PDH and PDL that
    chasing the original daily liquidity setup no longer makes sense, and the
    strategy should instead rotate to an adaptive intraday level? This is the
    'anti-dead-bot' mechanism described in strategy_liquidity_sweep_5m.
    """
    if not atr or atr <= 0:
        return False
    nearest_dist = min(abs(live_price - pdh), abs(live_price - pdl))
    return nearest_dist >= float(atr) * float(activation_distance_atr)


def strategy_liquidity_sweep_5m(df, filters=None, strategy_config=None, live_price=None, timeframe="5min"):
    """Liquidity Sweep on PDH/PDL with a short-lived active-setup window.

    The primary signal still uses only the latest closed candle. If that exact
    candle was missed by the scanner, a very recent valid sweep/retest can remain
    actionable for a few candles, but only while price is still close to the
    original PDH/PDL level. This avoids both missed entries and FOMO/chasing.
    """
    d, pdh, pdl = _compute_prev_day_levels(df)
    if d is None:
        return None, "داده کافی برای محاسبه High/Low روز قبل نیست"
    if pdh is None or pdl is None:
        return None, "هنوز یک روز کامل قبلی برای محاسبه سطوح ثبت نشده است"

    cfg = {**STRATEGY_DEFAULTS, **(_cfg(strategy_config) or {})}
    require_reclaim = bool(cfg.get("sweep_require_reclaim", True))
    require_reversal = bool(cfg.get("sweep_require_reversal_candle", True))
    # 5m is more noisy: require structure confirmation. Keep 15m faster.
    require_micro_structure = str(timeframe).lower() in ("5min", "5m", "5minute")

    def detect_at(idx):
        if idx < 0 or idx >= len(d):
            return None, None, None
        curr = d.iloc[idx]
        atr = _safe_float(curr.get("atr"), 0.0)
        if not np.isfinite(atr) or atr <= 0:
            return None, None, None
        min_sweep = atr * max(0.0, float(cfg.get("sweep_min_distance_atr", 0.10)))
        o, c, h, l = float(curr["open"]), float(curr["close"]), float(curr["high"]), float(curr["low"])
        if h >= pdh + min_sweep:
            reclaimed = (not require_reclaim) or (c < pdh)
            reversal = (not require_reversal) or (c < o)
            if reclaimed and reversal:
                return "SELL", f"Liquidity Sweep سقف روز قبل (PDH={pdh:.6g}) + ریکلیم نزولی", atr
        if l <= pdl - min_sweep:
            reclaimed = (not require_reclaim) or (c > pdl)
            reversal = (not require_reversal) or (c > o)
            if reclaimed and reversal:
                return "BUY", f"Liquidity Sweep کف روز قبل (PDL={pdl:.6g}) + ریکلیم صعودی", atr
        if bool(cfg.get("sweep_enable_retest_continuation", True)) and idx >= 1:
            sig, reason = _detect_retest_continuation(d, idx, pdh, pdl, atr, cfg)
            if sig:
                return sig, reason, atr
        return None, None, None

    latest_idx = len(d) - 2  # آخرین کندل کاملاً بسته‌شده
    sig, reason, atr = detect_at(latest_idx)

    # سیگنال روی آخرین کندل بسته‌شده معتبر است، اما اگر قیمت زنده از سطح
    # روز قبل بیش از حد فاصله گرفته باشد، ورود تعقیبی/FOMO ممنوع است.
    # در این حالت ستاپ وارد مسیر Active Setup می‌شود تا فقط با Pullback/Reclaim دوباره معتبر شود.
    try:
        live_for_guard = float(live_price) if live_price is not None else float(d.iloc[latest_idx]["close"])
    except Exception:
        live_for_guard = float(d.iloc[latest_idx]["close"])
    if sig and atr and np.isfinite(live_for_guard) and live_for_guard > 0:
        level = pdl if sig == "BUY" else pdh
        too_far, invalidated = _active_setup_distance_check(
            live_for_guard, level, atr,
            cfg.get("active_setup_max_distance_atr", 0.80),
            cfg.get("active_setup_invalidation_atr", 0.25),
            sig == "BUY",
        )
        if not too_far and not invalidated:
            return sig, reason
        sig, reason = None, None
    elif sig:
        return sig, reason

    # If the daily liquidity is no longer realistically reachable, rotate the reference
    # instead of widening the old setup. This is the key anti-dead-bot mechanism.
    try:
        guard_atr = float(atr) if atr is not None and np.isfinite(atr) and atr > 0 else _safe_float(d.iloc[latest_idx].get("atr"), 0.0)
        daily_activation_atr = float(cfg.get("adaptive_activation_distance_atr", 1.00))
        daily_far = _is_daily_level_unreachable(live_for_guard, pdh, pdl, guard_atr, daily_activation_atr)
    except Exception:
        guard_atr = 0.0
        daily_far = False

    if daily_far:
        adaptive_sig, adaptive_reason, adaptive_atr = _detect_adaptive_liquidity(d, latest_idx, cfg)
        if adaptive_sig:
            # Do not allow adaptive continuation entries inside the previous-day range
            # unless a confirmed PDH/PDL breakout already happened. This prevents
            # buying below PDH or selling above PDL from intraday anchors.
            if _has_confirmed_daily_breakout(
                d, latest_idx, pdh, pdl, adaptive_sig,
                adaptive_atr if adaptive_atr else guard_atr,
                cfg
            ):
                return adaptive_sig, adaptive_reason

    if not bool(cfg.get("active_setup_enabled", True)):
        return None, "ستاپ جدیدی ثبت نشد"

    try:
        live = float(live_price) if live_price is not None else float(d.iloc[latest_idx]["close"])
    except Exception:
        live = float(d.iloc[latest_idx]["close"])
    if not np.isfinite(live) or live <= 0:
        return None, "قیمت فعلی معتبر نیست"

    max_age = max(1, int(cfg.get("active_setup_max_age_candles", cfg.get("active_setup_lookback_candles", 3))))
    lookback = max(max_age, int(cfg.get("active_setup_lookback_candles", 3)))
    min_idx = max(1, latest_idx - lookback)
    # Newest candidate wins. We intentionally do not search older than the short freshness window.
    latest_date = d.loc[latest_idx, "_date"] if "_date" in d.columns else None
    current = d.iloc[latest_idx]
    co, cc, ch, cl = (float(current["open"]), float(current["close"]),
                       float(current["high"]), float(current["low"]))
    for idx in range(latest_idx - 1, min_idx - 1, -1):
        if latest_date is not None and d.loc[idx, "_date"] != latest_date:
            continue
        sig, reason, atr = detect_at(idx)
        if not sig or atr <= 0:
            continue
        if not _has_confirmed_daily_breakout(d, idx, pdh, pdl, sig, atr, cfg):
            continue
        level = pdl if sig == "BUY" else pdh
        tol = atr * max(0.05, float(cfg.get("retest_tolerance_atr", 0.25)))
        max_dist = atr * max(0.20, float(cfg.get("active_setup_max_distance_atr", 0.80)))
        invalid_dist = atr * max(0.05, float(cfg.get("active_setup_invalidation_atr", 0.25)))

        # IMPORTANT: an old setup is NOT enough by itself. The latest closed candle
        # must now perform a fresh pullback/reclaim of the original PDH/PDL level.
        # This prevents entering merely because live price happens to be near the level.
        if sig == "BUY":
            retest = cl <= level + tol
            reclaimed = cc > level
            directional = (cc > co) if require_reversal else True
        else:
            retest = ch >= level - tol
            reclaimed = cc < level
            directional = (cc < co) if require_reversal else True
        if not (retest and reclaimed and directional):
            continue

        # The live price is only used as an anti-chasing guard after the closed-candle
        # revalidation above. We never enter from a live tick alone.
        if sig == "BUY":
            if live < level - invalid_dist or live > level + max_dist:
                continue
        else:
            if live > level + invalid_dist or live < level - max_dist:
                continue
        if bool(cfg.get("active_structure_confirmation", True)) or require_micro_structure:
            if not _confirm_active_structure(d, latest_idx, sig, cfg):
                continue

        age = latest_idx - idx
        return sig, (f"ACTIVE_SETUP_INDEX={idx} | فرصت بازیابی‌شده ({age} کندل قبل) | "
                     f"Pullback + Reclaim جدید روی سطح روز قبل تأیید شد | {reason} | "
                     f"ورود با قیمت فعلی، بدون تعقیب قیمت")

    return None, "ستاپ جدیدی ثبت نشد یا ستاپ‌های اخیر بدون Pullback/Reclaim جدید معتبر نیستند"

def _extend_stop_to_grid(levels, sweep_extreme, naive_sl, atr, direction):
    """
    اگر یک سطح شبکه‌ی لگاریتمی خیلی نزدیک به نقطه‌ی sweep باشد (حداکثر ۱.۵ ATR جلوتر)،
    استاپ را کمی جلوتر از آن سطح می‌گذاریم، نه فقط بر اساس بافر ثابت ATR - چون طبق
    بررسی کاربر قیمت تاریخی به این سطوح واکنش نشان داده و ممکن است قبل از برگشت واقعی
    یک ویک (wick) کوتاه به آن سطح بخورد؛ استاپ صرفاً ATR-محور ممکن است زودتر از موعد بخورد.
    """
    if not levels:
        return naive_sl
    if direction == -1:  # SELL: استاپ بالای sweep_extreme
        cands = [lv['price'] for lv in levels if sweep_extreme < lv['price'] <= sweep_extreme + atr * 1.5]
        if cands:
            return max(naive_sl, min(cands) + atr * 0.15)
    else:  # BUY: استاپ پایین sweep_extreme
        cands = [lv['price'] for lv in levels if sweep_extreme - atr * 1.5 <= lv['price'] < sweep_extreme]
        if cands:
            return min(naive_sl, max(cands) - atr * 0.15)
    return naive_sl


def _cap_target_to_grid(levels, entry, risk_dist, direction, min_rr, current_target):
    """
    اگر بین قیمت ورود و هدف فعلی یک سطح شبکه‌ی لگاریتمی معتبر (با رعایت حداقل R:R) وجود
    داشته باشد، هدف را به نزدیک‌ترین آن سطح محدود می‌کند - چون طبق بررسی تاریخی کاربر،
    قیمت معمولاً پیش از عبور از این سطوح واکنش نشان می‌دهد و رسیدن به هدف دورتر بعید است.
    """
    if not levels:
        return current_target
    candidates = []
    for lv in levels:
        p = lv['price']
        dist = (entry - p) if direction == -1 else (p - entry)
        if dist <= 0:
            continue
        if dist / risk_dist < min_rr:
            continue
        candidates.append((dist, p))
    if not candidates:
        return current_target
    candidates.sort()
    _, nearest_price = candidates[0]
    if direction == -1 and nearest_price > current_target:
        return nearest_price
    if direction == 1 and nearest_price < current_target:
        return nearest_price
    return current_target


def build_sweep_trade_plan(df, signal, strategy_config=None, grid_levels=None, setup_index=None, live_price=None, anchor_level=None, target_level=None, continuation=False, defer_quality_gate=False):
    if df is None or len(df) < 100 or signal not in ("BUY", "SELL"):
        return None, "داده کافی برای طراحی معامله وجود ندارد"
    d, pdh, pdl = _compute_prev_day_levels(df)
    if d is None or pdh is None or pdl is None:
        return None, "سطوح روز قبل هنوز آماده نیست"
    idx = (len(d) - 2) if setup_index is None else int(setup_index)
    if idx < 1 or idx >= len(d):
        return None, "شاخص ستاپ معتبر نیست"
    curr = d.iloc[idx]
    # Active setup: the liquidity anchor/extreme belongs to the original setup candle,
    # but risk must be sized from the latest closed candle because entry is current.
    risk_idx = len(d) - 2 if setup_index is not None else idx
    risk_row = d.iloc[risk_idx]
    try:
        entry = float(live_price) if (setup_index is not None and live_price is not None) else float(curr["close"])
        atr = float(risk_row["atr"])
    except Exception:
        return None, "ATR یا قیمت ورود نامعتبر است"
    if not np.isfinite(entry) or entry <= 0 or not np.isfinite(atr) or atr <= 0:
        return None, "ATR یا قیمت ورود نامعتبر است"

    cfg = {**STRATEGY_DEFAULTS, **(_cfg(strategy_config) or {})}
    min_rr = float(cfg.get("min_rr", 1.30))
    target_rr = max(min_rr, float(cfg.get("sweep_risk_reward", 1.8)))
    buffer_atr = max(0.40, float(cfg.get("sweep_stop_buffer_atr", 0.40)))
    min_sl_pct = float(cfg.get("min_sl_percent", 0.005))
    max_fee_ratio = float(cfg.get("max_fee_risk_ratio", 0.20))
    max_sl_atr = max(1.5, float(cfg.get("max_sl_atr", 3.00)))
    body_ratio = _safe_float(curr.get("body_ratio"), 0)
    vr = _safe_float(curr.get("volume_ratio"), 1)

    extend_to_structure = bool(cfg.get("extend_tp_to_pdl", True))

    if signal == "SELL":
        sweep_extreme = float(curr["high"])
        sl = sweep_extreme + (atr * buffer_atr)
        sl = _extend_stop_to_grid(grid_levels, sweep_extreme, sl, atr, -1)
        if (sl - entry) / entry < min_sl_pct:
            sl = entry * (1.0 + min_sl_pct)
        risk_dist = sl - entry
        if risk_dist <= 0:
            return None, "فاصله حد ضرر معتبر نیست"
        if risk_dist > atr * max_sl_atr:
            return None, "استاپ ساختاری بیش از حد دور است؛ معامله رد شد"
        reclaim_depth = (sweep_extreme - entry) / risk_dist
        soft_tp = entry - (risk_dist * target_rr)
        tp = soft_tp
        target_ref = float(target_level) if target_level is not None else pdl
        if extend_to_structure and target_ref < entry and (entry - target_ref) / risk_dist >= min_rr:
            tp = target_ref
        elif target_ref < entry and (entry - target_ref) / risk_dist >= min_rr:
            tp = max(tp, target_ref)
        tp = _cap_target_to_grid(grid_levels, entry, risk_dist, -1, min_rr, tp)
    else:
        sweep_extreme = float(curr["low"])
        sl = sweep_extreme - (atr * buffer_atr)
        sl = _extend_stop_to_grid(grid_levels, sweep_extreme, sl, atr, 1)
        if (entry - sl) / entry < min_sl_pct:
            sl = entry * (1.0 - min_sl_pct)
        risk_dist = entry - sl
        if risk_dist <= 0:
            return None, "فاصله حد ضرر معتبر نیست"
        if risk_dist > atr * max_sl_atr:
            return None, "استاپ ساختاری بیش از حد دور است؛ معامله رد شد"
        reclaim_depth = (entry - sweep_extreme) / risk_dist
        soft_tp = entry + (risk_dist * target_rr)
        tp = soft_tp
        target_ref = float(target_level) if target_level is not None else pdh
        if extend_to_structure and target_ref > entry and (target_ref - entry) / risk_dist >= min_rr:
            tp = target_ref
        elif target_ref > entry and (target_ref - entry) / risk_dist >= min_rr:
            tp = min(tp, target_ref)
        tp = _cap_target_to_grid(grid_levels, entry, risk_dist, 1, min_rr, tp)

    # فیلتر کارمزد به ریسک دلاری
    risk_pct = risk_dist / entry
    est_risk_usdt = 500.0 * risk_pct
    if est_risk_usdt > 0:
        if (0.50 / est_risk_usdt) > max_fee_ratio:
            return None, f"ریسک به کارمزد کوچک است ({est_risk_usdt:.2f}$)"

    rr = abs(tp - entry) / risk_dist
    if rr < min_rr:
        return None, f"R:R کافی نیست ({rr:.2f}R < {min_rr:.2f}R)"

    reclaim_score = min(35.0, max(0.0, reclaim_depth * 35.0))
    candle_score = min(20.0, max(0.0, body_ratio * 27.0))
    volume_score = min(20.0, max(0.0, (vr - 0.8) * 25.0))
    rr_score = min(15.0, max(0.0, (rr - min_rr) * 10.0))
    # این استراتژی خودش یک برگشت روی سطح کلیدی (PDH/PDL) است، پس همیشه «نزدیک سطح ساختاری»
    # و رژیم «رنج/برگشتی» در نظر گرفته می‌شود؛ کندل ریکلیم با الگوهای شناخته‌شده تقویت/تضعیف می‌شود.
    pattern_df = d.iloc[:idx + 1].copy() if setup_index is not None else df
    pattern_score, pattern_name = candle_pattern_score(pattern_df, signal, regime="range", near_structure=True, max_points=10.0)
    score = int(round(max(0.0, min(100.0, reclaim_score + candle_score + volume_score + rr_score + pattern_score))))

    min_score = float(cfg.get("min_trade_score", 58.0))
    quality_label = "عالی" if score >= 85 else "خوب" if score >= 75 else "قابل قبول" if score >= min_score else "ضعیف"
    # In V2 the final decision belongs to the adaptive evidence engine after
    # HTF/bias/direction adjustments.  Do not discard a structurally valid
    # candidate here just because its *raw* score is slightly below the final
    # threshold; otherwise HTF and direction evidence can never rescue it.
    if score < min_score and not defer_quality_gate:
        return None, f"امتیاز کیفیت پایین است ({score}/100)"

    plan = {
        "entry": entry, "sl": float(sl), "tp": float(tp), "score": score,
        "quality_label": quality_label, "rr": float(rr),
        "pdh": float(pdh), "pdl": float(pdl), "soft_tp": float(soft_tp),
        "anchor_level": float(anchor_level) if anchor_level is not None else (float(pdh) if signal == "SELL" else float(pdl)),
        "target_level": float(target_level) if target_level is not None else (float(pdl) if signal == "SELL" else float(pdh)),
        "structural_target": bool(target_level is not None or tp == pdl or tp == pdh),
        "risk_atr_source_index": int(risk_idx),
        "setup_index": int(idx),
        "pattern": pattern_name,
        "reason": f"Liquidity Sweep | کیفیت {score}/100 ({quality_label}) | عمق ریکلیم {reclaim_depth:.2f}x ریسک | R:R {rr:.2f}R" + (f" | الگو: {pattern_name}" if pattern_name else "")
    }
    return plan, plan["reason"]


def evaluate_trend_weakness(df, side, strategy_config=None):
    """
    بررسی می‌کند که آیا روند معامله باز، در حال از دست دادن قدرت است یا نه.
    برای استفاده در مدیریت خودکار پوزیشن: وقتی معامله سود دارد ولی هنوز به هدف
    ساختاری (PDH/PDL) نرسیده، این تابع علائم ضعف را روی آخرین کندل بسته‌شده
    می‌سنجد تا در صورت لزوم با سود بسته شود؛ در غیر این صورت اجازه می‌دهد
    معامله تا رسیدن به هدف ادامه یابد.

    df باید از قبل با calculate_indicators پردازش شده باشد (حداقل ۶۰ کندل).
    side: 'BUY'/'LONG' یا 'SELL'/'SHORT'

    خروجی: (is_weak: bool, score: int 0-100, reasons: list[str])
    """
    if df is None or len(df) < 20:
        return False, 0, []
    required_cols = {"adx", "rsi", "ema20", "plus_di", "minus_di", "body_ratio", "volume_ratio"}
    if not required_cols.issubset(df.columns):
        return False, 0, []

    cfg = {**STRATEGY_DEFAULTS, **(_cfg(strategy_config) or {})}
    curr = df.iloc[-2]
    prev = df.iloc[-3] if len(df) >= 3 else curr
    is_long = isinstance(side, str) and ("BUY" in side.upper() or "LONG" in side.upper())

    adx = _safe_float(curr.get("adx"), 0)
    prev_adx = _safe_float(prev.get("adx"), adx)
    rsi = _safe_float(curr.get("rsi"), 50)
    plus_di = _safe_float(curr.get("plus_di"), 0)
    minus_di = _safe_float(curr.get("minus_di"), 0)
    ema20 = _safe_float(curr.get("ema20"), 0)
    close = _safe_float(curr.get("close"), 0)
    open_ = _safe_float(curr.get("open"), 0)
    body_ratio = _safe_float(curr.get("body_ratio"), 0)
    vr = _safe_float(curr.get("volume_ratio"), 1)

    score = 0.0
    reasons = []

    if is_long:
        if minus_di > plus_di:
            score += 30.0; reasons.append("DI منفی از DI مثبت عبور کرد (تغییر جهت روند)")
        if adx < prev_adx and adx < 22:
            score += 15.0; reasons.append(f"قدرت روند (ADX={adx:.1f}) رو به افت است")
        if close < ema20:
            score += 20.0; reasons.append("قیمت زیر EMA20 بسته شد")
        if rsi < 45:
            score += 15.0; reasons.append(f"RSI ضعیف شده ({rsi:.1f})")
        if close < open_ and body_ratio >= 0.55 and vr >= 1.0:
            score += 20.0; reasons.append("کندل نزولی قدرتمند مخالف روند با حجم بالا")
    else:
        if plus_di > minus_di:
            score += 30.0; reasons.append("DI مثبت از DI منفی عبور کرد (تغییر جهت روند)")
        if adx < prev_adx and adx < 22:
            score += 15.0; reasons.append(f"قدرت روند (ADX={adx:.1f}) رو به افت است")
        if close > ema20:
            score += 20.0; reasons.append("قیمت بالای EMA20 بسته شد")
        if rsi > 55:
            score += 15.0; reasons.append(f"RSI ضعیف شده ({rsi:.1f})")
        if close > open_ and body_ratio >= 0.55 and vr >= 1.0:
            score += 20.0; reasons.append("کندل صعودی قدرتمند مخالف روند با حجم بالا")

    score = max(0.0, min(100.0, score))
    threshold = float(cfg.get("weakness_exit_score", 45.0))
    is_weak = score >= threshold
    return is_weak, int(round(score)), reasons


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


def check_candlestick_confirmation(df, filters=None, strategy_config=None):
    f = _flt(filters)
    curr = df.iloc[-2]
    prev = df.iloc[-3]
    min_ratio = float(_cfg(strategy_config).get("min_volume_ratio", 1.0)) if strategy_config else 1.0
    vol_ok, vol_reason = check_volume(df, -2, f, min_ratio)
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
    p = get_strategy_params(strategy_config)
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
            ok, reason = check_volume(df, -2, f, float(p["volume_ratio"]))
            return ("BUY", f"روندی خرید | {reason}") if ok else (None, reason)
        sig, reason = check_candlestick_confirmation(df, f, strategy_config)
        return ("BUY", f"روندی خرید + {reason}") if sig in ("BUY_CONFIRMED", "CONFIRMED") else (None, reason)
    if down and touch_sell and curr["close"] < curr["ema20"]:
        if not f.get("candlestick_filter", True):
            ok, reason = check_volume(df, -2, f, float(p["volume_ratio"]))
            return ("SELL", f"روندی فروش | {reason}") if ok else (None, reason)
        sig, reason = check_candlestick_confirmation(df, f, strategy_config)
        return ("SELL", f"روندی فروش + {reason}") if sig in ("SELL_CONFIRMED", "CONFIRMED") else (None, reason)
    return None, "شرایط روندی برقرار نیست"


def strategy_breakout(df, filters=None, strategy_config=None):
    curr, prev = df.iloc[-2], df.iloc[-3]
    if pd.isna(curr.get("channel_high")) or pd.isna(curr.get("channel_low")):
        return None, "کانال آماده نیست"
    f = _flt(filters)
    p = get_strategy_params(strategy_config)
    adx = _safe_float(curr.get("adx"))
    if adx < max(15.0, p["adx"] - 5):
        return None, f"ADX پایین است ({adx:.1f})"
    vr = _safe_float(curr.get("volume_ratio"), 0)
    if f.get("volume_filter", True) and vr < p["volume_ratio"]:
        return None, f"حجم شکست کافی نیست ({vr:.2f}x)"
    if _safe_float(curr.get("body_ratio"), 0) < p["body_ratio"]:
        return None, "قدرت بدنه کافی نیست"
    trend_buy = curr["close"] > curr["ema20"] > curr["ema50"] and curr["plus_di"] > curr["minus_di"]
    trend_sell = curr["close"] < curr["ema20"] < curr["ema50"] and curr["minus_di"] > curr["plus_di"]
    bull = curr["close"] > curr["channel_high"] and prev["close"] <= prev.get("channel_high", np.inf) and trend_buy and adx >= p["adx"]
    bear = curr["close"] < curr["channel_low"] and prev["close"] >= prev.get("channel_low", -np.inf) and trend_sell and adx >= p["adx"]
    if not (bull or bear):
        return None, "شکست جدیدی ثبت نشد"
    if not f.get("candlestick_filter", True):
        return ("BUY", "شکست صعودی تأیید شد") if bull else ("SELL", "شکست نزولی تأیید شد")
    sig, reason = check_candlestick_confirmation(df, f, strategy_config)
    if bull and sig in ("BUY_CONFIRMED", "CONFIRMED"):
        return "BUY", f"شکست صعودی + {reason}"
    if bear and sig in ("SELL_CONFIRMED", "CONFIRMED"):
        return "SELL", f"شکست نزولی + {reason}"
    return None, reason


def strategy_mean_reversion(df, filters=None, strategy_config=None):
    curr = df.iloc[-2]
    rsi, adx = _safe_float(curr.get("rsi"), 50), _safe_float(curr.get("adx"), 50)
    p = get_strategy_params(strategy_config)
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


def _htf_trend_aligned(df, want_bullish):
    if df is None or df.empty or len(df) < 55:
        return None
    try:
        c = df.iloc[-2]
        if want_bullish:
            return bool(c["close"] > c["ema20"] > c["ema50"] and c["plus_di"] > c["minus_di"])
        return bool(c["close"] < c["ema20"] < c["ema50"] and c["minus_di"] > c["plus_di"])
    except Exception:
        return None


def strategy_htf_liquidity_reversal(df_primary, market_data_dict=None, timeframe="1h", filters=None, strategy_config=None):
    """HTF liquidity reversal model for 1H/4H.
    Uses higher-timeframe liquidity events instead of intraday breakout chasing.
    Entry requires sweep/reclaim + structure confirmation.
    """
    if df_primary is None or len(df_primary) < 80:
        return None, "HTF: داده کافی نیست"

    d = df_primary.copy()
    try:
        atr = float(d.iloc[-2].get("atr", 0) or 0)
    except Exception:
        atr = 0
    if atr <= 0:
        return None, "HTF: ATR نامعتبر"

    high = float(d.iloc[-2]["high"])
    low = float(d.iloc[-2]["low"])
    close = float(d.iloc[-2]["close"])

    # HTF liquidity anchors. Prefer supplied higher timeframe levels;
    # fallback to local structure if unavailable.
    anchors = market_data_dict or {}
    prev_week_high = anchors.get("prev_week_high")
    prev_week_low = anchors.get("prev_week_low")
    prev_month_high = anchors.get("prev_month_high")
    prev_month_low = anchors.get("prev_month_low")
    prev_day_high = anchors.get("prev_day_high")
    prev_day_low = anchors.get("prev_day_low")

    if timeframe in ("4h", "4hour"):
        resistance = prev_month_high or prev_week_high
        support = prev_month_low or prev_week_low
    else:
        resistance = prev_week_high or prev_day_high
        support = prev_week_low or prev_day_low

    # Fallback keeps old datasets compatible.
    highs = float(resistance) if resistance is not None else d["high"].rolling(20).max().iloc[-3]
    lows = float(support) if support is not None else d["low"].rolling(20).min().iloc[-3]

    # Long: liquidity grab below support + reclaim + bullish structure candle
    if low < lows and close > lows and close > float(d.iloc[-3]["close"]):
        return "BUY", "HTF Liquidity Sweep + Reclaim + ساختار صعودی تأیید شد"

    # Short: liquidity grab above resistance + reclaim + bearish structure candle
    if high > highs and close < highs and close < float(d.iloc[-3]["close"]):
        return "SELL", "HTF Liquidity Sweep + Reclaim + ساختار نزولی تأیید شد"

    return None, "HTF: ستاپ نقدینگی تشکیل نشده"


def strategy_dynamic(df_primary, market_data_dict=None, timeframe="5min", filters=None, strategy_config=None, regime=None):
    break_sig, break_reason = strategy_breakout(df_primary, filters, strategy_config)
    if break_sig not in ("BUY", "SELL"):
        return None, break_reason
    want_bullish = break_sig == "BUY"

    if isinstance(market_data_dict, dict) and any(k in market_data_dict for k in ("4h", "1h", "1d")):
        checks = []
        for key in ("1d", "4h", "1h"):
            aligned = _htf_trend_aligned(market_data_dict.get(key), want_bullish)
            if aligned is not None:
                checks.append((key, aligned))
        if checks:
            not_aligned = [k for k, ok in checks if not ok]
            if not_aligned:
                return None, f"شکست تأیید نشد چون روند {', '.join(not_aligned)} هم‌جهت نیست"
            confirmed = ", ".join(k for k, _ in checks)
            return break_sig, f"[شکست-قوی + تأیید {confirmed}] {break_reason}"

    return break_sig, f"[شکست-قوی] {break_reason}"


def get_signal_with_reason(df_primary, market_data_dict=None, timeframe_mode="single", timeframe="5min", strategy_type="trend", filters=None, strategy_config=None, regime=None, live_price=None):
    if df_primary is None or df_primary.empty or len(df_primary) < 60:
        return None, "داده کافی نیست"
    st = strategy_type
    if st == "dynamic" and timeframe in ("1h", "4h", "1hour", "4hour"):
        sig, reason = strategy_htf_liquidity_reversal(df_primary, market_data_dict, timeframe, filters, strategy_config)
    elif st == "dynamic" and get_v2_config(strategy_config).get("v2_enabled", True):
        sig, reason = strategy_dynamic_v2(df_primary, market_data_dict, timeframe, filters, strategy_config, regime, live_price=live_price)
    elif st == "dynamic":
        if timeframe in ("5min", "15min"):
            sig, reason = strategy_liquidity_sweep_5m(df_primary, filters, strategy_config, live_price=live_price, timeframe=timeframe)
        else:
            sig, reason = strategy_dynamic(df_primary, market_data_dict, timeframe, filters, strategy_config, regime)
    elif st == "trend":
        sig, reason = strategy_trend_following(df_primary, timeframe, filters, strategy_config)
    elif st == "breakout":
        sig, reason = strategy_breakout(df_primary, filters, strategy_config)
    elif st == "mean_reversion":
        sig, reason = strategy_mean_reversion(df_primary, filters, strategy_config)
    else:
        sig, reason = strategy_trend_following(df_primary, timeframe, filters, strategy_config)

    # Market regime دیگر قفل سخت ورود نیست. V2 آن را داخل امتیاز و آستانه‌ی
    # لازم برای ستاپ خلاف جهت اعمال می‌کند. برای استراتژی‌های قدیمی هم سیگنال
    # خلاف جهت صرفاً اجازه‌ی بررسی بیشتر دارد و حذف نمی‌شود.
    if sig in ("BUY", "SELL") and regime in ("BULLISH", "BEARISH"):
        direction_text = "صعودی" if regime == "BULLISH" else "نزولی"
        side_text = "خرید" if sig == "BUY" else "فروش"
        return sig, f"{reason} | جهت غالب بازار: {direction_text}؛ {side_text} به‌صورت فرصت خلاف‌جهت بررسی شد"
    return sig, reason

# ========================= STRATEGY V2 =========================
# Adaptive regime + setup selection + execution-quality filters.
# This layer intentionally keeps the public APIs above backward compatible.

V2_DEFAULTS = {
    "v2_enabled": True,
    "regime_adx_trend": 23.0,
    "regime_adx_strong": 30.0,
    "regime_atr_high": 1.35,
    "regime_atr_low": 0.75,
    "ema_slope_min_atr": 0.03,
    "min_edge_proxy": 0.10,
    "use_edge_proxy_gate": False,
    # ضد بیش‌فیلتر شدن: ستاپ خوب نباید به خاطر چند ناهماهنگی جزئی خفه شود.
    "min_setup_score": 60.0,
    "high_vol_min_score": 66.0,
    "high_vol_min_rr": 1.45,
    # Market bias فقط «مالیات خلاف جهت» است، نه دروازه‌ی ورود.
    "directional_aligned_bonus": 2.0,
    "directional_opposite_penalty": 6.0,
    "directional_opposite_extra_score": 8.0,
    "directional_opposite_extra_rr": 0.10,
    # PDH/PDL Equilibrium (میان‌بها = وسط PDH و PDL، مفهوم Premium/Discount).
    # همانند directional bias، فقط «مالیات» است: هرگز معامله را رد نمی‌کند،
    # فقط امتیاز رتبه‌بندی بین کاندیداها را کمی جابه‌جا می‌کند.
    "eq_bias_enabled": True,
    "eq_aligned_bonus": 2.0,
    "eq_counter_penalty": 3.0,
    "range_max_adx": 20.0,
    "range_rsi_buy": 34.0,
    "range_rsi_sell": 66.0,
    "trend_pullback_atr": 0.35,
    "breakout_volume": 1.15,
    "breakout_body": 0.55,
    "sweep_score_bonus": 8.0,
    "regime_confidence_min": 0.55,
    "max_atr_ratio_for_entry": 2.20,
    # Adaptive intraday liquidity: deliberately conservative to prevent signal spam.
    "adaptive_activation_distance_atr": 1.00,
    "adaptive_min_level_candles": 6,
    "adaptive_opening_range_minutes": 30,
    "adaptive_swing_left": 2,
    "adaptive_swing_right": 2,
    "adaptive_max_anchor_distance_atr": 1.60,
    "adaptive_min_anchor_distance_atr": 0.20,
    "adaptive_sweep_min_distance_atr": 0.15,
    "adaptive_retest_tolerance_atr": 0.22,
    "adaptive_min_volume_ratio": 1.12,
    "adaptive_min_body_ratio": 0.50,
    "adaptive_min_target_distance_atr": 1.20,
    "adaptive_trend_adx": 23.0,
}


def get_v2_config(strategy_config=None):
    cfg = {**STRATEGY_DEFAULTS, **V2_DEFAULTS}
    if isinstance(strategy_config, dict):
        cfg.update(strategy_config)
    return cfg


def _ema_slope_atr(df, ema_col="ema20", lookback=5):
    if df is None or len(df) < lookback + 3 or ema_col not in df.columns or "atr" not in df.columns:
        return 0.0
    c = df.iloc[-2]
    prev = df.iloc[-2 - lookback]
    atr = _safe_float(c.get("atr"), 0.0)
    if atr <= 0:
        return 0.0
    return (_safe_float(c.get(ema_col)) - _safe_float(prev.get(ema_col))) / atr


def detect_market_regime(df, strategy_config=None):
    """Return trend and volatility as separate state dimensions.

    The previous implementation made HIGH_VOL mutually exclusive with trend,
    which could route a strong high-vol trend into mean reversion. Here trend
    state is detected first from directional structure, while volatility is
    reported independently.
    """
    if df is None or len(df) < 65:
        return {
            "name": "MIXED", "confidence": 0.0, "atr_ratio": 1.0,
            "trend_strength": 0.0, "trend_state": "NEUTRAL",
            "volatility_state": "NORMAL",
        }
    cfg = get_v2_config(strategy_config)
    c = df.iloc[-2]
    adx = _safe_float(c.get("adx"), 0)
    atr = _safe_float(c.get("atr"), 0)
    hist = pd.to_numeric(df["atr"].iloc[-62:-2], errors="coerce").dropna()
    med_atr = float(hist.median()) if len(hist) else atr
    atr_ratio = atr / max(med_atr, 1e-12)
    slope = _ema_slope_atr(df, "ema20", 5)
    close = _safe_float(c.get("close"))
    ema20 = _safe_float(c.get("ema20"))
    ema50 = _safe_float(c.get("ema50"))
    plus = _safe_float(c.get("plus_di"))
    minus = _safe_float(c.get("minus_di"))
    bull = close > ema20 > ema50 and plus > minus and slope > 0
    bear = close < ema20 < ema50 and minus > plus and slope < 0
    strong_trend = adx >= float(cfg["regime_adx_trend"]) and abs(slope) >= float(cfg["ema_slope_min_atr"])
    if strong_trend and bull:
        trend_state = "BULL"
    elif strong_trend and bear:
        trend_state = "BEAR"
    elif adx <= float(cfg["range_max_adx"]):
        trend_state = "RANGE"
    else:
        trend_state = "NEUTRAL"

    if atr_ratio >= float(cfg["regime_atr_high"]):
        volatility_state = "HIGH"
    elif atr_ratio <= float(cfg["regime_atr_low"]):
        volatility_state = "LOW"
    else:
        volatility_state = "NORMAL"

    # Preserve stable names for downstream/UI compatibility while ensuring
    # strong trends remain trend regimes even when volatility is high/low.
    if trend_state == "BULL":
        name = "TREND_BULL"
        conf = 0.60 + min(0.35, max(0.0, (adx - 23.0) / 30.0))
    elif trend_state == "BEAR":
        name = "TREND_BEAR"
        conf = 0.60 + min(0.35, max(0.0, (adx - 23.0) / 30.0))
    elif trend_state == "RANGE":
        name = "RANGE"
        conf = 0.55 + max(0.0, (20.0 - adx) / 30.0)
    elif volatility_state == "HIGH":
        name = "HIGH_VOL"
        conf = 0.55 + min(0.35, max(0.0, (atr_ratio - 1.0) * 0.45))
    elif volatility_state == "LOW":
        name = "LOW_VOL"
        conf = 0.55 + min(0.30, max(0.0, (1.0 - atr_ratio) * 0.7))
    else:
        name = "MIXED"
        conf = 0.50
    trend_strength = min(1.0, adx / 40.0) * min(1.0, abs(slope) / 0.15 if slope else 0.0)
    return {
        "name": name,
        "confidence": round(min(1.0, conf), 3),
        "atr_ratio": float(atr_ratio),
        "trend_strength": float(trend_strength),
        "ema_slope_atr": float(slope),
        "adx": float(adx),
        "trend_state": trend_state,
        "volatility_state": volatility_state,
    }


def _v2_htf_bias(market_data_dict, want_bullish):
    if not isinstance(market_data_dict, dict):
        return 0.0, []
    weights = {"1d": 0.40, "4h": 0.30, "1h": 0.20, "15m": 0.10}
    total = 0.0
    used = 0.0
    details = []
    for key, weight in weights.items():
        d = market_data_dict.get(key)
        if d is None or d.empty or len(d) < 55:
            continue
        c = d.iloc[-2]
        adx = _safe_float(c.get("adx"), 0)
        if want_bullish:
            aligned = _safe_float(c.get("close")) > _safe_float(c.get("ema20")) > _safe_float(c.get("ema50")) and _safe_float(c.get("plus_di")) >= _safe_float(c.get("minus_di"))
        else:
            aligned = _safe_float(c.get("close")) < _safe_float(c.get("ema20")) < _safe_float(c.get("ema50")) and _safe_float(c.get("minus_di")) >= _safe_float(c.get("plus_di"))
        strength = min(1.0, adx / 30.0)
        total += weight * (strength if aligned else -strength)
        used += weight
        details.append(f"{key}:{'+' if aligned else '-'}{strength:.2f}")
    return (total / used if used else 0.0), details


def _v2_edge_proxy(score, rr, regime_name, atr_ratio):
    """Conservative expectancy proxy. It is NOT a backtest-derived probability."""
    base_p = 0.40 + max(0.0, min(0.18, (float(score) - 55.0) / 250.0))
    if regime_name in ("TREND_BULL", "TREND_BEAR"):
        base_p += 0.025
    elif regime_name == "RANGE":
        base_p += 0.015
    elif regime_name == "HIGH_VOL":
        base_p -= 0.035
    if atr_ratio > 1.8:
        base_p -= 0.03
    base_p = max(0.30, min(0.65, base_p))
    ev = base_p * float(rr) - (1.0 - base_p)
    return float(ev), float(base_p)


def _v2_score_thresholds(vol_state, cfg):
    """Return effective final-entry thresholds without weakening the active
    user/session profile. V2 provides a safety floor; the effective gate is
    the strictest applicable requirement.
    """
    configured_score = float(cfg.get("min_trade_score", 0.0) or 0.0)
    v2_score_floor = float(cfg.get("min_setup_score", 60.0))
    min_score = max(configured_score, v2_score_floor)

    configured_rr = float(cfg.get("min_rr", 0.0) or 0.0)
    min_rr = max(configured_rr, 1.30)

    if vol_state == "HIGH":
        min_score = max(min_score, float(cfg.get("high_vol_min_score", 66.0)))
        min_rr = max(min_rr, float(cfg.get("high_vol_min_rr", 1.45)))
    return min_score, min_rr


def _v2_passes_setup_gates(score, rr, vol_state, cfg, ev):
    """Pure: does this candidate setup clear the score/RR/edge-proxy gates?"""
    min_score, min_rr = _v2_score_thresholds(vol_state, cfg)
    if score < min_score or rr < min_rr:
        return False
    if bool(cfg.get("use_edge_proxy_gate", False)) and ev < float(cfg["min_edge_proxy"]):
        return False
    return True


def _v2_rank_key(score, rr):
    """Pure: sort key used to pick the best among competing candidate setups
    generated in the same scan cycle (e.g. a trend continuation vs a breakout
    signal firing simultaneously). RR is floored at 0.01 so a zero/negative RR
    plan never ranks as a false tie with a genuinely-zero-score plan.
    """
    return score * max(rr, 0.01)


def _select_v2_setup(df_primary, market_data_dict=None, timeframe="5min", filters=None, strategy_config=None, regime=None, grid_levels=None, live_price=None):
    cfg = get_v2_config(strategy_config)
    regime_info = detect_market_regime(df_primary, cfg)
    rname = regime_info["name"]
    rconf = regime_info["confidence"]
    trend_state = regime_info.get("trend_state", "NEUTRAL")
    vol_state = regime_info.get("volatility_state", "NORMAL")
    candidates = []

    # Equilibrium (میان‌بها) = وسط PDH/PDL. فقط یک‌بار محاسبه می‌شود و بین همه‌ی
    # کاندیداها به‌اشتراک گذاشته می‌شود؛ اگر PDH/PDL هنوز کامل نشده باشد (روز اول)
    # eq_level برابر None می‌ماند و این تعدیل به‌سادگی خاموش می‌شود.
    eq_level = None
    if bool(cfg.get("eq_bias_enabled", True)):
        _, _eq_pdh, _eq_pdl = _compute_prev_day_levels(df_primary)
        if _eq_pdh is not None and _eq_pdl is not None:
            eq_level = (_eq_pdh + _eq_pdl) / 2.0

    # Regime confidence is contextual evidence, not a hard entry gate.
    # A neutral/mixed market (normally confidence=0.50) must still reach the
    # existing setup families; each candidate is independently protected by
    # score/RR, volatility, directional and execution-quality gates below.
    # Keeping this as a diagnostic preserves observability without creating a
    # dead-zone in 5m/15m where valid sweep/pullback/retest setups never get
    # evaluated.

    def add_candidate(sig, reason, family, bonus=0):
        if sig not in ("BUY", "SELL"):
            return
        # Risk plan must use the signal timeframe. HTF is context, not execution.
        plan_tf = timeframe
        active_setup_index = None
        if family == "liquidity_sweep":
            m_active = __import__("re").search(r"ACTIVE_SETUP_INDEX=(\d+)", reason or "")
            if m_active:
                active_setup_index = int(m_active.group(1))
        anchor_level = None
        target_level = None
        if family == "liquidity_sweep" and "ADAPTIVE_SWEEP" in (reason or ""):
            import re as _re
            ma = _re.search(r"\bANCHOR=([0-9.eE+-]+)", reason or "")
            mt = _re.search(r"\bTARGET=([0-9.eE+-]+)", reason or "")
            if ma:
                try: anchor_level = float(ma.group(1))
                except Exception: anchor_level = None
            if mt:
                try: target_level = float(mt.group(1))
                except Exception: target_level = None
        if family == "liquidity_sweep":
            plan, plan_reason = build_sweep_trade_plan(
                df_primary, sig, cfg, grid_levels=grid_levels,
                setup_index=active_setup_index, live_price=live_price,
                anchor_level=anchor_level, target_level=target_level,
                defer_quality_gate=True
            )
        else:
            plan, plan_reason = build_trade_plan(
                df_primary, sig, cfg, family, strategy_timeframe=plan_tf,
                grid_levels=grid_levels, setup_index=active_setup_index, live_price=live_price,
                defer_quality_gate=True
            )
        if not plan:
            return
        htf, htf_details = _v2_htf_bias(market_data_dict, sig == "BUY")
        score = float(plan.get("score", 0)) + float(bonus)
        score += max(-8.0, min(8.0, htf * 8.0))

        # بازارخوانی یک «جهت ترجیحی» است، نه قفل ورود.
        # اگر ستاپ خلاف جهت بازار شدیداً غالب باشد، فقط کمی مالیات کیفیت می‌گیرد
        # و برای ورود باید امتیاز/RR بهتری نشان دهد؛ در غیر این صورت معامله همچنان ممکن است.
        directional_context = "NEUTRAL"
        directional_adjustment = 0.0
        extra_score = 0.0
        extra_rr = 0.0
        if regime in ("BULLISH", "BEARISH"):
            aligned = (regime == "BULLISH" and sig == "BUY") or (regime == "BEARISH" and sig == "SELL")
            directional_context = "ALIGNED" if aligned else "COUNTER"
            directional_adjustment = (
                float(cfg.get("directional_aligned_bonus", 2.0))
                if aligned else -float(cfg.get("directional_opposite_penalty", 6.0))
            )
            if not aligned:
                extra_score = float(cfg.get("directional_opposite_extra_score", 8.0))
                extra_rr = float(cfg.get("directional_opposite_extra_rr", 0.10))
        score = max(0.0, min(100.0, score + directional_adjustment))

        # PDH/PDL Equilibrium (میان‌بها): خرید در Discount (زیر EQ) و فروش در
        # Premium (بالای EQ) هم‌جهت با منطق liquidity/PDH-PDL همین پروژه است.
        # عمداً سبک‌تر از directional bias است و هرگز روی گیت امتیاز/RR اثر
        # نمی‌گذارد — فقط رتبه‌بندی بین کاندیداهای موجود را کمی جابه‌جا می‌کند.
        eq_context = "NEUTRAL"
        eq_adjustment = 0.0
        entry_px = _safe_float(plan.get("entry"), 0.0)
        if eq_level is not None and entry_px > 0:
            in_discount = entry_px < eq_level
            in_premium = entry_px > eq_level
            aligned_bonus = float(cfg.get("eq_aligned_bonus", 2.0))
            counter_penalty = float(cfg.get("eq_counter_penalty", 3.0))
            if sig == "BUY" and in_discount:
                eq_context, eq_adjustment = "DISCOUNT_ALIGNED", aligned_bonus
            elif sig == "BUY" and in_premium:
                eq_context, eq_adjustment = "PREMIUM_COUNTER", -counter_penalty
            elif sig == "SELL" and in_premium:
                eq_context, eq_adjustment = "PREMIUM_ALIGNED", aligned_bonus
            elif sig == "SELL" and in_discount:
                eq_context, eq_adjustment = "DISCOUNT_COUNTER", -counter_penalty
        score = max(0.0, min(100.0, score + eq_adjustment))

        rr = float(plan.get("rr", 0))
        ev, pwin = _v2_edge_proxy(score, rr, rname, regime_info["atr_ratio"])
        # Strong trend is allowed to remain directional even in HIGH/LOW volatility,
        # but high volatility requires stricter score/RR. Mean reversion is never selected
        # merely because volatility is high. Market bias only raises the bar for a
        # counter-directional setup; it never hard-blocks it.
        min_score_gate, min_rr_gate = _v2_score_thresholds(vol_state, cfg)
        if directional_context == "COUNTER":
            min_score_gate += extra_score
            min_rr_gate += extra_rr
        if score < min_score_gate or rr < min_rr_gate:
            return
        if bool(cfg.get("use_edge_proxy_gate", False)) and ev < float(cfg["min_edge_proxy"]):
            return
        plan = dict(plan)
        plan.update({
            "score": int(round(score)),
            "regime": rname,
            "regime_confidence": rconf,
            "trend_state": trend_state,
            "volatility_state": vol_state,
            "htf_bias": float(htf),
            "htf_details": htf_details,
            "edge_proxy": round(ev, 4),
            "model_win_proxy": round(pwin, 4),
            "setup_family": family,
            "directional_context": directional_context,
            "directional_adjustment": round(directional_adjustment, 2),
            "directional_gate_score": round(min_score_gate, 2),
            "directional_gate_rr": round(min_rr_gate, 2),
            "eq_level": round(eq_level, 6) if eq_level is not None else None,
            "eq_context": eq_context,
            "eq_adjustment": round(eq_adjustment, 2),
        })
        candidates.append((_v2_rank_key(score, rr), plan, sig, f"V2 {rname}/{vol_state} | {family} | {reason} | HTF={htf:.2f} | EdgeProxy={ev:.2f}" + (f" | EQ={eq_context}" if eq_context != "NEUTRAL" else "")))

    if timeframe in ("5min", "15min"):
        # Keep the proven liquidity-sweep path, but let a clean trend-pullback
        # setup compete for the same entry slot. This increases opportunity
        # coverage without lowering the safety floors: both candidates still
        # pass the same final V2 score/RR gates and only the best candidate wins.
        sig, reason = strategy_liquidity_sweep_5m(
            df_primary, filters, cfg, live_price=live_price, timeframe=timeframe
        )
        family = "trend" if "ADAPTIVE_CONTINUATION" in (reason or "") else "liquidity_sweep"
        add_candidate(
            sig, reason, family,
            float(cfg["sweep_score_bonus"]) if family == "liquidity_sweep" else 3.0
        )

        trend_sig, trend_reason = strategy_trend_following(
            df_primary, timeframe, filters, cfg
        )
        if trend_sig:
            add_candidate(trend_sig, trend_reason, "trend_pullback", 4.0)

        # New independent family: local breakout -> retest -> continuation.
        # It competes on the same V2 safety/quality gates; it does not weaken them.
        br_sig, br_reason = strategy_breakout_retest_5m15m(
            df_primary, filters, cfg
        )
        if br_sig:
            add_candidate(br_sig, br_reason, "breakout_retest", 5.0)
    else:
        # Strategy selection is driven by trend state, while volatility only changes
        # strictness. This prevents high-vol trends from being treated as mean-reversion.
        if trend_state in ("BULL", "BEAR", "NEUTRAL"):
            sig, reason = strategy_trend_following(df_primary, timeframe, filters, cfg)
            add_candidate(sig, reason, "trend", 4 if trend_state in ("BULL", "BEAR") else 0)
            sig, reason = strategy_breakout(df_primary, filters, cfg)
            add_candidate(sig, reason, "breakout", 6 if trend_state in ("BULL", "BEAR") else 2)
        if trend_state in ("RANGE", "NEUTRAL"):
            sig, reason = strategy_mean_reversion(df_primary, filters, cfg)
            add_candidate(sig, reason, "mean_reversion", 0)

    if not candidates:
        return None, None, (
            f"V2: ستاپ مناسب پیدا نشد | regime={rname} trend={trend_state} "
            f"vol={vol_state} conf={rconf:.2f} ATRx={regime_info['atr_ratio']:.2f}"
        )
    candidates.sort(key=lambda x: x[0], reverse=True)
    _, best_plan, best_sig, best_reason = candidates[0]
    return best_sig, best_plan, best_reason



def strategy_breakout_retest_5m15m(df, filters=None, strategy_config=None):
    """Local breakout -> retest -> continuation candidate for 5m/15m.

    This is deliberately an additional candidate family, not a bypass around
    V2. It only proposes a setup after a confirmed local channel breakout,
    followed by a fresh retest/hold on the latest closed candle. Final score,
    RR, HTF context, regime and all safety gates are still applied downstream.
    """
    if df is None or len(df) < 65:
        return None, "Breakout-retest: داده کافی نیست"

    curr = df.iloc[-2]
    prev = df.iloc[-3]
    atr = _safe_float(curr.get("atr"), 0.0)
    if atr <= 0:
        return None, "Breakout-retest: ATR نامعتبر"

    ch = _safe_float(prev.get("channel_high"), np.nan)
    cl = _safe_float(prev.get("channel_low"), np.nan)
    prev_ch = _safe_float(df.iloc[-4].get("channel_high"), np.nan)
    prev_cl = _safe_float(df.iloc[-4].get("channel_low"), np.nan)

    if not (np.isfinite(ch) and np.isfinite(cl) and np.isfinite(prev_ch) and np.isfinite(prev_cl)):
        return None, "Breakout-retest: کانال آماده نیست"

    vr = _safe_float(curr.get("volume_ratio"), 0.0)
    body = _safe_float(curr.get("body_ratio"), 0.0)
    adx = _safe_float(curr.get("adx"), 0.0)
    tol = atr * 0.30

    # Previous candle must have closed outside the local channel.
    broke_up = float(prev["close"]) > ch and float(df.iloc[-4]["close"]) <= prev_ch
    broke_down = float(prev["close"]) < cl and float(df.iloc[-4]["close"]) >= prev_cl

    # Latest closed candle must retest the broken level and hold it.
    if broke_up:
        touched = float(curr["low"]) <= ch + tol
        held = float(curr["close"]) > ch
        directional = float(curr["close"]) > float(curr["open"])
        if touched and held and directional and adx >= 18.0 and body >= 0.35 and vr >= 0.90:
            return "BUY", (
                f"Breakout-Retest صعودی | سطح={ch:.6g} | "
                f"پولبک به شکست + حفظ سطح | ADX={adx:.1f} | حجم={vr:.2f}x"
            )

    if broke_down:
        touched = float(curr["high"]) >= cl - tol
        held = float(curr["close"]) < cl
        directional = float(curr["close"]) < float(curr["open"])
        if touched and held and directional and adx >= 18.0 and body >= 0.35 and vr >= 0.90:
            return "SELL", (
                f"Breakout-Retest نزولی | سطح={cl:.6g} | "
                f"پولبک به شکست + حفظ سطح | ADX={adx:.1f} | حجم={vr:.2f}x"
            )

    return None, "Breakout-retest: شکست و پولبک معتبر هم‌زمان تشکیل نشده"


def strategy_dynamic_v2(df_primary, market_data_dict=None, timeframe="5min", filters=None, strategy_config=None, regime=None, live_price=None):
    sig, plan, reason = _select_v2_setup(df_primary, market_data_dict, timeframe, filters, strategy_config, regime, live_price=live_price)
    return sig, reason

def get_signal_with_reason_v2(df_primary, market_data_dict=None, timeframe_mode="single", timeframe="5min", strategy_type="dynamic", filters=None, strategy_config=None, regime=None, live_price=None):
    if df_primary is None or df_primary.empty or len(df_primary) < 60:
        return None, "V2: داده کافی نیست"
    if strategy_type == "dynamic" and get_v2_config(strategy_config).get("v2_enabled", True):
        return strategy_dynamic_v2(df_primary, market_data_dict, timeframe, filters, strategy_config, regime, live_price=live_price)
    return get_signal_with_reason(df_primary, market_data_dict, timeframe_mode, timeframe, strategy_type, filters, strategy_config, regime, live_price=live_price)
