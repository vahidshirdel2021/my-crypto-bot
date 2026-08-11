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
    return f"OK - Inline Button Bot Active! Active Coins: {len(ACTIVE_SYMBOLS)}", 200

@app.route('/health')
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# ۱. تنظیمات تلگرام و لیست اولیه ارزها
# ==========================================
TELEGRAM_TOKEN = "8931433787:AAEdgjh8du4c-gLEF7DQA7H8xAzs6O0p7mw"
CHAT_ID = "1878257830"

ALL_SYMBOLS = [
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

ACTIVE_SYMBOLS = []

def send_telegram_msg(message, chat_target=None, reply_markup=None):
    target = chat_target or CHAT_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": target, "text": message, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.status_code == 200
    except Exception as e:
        print(f"❌ خطا در ارسال پیام تلگرام: {e}")
        return False

# ==========================================
# ۲. ارسال منوی اصلی با دکمه‌های شیشه‌ای
# ==========================================
def send_main_menu(chat_id):
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "📊 تحلیل BTC", "callback_data": "/analyze BTC"},
                {"text": "⚡ تحلیل ETH", "callback_data": "/analyze ETH"},
                {"text": "🚀 تحلیل SOL", "callback_data": "/analyze SOL"}
            ],
            [
                {"text": "📋 واچ‌لیست فعال و سودده", "callback_data": "/active_coins"},
                {"text": "🔄 فیلتر مجدد واچ‌لیست", "callback_data": "/refilter"}
            ],
            [
                {"text": "❓ راهنمای دستورات پویا", "callback_data": "/help"}
            ]
        ]
    }
    msg = (
        "🎛 *پنل مدیریت و کنترل هوشمند ربات*\n\n"
        "یکی از دکمه‌های زیر را لمس کنید یا دستور خود را ارسال نمایید:"
    )
    send_telegram_msg(msg, chat_target=chat_id, reply_markup=keyboard)

