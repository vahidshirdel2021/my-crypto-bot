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
PAPER_BALANCE = config["initial_balance"]
DAILY_START_BALANCE = config["initial_balance"]

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
    except Exception:
        pass

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

def send_telegram_msg(message, chat_target=None, reply_markup=None):
    target = chat_target or CHAT_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": target, "text": message, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception:
        pass

def send_persistent_keyboard(chat_id):
    keyboard = {
        "keyboard": [
            [{"text": "منوی اصلی"}, {"text": "گزارش عملکرد"}]
        ],
        "resize_keyboard": True,
        "is_persistent": True
    }
    send_telegram_msg("سیستم مدیریت آماده است.", chat_target=chat_id, reply_markup=keyboard)

def send_main_menu(chat_id):
    send_persistent_keyboard(chat_id)
    status_str = "فعال (در حال اسکن)" if IS_BOT_ACTIVE else "متوقف شده"
    toggle_text = "توقف اسکن" if IS_BOT_ACTIVE else "شروع اسکن"
    
    keyboard = {
        "inline_keyboard": [
            [
                {"text": toggle_text, "callback_data": "/toggle_active"},
                {"text": "بستن همه پوزیشن‌ها", "callback_data": "/close_all"}
            ],
            [
                {"text": "پوزیشن‌های باز", "callback_data": "/open_positions"},
                {"text": "تاریخچه معاملات", "callback_data": "/closed_positions"}
            ],
            [
                {"text": "گزارش عملکرد", "callback_data": "/performance"},
                {"text": "تنظیمات مجدد", "callback_data": "/wizard_start"}
            ]
        ]
    }
    
    msg = (
        f"📊 *پنل مدیریت ربات معامله‌گر*\n\n"
        f"• حالت: `{config['trading_mode']}`\n"
        f"• وضعیت: `{status_str}`\n"
        f"• موجودی: `${PAPER_BALANCE:.2f} USDT`\n"
        f"• مارجین هر معامله: `${config['trade_amount_usdt']:.0f} USDT`\n"
        f"• اهرم: `{config['leverage']}X` | حداکثر پوزیشن: `{config['max_open_positions']}`\n"
        f"• تایم‌فریم: `{config['timeframe']}`"
    )
    send_telegram_msg(msg, chat_target=chat_id, reply_markup=keyboard)

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
    if config["max_open_positions"] > 0 and len(PAPER_POSITIONS) >= config["max_open_positions"]: return
    for pos in PAPER_POSITIONS:
        if pos['symbol'] == symbol: return

    margin = config["trade_amount_usdt"]
    if PAPER_BALANCE < margin: return

    trade = {
        "symbol": symbol, "side": side, "entry_price": price,
        "sl": sl, "tp": tp, "margin": margin,
        "leverage": config["leverage"], "timeframe": config["timeframe"],
        "close_timestamp": None, "pnl_usdt": 0.0
    }
    PAPER_POSITIONS.append(trade)
    send_telegram_msg(f"📝 *معامله جدید ({side})*\n• نماد: `{symbol}`\n• ورود: `{price:.4f}`\n• TP: `{tp:.4f}` | SL: `{sl:.4f}`")

def close_all_open_positions():
    global PAPER_BALANCE
    if not PAPER_POSITIONS: return "پوزیشن بازی وجود ندارد."
    count = len(PAPER_POSITIONS)
    total_change = 0.0

    for pos in PAPER_POSITIONS[:]:
        sym = pos['symbol']
        df = get_crypto_klines(sym, interval_type=pos.get('timeframe', config["timeframe"]), limit=2)
        curr_p = float(df.iloc[-1]['close']) if not df.empty else pos['entry_price']
        
        raw_pnl = ((curr_p - pos['entry_price']) / pos['entry_price']) * 100 if "BUY" in pos['side'] else ((pos['entry_price'] - curr_p) / pos['entry_price']) * 100
        pnl_usdt = (pos['margin'] * (raw_pnl * pos['leverage'])) / 100
        
        PAPER_BALANCE += pnl_usdt
        total_change += pnl_usdt
        pos['pnl_usdt'] = pnl_usdt
        pos['close_timestamp'] = time.time()
        CLOSED_POSITIONS.append(pos)
        PAPER_POSITIONS.remove(pos)

    return f"تعداد {count} پوزیشن بسته شد.\nسود/زیان کل: `{total_change:+.2f} USDT`"

