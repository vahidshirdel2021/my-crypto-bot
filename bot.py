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
    status_str = "ACTIVE" if IS_BOT_ACTIVE else "PAUSED"
    return f"OK - Mode: {TRADING_MODE} | Status: {status_str} | TF: {TIMEFRAME} | Active Coins: {len(ACTIVE_SYMBOLS)}", 200

@app.route('/health')
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# ۱. تنظیمات اولیه و متغیرها
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8931433787:AAEdgjh8du4c-gLEF7DQA7H8xAzs6O0p7mw")
CHAT_ID = os.environ.get("CHAT_ID", "1878257830")

TRADING_MODE = "PAPER"
IS_BOT_ACTIVE = False
INITIAL_BALANCE = 1000.0
PAPER_BALANCE = INITIAL_BALANCE
TRADE_AMOUNT_USDT = 50.0
LEVERAGE = 10
MAX_OPEN_POSITIONS = 3
TIMEFRAME = "5min"

MAX_DAILY_LOSS_PCT = 5.0
DAILY_START_BALANCE = INITIAL_BALANCE

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
# ۲. منوهای ویزارد و پنل اصلی
# ==========================================
def send_welcome_mode_menu(chat_id):
    send_persistent_keyboard(chat_id)
    keyboard = {
        "inline_keyboard": [
            [{"text": "شروع معاملات با موجودی واقعی", "callback_data": "/mode_real"}],
            [{"text": "شروع معاملات با موجودی کاغذی", "callback_data": "/mode_paper"}]
        ]
    }
    send_telegram_msg("به ربات معامله‌گر خوش آمدید.\nلطفاً نوع حساب معاملاتی را انتخاب کنید:", chat_target=chat_id, reply_markup=keyboard)

def send_capital_menu(chat_id):
    keyboard = {
        "inline_keyboard": [
            [{"text": "$500", "callback_data": "/set_cap_500"}, {"text": "$1,000", "callback_data": "/set_cap_1000"}],
            [{"text": "$5,000", "callback_data": "/set_cap_5000"}, {"text": "$10,000", "callback_data": "/set_cap_10000"}]
        ]
    }
    send_telegram_msg("موجودی اولیه حساب کاغذی را انتخاب کنید:", chat_target=chat_id, reply_markup=keyboard)

def send_margin_menu(chat_id):
    keyboard = {
        "inline_keyboard": [
            [{"text": "10 USDT", "callback_data": "/set_margin_10"}, {"text": "25 USDT", "callback_data": "/set_margin_25"}],
            [{"text": "50 USDT", "callback_data": "/set_margin_50"}, {"text": "100 USDT", "callback_data": "/set_margin_100"}]
        ]
    }
    send_telegram_msg("مقدار مارجین (سرمایه درگیر) در هر معامله:", chat_target=chat_id, reply_markup=keyboard)

def send_leverage_menu(chat_id):
    keyboard = {
        "inline_keyboard": [
            [{"text": "3X", "callback_data": "/set_lev_3"}, {"text": "5X", "callback_data": "/set_lev_5"}, {"text": "10X", "callback_data": "/set_lev_10"}]
        ]
    }
    send_telegram_msg("ضریب اهرم (Leverage) را انتخاب کنید:", chat_target=chat_id, reply_markup=keyboard)

def send_max_positions_menu(chat_id):
    keyboard = {
        "inline_keyboard": [
            [{"text": "2 معامله", "callback_data": "/set_max_2"}, {"text": "3 معامله", "callback_data": "/set_max_3"}, {"text": "5 معامله", "callback_data": "/set_max_5"}],
            [{"text": "10 معامله", "callback_data": "/set_max_10"}, {"text": "بدون محدودیت", "callback_data": "/set_max_0"}]
        ]
    }
    send_telegram_msg("حداکثر تعداد پوزیشن‌های هم‌زمان:", chat_target=chat_id, reply_markup=keyboard)

