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
    return f"OK - Scalper Active! Open: {len(PAPER_POSITIONS)} | Closed: {len(CLOSED_POSITIONS)}", 200

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

# متغیرهای قابل تنظیم از تلگرام
INITIAL_BALANCE = 500.0     # سرمایه اولیه پیش‌فرض
PAPER_BALANCE = INITIAL_BALANCE
TRADE_AMOUNT_USDT = 50.0   # مارجین هر معامله
LEVERAGE = 10              # اهرم پیش‌فرض (3, 5, 10)
TIMEFRAME = "5min"         # تایم‌فریم پیش‌فرض (5min, 15min, 1hour)

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

# ==========================================
# ۲. منوی اصلی دکمه‌های شیشه‌ای
# ==========================================
def send_main_menu(chat_id):
    tf_display = "5 دقیقه" if TIMEFRAME == "5min" else ("15 دقیقه" if TIMEFRAME == "15min" else "1 ساعته")
    
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "🔄 پوزیشن‌های باز", "callback_data": "/open_positions"},
                {"text": "📜 تاریخچه معاملات بسته", "callback_data": "/closed_positions"}
            ],
            [
                {"text": "📋 واچ‌لیست ارزها", "callback_data": "/active_coins"},
                {"text": "📈 گزارش کلی PnL", "callback_data": "/pnl"}
            ],
            [
                {"text": "⏱ تغییر تایم‌فریم", "callback_data": "/menu_timeframe"},
                {"text": "⚡ تغییر اهرم", "callback_data": "/menu_leverage"}
            ],
            [
                {"text": "💰 سرمایه اولیه", "callback_data": "/menu_capital"},
                {"text": "🧠 استراتژی کلی", "callback_data": "/strategy"}
            ]
        ]
    }
    
    msg = (
        f"🎛 *پنل مدیریت هوشمند ربات معامله‌گر*\n\n"
        f"🔹 *سرمایه کل:* `${PAPER_BALANCE:.2f} USDT` (اولیه: `${INITIAL_BALANCE:.0f}`)\n"
        f"🔹 *اهرم فعال:* `{LEVERAGE}X` | *مارجین معامله:* `${TRADE_AMOUNT_USDT:.0f}`\n"
        f"🔹 *تایم‌فریم اسکن:* `{tf_display}`\n"
        f"🔹 *پوزیشن‌های فعال:* `{len(PAPER_POSITIONS)}` | *بسته‌شده:* `{len(CLOSED_POSITIONS)}`\n\n"
        f"یک گزینه را جهت مدیریت انتخاب کنید:"
    )
    send_telegram_msg(msg, chat_target=chat_id, reply_markup=keyboard)

def send_timeframe_menu(chat_id):
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "⏱ 5 دقیقه", "callback_data": "/set_tf_5m"},
                {"text": "⏱ 15 دقیقه", "callback_data": "/set_tf_15m"},
                {"text": "⏱ 1 ساعته", "callback_data": "/set_tf_1h"}
            ],
            [{"text": "🔙 بازگشت به منوی اصلی", "callback_data": "/main_menu"}]
        ]
    }
    msg = f"⏱ *انتخاب تایم‌فریم اسکن و تحلیل:*\nتایم‌فریم فعلی: `{TIMEFRAME}`"
    send_telegram_msg(msg, chat_target=chat_id, reply_markup=keyboard)

def send_leverage_menu(chat_id):
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "⚡ اهرم 3X", "callback_data": "/set_lev_3"},
                {"text": "⚡ اهرم 5X", "callback_data": "/set_lev_5"},
                {"text": "⚡ اهرم 10X", "callback_data": "/set_lev_10"}
            ],
            [{"text": "🔙 بازگشت به منوی اصلی", "callback_data": "/main_menu"}]
        ]
    }
    msg = f"⚡ *انتخاب ضریب اهرم (Leverage):*\nاهرم فعلی: `{LEVERAGE}X`"
    send_telegram_msg(msg, chat_target=chat_id, reply_markup=keyboard)

