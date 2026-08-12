import os
import json
import time
import requests
import ccxt
import pandas as pd
from threading import Thread
from flask import Flask
from strategy import calculate_indicators, get_signal, get_signal_with_reason, get_strategy_params, get_strategy_description, FILTERS
from ui import (
    get_start_keyboard, get_balance_keyboard, get_margin_keyboard, 
    get_leverage_keyboard, get_max_positions_keyboard, get_timeframe_keyboard, 
    get_main_menu_keyboard, get_watchlist_manage_keyboard, get_strategies_menu_keyboard,
    get_bottom_menu_keyboard, get_strategies_selection_keyboard, get_filters_menu_keyboard
)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8931433787:AAEdgjh8du4c-gLEF7DQA7H8xAzs6O0p7mw")
CHAT_ID = os.environ.get("CHAT_ID", "1878257830")

IS_BOT_ACTIVE = False
TRADING_MODE = "PAPER"
PAPER_BALANCE = 1000.0
DAILY_START_BALANCE = 1000.0
DAILY_STOPPED = False
TRADE_AMOUNT_USDT = 50.0
LEVERAGE = 10
MAX_OPEN_POSITIONS = 3
TIMEFRAME = "5min"
ACTIVE_STRATEGY = "dynamic"

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

app = Flask(__name__)

@app.route('/')
def home():
    status_str = "ACTIVE" if IS_BOT_ACTIVE else "PAUSED"
    return f"OK - Mode: {TRADING_MODE} | Status: {status_str} | Strategy: {ACTIVE_STRATEGY} | TF: {TIMEFRAME} | Watchlist: {len(ACTIVE_SYMBOLS)}", 200

@app.route('/health')
def health():
    return "OK", 200

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
    if reply_markup:
        payload["reply_markup"] = reply_markup
    else:
        payload["reply_markup"] = get_bottom_menu_keyboard(IS_BOT_ACTIVE)

    try:
        return requests.post(url, json=payload, timeout=10).status_code == 200
    except:
        return False

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

def generate_market_health_report():
    benchmarks = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP']
    up_count = 0
    total_adx = 0
    valid_coins = 0
    
    for sym in benchmarks:
        df = get_crypto_klines(sym, interval_type=TIMEFRAME, limit=100)
        if not df.empty and len(df) > 50:
            df = calculate_indicators(df)
            curr = df.iloc[-2]
            if curr['close'] > curr['ema50']:
                up_count += 1
            total_adx += float(curr['adx'])
            valid_coins += 1
            
    if valid_coins == 0:
        return "❌ خطا در دریافت اطلاعات از بازار برای ارزهای مرجع."
        
    avg_adx = total_adx / valid_coins
    bullish_pct = (up_count / valid_coins) * 100
    
    if avg_adx > 25:
        regime = "رونددار پرقدرت (Trending)"
        rec_adx = "عالی برای روندپیروی (حساسیت فعلی مناسب است)"
    elif avg_adx >= 20:
        regime = "فاز گذار / نوسانی معتدل (Transition)"
        rec_adx = "پیشنهاد افزایش حساسیت ADX به 25 یا استفاده از تایم بالاتر"
    else:
        regime = "رنج و خنثی (Ranging / Chop)"
        rec_adx = "بازار کم‌روند؛ پیشنهاد استفاده از استراتژی RSI یا توقف موقت"
        
    trend_str = "صعودی (Bullish)" if bullish_pct >= 60 else ("نزولی (Bearish)" if bullish_pct <= 40 else "خنثی / مخلوط (Mixed)")
    
    report = (
        f"📊 *گزارش هوشمند وضعیت بازار (Market Regime)*\n\n"
        f"• **روند کلی سبد مرجع:** `{trend_str}` ({up_count}/{valid_coins} ارز بالای EMA50)\n"
        f"• **میانگین قدرت روند (ADX):** `{avg_adx:.1f}`\n"
        f"• **تشخیص رژیم بازار:** `{regime}`\n\n"
        f"💡 *پیشنهاد استراتژیک سیستم:*\n"
        f"• **تایم‌فریم فعلی:** `{TIMEFRAME}`\n"
        f"• **وضعیت فیلتر پرایس‌آکشن:** `{'🟢 فعال' if FILTERS['candlestick_filter'] else '🔴 غیرفعال'}`\n"
        f"• **توصیه معاملاتی:** `{rec_adx}`"
    )
    return report