def update_open_positions():
    global PAPER_BALANCE, IS_BOT_ACTIVE
    if not PAPER_POSITIONS: return

    for pos in PAPER_POSITIONS[:]:
        df = get_crypto_klines(pos['symbol'], interval_type=pos.get('timeframe', config["timeframe"]), limit=5)
        if df.empty: continue
        high, low = float(df.iloc[-1]['high']), float(df.iloc[-1]['low'])
        
        closed, raw_pnl = False, 0.0
        if "BUY" in pos['side']:
            if high >= pos['tp']: closed, raw_pnl = True, ((pos['tp'] - pos['entry_price']) / pos['entry_price']) * 100
            elif low <= pos['sl']: closed, raw_pnl = True, ((pos['sl'] - pos['entry_price']) / pos['entry_price']) * 100
        else:
            if low <= pos['tp']: closed, raw_pnl = True, ((pos['entry_price'] - pos['tp']) / pos['entry_price']) * 100
            elif high >= pos['sl']: closed, raw_pnl = True, ((pos['entry_price'] - pos['sl']) / pos['entry_price']) * 100

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
        df = get_crypto_klines(coin_symbol, interval_type=config["timeframe"], limit=200)
        if df.empty or len(df) < 50: return
        df = calculate_indicators(df)
        
        signal = get_signal(df, config["timeframe"])
        if not signal: return
        
        curr = df.iloc[-2]
        close_p = float(curr['close'])
        atr = float(curr['atr'])
        p = get_strategy_params(config["timeframe"])
        
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

def def process_command(data, chat_id):
    global IS_BOT_ACTIVE, TRADING_MODE, INITIAL_BALANCE, PAPER_BALANCE, DAILY_START_BALANCE, TRADE_AMOUNT_USDT, LEVERAGE, MAX_OPEN_POSITIONS, TIMEFRAME
    
    cmd = data.strip().lower()
    
    # اصلاح اصلی: دستور استارت باید حتماً ویزارد (انتخاب حساب واقعی یا کاغذی) را شروع کند
    if cmd in ["/start", "/wizard_start", "تنظیمات مجدد"]:
        IS_BOT_ACTIVE = False
        send_welcome_mode_menu(chat_id)
        
    elif cmd in ["/menu", "/main_menu", "menu", "منوی اصلی"]:
        send_main_menu(chat_id)
    elif cmd in ["/performance", "گزارش عملکرد"]:
        send_full_performance(chat_id)
    elif cmd == "/toggle_active":
        IS_BOT_ACTIVE = not IS_BOT_ACTIVE
        send_main_menu(chat_id)
    elif cmd == "/close_all":
        send_telegram_msg(close_all_open_positions(), chat_target=chat_id)
        send_main_menu(chat_id)
    elif cmd == "/mode_real":
        usdt_balance = 0.0
        if exchange:
            try:
                bal = exchange.fetch_balance()
                usdt_balance = float(bal.get('total', {}).get('USDT', 0.0))
            except Exception as e:
                send_telegram_msg(f"⚠️ خطا در صرافی: {e}", chat_target=chat_id)
                return

        if usdt_balance <= 0:
            send_telegram_msg("❌ موجودی حساب واقعی شما در صرافی صفر (۰) است. امکان شروع معاملات واقعی وجود ندارد.", chat_target=chat_id)
            send_welcome_mode_menu(chat_id)
        else:
            TRADING_MODE = "REAL"
            PAPER_BALANCE = usdt_balance
            DAILY_START_BALANCE = usdt_balance
            send_telegram_msg(f"🔴 موجودی واقعی شناسایی شد: `{usdt_balance:.2f} USDT`", chat_target=chat_id)
            send_margin_menu(chat_id)
    elif cmd == "/mode_paper":
        TRADING_MODE = "PAPER"
        send_capital_menu(chat_id)
    elif cmd in ["/set_cap_500", "/set_cap_1000", "/set_cap_5000", "/set_cap_10000"]:
        cap = float(cmd.replace("/set_cap_", ""))
        INITIAL_BALANCE, PAPER_BALANCE, DAILY_START_BALANCE = cap, cap, cap
        CLOSED_POSITIONS.clear()
        PAPER_POSITIONS.clear()
        send_margin_menu(chat_id)
    elif cmd in ["/set_margin_10", "/set_margin_25", "/set_margin_50", "/set_margin_100"]:
        TRADE_AMOUNT_USDT = float(cmd.replace("/set_margin_", ""))
        send_leverage_menu(chat_id)
    elif cmd in ["/set_lev_3", "/set_lev_5", "/set_lev_10"]:
        LEVERAGE = int(cmd.replace("/set_lev_", ""))
        send_max_positions_menu(chat_id)
    elif cmd.startswith("/set_max_"):
        MAX_OPEN_POSITIONS = int(cmd.replace("/set_max_", ""))
        send_timeframe_menu(chat_id)
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
        send_telegram_msg("🚀 تنظیمات ذخیره و اسکن زنده آغاز شد.", chat_target=chat_id)
        send_main_menu(chat_id)

def telegram_listener():
    last_id = None
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    while True:
        try:
            res = requests.get(url, params={"timeout": 10, "offset": last_id}, timeout=12)
            if res.status_code == 200:
                for r in res.json().get("result", []):
                    last_id = r["update_id"] + 1
                    if "callback_query" in r:
                        cb = r["callback_query"]
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery", json={"callback_query_id": cb["id"]})
                        process_command(cb.get("data", ""), cb["message"]["chat"]["id"])
                    elif "message" in r:
                        m = r["message"]
                        process_command(m.get("text", ""), m["chat"]["id"])
        except Exception:
            pass
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