def send_timeframe_menu(chat_id):
    keyboard = {
        "inline_keyboard": [
            [{"text": "5 دقیقه", "callback_data": "/set_tf_5m"}, {"text": "15 دقیقه", "callback_data": "/set_tf_15m"}, {"text": "1 ساعت", "callback_data": "/set_tf_1h"}]
        ]
    }
    send_telegram_msg("انتخاب تایم‌فریم معاملاتی (شروع نهایی اسکن):", chat_target=chat_id, reply_markup=keyboard)

def send_main_menu(chat_id):
    send_persistent_keyboard(chat_id)
    tf_display = "5m" if TIMEFRAME == "5min" else ("15m" if TIMEFRAME == "15min" else "1h")
    status_str = "فعال (در حال اسکن)" if IS_BOT_ACTIVE else "متوقف شده"
    mode_str = "معامله واقعی" if TRADING_MODE == "REAL" else "معامله کاغذی"
    max_pos = f"{MAX_OPEN_POSITIONS}" if MAX_OPEN_POSITIONS > 0 else "نامحدود"
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
                {"text": "تحلیل ارز", "callback_data": "/menu_analyze_coin"},
                {"text": "گزارش عملکرد", "callback_data": "/performance"}
            ],
            [
                {"text": "واچ‌لیست ارزها", "callback_data": "/active_coins"},
                {"text": "تنظیمات مجدد (Wizard)", "callback_data": "/wizard_start"}
            ]
        ]
    }
    
    params = get_strategy_params(TIMEFRAME)
    msg = (
        f"📊 *پنل مدیریت ربات معامله‌گر*\n\n"
        f"• حالت: `{mode_str}`\n"
        f"• وضعیت: `{status_str}`\n"
        f"• موجودی: `${PAPER_BALANCE:.2f} USDT`\n"
        f"• مارجین هر معامله: `${TRADE_AMOUNT_USDT:.0f} USDT`\n"
        f"• اهرم: `{LEVERAGE}X` | حداکثر پوزیشن: `{max_pos}`\n"
        f"• تایم‌فریم: `{tf_display}` (ADX > {params['adx_min']})\n"
        f"• تعداد ارزها: `{len(ACTIVE_SYMBOLS)}` | پوزیشن باز: `{len(PAPER_POSITIONS)}`"
    )
    send_telegram_msg(msg, chat_target=chat_id, reply_markup=keyboard)

# ==========================================
# ۳. پارامترهای استراتژی پویا
# ==========================================
def get_strategy_params(tf):
    if tf == "5min":
        return {"adx_min": 25, "sl_atr": 1.2, "tp_atr": 2.0, "rsi_buy": 45, "rsi_sell": 55}
    elif tf == "15min":
        return {"adx_min": 20, "sl_atr": 1.3, "tp_atr": 2.2, "rsi_buy": 48, "rsi_sell": 52}
    else:
        return {"adx_min": 18, "sl_atr": 1.5, "tp_atr": 2.5, "rsi_buy": 50, "rsi_sell": 50}

# ==========================================
# ۴. دریافت داده‌ها و محاسبه اندیکاتورها
# ==========================================
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

def calculate_indicators(df):
    try:
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
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
        print(f"خطا در اندیکاتورها: {e}")
    return df