def send_main_menu(chat_id, message_id=None):
    tf_display = "5م" if TIMEFRAME == "5min" else ("15م" if TIMEFRAME == "15min" else ("1س" if TIMEFRAME == "1hour" else "مولتی آبشاری"))
    status_str = "فعال (در حال اسکن)" if IS_BOT_ACTIVE else "متوقف شده"
    mode_str = "معامله واقعی" if TRADING_MODE == "REAL" else "معامله کاغذی"
    max_pos = f"{MAX_OPEN_POSITIONS}" if MAX_OPEN_POSITIONS > 0 else "نامحدود"
    
    msg = (
        f"📊 *پنل مدیریت پیشرفته ربات معامله‌گر*\n\n"
        f"• حالت: `{mode_str}`\n"
        f"• وضعیت: `{status_str}`\n"
        f"• استراتژی فعال: `{ACTIVE_STRATEGY.upper()}`\n"
        f"• موجودی حساب: `${PAPER_BALANCE:.2f} USDT`\n"
        f"• مارجین هر معامله: `${TRADE_AMOUNT_USDT:.0f} USDT`\n"
        f"• اهرم: `{LEVERAGE}X` | پوزیشن: `{max_pos}`\n"
        f"• تایم‌فریم: `{tf_display}`\n"
        f"• تعداد ارزهای واچ‌لیست: `{len(ACTIVE_SYMBOLS)}`"
    )
    keyboard = get_main_menu_keyboard(IS_BOT_ACTIVE)
    send_telegram_msg(msg, chat_target=chat_id, reply_markup=keyboard, message_id=message_id)

def execute_trade(symbol, side, price, sl, tp):
    global IS_BOT_ACTIVE, PAPER_BALANCE, DAILY_STOPPED
    if not IS_BOT_ACTIVE or DAILY_STOPPED: return
    if MAX_OPEN_POSITIONS > 0 and len(PAPER_POSITIONS) >= MAX_OPEN_POSITIONS: return
    for pos in PAPER_POSITIONS:
        if pos['symbol'] == symbol: return

    margin = TRADE_AMOUNT_USDT
    if PAPER_BALANCE < margin: return

    trade = {
        "symbol": symbol, "side": side, "entry_price": price,
        "sl": sl, "tp": tp, "margin": margin,
        "leverage": LEVERAGE, "timeframe": TIMEFRAME,
        "close_timestamp": None, "pnl_usdt": 0.0, "trailing_activated": False
    }
    PAPER_POSITIONS.append(trade)
    send_telegram_msg(
        f"📝 *معامله جدید ({side})*\n"
        f"• نماد: `{symbol}`\n"
        f"• ورود: `{price:.4f}`\n"
        f"• مارجین درگیر: `${margin:.1f} USDT`\n"
        f"• TP: `{tp:.4f}` | SL: `{sl:.4f}`"
    )

