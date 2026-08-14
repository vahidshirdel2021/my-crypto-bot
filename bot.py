import os
import json
import time
import asyncio
import aiohttp
import requests
import ccxt
import pandas as pd
from threading import Thread
from flask import Flask
from strategy import calculate_indicators, get_signal, get_signal_with_reason, get_strategy_params, get_strategy_description, FILTERS, STRATEGY_CONFIG
from ui import (
    get_start_keyboard, get_balance_keyboard, get_margin_keyboard, 
    get_leverage_keyboard, get_max_positions_keyboard, get_timeframe_keyboard, 
    get_main_menu_keyboard, get_watchlist_manage_keyboard, get_strategies_menu_keyboard,
    get_bottom_menu_keyboard, get_strategies_selection_keyboard, get_filters_menu_keyboard, get_params_menu_keyboard, get_positions_keyboard
)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")

USER_SESSIONS = {}

def get_user_session(chat_id):
    if chat_id not in USER_SESSIONS:
        USER_SESSIONS[chat_id] = {
            "is_bot_active": False,
            "trading_mode": "PAPER",
            "paper_balance": 1000.0,
            "daily_start_balance": 1000.0,
            "daily_stopped": False,
            "trade_amount_usdt": 50.0,
            "leverage": 10,
            "max_open_positions": 3,
            "timeframe": "5min",
            "active_strategy": "dynamic",
            "paper_positions": [],
            "closed_positions": [],
            "user_state": None,
            "active_symbols": ALL_SYMBOLS.copy()
        }
    return USER_SESSIONS[chat_id]

COINEX_API_KEY = os.environ.get("COINEX_API_KEY", "") or os.environ.get("coinexaccessid", "")
COINEX_SECRET = os.environ.get("COINEX_SECRET", "") or os.environ.get("coinexSecretKey", "")

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

app = Flask(__name__)

@app.route('/')
def home():
    active_count = sum(1 for s in USER_SESSIONS.values() if s["is_bot_active"])
    return f"OK - Active Sessions: {len(USER_SESSIONS)} | Active Bots: {active_count}", 200

@app.route('/health')
def health():
    return "OK", 200

def send_telegram_msg(message, chat_target=None, reply_markup=None, message_id=None):
    if not TELEGRAM_TOKEN: return False
    target = chat_target or list(USER_SESSIONS.keys())[0] if USER_SESSIONS else None
    if not target: return False
    session = get_user_session(target)
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
        payload["reply_markup"] = get_bottom_menu_keyboard(session["is_bot_active"])

    try:
        return requests.post(url, json=payload, timeout=10).status_code == 200
    except:
        return False

async def get_crypto_klines_async(session, coin_symbol, interval_type="5min"):
    coin_symbol = coin_symbol.upper().replace("USDT", "").replace("/", "").strip()
    url = f"https://api.kucoin.com/api/v1/market/candles?symbol={coin_symbol}-USDT&type={interval_type}"
    try:
        async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5) as res:
            if res.status == 200:
                data = await res.json()
                if data.get("code") == "200000" and data.get("data"):
                    df = pd.DataFrame(data["data"], columns=['timestamp', 'open', 'close', 'high', 'low', 'volume', 'turnover'])
                    df = df.iloc[::-1].reset_index(drop=True)
                    for col in ['open', 'high', 'low', 'close', 'volume']:
                        df[col] = df[col].astype(float)
                    if not df.empty and len(df) > 30:
                        return df
    except: pass
    return pd.DataFrame()

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

def generate_market_health_report(session):
    benchmarks = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP']
    up_count = 0
    total_adx = 0
    valid_coins = 0
    tf = session["timeframe"]
    
    for sym in benchmarks:
        df = get_crypto_klines(sym, interval_type=tf, limit=100)
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
        rec_adx = "عالی برای روندپیروی"
    elif avg_adx >= 20:
        regime = "فاز گذار / نوسانی معتدل (Transition)"
        rec_adx = "پیشنهاد احتیاط یا استفاده از تایم بالاتر"
    else:
        regime = "رنج و خنثی (Ranging / Chop)"
        rec_adx = "بازار کم‌روند؛ تمرکز بر شورت احتیاطی یا رنج"
        
    trend_str = "صعودی (Bullish)" if bullish_pct >= 60 else ("نزولی (Bearish)" if bullish_pct <= 40 else "خنثی / مخلوط (Mixed)")
    
    report = (
        f"📊 *گزارش هوشمند وضعیت بازار*\n\n"
        f"• **روند کلی:** `{trend_str}` ({up_count}/{valid_coins} ارز بالای EMA50)\n"
        f"• **میانگین ADX:** `{avg_adx:.1f}`\n"
        f"• **رژیم بازار:** `{regime}`\n\n"
        f"💡 *توصیه:* `{rec_adx}`"
    )
    return report

