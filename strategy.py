import pandas as pd
import numpy as np

FILTERS = {
    "volume_filter": True,
    "trailing_stop": True,
    "candlestick_filter": True,
    "no_short_filter": False
}

STRATEGY_CONFIG = {
    "min_adx": 20,
    "sl_multiplier": 1.5,
    "tp_multiplier": 2.0
}

def calculate_indicators(df):
    if df.empty or len(df) < 50:
        return df
    
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    df['atr'] = true_range.rolling(14).mean()
    
    plus_dm = df['high'].diff()
    minus_dm = df['low'].diff()
    plus_dm = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0.0)
    minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), minus_dm, 0.0)
    
    tr14 = true_range.rolling(14).sum()
    plus_di = 100 * (pd.Series(plus_dm).rolling(14).sum() / (tr14 + 1e-9))
    minus_di = 100 * (pd.Series(minus_dm).rolling(14).sum() / (tr14 + 1e-9))
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-9)
    df['adx'] = pd.Series(dx).rolling(14).mean()
    
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / (loss + 1e-9)
    df['rsi'] = 100 - (100 / (1 + rs))
    
    df['channel_high'] = df['high'].rolling(20).max().shift(1)
    df['channel_low'] = df['low'].rolling(20).min().shift(1)
    
    return df

def get_strategy_params(timeframe):
    return {"adx": STRATEGY_CONFIG["min_adx"], "sl": STRATEGY_CONFIG["sl_multiplier"], "tp": STRATEGY_CONFIG["tp_multiplier"]}

def get_strategy_description(timeframe):
    params = get_strategy_params(timeframe)
    return (
        f"📊 *تشریح استراتژی و پارامترهای فعال ({timeframe})*\n\n"
        f"• **آستانه قدرت روند (ADX):** `{params['adx']}`\n"
        f"• **حد ضرر (SL):** `{params['sl']}` برابر ATR\n"
        f"• **حد سود (TP):** `{params['tp']}` برابر ATR\n"
        f"• **فیلتر حجم:** `{'🟢 فعال' if FILTERS['volume_filter'] else '🔴 غیرفعال'}`\n"
        f"• **تریلینگ استاپ:** `{'🟢 فعال' if FILTERS['trailing_stop'] else '🔴 غیرفعال'}`"
    )

def check_candlestick_confirmation(df):
    curr = df.iloc[-2]
    prev = df.iloc[-3]
    
    if FILTERS["volume_filter"]:
        avg_vol = df['volume'].rolling(20).mean().iloc[-2]
        if curr['volume'] < avg_vol:
            return None, "حجم معاملات پایین‌تر از میانگین است"
            
    body = abs(curr['close'] - curr['open'])
    total_range = curr['high'] - curr['low']
    if total_range == 0:
        return None, None
    
    upper_shadow = curr['high'] - max(curr['close'], curr['open'])
    lower_shadow = min(curr['close'], curr['open']) - curr['low']
    
    is_bullish_pin = (lower_shadow >= 2 * body) and (upper_shadow < body) and (curr['close'] > curr['open'])
    is_bearish_pin = (upper_shadow >= 2 * body) and (lower_shadow < body) and (curr['close'] < curr['open'])
    
    prev_body = abs(prev['close'] - prev['open'])
    is_bullish_engulfing = (prev['close'] < prev['open']) and (curr['close'] > curr['open']) and (curr['close'] >= prev['open']) and (curr['open'] <= prev['close']) and (body > prev_body)
    is_bearish_engulfing = (prev['close'] > prev['open']) and (curr['close'] < curr['open']) and (curr['close'] <= prev['open']) and (curr['close'] >= prev['close']) and (body > prev_body)
    
    if is_bullish_pin or is_bullish_engulfing:
        pattern_name = "پین‌بار صعودی" if is_bullish_pin else "انگالفینگ صعودی"
        return "BUY_CONFIRMED", pattern_name
    elif is_bearish_pin or is_bearish_engulfing:
        pattern_name = "پین‌بار نزولی" if is_bearish_pin else "انگالفینگ نزولی"
        return "SELL_CONFIRMED", pattern_name
        
    return None, None

