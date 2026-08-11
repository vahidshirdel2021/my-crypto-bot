import os
from threading import Thread
from flask import Flask
import requests
import pandas as pd
import time
from datetime import datetime

# ==========================================
# ۰. وب‌سرور کوچک برای Render
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# ۱. تنظیمات تلگرام و واچ‌لیست (۱۳ ارز)
# ==========================================
TELEGRAM_TOKEN = "8931433787:AAEdgjh8du4c-gLEF7DQA7H8xAzs6O0p7mw"
CHAT_ID = "1878257830"

SYMBOLS = [
    'BTC', 'ETH', 'BNB', 'ADA', 
    'DOGE', 'AVAX', 'TRX', 'DOT', 
    'NEAR', 'XLM', 'AAVE', 'GRT', 'INJ'
]

LOOKBACK = 300

def send_telegram_msg(message):
    """ارسال پیام مستقیم به تلگرام"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.status_code == 200
    except Exception as e:
        print(f"❌ خطا در ارسال پیام تلگرام: {e}")
        return False

def get_crypto_klines(coin_symbol, aggregate=1, limit=400):
    """دریافت کندل‌ها از CryptoCompare"""
    url = "https://min-api.cryptocompare.com/data/v2/histohour"
    params = {
        "fsym": coin_symbol,
        "tsym": "USDT",
        "limit": limit,
        "aggregate": aggregate
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, params=params, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if data.get("Response") == "Success":
                raw_candles = data["Data"]["Data"]
                df = pd.DataFrame(raw_candles)
                df = df.rename(columns={'time': 'timestamp', 'volumefrom': 'volume'})
                df['open'] = df['open'].astype(float)
                df['high'] = df['high'].astype(float)
                df['low'] = df['low'].astype(float)
                df['close'] = df['close'].astype(float)
                df['volume'] = df['volume'].astype(float)
                return df
    except Exception as e:
        print(f"❌ خطا در دریافت کندل‌های {coin_symbol}: {e}")
    return pd.DataFrame()

# ==========================================
# ۲. محاسبات اندیکاتورها با پایتون خالص
# ==========================================
def calculate_indicators(df):
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = ema12 - ema26
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    
    df['vol_ma'] = df['volume'].rolling(window=20).mean()
    
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=14).mean()
    
    return df

def check_symbol(coin_symbol):
    display_name = f"{coin_symbol}/USDT"
    print(f"[{datetime.now().strftime('%H:%M:%S')}] در حال بررسی {display_name}...")
    
    df = get_crypto_klines(coin_symbol, aggregate=1, limit=400)
    if df.empty or len(df) < 50:
        print(f"⚠️ داتایی برای {display_name} دریافت نشد.")
        return
        
    df = calculate_indicators(df)
    
    df_4h = get_crypto_klines(coin_symbol, aggregate=4, limit=300)
    if not df_4h.empty:
        df_4h['ema200'] = df_4h['close'].ewm(span=200, adjust=False).mean()
        ema_4h_val = df_4h['ema200'].iloc[-1]
    else:
        ema_4h_val = df['ema200'].iloc[-1]
    
    df_sub = df.tail(LOOKBACK)
    ath = df_sub['high'].max()
    atl = df_sub['low'].min()
    mid_price = (ath + atl) / 2
    upper_mid = (ath + mid_price) / 2
    lower_mid = (mid_price + atl) / 2
    
    curr = df.iloc[-2]
    close_p = float(curr['close'])
    
    near_support = (abs(close_p - lower_mid) / lower_mid < 0.02) or (abs(close_p - mid_price) / mid_price < 0.02)
    near_resistance = (abs(close_p - upper_mid) / upper_mid < 0.02) or (abs(close_p - mid_price) / mid_price < 0.02)
    
    volume_ok = float(curr['volume']) > (float(curr['vol_ma']) * 1.1)
    macd_long_ok = float(curr['macd']) > float(curr['macd_signal'])
    macd_short_ok = float(curr['macd']) < float(curr['macd_signal'])
    
    if (close_p > ema_4h_val) and near_support and (float(curr['rsi']) > 35) and macd_long_ok and volume_ok:
        atr_val = float(curr['atr'])
        sl = close_p - (atr_val * 1.5)
        tp = close_p + (atr_val * 3.0)
        
        msg = f"🚀 *سیگنال خرید (Long)*\n\n🔹 *ارز:* `{display_name}`\n🔹 *قیمت ورود:* `{close_p:.4f}`\n🎯 *حد سود (TP):* `{tp:.4f}`\n🛑 *حد زیان (SL):* `{sl:.4f}`\n\n📊 *تایم‌فریم:* ۱ ساعته"
        send_telegram_msg(msg)
        print(f"✅ سیگنال خرید فرستاده شد: {display_name}")
        
    elif (close_p < ema_4h_val) and near_resistance and (float(curr['rsi']) < 65) and macd_short_ok and volume_ok:
        atr_val = float(curr['atr'])
        sl = close_p + (atr_val * 1.5)
        tp = close_p - (atr_val * 3.0)
        
        msg = f"🔻 *سیگنال فروش (Short)*\n\n🔹 *ارز:* `{display_name}`\n🔹 *قیمت ورود:* `{close_p:.4f}`\n🎯 *حد سود (TP):* `{tp:.4f}`\n🛑 *حد زیان (SL):* `{sl:.4f}`\n\n📊 *تایم‌فریم:* ۱ ساعته"
        send_telegram_msg(msg)
        print(f"✅ سیگنال فروش فرستاده شد: {display_name}")

# ==========================================
# ۳. اجرای اصلی برنامه
# ==========================================
if __name__ == "__main__":
    # روشن کردن وب‌سرور در پس‌زمینه
    server_thread = Thread(target=run_flask)
    server_thread.daemon = True
    server_thread.start()
    
    print("🚀 در حال راه‌اندازی ربات روی Render...")
    send_telegram_msg("🟢 *ربات سیگنال‌دهی با موفقیت روی سرور Render راه‌اندازی و روشن شد.*")
    
    while True:
        for sym in SYMBOLS:
            try:
                check_symbol(sym)
            except Exception as e:
                print(f"⚠️ خطا در بررسی {sym}: {e}")
            time.sleep(1)
        
        print("\n⏱️ اسکن ۱۳ ارز کامل شد. انتظار ۱ ساعته تا کندل بعدی...\n")
        time.sleep(3600)