def analyze_single_coin(text_input, chat_id):
    # پاکسازی دستورات /analyze یا analyze برای استخراج نام ارز
    clean_sym = text_input.lower().replace("/analyze", "").replace("analyze", "").upper().replace("USDT", "").replace("/", "").strip()
    if not clean_sym:
        send_telegram_msg("نماد را وارد کنید (مثال: `/analyze BTC`).", chat_target=chat_id)
        return

    df = get_crypto_klines(clean_sym, interval_type=TIMEFRAME, limit=200)
    if df.empty or len(df) < 50:
        send_telegram_msg(f"داده‌ای برای {clean_sym} یافت نشد.", chat_target=chat_id)
        return

    df = calculate_indicators(df)
    curr, prev = df.iloc[-2], df.iloc[-3]

    close_p, open_p = float(curr['close']), float(curr['open'])
    rsi_curr, rsi_prev = float(curr['rsi']), float(prev['rsi'])
    adx_val, atr_val = float(curr['adx']), float(curr['atr'])
    ema50_val, ema200_val = float(curr['ema50']), float(curr['ema200'])

    params = get_strategy_params(TIMEFRAME)
    trend_long = (close_p > ema200_val) and (ema50_val > ema200_val) and (adx_val > params["adx_min"])
    trend_short = (close_p < ema200_val) and (ema50_val < ema200_val) and (adx_val > params["adx_min"])

    pullback_long = trend_long and (rsi_prev < params["rsi_buy"]) and (rsi_curr > rsi_prev) and (close_p > open_p)
    pullback_short = trend_short and (rsi_prev > params["rsi_sell"]) and (rsi_curr < rsi_prev) and (close_p < open_p)

    signal = "بدون سیگنال"
    if pullback_long: signal = "سیگنال خرید (Long)"
    elif pullback_short: signal = "سیگنال فروش (Short)"

    report = (
        f"🔍 *تحلیل فنی: {clean_sym}/USDT*\n\n"
        f"• قیمت: `{close_p:.4f}`\n"
        f"• RSI: `{rsi_curr:.1f}`\n"
        f"• ADX: `{adx_val:.1f}`\n"
        f"• وضعیت: *{signal}*"
    )
    send_telegram_msg(report, chat_target=chat_id)

