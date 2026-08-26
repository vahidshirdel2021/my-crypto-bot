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
    "early_loss_weakness_exit_enabled": True,
    "early_loss_weakness_exit_min_r": -0.10,
    "early_loss_weakness_exit_score": 45.0,
    "use_edge_proxy_gate": False,   # proxy فقط diagnostic است مگر اینکه صراحتاً فعال شود
    # --- ATR فقط برای سنجش فشار حرکت مخالف در مدیریت هوشمند؛ جایگزین SL/TP نیست ---
    "atr_early_exit_extreme": 0.85,
    "atr_early_exit_extreme_score": 25.0,
    "atr_early_exit_strong": 0.60,
    "atr_early_exit_strong_score": 30.0,
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


def build_trade_plan(df, signal, strategy_config=None, strategy_type="dynamic", strategy_timeframe="5min", grid_levels=None, setup_index=None, live_price=None, market_data_dict=None, filters=None, regime=None, defer_quality_gate=False):
    if strategy_type == "dynamic" and get_v2_config(strategy_config).get("v2_enabled", True):
        sig, plan, reason = _select_v2_setup(df, market_data_dict, strategy_timeframe, filters or FILTER_DEFAULTS, strategy_config, regime, grid_levels, live_price=live_price, defer_quality_gate=defer_quality_gate)
        if sig == signal and plan:
            return plan, reason
    if strategy_type == "htf_liquidity_reversal":
        return build_htf_liquidity_reversal_plan(df, signal, strategy_config, strategy_timeframe)
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
    if score < min_score:
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



def compute_daily_structure_levels(pdh, pdl):
    """Return the five-level daily structure map built from PDH/PDL.

    EQ is the midpoint. The outer reaction levels mirror each half-range:
    lower = PDL - (EQ - PDL), upper = PDH + (PDH - EQ).
    This function is descriptive/structural only; it does not alter entry rules.
    """
    try:
        pdh = float(pdh); pdl = float(pdl)
    except Exception:
        return {}
    if not (np.isfinite(pdh) and np.isfinite(pdl)) or pdh <= pdl:
        return {}
    eq = (pdh + pdl) / 2.0
    lower = pdl - (eq - pdl)
    upper = pdh + (pdh - eq)
    return {
        "pdh": pdh,
        "eq": eq,
        "pdl": pdl,
        "upper_reaction": upper,
        "lower_reaction": lower,
        "upper_half_range": pdh - eq,
        "lower_half_range": eq - pdl,
    }


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


def strategy_liquidity_sweep_5m(df, filters=None, strategy_config=None, live_price=None):
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
        max_dist = atr * max(0.20, float(cfg.get("active_setup_max_distance_atr", 0.80)))
        invalid_dist = atr * max(0.05, float(cfg.get("active_setup_invalidation_atr", 0.25)))
        too_far = (live_for_guard > level + max_dist) if sig == "BUY" else (live_for_guard < level - max_dist)
        invalidated = (live_for_guard < level - invalid_dist) if sig == "BUY" else (live_for_guard > level + invalid_dist)
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
        daily_nearest_dist = min(abs(live_for_guard - pdh), abs(live_for_guard - pdl))
        daily_far = daily_nearest_dist >= guard_atr * daily_activation_atr if guard_atr > 0 else False
    except Exception:
        guard_atr = 0.0
        daily_far = False

    if daily_far:
        adaptive_sig, adaptive_reason, adaptive_atr = _detect_adaptive_liquidity(d, latest_idx, cfg)
        if adaptive_sig:
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
        level = pdl if sig == "BUY" else pdh
        tol = atr * max(0.05, float(cfg.get("retest_tolerance_atr", 0.25)))
        max_dist = atr * max(0.20, float(cfg.get("active_setup_max_distance_atr", 0.80)))
        invalid_dist = atr * max(0.05, float(cfg.get("active_setup_invalidation_atr", 0.25)))

        if bool(cfg.get("active_setup_require_daily_breakout", True)):
            if not _has_confirmed_daily_breakout(d, idx, sig, pdh, pdl, cfg.get("active_setup_breakout_lookback", 8)):
                continue
            if not _confirm_active_structure(d, latest_idx, sig, cfg.get("active_setup_micro_structure_lookback", 3)):
                continue

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


def build_htf_liquidity_reversal_plan(df, signal, strategy_config=None, strategy_timeframe="1hour"):
    if signal not in ("BUY", "SELL"):
        return None, "سیگنال HTF نامعتبر است"
    levels = _compute_period_liquidity_levels(df)
    c = df.iloc[-2]
    atr = _safe_float(c.get("atr"), 0.0)
    if not levels or atr <= 0:
        return None, "سطوح HTF یا ATR نامعتبر است"
    cfg = get_v2_config(strategy_config)
    # Prefer the nearest opposing liquidity target among weekly/monthly levels.
    entry = float(c["close"])
    period_candidates = []
    for period, lv in levels.items():
        target = lv.get("high") if signal == "BUY" else lv.get("low")
        if target is not None and ((target > entry) if signal == "BUY" else (target < entry)):
            period_candidates.append((abs(target-entry), target, period))
    if not period_candidates:
        return None, "هدف ساختاری HTF معتبر پیدا نشد"
    _, target, target_period = min(period_candidates)
    buffer = max(0.35, float(cfg.get("htf_reversal_stop_buffer_atr", 0.45))) * atr
    if signal == "BUY":
        # The stop belongs to the actual reversal candle; the weekly/monthly level is
        # the liquidity reference, not an invitation to place the stop at an old extreme.
        sl = float(c["low"]) - buffer
        risk = entry-sl
    else:
        sl = float(c["high"]) + buffer
        risk = sl-entry
    if risk <= 0 or risk > atr*4.0:
        return None, "ریسک HTF بیش از حد بزرگ است"
    rr = abs(float(target)-entry)/risk
    min_rr = float(cfg.get("htf_reversal_min_rr", 1.20))
    if rr < min_rr:
        return None, f"R:R HTF کافی نیست ({rr:.2f}R < {min_rr:.2f}R)"
    body = _safe_float(c.get("body_ratio"), 0.0)
    vr = _safe_float(c.get("volume_ratio"), 1.0)
    score = min(100.0, 40.0 + min(25.0, body*30.0) + min(20.0, max(0.0,(vr-0.8)*25.0)) + min(15.0,max(0.0,(rr-min_rr)*10.0)))
    min_score = float(cfg.get("min_setup_score",60.0))
    if score < min_score:
        return None, f"امتیاز HTF پایین است ({score:.0f}/100)"
    return {"entry":entry,"sl":float(sl),"tp":float(target),"score":int(round(score)),"quality_label":"خوب" if score>=75 else "قابل قبول","rr":float(rr),"risk_atr":float(risk/atr),"target_period":target_period,"setup_family":"htf_liquidity_reversal","reason":f"HTF Liquidity Reversal | {target_period} | RR={rr:.2f}R"}, f"HTF Liquidity Reversal | شکار نقدینگی {target_period}"


