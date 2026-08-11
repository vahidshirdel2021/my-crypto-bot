import os
import time
import requests
import pandas as pd
from threading import Thread
from flask import Flask

# ==========================================
# ۰. وب‌سرور Flask برای Render و UptimeRobot
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "OK - Balanced Crypto Signal Bot Active 24/7!", 200

@app.route('/health')
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# ۱. تنظیمات تلگرام و واچ‌لیست ارزها
# ==========================================
TELEGRAM_TOKEN = "8931433787:AAEdgjh8du4c-gLEF7DQA7H8xAzs6O0p7mw"
CHAT_ID = "1878257830"

SYMBOLS = [
    'BTC', 'ETH', 'DEFI', 'YFI', 'MKR', 'BCH', 'COMP', 'KSM', 'LTC', 'AAVE',
    'ZEC', 'EGLD', 'BNB', 'DASH', 'FIL', 'ZEN', 'WAVES', 'SOL', 'UNI', 'DOT',
    'BAL', 'LIT', 'BAND', 'UNFI', 'SUSHI', 'SNX', 'AVAX', 'ATOM', 'TRB', 'ETC',
    'NEO', 'SRM', 'SFP', 'BEL', 'IOTA', 'AXS', 'RLC', 'SXP', 'GRT', 'RUNE',
    'ONT', 'KAVA', 'OCEAN', '1INCH', 'REN', 'KNC', 'ALPHA', 'TOMO', 'HNT', 'ENJ',
    'ICX', 'CRV', 'NEAR', 'CTK', 'LUNA', 'EOS', 'THETA', 'QTUM', 'MANA', 'OMG',
    'SAND', 'ADA', 'XEM', 'FTM', 'RVN', 'MTL', 'SC', 'STORJ', 'ZIL', 'SLP',
    'BTS', 'XRP', 'BLZ', 'FET', 'ALGO', 'DODO', 'CHR', 'AKRO', 'BZRX', 'CVC',
    'STMX', 'CELR', 'HBAR', 'SKL', 'RSR', 'REEF', 'CHZ', 'LINK', 'ALICE', 'ZRX',
    'COTI', 'ONE', 'MATIC', 'XTZ', 'NKN', 'ANKR', 'LINA', 'HOT', 'LRC', 'DOGE',
    'DENT', 'DGB', 'WIN', 'IOST', 'TRX', 'BTT', 'FLM', 'BAT', 'VET', 'SHIB',
    'ARPA', 'AR', 'C98', 'DYDX', 'TLM', 'GALA', 'AUDIO', 'MASK', 'BAKE', 'KEEP',
    'OGN', 'RAY', 'KLAY', 'ATA', 'NU', 'GTC', 'CELO', 'YFII', 'CTSI'
]

LOOKBACK = 300

def send_telegram_msg(message, chat_target=None):
    target = chat_target or CHAT_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": target, "text": message, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.status_code == 200
    except Exception as e:
        print(f"❌ خطا در ارسال پیام تلگرام: {e}")
        return False

