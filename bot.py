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
    return f"OK - Mode: {TRADING_MODE} | Status: {status_str} | Active Coins: {len(ACTIVE_SYMBOLS)}", 200

@app.route('/health')
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# ۱. تنظیمات اولیه و متغیرهای پویا
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8931433787:AAEdgjh8du4c-gLEF7DQA7H8xAzs6O0p7mw")
CHAT_ID = os.environ.get("CHAT_ID", "1878257830")

# وضعیت‌های ربات
TRADING_MODE = "PAPER"      # "REAL" یا "PAPER"
IS_BOT_ACTIVE = False       # 🛑 اسکن تا زمان اتمام تنظیمات خاموش است
INITIAL_BALANCE = 1000.0    # سرمایه اولیه پیش‌فرض
PAPER_BALANCE = INITIAL_BALANCE
TRADE_AMOUNT_USDT = 50.0   # مارجین هر معامله
LEVERAGE = 10              # اهرم پیش‌فرض
TIMEFRAME = "5min"         # تایم‌فریم پیش‌فرض

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
    # کیبورد ثابت در پایین صفحه
    keyboard = {
        "keyboard": [
            [{"text": "🎛 منوی اصلی"}]
        ],
        "resize_keyboard": True,
        "is_persistent": True
    }
    send_telegram_msg("📍 *دکمه منوی اصلی در پایین صفحه فعال شد.*", chat_target=chat_id, reply_markup=keyboard)

# ==========================================
# ۲. منوهای راه‌اندازی و تعاملی
# ==========================================
def send_welcome_mode_menu(chat_id):
    send_persistent_keyboard(chat_id)
    keyboard = {
        "inline_keyboard": [
            [{"text": "🔴 شروع معاملات با موجودی واقعی", "callback_data": "/mode_real"}],
            [{"text": "🧪 شروع معاملات با موجودی کاغذی", "callback_data": "/mode_paper"}]
        ]
    }
    msg = (
        f"👋 *به ربات معامله‌گر اتوماتیک خوش آمدید!*\n\n"
        f"لطفاً جهت راه‌اندازی، نحوه فعالیت ربات را انتخاب کنید:"
    )
    send_telegram_msg(msg, chat_target=chat_id, reply_markup=keyboard)

def send_capital_menu(chat_id):
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "💵 $500", "callback_data": "/set_cap_500"},
                {"text": "💵 $1,000", "callback_data": "/set_cap_1000"}
            ],
            [
                {"text": "💵 $5,000", "callback_data": "/set_cap_5000"},
                {"text": "💵 $10,000", "callback_data": "/set_cap_10000"}
            ]
        ]
    }
    msg = f"💰 *گام ۱: موجودی اولیه حساب کاغذی را انتخاب کنید:*"
    send_telegram_msg(msg, chat_target=chat_id, reply_markup=keyboard)

def send_leverage_menu(chat_id):
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "⚡ اهرم 3X", "callback_data": "/set_lev_3"},
                {"text": "⚡ اهرم 5X", "callback_data": "/set_lev_5"},
                {"text": "⚡ اهرم 10X", "callback_data": "/set_lev_10"}
            ]
        ]
    }
    msg = f"⚡ *گام ۲: اهرم معاملاتی (Leverage) خود را انتخاب کنید:*"
    send_telegram_msg(msg, chat_target=chat_id, reply_markup=keyboard)

def send_timeframe_menu(chat_id):
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "⏱ 5 دقیقه", "callback_data": "/set_tf_5m"},
                {"text": "⏱ 15 دقیقه", "callback_data": "/set_tf_15m"},
                {"text": "⏱ 1 ساعته", "callback_data": "/set_tf_1h"}
            ]
        ]
    }
    msg = f"⏱ *گام نهایی: تایم‌فریم معاملاتی خود را انتخاب کنید:*\n(با انتخاب این گزینه اسکن زنده فعال می‌شود)"
    send_telegram_msg(msg, chat_target=chat_id, reply_markup=keyboard)

