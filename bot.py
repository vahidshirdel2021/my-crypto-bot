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
    return f"OK - Paper Trading Scalper (Leverage & Capital Configured) Active! Active Coins: {len(ACTIVE_SYMBOLS)}", 200

@app.route('/health')
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# ۱. تنظیمات سرمایه، اهرم و تلگرام
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8931433787:AAEdgjh8du4c-gLEF7DQA7H8xAzs6O0p7mw")
CHAT_ID = os.environ.get("CHAT_ID", "1878257830")

# ⚙️ تنظیمات متغیرهای سرمایه و اهرم (قابل تغییر)
INITIAL_BALANCE = 500.0     # میزان سرمایه اولیه مجازی (دلار)
PAPER_BALANCE = INITIAL_BALANCE
TRADE_AMOUNT_USDT = 50.0   # مارجین/سرمایه درگیر در هر معامله (دلار)
LEVERAGE = 10              # ضریب اهرم (Leverage) مثلا 10X

PAPER_POSITIONS = []
CLOSED_POSITIONS = []

COINEX_API_KEY = os.environ.get("COINEX_API_KEY", "D6A52010E5B846469B6EE3DB773B32B6")
COINEX_SECRET = os.environ.get("COINEX_SECRET", "527FB6BC384FC302453676431692A8620F9A3E0F6A3D5D15")

exchange = None
if COINEX_API_KEY and COINEX_SECRET:
    try:
        exchange = ccxt.coinex({
            'apiKey': COINEX_API_KEY,
            'secret': COINEX_SECRET,
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
        print("✅ اتصال به API صرافی CoinEx برقرار شد.")
    except Exception as e:
        print(f"⚠️ خطا در راه‌اندازی API: {e}")

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
                {"text": "⚡ اسکالپ BTC (5m)", "callback_data": "/analyze BTC"},
                {"text": "⚡ اسکالپ ETH (5m)", "callback_data": "/analyze ETH"},
                {"text": "⚡ اسکالپ SOL (5m)", "callback_data": "/analyze SOL"}
            ],
            [
                {"text": "📋 واچ‌لیست ۵ دقیقه‌ای", "callback_data": "/active_coins"},
                {"text": "📈 گزارش PnL و تنظیمات", "callback_data": "/pnl"}
            ]
        ]
    }
    msg = f"🎛 *پنل مدیریت اسکالپینگ (سرمایه: ${INITIAL_BALANCE:.0f} | اهرم: {LEVERAGE}X)*\n\nیک گزینه را انتخاب کنید:"
    send_telegram_msg(msg, chat_target=chat_id, reply_markup=keyboard)

# ==========================================
# ۲. دریافت داده‌ها و اندیکاتورها
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
# ۳. مدیریت پوزیشن کاغذی با اهرم
# ==========================================
def execute_paper_trade(symbol, side, price, sl, tp):
    for pos in PAPER_POSITIONS:
        if pos['symbol'] == symbol:
            return

    position_val = TRADE_AMOUNT_USDT * LEVERAGE
    trade = {
        "id": len(CLOSED_POSITIONS) + len(PAPER_POSITIONS) + 1,
        "symbol": symbol,
        "side": side,
        "entry_price": price,
        "sl": sl,
        "tp": tp,
        "margin": TRADE_AMOUNT_USDT,
        "position_val": position_val,
        "leverage": LEVERAGE,
        "open_time": time.strftime("%H:%M:%S")
    }
    PAPER_POSITIONS.append(trade)
    
    msg = (
        f"📝 *معامله کاغذی با اهرم {LEVERAGE}X ثبت شد*\n\n"
        f"🔹 *نماد:* `{symbol}/USDT` | *جهت:* `{side}`\n"
        f"🔹 *قیمت ورود:* `{price:.4f}`\n"
        f"🎯 *حد سود (TP):* `{tp:.4f}` | 🛑 *حد زیان (SL):* `{sl:.4f}`\n"
        f"💵 *مارجین (سرمایه):* `${TRADE_AMOUNT_USDT:.0f} USDT`\n"
        f"⚡ *ارزش پوزیشن (با اهرم):* `${position_val:.0f} USDT`"
    )
    send_telegram_msg(msg)

