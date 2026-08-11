import os
import time
from datetime import datetime
from threading import Thread
from flask import Flask
import requests
import pandas as pd
import google.generativeai as genai

# ==========================================
# ۰. وب‌سرور Flask برای Render و UptimeRobot
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "OK - AI Strict Crypto Bot Active!", 200

@app.route('/health')
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# ۱. تنظیمات تلگرام و جمینای
# ==========================================
TELEGRAM_TOKEN = "8931433787:AAEdgjh8du4c-gLEF7DQA7H8xAzs6O0p7mw"
CHAT_ID = "1878257830"
# حتما بررسی کنید که کلید در بخش Environment سایت Render وارد شده باشد
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AQ.Ab8RN6KAg0sT3mnay_Pq7lN3dXKWp-D7wNwp_hDGGMk0wYW3eg")

genai.configure(api_key=GEMINI_API_KEY)

def generate_gemini_response(prompt):
    """تلاش برای اتصال به مدل‌های پایدار جمینای و نمایش خطای واقعی در صورت شکست"""
    models_to_try = [
        'gemini-1.5-flash',
        'gemini-1.5-pro',
        'gemini-1.0-pro'
    ]
    last_error = ""
    for model_name in models_to_try:
        try:
            m = genai.GenerativeModel(model_name)
            res = m.generate_content(prompt)
            if res and res.text:
                return res.text.strip()
        except Exception as e:
            last_error = str(e)
            print(f"⚠️ Error with {model_name}: {e}")
            continue
            
    # اگر هیچ‌کدام کار نکرد، خطای واقعی را برگردان تا بفهمیم مشکل چیست
    return f"⚠️ ارتباط با جمینای برقرار نشد. جزئیات خطا:\n`{last_error}`"

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
# ۲. دریافت داده‌های آنلاین بازار (KuCoin / Gate.io)
# ==========================================
def get_crypto_klines(coin_symbol, aggregate=1, limit=400):
    coin_symbol = coin_symbol.upper().replace("USDT", "").replace("/", "").strip()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
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

def get_ai_validation(coin, signal_type, price, rsi_val, macd_status):
    prompt = f"""
    یک معامله‌گر حرفه‌ای هستی. یک سیگنال با کیفیت بالا صادر شده است:
    ارز: {coin}/USDT | نوع: {signal_type} | قیمت: {price} | RSI: {rsi_val:.1f} | MACD: {macd_status}
    در ۲ جمله کوتاه و دقیق علت مناسب بودن این ورود را بگو.
    """
    return generate_gemini_response(prompt)

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

    prompt = f"""
    داده‌های ارز {coin_symbol}/USDT:
    قیمت: {close_p} | EMA200 ۴ساعته: {ema_4h_val} | RSI: {rsi_val:.1f} | MACD: {macd_val:.4f} | حجم: {vol_val:.1f} (میانگین: {vol_ma_val:.1f})
    حمایت: {lower_mid:.4f} | مقاومت: {upper_mid:.4f}

    پاسخ دقیق فارسی با فرمت:
    1. وضعیت معامله: (🟢 **ورود (Long)** / 🔻 **ورود (Short)** / 🛑 **عدم ورود**)
    2. علت تصمیم در ۲ جمله کوتاه.
    3. حد سود (TP) و حد زیان (SL) پیشنهادی.
    """
    res_text = generate_gemini_response(prompt)
    return f"🔍 *تحلیل هوشمند لحظه‌ای `{coin_symbol}/USDT`*\n\n{res_text}"

