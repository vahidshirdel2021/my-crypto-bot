import os
import json
import time
import requests
import ccxt
import pandas as pd
from threading import Thread
from flask import Flask
from strategy import calculate_indicators, get_signal, get_strategy_params

# ==========================================
# ۰. بارگذاری تنظیمات از config.json
# ==========================================
CONFIG_FILE = "config.json"

def load_config():
    default_config = {
        "trading_mode": "PAPER",
        "initial_balance": 1000.0,
        "trade_amount_usdt": 50.0,
        "leverage": 10,
        "max_open_positions": 3,
        "timeframe": "5min",
        "max_daily_loss_pct": 5.0
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return {**default_config, **json.load(f)}
        except Exception:
            pass
    return default_config

config = load_config()

# ==========================================
# ۱. وب‌سرور Flask برای Render
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    status_str = "ACTIVE" if IS_BOT_ACTIVE else "PAUSED"
    return f"OK - Mode: {config['trading_mode']} | Status: {status_str} | TF: {config['timeframe']}", 200

@app.route('/health')
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# ۲. متغیرهای اجرایی
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8931433787:AAEdgjh8du4c-gLEF7DQA7H8xAzs6O0p7mw")
CHAT_ID = os.environ.get("CHAT_ID", "1878257830")

IS_BOT_ACTIVE = False
TRADING_MODE = config["trading_mode"]
INITIAL_BALANCE = config["initial_balance"]
PAPER_BALANCE = INITIAL_BALANCE
DAILY_START_BALANCE = INITIAL_BALANCE
TRADE_AMOUNT_USDT = config["trade_amount_usdt"]
LEVERAGE = config["leverage"]
MAX_OPEN_POSITIONS = config["max_open_positions"]
TIMEFRAME = config["timeframe"]

PAPER_POSITIONS = []
CLOSED_POSITIONS = []

COINEX_API_KEY = os.environ.get("COINEX_API_KEY", "")
COINEX_SECRET = os.environ.get("COINEX_SECRET", "")

exchange = None
if COINEX_API_KEY and COINEX_SECRET:
    try:
        exchange = ccxt.coinex({
            'apiKey': COINEX_API_KEY,
            'secret': COINEX_SECRET,
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
        print("✅ اتصال به صرافی CoinEx برقرار شد.")
    except Exception as e:
        print(f"⚠️ خطا در راه‌اندازی API: {e}")

ALL_SYMBOLS = [
    'BTC', 'ETH', 'YFI', 'MKR', 'BCH', 'COMP', 'KSM', 'LTC', 'AAVE', 'ZEC',
    'EGLD', 'BNB', 'DASH', 'FIL', 'ZEN', 'WAVES', 'SOL', 'UNI', 'DOT', 'BAL',
    'LIT', 'BAND', 'UNFI', 'SUSHI', 'SNX', 'AVAX', 'ATOM', 'TRB', 'ETC', 'NEO',
    'SRM', 'SFP', 'BEL', 'IOTA', 'AXS', 'RLC', 'SXP', 'GRT', 'RUNE', 'ONT',
    'KAVA', 'OCEAN', '1INCH', 'REN', 'KNC', 'ALPHA', 'TOMO', 'HNT', 'ENJ', 'ICX',
    'CRV', 'NEAR', 'CTK', 'LUNA', 'EOS', 'THETA', 'QTUM', 'MANA', 'OMG', 'SAND',
    'ADA', 'XEM', 'FTM', 'RVN', 'MTL', 'SC', 'STORJ', 'ZIL', 'SLP', 'BTS',
    'XRP', 'BLZ', 'FET', 'ALGO', 'DODO', 'CHR', 'AKRO', 'BZRX', 'CVC', 'STMX',
    'CELR', 'HBAR', 'SKL', 'RSR', 'REEF', 'CHZ', 'LINK', 'ALICE', 'ZRX', 'COTI',
    'ONE', 'MATIC', 'XTZ', 'NKN', 'ANKR', 'LINA', 'HOT', 'LRC', 'DOGE', 'DENT',
    'DGB', 'WIN', 'IOST', 'TRX', 'BTT', 'FLM', 'BAT', 'VET', 'SHIB', 'ARPA',
    'AR', 'C98', 'DYDX', 'TLM', 'GALA', 'AUDIO', 'MASK', 'BAKE', 'KEEP', 'OGN',
    'RAY', 'KLAY', 'ATA', 'NU', 'GTC', 'CELO', 'YFII', 'CTSI'
]
ACTIVE_SYMBOLS = ALL_SYMBOLS.copy()

def send_telegram_msg(message, chat_target=None, reply_markup=None, message_id=None):
    target = chat_target or CHAT_ID
    if message_id:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
        payload = {"chat_id": target, "message_id": message_id, "text": message, "parse_mode": "Markdown"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            res = requests.post(url, json=payload, timeout=10)
            if res.status_code == 200:
                return True
        except Exception:
            pass

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": target, "text": message, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.status_code == 200
    except Exception:
        return False

def send_persistent_keyboard(chat_id):
    keyboard = {
        "keyboard": [
            [{"text": "منوی اصلی"}, {"text": "گزارش عملکرد"}]
        ],
        "resize_keyboard": True,
        "is_persistent": True
    }
    send_telegram_msg("سیستم مدیریت آماده است.", chat_target=chat_id, reply_markup=keyboard)

# ==========================================
# ۳. منوهای ویزارد و مدیریت
# ==========================================
def send_margin_menu(chat_id, message_id=None):
    keyboard = {
        "inline_keyboard": [
            [{"text": "10 USDT", "callback_data": "/set_margin_10"}, {"text": "25 USDT", "callback_data": "/set_margin_25"}],
            [{"text": "50 USDT", "callback_data": "/set_margin_50"}, {"text": "100 USDT", "callback_data": "/set_margin_100"}]
        ]
    }
    send_telegram_msg("⚙️ مقدار مارجین (سرمایه درگیر) جدید در هر معامله:", chat_target=chat_id, reply_markup=keyboard, message_id=message_id)

def send_leverage_menu(chat_id, message_id=None):
    keyboard = {
        "inline_keyboard": [
            [{"text": "3X", "callback_data": "/set_lev_3"}, {"text": "5X", "callback_data": "/set_lev_5"}, {"text": "10X", "callback_data": "/set_lev_10"}]
        ]
    }
    send_telegram_msg("⚙️ ضریب اهرم (Leverage) جدید را انتخاب کنید:", chat_target=chat_id, reply_markup=keyboard, message_id=message_id)

def send_max_positions_menu(chat_id, message_id=None):
    keyboard = {
        "inline_keyboard": [
            [{"text": "2 معامله", "callback_data": "/set_max_2"}, {"text": "3 معامله", "callback_data": "/set_max_3"}, {"text": "5 معامله", "callback_data": "/set_max_5"}],
            [{"text": "10 معامله", "callback_data": "/set_max_10"}, {"text": "بدون محدودیت", "callback_data": "/set_max_0"}]
        ]
    }
    send_telegram_msg("⚙️ حداکثر تعداد پوزیشن‌های هم‌زمان:", chat_target=chat_id, reply_markup=keyboard, message_id=message_id)

def send_timeframe_menu(chat_id, message_id=None):
    keyboard = {
        "inline_keyboard": [
            [{"text": "5 دقیقه", "callback_data": "/set_tf_5m"}, {"text": "15 دقیقه", "callback_data": "/set_tf_15m"}, {"text": "1 ساعت", "callback_data": "/set_tf_1h"}]
        ]
    }
    send_telegram_msg("⚙️ انتخاب تایم‌فریم معاملاتی جدید:", chat_target=chat_id, reply_markup=keyboard, message_id=message_id)

def send_main_menu(chat_id, message_id=None):
    send_persistent_keyboard(chat_id)
    tf_display = "5m" if TIMEFRAME == "5min" else ("15m" if TIMEFRAME == "15min" else "1h")
    status_str = "فعال (در حال اسکن)" if IS_BOT_ACTIVE else "متوقف شده"
    mode_str = "معامله واقعی" if TRADING_MODE == "REAL" else "معامله کاغذی"
    max_pos = f"{MAX_OPEN_POSITIONS}" if MAX_OPEN_POSITIONS > 0 else "نامحدود"
    toggle_text = "توقف/شروع اسکن" if IS_BOT_ACTIVE else "توقف/شروع اسکن"
    active_btn_text = "🟢 روشن کردن اسکن" if not IS_BOT_ACTIVE else "🔴 متوقف کردن اسکن"
    
    keyboard = {
        "inline_keyboard": [
            [
                {"text": active_btn_text, "callback_data": "/toggle_active"},
                {"text": "🔍 تحلیل تک ارز", "callback_data": "/analyze_single"}
            ],
            [
                {"text": "📋 مدیریت واچ‌لیست", "callback_data": "/manage_watchlist"},
                {"text": "⚙️ تنظیمات معاملاتی", "callback_data": "/wizard_start"}
            ],
            [
                {"text": "🔄 پوزیشن‌های باز", "callback_data": "/open_positions"},
                {"text": "📈 گزارش عملکرد", "callback_data": "/performance"}
            ]
        ]
    }
    
    p = get_strategy_params(TIMEFRAME)
    msg = (
        f"📊 *پنل مدیریت پیشرفته ربات معامله‌گر*\n\n"
        f"• حالت: `{mode_str}`\n"
        f"• وضعیت: `{status_str}`\n"
        f"• موجودی حساب: `${PAPER_BALANCE:.2f} USDT`\n"
        f"• مارجین هر معامله: `${TRADE_AMOUNT_USDT:.0f} USDT`\n"
        f"• اهرم: `{LEVERAGE}X` | حداکثر پوزیشن: `{max_pos}`\n"
        f"• تایم‌فریم: `{tf_display}` (ADX > {p['adx']})\n"
        f"• تعداد ارزهای واچ‌لیست: `{len(ACTIVE_SYMBOLS)}`"
    )
    send_telegram_msg(msg, chat_target=chat_id, reply_markup=keyboard, message_id=message_id)

def get_crypto_klines(coin_symbol, interval_type="5min", limit=200):
    coin_symbol = coin_symbol.upper().replace("USDT", "").replace("/", "").strip()
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        url = f"https://api.kucoin.com/api/v1/market/candles?symbol={coin_symbol}-USDT&type={interval_type}"
        res = requests.get(url, headers=headers, timeout=5)
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

def execute_trade(symbol, side, price, sl, tp):
    global IS_BOT_ACTIVE
    if not IS_BOT_ACTIVE: return
    if MAX_OPEN_POSITIONS > 0 and len(PAPER_POSITIONS) >= MAX_OPEN_POSITIONS: return
    for pos in PAPER_POSITIONS:
        if pos['symbol'] == symbol: return

    margin = TRADE_AMOUNT_USDT
    if PAPER_BALANCE < margin: return

    trade = {
        "symbol": symbol, "side": side, "entry_price": price,
        "sl": sl, "tp": tp, "margin": margin,
        "leverage": LEVERAGE, "timeframe": TIMEFRAME,
        "close_timestamp": None, "pnl_usdt": 0.0
    }
    PAPER_POSITIONS.append(trade)
    send_telegram_msg(f"📝 *معامله جدید ({side})*\n• نماد: `{symbol}`\n• ورود: `{price:.4f}`\n• TP: `{tp:.4f}` | SL: `{sl:.4f}`")

def update_open_positions():
    global PAPER_BALANCE, IS_BOT_ACTIVE
    if not PAPER_POSITIONS: return

    for pos in PAPER_POSITIONS[:]:
        df = get_crypto_klines(pos['symbol'], interval_type=pos.get('timeframe', TIMEFRAME), limit=5)
        if df.empty: continue
        high, low = float(df.iloc[-1]['high']), float(df.iloc[-1]['low'])
        
        closed, raw_pnl = False, 0.0
        if "BUY" in pos['side']:
            if high >= pos['tp']: closed, raw_pnl = True, ((pos['tp'] - pos['entry_price']) / pos['entry_price']) * 100
            elif low <= pos['sl']: closed, raw_pnl = True, ((pos['sl'] - pos['entry_price']) / pos['entry_price']) * 100
        else:
            if low <= pos['tp']: closed, raw_pnl = True, ((pos['entry_price'] - pos['tp']) / pos['entry_price']) * 100
            elif high >= pos['sl']: closed, raw_pnl = True, ((pos['entry_price'] - high) / pos['entry_price']) * 100

        if closed:
            pnl_usdt = (pos['margin'] * (raw_pnl * pos['leverage'])) / 100
            PAPER_BALANCE += pnl_usdt
            pos['pnl_usdt'] = pnl_usdt
            pos['close_timestamp'] = time.time()
            CLOSED_POSITIONS.append(pos)
            PAPER_POSITIONS.remove(pos)
            send_telegram_msg(f"📌 *پوزیشن بسته شد.*\n• نماد: `{pos['symbol']}`\n• سود/زیان: `{pnl_usdt:+.2f} USDT`")

            if (DAILY_START_BALANCE - PAPER_BALANCE) / DAILY_START_BALANCE * 100 >= config["max_daily_loss_pct"]:
                IS_BOT_ACTIVE = False
                send_telegram_msg("🛑 سقف زیان روزانه لمس شد. ربات متوقف گردید.")

def check_symbol(coin_symbol):
    if not IS_BOT_ACTIVE: return
    try:
        df_5m = get_crypto_klines(coin_symbol, interval_type="5min", limit=200)
        if df_5m.empty or len(df_5m) < 50: return
        df_5m = calculate_indicators(df_5m)
        
        df_1h = get_crypto_klines(coin_symbol, interval_type="1hour", limit=100)
        if not df_1h.empty and len(df_1h) > 30:
            df_1h = calculate_indicators(df_1h)
        else:
            df_1h = None
        
        signal = get_signal(df_5m, df_1h)
        if not signal: return
        
        curr = df_5m.iloc[-2]
        close_p = float(curr['close'])
        atr = float(curr['atr'])
        p = get_strategy_params(TIMEFRAME)
        
        if signal == "BUY":
            execute_trade(coin_symbol, 'BUY (Long)', close_p, close_p - (atr * p["sl"]), close_p + (atr * p["tp"]))
        elif signal == "SELL":
            execute_trade(coin_symbol, 'SELL (Short)', close_p, close_p + (atr * p["sl"]), close_p - (atr * p["tp"]))
    except Exception:
        pass

def generate_report(hours=None, title=""):
    now = time.time()
    trades = [p for p in CLOSED_POSITIONS if p.get('close_timestamp', now) >= (now - hours * 3600)] if hours else CLOSED_POSITIONS
    wins = [p for p in trades if p.get('pnl_usdt', 0) > 0]
    losses = [p for p in trades if p.get('pnl_usdt', 0) < 0]
    net = sum(p.get('pnl_usdt', 0) for p in trades)
    return f"📌 *[{title}]*\n• تعداد معامله: `{len(trades)}` | مثبت: `{len(wins)}` | منفی: `{len(losses)}`\n• سود/زیان: `{net:+.2f} USDT`"

def send_full_performance(chat_id):
    send_telegram_msg("📈 *گزارش جامع عملکرد ربات:*", chat_target=chat_id)
    send_telegram_msg(generate_report(None, "کل دوره"), chat_target=chat_id)
    send_telegram_msg(generate_report(4, "۴ ساعت گذشته"), chat_target=chat_id)
    send_telegram_msg(generate_report(12, "۱۲ ساعت گذشته"), chat_target=chat_id)
    send_telegram_msg(generate_report(24, "روزانه (۲۴ ساعت)"), chat_target=chat_id)
    send_telegram_msg(generate_report(720, "ماهانه (۳۰ روز)"), chat_target=chat_id)

def process_command(data, chat_id, message_id=None):
    global IS_BOT_ACTIVE, TRADING_MODE, INITIAL_BALANCE, PAPER_BALANCE, DAILY_START_BALANCE, TRADE_AMOUNT_USDT, LEVERAGE, MAX_OPEN_POSITIONS, TIMEFRAME
    
    cmd = data.strip().lower()
    
    if cmd in ["/start", "/menu", "/main_menu", "menu", "منوی اصلی"]:
        send_main_menu(chat_id, message_id=message_id)
        
    elif cmd in ["/wizard_start", "تنظیمات مجدد"]:
        if IS_BOT_ACTIVE:
            send_telegram_msg("⚠️ ابتدا اسکن زنده را متوقف کنید، سپس تنظیمات را تغییر دهید.", chat_target=chat_id)
        else:
            # مستقیماً به تنظیم مارجین می‌رود بدون دستکاری موجودی
            send_margin_menu(chat_id, message_id=message_id)
            
    elif cmd == "/analyze_single":
        send_telegram_msg("🔍 برای تحلیل تک ارز، نام نماد (مثلا BTC یا ETH) را ارسال کنید.", chat_target=chat_id)
    elif cmd == "/manage_watchlist":
        send_telegram_msg(f"📋 لیست ارزهای فعال تحت نظارت ({len(ACTIVE_SYMBOLS)} ارز):\n`" + ", ".join(ACTIVE_SYMBOLS[:20]) + "...`", chat_target=chat_id)
        
    elif cmd in ["/performance", "گزارش عملکرد"]:
        send_full_performance(chat_id)
    elif cmd == "/toggle_active":
        IS_BOT_ACTIVE = not IS_BOT_ACTIVE
        send_main_menu(chat_id, message_id=message_id)
    elif cmd == "/close_all":
        res_txt = close_all_open_positions()
        send_telegram_msg(res_txt, chat_target=chat_id)
        send_main_menu(chat_id, message_id=message_id)
        
    elif cmd in ["/set_margin_10", "/set_margin_25", "/set_margin_50", "/set_margin_100"]:
        TRADE_AMOUNT_USDT = float(cmd.replace("/set_margin_", ""))
        send_leverage_menu(chat_id, message_id=message_id)
    elif cmd in ["/set_lev_3", "/set_lev_5", "/set_lev_10"]:
        LEVERAGE = int(cmd.replace("/set_lev_", ""))
        send_max_positions_menu(chat_id, message_id=message_id)
    elif cmd.startswith("/set_max_"):
        MAX_OPEN_POSITIONS = int(cmd.replace("/set_max_", ""))
        send_timeframe_menu(chat_id, message_id=message_id)
        
    elif cmd in ["/open_positions", "پوزیشن‌های باز"]:
        txt = f"🔄 *پوزیشن‌های باز ({len(PAPER_POSITIONS)}):*\n\n" + "".join([f"• `{p['symbol']}` ({p['side']})\n" for p in PAPER_POSITIONS]) if PAPER_POSITIONS else "پوزیشن بازی وجود ندارد."
        send_telegram_msg(txt, chat_target=chat_id)
    elif cmd in ["/closed_positions", "تاریخچه معاملات"]:
        txt = "📜 *آخرین معاملات بسته شده:*\n\n" + "".join([f"• `{p['symbol']}` - سود: `{p.get('pnl_usdt',0):+.2f} USDT`\n" for p in CLOSED_POSITIONS[-5:][::-1]]) if CLOSED_POSITIONS else "معامله بسته‌شده‌ای نیست."
        send_telegram_msg(txt, chat_target=chat_id)
        
    elif cmd in ["/set_tf_5m", "/set_tf_15m", "/set_tf_1h"]:
        if cmd == "/set_tf_5m": TIMEFRAME = "5min"
        elif cmd == "/set_tf_15m": TIMEFRAME = "15min"
        elif cmd == "/set_tf_1h": TIMEFRAME = "1hour"
        IS_BOT_ACTIVE = True
        send_telegram_msg("🚀 تنظیمات ذخیره شد و اسکن زنده با پارامترهای جدید آغاز گردید.", chat_target=chat_id)
        send_main_menu(chat_id, message_id=message_id)

def telegram_listener():
    last_id = None
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    print("🤖 تلگرام لیسنر آغاز به کار کرد...")
    while True:
        try:
            res = requests.get(url, params={"timeout": 10, "offset": last_id}, timeout=15)
            if res.status_code == 200:
                data = res.json()
                for r in data.get("result", []):
                    last_id = r["update_id"] + 1
                    if "callback_query" in r:
                        cb = r["callback_query"]
                        msg_id = cb["message"]["message_id"]
                        chat_id = cb["message"]["chat"]["id"]
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery", json={"callback_query_id": cb["id"]})
                        process_command(cb.get("data", ""), chat_id, message_id=msg_id)
                    elif "message" in r:
                        m = r["message"]
                        chat_id = m["chat"]["id"]
                        text = m.get("text", "").strip()
                        # اگر کاربر نام ارزی را فرستاد برای تحلیل تک‌ارز
                        if text and not text.startswith("/"):
                            df = get_crypto_klines(text, interval_type=TIMEFRAME, limit=100)
                            if not df.empty:
                                df = calculate_indicators(df)
                                curr = df.iloc[-2]
                                send_telegram_msg(f"🔍 *تحلیل آنی نماد `{text.upper()}`*\n• قیمت فعلی: `{curr['close']}`\n• اندیکاتور EMA20: `{curr['ema20']:.2f}`\n• اندیکاتور ADX: `{curr['adx']:.2f}`", chat_target=chat_id)
                            else:
                                send_telegram_msg(f"❌ اطلاعاتی برای نماد `{text}` یافت نشد.", chat_target=chat_id)
                        else:
                            process_command(text, chat_id)
        except Exception as e:
            print(f"❌ خطا در دریافت آپدیت‌ها: {e}")
        time.sleep(2)

def bot_loop():
    time.sleep(5)
    while True:
        try:
            update_open_positions()
        except Exception:
            pass
        if IS_BOT_ACTIVE:
            for sym in ACTIVE_SYMBOLS:
                check_symbol(sym)
                time.sleep(0.2)
        time.sleep(30)

if __name__ == "__main__":
    Thread(target=telegram_listener, daemon=True).start()
    Thread(target=bot_loop, daemon=True).start()
    run_flask()