def send_main_menu(chat_id, message_id=None):
    session = get_user_session(chat_id)
    tf_map_display = {"5min": "5م", "15min": "15م", "1hour": "1س", "4hour": "4ساعته", "1day": "روزانه", "multi": "مولتی آبشاری"}
    tf_display = tf_map_display.get(session["timeframe"], session["timeframe"])
    status_str = "فعال (در حال اسکن)" if session["is_bot_active"] else "متوقف شده"
    mode_str = "معامله واقعی" if session["trading_mode"] == "REAL" else "معامله کاغذی"
    max_pos = f"{session['max_open_positions']}" if session["max_open_positions"] > 0 else "نامحدود"
    
    msg = (
        f"📊 *پنل مدیریت پیشرفته ربات معامله‌گر*\n\n"
        f"• حالت: `{mode_str}`\n"
        f"• وضعیت: `{status_str}`\n"
        f"• استراتژی فعال: `{session['active_strategy'].upper()}`\n"
        f"• موجودی حساب: `${session['paper_balance']:.2f} USDT`\n"
        f"• مارجین هر معامله: `${session['trade_amount_usdt']:.0f} USDT`\n"
        f"• اهرم: `{session['leverage']}X` | پوزیشن: `{max_pos}`\n"
        f"• تایم‌فریم: `{tf_display}`\n"
        f"• تعداد واچ‌لیست: `{len(session['active_symbols'])}`"
    )
    keyboard = get_main_menu_keyboard(session["is_bot_active"])
    send_telegram_msg(msg, chat_target=chat_id, reply_markup=keyboard, message_id=message_id)

def execute_trade(chat_id, symbol, side, price, sl, tp):
    session = get_user_session(chat_id)
    if not session["is_bot_active"] or session["daily_stopped"]: return
    if FILTERS["no_short_filter"] and ("SELL" in side or "Short" in side): return
    if FILTERS["no_buy_filter"] and ("BUY" in side or "Long" in side): return
    if session["max_open_positions"] > 0 and len(session["paper_positions"]) >= session["max_open_positions"]: return
    for pos in session["paper_positions"]:
        if pos['symbol'] == symbol: return

    margin = session["trade_amount_usdt"]

    if session["trading_mode"] == "REAL" and exchange:
        try:
            notional = margin * session["leverage"]
            amount = notional / price
            try:
                exchange.set_leverage(session["leverage"], f"{symbol}/USDT:USDT")
            except:
                pass

            order = exchange.create_order(
                symbol=f"{symbol}/USDT:USDT",
                type='market',
                side='buy' if "BUY" in side else 'sell',
                amount=amount
            )
            exec_price = float(order.get('average', price) or price)

            trade = {
                "symbol": symbol, "side": side, "entry_price": exec_price,
                "sl": sl, "tp": tp, "margin": margin,
                "leverage": session["leverage"], "timeframe": session["timeframe"],
                "close_timestamp": None, "pnl_usdt": 0.0, "trailing_activated": False,
                "is_real": True
            }
            session["paper_positions"].append(trade)
            side_icon = "🟢" if "BUY" in side or "Long" in side else "🔴"
            send_telegram_msg(
                f"🔴 *سفارش واقعی در صرافی کوینکس ثبت شد ({side_icon} {side})*\n"
                f"• نماد: `{symbol}`\n"
                f"• قیمت اجرایی: `{exec_price:.4f}`\n"
                f"• مارجین: `${margin:.1f} USDT` (اهرم {session['leverage']}X)\n"
                f"• TP: `{tp:.4f}` | SL: `{sl:.4f}`",
                chat_target=chat_id
            )
            return
        except Exception as e:
            send_telegram_msg(f"❌ خطا در ثبت سفارش واقعی در صرافی کوینکس: {e}", chat_target=chat_id)
            return

    if session["paper_balance"] < margin: return

    trade = {
        "symbol": symbol, "side": side, "entry_price": price,
        "sl": sl, "tp": tp, "margin": margin,
        "leverage": session["leverage"], "timeframe": session["timeframe"],
        "close_timestamp": None, "pnl_usdt": 0.0, "trailing_activated": False,
        "is_real": False
    }
    session["paper_positions"].append(trade)
    side_icon = "🟢" if "BUY" in side or "Long" in side else "🔴"
    send_telegram_msg(
        f"📝 *معامله جدید کاغذی {side_icon} ({side})*\n"
        f"• نماد: `{symbol}`\n"
        f"• ورود: `{price:.4f}`\n"
        f"• مارجین: `${margin:.1f} USDT`\n"
        f"• TP: `{tp:.4f}` | SL: `{sl:.4f}`",
        chat_target=chat_id
    )