def send_main_menu(chat_id):
    tf_display = "5 دقیقه" if TIMEFRAME == "5min" else ("15 دقیقه" if TIMEFRAME == "15min" else "1 ساعته")
    status_icon = "🟢 در حال اسکن" if IS_BOT_ACTIVE else "🔴 متوقف شده"
    mode_icon = "🔴 واقعی (Real)" if TRADING_MODE == "REAL" else "🧪 کاغذی (Paper)"
    toggle_button_text = "⏸ توقف اسکن معاملات" if IS_BOT_ACTIVE else "▶️ شروع اسکن معاملات"
    
    keyboard = {
        "inline_keyboard": [
            [
                {"text": toggle_button_text, "callback_data": "/toggle_active"},
                {"text": "❌ بستن کل معاملات باز", "callback_data": "/close_all"}
            ],
            [
                {"text": "🔄 پوزیشن‌های باز", "callback_data": "/open_positions"},
                {"text": "📜 تاریخچه معاملات بسته", "callback_data": "/closed_positions"}
            ],
            [
                {"text": "🔎 تحلیل ارز دلخواه", "callback_data": "/menu_analyze_coin"},
                {"text": "📋 واچ‌لیست ارزها", "callback_data": "/active_coins"}
            ],
            [
                {"text": "📈 گزارش کلی PnL", "callback_data": "/pnl"},
                {"text": "⚙️ شروع مجدد تنظیمات", "callback_data": "/start"}
            ]
        ]
    }
    
    msg = (
        f"🎛 *پنل مدیریت اصلی ربات*\n\n"
        f"🔹 *حالت معامله:* `{mode_icon}`\n"
        f"🔹 *وضعیت اسکن:* `{status_icon}`\n"
        f"🔹 *موجودی کل:* `${PAPER_BALANCE:.2f} USDT`\n"
        f"🔹 *اهرم فعال:* `{LEVERAGE}X` | *مارجین:* `${TRADE_AMOUNT_USDT:.0f}`\n"
        f"🔹 *تایم‌فریم اسکن:* `{tf_display}`\n"
        f"🔹 *ارزهای فعال:* `{len(ACTIVE_SYMBOLS)} ارز`\n"
        f"🔹 *پوزیشن‌های باز:* `{len(PAPER_POSITIONS)}` | *بسته‌شده:* `{len(CLOSED_POSITIONS)}`"
    )
    send_telegram_msg(msg, chat_target=chat_id, reply_markup=keyboard)

# ==========================================
# ۳. دریافت داده‌ها و اندیکاتورها
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
# ۴. تحلیل تک‌ارز طبق استراتژی
# ==========================================
def analyze_single_coin(symbol, chat_id):
    clean_sym = symbol.upper().replace("USDT", "").replace("/", "").replace("/ANALYZE", "").strip()
    if not clean_sym:
        send_telegram_msg("⚠️ لطفاً نماد ارز را وارد کنید (مثال: `/analyze BTC`).", chat_target=chat_id)
        return

    df = get_crypto_klines(clean_sym, interval_type=TIMEFRAME, limit=200)
    if df.empty or len(df) < 50:
        send_telegram_msg(f"❌ داده‌های قیمت برای ارز `{clean_sym}` دریافت نشد.", chat_target=chat_id)
        return

    df = calculate_indicators(df)
    curr, prev = df.iloc[-2], df.iloc[-3]

    close_p, open_p = float(curr['close']), float(curr['open'])
    rsi_curr, rsi_prev = float(curr['rsi']), float(prev['rsi'])
    adx_val, atr_val = float(curr['adx']), float(curr['atr'])
    ema_val = float(curr['ema200'])

    trend_long = close_p > ema_val and adx_val > 14
    trend_short = close_p < ema_val and adx_val > 14

    pullback_long = trend_long and (rsi_prev < 50) and (rsi_curr > rsi_prev) and (close_p > open_p)
    pullback_short = trend_short and (rsi_prev > 50) and (rsi_curr < rsi_prev) and (close_p < open_p)

    trend_str = "🟢 صعودی (بالای EMA200)" if close_p > ema_val else "🔴 نزولی (زیر EMA200)"
    signal_str = "🟡 فاقد سیگنال ورود در این کندل"
    if pullback_long:
        signal_str = "🚀 *سیگنال ورود خرید (Long)*"
    elif pullback_short:
        signal_str = "🔻 *سیگنال ورود فروش (Short)*"

    tf_display = "5 دقیقه" if TIMEFRAME == "5min" else ("15 دقیقه" if TIMEFRAME == "15min" else "1 ساعته")

    report = (
        f"🔎 *گزارش تحلیل فنی {clean_sym}/USDT*\n\n"
        f"⏱ *تایم‌فریم:* `{tf_display}`\n"
        f"💵 *قیمت فعلی:* `{close_p:.4f}`\n"
        f"📈 *میانگین EMA200:* `{ema_val:.4f}` ({trend_str})\n"
        f"📊 *شاخص RSI (14):* `{rsi_curr:.1f}` (کندل قبل: `{rsi_prev:.1f}`)\n"
        f"⚡ *قدرت روند ADX:* `{adx_val:.1f}`\n"
        f"📏 *نوسان ATR:* `{atr_val:.4f}`\n\n"
        f"🎯 *وضعیت سیگنال:* {signal_str}"
    )
    send_telegram_msg(report, chat_target=chat_id)

