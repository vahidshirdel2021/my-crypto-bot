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
    return "OK - Ultimate Pullback Crypto Bot Active 24/7!", 200

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
    # EMA 200
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # RSI 14
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # ATR 14
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=14).mean()
    
    # ADX 14
    up = df['high'].diff()
    down = -df['low'].diff()
    pos_dm = up.where((up > down) & (up > 0), 0)
    neg_dm = down.where((down > up) & (down > 0), 0)
    
    tr_smooth = tr.rolling(window=14).sum()
    pos_dm_smooth = pos_dm.rolling(window=14).sum()
    neg_dm_smooth = neg_dm.rolling(window=14).sum()
    
    pos_di = 100 * (pos_dm_smooth / tr_smooth)
    neg_di = 100 * (neg_dm_smooth / tr_smooth)
    dx = 100 * (pos_di - neg_di).abs() / (pos_di + neg_di)
    df['adx'] = dx.rolling(window=14).mean()
    
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

    curr = df.iloc[-1]
    prev = df.iloc[-2]
    
    close_p = float(curr['close'])
    open_p = float(curr['open'])
    rsi_curr = float(curr['rsi'])
    rsi_prev = float(prev['rsi'])
    adx_val = float(curr['adx'])
    ema_1h_val = float(curr['ema200'])
    atr_val = float(curr['atr'])

    # شرایط استراتژی پولبک
    trend_long = (close_p > ema_1h_val) or (close_p > ema_4h_val)
    trend_short = (close_p < ema_1h_val) or (close_p < ema_4h_val)
    trending_market = adx_val > 20
    
    bullish_candle = close_p > open_p
    bearish_candle = close_p < open_p
    
    pullback_long = trend_long and trending_market and (rsi_prev < 45) and (rsi_curr > rsi_prev) and bullish_candle
    pullback_short = trend_short and trending_market and (rsi_prev > 55) and (rsi_curr < rsi_prev) and bearish_candle

    if pullback_long:
        status = "🟢 **ورود به معامله خرید (Long - Pullback)**"
        sl = close_p - (atr_val * 2.0)
        tp = close_p + (atr_val * 3.0)
        details = f"🎯 *حد سود (TP):* `{tp:.4f}`\n🛑 *حد زیان (SL):* `{sl:.4f}`"
    elif pullback_short:
        status = "🔻 **ورود به معامله فروش (Short - Pullback)**"
        sl = close_p + (atr_val * 2.0)
        tp = close_p - (atr_val * 3.0)
        details = f"🎯 *حد سود (TP):* `{tp:.4f}`\n🛑 *حد زیان (SL):* `{sl:.4f}`"
    else:
        status = "🛑 **عدم ورود (شرایط پولبک یا روند مهیا نیست)**"
        details = f"📊 *شاخص ADX:* `{adx_val:.1f}` (حداقل ۲۰) | *RSI:* `{rsi_curr:.1f}`"

    msg = (
        f"📊 *تحلیل تکنیکال استراتژی پولبک `{coin_symbol}/USDT`*\n\n"
        f"🔹 *قیمت فعلی:* `{close_p:.4f}`\n"
        f"🔹 *شاخص ADX (قدرت روند):* `{adx_val:.1f}`\n"
        f"🔹 *شاخص RSI:* `{rsi_curr:.1f}`\n\n"
        f"📌 *وضعیت معامله:* {status}\n\n"
        f"{details}"
    )
    return msg

# ==========================================
# ۴. اسکنر اتوماتیک و صدور سیگنال (Pullback)
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
        
    ema_1h_val = df['ema200'].iloc[-2]
    ema_4h_val = df_4h['close'].ewm(span=200, adjust=False).mean().iloc[-1]
    
    curr = df.iloc[-2]  # کندل تثبیت‌شده قبلی
    prev = df.iloc[-3]
    
    close_p = float(curr['close'])
    open_p = float(curr['open'])
    rsi_curr = float(curr['rsi'])
    rsi_prev = float(prev['rsi'])
    adx_val = float(curr['adx'])
    atr_val = float(curr['atr'])
    
    trend_long_ok = (close_p > ema_1h_val) or (close_p > ema_4h_val)
    trend_short_ok = (close_p < ema_1h_val) or (close_p < ema_4h_val)
    trending_market = adx_val > 20
    
    bullish_candle = close_p > open_p
    bearish_candle = close_p < open_p
    
    pullback_long = trend_long_ok and trending_market and (rsi_prev < 45) and (rsi_curr > rsi_prev) and bullish_candle
    pullback_short = trend_short_ok and trending_market and (rsi_prev > 55) and (rsi_curr < rsi_prev) and bearish_candle
    
    if pullback_long:
        sl = close_p - (atr_val * 2.0)
        tp = close_p + (atr_val * 3.0)
        msg = (
            f"🚀 *سیگنال خرید پولبک (Long)*\n\n"
            f"🔹 *ارز:* `{display_name}`\n"
            f"🔹 *قیمت ورود:* `{close_p:.4f}`\n"
            f"🎯 *حد سود (TP):* `{tp:.4f}`\n"
            f"🛑 *حد زیان (SL):* `{sl:.4f}`\n"
            f"📈 *شاخص ADX:* `{adx_val:.1f}`\n\n"
            f"📊 *تایم‌فریم:* ۱ ساعته"
        )
        send_telegram_msg(msg)
        
    elif pullback_short:
        sl = close_p + (atr_val * 2.0)
        tp = close_p - (atr_val * 3.0)
        msg = (
            f"🔻 *سیگنال فروش پولبک (Short)*\n\n"
            f"🔹 *ارز:* `{display_name}`\n"
            f"🔹 *قیمت ورود:* `{close_p:.4f}`\n"
            f"🎯 *حد سود (TP):* `{tp:.4f}`\n"
            f"🛑 *حد زیان (SL):* `{sl:.4f}`\n"
            f"📈 *شاخص ADX:* `{adx_val:.1f}`\n\n"
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
                        send_telegram_msg(f"⏳ در حال بررسی اندیکاتورهای پولبک روی `{coin}`...", chat_target=chat_id)
                        analysis_res = analyze_coin_on_demand(coin)
                        send_telegram_msg(analysis_res, chat_target=chat_id)
                    elif text.startswith("/start") or text.startswith("/help"):
                        help_text = (
                            "🤖 *ربات سیگنال‌دهی تکنیکال (استراتژی پولبک)*\n\n"
                            "🔹 `/analyze BTC` : استعلام تحلیل تکنیکال بیت‌کوین\n"
                            "🔹 `/analyze SOL` : استعلام تحلیل تکنیکال سولانا"
                        )
                        send_telegram_msg(help_text, chat_target=chat_id)
        except Exception:
            pass
        time.sleep(2)

def bot_loop():
    time.sleep(5)
    send_telegram_msg("⚡ *ربات سیگنال‌دهی با استراتژی پولبک (Ultimate Pullback) با موفقیت فعال شد.*")
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