def close_position_manually(chat_id, pos, current_price=None):
    session = get_user_session(chat_id)
    if pos not in session["paper_positions"]: return
    
    if current_price is None:
        df = get_crypto_klines(pos['symbol'], interval_type=pos.get('timeframe', session["timeframe"]) if pos.get('timeframe') != 'multi' else '5min', limit=2)
        current_price = float(df.iloc[-1]['close']) if not df.empty else pos['entry_price']
        
    if pos.get("is_real") and exchange:
        try:
            close_side = 'sell' if "BUY" in pos['side'] else 'buy'
            notional = pos['margin'] * pos['leverage']
            amount = notional / pos['entry_price']
            exchange.create_order(
                symbol=f"{pos['symbol']}/USDT:USDT",
                type='market',
                side=close_side,
                amount=amount,
                params={'reduceOnly': True}
            )
        except Exception as e:
            send_telegram_msg(f"⚠️ خطا در بستن پوزیشن در صرافی: {e}", chat_target=chat_id)

    if "BUY" in pos['side']:
        raw_pnl = ((current_price - pos['entry_price']) / pos['entry_price']) * 100
    else:
        raw_pnl = ((pos['entry_price'] - current_price) / pos['entry_price']) * 100
        
    pnl_usdt = (pos['margin'] * (raw_pnl * pos['leverage'])) / 100
    if not pos.get("is_real"):
        session["paper_balance"] += pnl_usdt
    pos['pnl_usdt'] = pnl_usdt
    pos['close_timestamp'] = time.time()
    
    session["closed_positions"].append(pos)
    session["paper_positions"].remove(pos)
    
    mode_text = "واقعی (صرافی)" if pos.get("is_real") else "کاغذی"
    send_telegram_msg(
        f"📌 *پوزیشن {mode_text} بسته شد.*\n"
        f"• نماد: `{pos['symbol']}`\n"
        f"• سود/زیان: `{pnl_usdt:+.2f} USDT`",
        chat_target=chat_id
    )

def update_open_positions(chat_id):
    session = get_user_session(chat_id)
    if not session["paper_positions"]: return

    for pos in session["paper_positions"][:]:
        df = get_crypto_klines(pos['symbol'], interval_type=pos.get('timeframe', session["timeframe"]) if pos.get('timeframe') != 'multi' else '5min', limit=5)
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
                send_telegram_msg(f"🛡️ *تریلینگ استاپ فعال شد*\n• نماد: `{pos['symbol']}`\n• حد ضرر به نقطه سر‌به‌سر منتقل شد.", chat_target=chat_id)

        closed, raw_pnl = False, 0.0
        if "BUY" in pos['side']:
            if high >= pos['tp']: closed, raw_pnl = True, ((pos['tp'] - pos['entry_price']) / pos['entry_price']) * 100
            elif low <= pos['sl']: closed, raw_pnl = True, ((pos['sl'] - pos['entry_price']) / pos['entry_price']) * 100
        else:
            if low <= pos['tp']: closed, raw_pnl = True, ((pos['entry_price'] - pos['tp']) / pos['entry_price']) * 100
            elif high >= pos['sl']: closed, raw_pnl = True, ((pos['entry_price'] - high) / pos['entry_price']) * 100

        if closed:
            close_position_manually(chat_id, pos, current_price=current_price)

