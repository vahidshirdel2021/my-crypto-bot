import os
import time
import requests
import ccxt
import pandas as pd
from threading import Thread
from flask import Flask

# ==========================================
# ۰. وب‌سرور Flask برای Render
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return f"OK - CoinEx Paper Trading Bot Active! Active Coins: {len(ACTIVE_SYMBOLS)}", 200

@app.route('/health')
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# ۱. تنظیمات تلگرام و سیستم Paper Trading
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8931433787:AAEdgjh8du4c-gLEF7DQA7H8xAzs6O0p7mw")
CHAT_ID = os.environ.get("CHAT_ID", "1878257830")

# تنظیمات معامله کاغذی (Paper Trading)
PAPER_TRADING = True
paper_balance = 1000.0  # موجودی اولیه مجازی دلار
open_positions = []      # لیست پوزیشن‌های باز مجازی

ALL_SYMBOLS = [
    'BTC', 'ETH', 'SOL', 'AVAX', 'BNB', 'ADA', 'DOT', 'DOGE', 'LINK', 'XRP',
    'NEAR', 'INJ', 'TRX', 'MATIC', 'FTM', 'SAND', 'MANA', 'ATOM', 'LTC', 'BCH',
    'APT', 'SUI', 'OP', 'ARB', 'RNDR', 'FET', 'PEPE', 'SHIB', 'GALA', 'DYDX'
]

ACTIVE_SYMBOLS = ALL_SYMBOLS.copy()

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

def send_main_menu(chat_id):
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "📋 واچ‌لیست ۵ دقیقه‌ای", "callback_data": "/active_coins"},
                {"text": "📊 پوزیشن‌های باز کاغذی", "callback_data": "/positions"}
            ],
            [
                {"text": "💼 موجودی حساب کاغذی", "callback_data": "/balance"}
            ]
        ]
    }
    msg = (
        "🎛 *پنل ربات اسکالپینگ (حالت Paper Trading)*\n\n"
        f"💵 *موجودی مجازی فعلی:* `${paper_balance:.2f} USDT`\n"
        "یکی از گزینه‌ها را انتخاب کنید:"
    )
    send_telegram_msg(msg, chat_target=chat_id, reply_markup=keyboard)

