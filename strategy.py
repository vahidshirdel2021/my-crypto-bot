import pandas as pd
import numpy as np

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
    
    return df

def get_strategy_params(timeframe):
    if timeframe == "5min":
        return {"adx": 20, "sl": 1.5, "tp": 2.0}
    elif timeframe == "15min":
        return {"adx": 22, "sl": 1.8, "tp": 2.5}
    elif timeframe == "1hour":
        return {"adx": 25, "sl": 2.0, "tp": 3.0}
    else: # multi
        return {"adx": 20, "sl": 1.5, "tp": 2.0}

def get_strategy_description(timeframe):
    params = get_strategy_params(timeframe)
    if timeframe == "5min":
        return (
            "📊 *تشریح استراتژی: اسکالپ ۵ دقیقه*\n\n"
            "• **سبک معاملاتی:** اسکالپ سریع و کوتاه مدت\n"
            f"• **حداقل قدرت روند (ADX):** بالای `{params['adx']}`\n"
            f"• **حد ضرر (SL):** `{params['sl']}` برابر ATR\n"
            f"• **حد سود (TP):** `{params['tp']}` برابر ATR\n"
            "• **شرط ورود:** نفوذ قیمت به خط EMA20 در جهت روند EMA50 به همراه تایید مومنتوم."
        )
    elif timeframe == "15min":
        return (
            "📊 *تشریح استراتژی: روزانه ۱۵ دقیقه*\n\n"
            "• **سبک معاملاتی:** ترید روزانه (Day Trading)\n"
            f"• **حداقل قدرت روند (ADX):** بالای `{params['adx']}`\n"
            f"• **حد ضرر (SL):** `{params['sl']}` برابر ATR\n"
            f"• **حد سود (TP):** `{params['tp']}` برابر ATR\n"
            "• **شرط ورود:** فیلتر نویزهای بازار و تایید پولبک در تایم‌فریم ۱۵ دقیقه."
        )
    elif timeframe == "1hour":
        return (
            "📊 *تشریح استراتژی: سوئینگ ۱ ساعت*\n\n"
            "• **سبک معاملاتی:** سوئینگ تریدینگ (Swing Trading)\n"
            f"• **حداقل قدرت روند (ADX):** بالای `{params['adx']}`\n"
            f"• **حد ضرر (SL):** `{params['sl']}` برابر ATR\n"
            f"• **حد سود (TP):** `{params['tp']}` برابر ATR\n"
            "• **شرط ورود:** تثبیت کندل‌ها در جهت خطوط کلیدی روند بلندمدت."
        )
    elif timeframe == "multi":
        return (
            "📊 *تشریح استراتژی: مولتی‌تایم‌فریم آبشاری*\n\n"
            "• **سبک معاملاتی:** ترید با روند کلان (Multi-TF Trend Following)\n"
            "• **مسیر فیلتر روند:** بررسی آبشاری از تایم‌فریم **روزانه (1D) ➔ ۴ ساعته (4H) ➔ ۱ ساعته (1H) ➔ ۱۵ دقیقه (15m)**\n"
            "• **نقطه ورود:** شکار دقیق نقطه ورود در تایم‌فریم **۵ دقیقه (5m)**\n"
            f"• **ریسک:** حد ضرر `{params['sl']}` ATR و حد سود `{params['tp']}` ATR\n"
            "• **قانون:** هم‌راستایی کامل روند تمام تایم‌فریم‌های بالاتر و بدون مغایرت."
        )
    return "⚠️ تایم‌فریم نامعتبر است."

def get_signal(df_primary, market_data_dict=None, timeframe_mode="single"):
    if df_primary.empty or len(df_primary) < 50:
        return None
    
    curr = df_primary.iloc[-2]
    prev = df_primary.iloc[-3]
    
    adx_ok = curr.get('adx', 30) > 20
    is_uptrend = curr['close'] > curr['ema50'] and curr['ema20'] > curr['ema50']
    is_downtrend = curr['close'] < curr['ema50'] and curr['ema20'] < curr['ema50']
    
    pullback_buy = prev['low'] <= prev['ema20'] and curr['close'] > curr['ema20']
    pullback_sell = prev['high'] >= prev['ema20'] and curr['close'] < curr['ema20']

    if timeframe_mode == "multi" and market_data_dict:
        for tf in ['1d', '4h', '1h', '15m']:
            df_tf = market_data_dict.get(tf)
            if df_tf is not None and not df_tf.empty and len(df_tf) > 20:
                h_curr = df_tf.iloc[-2]
                if is_uptrend and h_curr['close'] < h_curr['ema50']:
                    return None
                if is_downtrend and h_curr['close'] > h_curr['ema50']:
                    return None

    if is_uptrend and pullback_buy and adx_ok:
        return "BUY"
    elif is_downtrend and pullback_sell and adx_ok:
        return "SELL"
        
    return None