async def check_symbol_async(session_data, chat_id, coin_symbol):
    session = get_user_session(chat_id)
    if not session["is_bot_active"] or session["daily_stopped"]: return
    tf = session["timeframe"]
    strat = session["active_strategy"]
    try:
        market_data = {}
        if tf == "multi" or strat == "multi":
            for tf_key, tf_val in [('1d', '1day'), ('4h', '4hour'), ('1h', '1hour'), ('15m', '15min'), ('5m', '5min')]:
                df_t = await get_crypto_klines_async(session_data, coin_symbol, interval_type=tf_val)
                if not df_t.empty:
                    market_data[tf_key] = calculate_indicators(df_t)
            df_5m = market_data.get('5m')
            if df_5m is None or df_5m.empty or len(df_5m) < 50: return
            df_primary = calculate_indicators(df_5m)
        else:
            tf_api_map = {"5min": "5min", "15min": "15min", "1hour": "1hour", "4hour": "4hour", "1day": "1day"}
            api_tf = tf_api_map.get(tf, "5min")
            df_primary = await get_crypto_klines_async(session_data, coin_symbol, interval_type=api_tf)
            if df_primary.empty or len(df_primary) < 50: return
            df_primary = calculate_indicators(df_primary)
        
        signal, _ = get_signal_with_reason(df_primary, market_data_dict=market_data, timeframe_mode="single", timeframe=tf, strategy_type=strat)
        
        if not signal: return
        
        curr = df_primary.iloc[-2]
        close_p = float(curr['close'])
        atr = float(curr['atr'])
        p = get_strategy_params(tf)
        
        if signal == "BUY":
            execute_trade(chat_id, coin_symbol, 'BUY (Long)', close_p, close_p - (atr * p["sl"]), close_p + (atr * p["tp"]))
        elif signal == "SELL":
            execute_trade(chat_id, coin_symbol, 'SELL (Short)', close_p, close_p + (atr * p["sl"]), close_p - (atr * p["tp"]))
    except: pass

def analyze_symbol_detailed(chat_id, text_val):
    session = get_user_session(chat_id)
    tf = session["timeframe"]
    df = get_crypto_klines(text_val, interval_type="5min" if tf=="multi" else ("1hour" if tf=="1hour" else ("1day" if tf=="1day" else "5min")), limit=100)
    if df.empty or len(df) < 50:
        return f"❌ اطلاعات کافی برای نماد `{text_val}` یافت نشد."
    
    df = calculate_indicators(df)
    curr = df.iloc[-2]
    adx_val = float(curr.get('adx', 20))
    rsi_val = float(curr.get('rsi', 50))
    
    res_trend, reason_trend = strategy_trend_following(df, tf)
    res_breakout, reason_breakout = strategy_breakout(df)
    res_rsi, reason_rsi = strategy_mean_reversion(df)
    
    report = (
        f"🔍 *تحلیل جامع و ارزیابی استراتژی‌ها برای `{text_val}`*\n\n"
        f"• قیمت فعلی: `{curr['close']}`\n"
        f"• EMA20: `{curr['ema20']:.2f}` | EMA50: `{curr['ema50']:.2f}`\n"
        f"• ADX: `{adx_val:.1f}` | RSI: `{rsi_val:.1f}`\n\n"
        f"📋 *بررسی استراتژی‌ها:*\n"
        f"1️⃣ **روندپیروی (Trend):** `{reason_trend}`\n"
        f"2️⃣ **شکست کانال (Breakout):** `{reason_breakout}`\n"
        f"3️⃣ **بازگشت به میانگین (RSI):** `{reason_rsi}`\n\n"
    )
    
    if adx_val < 20:
        report += "💡 *ارزیابی کلی:* بازار کم‌روند (رنج). استراتژی‌های روندپیروی ممکن است سیگنال فیک بدهند؛ با احتیاط عمل کنید."
    elif adx_val > 25:
        report += "💡 *ارزیابی کلی:* روند پرقدرت حاکم است. استراتژی‌های روندپیروی و شکست کانال عملکرد مناسبی دارند."
    else:
        report += "💡 *ارزیابی کلی:* فاز گذار بازار. منتظر تثبیت یا کندل تاییدیه باشید."
        
    return report

