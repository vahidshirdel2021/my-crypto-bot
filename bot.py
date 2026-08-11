import os
import json
import time
import requests
import ccxt
import pandas as pd
from threading import Thread
from flask import Flask
from strategy import calculate_indicators, get_signal, get_strategy_params

# تنظیمات اولیه
CONFIG_FILE = "config.json"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8931433787:AAEdgjh8du4c-gLEF7DQA7H8xAzs6O0p7mw")
CHAT_ID = os.environ.get("CHAT_ID", "1878257830")

IS_BOT_ACTIVE = False
# متغیرها
TRADE_AMOUNT_USDT = 50.0
LEVERAGE = 10
MAX_OPEN_POSITIONS = 3
TIMEFRAME = "5min"
PAPER_BALANCE = 1000.0
TRADING_MODE = "PAPER"
PAPER_POSITIONS = []
CLOSED_POSITIONS = []
ACTIVE_SYMBOLS = ['BTC', 'ETH', 'BNB', 'ADA', 'XRP', 'SOL', 'DOT', 'LINK', 'MATIC', 'AVAX']

# توابع ارسال پیام
def send_telegram_msg(message, chat_target=None, reply_markup=None, message_id=None):
    target = chat_target or CHAT_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText" if message_id else f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": target, "text": message, "parse_mode": "Markdown"}
    if message_id: payload["message_id"] = message_id
    if reply_markup: payload["reply_markup"] = reply_markup
    try:
        requests.post(url, json=payload, timeout=10)
    except: pass

def send_main_menu(chat_id, message_id=None):
    status_str = "🟢 فعال" if IS_BOT_ACTIVE else "🔴 متوقف"
    keyboard = {
        "inline_keyboard": [
            [{"text": "توقف/شروع اسکن", "callback_data": "/toggle_active"}, {"text": "🔍 تحلیل تک ارز", "callback_data": "/analyze_single"}],
            [{"text": "📋 مدیریت واچ‌لیست", "callback_data": "/manage_watchlist"}, {"text": "⚙️ تنظیمات معاملاتی", "callback_data": "/wizard_start"}],
            [{"text": "🔄 پوزیشن‌های باز", "callback_data": "/open_positions"}, {"text": "📈 گزارش عملکرد", "callback_data": "/performance"}]
        ]
    }
    msg = f"📊 *پنل مدیریت ربات*\n\nوضعیت: {status_str}\nموجودی: ${PAPER_BALANCE:.2f}\nمارجین: ${TRADE_AMOUNT_USDT}\nاهرم: {LEVERAGE}X"
    send_telegram_msg(msg, chat_target=chat_id, reply_markup=keyboard, message_id=message_id)

def process_command(data, chat_id, message_id=None):
    global IS_BOT_ACTIVE, TRADE_AMOUNT_USDT, LEVERAGE, MAX_OPEN_POSITIONS, TIMEFRAME, TRADING_MODE
    cmd = data.strip().lower()
    
    if cmd == "/start":
        keyboard = {"inline_keyboard": [[{"text": "حساب واقعی", "callback_data": "/mode_real"}, {"text": "حساب کاغذی", "callback_data": "/mode_paper"}]]}
        send_telegram_msg("نوع حساب را انتخاب کنید:", chat_target=chat_id, reply_markup=keyboard)
    elif cmd in ["/menu", "منوی اصلی"]:
        send_main_menu(chat_id, message_id=message_id)
    elif cmd == "/wizard_start":
        if IS_BOT_ACTIVE: send_telegram_msg("ابتدا اسکن را متوقف کنید.", chat_target=chat_id)
        else:
            keyboard = {"inline_keyboard": [[{"text": "10$", "callback_data": "/set_margin_10"}, {"text": "50$", "callback_data": "/set_margin_50"}]]}
            send_telegram_msg("مارجین جدید را انتخاب کنید:", chat_target=chat_id, reply_markup=keyboard, message_id=message_id)
    # اضافه کردن سایر دستورات مشابه...
    elif cmd == "/toggle_active":
        IS_BOT_ACTIVE = not IS_BOT_ACTIVE
        send_main_menu(chat_id, message_id=message_id)

# بخش شنونده تلگرام
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
                    process_command(data, chat_id, message_id=msg_id)
        except: pass
        time.sleep(2)

if __name__ == "__main__":
    Thread(target=telegram_listener, daemon=True).start()
    app.run(host='0.0.0.0', port=10000)