# ==========================================
# ۵. سیستم معاملات واقعی و کاغذی
# ==========================================
def execute_trade(symbol, side, price, sl, tp):
    if not IS_BOT_ACTIVE:
        return

    for pos in PAPER_POSITIONS:
        if pos['symbol'] == symbol:
            return

    if TRADING_MODE == "REAL":
        if exchange:
            try:
                market_symbol = f"{symbol}/USDT:USDT"
                order = exchange.create_order(
                    symbol=market_symbol,
                    type='market',
                    side='buy' if 'BUY' in side else 'sell',
                    amount=1
                )
                print(f"✅ معامله واقعی CoinEx ثبت شد: {order.get('id')}")
            except Exception as e:
                send_telegram_msg(f"❌ *خطا در ثبت معامله واقعی CoinEx:* `{e}`")
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
        "timeframe": TIMEFRAME,
        "mode": TRADING_MODE,
        "open_time": time.strftime("%H:%M:%S")
    }
    PAPER_POSITIONS.append(trade)
    
    mode_str = "🔴 معامله واقعی" if TRADING_MODE == "REAL" else "🧪 معامله کاغذی"
    msg = (
        f"📝 *{mode_str} جدید باز شد*\n\n"
        f"🔹 *نماد:* `{symbol}/USDT` | *جهت:* `{side}`\n"
        f"🔹 *قیمت ورود:* `{price:.4f}`\n"
        f"🎯 *حد سود (TP):* `{tp:.4f}` | 🛑 *حد زیان (SL):* `{sl:.4f}`\n"
        f"⚡ *اهرم:* `{LEVERAGE}X` | *مارجین:* `${TRADE_AMOUNT_USDT:.0f}`\n"
        f"⏱ *تایم‌فریم:* `{TIMEFRAME}`"
    )
    send_telegram_msg(msg)

def close_all_open_positions():
    global PAPER_BALANCE
    if not PAPER_POSITIONS:
        return "🔄 *پوزیشن بازی برای بستن وجود ندارد.*"

    count = len(PAPER_POSITIONS)
    total_pnl_change = 0.0

    for pos in PAPER_POSITIONS[:]:
        symbol = pos['symbol']
        df = get_crypto_klines(symbol, interval_type=pos.get('timeframe', TIMEFRAME), limit=2)
        curr_p = float(df.iloc[-1]['close']) if not df.empty else pos['entry_price']
        
        entry = pos['entry_price']
        lev = pos['leverage']
        margin = pos['margin']

        if "BUY" in pos['side']:
            raw_pnl = ((curr_p - entry) / entry) * 100
        else:
            raw_pnl = ((entry - curr_p) / entry) * 100

        leveraged_pnl_pct = raw_pnl * lev
        pnl_usdt = (margin * leveraged_pnl_pct) / 100

        PAPER_BALANCE += pnl_usdt
        total_pnl_change += pnl_usdt

        pos['pnl_pct'] = leveraged_pnl_pct
        pos['pnl_usdt'] = pnl_usdt
        pos['exit_reason'] = "⚠️ خروج دستی یکباره"
        pos['close_time'] = time.strftime("%H:%M:%S")

        CLOSED_POSITIONS.append(pos)
        PAPER_POSITIONS.remove(pos)

    pnl_icon = "🟢" if total_pnl_change >= 0 else "🔴"
    return (
        f"❌ *تمام {count} پوزیشن باز به‌صورت دستی بسته شدند!*\n\n"
        f"{pnl_icon} *سود/زیان کل این خروج:* `{total_pnl_change:+.2f} USDT`\n"
        f"💰 *موجودی کل جدید:* `{PAPER_BALANCE:.2f} USDT`"
    )