def process_command(data, chat_id, message_id=None):
    session = get_user_session(chat_id)
    cmd = data.strip()
    cmd_lower = cmd.lower()
    
    if cmd_lower.startswith("/close_") and cmd_lower != "/close_shorts":
        symbol_to_close = cmd_lower.replace("/close_", "").upper()
        found = False
        for pos in session["paper_positions"][:]:
            if pos['symbol'] == symbol_to_close:
                close_position_manually(chat_id, pos)
                found = True
                break
        if not found:
            send_telegram_msg(f"❌ پوزیشنی با نماد `{symbol_to_close}` یافت نشد.", chat_target=chat_id)
        return

    if cmd_lower == "/close_shorts":
        shorts = [p for p in session["paper_positions"] if "SELL" in p['side'] or "Short" in p['side']]
        if not shorts:
            send_telegram_msg("❌ پوزیشن شورت فعالی وجود ندارد.", chat_target=chat_id)
            return
        for pos in shorts:
            close_position_manually(chat_id, pos)
        return

    setting_commands = ["/check_wizard", "مدیریت تنظیمات معامله", "/mode_paper", "/mode_real", "/set_bal_", "/set_margin_", "/set_lev_", "/set_max_", "/set_tf_"]
    if session["is_bot_active"] and any(cmd_lower.startswith(sc) or sc in cmd_lower for sc in setting_commands):
        send_telegram_msg("⚠️ *اسکن بازار فعال است!*\n\nبرای تغییر تنظیمات ابتدا دکمه «توقف اسکن» را بزنید.", chat_target=chat_id)
        return

    if "منوی اصلی" in cmd or cmd_lower == "/menu":
        session["user_state"] = None
        send_main_menu(chat_id, message_id=message_id)
        return
    elif "گزارش وضعیت بازار" in cmd or cmd_lower == "/market_report":
        send_telegram_msg("🔄 *در حال تحلیل و اسکن بازار...*", chat_target=chat_id)
        report_msg = generate_market_health_report(session)
        send_telegram_msg(report_msg, chat_target=chat_id)
        return
    elif "تنظیم پارامترها" in cmd or cmd_lower == "/params_menu":
        send_telegram_msg("🎛️ *مدیریت و تنظیم دستی پارامترهای استراتژی*", chat_target=chat_id, reply_markup=get_params_menu_keyboard())
        return
    elif cmd_lower == "/adx_up":
        STRATEGY_CONFIG["min_adx"] = min(50, STRATEGY_CONFIG["min_adx"] + 1)
        send_telegram_msg("🎛️ *تنظیمات استراتژی*", chat_target=chat_id, reply_markup=get_params_menu_keyboard(), message_id=message_id)
        return
    elif cmd_lower == "/adx_down":
        STRATEGY_CONFIG["min_adx"] = max(10, STRATEGY_CONFIG["min_adx"] - 1)
        send_telegram_msg("🎛️ *تنظیمات استراتژی*", chat_target=chat_id, reply_markup=get_params_menu_keyboard(), message_id=message_id)
        return
    elif cmd_lower == "/sl_up":
        STRATEGY_CONFIG["sl_multiplier"] = round(STRATEGY_CONFIG["sl_multiplier"] + 0.2, 1)
        send_telegram_msg("🎛️ *تنظیمات استراتژی*", chat_target=chat_id, reply_markup=get_params_menu_keyboard(), message_id=message_id)
        return
    elif cmd_lower == "/sl_down":
        STRATEGY_CONFIG["sl_multiplier"] = max(0.5, round(STRATEGY_CONFIG["sl_multiplier"] - 0.2, 1))
        send_telegram_msg("🎛️ *تنظیمات استراتژی*", chat_target=chat_id, reply_markup=get_params_menu_keyboard(), message_id=message_id)
        return
    elif cmd_lower == "/tp_up":
        STRATEGY_CONFIG["tp_multiplier"] = round(STRATEGY_CONFIG["tp_multiplier"] + 0.5, 1)
        send_telegram_msg("🎛️ *تنظیمات استراتژی*", chat_target=chat_id, reply_markup=get_params_menu_keyboard(), message_id=message_id)
        return
    elif cmd_lower == "/tp_down":
        STRATEGY_CONFIG["tp_multiplier"] = max(0.5, round(STRATEGY_CONFIG["tp_multiplier"] - 0.5, 1))
        send_telegram_msg("🎛️ *تنظیمات استراتژی*", chat_target=chat_id, reply_markup=get_params_menu_keyboard(), message_id=message_id)
        return
    elif "پوزیشن‌های باز" in cmd or cmd_lower == "/open_positions":
        if session["paper_positions"]:
            txt = f"🔄 *پوزیشن‌های باز ({len(session['paper_positions'])}):*\n"
            for p in session["paper_positions"]:
                side_icon = "🟢" if "BUY" in p['side'] or "Long" in p['side'] else "🔴"
                mode_badge = " [واقعی]" if p.get("is_real") else ""
                txt += f"{side_icon} • `{p['symbol']}` ({p['side']}){mode_badge}\n  - ورود: `{p['entry_price']}` | مارجین: `${p['margin']:.1f}`\n"
            keyboard = get_positions_keyboard(session["paper_positions"])
            send_telegram_msg(txt, chat_target=chat_id, reply_markup=keyboard)
        else:
            send_telegram_msg("پوزیشن بازی وجود ندارد.", chat_target=chat_id)
        return
    elif "گزارش عملکرد" in cmd or cmd_lower == "/performance":
        wins_long = [p for p in session["closed_positions"] if p.get('pnl_usdt', 0) > 0 and ("BUY" in p['side'] or "Long" in p['side'])]
        losses_long = [p for p in session["closed_positions"] if p.get('pnl_usdt', 0) <= 0 and ("BUY" in p['side'] or "Long" in p['side'])]
        wins_short = [p for p in session["closed_positions"] if p.get('pnl_usdt', 0) > 0 and ("SELL" in p['side'] or "Short" in p['side'])]
        losses_short = [p for p in session["closed_positions"] if p.get('pnl_usdt', 0) <= 0 and ("SELL" in p['side'] or "Short" in p['side'])]
        total_pnl = sum(p.get('pnl_usdt', 0) for p in session["closed_positions"])
        
        send_telegram_msg(
            f"📈 *گزارش عملکرد تخصصی (خرید و فروش)*\n\n"
            f"🟢 *معاملات خرید (Long):*\n"
            f"• موفق: `{len(wins_long)}` | ناموفق: `{len(losses_long)}`\n\n"
            f"🔴 *معاملات فروش (Short):*\n"
            f"• موفق: `{len(wins_short)}` | ناموفق: `{len(losses_short)}`\n\n"
            f"💰 *سود/زیان کل خالص:* `{total_pnl:+.2f} USDT`\n"
            f"🏦 *مانده فعلی:* `${session['paper_balance']:.2f} USDT`",
            chat_target=chat_id
        )
        return
    elif "مدیریت تنظیمات معامله" in cmd or cmd_lower == "/check_wizard":
        if session["is_bot_active"]:
            send_telegram_msg("⚠️ *اسکن بازار فعال است!* ابتدا اسکن را متوقف کنید.", chat_target=chat_id)
        else:
            send_telegram_msg("⚙️ *مدیریت تنظیمات معامله*\n\nپارامتر مورد نظر را انتخاب کنید:", chat_target=chat_id, reply_markup=get_margin_keyboard())
        return
    elif "تنظیمات فیلترها" in cmd or cmd_lower == "/filters_menu":
        send_telegram_msg("⚙️ *مدیریت و کنترل فیلترهای استراتژی*", chat_target=chat_id, reply_markup=get_filters_menu_keyboard())
        return
    elif cmd_lower == "/toggle_vol":
        FILTERS["volume_filter"] = not FILTERS["volume_filter"]
        send_telegram_msg("⚙️ *تنظیمات فیلترها*", chat_target=chat_id, reply_markup=get_filters_menu_keyboard(), message_id=message_id)
        return
    elif cmd_lower == "/toggle_trail":
        FILTERS["trailing_stop"] = not FILTERS["trailing_stop"]
        send_telegram_msg("⚙️ *تنظیمات فیلترها*", chat_target=chat_id, reply_markup=get_filters_menu_keyboard(), message_id=message_id)
        return
    elif cmd_lower == "/toggle_candle":
        FILTERS["candlestick_filter"] = not FILTERS["candlestick_filter"]
        send_telegram_msg("⚙️ *تنظیمات فیلترها*", chat_target=chat_id, reply_markup=get_filters_menu_keyboard(), message_id=message_id)
        return
    elif cmd_lower == "/toggle_short":
        FILTERS["no_short_filter"] = not FILTERS["no_short_filter"]
        send_telegram_msg("⚙️ *تنظیمات فیلترها*", chat_target=chat_id, reply_markup=get_filters_menu_keyboard(), message_id=message_id)
        return
    elif cmd_lower == "/toggle_buy":
        FILTERS["no_buy_filter"] = not FILTERS["no_buy_filter"]
        send_telegram_msg("⚙️ *تنظیمات فیلترها*", chat_target=chat_id, reply_markup=get_filters_menu_keyboard(), message_id=message_id)
        return
    elif "شروع اسکن" in cmd or "توقف اسکن" in cmd or "روشن کردن اسکن" in cmd or cmd_lower == "/toggle_active":
        if not session["is_bot_active"] and session["daily_stopped"]:
            session["daily_start_balance"] = session["paper_balance"]
            session["daily_stopped"] = False
            send_telegram_msg("✅ سقف ضرر روزانه ریست شد و اسکن ادامه می‌یابد.", chat_target=chat_id)
        
        session["is_bot_active"] = not session["is_bot_active"]
        send_main_menu(chat_id, message_id=message_id)
        return

    if cmd_lower == "/start":
        session["is_bot_active"] = False
        session["daily_stopped"] = False
        session["user_state"] = None
        send_telegram_msg("🤖 *به ربات معامله‌گر خوش آمدید.*\n\nنوع حساب معاملاتی خود را انتخاب کنید:", chat_target=chat_id, reply_markup=get_start_keyboard(), message_id=message_id)
    elif cmd_lower == "/mode_paper":
        session["trading_mode"] = "PAPER"
        send_telegram_msg("⚙️ موجودی اولیه حساب کاغذی:", chat_target=chat_id, reply_markup=get_balance_keyboard(), message_id=message_id)
    elif cmd_lower.startswith("/set_bal_"):
        bal_val = float(cmd_lower.replace("/set_bal_", ""))
        session["paper_balance"] = bal_val
        session["daily_start_balance"] = bal_val
        session["daily_stopped"] = False
        send_telegram_msg(f"✅ موجودی روی `{bal_val} USDT` تنظیم شد.\n\n⚙️ مقدار مارجین:", chat_target=chat_id, reply_markup=get_margin_keyboard(), message_id=message_id)
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
            send_telegram_msg("❌ موجودی حساب واقعی شما در صرافی صفر است یا کلیدها نامعتبرند.", chat_target=chat_id)
        else:
            session["trading_mode"] = "REAL"
            session["paper_balance"] = usdt_balance
            session["daily_start_balance"] = usdt_balance
            session["daily_stopped"] = False
            send_telegram_msg(f"🔴 موجودی واقعی شناسایی شد: `{usdt_balance:.2f} USDT`\n\n⚙️ مارجین هر معامله:", chat_target=chat_id, reply_markup=get_margin_keyboard(), message_id=message_id)
    elif cmd_lower == "/strategies_menu":
        send_telegram_msg("📊 *انتخاب استراتژی معاملاتی*", chat_target=chat_id, reply_markup=get_strategies_selection_keyboard())
        return
    elif cmd_lower.startswith("/set_strat_"):
        strat_key = cmd_lower.replace("/set_strat_", "")
        if strat_key in ["dynamic", "trend", "breakout", "mean_reversion", "multi"]:
            session["active_strategy"] = strat_key
            send_telegram_msg(f"✅ استراتژی فعال تغییر کرد به: `{strat_key.upper()}`", chat_target=chat_id)
            send_main_menu(chat_id, message_id=message_id)
        return
    elif cmd_lower == "/analyze_single":
        session["user_state"] = "WAITING_FOR_SINGLE_SYMBOL"
        send_telegram_msg("🔍 نام رمزارز مورد نظر (مثلاً `BTC`) را ارسال کنید:", chat_target=chat_id)
    elif cmd_lower == "/manage_watchlist":
        send_telegram_msg(f"📋 *مدیریت واچ‌لیست*\nتعداد: `{len(session['active_symbols'])}`", chat_target=chat_id, reply_markup=get_watchlist_manage_keyboard())
    elif cmd_lower == "/add_symbol_prompt":
        session["user_state"] = "WAITING_FOR_ADD_SYMBOL"
        send_telegram_msg("➕ نماد جدید برای افزودن:", chat_target=chat_id)
    elif cmd_lower == "/remove_symbol_prompt":
        session["user_state"] = "WAITING_FOR_REMOVE_SYMBOL"
        send_telegram_msg("➖ نماد برای حذف:", chat_target=chat_id)
    elif cmd_lower == "/close_all":
        session["is_bot_active"] = False
        count = len(session["paper_positions"])
        for pos in session["paper_positions"][:]:
            close_position_manually(chat_id, pos)
        send_telegram_msg(f"🛑 اسکن متوقف شد!\n❌ کل پوزیشن‌ها (`{count}`) بسته شدند.", chat_target=chat_id)
        send_main_menu(chat_id, message_id=message_id)
    elif cmd_lower in ["/set_margin_10", "/set_margin_25", "/set_margin_50", "/set_margin_100"]:
        session["trade_amount_usdt"] = float(cmd_lower.replace("/set_margin_", ""))
        send_telegram_msg("⚙️ ضریب اهرم (Leverage):", chat_target=chat_id, reply_markup=get_leverage_keyboard(), message_id=message_id)
    elif cmd_lower in ["/set_lev_3", "/set_lev_5", "/set_lev_10"]:
        session["leverage"] = int(cmd_lower.replace("/set_lev_", ""))
        send_telegram_msg("⚙️ حداکثر تعداد پوزیشن‌های هم‌زمان:", chat_target=chat_id, reply_markup=get_max_positions_keyboard(), message_id=message_id)
    elif cmd_lower.startswith("/set_max_"):
        session["max_open_positions"] = int(cmd_lower.replace("/set_max_", ""))
        send_telegram_msg("⚙️ تایم‌فریم معاملاتی:", chat_target=chat_id, reply_markup=get_timeframe_keyboard(), message_id=message_id)
    elif cmd_lower in ["/set_tf_5m", "/set_tf_15m", "/set_tf_1h", "/set_tf_4h", "/set_tf_1d", "/set_tf_multi"]:
        if cmd_lower == "/set_tf_5m": session["timeframe"] = "5min"
        elif cmd_lower == "/set_tf_15m": session["timeframe"] = "15min"
        elif cmd_lower == "/set_tf_1h": session["timeframe"] = "1hour"
        elif cmd_lower == "/set_tf_4h": session["timeframe"] = "4hour"
        elif cmd_lower == "/set_tf_1d": session["timeframe"] = "1day"
        elif cmd_lower == "/set_tf_multi": session["timeframe"] = "multi"
        send_telegram_msg("🚀 تنظیمات اعمال شد.", chat_target=chat_id)
        send_main_menu(chat_id, message_id=message_id)