def build_sweep_trade_plan(df, signal, strategy_config=None, grid_levels=None, setup_index=None, live_price=None, anchor_level=None, target_level=None, continuation=False):
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
    if score < min_score:
        return None, f"امتیاز کیفیت پایین است ({score}/100)"

    plan = {
        "entry": entry, "sl": float(sl), "tp": float(tp), "score": score,
        "quality_label": quality_label, "rr": float(rr),
        "pdh": float(pdh), "pdl": float(pdl), "soft_tp": float(soft_tp),
        "daily_structure_levels": compute_daily_structure_levels(pdh, pdl),
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


def get_signal_with_reason(df_primary, market_data_dict=None, timeframe_mode="single", timeframe="5min", strategy_type="trend", filters=None, strategy_config=None, regime=None, live_price=None, defer_quality_gate=False):
    if df_primary is None or df_primary.empty or len(df_primary) < 60:
        return None, "داده کافی نیست"
    st = strategy_type
    if st == "dynamic" and get_v2_config(strategy_config).get("v2_enabled", True):
        sig, reason = strategy_dynamic_v2(df_primary, market_data_dict, timeframe, filters, strategy_config, regime, live_price=live_price, defer_quality_gate=defer_quality_gate)
    elif st == "dynamic":
        if timeframe in ("5min", "15min"):
            sig, reason = strategy_liquidity_sweep_5m(df_primary, filters, strategy_config, live_price=live_price)
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

    # Directional market state is handled as a score tax inside V2, not a hard veto.
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
    "min_setup_score": 60.0,
    "high_vol_min_score": 66.0,
    "high_vol_min_rr": 1.45,
    "range_max_adx": 20.0,
    "range_rsi_buy": 34.0,
    "range_rsi_sell": 66.0,
    "trend_pullback_atr": 0.35,
    "breakout_volume": 1.15,
    "breakout_body": 0.55,
    "sweep_score_bonus": 8.0,
    "regime_confidence_min": 0.55,
    "regime_opposite_direction_penalty": 8.0,
    "equilibrium_bias_bonus": 4.0,
    "equilibrium_bias_penalty": 3.0,
    "htf_reversal_score_bonus": 8.0,
    "htf_reversal_min_sweep_atr": 0.10,
    "htf_reversal_stop_buffer_atr": 0.45,
    "htf_reversal_min_rr": 1.20,
    "active_setup_require_daily_breakout": True,
    "active_setup_breakout_lookback": 8,
    "active_setup_micro_structure_lookback": 3,
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

    # --- 5m-only V2 filter (intentionally not used by 15m/1h/4h) ---
    "five_m_filter_enabled": True,
    "five_m_disable_breakout_retest": True,
    "five_m_range_only_sweep": True,
    "five_m_range_min_volume": 1.50,
    "five_m_range_min_body": 0.70,
    "five_m_htf_min_abs": 0.25,
    "five_m_htf_max_abs": 0.85,
    "five_m_trend_min_htf_abs": 0.15,
    "five_m_trend_max_htf_abs": 0.85,
    "five_m_min_score": 64.0,

    # --- Daily Structure Flip (PDL / EQ / PDH + mirrored outer zones) ---
    "structure_flip_enabled": True,
    "structure_flip_timeframes": ("5min", "15min"),
    "structure_flip_lookback": 14,
    "structure_flip_retest_tolerance_atr": 0.18,
    "structure_flip_min_break_distance_atr": 0.08,
    "structure_flip_min_rr": 1.30,
    "structure_flip_min_score": 62.0,
    "structure_flip_volume_bonus_threshold": 1.05,
    # V8.1: SL is placed behind the confirmed retest swing, with this ATR buffer.
    "structure_flip_sl_buffer_atr": 0.20,
    # --- V8: Structure First hard gate (5m/15m only) ---
    # When enabled, no legacy entry family can open a trade on these TFs unless
    # a confirmed Structure Flip exists. Set False to restore the previous V7
    # behavior without changing the underlying legacy rules.
    "structure_first_enabled": True,
    "structure_first_timeframes": ("5min", "15min"),
    # V8.2: tunable Structure First strictness. strict/balanced/flexible/off.
    "structure_mode": "balanced",
    "structure_first_min_score": 55.0,
    "structure_first_min_score_balanced": 55.0,
    "structure_first_min_score_flexible": 52.0,
    "structure_first_use_htf_as_score": True,
    "structure_first_use_regime_as_score": True,
    # Primary local structure gate: deliberately separate 5m and 15m behavior.
    "5min_swing_left": 2, "5min_swing_right": 2, "5min_break_retest_bars": 5,
    "5min_break_min_atr": 0.10, "5min_retest_tolerance_atr": 0.18, "5min_confirmation_body": 0.22,
    "5min_sl_buffer_atr": 0.12, "5min_target_atr": 1.50, "5min_structure_min_rr": 1.25,
    # V13: 5m-only recency guards for _detect_swing_break_entry. Without these
    # a stale break/retest (many hours old, on a ~200-candle window) could be
    # "confirmed" by an unrelated later candle. Not used by 15m.
    "5min_confirm_gap_bars": 3, "5min_max_setup_age_bars": 48,
    "15min_swing_left": 3, "15min_swing_right": 3, "15min_break_retest_bars": 7,
    "15min_break_min_atr": 0.08, "15min_retest_tolerance_atr": 0.24, "15min_confirmation_body": 0.18,
    "15min_sl_buffer_atr": 0.15, "15min_target_atr": 1.80, "15min_structure_min_rr": 1.20,
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



def _compute_period_liquidity_levels(df):
    """Completed weekly/monthly highs/lows available before the latest closed candle."""
    if df is None or df.empty or "timestamp" not in df.columns:
        return {}
    d = df.copy()
    ts = pd.to_numeric(d["timestamp"], errors="coerce")
    if ts.isna().all():
        return {}
    unit = "ms" if float(ts.median()) > 1e12 else "s"
    dt = pd.to_datetime(ts, unit=unit, utc=True)
    d["_dt"] = dt
    period_dt = dt.dt.tz_localize(None)
    d["_week"] = period_dt.dt.to_period("W-SUN")
    d["_month"] = period_dt.dt.to_period("M")
    out = {}
    for key, col in (("weekly", "_week"), ("monthly", "_month")):
        g = d.groupby(col).agg(high=("high", "max"), low=("low", "min"))
        if len(g) < 2:
            continue
        latest_period = d.iloc[-2][col]
        try:
            pos = list(g.index).index(latest_period)
        except ValueError:
            continue
        if pos <= 0:
            continue
        prev = g.iloc[pos - 1]
        out[key] = {"high": float(prev["high"]), "low": float(prev["low"])}
    return out


def strategy_htf_liquidity_reversal(df, timeframe="1hour", filters=None, strategy_config=None, market_data_dict=None):
    """Dedicated 1h/4h reversal strategy around completed weekly/monthly liquidity."""
    if timeframe not in ("1hour", "4hour") or df is None or len(df) < 80:
        return None, "HTF Liquidity Reversal فقط برای 1h/4h و با داده کافی فعال است"
    cfg = get_v2_config(strategy_config)
    # Weekly/monthly liquidity must be derived from daily candles, not the execution TF.
    level_source = (market_data_dict or {}).get("1d") if isinstance(market_data_dict, dict) else None
    levels = _compute_period_liquidity_levels(level_source if level_source is not None and not level_source.empty else df)
    if not levels:
        return None, "سطوح هفتگی/ماهانه کافی نیستند"
    c = df.iloc[-2]
    atr = _safe_float(c.get("atr"), 0.0)
    if atr <= 0:
        return None, "ATR نامعتبر است"
    min_sweep = atr * float(cfg.get("htf_reversal_min_sweep_atr", 0.10))
    body = _safe_float(c.get("body_ratio"), 0.0)
    vr = _safe_float(c.get("volume_ratio"), 0.0)
    min_body = float(cfg.get("min_body_ratio", 0.40))
    min_vol = float(cfg.get("min_volume_ratio", 1.0))
    best = None
    for period in ("monthly", "weekly"):
        lv = levels.get(period, {})
        hi, lo = lv.get("high"), lv.get("low")
        if hi is not None and float(c["high"]) >= hi + min_sweep and float(c["close"]) < hi and float(c["close"]) < float(c["open"]) and body >= min_body and vr >= min_vol:
            depth = (float(c["high"]) - hi) / atr
            cand = (depth, "SELL", period, hi)
            if best is None or cand[0] > best[0]: best = cand
        if lo is not None and float(c["low"]) <= lo - min_sweep and float(c["close"]) > lo and float(c["close"]) > float(c["open"]) and body >= min_body and vr >= min_vol:
            depth = (lo - float(c["low"])) / atr
            cand = (depth, "BUY", period, lo)
            if best is None or cand[0] > best[0]: best = cand
    if best is None:
        return None, "شکار نقدینگی هفتگی/ماهانه تأیید نشد"
    _, sig, period, level = best
    return sig, f"HTF_LIQUIDITY_REVERSAL|{period.upper()}={level:.10g}|شکار نقدینگی {period} + ریکلیم"


def strategy_trend_pullback(df, timeframe="5min", filters=None, strategy_config=None):
    """Trend pullback: EMA20 touch is allowed on any of the previous 3 candles."""
    if df is None or len(df) < 10:
        return None, "داده کافی برای Trend Pullback نیست"
    cfg = get_v2_config(strategy_config)
    curr = df.iloc[-2]
    atr = _safe_float(curr.get("atr"), 0.0)
    adx = _safe_float(curr.get("adx"), 0.0)
    if atr <= 0 or adx < float(cfg.get("min_adx", 20.0)):
        return None, "قدرت روند برای Pullback کافی نیست"
    ema20 = _safe_float(curr.get("ema20"), 0.0)
    bull = float(curr["close"]) > ema20 and float(curr["ema20"]) > float(curr["ema50"]) and _safe_float(curr.get("plus_di")) > _safe_float(curr.get("minus_di"))
    bear = float(curr["close"]) < ema20 and float(curr["ema20"]) < float(curr["ema50"]) and _safe_float(curr.get("minus_di")) > _safe_float(curr.get("plus_di"))
    window = df.iloc[-5:-2]
    tol = atr * float(cfg.get("trend_pullback_atr", 0.35))
    if bull:
        touched = any(float(r["low"]) <= float(r["ema20"]) + tol and float(r["high"]) >= float(r["ema20"]) - tol for _, r in window.iterrows())
        if touched and float(curr["close"]) > float(curr["open"]):
            return "BUY", "trend_pullback | برخورد EMA20 در 3 کندل قبل + تأیید صعودی"
    if bear:
        touched = any(float(r["high"]) >= float(r["ema20"]) - tol and float(r["low"]) <= float(r["ema20"]) + tol for _, r in window.iterrows())
        if touched and float(curr["close"]) < float(curr["open"]):
            return "SELL", "trend_pullback | برخورد EMA20 در 3 کندل قبل + تأیید نزولی"
    return None, "Trend Pullback تأیید نشد"


def strategy_breakout_retest(df, filters=None, strategy_config=None):
    """Breakout followed by a fresh retest of the breakout channel level."""
    if df is None or len(df) < 15:
        return None, "داده کافی برای Breakout Retest نیست"
    cfg = get_v2_config(strategy_config)
    curr = df.iloc[-2]
    atr = _safe_float(curr.get("atr"), 0.0)
    if atr <= 0:
        return None, "ATR نامعتبر است"
    tol = atr * float(cfg.get("adaptive_retest_tolerance_atr", 0.22))
    for back in range(3, 8):
        if len(df) <= back + 5: continue
        br = df.iloc[-back]
        level_up = _safe_float(br.get("channel_high"), 0.0)
        level_dn = _safe_float(br.get("channel_low"), 0.0)
        if level_up > 0 and float(br["close"]) > level_up and float(curr["low"]) <= level_up + tol and float(curr["close"]) > level_up and float(curr["close"]) > float(curr["open"]):
            return "BUY", f"breakout_retest | شکست کانال + ریتست صعودی ({level_up:.6g})"
        if level_dn > 0 and float(br["close"]) < level_dn and float(curr["high"]) >= level_dn - tol and float(curr["close"]) < level_dn and float(curr["close"]) < float(curr["open"]):
            return "SELL", f"breakout_retest | شکست کانال + ریتست نزولی ({level_dn:.6g})"
    return None, "Breakout Retest تأیید نشد"


def _equilibrium_bias(df, signal):
    """PDH/PDL midpoint: reward discount buys / premium sells, penalize the inverse."""
    d, pdh, pdl = _compute_prev_day_levels(df)
    if pdh is None or pdl is None:
        return 0.0, None
    price = float(d.iloc[-2]["close"])
    mid = (pdh + pdl) / 2.0
    if signal == "BUY":
        return (1.0 if price < mid else -1.0), mid
    return (1.0 if price > mid else -1.0), mid


def _has_confirmed_daily_breakout(d, before_idx, signal, pdh, pdl, lookback=8):
    """Require a real close beyond the prior-day level before an active recovery."""
    if before_idx <= 1:
        return False
    start = max(1, before_idx - int(lookback))
    w = d.iloc[start:before_idx]
    if signal == "BUY":
        return bool((pd.to_numeric(w["close"], errors="coerce") > float(pdh)).any())
    return bool((pd.to_numeric(w["close"], errors="coerce") < float(pdl)).any())


def _confirm_active_structure(d, before_idx, signal, lookback=3):
    """Micro structure confirmation: HH/HL for buys, LH/LL for sells."""
    n = max(2, int(lookback))
    if before_idx < n + 1:
        return False
    w = d.iloc[before_idx-n:before_idx]
    highs = pd.to_numeric(w["high"], errors="coerce").to_numpy(dtype=float)
    lows = pd.to_numeric(w["low"], errors="coerce").to_numpy(dtype=float)
    if len(highs) < 2:
        return False
    if signal == "BUY":
        return bool(highs[-1] >= highs[-2] and lows[-1] >= lows[-2])
    return bool(highs[-1] <= highs[-2] and lows[-1] <= lows[-2])

def _detect_structure_flip(df, cfg):
    """Detect a confirmed break/retest of one of five daily structure levels.

    Levels are: PDL-Range, PDL, EQ, PDH, PDH+Range.  A valid flip requires a
    completed candle that breaks/ closes through a level, followed later by a
    retest from the new side and a confirming rejection candle.  Only candles
    before the latest closed candle are used, so the detector does not look ahead.

    Returns a dict suitable for an entry candidate or None.
    """
    if df is None or len(df) < 70:
        return None
    d, pdh, pdl = _compute_prev_day_levels(df)
    if pdh is None or pdl is None:
        return None
    levels = compute_daily_structure_levels(pdh, pdl)
    if not levels:
        return None

    ordered = [
        ("PDL_EXT", levels["lower_reaction"]),
        ("PDL", levels["pdl"]),
        ("EQ", levels["eq"]),
        ("PDH", levels["pdh"]),
        ("PDH_EXT", levels["upper_reaction"]),
    ]
    # Work only with fully closed candles. The last row is normally the live candle.
    idx = len(d) - 2
    if idx < 10:
        return None
    atr = _safe_float(d.iloc[idx].get("atr"), 0.0)
    if atr <= 0:
        return None
    # V8.2: keep Structure mandatory, but allow a controlled amount of
    # flexibility so 5m/15m do not become unnecessarily signal-starved.
    mode = str(cfg.get("structure_mode", "strict")).lower()
    base_tol = float(cfg.get("structure_flip_retest_tolerance_atr", 0.18))
    base_break = float(cfg.get("structure_flip_min_break_distance_atr", 0.08))
    base_lookback = int(cfg.get("structure_flip_lookback", 14))
    if mode == "balanced":
        tol_mult, break_mult, lookback_add = 1.25, 0.75, 4
    elif mode == "flexible":
        tol_mult, break_mult, lookback_add = 1.45, 0.60, 8
    else:
        tol_mult, break_mult, lookback_add = 1.0, 1.0, 0
    tol = atr * base_tol * tol_mult
    min_break = atr * base_break * break_mult
    lookback = max(6, base_lookback + lookback_add)
    start = max(2, idx - lookback)

    def _c(i, col):
        return _safe_float(d.iloc[i].get(col), 0.0)

    candidates = []
    for pos, (name, level) in enumerate(ordered):
        level = float(level)
        # Search for the most recent clean break before the retest.
        for br in range(idx - 2, start - 1, -1):
            prev_close = _c(br - 1, "close")
            br_close = _c(br, "close")
            if not prev_close or not br_close:
                continue
            short_break = prev_close >= level and br_close < level - min_break
            long_break = prev_close <= level and br_close > level + min_break
            if not (short_break or long_break):
                continue
            # Need at least one completed candle after the break before the retest.
            if idx - br < 1:
                continue
            # The candle immediately before the confirmation candle must form the
            # swing/retest at the flipped level; the latest closed candle confirms it.
            swing_i = idx - 1
            if swing_i <= br:
                continue
            so = _c(swing_i, "open"); sh = _c(swing_i, "high"); sl = _c(swing_i, "low"); sc = _c(swing_i, "close")
            o = _c(idx, "open"); h = _c(idx, "high"); l = _c(idx, "low"); c = _c(idx, "close")
            vr = _safe_float(d.iloc[idx].get("volume_ratio"), 1.0)
            body = _safe_float(d.iloc[idx].get("body_ratio"), 0.0)
            swing_body = _safe_float(d.iloc[swing_i].get("body_ratio"), 0.0)
            if short_break:
                # Confirm a real local swing high on the retest candle: its high must
                # exceed the two candles to its left and the confirmation candle.
                swing_is_pivot = (sh >= _c(swing_i - 1, "high") and sh >= _c(swing_i - 2, "high") and sh >= h)
                swing_retest = sh >= level - tol and sc < level and swing_is_pivot
                confirmation = c < o and c < level and c < sc
                if not (swing_retest and confirmation):
                    continue
                signal = "SELL"
                next_target = ordered[pos - 1][1] if pos > 0 else None
                reaction = "مقاومت"
                distance = level - (next_target if next_target is not None else c)
            else:
                # Confirm a real local swing low on the retest candle: its low must
                # be below the two candles to its left and the confirmation candle.
                swing_is_pivot = (sl <= _c(swing_i - 1, "low") and sl <= _c(swing_i - 2, "low") and sl <= l)
                swing_retest = sl <= level + tol and sc > level and swing_is_pivot
                confirmation = c > o and c > level and c > sc
                if not (swing_retest and confirmation):
                    continue
                signal = "BUY"
                next_target = ordered[pos + 1][1] if pos < len(ordered) - 1 else None
                reaction = "حمایت"
                distance = (next_target if next_target is not None else c) - level
            if next_target is None or distance <= 0:
                continue
            # V8.2 confirmation strictness. Structure remains mandatory in every
            # non-off mode, but balanced/flexible modes accept a cleaner rejection
            # with less candle-body strength than strict mode.
            if mode == "balanced":
                min_body, min_swing_body = 0.28, 0.18
            elif mode == "flexible":
                min_body, min_swing_body = 0.22, 0.12
            else:
                min_body, min_swing_body = 0.35, 0.25
            if body < min_body or swing_body < min_swing_body:
                continue
            score = 55.0
            score += min(15.0, body * 15.0)
            score += min(10.0, max(0.0, (vr - 0.85) * 18.0))
            # More recent break/retest gets a small priority bonus.
            age = idx - br
            score += max(0.0, 8.0 - age * 0.8)
            rr_hint = distance / max(atr * 1.25, 1e-9)
            score += min(12.0, max(0.0, (rr_hint - 1.0) * 6.0))
            candidates.append({
                "signal": signal,
                "level_name": name,
                "level": level,
                "target_level": float(next_target),
                "reaction": reaction,
                "break_index": br,
                # The retest candle is the confirmed swing used to invalidate the
                # setup. Keep its actual wick extreme so the SL can sit behind the
                # swing instead of being anchored to the flipped level.
                "swing_index": swing_i,
                "swing_level": float(sh if signal == "SELL" else sl),
                "score": float(min(100.0, score)),
                "volume_ratio": vr,
                "body_ratio": body,
                "atr": atr,
            })
            break

    if not candidates:
        return None
    candidates.sort(key=lambda x: (x["score"], -x["break_index"]), reverse=True)
    return candidates[0]


def _build_structure_flip_plan(df, flip, cfg, strict_mode=False):
    """Build a risk plan for a confirmed daily structure flip."""
    if not flip or df is None or len(df) < 30:
        return None, "Structure Flip داده کافی ندارد"
    idx = len(df) - 2
    c = df.iloc[idx]
    entry = _safe_float(c.get("close"), 0.0)
    atr = _safe_float(c.get("atr"), 0.0)
    if entry <= 0 or atr <= 0:
        return None, "Structure Flip قیمت/ATR نامعتبر است"
    level = float(flip["level"])
    target = float(flip["target_level"])
    signal = flip["signal"]
    # V8.1: the hard SL is structural. It must sit behind the exact swing that
    # formed during the retest/confirmation, with only a small ATR buffer.
    # The flipped level is NOT used as the primary SL anchor.
    swing_level = _safe_float(flip.get("swing_level"), 0.0)
    swing_index = int(flip.get("swing_index", -1))
    if swing_level <= 0 or swing_index < 0:
        return None, "Structure Flip سوینگ تأییدشده برای SL موجود نیست"
    buffer_atr = float(cfg.get("structure_flip_sl_buffer_atr", 0.20))
    buffer_atr = max(0.05, min(0.60, buffer_atr))
    if signal == "SELL":
        sl = swing_level + atr * buffer_atr
        risk = sl - entry
        reward = entry - target
    else:
        sl = swing_level - atr * buffer_atr
        risk = entry - sl
        reward = target - entry
    if risk <= 0 or reward <= 0:
        return None, "Structure Flip فاصله ریسک/هدف نامعتبر است"
    min_rr = float(cfg.get("structure_flip_min_rr", 1.30))
    rr = reward / risk
    if rr < min_rr:
        return None, f"Structure Flip R:R ناکافی ({rr:.2f}R)"
    # Avoid pathological stops in high volatility.
    if risk > atr * 2.50:
        return None, "Structure Flip استاپ بیش از حد دور است"
    score = float(flip["score"])
    min_score_key = "structure_first_min_score" if strict_mode else "structure_flip_min_score"
    min_score = float(cfg.get(min_score_key, 55.0 if strict_mode else 62.0))
    if score < min_score:
        return None, f"Structure Flip کیفیت پایین است ({score:.0f}/100)"
    quality = "عالی" if score >= 85 else "خوب" if score >= 75 else "قابل قبول"
    plan = {
        "entry": entry,
        "sl": float(sl),
        "tp": float(target),
        "score": int(round(score)),
        "quality_label": quality,
        "rr": float(rr),
        "risk_atr": float(risk / atr),
        "target_r": float(rr),
        "atr": atr,
        "atr_ratio": 1.0,
        "volume_ratio": float(flip.get("volume_ratio", 1.0)),
        "body_ratio": float(flip.get("body_ratio", 0.0)),
        "structure_flip": True,
        "structure_flip_level": level,
        "structure_flip_level_name": flip["level_name"],
        "structure_flip_target": target,
        "structure_flip_swing_level": float(swing_level),
        "structure_flip_swing_index": int(flip.get("swing_index", -1)),
        "structure_flip_sl_buffer_atr": float(buffer_atr),
        "sl_basis": "confirmed_retest_swing",
        "daily_structure_levels": compute_daily_structure_levels(*_compute_prev_day_levels(df)[1:]),
        "reason": (
            f"Structure Flip | {flip['level_name']} به {flip['reaction']} تبدیل شد | "
            f"Break→Retest→Confirmation | Target={target:.6g} | R:R={rr:.2f}R"
        ),
    }
    return plan, plan["reason"]


def _five_min_candidate_allowed(df_primary, family, reason, regime_name, htf, score, cfg):
    """5m-only entry gate. Returns (allowed, rejection_reason).

    This gate is deliberately isolated from other timeframes so 15m/1h/4h
    behavior remains unchanged. It uses only evidence already available to the
    V2 selector; it does not invent a probability from EdgeProxy.
    """
    if not bool(cfg.get("five_m_filter_enabled", True)):
        return True, ""

    # Breakout-retest was the weakest family in the audit sample. Disable it
    # only on 5m; other timeframes keep their existing behavior.
    if family == "breakout_retest" and bool(cfg.get("five_m_disable_breakout_retest", True)):
        return False, "5m Filter: breakout_retest موقتاً غیرفعال است"

    # RANGE is treated as a liquidity-reversion environment on 5m.
    if regime_name == "RANGE" and bool(cfg.get("five_m_range_only_sweep", True)) and family != "liquidity_sweep":
        return False, "5m Filter: در RANGE فقط liquidity_sweep مجاز است"

    # Directional HTF context: require a meaningful, not extreme, alignment.
    htf = float(htf or 0.0)
    if abs(htf) < float(cfg.get("five_m_trend_min_htf_abs", 0.15)):
        return False, f"5m Filter: HTF ضعیف ({htf:.2f})"
    if abs(htf) > float(cfg.get("five_m_trend_max_htf_abs", 0.85)):
        return False, f"5m Filter: HTF بیش از حد شدید ({htf:.2f})"

    # Range sweep needs stronger confirmation and a real structural anchor.
    if regime_name == "RANGE" and family == "liquidity_sweep":
        text = str(reason or "").upper()
        valid_anchor = any(k in text for k in (
            "PDH", "PDL", "LONDON", "NEW_YORK", "ASIA", "OPENING", "SWING"
        ))
        if not valid_anchor:
            return False, "5m Filter: سطح نقدینگی معتبر برای RANGE پیدا نشد"
        try:
            c = df_primary.iloc[-2]
            vr = float(c.get("volume_ratio", 0) or 0)
            body = float(c.get("body_ratio", 0) or 0)
        except Exception:
            return False, "5m Filter: داده کندل تأیید نامعتبر است"
        if vr < float(cfg.get("five_m_range_min_volume", 1.50)):
            return False, f"5m Filter: حجم RANGE کم است ({vr:.2f}x)"
        if body < float(cfg.get("five_m_range_min_body", 0.70)):
            return False, f"5m Filter: بدنه کندل RANGE ضعیف است ({body:.2f})"
        if not (float(cfg.get("five_m_htf_min_abs", 0.25)) <= abs(htf) <= float(cfg.get("five_m_htf_max_abs", 0.85))):
            return False, f"5m Filter: HTF RANGE خارج از محدوده ({htf:.2f})"

    # Trend pullback keeps the family alive, but demands a meaningful score.
    if family == "trend_pullback" and float(score) < float(cfg.get("five_m_min_score", 64.0)):
        return False, f"5m Filter: امتیاز trend_pullback پایین است ({score:.0f})"

    return True, ""




def _detect_swing_break_entry(df, cfg, timeframe="5min"):
    """Primary Swing -> Break -> Retest -> Confirmation detector for 5m/15m.
    Uses confirmed pivots only; a wick through a level is not a break.

    5m-only fix: the "confirmation" candle was always the current closed
    candle (idx), with no bound on how long ago the break/retest happened.
    On a ~200-candle 5m window that let a break/retest from many hours
    earlier be "confirmed" by an unrelated, much later candle just because
    it closed in the right direction — anchoring SL to a stale, no-longer-
    relevant swing instead of the structure actually forming right now.
    `5min_confirm_gap_bars` bounds how far the confirmation may sit from the
    retest, and `5min_max_setup_age_bars` bounds how old the pivot itself may
    be. Both are gated behind `is_5m` so 15m keeps its exact prior behavior.
    """
    if df is None or len(df) < 40:
        return None
    tf = "15min" if timeframe == "15min" else "5min"
    is_5m = (tf == "5min")
    left = int(cfg.get(f"{tf}_swing_left", 2))
    right = int(cfg.get(f"{tf}_swing_right", 2))
    max_retest = int(cfg.get(f"{tf}_break_retest_bars", 5))
    break_atr = float(cfg.get(f"{tf}_break_min_atr", 0.10))
    tol_atr = float(cfg.get(f"{tf}_retest_tolerance_atr", 0.18))
    min_body = float(cfg.get(f"{tf}_confirmation_body", 0.22))
    max_confirm_gap = int(cfg.get("5min_confirm_gap_bars", 3))
    max_setup_age = int(cfg.get("5min_max_setup_age_bars", 48))
    idx = len(df) - 2
    atr = _safe_float(df.iloc[idx].get("atr"), 0.0)
    if atr <= 0: return None
    highs=df["high"].astype(float).to_numpy(); lows=df["low"].astype(float).to_numpy()
    closes=df["close"].astype(float).to_numpy(); opens=df["open"].astype(float).to_numpy()
    piv_h=[]; piv_l=[]
    for i in range(left, idx-right+1):
        if highs[i] > max(highs[i-left:i]) and highs[i] >= max(highs[i+1:i+1+right]): piv_h.append(i)
        if lows[i] < min(lows[i-left:i]) and lows[i] <= min(lows[i+1:i+1+right]): piv_l.append(i)
    candidates=[]
    for pi in piv_h[-8:]:
        if is_5m and (idx - pi) > max_setup_age: continue
        level=highs[pi]
        for br in range(pi+1, idx):
            if closes[br] <= level + atr*break_atr: continue
            # break must close beyond the pivot, not just wick through it
            for r in range(br+1, min(idx, br+1+max_retest)):
                if is_5m and (idx - r) > max_confirm_gap: continue
                if lows[r] > level + atr*tol_atr: continue
                if closes[r] < level: continue
                conf_o, conf_c = opens[idx], closes[idx]
                body=abs(conf_c-conf_o)/max(float(df.iloc[idx]["high"]-df.iloc[idx]["low"]),1e-12)
                if conf_c > conf_o and conf_c > closes[r] and body >= min_body:
                    sl=lows[r]
                    candidates.append({"signal":"BUY","break_index":br,"swing_index":r,"break_level":level,"swing_level":sl,"confirmation_index":idx,"atr":atr,"body_ratio":body,"reason":f"Swing→Break→Retest→Confirmation | {tf}"})
                    break
            if candidates: break
    for pi in piv_l[-8:]:
        if is_5m and (idx - pi) > max_setup_age: continue
        level=lows[pi]
        for br in range(pi+1, idx):
            if closes[br] >= level - atr*break_atr: continue
            for r in range(br+1, min(idx, br+1+max_retest)):
                if is_5m and (idx - r) > max_confirm_gap: continue
                if highs[r] < level - atr*tol_atr: continue
                if closes[r] > level: continue
                conf_o, conf_c = opens[idx], closes[idx]
                body=abs(conf_c-conf_o)/max(float(df.iloc[idx]["high"]-df.iloc[idx]["low"]),1e-12)
                if conf_c < conf_o and conf_c < closes[r] and body >= min_body:
                    sl=highs[r]
                    candidates.append({"signal":"SELL","break_index":br,"swing_index":r,"break_level":level,"swing_level":sl,"confirmation_index":idx,"atr":atr,"body_ratio":body,"reason":f"Swing→Break→Retest→Confirmation | {tf}"})
                    break
            if candidates: break
    if not candidates: return None
    candidates.sort(key=lambda x: x["break_index"], reverse=True)
    return candidates[0]

def _build_swing_break_plan(df, setup, cfg, timeframe):
    if not setup: return None, "Swing/Break معتبر وجود ندارد"
    idx=len(df)-2; entry=_safe_float(df.iloc[idx].get("close"),0); atr=_safe_float(df.iloc[idx].get("atr"),0)
    swing=_safe_float(setup.get("swing_level"),0); level=_safe_float(setup.get("break_level"),0)
    if entry<=0 or atr<=0 or swing<=0: return None, "Swing معتبر برای SL وجود ندارد"
    buf=float(cfg.get(f"{timeframe}_sl_buffer_atr",0.12))
    if setup["signal"]=="BUY":
        sl=swing-atr*buf
        if sl>=entry: return None,"SL پشت Swing قرار نگرفت"
        tp=level + max(atr*float(cfg.get(f"{timeframe}_target_atr",1.5)), atr)
    else:
        sl=swing+atr*buf
        if sl<=entry: return None,"SL پشت Swing قرار نگرفت"
        tp=level - max(atr*float(cfg.get(f"{timeframe}_target_atr",1.5)), atr)
    risk=abs(entry-sl); reward=abs(tp-entry); rr=reward/max(risk,1e-12)
    minrr=float(cfg.get(f"{timeframe}_structure_min_rr",1.25))
    if rr<minrr: return None,f"R:R ناکافی ({rr:.2f}R)"
    return {"entry":entry,"sl":float(sl),"tp":float(tp),"rr":float(rr),"score":70,"quality_label":"ساختاری","atr":atr,"swing_level":swing,"swing_index":int(setup["swing_index"]),"break_level":level,"break_index":int(setup["break_index"]),"confirmation_index":int(setup["confirmation_index"]),"sl_basis":"confirmed_retest_swing","setup_family":"swing_break","reason":setup["reason"]}, setup["reason"]


def _select_v2_setup(df_primary, market_data_dict=None, timeframe="5min", filters=None, strategy_config=None, regime=None, grid_levels=None, live_price=None, defer_quality_gate=False):
    cfg = get_v2_config(strategy_config)
    regime_info = detect_market_regime(df_primary, cfg)
    rname = regime_info["name"]
    rconf = regime_info["confidence"]
    trend_state = regime_info.get("trend_state", "NEUTRAL")
    vol_state = regime_info.get("volatility_state", "NORMAL")
    candidates = []

    # Regime confidence is diagnostic in the evolved engine; it no longer hard-blocks setup discovery.

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
                anchor_level=anchor_level, target_level=target_level
            )
        else:
            plan, plan_reason = build_trade_plan(
                df_primary, sig, cfg, family, strategy_timeframe=plan_tf,
                grid_levels=grid_levels, setup_index=active_setup_index, live_price=live_price
            )
        if not plan:
            return
        htf, htf_details = _v2_htf_bias(market_data_dict, sig == "BUY")
        score = float(plan.get("score", 0)) + float(bonus)
        score += max(-8.0, min(8.0, htf * 8.0))
        eq_bias, eq_mid = _equilibrium_bias(df_primary, sig)
        if eq_bias > 0:
            score += float(cfg.get("equilibrium_bias_bonus", 4.0))
        elif eq_bias < 0:
            score -= float(cfg.get("equilibrium_bias_penalty", 3.0))
        # Opposite market direction is a score tax, not a hard veto.
        if regime == "BULLISH" and sig == "SELL":
            score -= float(cfg.get("regime_opposite_direction_penalty", 8.0))
        elif regime == "BEARISH" and sig == "BUY":
            score -= float(cfg.get("regime_opposite_direction_penalty", 8.0))
        score = max(0.0, min(100.0, score))
        if timeframe == "5min":
            allowed_5m, reject_5m = _five_min_candidate_allowed(
                df_primary, family, reason, rname, htf, score, cfg
            )
            if not allowed_5m:
                return
        rr = float(plan.get("rr", 0))
        ev, pwin = _v2_edge_proxy(score, rr, rname, regime_info["atr_ratio"])
        # Strong trend is allowed to remain directional even in HIGH/LOW volatility,
        # but high volatility requires stricter score/RR. Mean reversion is never selected
        # merely because volatility is high.
        if vol_state == "HIGH":
            min_score = max(float(cfg["high_vol_min_score"]), 60.0)
            min_rr = max(float(cfg["high_vol_min_rr"]), 1.30)
        else:
            min_score = max(float(cfg["min_setup_score"]), 60.0)
            min_rr = max(float(cfg.get("min_rr", 1.3)), 1.30)
        if (not defer_quality_gate) and (score < min_score or rr < min_rr):
            return
        if bool(cfg.get("use_edge_proxy_gate", False)) and ev < float(cfg["min_edge_proxy"]):
            return

        if timeframe == "5min" and not defer_quality_gate and family != "structure_flip":
            # V3 research gate applies to the legacy 5m families. Structure Flip is
            # an independent structure-based entry family and has its own quality/RR gate.
            htf_min = float(cfg.get("five_m_htf_min", -0.70))
            htf_max = float(cfg.get("five_m_htf_max", -0.35))
            edge_min = float(cfg.get("five_m_edge_min", 0.20))
            if rname not in {"TREND_BEAR", "MIXED"}:
                return
            if sig != "SELL":
                return
            if not (htf_min <= htf <= htf_max):
                return
            if ev < edge_min:
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
            "equilibrium_bias": float(eq_bias),
            "equilibrium_mid": float(eq_mid) if eq_mid is not None else None,
            "edge_proxy": round(ev, 4),
            "model_win_proxy": round(pwin, 4),
            "setup_family": family,
        })
        version_label = "V3" if timeframe == "5min" else "V2"
        candidates.append((score * max(rr, 0.01), plan, sig, f"{version_label} {rname}/{vol_state} | {family} | {reason} | HTF={htf:.2f} | EdgeProxy={ev:.2f}"))

    if timeframe in ("5min", "15min"):
        # V8 Structure First: on 5m/15m, Structure Flip is the hard entry gate.
        # Legacy families remain available only when this gate is explicitly disabled.
        structure_mode = str(cfg.get("structure_mode", "strict")).lower()
        structure_first = (
            bool(cfg.get("structure_first_enabled", True))
            and structure_mode != "off"
            and timeframe in tuple(cfg.get("structure_first_timeframes", ("5min", "15min")))
        )
        flip_enabled = bool(cfg.get("structure_flip_enabled", True))
        flip_tfs = tuple(cfg.get("structure_flip_timeframes", ("5min", "15min")))

        if structure_first:
            # No legacy candidate is even constructed. This is intentional: HTF,
            # volume, regime, EdgeProxy, etc. are confirmation/scoring layers only.
            swing_setup = _detect_swing_break_entry(df_primary, cfg, timeframe)
            if swing_setup:
                swing_plan, swing_reason = _build_swing_break_plan(df_primary, swing_setup, cfg, timeframe)
                if swing_plan:
                    htf_sb, htf_sb_details = _v2_htf_bias(market_data_dict, swing_setup["signal"] == "BUY")
                    sb_score = float(swing_plan.get("score",70)) + max(-5.0, min(5.0, htf_sb*5.0))
                    sb_score = max(0.0,min(100.0,sb_score))
                    fp=dict(swing_plan); fp.update({"score":int(round(sb_score)),"regime":rname,"regime_confidence":rconf,"trend_state":trend_state,"volatility_state":vol_state,"htf_bias":float(htf_sb),"htf_details":htf_sb_details,"setup_family":"swing_break"})
                    candidates.append((sb_score*max(float(fp.get("rr",0.01)),0.01),fp,swing_setup["signal"],f"V9 Swing First {rname}/{vol_state} | {swing_reason} | HTF={htf_sb:.2f}"))
            # Daily Structure Flip is retained only as a structural variant; it no longer bypasses local Swing→Break validation.
            # 5m-only: Structure Flip and Swing->Break are independent signals, so on 5m Flip is no
            # longer required to wait on a swing_setup match (15m keeps its original coupled behavior).
            flip_gate = swing_setup if timeframe != "5min" else True
            flip = _detect_structure_flip(df_primary, cfg) if (flip_enabled and timeframe in flip_tfs and flip_gate) else None
            if flip:
                flip_plan, flip_reason = _build_structure_flip_plan(df_primary, flip, cfg, strict_mode=True)
                if flip_plan:
                    htf_flip, htf_flip_details = _v2_htf_bias(market_data_dict, flip["signal"] == "BUY")
                    # Structure is the primary score; contextual signals can only
                    # add/subtract points and cannot replace the structural setup.
                    flip_score = float(flip_plan.get("score", 0))
                    if bool(cfg.get("structure_first_use_htf_as_score", True)):
                        flip_score += max(-6.0, min(6.0, htf_flip * 6.0))
                    if bool(cfg.get("structure_first_use_regime_as_score", True)):
                        if (rname == "TREND_BEAR" and flip["signal"] == "SELL") or (rname == "TREND_BULL" and flip["signal"] == "BUY"):
                            flip_score += 4.0
                        elif (rname == "TREND_BEAR" and flip["signal"] == "BUY") or (rname == "TREND_BULL" and flip["signal"] == "SELL"):
                            flip_score -= 4.0
                    flip_score = max(0.0, min(100.0, flip_score))
                    rr_flip = float(flip_plan.get("rr", 0.0))
                    # Only the structural minimum score and structural R:R are hard
                    # gates. Other model signals are scoring/diagnostic only.
                    if structure_mode == "flexible":
                        min_struct_score = float(cfg.get("structure_first_min_score_flexible", 52.0))
                    elif structure_mode == "balanced":
                        min_struct_score = float(cfg.get("structure_first_min_score_balanced", 55.0))
                    else:
                        min_struct_score = float(cfg.get("structure_first_min_score", 55.0))
                    if flip_score >= min_struct_score and rr_flip >= float(cfg.get("structure_flip_min_rr", 1.30)):
                        ev_flip, pwin_flip = _v2_edge_proxy(flip_score, rr_flip, rname, regime_info["atr_ratio"])
                        fp = dict(flip_plan)
                        fp.update({
                            "score": int(round(flip_score)),
                            "regime": rname,
                            "regime_confidence": rconf,
                            "trend_state": trend_state,
                            "volatility_state": vol_state,
                            "htf_bias": float(htf_flip),
                            "htf_details": htf_flip_details,
                            "equilibrium_bias": 0.0,
                            "equilibrium_mid": fp.get("daily_structure_levels", {}).get("eq"),
                            "edge_proxy": round(ev_flip, 4),
                            "model_win_proxy": round(pwin_flip, 4),
                            "setup_family": "structure_flip",
                        })
                        flip_reason_full = f"V8 Structure First {rname}/{vol_state} | {flip_reason} | HTF={htf_flip:.2f} | EdgeProxy={ev_flip:.2f}"
                        candidates.append((flip_score * max(rr_flip, 0.01), fp, flip["signal"], flip_reason_full))
            # If no valid Structure Flip exists, candidates stays empty => NO TRADE.
        else:
            # V7 fallback: preserve the previous competing-family selector exactly.
            sig, reason = strategy_liquidity_sweep_5m(df_primary, filters, cfg, live_price=live_price)
            family = "trend" if "ADAPTIVE_CONTINUATION" in (reason or "") else "liquidity_sweep"
            add_candidate(sig, reason, family, float(cfg["sweep_score_bonus"]) if family == "liquidity_sweep" else 3.0)
            sig, reason = strategy_trend_pullback(df_primary, timeframe, filters, cfg)
            add_candidate(sig, reason, "trend_pullback", 4.0)
            sig, reason = strategy_breakout_retest(df_primary, filters, cfg)
            add_candidate(sig, reason, "breakout_retest", 6.0)

            if flip_enabled and timeframe in flip_tfs:
                flip = _detect_structure_flip(df_primary, cfg)
                if flip:
                    flip_plan, flip_reason = _build_structure_flip_plan(df_primary, flip, cfg)
                    if flip_plan:
                        htf_flip, htf_flip_details = _v2_htf_bias(market_data_dict, flip["signal"] == "BUY")
                        flip_score = float(flip_plan.get("score", 0)) + max(-6.0, min(6.0, htf_flip * 6.0))
                        flip_score = max(0.0, min(100.0, flip_score))
                        rr_flip = float(flip_plan.get("rr", 0.0))
                        ev_flip, pwin_flip = _v2_edge_proxy(flip_score, rr_flip, rname, regime_info["atr_ratio"])
                        if flip_score >= float(cfg.get("structure_flip_min_score", 62.0)) and rr_flip >= float(cfg.get("structure_flip_min_rr", 1.30)):
                            fp = dict(flip_plan)
                            fp.update({
                                "score": int(round(flip_score)),
                                "regime": rname,
                                "regime_confidence": rconf,
                                "trend_state": trend_state,
                                "volatility_state": vol_state,
                                "htf_bias": float(htf_flip),
                                "htf_details": htf_flip_details,
                                "equilibrium_bias": 0.0,
                                "equilibrium_mid": fp.get("daily_structure_levels", {}).get("eq"),
                                "edge_proxy": round(ev_flip, 4),
                                "model_win_proxy": round(pwin_flip, 4),
                                "setup_family": "structure_flip",
                            })
                            flip_reason_full = f"V6 Structure Flip {rname}/{vol_state} | {flip_reason} | HTF={htf_flip:.2f} | EdgeProxy={ev_flip:.2f}"
                            candidates.append((flip_score * max(rr_flip, 0.01), fp, flip["signal"], flip_reason_full))
    elif timeframe in ("1hour", "4hour"):
        # Dedicated HTF strategy: weekly/monthly liquidity reversal only. Generic V2
        # trend/breakout/mean-reversion selection is intentionally not used here.
        sig, reason = strategy_htf_liquidity_reversal(df_primary, timeframe, filters, cfg, market_data_dict=market_data_dict)
        add_candidate(sig, reason, "htf_liquidity_reversal", float(cfg.get("htf_reversal_score_bonus", 8.0)))
    else:
        if trend_state in ("BULL", "BEAR", "NEUTRAL"):
            sig, reason = strategy_trend_following(df_primary, timeframe, filters, cfg)
            add_candidate(sig, reason, "trend", 4 if trend_state in ("BULL", "BEAR") else 0)
            sig, reason = strategy_breakout(df_primary, filters, cfg)
            add_candidate(sig, reason, "breakout", 6 if trend_state in ("BULL", "BEAR") else 2)
        if trend_state in ("RANGE", "NEUTRAL"):
            sig, reason = strategy_mean_reversion(df_primary, filters, cfg)
            add_candidate(sig, reason, "mean_reversion", 0)

    if not candidates:
        no_setup_label = "V8 Structure First: هیچ Structure Flip معتبری وجود ندارد؛ ورود ممنوع" if (timeframe in tuple(cfg.get("structure_first_timeframes", ("5min", "15min"))) and bool(cfg.get("structure_first_enabled", True))) else "V2: ستاپ مناسب پیدا نشد"
        return None, None, (
            f"{no_setup_label} | regime={rname} trend={trend_state} "
            f"vol={vol_state} conf={rconf:.2f} ATRx={regime_info['atr_ratio']:.2f}"
        )
    candidates.sort(key=lambda x: x[0], reverse=True)
    _, best_plan, best_sig, best_reason = candidates[0]
    return best_sig, best_plan, best_reason


def strategy_dynamic_v2(df_primary, market_data_dict=None, timeframe="5min", filters=None, strategy_config=None, regime=None, live_price=None, defer_quality_gate=False):
    sig, plan, reason = _select_v2_setup(df_primary, market_data_dict, timeframe, filters, strategy_config, regime, live_price=live_price, defer_quality_gate=defer_quality_gate)
    return sig, reason

def get_signal_with_reason_v2(df_primary, market_data_dict=None, timeframe_mode="single", timeframe="5min", strategy_type="dynamic", filters=None, strategy_config=None, regime=None, live_price=None, defer_quality_gate=False):
    if df_primary is None or df_primary.empty or len(df_primary) < 60:
        return None, "V2: داده کافی نیست"
    if strategy_type == "dynamic" and get_v2_config(strategy_config).get("v2_enabled", True):
        return strategy_dynamic_v2(df_primary, market_data_dict, timeframe, filters, strategy_config, regime, live_price=live_price, defer_quality_gate=defer_quality_gate)
    return get_signal_with_reason(df_primary, market_data_dict, timeframe_mode, timeframe, strategy_type, filters, strategy_config, regime, live_price=live_price)