# ==========================================
# ۳. اسکنر سخت‌گیرانه (فقط سیگنال‌های A+)
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
    
    # ۱. فیلتر فاصله بسیار نزدیک به حمایت/مقاومت (کاهش به ۱٪)
    near_support = (abs(close_p - lower_mid) / lower_mid < 0.01) or (abs(close_p - mid_price) / mid_price < 0.01)
    near_resistance = (abs(close_p - upper_mid) / upper_mid < 0.01) or (abs(close_p - mid_price) / mid_price < 0.01)
    
    # ۲. فیلتر حجم سنگین (حداقل ۵۰٪ بیشتر از میانگین)
    volume_ok = float(curr['volume']) > (float(curr['vol_ma']) * 1.5)
    
    macd_long_ok = float(curr['macd']) > float(curr['macd_signal'])
    macd_short_ok = float(curr['macd']) < float(curr['macd_signal'])
    rsi_val = float(curr['rsi'])
    
    # ۳. تایید هم‌زمان روند ۱ ساعته و ۴ ساعته
    trend_long_ok = (close_p > ema_1h_val) and (close_p > ema_4h_val)
    trend_short_ok = (close_p < ema_1h_val) and (close_p < ema_4h_val)
    
    # ۴. محدوده RSI بهینه
    rsi_long_ok = 40 < rsi_val < 65
    rsi_short_ok = 35 < rsi_val < 60
    
    if trend_long_ok and near_support and rsi_long_ok and macd_long_ok and volume_ok:
        atr_val = float(curr['atr'])
        sl, tp = close_p - (atr_val * 1.5), close_p + (atr_val * 3.0)
        ai_comment = get_ai_validation(coin_symbol, "خرید (Long)", close_p, rsi_val, "صعودی قوی")
        msg = (
            f"🌟 *سیگنال ویژه خرید (Long - A+)*\n\n"
            f"🔹 *ارز:* `{display_name}`\n"
            f"🔹 *قیمت ورود:* `{close_p:.4f}`\n"
            f"🎯 *حد سود (TP):* `{tp:.4f}`\n"
            f"🛑 *حد زیان (SL):* `{sl:.4f}`\n\n"
            f"🤖 *تحلیل جمینای:*\n_{ai_comment}_\n\n"
            f"📊 *تایم‌فریم:* ۱ ساعته"
        )
        send_telegram_msg(msg)
        
    elif trend_short_ok and near_resistance and rsi_short_ok and macd_short_ok and volume_ok:
        atr_val = float(curr['atr'])
        sl, tp = close_p + (atr_val * 1.5), close_p - (atr_val * 3.0)
        ai_comment = get_ai_validation(coin_symbol, "فروش (Short)", close_p, rsi_val, "نزولی قوی")
        msg = (
            f"🌟 *سیگنال ویژه فروش (Short - A+)*\n\n"
            f"🔹 *ارز:* `{display_name}`\n"
            f"🔹 *قیمت ورود:* `{close_p:.4f}`\n"
            f"🎯 *حد سود (TP):* `{tp:.4f}`\n"
            f"🛑 *حد زیان (SL):* `{sl:.4f}`\n\n"
            f"🤖 *تحلیل جمینای:*\n_{ai_comment}_\n\n"
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
                        send_telegram_msg(f"⏳ در حال تحلیل فیلترهای سخت‌گیرانه روی `{coin}`...", chat_target=chat_id)
                        analysis_res = analyze_coin_on_demand(coin)
                        send_telegram_msg(analysis_res, chat_target=chat_id)
                    elif text.startswith("/start") or text.startswith("/help"):
                        help_text = (
                            "🤖 *ربات هوشمند سیگنال‌دهی VIP*\n\n"
                            "🔹 `/analyze BTC` : تحلیل کامل استراتژی روی بیت‌کوین\n"
                            "🔹 `/analyze ETH` : تحلیل کامل روی اتریوم"
                        )
                        send_telegram_msg(help_text, chat_target=chat_id)
        except Exception:
            pass
        time.sleep(2)

def bot_loop():
    time.sleep(5)
    send_telegram_msg("🎯 *استراتژی سخت‌گیرانه (VIP / A+) به همراه سیستم عیب‌یاب هوش مصنوعی با موفقیت فعال شد.*")
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