def telegram_listener():
    last_id = None
    while True:
        try:
            res = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates", params={"offset": last_id}, timeout=15)
            if res.status_code == 200:
                for r in res.json().get("result", []):
                    last_id = r["update_id"] + 1
                    chat_id = r.get("callback_query", {}).get("message", {}).get("chat", {}).get("id") or r.get("message", {}).get("chat", {}).get("id")
                    if not chat_id: continue
                    session = get_user_session(chat_id)
                    data = r.get("callback_query", {}).get("data") or r.get("message", {}).get("text")
                    msg_id = r.get("callback_query", {}).get("message", {}).get("message_id")
                    
                    if data:
                        is_menu_btn = any(k in data for k in ["منوی اصلی", "پوزیشن‌های باز", "گزارش عملکرد", "مدیریت تنظیمات معامله", "شروع اسکن", "توقف اسکن", "روشن کردن اسکن", "تنظیمات فیلترها", "گزارش وضعیت بازار", "تنظیم پارامترها"])
                        if not data.startswith("/") and not is_menu_btn:
                            text_val = data.strip().upper()
                            if session["user_state"] == "WAITING_FOR_SINGLE_SYMBOL":
                                report_text = analyze_symbol_detailed(chat_id, text_val)
                                send_telegram_msg(report_text, chat_target=chat_id)
                                session["user_state"] = None
                            elif session["user_state"] == "WAITING_FOR_ADD_SYMBOL":
                                if text_val not in session["active_symbols"]:
                                    session["active_symbols"].append(text_val)
                                    send_telegram_msg(f"✅ نماد `{text_val}` اضافه شد.", chat_target=chat_id)
                                else:
                                    send_telegram_msg(f"⚠️ نماد از قبل موجود است.", chat_target=chat_id)
                                session["user_state"] = None
                            elif session["user_state"] == "WAITING_FOR_REMOVE_SYMBOL":
                                if text_val in session["active_symbols"]:
                                    session["active_symbols"].remove(text_val)
                                    send_telegram_msg(f"🗑️ نماد `{text_val}` حذف شد.", chat_target=chat_id)
                                else:
                                    send_telegram_msg(f"❌ نماد یافت نشد.", chat_target=chat_id)
                                session["user_state"] = None
                            else:
                                # اصلاح تشخیص مستقیم نام ارز در چت
                                if len(text_val) >= 2 and len(text_val) <= 8 and text_val.isalpha():
                                    report_text = analyze_symbol_detailed(chat_id, text_val)
                                    send_telegram_msg(report_text, chat_target=chat_id)
                                else:
                                    process_command(data, chat_id, message_id=msg_id)
                        else:
                            session["user_state"] = None
                            process_command(data, chat_id, message_id=msg_id)
        except: pass
        time.sleep(2)

async def async_main_scan_loop():
    while True:
        try:
            for chat_id, session in list(USER_SESSIONS.items()):
                if session["paper_positions"]:
                    update_open_positions(chat_id)
        except: pass
        
        async with aiohttp.ClientSession() as session_http:
            for chat_id, session in list(USER_SESSIONS.items()):
                if session["is_bot_active"] and not session["daily_stopped"]:
                    tasks = [check_symbol_async(session_http, chat_id, sym) for sym in session["active_symbols"]]
                    await asyncio.gather(*tasks)
                
        await asyncio.sleep(30)

def bot_loop():
    time.sleep(5)
    asyncio.run(async_main_scan_loop())

if __name__ == "__main__":
    Thread(target=telegram_listener, daemon=True).start()
    Thread(target=bot_loop, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