# ==========================================
# ۵. اجرای معاملات و مدیریت پوزیشن‌ها
# ==========================================
def execute_trade(symbol, side, price, sl, tp):
    global IS_BOT_ACTIVE
    if not IS_BOT_ACTIVE: return
    if MAX_OPEN_POSITIONS > 0 and len(PAPER_POSITIONS) >= MAX_OPEN_POSITIONS: return
    for pos in PAPER_POSITIONS:
        if pos['symbol'] == symbol: return

    margin = TRADE_AMOUNT_USDT
    pos_val = margin * LEVERAGE
    if PAPER_BALANCE < margin: return

    trade = {
        "symbol": symbol, "side": side, "entry_price": price,
        "sl": sl, "tp": tp, "margin": margin, "position_val": pos_val,
        "leverage": LEVERAGE, "timeframe": TIMEFRAME, "mode": TRADING_MODE,
        "timestamp": time.time(), "open_time": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    PAPER_POSITIONS.append(trade)
    msg = f"📝 *معامله جدید ({side})*\n• نماد: `{symbol}`\n• ورود: `{price:.4f}`\n• TP: `{tp:.4f}` | SL: `{sl:.4f}`"
    send_telegram_msg(msg)

def close_all_open_positions():
    global PAPER_BALANCE
    if not PAPER_POSITIONS: return "پوزیشن بازی وجود ندارد."
    count = len(PAPER_POSITIONS)
    total_change = 0.0

    for pos in PAPER_POSITIONS[:]:
        sym = pos['symbol']
        df = get_crypto_klines(sym, interval_type=pos.get('timeframe', TIMEFRAME), limit=2)
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
        df = get_crypto_klines(pos['symbol'], interval_type=pos.get('timeframe', TIMEFRAME), limit=5)
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

            if (INITIAL_BALANCE - PAPER_BALANCE) / INITIAL_BALANCE * 100 >= MAX_DAILY_LOSS_PCT:
                IS_BOT_ACTIVE = False
                send_telegram_msg("🛑 سقف زیان روزانه لمس شد. ربات متوقف گردید.")

def check_symbol(coin_symbol):
    if not IS_BOT_ACTIVE: return
    try:
        df = get_crypto_klines(coin_symbol, interval_type=TIMEFRAME, limit=200)
        if df.empty or len(df) < 50: return
        df = calculate_indicators(df)
        curr, prev = df.iloc[-2], df.iloc[-3]
        
        close_p, open_p = float(curr['close']), float(curr['open'])
        rsi_c, rsi_p = float(curr['rsi']), float(prev['rsi'])
        adx, atr = float(curr['adx']), float(curr['atr'])
        ema50, ema200 = float(curr['ema50']), float(curr['ema200'])
        
        params = get_strategy_params(TIMEFRAME)
        t_long = (close_p > ema200) and (ema50 > ema200) and (adx > params["adx_min"])
        t_short = (close_p < ema200) and (ema50 < ema200) and (adx > params["adx_min"])
        
        if t_long and (rsi_p < params["rsi_buy"]) and (rsi_c > rsi_p) and (close_p > open_p):
            execute_trade(coin_symbol, 'BUY (Long)', close_p, close_p - (atr * params["sl_atr"]), close_p + (atr * params["tp_atr"]))
        elif t_short and (rsi_p > params["rsi_sell"]) and (rsi_c < rsi_p) and (close_p < open_p):
            execute_trade(coin_symbol, 'SELL (Short)', close_p, close_p + (atr * params["sl_atr"]), close_p - (atr * params["tp_atr"]))
    except Exception:
        pass

# ==========================================
# ۶. گزارش عملکرد
# ==========================================
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

def get_open_report():
    if not PAPER_POSITIONS: return "پوزیشن بازی وجود ندارد."
    txt = f"🔄 *پوزیشن‌های باز ({len(PAPER_POSITIONS)}):*\n\n"
    for p in PAPER_POSITIONS:
        txt += f"• `{p['symbol']}` ({p['side']}) - ورود: `{p['entry_price']:.4f}`\n"
    return txt

def get_closed_report():
    if not CLOSED_POSITIONS: return "معامله بسته‌شده‌ای نیست."
    txt = "📜 *آخرین معاملات بسته شده:*\n\n"
    for p in CLOSED_POSITIONS[-5:][::-1]:
        txt += f"• `{p['symbol']}` ({p['side']}) - سود: `{p.get('pnl_usdt',0):+.2f} USDT`\n"
    return txt

# ==========================================
# ۷. کنترلر دستورات تلگرام
# ==========================================
def process_command(data, chat_id):
    global TIMEFRAME, LEVERAGE, INITIAL_BALANCE, PAPER_BALANCE, CLOSED_POSITIONS, PAPER_POSITIONS, IS_BOT_ACTIVE, ACTIVE_SYMBOLS, TRADING_MODE, MAX_OPEN_POSITIONS, DAILY_START_BALANCE, TRADE_AMOUNT_USDT
    
    cmd = data.strip().lower()
    
    if cmd in ["/start", "/wizard_start", "تنظیمات مجدد (wizard)", "تنظیمات مجدد"]:
        IS_BOT_ACTIVE = False
        send_welcome_mode_menu(chat_id)
    elif cmd in ["/menu", "/main_menu", "menu", "منوی اصلی"]:
        send_main_menu(chat_id)
    elif cmd in ["/performance", "گزارش عملکرد"]:
        send_full_performance(chat_id)
    elif cmd == "/menu_analyze_coin":
        send_telegram_msg("برای تحلیل، دستور زیر را بفرستید:\n`/analyze BTC`", chat_target=chat_id)
    elif cmd.startswith("/analyze"):
        analyze_single_coin(data, chat_id)
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
    elif cmd == "/toggle_active":
        IS_BOT_ACTIVE = not IS_BOT_ACTIVE
        send_main_menu(chat_id)
    elif cmd == "/close_all":
        send_telegram_msg(close_all_open_positions(), chat_target=chat_id)
        send_main_menu(chat_id)
    elif cmd in ["/open_positions", "پوزیشن‌های باز"]:
        send_telegram_msg(get_open_report(), chat_target=chat_id)
    elif cmd in ["/closed_positions", "تاریخچه معاملات"]:
        send_telegram_msg(get_closed_report(), chat_target=chat_id)
    elif cmd in ["/active_coins", "واچ‌لیست ارزها"]:
        send_telegram_msg(f"تعداد ارزها: {len(ACTIVE_SYMBOLS)}", chat_target=chat_id)
    elif cmd in ["/pnl", "گزارش کلی"]:
        send_telegram_msg(generate_report(None, "گزارش کل"), chat_target=chat_id)
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
                try:
                    check_symbol(sym)
                except Exception:
                    pass
                time.sleep(0.2)
        time.sleep(30)

if __name__ == "__main__":
    Thread(target=telegram_listener, daemon=True).start()
    Thread(target=bot_loop, daemon=True).start()
    run_flask()