def update_open_positions():
    global PAPER_BALANCE, IS_BOT_ACTIVE, DAILY_STOPPED
    if not PAPER_POSITIONS: return

    for pos in PAPER_POSITIONS[:]:
        df = get_crypto_klines(pos['symbol'], interval_type=pos.get('timeframe', TIMEFRAME) if pos.get('timeframe') != 'multi' else '5min', limit=5)
        if df.empty: continue
        high, low = float(df.iloc[-1]['high']), float(df.iloc[-1]['low'])
        current_price = float(df.iloc[-1]['close'])

        if "BUY" in pos['side']:
            current_raw_pnl = ((current_price - pos['entry_price']) / pos['entry_price']) * 100
        else:
            current_raw_pnl = ((pos['entry_price'] - current_price) / pos['entry_price']) * 100

        current_pnl_usdt = (pos['margin'] * (current_raw_pnl * pos['leverage'])) / 100

        if FILTERS["trailing_stop"] and not pos.get('trailing_activated', False):
            if current_pnl_usdt >= (pos['margin'] * 0.10):
                pos['sl'] = pos['entry_price']
                pos['trailing_activated'] = True
                send_telegram_msg(f"🛡️ *تریلینگ استاپ فعال شد*\n• نماد: `{pos['symbol']}`\n• حد ضرر به نقطه سر‌به‌سر منتقل شد.")

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

            if DAILY_START_BALANCE > 0 and not DAILY_STOPPED:
                drawdown_pct = ((DAILY_START_BALANCE - PAPER_BALANCE) / DAILY_START_BALANCE) * 100
                if drawdown_pct >= 5.0:
                    IS_BOT_ACTIVE = False
                    DAILY_STOPPED = True
                    send_telegram_msg(
                        f"🚨 *هشدار: سقف حد ضرر روزانه (۵٪) تکمیل شد!*\n\n"
                        f"• موجودی پایه روز: `{DAILY_START_BALANCE:.2f} USDT`\n"
                        f"• موجودی فعلی: `${PAPER_BALANCE:.2f} USDT`\n"
                        f"• میزان افت: `{drawdown_pct:.2f}%`\n\n"
                        f"🛑 معاملات و اسکن بازار به طور خودکار متوقف شدند.\n"
                        f"🔹 برای بررسی بازار و تایید دستی جهت ادامه فعالیت، لطفاً دکمه «شروع اسکن» را بزنید."
                    )

            send_telegram_msg(
                f"📌 *پوزیشن بسته شد.*\n"
                f"• نماد: `{pos['symbol']}`\n"
                f"• سود/زیان: `{pnl_usdt:+.2f} USDT`\n"
                f"• مانده جدید حساب: `${PAPER_BALANCE:.2f} USDT`"
            )

def check_symbol(coin_symbol):
    if not IS_BOT_ACTIVE or DAILY_STOPPED: return
    try:
        market_data = {}
        if TIMEFRAME == "multi" or ACTIVE_STRATEGY == "multi":
            for tf_key, tf_val in [('1d', '1day'), ('4h', '4hour'), ('1h', '1hour'), ('15m', '15min'), ('5m', '5min')]:
                df_t = get_crypto_klines(coin_symbol, interval_type=tf_val, limit=100)
                if not df_t.empty:
                    market_data[tf_key] = calculate_indicators(df_t)
            df_5m = market_data.get('5m')
            if df_5m is None or df_5m.empty or len(df_5m) < 50: return
            df_primary = calculate_indicators(df_5m)
        else:
            tf_api_map = {"5min": "5min", "15min": "15min", "1hour": "1hour"}
            api_tf = tf_api_map.get(TIMEFRAME, "5min")
            df_primary = get_crypto_klines(coin_symbol, interval_type=api_tf, limit=200)
            if df_primary.empty or len(df_primary) < 50: return
            df_primary = calculate_indicators(df_primary)
        
        signal, _ = get_signal_with_reason(df_primary, market_data_dict=market_data, timeframe_mode="single", timeframe=TIMEFRAME, strategy_type=ACTIVE_STRATEGY)
        
        if not signal: return
        
        curr = df_primary.iloc[-2]
        close_p = float(curr['close'])
        atr = float(curr['atr'])
        p = get_strategy_params(TIMEFRAME)
        
        if signal == "BUY":
            execute_trade(coin_symbol, 'BUY (Long)', close_p, close_p - (atr * p["sl"]), close_p + (atr * p["tp"]))
        elif signal == "SELL":
            execute_trade(coin_symbol, 'SELL (Short)', close_p, close_p + (atr * p["sl"]), close_p - (atr * p["tp"]))
    except: pass