# ==========================================
# ۲. دریافت داده‌های بازار و محاسبه اندیکاتورها
# ==========================================
def get_crypto_klines(coin_symbol, aggregate=1, limit=400):
    coin_symbol = coin_symbol.upper().replace("USDT", "").replace("/", "").strip()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    # اولویت اول: KuCoin API
    try:
        interval = "1hour" if aggregate == 1 else "4hour"
        url_kucoin = f"https://api.kucoin.com/api/v1/market/candles?symbol={coin_symbol}-USDT&type={interval}"
        res = requests.get(url_kucoin, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if data.get("code") == "200000" and data.get("data"):
                raw = data["data"]
                df = pd.DataFrame(raw, columns=['timestamp', 'open', 'close', 'high', 'low', 'volume', 'turnover'])
                df = df.iloc[::-1].reset_index(drop=True)
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = df[col].astype(float)
                if not df.empty and len(df) > 50:
                    return df
    except Exception:
        pass

    # اولویت دوم: Gate.io API
    try:
        interval = "1h" if aggregate == 1 else "4h"
        url_gate = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={coin_symbol}_USDT&interval={interval}&limit={limit}"
        res = requests.get(url_gate, headers=headers, timeout=5)
        if res.status_code == 200:
            raw = res.json()
            if isinstance(raw, list) and len(raw) > 50:
                df = pd.DataFrame(raw, columns=['timestamp', 'volume', 'close', 'high', 'low', 'open', 'amount'])
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = df[col].astype(float)
                if not df.empty:
                    return df
    except Exception:
        pass

    return pd.DataFrame()

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

# ==========================================
# ۳. تحلیل دستی ارز (/analyze)
# ==========================================
def analyze_coin_on_demand(coin_symbol):
    coin_symbol = coin_symbol.upper().replace("USDT", "").replace("/", "").strip()
    df = get_crypto_klines(coin_symbol, aggregate=1, limit=400)
    if df.empty or len(df) < 50:
        return f"❌ داده‌ای برای ارز `{coin_symbol}` یافت نشد."

    df = calculate_indicators(df)
    df_4h = get_crypto_klines(coin_symbol, aggregate=4, limit=300)
    ema_4h_val = df_4h['close'].ewm(span=200, adjust=False).mean().iloc[-1] if not df_4h.empty else df['ema200'].iloc[-1]

    df_sub = df.tail(LOOKBACK)
    ath, atl = df_sub['high'].max(), df_sub['low'].min()
    mid_price = (ath + atl) / 2
    upper_mid, lower_mid = (ath + mid_price) / 2, (mid_price + atl) / 2

    curr = df.iloc[-1]
    close_p = float(curr['close'])
    rsi_val = float(curr['rsi'])
    macd_val = float(curr['macd'])
    macd_sig = float(curr['macd_signal'])
    vol_val = float(curr['volume'])
    vol_ma_val = float(curr['vol_ma'])
    ema_1h_val = float(curr['ema200'])
    atr_val = float(curr['atr'])

    # فیلترهای روان‌تر
    trend_long = (close_p > ema_1h_val) or (close_p > ema_4h_val)
    trend_short = (close_p < ema_1h_val) or (close_p < ema_4h_val)
    near_support = (abs(close_p - lower_mid) / lower_mid < 0.03) or (abs(close_p - mid_price) / mid_price < 0.03)
    near_resistance = (abs(close_p - upper_mid) / upper_mid < 0.03) or (abs(close_p - mid_price) / mid_price < 0.03)
    volume_ok = vol_val > (vol_ma_val * 1.0)

    if trend_long and near_support and (35 < rsi_val < 70) and (macd_val > macd_sig) and volume_ok:
        status = "🟢 **ورود به معامله خرید (Long)**"
        tp, sl = close_p + (atr_val * 3.0), close_p - (atr_val * 2.0)
        details = f"🎯 *حد سود (TP):* `{tp:.4f}`\n🛑 *حد زیان (SL):* `{sl:.4f}`"
    elif trend_short and near_resistance and (30 < rsi_val < 65) and (macd_val < macd_sig) and volume_ok:
        status = "🔻 **ورود به معامله فروش (Short)**"
        tp, sl = close_p - (atr_val * 3.0), close_p + (atr_val * 2.0)
        details = f"🎯 *حد سود (TP):* `{tp:.4f}`\n🛑 *حد زیان (SL):* `{sl:.4f}`"
    else:
        status = "🛑 **عدم ورود (شرایط استراتژی مهیا نیست)**"
        details = "⏳ منتظر موقعیت مناسب تکنیکال باشید."

    msg = (
        f"📊 *تحلیل تکنیکال لحظه‌ای `{coin_symbol}/USDT`*\n\n"
        f"🔹 *قیمت فعلی:* `{close_p:.4f}`\n"
        f"🔹 *شاخص RSI:* `{rsi_val:.1f}`\n"
        f"🔹 *میانگین ۲۰۰ ۴ساعته:* `{ema_4h_val:.4f}`\n\n"
        f"📌 *وضعیت معامله:* {status}\n\n"
        f"{details}"
    )
    return msg

# ==========================================
# ۴. اسکنر اتوماتیک و صدور سیگنال (متعادل)
# ==========================================
def check_symbol(coin_symbol):
    display_name = f"{coin_symbol}/USDT"
    df = get_crypto_klines(coin_symbol, aggregate=1, limit=400)
    if df.empty or len(df) < 50:
        return
        
    df = calculate_indicators(df)
    df_4h = get_crypto_klines(coin_symbol, aggregate=4, limit=300)
    if df_4h.empty or len(df_4h) < 50:
        return
        
    ema_1h_val = df['ema200'].iloc[-1]
    ema_4h_val = df_4h['close'].ewm(span=200, adjust=False).mean().iloc[-1]
    
    df_sub = df.tail(LOOKBACK)
    ath, atl = df_sub['high'].max(), df_sub['low'].min()
    mid_price = (ath + atl) / 2
    upper_mid, lower_mid = (ath + mid_price) / 2, (mid_price + atl) / 2
    
    curr = df.iloc[-2]
    close_p = float(curr['close'])
    
    # فیلتر فاصله از سطوح (۳٪)
    near_support = (abs(close_p - lower_mid) / lower_mid < 0.03) or (abs(close_p - mid_price) / mid_price < 0.03)
    near_resistance = (abs(close_p - upper_mid) / upper_mid < 0.03) or (abs(close_p - mid_price) / mid_price < 0.03)
    
    # فیلتر حجم نرمال (۱.۱ برابر)
    volume_ok = float(curr['volume']) > (float(curr['vol_ma']) * 1.1)
    
    macd_long_ok = float(curr['macd']) > float(curr['macd_signal'])
    macd_short_ok = float(curr['macd']) < float(curr['macd_signal'])
    rsi_val = float(curr['rsi'])
    
    trend_long_ok = (close_p > ema_1h_val) or (close_p > ema_4h_val)
    trend_short_ok = (close_p < ema_1h_val) or (close_p < ema_4h_val)
    
    rsi_long_ok = 35 < rsi_val < 70
    rsi_short_ok = 30 < rsi_val < 65
    
    if trend_long_ok and near_support and rsi_long_ok and macd_long_ok and volume_ok:
        atr_val = float(curr['atr'])
        sl = close_p - (atr_val * 2.0)
        tp = close_p + (atr_val * 3.0)
        msg = (
            f"🚀 *سیگنال خرید (Long)*\n\n"
            f"🔹 *ارز:* `{display_name}`\n"
            f"🔹 *قیمت ورود:* `{close_p:.4f}`\n"
            f"🎯 *حد سود (TP):* `{tp:.4f}`\n"
            f"🛑 *حد زیان (SL):* `{sl:.4f}`\n\n"
            f"📊 *تایم‌فریم:* ۱ ساعته"
        )
        send_telegram_msg(msg)
        
    elif trend_short_ok and near_resistance and rsi_short_ok and macd_short_ok and volume_ok:
        atr_val = float(curr['atr'])
        sl = close_p + (atr_val * 2.0)
        tp = close_p - (atr_val * 3.0)
        msg = (
            f"🔻 *سیگنال فروش (Short)*\n\n"
            f"🔹 *ارز:* `{display_name}`\n"
            f"🔹 *قیمت ورود:* `{close_p:.4f}`\n"
            f"🎯 *حد سود (TP):* `{tp:.4f}`\n"
            f"🛑 *حد زیان (SL):* `{sl:.4f}`\n\n"
            f"📊 *تایم‌فریم:* ۱ ساعته"
        )
        send_telegram_msg(msg)

def telegram_listener():
    last_update_id = None
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    while True:
        try:
            params = {"timeout": 10, "offset": last_update_id}
            res = requests.get(url, params=params, timeout=12)
            if res.status_code == 200:
                data = res.json()
                for result in data.get("result", []):
                    last_update_id = result["update_id"] + 1
                    message = result.get("message", {})
                    text = message.get("text", "").strip()
                    chat_id = message.get("chat", {}).get("id")

                    if not text or not chat_id:
                        continue

                    if text.startswith("/analyze") or text.startswith("/check"):
                        parts = text.split()
                        coin = parts[1] if len(parts) > 1 else "BTC"
                        send_telegram_msg(f"⏳ در حال استعلام داده‌های تکنیکال `{coin}`...", chat_target=chat_id)
                        analysis_res = analyze_coin_on_demand(coin)
                        send_telegram_msg(analysis_res, chat_target=chat_id)
                    elif text.startswith("/start") or text.startswith("/help"):
                        help_text = (
                            "🤖 *ربات سیگنال‌دهی تکنیکال (نسخه متعادل)*\n\n"
                            "🔹 `/analyze BTC` : استعلام تحلیل تکنیکال بیت‌کوین\n"
                            "🔹 `/analyze SOL` : استعلام تحلیل تکنیکال سولانا"
                        )
                        send_telegram_msg(help_text, chat_target=chat_id)
        except Exception:
            pass
        time.sleep(2)

def bot_loop():
    time.sleep(5)
    send_telegram_msg("⚡ *ربات سیگنال‌دهی با تنظیمات روان و روان‌تر صادرکننده سیگنال فعال شد.*")
    while True:
        for sym in SYMBOLS:
            try:
                check_symbol(sym)
            except Exception:
                pass
            time.sleep(1)
        time.sleep(3600)

if __name__ == "__main__":
    Thread(target=telegram_listener, daemon=True).start()
    Thread(target=bot_loop, daemon=True).start()
    run_flask()