# ==========================================
# ۲. دریافت داده‌های بازار
# ==========================================
def get_crypto_klines(coin_symbol, interval_type="5min", limit=200):
    coin_symbol = coin_symbol.upper().replace("USDT", "").replace("/", "").strip()
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        url_kucoin = f"https://api.kucoin.com/api/v1/market/candles?symbol={coin_symbol}-USDT&type={interval_type}"
        res = requests.get(url_kucoin, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if data.get("code") == "200000" and data.get("data"):
                raw = data["data"]
                df = pd.DataFrame(raw, columns=['timestamp', 'open', 'close', 'high', 'low', 'volume', 'turnover'])
                df = df.iloc[::-1].reset_index(drop=True)
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = df[col].astype(float)
                if not df.empty and len(df) > 30:
                    return df
    except Exception:
        pass
    return pd.DataFrame()

def calculate_indicators(df):
    try:
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
    except Exception as e:
        print(f"خطا در محاسبه اندیکاتورها: {e}")
    
    return df

# ==========================================
# ۳. ثبت و مدیریت معاملات کاغذی (Paper Trading)
# ==========================================
def open_paper_position(symbol, side, entry_price, sl_price, tp_price):
    global paper_balance, open_positions
    
    # بررسی جلوگیری از پوزیشن تکراری
    for pos in open_positions:
        if pos['symbol'] == symbol:
            return
            
    margin = 50.0  # مارجین اختصاصی هر معامله (۵۰ دلار مجازی)
    leverage = 10  # اهرم ۱۰ برابر
    position_size = (margin * leverage) / entry_price
    
    pos = {
        'symbol': symbol,
        'side': side,
        'entry_price': entry_price,
        'sl': sl_price,
        'tp': tp_price,
        'margin': margin,
        'size': position_size,
        'timestamp': time.time()
    }
    open_positions.append(pos)
    
    msg = (
        f"📝 *معامله کاغذی باز شد (Paper Trade)*\n\n"
        f"🔹 *ارز:* `{symbol}/USDT`\n"
        f"🔹 *جهت:* `{side}`\n"
        f"🔹 *قیمت ورود:* `{entry_price:.4f}`\n"
        f"🎯 *حد سود (TP):* `{tp_price:.4f}`\n"
        f"🛑 *حد زیان (SL):* `{sl_price:.4f}`\n"
        f"💰 *حجم معامله:* `${margin * leverage:.2f}` (اهرم ۱۰X)"
    )
    send_telegram_msg(msg)

def update_paper_positions():
    global paper_balance, open_positions
    if not open_positions:
        return

    for pos in open_positions[:]:
        df = get_crypto_klines(pos['symbol'], interval_type="5min", limit=5)
        if df.empty:
            continue
            
        curr_price = float(df.iloc[-1]['close'])
        high_price = float(df.iloc[-1]['high'])
        low_price = float(df.iloc[-1]['low'])
        
        hit_tp = False
        hit_sl = False
        pnl = 0.0
        
        if pos['side'] == 'BUY':
            if high_price >= pos['tp']:
                hit_tp = True
                pnl = (pos['tp'] - pos['entry_price']) * pos['size']
            elif low_price <= pos['sl']:
                hit_sl = True
                pnl = (pos['sl'] - pos['entry_price']) * pos['size']
        elif pos['side'] == 'SELL':
            if low_price <= pos['tp']:
                hit_tp = True
                pnl = (pos['entry_price'] - pos['tp']) * pos['size']
            elif high_price >= pos['sl']:
                hit_sl = True
                pnl = (pos['entry_price'] - pos['sl']) * pos['size']
                
        if hit_tp or hit_sl:
            paper_balance += pnl
            status = "🎯 *برخورد با حد سود (TP)*" if hit_tp else "🛑 *برخورد با حد زیان (SL)*"
            pnl_sign = "+" if pnl > 0 else ""
            
            msg = (
                f"{status}\n\n"
                f"🔹 *ارز:* `{pos['symbol']}/USDT` ({pos['side']})\n"
                f"🔹 *قیمت ورود:* `{pos['entry_price']:.4f}`\n"
                f"🔹 *قیمت خروج:* `{curr_price:.4f}`\n"
                f"💵 *سود/زیان:* `{pnl_sign}{pnl:.2f} USDT`\n"
                f"💼 *موجودی کل جدید:* `${paper_balance:.2f} USDT`"
            )
            send_telegram_msg(msg)
            open_positions.remove(pos)

# ==========================================
# ۴. اسکن زنده (تایم‌فریم ۵ دقیقه)
# ==========================================
def check_symbol(coin_symbol):
    try:
        df_5m = get_crypto_klines(coin_symbol, interval_type="5min", limit=200)
        if df_5m.empty or len(df_5m) < 50:
            return
            
        df_5m = calculate_indicators(df_5m)
        curr, prev = df_5m.iloc[-2], df_5m.iloc[-3]
        
        close_p, open_p = float(curr['close']), float(curr['open'])
        rsi_curr, rsi_prev = float(curr['rsi']), float(prev['rsi'])
        adx_val, atr_val = float(curr['adx']), float(curr['atr'])
        ema_val = float(curr['ema200'])
        
        trend_long = close_p > ema_val and adx_val > 14
        trend_short = close_p < ema_val and adx_val > 14
        
        pullback_long = trend_long and (rsi_prev < 50) and (rsi_curr > rsi_prev) and (close_p > open_p)
        pullback_short = trend_short and (rsi_prev > 50) and (rsi_curr < rsi_prev) and (close_p < open_p)
        
        if pullback_long:
            sl = close_p - (atr_val * 1.2)
            tp = close_p + (atr_val * 1.8)
            open_paper_position(coin_symbol, 'BUY', close_p, sl, tp)
            
        elif pullback_short:
            sl = close_p + (atr_val * 1.2)
            tp = close_p - (atr_val * 1.8)
            open_paper_position(coin_symbol, 'SELL', close_p, sl, tp)
    except Exception as e:
        print(f"خطا در اسکن {coin_symbol}: {e}")

def process_command(text, chat_id):
    parts = text.strip().split()
    if not parts: return
    cmd = parts[0].lower()
    
    if cmd in ["/start", "/menu", "/help"]:
        send_main_menu(chat_id)
    elif cmd in ["/active_coins", "/coins"]:
        send_telegram_msg(f"📋 *تعداد ارزهای فعال در اسکن:* `{len(ACTIVE_SYMBOLS)}`", chat_target=chat_id)
    elif cmd in ["/balance", "/bal"]:
        send_telegram_msg(f"💼 *موجودی حساب کاغذی (Paper USDT):* `${paper_balance:.2f} USDT`", chat_target=chat_id)
    elif cmd in ["/positions", "/pos"]:
        if not open_positions:
            send_telegram_msg("📊 *در حال حاضر هیچ پوزیشن کاغذی باز نیست.*", chat_target=chat_id)
        else:
            msg = "📊 *پوزیشن‌های کاغذی فعال:*\n\n"
            for p in open_positions:
                msg += f"🔹 `{p['symbol']}` ({p['side']}) | ورود: `{p['entry_price']:.4f}` | TP: `{p['tp']:.4f}` | SL: `{p['sl']:.4f}`\n"
            send_telegram_msg(msg, chat_target=chat_id)

def telegram_listener():
    last_update_id = None
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    while True:
        try:
            res = requests.get(url, params={"timeout": 10, "offset": last_update_id}, timeout=12)
            if res.status_code == 200:
                data = res.json()
                for result in data.get("result", []):
                    last_update_id = result["update_id"] + 1
                    if "callback_query" in result:
                        cb = result["callback_query"]
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery", json={"callback_query_id": cb["id"]})
                        process_command(cb.get("data", ""), cb["message"]["chat"]["id"])
                    elif "message" in result:
                        msg = result["message"]
                        process_command(msg.get("text", ""), msg["chat"]["id"])
        except Exception:
            pass
        time.sleep(2)

def bot_loop():
    time.sleep(5)
    send_telegram_msg("🚀 *سیستم معامله کاغذی (Paper Trading) با ۱,۰۰۰ دلار موجودی مجازی فعال شد.*")
    while True:
        update_paper_positions()  # بررسی معاملات باز قبلی
        for sym in ACTIVE_SYMBOLS:
            try:
                check_symbol(sym)
            except Exception:
                pass
            time.sleep(0.3)
        time.sleep(30)

if __name__ == "__main__":
    Thread(target=telegram_listener, daemon=True).start()
    Thread(target=bot_loop, daemon=True).start()
    run_flask()