def process_command(data, chat_id, message_id=None):
    global IS_BOT_ACTIVE, TRADING_MODE, PAPER_BALANCE, DAILY_START_BALANCE, DAILY_STOPPED, TRADE_AMOUNT_USDT, LEVERAGE, MAX_OPEN_POSITIONS, TIMEFRAME, ACTIVE_STRATEGY, USER_STATE
    cmd = data.strip()
    cmd_lower = cmd.lower()
    
    if "منوی اصلی" in cmd or cmd_lower == "/menu":
        USER_STATE = None
        send_main_menu(chat_id, message_id=message_id)
        return
    elif "گزارش وضعیت بازار" in cmd or cmd_lower == "/market_report":
        send_telegram_msg("🔄 *در حال تحلیل و اسکن وضعیت بازار (ارزهای شاخص)...*", chat_target=chat_id)
        report_msg = generate_market_health_report()
        send_telegram_msg(report_msg, chat_target=chat_id)
        return
    elif "پوزیشن‌های باز" in cmd or cmd_lower == "/open_positions":
        if PAPER_POSITIONS:
            txt = f"🔄 *پوزیشن‌های باز ({len(PAPER_POSITIONS)}):*\n"
            for p in PAPER_POSITIONS:
                txt += f"• `{p['symbol']}` ({p['side']})\n  - ورود: `{p['entry_price']}` | مارجین: `${p['margin']:.1f}`\n"
            txt += f"\n💰 *مانده حساب کل:* `${PAPER_BALANCE:.2f} USDT`"
        else:
            txt = f"پوزیشن بازی وجود ندارد.\n\n💰 *مانده حساب کل:* `${PAPER_BALANCE:.2f} USDT`"
        send_telegram_msg(txt, chat_target=chat_id)
        return
    elif "گزارش عملکرد" in cmd or cmd_lower == "/performance":
        total_pnl = sum(p.get('pnl_usdt', 0) for p in CLOSED_POSITIONS)
        wins = [p for p in CLOSED_POSITIONS if p.get('pnl_usdt', 0) > 0]
        losses = [p for p in CLOSED_POSITIONS if p.get('pnl_usdt', 0) < 0]
        send_telegram_msg(
            f"📈 *گزارش عملکرد کلی*\n\n"
            f"• کل معاملات بسته: `{len(CLOSED_POSITIONS)}`\n"
            f"• معاملات موفق: `{len(wins)}` | ناموفق: `{len(losses)}`\n"
            f"• سود/زیان کل: `{total_pnl:+.2f} USDT`\n"
            f"• مانده فعلی حساب: `${PAPER_BALANCE:.2f} USDT`",
            chat_target=chat_id
        )
        return
    elif "مدیریت تنظیمات معامله" in cmd or cmd_lower == "/check_wizard":
        if IS_BOT_ACTIVE:
            send_telegram_msg("⚠️ *اسکن بازار در حال حاضر فعال است!*\n\nبرای محافظت از موجودی و جلوگیری از تداخل در معاملات، لطفا ابتدا اسکن را متوقف کنید.", chat_target=chat_id)
        else:
            send_telegram_msg("⚙️ *مدیریت تنظیمات معامله*\n\nموجودی اولیه تثبیت شده است. لطفاً پارامتر مورد نظر را انتخاب کنید:", chat_target=chat_id, reply_markup=get_margin_keyboard())
        return
    elif "تنظیمات فیلترها" in cmd or cmd_lower == "/filters_menu":
        send_telegram_msg("⚙️ *مدیریت و کنترل فیلترهای استراتژی*\n\nبرای فعال یا غیرفعال کردن هر فیلتر روی دکمه مربوطه کلیک کنید:", chat_target=chat_id, reply_markup=get_filters_menu_keyboard())
        return
    elif cmd_lower == "/toggle_vol":
        FILTERS["volume_filter"] = not FILTERS["volume_filter"]
        send_telegram_msg("⚙️ *مدیریت و کنترل فیلترهای استراتژی*", chat_target=chat_id, reply_markup=get_filters_menu_keyboard(), message_id=message_id)
        return
    elif cmd_lower == "/toggle_trail":
        FILTERS["trailing_stop"] = not FILTERS["trailing_stop"]
        send_telegram_msg("⚙️ *مدیریت و کنترل فیلترهای استراتژی*", chat_target=chat_id, reply_markup=get_filters_menu_keyboard(), message_id=message_id)
        return
    elif cmd_lower == "/toggle_candle":
        FILTERS["candlestick_filter"] = not FILTERS["candlestick_filter"]
        send_telegram_msg("⚙️ *مدیریت و کنترل فیلترهای استراتژی*", chat_target=chat_id, reply_markup=get_filters_menu_keyboard(), message_id=message_id)
        return
    elif "شروع اسکن" in cmd or "توقف اسکن" in cmd or "روشن کردن اسکن" in cmd or cmd_lower == "/toggle_active":
        if not IS_BOT_ACTIVE and DAILY_STOPPED:
            DAILY_START_BALANCE = PAPER_BALANCE
            DAILY_STOPPED = False
            send_telegram_msg("✅ تایید دستی اعمال شد. سقف ضرر روزانه ریست شد و اسکن ادامه می‌یابد.", chat_target=chat_id)
        
        IS_BOT_ACTIVE = not IS_BOT_ACTIVE
        send_main_menu(chat_id, message_id=message_id)
        return

    if cmd_lower == "/start":
        IS_BOT_ACTIVE = False
        DAILY_STOPPED = False
        USER_STATE = None
        send_telegram_msg("🤖 *به ربات معامله‌گر خوش آمدید.*\n\nلطفاً نوع حساب معاملاتی خود را انتخاب کنید:", chat_target=chat_id, reply_markup=get_start_keyboard(), message_id=message_id)
    elif cmd_lower == "/mode_paper":
        TRADING_MODE = "PAPER"
        send_telegram_msg("⚙️ مقدار موجودی اولیه حساب کاغذی را انتخاب کنید:", chat_target=chat_id, reply_markup=get_balance_keyboard(), message_id=message_id)
    elif cmd_lower.startswith("/set_bal_"):
        bal_val = float(cmd_lower.replace("/set_bal_", ""))
        PAPER_BALANCE = bal_val
        DAILY_START_BALANCE = bal_val
        DAILY_STOPPED = False
        send_telegram_msg(f"✅ موجودی اولیه روی `{bal_val} USDT` تنظیم شد.\n\n⚙️ مقدار مارجین در هر معامله:", chat_target=chat_id, reply_markup=get_margin_keyboard(), message_id=message_id)
    elif cmd_lower == "/mode_real":
        usdt_balance = 0.0
        if exchange:
            try:
                bal = exchange.fetch_balance()
                usdt_balance = float(bal.get('total', {}).get('USDT', 0.0))
            except Exception as e:
                send_telegram_msg(f"⚠️ خطا در ارتباط با صرافی: {e}", chat_target=chat_id)
                return
        if usdt_balance <= 0:
            send_telegram_msg("❌ موجودی حساب واقعی شما در صرافی صفر است.", chat_target=chat_id)
        else:
            TRADING_MODE = "REAL"
            PAPER_BALANCE = usdt_balance
            DAILY_START_BALANCE = usdt_balance
            DAILY_STOPPED = False
            send_telegram_msg(f"🔴 موجودی واقعی شناسایی شد: `{usdt_balance:.2f} USDT`\n\n⚙️ مقدار مارجین هر معامله:", chat_target=chat_id, reply_markup=get_margin_keyboard(), message_id=message_id)
    elif cmd_lower == "/strategies_menu":
        send_telegram_msg("📊 *انتخاب استراتژی معاملاتی*\n\nمدل هوشمند یا استراتژی دلخواه خود را انتخاب کنید:", chat_target=chat_id, reply_markup=get_strategies_selection_keyboard())
        return
    elif cmd_lower.startswith("/set_strat_"):
        strat_key = cmd_lower.replace("/set_strat_", "")
        if strat_key in ["dynamic", "trend", "breakout", "mean_reversion", "multi"]:
            ACTIVE_STRATEGY = strat_key
            send_telegram_msg(f"✅ استراتژی فعال ربات با موفقیت تغییر کرد به: `{strat_key.upper()}`", chat_target=chat_id)
            send_main_menu(chat_id, message_id=message_id)
        return
    elif cmd_lower == "/analyze_single":
        USER_STATE = "WAITING_FOR_SINGLE_SYMBOL"
        send_telegram_msg("🔍 نام رمزارز مورد نظر برای تحلیل (مثلاً `BTC` یا `ETH`) را ارسال کنید:", chat_target=chat_id)
    elif cmd_lower == "/manage_watchlist":
        send_telegram_msg(f"📋 *مدیریت واچ‌لیست*\nتعداد ارزهای فعال: `{len(ACTIVE_SYMBOLS)}`", chat_target=chat_id, reply_markup=get_watchlist_manage_keyboard())
    elif cmd_lower == "/add_symbol_prompt":
        USER_STATE = "WAITING_FOR_ADD_SYMBOL"
        send_telegram_msg("➕ نماد رمزارز جدید برای افزودن به واچ‌لیست را ارسال کنید:", chat_target=chat_id)
    elif cmd_lower == "/remove_symbol_prompt":
        USER_STATE = "WAITING_FOR_REMOVE_SYMBOL"
        send_telegram_msg("➖ نماد رمزارز برای حذف از واچ‌لیست را ارسال کنید:", chat_target=chat_id)
    elif cmd_lower == "/close_all":
        IS_BOT_ACTIVE = False
        count = len(PAPER_POSITIONS)
        PAPER_POSITIONS.clear()
        send_telegram_msg(f"🛑 *اسکن متوقف شد!*\n❌ کل پوزیشن‌های باز (`{count} پوزیشن`) بسته شدند.", chat_target=chat_id)
        send_main_menu(chat_id, message_id=message_id)
    elif cmd_lower in ["/set_margin_10", "/set_margin_25", "/set_margin_50", "/set_margin_100"]:
        TRADE_AMOUNT_USDT = float(cmd_lower.replace("/set_margin_", ""))
        send_telegram_msg("⚙️ ضریب اهرم (Leverage) را انتخاب کنید:", chat_target=chat_id, reply_markup=get_leverage_keyboard(), message_id=message_id)
    elif cmd_lower in ["/set_lev_3", "/set_lev_5", "/set_lev_10"]:
        LEVERAGE = int(cmd_lower.replace("/set_lev_", ""))
        send_telegram_msg("⚙️ حداکثر تعداد پوزیشن‌های هم‌زمان:", chat_target=chat_id, reply_markup=get_max_positions_keyboard(), message_id=message_id)
    elif cmd_lower.startswith("/set_max_"):
        MAX_OPEN_POSITIONS = int(cmd_lower.replace("/set_max_", ""))
        pos_text = "بدون محدودیت" if MAX_OPEN_POSITIONS == 0 else str(MAX_OPEN_POSITIONS)
        send_telegram_msg(f"⚙️ حداکثر پوزیشن‌های هم‌زمان روی `{pos_text}` تنظیم شد.\n\nتایم‌فریم معاملاتی را انتخاب کنید:", chat_target=chat_id, reply_markup=get_timeframe_keyboard(), message_id=message_id)
    elif cmd_lower in ["/set_tf_5m", "/set_tf_15m", "/set_tf_1h", "/set_tf_multi"]:
        if cmd_lower == "/set_tf_5m": TIMEFRAME = "5min"
        elif cmd_lower == "/set_tf_15m": TIMEFRAME = "15min"
        elif cmd_lower == "/set_tf_1h": TIMEFRAME = "1hour"
        elif cmd_lower == "/set_tf_multi": TIMEFRAME = "multi"
        send_telegram_msg("🚀 تنظیمات جدید با موفقیت اعمال شد.", chat_target=chat_id)
        send_main_menu(chat_id, message_id=message_id)

