import pandas as pd

def get_strategy_params(tf):
    return {
        "5min": {"adx": 25, "sl": 1.2, "tp": 2.0, "rsi_b": 45, "rsi_s": 55},
        "15min": {"adx": 20, "sl": 1.3, "tp": 2.2, "rsi_b": 48, "rsi_s": 52},
        "1hour": {"adx": 18, "sl": 1.5, "tp": 2.5, "rsi_b": 50, "rsi_s": 50}
    }.get(tf, {"adx": 25, "sl": 1.2, "tp": 2.0, "rsi_b": 45, "rsi_s": 55})

def calculate_indicators(df):
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=14).mean()
    
    up = df['high'].diff()
    down = -df['low'].diff()
    pos_dm = up.where((up > down) & (up > 0), 0)
    neg_dm = down.where((down > up) & (down > 0), 0)
    
    tr_sum = tr.rolling(window=14).sum()
    pos_di = 100 * (pos_dm.rolling(window=14).sum() / tr_sum)
    neg_di = 100 * (neg_dm.rolling(window=14).sum() / tr_sum)
    df['adx'] = (100 * (pos_di - neg_di).abs() / (pos_di + neg_di)).rolling(window=14).mean()
    return df

def get_signal(df, tf):
    p = get_strategy_params(tf)
    curr = df.iloc[-2]
    prev = df.iloc[-3]
    
    trend_long = (curr['close'] > curr['ema200']) and (curr['ema50'] > curr['ema200']) and (curr['adx'] > p['adx'])
    trend_short = (curr['close'] < curr['ema200']) and (curr['ema50'] < curr['ema200']) and (curr['adx'] > p['adx'])
    
    if trend_long and (prev['rsi'] < p['rsi_b']) and (curr['rsi'] > prev['rsi']) and (curr['close'] > curr['open']): 
        return "BUY"
    if trend_short and (prev['rsi'] > p['rsi_s']) and (curr['rsi'] < prev['rsi']) and (curr['close'] < curr['open']): 
        return "SELL"
    return None