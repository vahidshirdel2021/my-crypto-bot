import os
import json
import time
import requests
import ccxt
import pandas as pd
from threading import Thread
from flask import Flask
from strategy import calculate_indicators, get_signal, get_strategy_params, get_strategy_description
from ui import (
    get_start_keyboard, get_balance_keyboard, get_margin_keyboard, 
    get_leverage_keyboard, get_max_positions_keyboard, get_timeframe_keyboard, 
    get_main_menu_keyboard, get_watchlist_manage_keyboard, get_strategies_menu_keyboard
)

CONFIG_FILE = "config.json"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8931433787:AAEdgjh8du4c-gLEF7DQA7H8xAzs6O0p7mw")
CHAT_ID = os.environ.get("CHAT_ID", "1878257830")

IS_BOT_ACTIVE = False
TRADING_MODE = "PAPER"
PAPER_BALANCE = 1000.0
DAILY_START_BALANCE = 1000.0
TRADE_AMOUNT_USDT = 50.0
LEVERAGE = 10
MAX_OPEN_POSITIONS = 3
TIMEFRAME = "5min"

PAPER_POSITIONS = []
CLOSED_POSITIONS = []
USER_STATE = None

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
    except: pass

ALL_SYMBOLS = ['BTC', 'ETH', 'YFI', 'MKR', 'BCH', 'COMP', 'KSM', 'LTC', 'AAVE', 'ZEC', 'BNB', 'SOL', 'UNI', 'DOT', 'AVAX', 'ATOM', 'ETC', 'NEO', 'ADA', 'FTM', 'XRP', 'LINK', 'MATIC', 'DOGE', 'TRX', 'VET', 'SHIB']
ACTIVE_SYMBOLS = ALL_SYMBOLS.copy()

app = Flask(__name__)

@app.route('/')
def home():
    return "OK", 200

def send_telegram_msg(message, chat_target=None, reply_markup=None, message_id=None):
    target = chat_target or CHAT_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/" + ("editMessageText" if message_id else "sendMessage")
    payload = {"chat_id": target, "text": message, "parse_mode": "Markdown"}
    if message_id: payload["message_id"] = message_id
    if reply_markup: payload["reply_markup"] = reply_markup
    try:
        requests.post(url, json=payload, timeout=10)
    except: pass

def send_main_menu(chat_id, message_id=None):
    msg = f"📊 *پنل مدیریت*\nموجودی: `${PAPER_BALANCE:.2f} USDT`"
    send_telegram_msg(msg, chat_target=chat_id, reply_markup=get_main_menu_keyboard(IS_BOT_ACTIVE), message_id=message_id)

def get_crypto_klines(coin_symbol, interval_type="5min", limit=100):
    coin_symbol = coin_symbol.upper().replace("USDT", "").replace("/", "").strip()
    try:
        url = f"https://api.kucoin.com/api/v1/market/candles?symbol={coin_symbol}-USDT&type={interval_type}"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json().get("data", [])
            df = pd.DataFrame(data, columns=['timestamp', 'open', 'close', 'high', 'low', 'volume', 'turnover'])
            return df.iloc[::-1].reset_index(drop=True)
    except: pass
    return pd.DataFrame()

def process_command(data, chat_id, message_id=None):
    global IS_BOT_ACTIVE, TRADING_MODE, PAPER_BALANCE, TRADE_AMOUNT_USDT, LEVERAGE, MAX_OPEN_POSITIONS, TIMEFRAME, USER_STATE, ACTIVE_SYMBOLS
    cmd = data.strip().lower()
    
    if cmd == "/start":
        send_telegram_msg("🤖 *سلام! نوع حساب را انتخاب کنید:*", chat_target=chat_id, reply_markup=get_start_keyboard())
    elif cmd == "/mode_paper":
        TRADING_MODE = "PAPER"
        send_telegram_msg("⚙️ موجودی اولیه را انتخاب کنید:", chat_target=chat_id, reply_markup=get_balance_keyboard())
    elif cmd.startswith("/set_bal_"):
        PAPER_BALANCE = float(cmd.replace("/set_bal_", ""))
        send_telegram_msg("⚙️ مارجین هر معامله را انتخاب کنید:", chat_target=chat_id, reply_markup=get_margin_keyboard())
    elif cmd == "/toggle_active":
        IS_BOT_ACTIVE = not IS_BOT_ACTIVE
        send_main_menu(chat_id, message_id=message_id)
    elif cmd == "/menu":
        send_main_menu(chat_id, message_id=message_id)
    elif cmd == "/strategies_list":
        send_telegram_msg("📊 *انتخاب استراتژی:*", chat_target=chat_id, reply_markup=get_strategies_menu_keyboard())
    elif cmd.startswith("/desc_"):
        mode = cmd.replace("/desc_", "")
        tf = "5min" if mode == "5min" else ("15min" if mode == "15min" else ("1hour" if mode == "1hour" else "multi"))
        send_telegram_msg(get_strategy_description(tf), chat_target=chat_id, reply_markup=get_strategies_menu_keyboard())
    elif cmd == "/close_all":
        IS_BOT_ACTIVE = False
        PAPER_POSITIONS.clear()
        send_telegram_msg("🛑 اسکن متوقف و تمام پوزیشن‌ها بسته شدند.", chat_target=chat_id)
    # ... سایر دستورات ...

if __name__ == "__main__":
    Thread(target=telegram_listener, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