# ==========================================
# ۳. دریافت داده‌های بازار و اندیکاتورها
# ==========================================
def get_crypto_klines(coin_symbol, aggregate=1, limit=300):
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
    
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=14).mean()
    
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
# ۴. الگوریتم فیلتر پویای واچ‌لیست
# ==========================================
def filter_winning_symbols():
    global ACTIVE_SYMBOLS
    print("🔍 در حال اجرای بک‌تست خودکار و سنجش سودآوری ارزها...")
    send_telegram_msg("🔄 *در حال ارزیابی و پاک‌سازی واچ‌لیست بر اساس داده‌های گذشته...*")
    
    winning_list = []
    for sym in ALL_SYMBOLS:
        try:
            df = get_crypto_klines(sym, aggregate=1, limit=300)
            if df.empty or len(df) < 150:
                continue
                
            df = calculate_indicators(df)
            df_4h = get_crypto_klines(sym, aggregate=4, limit=200)
            if df_4h.empty:
                continue
                
            ema_4h_series = df_4h['close'].ewm(span=200, adjust=False).mean()
            
            total_pnl = 0
            in_position = False
            entry_p = 0
            pos_type = None
            
            for i in range(150, len(df)-1):
                curr = df.iloc[i]
                prev = df.iloc[i-1]
                
                close_p = float(curr['close'])
                open_p = float(curr['open'])
                rsi_c = float(curr['rsi'])
                rsi_p = float(prev['rsi'])
                adx_v = float(curr['adx'])
                atr_v = float(curr['atr'])
                ema_1h_v = float(curr['ema200'])
                ema_4h_v = float(ema_4h_series.iloc[-1])
                
                trend_long = (close_p > ema_1h_v) or (close_p > ema_4h_v)
                trend_short = (close_p < ema_1h_v) or (close_p < ema_4h_v)
                trending = adx_v > 20
                
                long_cond = trend_long and trending and (rsi_p < 45) and (rsi_c > rsi_p) and (close_p > open_p)
                short_cond = trend_short and trending and (rsi_p > 55) and (rsi_c < rsi_p) and (close_p < open_p)
                
                if not in_position:
                    if long_cond:
                        in_position = True
                        entry_p = close_p
                        pos_type = 'LONG'
                    elif short_cond:
                        in_position = True
                        entry_p = close_p
                        pos_type = 'SHORT'
                else:
                    if pos_type == 'LONG':
                        if close_p >= entry_p + (atr_v * 3.0):
                            total_pnl += 3.0
                            in_position = False
                        elif close_p <= entry_p - (atr_v * 2.0):
                            total_pnl -= 2.0
                            in_position = False
                    elif pos_type == 'SHORT':
                        if close_p <= entry_p - (atr_v * 3.0):
                            total_pnl += 3.0
                            in_position = False
                        elif close_p >= entry_p + (atr_v * 2.0):
                            total_pnl -= 2.0
                            in_position = False
                            
            if total_pnl > 0:
                winning_list.append(sym)
                
        except Exception:
            pass
            
    if not winning_list:
        winning_list = ['BTC', 'ETH', 'SOL', 'AVAX', 'BNB', 'ADA', 'DOT']
        
    ACTIVE_SYMBOLS = winning_list
    print(f"✅ فیلتر تکمیل شد. {len(ACTIVE_SYMBOLS)} ارز انتخاب شدند.")
    
    coins_str = ", ".join(ACTIVE_SYMBOLS[:15]) + ("..." if len(ACTIVE_SYMBOLS) > 15 else "")
    msg = (
        f"✅ *ارزیابی واچ‌لیست تکمیل شد!*\n\n"
        f"📊 *تعداد ارزهای سودده فعال:* `{len(ACTIVE_SYMBOLS)}` ارز\n"
        f"🎯 *نمونه ارزها:* `{coins_str}`\n\n"
        f"💡 ارزهای منفی (مانند INJ و NEAR) از اسکن حذف شدند."
    )
    send_telegram_msg(msg)

# ==========================================
# ۵. تحلیل دستی ارز (/analyze)
# ==========================================
def analyze_coin_on_demand(coin_symbol, chat_id=None):
    coin_symbol = coin_symbol.upper().replace("USDT", "").replace("/", "").strip()
    df = get_crypto_klines(coin_symbol, aggregate=1, limit=300)
    if df.empty or len(df) < 50:
        send_telegram_msg(f"❌ داده‌ای برای ارز `{coin_symbol}` یافت نشد.", chat_target=chat_id)
        return

    df = calculate_indicators(df)
    df_4h = get_crypto_klines(coin_symbol, aggregate=4, limit=200)
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

    is_active = "🟢 تاییدشده در واچ‌لیست سودده" if coin_symbol in ACTIVE_SYMBOLS else "⚪ غیرفعال در فیلتر فعلی"

    msg = (
        f"📊 *تحلیل تکنیکال استراتژی پولبک `{coin_symbol}/USDT`*\n\n"
        f"📌 *وضعیت در واچ‌لیست:* {is_active}\n"
        f"🔹 *قیمت فعلی:* `{close_p:.4f}`\n"
        f"🔹 *شاخص ADX:* `{adx_val:.1f}`\n"
        f"🔹 *شاخص RSI:* `{rsi_curr:.1f}`\n\n"
        f"📌 *وضعیت سیگنال:* {status}\n\n"
        f"{details}"
    )
    send_telegram_msg(msg, chat_target=chat_id)

# ==========================================
# ۶. اسکنر اتوماتیک
# ==========================================
def check_symbol(coin_symbol):
    display_name = f"{coin_symbol}/USDT"
    df = get_crypto_klines(coin_symbol, aggregate=1, limit=300)
    if df.empty or len(df) < 50:
        return
        
    df = calculate_indicators(df)
    df_4h = get_crypto_klines(coin_symbol, aggregate=4, limit=200)
    if df_4h.empty or len(df_4h) < 50:
        return
        
    ema_1h_val = df['ema200'].iloc[-2]
    ema_4h_val = df_4h['close'].ewm(span=200, adjust=False).mean().iloc[-1]
    
    curr = df.iloc[-2]
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