def update_open_positions():
    global PAPER_BALANCE
    if not PAPER_POSITIONS:
        return

    for pos in PAPER_POSITIONS[:]:
        symbol = pos['symbol']
        df = get_crypto_klines(symbol, interval_type=pos.get('timeframe', TIMEFRAME), limit=5)
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
                f"{pnl_icon} *پوزیشن بسته شد ({exit_reason})*\n\n"
                f"🔹 *نماد:* `{symbol}/USDT` | *جهت:* `{side}` ({lev}X)\n"
                f"📊 *سود/زیان:* `{leveraged_pnl_pct:+.2f}%` (`{pnl_usdt:+.2f} USDT`)\n"
                f"💰 *موجودی کل جدید:* `{PAPER_BALANCE:.2f} USDT`"
            )
            send_telegram_msg(msg)

# ==========================================
# ۶. اسکن زنده
# ==========================================
def check_symbol(coin_symbol):
    if not IS_BOT_ACTIVE:
        return

    try:
        df = get_crypto_klines(coin_symbol, interval_type=TIMEFRAME, limit=200)
        if df.empty or len(df) < 50:
            return
            
        df = calculate_indicators(df)
        curr, prev = df.iloc[-2], df.iloc[-3]
        
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
            execute_trade(coin_symbol, 'BUY (Long)', close_p, sl, tp)
            
        elif pullback_short:
            sl = close_p + (atr_val * 1.2)
            tp = close_p - (atr_val * 1.8)
            execute_trade(coin_symbol, 'SELL (Short)', close_p, sl, tp)
    except Exception as e:
        print(f"خطا در اسکن {coin_symbol}: {e}")

# ==========================================
# ۷. توابع گزارش‌گیری
# ==========================================
def get_open_positions_report():
    if not PAPER_POSITIONS:
        return "🔄 *در حال حاضر هیچ پوزیشن بازی وجود ندارد.*"
    
    text = f"🔄 *گزارش پوزیشن‌های باز ({len(PAPER_POSITIONS)} معامله):*\n\n"
    for pos in PAPER_POSITIONS:
        sym = pos['symbol']
        df = get_crypto_klines(sym, interval_type=pos.get('timeframe', TIMEFRAME), limit=2)
        curr_p = float(df.iloc[-1]['close']) if not df.empty else pos['entry_price']
        
        entry = pos['entry_price']
        lev = pos['leverage']
        margin = pos['margin']
        
        if "BUY" in pos['side']:
            raw_pnl = ((curr_p - entry) / entry) * 100
        else:
            raw_pnl = ((entry - curr_p) / entry) * 100
            
        floating_pnl_pct = raw_pnl * lev
        floating_pnl_usdt = (margin * floating_pnl_pct) / 100
        pnl_icon = "🟢" if floating_pnl_usdt >= 0 else "🔴"
        
        text += (
            f"🔹 *نماد:* `{sym}/USDT` | `{pos['side']}` ({lev}X)\n"
            f"   • ورود: `{entry:.4f}` | قیمت فعلی: `{curr_p:.4f}`\n"
            f"   • 🎯 TP: `{pos['tp']:.4f}` | 🛑 SL: `{pos['sl']:.4f}`\n"
            f"   • {pnl_icon} سود/زیان شناور: `{floating_pnl_pct:+.2f}%` (`{floating_pnl_usdt:+.2f} USDT`)\n"
            f"   • زمان ورود: `{pos['open_time']}`\n"
            f"-----------------------------------\n"
        )
    return text

def get_closed_positions_report():
    if not CLOSED_POSITIONS:
        return "📜 *هنوز هیچ معاملاتی بسته نشده است.*"
    
    text = f"📜 *تاریخچه ۱۰ معامله بسته شده اخیر ({len(CLOSED_POSITIONS)} کل):*\n\n"
    recent_closed = CLOSED_POSITIONS[-10:][::-1]
    
    for pos in recent_closed:
        pnl_icon = "🟢" if pos['pnl_usdt'] >= 0 else "🔴"
        text += (
            f"{pnl_icon} *نماد:* `{pos['symbol']}/USDT` | `{pos['side']}` ({pos['leverage']}X)\n"
            f"   • علت خروج: `{pos['exit_reason']}`\n"
            f"   • ورود: `{pos['entry_price']:.4f}` | بسته‌شدن: `{pos['close_time']}`\n"
            f"   • سود/زیان: `{pos['pnl_pct']:+.2f}%` (`{pos['pnl_usdt']:+.2f} USDT`)\n"
            f"-----------------------------------\n"
        )
    return text