def send_capital_menu(chat_id):
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "💵 $100 دلار", "callback_data": "/set_cap_100"},
                {"text": "💵 $500 دلار", "callback_data": "/set_cap_500"},
                {"text": "💵 $1,000 دلار", "callback_data": "/set_cap_1000"}
            ],
            [{"text": "🔙 بازگشت به منوی اصلی", "callback_data": "/main_menu"}]
        ]
    }
    msg = f"💰 *تعیین سرمایه اولیه حساب مجازی:*\nبا تغییر سرمایه، آمار معاملات گذشته ریست می‌شود.\nسرمایه فعلی: `${INITIAL_BALANCE:.0f} USDT`"
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
# ۴. سیستم معاملات و آپدیت PnL
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
        "timeframe": TIMEFRAME,
        "open_time": time.strftime("%H:%M:%S")
    }
    PAPER_POSITIONS.append(trade)
    
    msg = (
        f"📝 *معامله کاغذی جدید باز شد*\n\n"
        f"🔹 *نماد:* `{symbol}/USDT` | *جهت:* `{side}`\n"
        f"🔹 *قیمت ورود:* `{price:.4f}`\n"
        f"🎯 *حد سود (TP):* `{tp:.4f}` | 🛑 *حد زیان (SL):* `{sl:.4f}`\n"
        f"⚡ *اهرم:* `{LEVERAGE}X` | *مارجین:* `${TRADE_AMOUNT_USDT:.0f}`\n"
        f"⏱ *تایم‌فریم:* `{TIMEFRAME}`"
    )
    send_telegram_msg(msg)

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
                f"{pnl_icon} *پوزیشن کاغذی بسته شد ({exit_reason})*\n\n"
                f"🔹 *نماد:* `{symbol}/USDT` | *جهت:* `{side}` ({lev}X)\n"
                f"📊 *سود/زیان مارجین:* `{leveraged_pnl_pct:+.2f}%` (`{pnl_usdt:+.2f} USDT`)\n"
                f"💰 *موجودی کل جدید:* `{PAPER_BALANCE:.2f} USDT`"
            )
            send_telegram_msg(msg)

# ==========================================
# ۵. اسکن زنده
# ==========================================
def check_symbol(coin_symbol):
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
            execute_paper_trade(coin_symbol, 'BUY (Long)', close_p, sl, tp)
            
        elif pullback_short:
            sl = close_p + (atr_val * 1.2)
            tp = close_p - (atr_val * 1.8)
            execute_paper_trade(coin_symbol, 'SELL (Short)', close_p, sl, tp)
    except Exception as e:
        print(f"خطا در اسکن {coin_symbol}: {e}")

# ==========================================
# ۶. توابع تولید گزارش معاملات باز و بسته
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
    recent_closed = CLOSED_POSITIONS[-10:][::-1] # ۱۰ معامله آخر
    
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

def get_strategy_info():
    info = (
        f"🧠 *استراتژی تحلیل و سیگنال‌دهی ربات*\n\n"
        f"1️⃣ *تشخیص روند اصلی:* با استفاده از میانگین متحرک نمایی ۲۰۰ دوره (**EMA 200**).\n"
        f"   • قیمت بالای EMA200 ➔ روند صعودی (فقط Long)\n"
        f"   • قیمت زیر EMA200 ➔ روند نزولی (فقط Short)\n\n"
        f"2️⃣ *قدرت روند:* سنجش با شاخص **ADX > 14** (تایید وجود قدرت کافی در روند).\n\n"
        f"3️⃣ *نقطه ورود (پولبک):* چرخش اندیکاتور **RSI (14)** در جهت روند.\n\n"
        f"4️⃣ *حد سود و زیان (TP / SL):* بر اساس میانگین دامنه واقعی (**ATR**).\n"
        f"   • حد سود (TP): `قیمت ورود + (ATR × 1.8)`\n"
        f"   • حد زیان (SL): `قیمت ورود - (ATR × 1.2)`"
    )
    return info