def strategy_trend_following(df, timeframe="5min"):
    curr = df.iloc[-2]
    prev = df.iloc[-3]
    params = get_strategy_params(timeframe)
    
    if curr['adx'] < params["adx"]:
        return None, f"رد شد: قدرت روند کم (ADX = {curr['adx']:.1f})"
    
    is_uptrend = curr['close'] > curr['ema50'] and curr['ema20'] > curr['ema50']
    is_downtrend = curr['close'] < curr['ema50'] and curr['ema20'] < curr['ema50']
    
    ema_val = prev['ema20']
    tolerance = curr['atr'] * 0.25
    
    touch_ema_buy = (prev['low'] <= ema_val + tolerance) and (prev['low'] >= ema_val - (curr['atr'] * 0.5))
    touch_ema_sell = (prev['high'] >= ema_val - tolerance) and (prev['high'] <= ema_val + (curr['atr'] * 0.5))
    
    if not FILTERS["candlestick_filter"]:
        if is_uptrend and touch_ema_buy and curr['close'] > curr['ema20']:
            return "BUY", f"خرید (Trend): تست موفق EMA20 (بدون نیاز به کندل تاییدیه)"
        if is_downtrend and touch_ema_sell and curr['close'] < curr['ema20']:
            return "SELL", f"فروش (Trend): تست موفق EMA20 (بدون نیاز به کندل تاییدیه)"
        return None, "شرایط روندپیروی برقرار نیست."

    candle_signal, pattern_desc = check_candlestick_confirmation(df)
    
    if is_uptrend and touch_ema_buy and curr['close'] > curr['ema20']:
        if candle_signal == "BUY_CONFIRMED":
            return "BUY", f"خرید (Trend + {pattern_desc}): تست موفق EMA20 و تاییدیه پرایس‌اکشن (ADX={curr['adx']:.1f})"
        else:
            return None, f"رد شد (صعودی): {pattern_desc if 'حجم' in str(pattern_desc) else 'کندل تاییدیه معتبر ثبت نشد.'}"
            
    if is_downtrend and touch_ema_sell and curr['close'] < curr['ema20']:
        if candle_signal == "SELL_CONFIRMED":
            return "SELL", f"فروش (Trend + {pattern_desc}): تست موفق EMA20 و تاییدیه پرایس‌اکشن (ADX={curr['adx']:.1f})"
        else:
            return None, f"رد شد (نزولی): {pattern_desc if 'حجم' in str(pattern_desc) else 'کندل تاییدیه معتبر ثبت نشد.'}"
    
    return None, "شرایط روندپیروی برقرار نیست."

def strategy_breakout(df):
    curr = df.iloc[-2]
    if curr['close'] > curr['channel_high']:
        return "BUY", "خرید (Breakout): شکست سقف کانال ۲۰ کندل گذشته"
    if curr['close'] < curr['channel_low']:
        return "SELL", "فروش (Breakout): شکست کف کانال ۲۰ کندل گذشته"
    return None, "قیمت درون کانال نوسان دارد."

def strategy_mean_reversion(df):
    curr = df.iloc[-2]
    rsi = float(curr.get('rsi', 50))
    if rsi < 30:
        return "BUY", f"خرید (RSI): اشباع فروش شدید (RSI = {rsi:.1f})"
    if rsi > 70:
        return "SELL", f"فروش (RSI): اشباع خرید شدید (RSI = {rsi:.1f})"
    return None, f"محدوده RSI خنثی است ({rsi:.1f})."

def strategy_multi_tf(df_primary, market_data_dict, timeframe="5min"):
    if market_data_dict:
        curr = df_primary.iloc[-2]
        is_uptrend = curr['close'] > curr['ema50']
        is_downtrend = curr['close'] < curr['ema50']
        for tf in ['1d', '4h', '1h', '15m']:
            df_tf = market_data_dict.get(tf)
            if df_tf is not None and not df_tf.empty and len(df_tf) > 20:
                h_curr = df_tf.iloc[-2]
                if is_uptrend and h_curr['close'] < h_curr['ema50']:
                    return None, f"رد شد: عدم هم‌راستایی در تایم بالاتر ({tf})"
                if is_downtrend and h_curr['close'] > h_curr['ema50']:
                    return None, f"رد شد: عدم هم‌راستایی در تایم بالاتر ({tf})"
    return strategy_trend_following(df_primary, timeframe)

def strategy_dynamic(df_primary, market_data_dict=None, timeframe="5min"):
    curr = df_primary.iloc[-2]
    adx = float(curr.get('adx', 20))
    min_adx_limit = STRATEGY_CONFIG["min_adx"]
    
    if adx > (min_adx_limit + 5):
        sig, reason = strategy_trend_following(df_primary, timeframe)
        return sig, f"[رژیم رونددار | ADX={adx:.1f}] {reason}"
    elif adx < min_adx_limit:
        sig, reason = strategy_mean_reversion(df_primary)
        return sig, f"[رژیم رنج | ADX={adx:.1f}] {reason}"
    else:
        return None, f"[فاز گذار | ADX={adx:.1f}] انتظار برای تثبیت بازار."

def get_signal_with_reason(df_primary, market_data_dict=None, timeframe_mode="single", timeframe="5min", strategy_type="trend"):
    if df_primary.empty or len(df_primary) < 50:
        return None, "داده‌های کافی برای محاسبه اندیکاتورها وجود ندارد."
    
    if strategy_type == "trend":
        return strategy_trend_following(df_primary, timeframe)
    elif strategy_type == "breakout":
        return strategy_breakout(df_primary)
    elif strategy_type == "mean_reversion":
        return strategy_mean_reversion(df_primary)
    elif strategy_type == "multi":
        return strategy_multi_tf(df_primary, market_data_dict, timeframe)
    elif strategy_type == "dynamic":
        return strategy_dynamic(df_primary, market_data_dict, timeframe)
    else:
        return strategy_trend_following(df_primary, timeframe)

def get_signal(df_primary, market_data_dict=None, timeframe_mode="single", timeframe="5min", strategy_type="trend"):
    sig, _ = get_signal_with_reason(df_primary, market_data_dict, timeframe_mode, timeframe, strategy_type)
    return sig