def get_pnl_report():
    total_closed = len(CLOSED_POSITIONS)
    wins = sum(1 for p in CLOSED_POSITIONS if p['pnl_usdt'] > 0)
    losses = sum(1 for p in CLOSED_POSITIONS if p['pnl_usdt'] < 0)
    win_rate = (wins / total_closed * 100) if total_closed > 0 else 0.0
    
    total_pnl_usdt = PAPER_BALANCE - INITIAL_BALANCE
    total_pnl_pct = (total_pnl_usdt / INITIAL_BALANCE) * 100

    report = (
        f"📊 *گزارش کامل PnL (اهرم {LEVERAGE}X | تایم‌فریم {TIMEFRAME})*\n\n"
        f"💵 *سرمایه اولیه:* `${INITIAL_BALANCE:.2f} USDT`\n"
        f"💰 *موجودی فعلی:* `${PAPER_BALANCE:.2f} USDT`\n"
        f"📈 *سود/زیان کل:* `{total_pnl_pct:+.2f}%` (`{total_pnl_usdt:+.2f} USDT`)\n\n"
        f"📉 *تعداد کل معاملات:* `{total_closed}`\n"
        f"🟢 *پوزیشن‌های برنده:* `{wins}`\n"
        f"🔴 *پوزیشن‌های بازنده:* `{losses}`\n"
        f"🎯 *وین‌ریت (Win Rate):* `{win_rate:.1f}%`\n"
        f"⏳ *پوزیشن‌های فعال فعلی:* `{len(PAPER_POSITIONS)}`"
    )
    return report