# ==========================================
# ۷. مدیریت دستورات و Callbackهای تلگرام
# ==========================================
def process_command(data, chat_id):
    global TIMEFRAME, LEVERAGE, INITIAL_BALANCE, PAPER_BALANCE, CLOSED_POSITIONS, PAPER_POSITIONS
    
    cmd = data.strip().lower()
    
    if cmd in ["/start", "/menu", "/main_menu", "menu"]:
        send_main_menu(chat_id)
    elif cmd in ["/open_positions", "/open"]:
        send_telegram_msg(get_open_positions_report(), chat_target=chat_id)
    elif cmd in ["/closed_positions", "/closed"]:
        send_telegram_msg(get_closed_positions_report(), chat_target=chat_id)
    elif cmd in ["/active_coins", "/coins"]:
        send_telegram_msg(f"📋 *واچ‌لیست فعال ({len(ACTIVE_SYMBOLS)} ارز):*\n`{', '.join(ACTIVE_SYMBOLS[:30])}...`", chat_target=chat_id)
    elif cmd in ["/pnl", "/report", "/balance"]:
        send_telegram_msg(get_pnl_report(), chat_target=chat_id)
    elif cmd in ["/strategy"]:
        send_telegram_msg(get_strategy_info(), chat_target=chat_id)
    elif cmd == "/menu_timeframe":
        send_timeframe_menu(chat_id)
    elif cmd == "/menu_leverage":
        send_leverage_menu(chat_id)
    elif cmd == "/menu_capital":
        send_capital_menu(chat_id)
    
    # تنظیمات تایم‌فریم
    elif cmd == "/set_tf_5m":
        TIMEFRAME = "5min"
        send_telegram_msg("✅ *تایم‌فریم اسکن به ۵ دقیقه تغییر یافت.*", chat_target=chat_id)
        send_main_menu(chat_id)
    elif cmd == "/set_tf_15m":
        TIMEFRAME = "15min"
        send_telegram_msg("✅ *تایم‌فریم اسکن به ۱۵ دقیقه تغییر یافت.*", chat_target=chat_id)
        send_main_menu(chat_id)
    elif cmd == "/set_tf_1h":
        TIMEFRAME = "1hour"
        send_telegram_msg("✅ *تایم‌فریم اسکن به ۱ ساعته تغییر یافت.*", chat_target=chat_id)
        send_main_menu(chat_id)
        
    # تنظیمات اهرم
    elif cmd == "/set_lev_3":
        LEVERAGE = 3
        send_telegram_msg("✅ *اهرم معاملات روی 3X تنظیم شد.*", chat_target=chat_id)
        send_main_menu(chat_id)
    elif cmd == "/set_lev_5":
        LEVERAGE = 5
        send_telegram_msg("✅ *اهرم معاملات روی 5X تنظیم شد.*", chat_target=chat_id)
        send_main_menu(chat_id)
    elif cmd == "/set_lev_10":
        LEVERAGE = 10
        send_telegram_msg("✅ *اهرم معاملات روی 10X تنظیم شد.*", chat_target=chat_id)
        send_main_menu(chat_id)
        
    # تنظیمات سرمایه
    elif cmd == "/set_cap_100":
        INITIAL_BALANCE = 100.0
        PAPER_BALANCE = 100.0
        CLOSED_POSITIONS = []
        PAPER_POSITIONS = []
        send_telegram_msg("✅ *سرمایه اولیه روی $100 دلار تنظیم و آمار ریست شد.*", chat_target=chat_id)
        send_main_menu(chat_id)
    elif cmd == "/set_cap_500":
        INITIAL_BALANCE = 500.0
        PAPER_BALANCE = 500.0
        CLOSED_POSITIONS = []
        PAPER_POSITIONS = []
        send_telegram_msg("✅ *سرمایه اولیه روی $500 دلار تنظیم و آمار ریست شد.*", chat_target=chat_id)
        send_main_menu(chat_id)
    elif cmd == "/set_cap_1000":
        INITIAL_BALANCE = 1000.0
        PAPER_BALANCE = 1000.0
        CLOSED_POSITIONS = []
        PAPER_POSITIONS = []
        send_telegram_msg("✅ *سرمایه اولیه روی $1,000 دلار تنظیم و آمار ریست شد.*", chat_target=chat_id)
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
    send_telegram_msg("🚀 *ربات معامله‌گر با دکمه‌های گزارش معاملات باز و بسته فعال شد.*")
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
            time.sleep(0.2)
            
        time.sleep(30)

if __name__ == "__main__":
    Thread(target=telegram_listener, daemon=True).start()
    Thread(target=bot_loop, daemon=True).start()
    run_flask()
