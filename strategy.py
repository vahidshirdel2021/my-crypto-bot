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
    else:
        return {"adx": 25, "sl": 2.0, "tp": 3.0}

def get_signal(df_5m, df_1h=None):
    if df_5m.empty or len(df_5m) < 50:
        return None
    
    curr = df_5m.iloc[-2]
    prev = df_5m.iloc[-3]
    
    higher_tf_bullish = True
    higher_tf_bearish = True
    
    if df_1h is not None and not df_1h.empty and len(df_1h) > 20:
        h_curr = df_1h.iloc[-2]
        higher_tf_bullish = h_curr['close'] > h_curr['ema50']
        higher_tf_bearish = h_curr['close'] < h_curr['ema50']

    adx_ok = curr.get('adx', 30) > 20
    is_uptrend = curr['close'] > curr['ema50'] and curr['ema20'] > curr['ema50']
    is_downtrend = curr['close'] < curr['ema50'] and curr['ema20'] < curr['ema50']
    
    pullback_buy = prev['low'] <= prev['ema20'] and curr['close'] > curr['ema20']
    pullback_sell = prev['high'] >= prev['ema20'] and curr['close'] < curr['ema20']
    
    if is_uptrend and pullback_buy and adx_ok and higher_tf_bullish:
        return "BUY"
    elif is_downtrend and pullback_sell and adx_ok and higher_tf_bearish:
        return "SELL"
        
    return None