# ==========================================
# ۸. مدیریت دستورات و Callbackهای تلگرام
# ==========================================
def process_command(data, chat_id):
    global TIMEFRAME, LEVERAGE, INITIAL_BALANCE, PAPER_BALANCE, CLOSED_POSITIONS, PAPER_POSITIONS, IS_BOT_ACTIVE, ACTIVE_SYMBOLS, TRADING_MODE
    
    text_raw = data.strip()
    cmd = text_raw.lower()
    
    if cmd in ["/start", "/menu", "/main_menu", "menu", "🎛 منوی اصلی"]:
        IS_BOT_ACTIVE = False  # خاموش کردن اسکن موقع شروع مجدد تنظیمات
        send_welcome_mode_menu(chat_id)

    elif cmd == "/menu_analyze_coin":
        msg = "🔎 *جهت تحلیل تک‌ارز طبق استراتژی، دستور زیر را ارسال فرمایید:*\n\n`/analyze BTC` یا `/analyze ETH`"
        send_telegram_msg(msg, chat_target=chat_id)

    elif cmd.startswith("/analyze"):
        analyze_single_coin(text_raw, chat_id)

    # انتخاب حالت معامله واقعی
    elif cmd == "/mode_real":
        usdt_balance = 0.0
        if exchange:
            try:
                bal = exchange.fetch_balance()
                usdt_balance = float(bal.get('USDT', {}).get('free', 0.0))
            except Exception as e:
                print(f"خطا در استعلام موجودی: {e}")

        if usdt_balance <= 0:
            keyboard = {
                "inline_keyboard": [
                    [{"text": "🧪 شروع معاملات با موجودی کاغذی", "callback_data": "/mode_paper"}]
                ]
            }
            msg = (
                f"❌ *موجودی حساب واقعی شما در CoinEx کافی نیست!*\n\n"
                f"💼 *موجودی فعلی:* `{usdt_balance:.2f} USDT`\n"
                f"جهت استفاده از ربات، حساب کوین‌اکس خود را شارژ کنید یا حالت کاغذی را انتخاب نمایید:"
            )
            send_telegram_msg(msg, chat_target=chat_id, reply_markup=keyboard)
        else:
            TRADING_MODE = "REAL"
            PAPER_BALANCE = usdt_balance
            msg = f"🔴 *حالت معامله واقعی انتخاب شد.* (موجودی: `{usdt_balance:.2f} USDT`)\n\n۱. اهرم معاملاتی خود را انتخاب کنید:"
            send_telegram_msg(msg, chat_target=chat_id)
            send_leverage_menu(chat_id)

    # انتخاب حالت معامله کاغذی (پرسش سرمایه اولیه)
    elif cmd == "/mode_paper":
        TRADING_MODE = "PAPER"
        msg = (
            f"🧪 *حالت معامله کاغذی (Paper Trading) انتخاب شد.*\n\n"
            f"📋 *تعداد ۱۲۸ ارز پیش‌فرض در لیست اسکن قرار گرفتند.*"
        )
        send_telegram_msg(msg, chat_target=chat_id)
        send_capital_menu(chat_id)

    # تنظیم سرمایه اولیه و رفتن به گام بعدی (اهرم)
    elif cmd in ["/set_cap_500", "/set_cap_1000", "/set_cap_5000", "/set_cap_10000"]:
        cap_val = float(cmd.replace("/set_cap_", ""))
        INITIAL_BALANCE = cap_val
        PAPER_BALANCE = cap_val
        CLOSED_POSITIONS = []
        PAPER_POSITIONS = []
        send_telegram_msg(f"✅ *موجودی اولیه روی ${cap_val:.0f} دلار تنظیم شد.*", chat_target=chat_id)
        send_leverage_menu(chat_id)

    elif cmd == "/toggle_active":
        IS_BOT_ACTIVE = not IS_BOT_ACTIVE
        status_txt = "🟢 *اسکن معاملات فعال شد.*" if IS_BOT_ACTIVE else "🔴 *اسکن معاملات متوقف شد.*"
        send_telegram_msg(status_txt, chat_target=chat_id)
        send_main_menu(chat_id)
        
    elif cmd == "/close_all":
        res_msg = close_all_open_positions()
        send_telegram_msg(res_msg, chat_target=chat_id)
        send_main_menu(chat_id)
        
    elif cmd in ["/open_positions", "/open"]:
        send_telegram_msg(get_open_positions_report(), chat_target=chat_id)
        
    elif cmd in ["/closed_positions", "/closed"]:
        send_telegram_msg(get_closed_positions_report(), chat_target=chat_id)
        
    elif cmd in ["/active_coins", "/coins"]:
        send_telegram_msg(f"📋 *واچ‌لیست فعال ({len(ACTIVE_SYMBOLS)} ارز):*\n`{', '.join(ACTIVE_SYMBOLS[:35])}...`", chat_target=chat_id)

    elif cmd in ["/pnl", "/report", "/balance"]:
        send_telegram_msg(get_pnl_report(), chat_target=chat_id)
        
    # تنظیمات اهرم و رفتن به مرحله بعد (تایم‌فریم)
    elif cmd in ["/set_lev_3", "/set_lev_5", "/set_lev_10"]:
        LEVERAGE = int(cmd.replace("/set_lev_", ""))
        send_telegram_msg(f"✅ *اهرم روی {LEVERAGE}X تنظیم شد.*", chat_target=chat_id)
        send_timeframe_menu(chat_id)
        
    # تنظیمات تایم‌فریم و فعال‌سازی نهایی اسکن
    elif cmd in ["/set_tf_5m", "/set_tf_15m", "/set_tf_1h"]:
        if cmd == "/set_tf_5m": TIMEFRAME = "5min"
        elif cmd == "/set_tf_15m": TIMEFRAME = "15min"
        elif cmd == "/set_tf_1h": TIMEFRAME = "1hour"
        
        IS_BOT_ACTIVE = True  # 🚀 شروع رسمی اسکن پس از اتمام آخرین مرحله تنظیمات
        tf_display = "5 دقیقه" if TIMEFRAME == "5min" else ("15 دقیقه" if TIMEFRAME == "15min" else "1 ساعته")
        send_telegram_msg(f"🚀 *تنظیمات با موفقیت تکمیل شد! اسکن زنده روی تایم‌فریم {tf_display} فعال گردید.*", chat_target=chat_id)
        send_main_menu(chat_id)

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
    send_telegram_msg("⚡ *ربات آماده به کار است. جهت شروع تنظیمات دستور /start را ارسال کنید.*")
    while True:
        try:
            update_open_positions()
        except Exception as e:
            print(f"خطا در آپدیت پوزیشن‌ها: {e}")
            
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