def update_open_positions():
    global PAPER_BALANCE
    if not PAPER_POSITIONS:
        return

    for pos in PAPER_POSITIONS[:]:
        symbol = pos['symbol']
        df = get_crypto_klines(symbol, interval_type="5min", limit=5)
        if df.empty:
            continue
            
        high_price = float(df.iloc[-1]['high'])
        low_price = float(df.iloc[-1]['low'])
        
        side = pos['side']
        entry = pos['entry_price']
        tp = pos['tp']
        sl = pos['sl']
        margin = pos['margin']
        lev = pos['leverage']
        
        closed = False
        raw_pnl_pct = 0.0
        pnl_usdt = 0.0
        exit_reason = ""

        if "BUY" in side:
            if high_price >= tp:
                raw_pnl_pct = ((tp - entry) / entry) * 100
                closed = True
                exit_reason = "🎯 حد سود (TP)"
            elif low_price <= sl:
                raw_pnl_pct = ((sl - entry) / entry) * 100
                closed = True
                exit_reason = "🛑 حد زیان (SL)"

        elif "SELL" in side:
            if low_price <= tp:
                raw_pnl_pct = ((entry - tp) / entry) * 100
                closed = True
                exit_reason = "🎯 حد سود (TP)"
            elif high_price >= sl:
                raw_pnl_pct = ((entry - sl) / entry) * 100
                closed = True
                exit_reason = "🛑 حد زیان (SL)"

        if closed:
            leveraged_pnl_pct = raw_pnl_pct * lev
            pnl_usdt = (margin * leveraged_pnl_pct) / 100
            
            PAPER_BALANCE += pnl_usdt
            pos['pnl_pct'] = leveraged_pnl_pct
            pos['pnl_usdt'] = pnl_usdt
            pos['exit_reason'] = exit_reason
            pos['close_time'] = time.strftime("%H:%M:%S")
            
            CLOSED_POSITIONS.append(pos)
            PAPER_POSITIONS.remove(pos)
            
            pnl_icon = "🟢" if pnl_usdt >= 0 else "🔴"
            msg = (
                f"{pnl_icon} *پوزیشن کاغذی بسته شد ({exit_reason})*\n\n"
                f"🔹 *نماد:* `{symbol}/USDT` | *جهت:* `{side}` ({lev}X)\n"
                f"📊 *سود/زیان مارجین:* `{leveraged_pnl_pct:+.2f}%` (`{pnl_usdt:+.2f} USDT`)\n"
                f"💰 *موجودی کل جدید:* `{PAPER_BALANCE:.2f} USDT`"
            )
            send_telegram_msg(msg)

# ==========================================
# ۴. اسکن زنده اسکالپینگ ۵ دقیقه‌ای
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
            execute_paper_trade(coin_symbol, 'BUY (Long)', close_p, sl, tp)
            
        elif pullback_short:
            sl = close_p + (atr_val * 1.2)
            tp = close_p - (atr_val * 1.8)
            execute_paper_trade(coin_symbol, 'SELL (Short)', close_p, sl, tp)
    except Exception as e:
        print(f"خطا در اسکن {coin_symbol}: {e}")

def get_pnl_report():
    total_closed = len(CLOSED_POSITIONS)
    wins = sum(1 for p in CLOSED_POSITIONS if p['pnl_usdt'] > 0)
    losses = sum(1 for p in CLOSED_POSITIONS if p['pnl_usdt'] < 0)
    win_rate = (wins / total_closed * 100) if total_closed > 0 else 0.0
    
    total_pnl_usdt = PAPER_BALANCE - INITIAL_BALANCE
    total_pnl_pct = (total_pnl_usdt / INITIAL_BALANCE) * 100

    report = (
        f"📊 *گزارش PnL (با احتساب اهرم {LEVERAGE}X)*\n\n"
        f"💵 *سرمایه اولیه:* `${INITIAL_BALANCE:.2f} USDT`\n"
        f"💰 *موجودی فعلی:* `${PAPER_BALANCE:.2f} USDT`\n"
        f"💵 *مارجین هر معامله:* `${TRADE_AMOUNT_USDT:.0f} USDT`\n"
        f"⚡ *اهرم معاملات:* `{LEVERAGE}X` (ارزش پوزیشن: `${TRADE_AMOUNT_USDT * LEVERAGE:.0f}`)\n"
        f"📈 *سود/زیان کل:* `{total_pnl_pct:+.2f}%` (`{total_pnl_usdt:+.2f} USDT`)\n\n"
        f"📉 *تعداد کل معاملات:* `{total_closed}` | 🟢 برد: `{wins}` | 🔴 باخت: `{losses}`\n"
        f"🎯 *وین‌ریت (Win Rate):* `{win_rate:.1f}%`"
    )
    return report

def process_command(text, chat_id):
    parts = text.strip().split()
    if not parts: return
    cmd = parts[0].lower()
    
    if cmd in ["/start", "/menu", "/help"]:
        send_main_menu(chat_id)
    elif cmd in ["/active_coins", "/coins"]:
        send_telegram_msg(f"📋 *تعداد ارزهای فعال:* `{len(ACTIVE_SYMBOLS)}`", chat_target=chat_id)
    elif cmd in ["/pnl", "/report", "/balance", "/bal"]:
        send_telegram_msg(get_pnl_report(), chat_target=chat_id)

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
    send_telegram_msg(f"⚙️ *حساب کاغذی با سرمایه ${INITIAL_BALANCE:.0f} و اهرم {LEVERAGE}X راه‌اندازی شد.*")
    while True:
        try:
            update_open_positions()
        except Exception as e:
            print(f"خطا در آپدیت پوزیشن‌ها: {e}")
            
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