def telegram_listener():
    global USER_STATE, ACTIVE_SYMBOLS
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
                    
                    if data:
                        is_menu_btn = any(k in data for k in ["منوی اصلی", "پوزیشن‌های باز", "گزارش عملکرد", "مدیریت تنظیمات معامله", "شروع اسکن", "توقف اسکن", "روشن کردن اسکن", "تنظیمات فیلترها", "گزارش وضعیت بازار"])
                        if not data.startswith("/") and not is_menu_btn:
                            text_val = data.strip().upper()
                            if USER_STATE == "WAITING_FOR_SINGLE_SYMBOL":
                                df = get_crypto_klines(text_val, interval_type="5min", limit=100)
                                if not df.empty:
                                    df = calculate_indicators(df)
                                    _, reason = get_signal_with_reason(df, timeframe=TIMEFRAME, strategy_type=ACTIVE_STRATEGY)
                                    curr = df.iloc[-2]
                                    send_telegram_msg(
                                        f"🔍 *تحلیل آنی نماد `{text_val}`*\n\n"
                                        f"• قیمت: `{curr['close']}`\n"
                                        f"• EMA20: `{curr['ema20']:.2f}` | EMA50: `{curr['ema50']:.2f}`\n"
                                        f"• ADX: `{curr['adx']:.2f}`\n\n"
                                        f"📝 *نتیجه ارزیابی استراتژی:*\n`{reason}`",
                                        chat_target=chat_id
                                    )
                                else:
                                    send_telegram_msg(f"❌ اطلاعاتی برای نماد `{text_val}` یافت نشد.", chat_target=chat_id)
                                USER_STATE = None
                            elif USER_STATE == "WAITING_FOR_ADD_SYMBOL":
                                if text_val not in ACTIVE_SYMBOLS:
                                    ACTIVE_SYMBOLS.append(text_val)
                                    send_telegram_msg(f"✅ نماد `{text_val}` به واچ‌لیست اضافه شد.", chat_target=chat_id)
                                else:
                                    send_telegram_msg(f"⚠️ نماد از قبل موجود است.", chat_target=chat_id)
                                USER_STATE = None
                            elif USER_STATE == "WAITING_FOR_REMOVE_SYMBOL":
                                if text_val in ACTIVE_SYMBOLS:
                                    ACTIVE_SYMBOLS.remove(text_val)
                                    send_telegram_msg(f"🗑️ نماد `{text_val}` حذف شد.", chat_target=chat_id)
                                else:
                                    send_telegram_msg(f"❌ نماد یافت نشد.", chat_target=chat_id)
                                USER_STATE = None
                            else:
                                process_command(data, chat_id, message_id=msg_id)
                        else:
                            USER_STATE = None
                            process_command(data, chat_id, message_id=msg_id)
        except: pass
        time.sleep(2)

def bot_loop():
    time.sleep(5)
    while True:
        try: update_open_positions()
        except: pass
        if IS_BOT_ACTIVE and not DAILY_STOPPED:
            for sym in ACTIVE_SYMBOLS:
                if not IS_BOT_ACTIVE or DAILY_STOPPED: break
                check_symbol(sym)
                time.sleep(0.2)
        time.sleep(30)

if __name__ == "__main__":
    Thread(target=telegram_listener, daemon=True).start()
    Thread(target=bot_loop, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