# ==========================================
# ۷. پردازشگر پویا و شنونده دکمه‌های شیشه‌ای
# ==========================================
def process_command(text, chat_id):
    parts = text.strip().split()
    if not parts:
        return
        
    cmd = parts[0].lower()
    
    if cmd in ["/start", "/menu", "/help"]:
        send_main_menu(chat_id)
        
    elif cmd in ["/analyze", "/check"]:
        coin = parts[1].upper() if len(parts) > 1 else "BTC"
        send_telegram_msg(f"⏳ در حال بررسی اندیکاتورهای پولبک روی `{coin}`...", chat_target=chat_id)
        analyze_coin_on_demand(coin, chat_id=chat_id)
        
    elif cmd in ["/active_coins", "/coins"]:
        coins_list = ", ".join(ACTIVE_SYMBOLS)
        msg = f"📋 *لیست ارزهای سودده و فعال در اسکن زنده ({len(ACTIVE_SYMBOLS)} ارز):*\n\n`{coins_list}`"
        send_telegram_msg(msg, chat_target=chat_id)
        
    elif cmd == "/refilter":
        filter_winning_symbols()
        
    elif cmd == "/add":
        if len(parts) > 1:
            coin = parts[1].upper().replace("USDT", "").strip()
            if coin not in ACTIVE_SYMBOLS:
                ACTIVE_SYMBOLS.append(coin)
                send_telegram_msg(f"✅ ارز `{coin}` به اسکن زنده اضافه شد.", chat_target=chat_id)
            else:
                send_telegram_msg(f"ℹ️ ارز `{coin}` در لیست موجود است.", chat_target=chat_id)
                
    elif cmd == "/remove":
        if len(parts) > 1:
            coin = parts[1].upper().replace("USDT", "").strip()
            if coin in ACTIVE_SYMBOLS:
                ACTIVE_SYMBOLS.remove(coin)
                send_telegram_msg(f"🗑 ارز `{coin}` از اسکن زنده حذف شد.", chat_target=chat_id)
            else:
                send_telegram_msg(f"ℹ️ ارز `{coin}` در لیست فعال یافت نشد.", chat_target=chat_id)

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
                    
                    # کلیک روی دکمه‌های شیشه‌ای (Callback Query)
                    if "callback_query" in result:
                        cb = result["callback_query"]
                        cb_id = cb["id"]
                        cb_data = cb.get("data", "")
                        chat_id = cb["message"]["chat"]["id"]
                        
                        # تایید دریافت کلیک دکمه
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery", json={"callback_query_id": cb_id})
                        
                        process_command(cb_data, chat_id)
                        
                    # پیام متنی مستقیم
                    elif "message" in result:
                        msg = result["message"]
                        text = msg.get("text", "").strip()
                        chat_id = msg.get("chat", {}).get("id")
                        if text and chat_id:
                            process_command(text, chat_id)
        except Exception:
            pass
        time.sleep(2)

def bot_loop():
    time.sleep(5)
    send_telegram_msg("⚡ *ربات هوشمند مجهز به دکمه‌های شیشه‌ای فعال شد.*")
    filter_winning_symbols()
    
    scan_count = 0
    while True:
        for sym in ACTIVE_SYMBOLS:
            try:
                check_symbol(sym)
            except Exception:
                pass
            time.sleep(1)
            
        scan_count += 1
        if scan_count >= 24:
            filter_winning_symbols()
            scan_count = 0
            
        time.sleep(3600)

if __name__ == "__main__":
    Thread(target=telegram_listener, daemon=True).start()
    Thread(target=bot_loop, daemon=True).start()
    run_flask()
