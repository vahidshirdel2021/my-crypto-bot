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
# ۰. تنظیمات اولیه و متغیرها
# ==========================================
CONFIG_FILE = "config.json"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8931433787:AAEdgjh8du4c-gLEF7DQA7H8xAzs6O0p7mw")
CHAT_ID = os.environ.get("CHAT_ID", "1878257830")

IS_BOT_ACTIVE = False
TRADE_AMOUNT_USDT = 50.0
LEVERAGE = 10
MAX_OPEN_POSITIONS = 3
TIMEFRAME = "5min"
PAPER_BALANCE = 1000.0
DAILY_START_BALANCE = 1000.0
TRADING_MODE = "PAPER"
PAPER_POSITIONS = []
CLOSED_POSITIONS = []

# لیست کامل واچ‌لیست ارزها
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

# ==========================================
# ۱. وب‌سرور Flask برای Render
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    status_str = "ACTIVE" if IS_BOT_ACTIVE else "PAUSED"
    return f"OK - Status: {status_str} | TF: {TIMEFRAME} | Watchlist: {len(ACTIVE_SYMBOLS)} coins", 200

@app.route('/health')
def health():
    return "OK", 200

# ==========================================
# ۲. کیبوردها و رابط کاربری تلگرام
# ==========================================
def get_main_menu_keyboard(is_active):
    active_btn_text = "🟢 روشن کردن اسکن" if not is_active else "🔴 متوقف کردن اسکن"
    return {
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

def send_telegram_msg(message, chat_target=None, reply_markup=None, message_id=None):
    target = chat_target or CHAT_ID
    if message_id:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
        payload = {"chat_id": target, "message_id": message_id, "text": message, "parse_mode": "Markdown"}
        if reply_markup: payload["reply_markup"] = reply_markup
        try:
            if requests.post(url, json=payload, timeout=10).status_code == 200:
                return True
        except: pass

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": target, "text": message, "parse_mode": "Markdown"}
    if reply_markup: payload["reply_markup"] = reply_markup
    try:
        return requests.post(url, json=payload, timeout=10).status_code == 200
    except:
        return False

def send_main_menu(chat_id, message_id=None):
    tf_display = "5m" if TIMEFRAME == "5min" else ("15m" if TIMEFRAME == "15min" else "1h")
    status_str = "فعال (در حال اسکن)" if IS_BOT_ACTIVE else "متوقف شده"
    max_pos = f"{MAX_OPEN_POSITIONS}" if MAX_OPEN_POSITIONS > 0 else "نامحدود"
    p = get_strategy_params(TIMEFRAME)
    
    msg = (
        f"📊 *پنل مدیریت پیشرفته ربات معامله‌گر*\n\n"
        f"• وضعیت: `{status_str}`\n"
        f"• موجودی: `${PAPER_BALANCE:.2f} USDT`\n"
        f"• مارجین: `${TRADE_AMOUNT_USDT:.0f} USDT`\n"
        f"• اهرم: `{LEVERAGE}X` | پوزیشن: `{max_pos}`\n"
        f"• تایم‌فریم: `{tf_display}` (ADX > {p['adx']})\n"
        f"• تعداد ارزهای واچ‌لیست: `{len(ACTIVE_SYMBOLS)}`"
    )
    keyboard = get_main_menu_keyboard(IS_BOT_ACTIVE)
    send_telegram_msg(msg, chat_target=chat_id, reply_markup=keyboard, message_id=message_id)

# ==========================================
# ۳. هسته معاملات و دریافت کندل‌ها
# ==========================================
def get_crypto_klines(coin_symbol, interval_type="5min", limit=200):
    coin_symbol = coin_symbol.upper().replace("USDT", "").replace("/", "").strip()
    try:
        url = f"https://api.kucoin.com/api/v1/market/candles?symbol={coin_symbol}-USDT&type={interval_type}"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if data.get("code") == "200000" and data.get("data"):
                df = pd.DataFrame(data["data"], columns=['timestamp', 'open', 'close', 'high', 'low', 'volume', 'turnover'])
                df = df.iloc[::-1].reset_index(drop=True)
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = df[col].astype(float)
                if not df.empty and len(df) > 30:
                    return df
    except: pass
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
    except: pass

# ==========================================
# ۴. مدیریت دستورات و منوهای تلگرام
# ==========================================
def process_command(data, chat_id, message_id=None):
    global IS_BOT_ACTIVE, TRADE_AMOUNT_USDT, LEVERAGE, MAX_OPEN_POSITIONS, TIMEFRAME
    cmd = data.strip().lower()
    
    if cmd in ["/start", "/menu", "منوی اصلی"]:
        send_main_menu(chat_id, message_id=message_id)
    elif cmd == "/wizard_start":
        if IS_BOT_ACTIVE:
            send_telegram_msg("⚠️ ابتدا اسکن را متوقف کنید.", chat_target=chat_id)
        else:
            kb = {"inline_keyboard": [[{"text": "10 USDT", "callback_data": "/set_margin_10"}, {"text": "25 USDT", "callback_data": "/set_margin_25"}], [{"text": "50 USDT", "callback_data": "/set_margin_50"}, {"text": "100 USDT", "callback_data": "/set_margin_100"}]]}
            send_telegram_msg("⚙️ مقدار مارجین جدید را انتخاب کنید:", chat_target=chat_id, reply_markup=kb, message_id=message_id)
    elif cmd == "/toggle_active":
        IS_BOT_ACTIVE = not IS_BOT_ACTIVE
        send_main_menu(chat_id, message_id=message_id)
    elif cmd in ["/set_margin_10", "/set_margin_25", "/set_margin_50", "/set_margin_100"]:
        TRADE_AMOUNT_USDT = float(cmd.replace("/set_margin_", ""))
        kb = {"inline_keyboard": [[{"text": "3X", "callback_data": "/set_lev_3"}, {"text": "5X", "callback_data": "/set_lev_5"}, {"text": "10X", "callback_data": "/set_lev_10"}]]}
        send_telegram_msg("⚙️ ضریب اهرم را انتخاب کنید:", chat_target=chat_id, reply_markup=kb, message_id=message_id)
    elif cmd in ["/set_lev_3", "/set_lev_5", "/set_lev_10"]:
        LEVERAGE = int(cmd.replace("/set_lev_", ""))
        kb = {"inline_keyboard": [[{"text": "2 معامله", "callback_data": "/set_max_2"}, {"text": "3 معامله", "callback_data": "/set_max_3"}, {"text": "5 معامله", "callback_data": "/set_max_5"}], [{"text": "بدون محدودیت", "callback_data": "/set_max_0"}]]}
        send_telegram_msg("⚙️ حداکثر تعداد پوزیشن را انتخاب کنید:", chat_target=chat_id, reply_markup=kb, message_id=message_id)
    elif cmd.startswith("/set_max_"):
        MAX_OPEN_POSITIONS = int(cmd.replace("/set_max_", ""))
        kb = {"inline_keyboard": [[{"text": "5 دقیقه", "callback_data": "/set_tf_5m"}, {"text": "15 دقیقه", "callback_data": "/set_tf_15m"}, {"text": "1 ساعت", "callback_data": "/set_tf_1h"}]]}
        send_telegram_msg("⚙️ تایم‌فریم جدید را انتخاب کنید:", chat_target=chat_id, reply_markup=kb, message_id=message_id)
    elif cmd in ["/set_tf_5m", "/set_tf_15m", "/set_tf_1h"]:
        if cmd == "/set_tf_5m": TIMEFRAME = "5min"
        elif cmd == "/set_tf_15m": TIMEFRAME = "15min"
        elif cmd == "/set_tf_1h": TIMEFRAME = "1hour"
        IS_BOT_ACTIVE = True
        send_telegram_msg("🚀 تنظیمات ذخیره شد و اسکن مجدداً فعال گردید.", chat_target=chat_id)
        send_main_menu(chat_id, message_id=message_id)
    elif cmd == "/open_positions":
        txt = f"🔄 *پوزیشن‌های باز ({len(PAPER_POSITIONS)}):*\n" + "".join([f"• `{p['symbol']}`\n" for p in PAPER_POSITIONS]) if PAPER_POSITIONS else "پوزیشن بازی وجود ندارد."
        send_telegram_msg(txt, chat_target=chat_id)
    elif cmd == "/manage_watchlist":
        send_telegram_msg(f"📋 لیست ارزهای واچ‌لیست فعال ({len(ACTIVE_SYMBOLS)} ارز):\n`" + ", ".join(ACTIVE_SYMBOLS[:25]) + "...`", chat_target=chat_id)

def telegram_listener():
    last_id = None
    while True:
        try:
            res = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates", params={"offset": last_id}, timeout=15)
            if res.status_code == 200:
                for r in res.json().get("result", []):
                    last_id = r["update_id"] + 1
                    chat_id = r.get("callback_query", {}).get("message", {}).get("chat", {}).get("id") or r.get("message", {}).get("chat", {}).get("id")
                    data = r.get("callback_query", {}).get("data") or r.get("message", {}).get("text")
                    msg_id = r.get("callback_query", {}).get("message", {}).get("message_id")
                    if data: process_command(data, chat_id, message_id=msg_id)
        except: pass
        time.sleep(2)

def bot_loop():
    time.sleep(5)
    while True:
        try: update_open_positions()
        except: pass
        if IS_BOT_ACTIVE:
            for sym in ACTIVE_SYMBOLS:
                check_symbol(sym)
                time.sleep(0.2)
        time.sleep(30)

if __name__ == "__main__":
    Thread(target=telegram_listener, daemon=True).start()
    Thread(target=bot_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))