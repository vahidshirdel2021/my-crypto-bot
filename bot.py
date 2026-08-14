import os, json, time, asyncio, aiohttp, requests, sqlite3, logging, math, io, hashlib, threading
from threading import Thread, RLock
from typing import Optional, Dict, Any

import pandas as pd
import ccxt
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from flask import Flask

from strategy import (
    FILTER_DEFAULTS, STRATEGY_DEFAULTS, calculate_indicators, get_signal_with_reason,
    get_strategy_params, get_strategy_description, strategy_trend_following,
    strategy_breakout, strategy_mean_reversion,
)
from ui import (
    get_start_keyboard, get_balance_keyboard, get_margin_keyboard, get_leverage_keyboard,
    get_max_positions_keyboard, get_timeframe_keyboard, get_main_menu_keyboard,
    get_watchlist_manage_keyboard, get_strategies_selection_keyboard,
    get_filters_menu_keyboard, get_params_menu_keyboard, get_positions_keyboard,
    get_bottom_menu_keyboard, get_confirm_close_all_keyboard, get_strategies_menu_keyboard,
)

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
PORT = int(os.environ.get('PORT', '10000'))
DB_PATH = os.environ.get('BOT_DB_PATH', 'trader_bot.sqlite3')
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()
SCAN_INTERVAL_SECONDS = max(20, int(os.environ.get('SCAN_INTERVAL_SECONDS', '45')))
DATA_CACHE_SECONDS = max(5, int(os.environ.get('DATA_CACHE_SECONDS', '20')))
MAX_ASYNC_REQUESTS = max(2, int(os.environ.get('MAX_ASYNC_REQUESTS', '10')))
DAILY_LOSS_LIMIT_PCT = float(os.environ.get('DAILY_LOSS_LIMIT_PCT', '3'))
RISK_PER_TRADE_PCT = float(os.environ.get('RISK_PER_TRADE_PCT', '0.5'))
MAX_MARGIN_USAGE_PCT = float(os.environ.get('MAX_MARGIN_USAGE_PCT', '50'))
REAL_RESTART_LOCK = os.environ.get('REAL_RESTART_LOCK', 'true').lower() not in ('0', 'false', 'no')
MARGIN_MODE = os.environ.get('MARGIN_MODE', 'isolated').lower()
PROTECTION_TRIGGER = os.environ.get('PROTECTION_TRIGGER', 'mark_price').lower()
ORDER_CONFIRM_RETRIES = max(1, int(os.environ.get('ORDER_CONFIRM_RETRIES', '4')))
ORDER_CONFIRM_DELAY = max(0.25, float(os.environ.get('ORDER_CONFIRM_DELAY', '1.0')))
ENTRY_LOCK_TIMEOUT = max(1, float(os.environ.get('ENTRY_LOCK_TIMEOUT', '5')))
PAPER_CONSERVATIVE_OHLC = os.environ.get('PAPER_CONSERVATIVE_OHLC', 'true').lower() not in ('0', 'false', 'no')

# Multi-user REAL account mapping. Example:
# COINEX_ACCOUNTS_JSON='{"123456":{"apiKey":"KEY_A","secret":"SECRET_A"},"987654":{"apiKey":"KEY_B","secret":"SECRET_B"}}'
COINEX_ACCOUNTS_JSON = os.environ.get('COINEX_ACCOUNTS_JSON', '{}').strip()
try:
    COINEX_ACCOUNTS = json.loads(COINEX_ACCOUNTS_JSON) if COINEX_ACCOUNTS_JSON else {}
except Exception:
    COINEX_ACCOUNTS = {}

ALLOWED_CHAT_IDS_RAW = os.environ.get('ALLOWED_CHAT_IDS', '').strip()
ALLOWED_CHAT_IDS = {int(x.strip()) for x in ALLOWED_CHAT_IDS_RAW.split(',') if x.strip().lstrip('-').isdigit()}

ALL_SYMBOLS = [
    'BTC','ETH','YFI','MKR','BCH','COMP','KSM','LTC','AAVE','ZEC','EGLD','BNB','DASH','FIL','ZEN','SOL','UNI','DOT','BAL','LIT','BAND','UNFI','SUSHI','SNX','AVAX','ATOM','TRB','ETC','NEO','SFP','BEL','IOTA','AXS','RLC','SXP','GRT','RUNE','ONT','KAVA','OCEAN','1INCH','REN','KNC','HNT','ENJ','ICX','CRV','NEAR','CTK','EOS','THETA','QTUM','MANA','OMG','SAND','ADA','XEM','FTM','RVN','MTL','SC','STORJ','ZIL','SLP','BTS','XRP','BLZ','FET','ALGO','DODO','CHR','AKRO','CVC','STMX','CELR','HBAR','SKL','RSR','REEF','CHZ','LINK','ALICE','ZRX','COTI','ONE','MATIC','XTZ','NKN','ANKR','LINA','HOT','LRC','DOGE','DENT','DGB','WIN','IOST','TRX','BTT','FLM','BAT','VET','SHIB','ARPA','AR','C98','DYDX','TLM','GALA','AUDIO','MASK','BAKE','KEEP','OGN','RAY','KLAY','ATA','GTC','CELO','YFII','CTSI'
]
TIMEFRAME_MAP = {'5min':'5min','15min':'15min','1hour':'1hour','4hour':'4hour','1day':'1day'}
TF_DISPLAY = {'5min':'5م','15min':'15م','1hour':'1س','4hour':'4س','1day':'روزانه','multi':'مولتی'}
COINEX_PUBLIC = 'https://api.coinex.com/v2'
KUCOIN_PUBLIC = 'https://api.kucoin.com/api/v1'

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format='%(asctime)s | %(levelname)s | %(threadName)s | %(message)s')
logger = logging.getLogger('trader_bot')
app = Flask(__name__)
STATE_LOCK = RLock()
DB_LOCK = RLock()
DATA_LOCK = RLock()
USER_SESSIONS: Dict[int, Dict[str, Any]] = {}
EXCHANGE_CACHE: Dict[int, Any] = {}
DATA_CACHE: Dict[str, Any] = {}
PRICE_CACHE: Dict[str, Any] = {}
ASYNC_SEMAPHORE = None
ENTRY_LOCKS: Dict[int, RLock] = {}
ENTRY_LOCKS_GUARD = RLock()
TELEGRAM_OFFSET = 0
TELEGRAM_SKIP_BACKLOG = os.environ.get('TELEGRAM_SKIP_BACKLOG', 'false').lower() not in ('0','false','no')
HTTP_SESSION = None

class ExchangeStateError(RuntimeError):
    pass


def json_default(obj):
    if isinstance(obj, set): return list(obj)
    raise TypeError


def init_db():
    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH, timeout=15)
        try:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA synchronous=NORMAL')
            conn.execute('PRAGMA busy_timeout=15000')
            conn.execute('CREATE TABLE IF NOT EXISTS sessions(chat_id INTEGER PRIMARY KEY, data TEXT NOT NULL, updated_at INTEGER NOT NULL)')
            conn.execute('CREATE TABLE IF NOT EXISTS bot_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at INTEGER NOT NULL)')
            conn.commit()
        finally:
            conn.close()


def get_entry_lock(chat_id):
    with ENTRY_LOCKS_GUARD:
        return ENTRY_LOCKS.setdefault(int(chat_id), RLock())


def load_telegram_offset():
    global TELEGRAM_OFFSET
    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH, timeout=15)
        try:
            row = conn.execute('SELECT value FROM bot_meta WHERE key=?', ('telegram_offset',)).fetchone()
        finally:
            conn.close()
    try:
        TELEGRAM_OFFSET = max(0, int(row[0])) if row else 0
    except Exception:
        TELEGRAM_OFFSET = 0
    logger.info('Telegram offset loaded: %s', TELEGRAM_OFFSET)


def save_telegram_offset(offset):
    global TELEGRAM_OFFSET
    TELEGRAM_OFFSET = max(0, int(offset))
    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH, timeout=15)
        try:
            conn.execute('PRAGMA busy_timeout=15000')
            conn.execute('INSERT INTO bot_meta(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at', ('telegram_offset', str(TELEGRAM_OFFSET), int(time.time())))
            conn.commit()
        finally:
            conn.close()


def save_session(chat_id):
    with STATE_LOCK:
        data = USER_SESSIONS.get(chat_id)
        if data is None: return
        payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'), default=json_default)
    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH, timeout=15)
        try:
            conn.execute('PRAGMA busy_timeout=15000')
            conn.execute('INSERT INTO sessions(chat_id,data,updated_at) VALUES(?,?,?) ON CONFLICT(chat_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at', (chat_id, payload, int(time.time())))
            conn.commit()
        finally: conn.close()


def default_session():
    return {
        'is_bot_active': False,
        'trading_mode': 'PAPER',
        'paper_balance': 1000.0,
        'daily_start_equity': 1000.0,
        'daily_start_date': time.strftime('%Y-%m-%d', time.gmtime()),
        'daily_stopped': False,
        'trade_amount_usdt': 50.0,
        'leverage': 5,
        'max_open_positions': 3,
        'timeframe': '5min',
        'active_strategy': 'dynamic',
        'paper_positions': [],
        'closed_positions': [],
        'cooldowns': {},
        'user_state': None,
        'active_symbols': ALL_SYMBOLS[:],
        'filters': FILTER_DEFAULTS.copy(),
        'strategy_config': STRATEGY_DEFAULTS.copy(),
        'daily_loss_limit_pct': DAILY_LOSS_LIMIT_PCT,
        'risk_per_trade_pct': RISK_PER_TRADE_PCT,
        'max_margin_usage_pct': MAX_MARGIN_USAGE_PCT,
        'real_reconciliation_required': False,
        'last_risk_check': 0,
        'last_reconcile': 0,
        'telegram_offset': None,
        'protection_failures': 0,
        'trading_halted_reason': None,
        'created_at': int(time.time()),
    }


def normalize_session(data):
    s = default_session(); s.update(data or {})
    s['filters'] = {**FILTER_DEFAULTS, **(data.get('filters') or {})}
    s['strategy_config'] = {**STRATEGY_DEFAULTS, **(data.get('strategy_config') or {})}
    s['paper_positions'] = list(data.get('paper_positions') or [])
    s['closed_positions'] = list(data.get('closed_positions') or [])
    s['cooldowns'] = dict(data.get('cooldowns') or {})
    s['active_symbols'] = list(data.get('active_symbols') or ALL_SYMBOLS[:])
    for k in ('paper_balance','daily_start_equity','trade_amount_usdt','daily_loss_limit_pct','risk_per_trade_pct','max_margin_usage_pct'):
        s[k] = float(s.get(k, default_session()[k]))
    s['is_bot_active'] = False if REAL_RESTART_LOCK else bool(s.get('is_bot_active', False))
    return s


def load_sessions():
    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH, timeout=15)
        try: rows = conn.execute('SELECT chat_id,data FROM sessions').fetchall()
        finally: conn.close()
    with STATE_LOCK:
        for chat_id, raw in rows:
            try: USER_SESSIONS[int(chat_id)] = normalize_session(json.loads(raw))
            except Exception: logger.exception('Failed loading session %s', chat_id)


def get_session(chat_id):
    with STATE_LOCK:
        if chat_id not in USER_SESSIONS:
            USER_SESSIONS[chat_id] = default_session()
            created = True
        else: created = False
        s = USER_SESSIONS[chat_id]
    if created: save_session(chat_id)
    return s


def account_credentials(chat_id):
    raw = COINEX_ACCOUNTS.get(str(chat_id)) or COINEX_ACCOUNTS.get(chat_id)
    if not isinstance(raw, dict): return None
    key = (raw.get('apiKey') or raw.get('api_key') or '').strip()
    secret = (raw.get('secret') or raw.get('apiSecret') or raw.get('api_secret') or '').strip()
    if not key or not secret: return None
    return key, secret


def get_exchange(chat_id):
    creds = account_credentials(chat_id)
    if not creds: return None
    if chat_id in EXCHANGE_CACHE: return EXCHANGE_CACHE[chat_id]
    try:
        ex = ccxt.coinex({'apiKey':creds[0],'secret':creds[1],'enableRateLimit':True,'options':{'defaultType':'swap','defaultMarginMode':MARGIN_MODE}})
        ex.load_markets()
        EXCHANGE_CACHE[chat_id] = ex
        logger.info('CoinEx connected for chat_id=%s', chat_id)
        return ex
    except Exception as exc:
        logger.exception('CoinEx init failed for %s: %s', chat_id, exc)
        return None


def is_allowed(chat_id):
    return not ALLOWED_CHAT_IDS or chat_id in ALLOWED_CHAT_IDS


def tg(method, payload=None, timeout=10):
    if not TELEGRAM_TOKEN: return None
    try:
        r = requests.post(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}', json=payload or {}, timeout=timeout)
        if r.status_code != 200: logger.warning('Telegram %s: %s', method, r.text[:300]); return None
        return r.json()
    except Exception as exc:
        logger.warning('Telegram request failed: %s', exc); return None


def answer_callback(cid):
    if cid: tg('answerCallbackQuery', {'callback_query_id': cid}, 5)


def send_message(chat_id, text, markup=None, message_id=None, parse_mode='Markdown'):
    if not is_allowed(chat_id): return False
    s = get_session(chat_id)
    if markup is None: markup = get_bottom_menu_keyboard(s['is_bot_active'])
    if message_id:
        body = {'chat_id':chat_id,'message_id':message_id,'text':text,'reply_markup':markup}
        if parse_mode: body['parse_mode'] = parse_mode
        res = tg('editMessageText', body, 10)
        if res and res.get('ok'): return True
    body = {'chat_id':chat_id,'text':text,'reply_markup':markup}
    if parse_mode: body['parse_mode'] = parse_mode
    res = tg('sendMessage', body, 10)
    return bool(res and res.get('ok'))


def send_photo(chat_id, img, caption=''):
    if not is_allowed(chat_id) or not TELEGRAM_TOKEN: return False
    s = get_session(chat_id)
    try:
        r = requests.post(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto', data={'chat_id':chat_id,'caption':caption,'parse_mode':'Markdown','reply_markup':json.dumps(get_bottom_menu_keyboard(s['is_bot_active']), ensure_ascii=False)}, files={'photo':('chart.png',img,'image/png')}, timeout=20)
        return r.status_code == 200
    except Exception as exc: logger.warning('sendPhoto failed: %s', exc); return False


def fmt(v):
    try:
        x=float(v)
        if abs(x)<.0001: return f'{x:.8f}'
        if abs(x)<1: return f'{x:.6f}'
        return f'{x:.4f}'
    except: return str(v)


def market_name(symbol): return f"{symbol.upper().replace('USDT','').replace('/','')}USDT"
def ccxt_symbol(symbol): return f"{symbol.upper().replace('USDT','').replace('/','')}/USDT:USDT"


def normalize_klines(data):
    if not data: return pd.DataFrame()
    rows=[]
    for x in data:
        if isinstance(x,dict): rows.append({'timestamp':x.get('created_at') or x.get('timestamp'),'open':x.get('open'),'close':x.get('close'),'high':x.get('high'),'low':x.get('low'),'volume':x.get('volume')})
        elif isinstance(x,(list,tuple)) and len(x)>=6: rows.append({'timestamp':x[0],'open':x[1],'close':x[2],'high':x[3],'low':x[4],'volume':x[5]})
    df=pd.DataFrame(rows)
    if df.empty: return df
    for c in ['open','close','high','low','volume','timestamp']: df[c]=pd.to_numeric(df[c], errors='coerce')
    return df.dropna(subset=['open','high','low','close']).sort_values('timestamp').reset_index(drop=True)


def get_klines(symbol, tf='5min', limit=200):
    period=TIMEFRAME_MAP.get(tf,tf); key=f'{symbol}:{period}:{limit}'; now=time.time()
    with DATA_LOCK:
        c=DATA_CACHE.get(key)
        if c and now-c['ts']<DATA_CACHE_SECONDS: return c['df'].copy()
    try:
        r=requests.get(f'{COINEX_PUBLIC}/futures/kline', params={'market':market_name(symbol),'period':period,'limit':min(limit,1000)}, timeout=7)
        if r.ok:
            p=r.json()
            if p.get('code')==0:
                df=normalize_klines(p.get('data'))
                if len(df)>=60:
                    with DATA_LOCK: DATA_CACHE[key]={'ts':now,'df':df.copy()}
                    return df
    except Exception as exc: logger.debug('CoinEx kline %s: %s', symbol, exc)
    try:
        r=requests.get(f'{KUCOIN_PUBLIC}/market/candles', params={'symbol':f'{symbol}-USDT','type':period}, timeout=7)
        if r.ok and r.json().get('code')=='200000':
            data=r.json().get('data') or []
            df=pd.DataFrame(data, columns=['timestamp','open','close','high','low','volume','turnover']).iloc[::-1].reset_index(drop=True)
            for c in ['timestamp','open','close','high','low','volume']: df[c]=pd.to_numeric(df[c],errors='coerce')
            if len(df)>=60:
                with DATA_LOCK: DATA_CACHE[key]={'ts':now,'df':df.copy()}
                return df
    except Exception as exc: logger.debug('KuCoin kline %s: %s', symbol, exc)
    return pd.DataFrame()


async def get_klines_async(http, symbol, tf='5min', limit=200):
    period=TIMEFRAME_MAP.get(tf,tf); key=f'{symbol}:{period}:{limit}'; now=time.time()
    with DATA_LOCK:
        c=DATA_CACHE.get(key)
        if c and now-c['ts']<DATA_CACHE_SECONDS: return c['df'].copy()
    await ASYNC_SEMAPHORE.acquire()
    try:
        for base, params in [(f'{COINEX_PUBLIC}/futures/kline',{'market':market_name(symbol),'period':period,'limit':min(limit,1000)}),(f'{KUCOIN_PUBLIC}/market/candles',{'symbol':f'{symbol}-USDT','type':period})]:
            try:
                async with http.get(base, params=params) as r:
                    if r.status != 200: continue
                    p=await r.json()
                    good = p.get('code')==0 if 'coinex.com' in base else p.get('code')=='200000'
                    if not good: continue
                    df=normalize_klines(p.get('data')) if 'coinex.com' in base else pd.DataFrame(p.get('data') or [], columns=['timestamp','open','close','high','low','volume','turnover']).iloc[::-1].reset_index(drop=True)
                    for c in ['timestamp','open','close','high','low','volume']: df[c]=pd.to_numeric(df[c],errors='coerce')
                    if len(df)>=60:
                        with DATA_LOCK: DATA_CACHE[key]={'ts':now,'df':df.copy()}
                        return df
            except Exception as exc: logger.debug('async market data %s: %s',symbol,exc)
    finally: ASYNC_SEMAPHORE.release()
    return pd.DataFrame()


def latest_price(symbol):
    key=symbol.upper(); now=time.time()
    with DATA_LOCK:
        c=PRICE_CACHE.get(key)
        if c and now-c['ts']<5: return c['price']
    try:
        r=requests.get(f'{COINEX_PUBLIC}/futures/ticker', params={'market':market_name(symbol)}, timeout=5)
        if r.ok and r.json().get('code')==0:
            data=r.json().get('data')
            item=data[0] if isinstance(data,list) else data
            price=float(item.get('last') or item.get('mark_price'))
            if price>0:
                with DATA_LOCK: PRICE_CACHE[key]={'ts':now,'price':price}
                return price
    except Exception as exc: logger.debug('price %s: %s',symbol,exc)
    return None


def exchange_balance(chat_id):
    ex=get_exchange(chat_id)
    if not ex: raise ExchangeStateError('exchange unavailable')
    try:
        b=ex.fetch_balance({'type':'swap'})
        total=(b.get('total') or {}).get('USDT')
        if total is None: raise ExchangeStateError('USDT balance missing')
        return float(total)
    except ExchangeStateError:
        raise
    except Exception as exc:
        logger.warning('balance %s: %s',chat_id,exc)
        raise ExchangeStateError(f'balance fetch failed: {exc}') from exc


def get_open_positions(chat_id):
    ex=get_exchange(chat_id)
    if not ex: raise ExchangeStateError('exchange unavailable')
    try:
        rows=ex.fetch_positions()
        return [p for p in rows if abs(float(p.get('contracts') or p.get('amount') or 0))>0]
    except Exception as exc:
        logger.warning('positions %s: %s',chat_id,exc)
        raise ExchangeStateError(f'position fetch failed: {exc}') from exc


def normalize_real_position(pos):
    sym=pos.get('symbol','')
    base=sym.split('/')[0].upper() if '/' in sym else sym.replace(':USDT','').replace('USDT','').upper()
    side='BUY (Long)' if str(pos.get('side','')).lower()=='long' else 'SELL (Short)'
    return {'symbol':base,'side':side,'entry_price':float(pos.get('entryPrice') or pos.get('average') or 0),'amount':abs(float(pos.get('contracts') or pos.get('amount') or 0)),'leverage':int(float(pos.get('leverage') or 1)),'unrealized_pnl':float(pos.get('unrealizedPnl') or 0),'position_id':pos.get('id')}


def find_position(chat_id, symbol):
    for p in get_open_positions(chat_id):
        n=normalize_real_position(p)
        if n['symbol']==symbol.upper(): return n
    return None


def call_implicit_any(ex, candidates, params):
    for name in candidates:
        fn=getattr(ex,name,None)
        if callable(fn): return fn(params)
    # Last chance: python-ccxt snake_case name conversion varies by version.
    raise AttributeError('CoinEx implicit SL/TP method unavailable in this CCXT version')


def _extract_response_data(resp):
    if not isinstance(resp, dict):
        return {}
    data = resp.get('data') if isinstance(resp.get('data'), dict) else resp
    return data if isinstance(data, dict) else {}


def _price_matches(a, b, tolerance=1e-8):
    try:
        a, b = float(a), float(b)
        scale = max(abs(a), abs(b), 1.0)
        return abs(a-b) <= max(tolerance, scale*1e-6)
    except Exception:
        return False


def _halt_real_trading(chat_id, reason, notify=True):
    s = get_session(chat_id)
    s['is_bot_active'] = False
    s['real_reconciliation_required'] = True
    s['trading_halted_reason'] = str(reason)[:500]
    s['protection_failures'] = int(s.get('protection_failures', 0)) + 1
    save_session(chat_id)
    if notify:
        send_message(chat_id, f"🚨 *توقف ایمنی REAL فعال شد.*\n\n{reason}\n\nبرای جلوگیری از سفارش تکراری/بدون حفاظت، اسکن متوقف شد. وضعیت CoinEx را بررسی و سپس دوباره فعال کنید.")


def set_protection(chat_id, symbol, sl, tp):
    ex=get_exchange(chat_id)
    if not ex: return False,'exchange unavailable'
    m=market_name(symbol)
    errors=[]
    sl_resp = tp_resp = None
    try:
        sl_resp=call_implicit_any(ex,['v2PrivatePostFuturesSetPositionStopLoss','v2_private_post_futures_set_position_stop_loss'],{'market':m,'market_type':'FUTURES','stop_loss_type':PROTECTION_TRIGGER,'stop_loss_price':str(sl)})
    except Exception as e: errors.append(f'SL:{e}')
    try:
        tp_resp=call_implicit_any(ex,['v2PrivatePostFuturesSetPositionTakeProfit','v2_private_post_futures_set_position_take_profit'],{'market':m,'market_type':'FUTURES','take_profit_type':PROTECTION_TRIGGER,'take_profit_price':str(tp)})
    except Exception as e: errors.append(f'TP:{e}')
    if errors: return False,' | '.join(errors)
    # Verify the actual exchange response, then verify the live position. CoinEx returns the active TP/SL prices in the position payload.
    try:
        sd=_extract_response_data(sl_resp); td=_extract_response_data(tp_resp)
        sl_returned=sd.get('stop_loss_price') or sd.get('stopLossPrice') or td.get('stop_loss_price') or td.get('stopLossPrice')
        tp_returned=td.get('take_profit_price') or td.get('takeProfitPrice') or sd.get('take_profit_price') or sd.get('takeProfitPrice')
        if not sl_returned: return False, 'exchange did not return an active stop-loss price'
        if not tp_returned: return False, 'exchange did not return an active take-profit price'
        if not _price_matches(sl_returned, sl):
            return False, f'SL verification mismatch: expected {sl}, got {sl_returned}'
        if not _price_matches(tp_returned, tp):
            return False, f'TP verification mismatch: expected {tp}, got {tp_returned}'
        pos=find_position(chat_id,symbol)
        if not pos: return False,'position disappeared after protection setup'
        return True,'OK'
    except Exception as exc:
        return False,f'protection verification failed: {exc}'

def move_stop_loss(chat_id, symbol, sl):
    ex=get_exchange(chat_id)
    if not ex: return False,'exchange unavailable'
    try:
        call_implicit_any(ex,['v2PrivatePostFuturesSetPositionStopLoss','v2_private_post_futures_set_position_stop_loss'],{'market':market_name(symbol),'market_type':'FUTURES','stop_loss_type':PROTECTION_TRIGGER,'stop_loss_price':str(sl)})
        return True,'OK'
    except Exception as e: return False,str(e)


def position_history_for(chat_id, symbol, since_ms):
    ex=get_exchange(chat_id)
    if not ex: return []
    try: return ex.fetch_position_history(ccxt_symbol(symbol), since_ms, 20)
    except Exception as exc: logger.debug('position history %s: %s',symbol,exc); return []


def side_long(side): return 'BUY' in str(side).upper() or 'LONG' in str(side).upper()


def reserved_margin(s): return sum(float(p.get('margin',0)) for p in s['paper_positions'])


def reset_daily_if_needed(chat_id, equity):
    s=get_session(chat_id); today=time.strftime('%Y-%m-%d',time.gmtime())
    if s.get('daily_start_date')!=today:
        s['daily_start_date']=today; s['daily_start_equity']=float(equity); s['daily_stopped']=False; save_session(chat_id)


def current_paper_equity(s):
    eq=float(s['paper_balance'])
    for p in s['paper_positions']:
        price=latest_price(p['symbol'])
        if not price: continue
        entry=float(p['entry_price']); frac=((price-entry)/entry) if side_long(p['side']) else ((entry-price)/entry)
        eq += float(p.get('margin',0))*frac*float(p.get('leverage',1))
    return eq


def risk_guard(chat_id):
    s=get_session(chat_id); now=time.time()
    if now-s.get('last_risk_check',0)<5: return not s['daily_stopped']
    try:
        if s['trading_mode']=='REAL':
            balance=exchange_balance(chat_id)
            # Include live unrealized PnL in the risk equity when available.
            live=get_open_positions(chat_id)
            unrealized=sum(float(p.get('unrealizedPnl') or p.get('unrealized_pnl') or 0) for p in live)
            equity=balance+unrealized
        else:
            equity=current_paper_equity(s)
    except ExchangeStateError as exc:
        logger.warning('risk data unavailable chat=%s: %s',chat_id,exc)
        if s['trading_mode']=='REAL':
            _halt_real_trading(chat_id, f'داده حساب/پوزیشن برای کنترل ریسک در دسترس نیست: {exc}')
        return False
    s['last_risk_check']=now
    reset_daily_if_needed(chat_id,equity)
    start=float(s['daily_start_equity'])
    if start<=0: return True
    limit=start*(1-float(s['daily_loss_limit_pct'])/100)
    if equity<=limit:
        s['daily_stopped']=True; s['is_bot_active']=False; save_session(chat_id)
        send_message(chat_id,f"🛑 *حد ضرر روزانه فعال شد.*\n\nشروع روز: `${start:.2f}`\nEquity: `${equity:.2f}`\nحد: `{s['daily_loss_limit_pct']:.2f}%`\n\nپوزیشن‌های باز به‌صورت خودکار بسته نمی‌شوند؛ اسکن متوقف شد.")
        return False
    return True


def market_meta(chat_id,symbol):
    ex=get_exchange(chat_id)
    if not ex: return None
    try: return ex.market(ccxt_symbol(symbol))
    except: return None


def normalize_amount(chat_id,symbol,amount):
    ex=get_exchange(chat_id)
    if not ex: return 0.0
    try: return float(ex.amount_to_precision(ccxt_symbol(symbol),amount))
    except: return float(amount)


def normalize_price(chat_id,symbol,price):
    ex=get_exchange(chat_id)
    if not ex: return float(price)
    try: return float(ex.price_to_precision(ccxt_symbol(symbol),price))
    except: return float(price)


def safe_size(chat_id, s, symbol, entry, sl):
    balance=exchange_balance(chat_id) if s['trading_mode']=='REAL' else float(s['paper_balance'])
    stop_dist=abs(float(entry)-float(sl))/max(abs(float(entry)),1e-12)
    if stop_dist<=0: return 0,'invalid stop distance'
    risk_budget=max(0.0, balance*float(s['risk_per_trade_pct'])/100.0)
    leverage=max(1,int(s['leverage']))
    requested_margin=max(0.0,float(s['trade_amount_usdt']))
    cap=max(0.0,balance*float(s['max_margin_usage_pct'])/100.0)
    available=max(0.0,cap-reserved_margin(s))
    # Risk is defined on position notional, not on margin.
    risk_notional = risk_budget/stop_dist
    risk_margin = risk_notional/leverage
    margin=min(requested_margin,available,risk_margin)
    if margin<=0: return 0,'risk/margin cap blocks entry'
    amount=(margin*leverage)/float(entry)
    if s['trading_mode']=='REAL':
        amount=normalize_amount(chat_id,symbol,amount)
    return margin,amount

def chart(chat_id,symbol,df,trade):
    try:
        if df.empty: return
        d=df.tail(60); plt.figure(figsize=(10,5)); plt.plot(d.close.values,label='Close'); plt.plot(d.ema20.values,label='EMA20',linestyle='--'); plt.plot(d.ema50.values,label='EMA50',linestyle='--')
        for val,ls,label in [(trade['entry_price'],'-','Entry'),(trade['tp'],':','TP'),(trade['sl'],':','SL')]: plt.axhline(val,linestyle=ls,label=f'{label}: {fmt(val)}')
        plt.title(f"{symbol} {trade['side']}"); plt.legend(fontsize=8); plt.grid(alpha=.25); plt.tight_layout(); b=io.BytesIO(); plt.savefig(b,format='png',dpi=100); plt.close(); b.seek(0)
        send_photo(chat_id,b.getvalue(),f"📊 *معامله جدید [{ 'REAL' if trade.get('is_real') else 'PAPER'}]*\n• `{symbol}` {trade['side']}\n• ورود: `{fmt(trade['entry_price'])}`\n• Margin: `${trade['margin']:.2f}` | `{trade['leverage']}X`\n• TP: `{fmt(trade['tp'])}` | SL: `{fmt(trade['sl'])}`")
    except Exception: logger.exception('chart error')


def _live_symbol_count(chat_id):
    try:
        return len(get_open_positions(chat_id))
    except Exception:
        return 10**9


def _confirm_order_fill(ex, symbol, order):
    order_id = order.get('id') if isinstance(order,dict) else None
    last = order if isinstance(order,dict) else {}
    for attempt in range(ORDER_CONFIRM_RETRIES):
        try:
            if order_id and hasattr(ex,'fetch_order'):
                fetched=ex.fetch_order(order_id, symbol)
                if isinstance(fetched,dict): last=fetched
            status=str(last.get('status') or '').lower()
            filled=float(last.get('filled') or 0)
            avg=last.get('average') or last.get('price')
            if filled>0:
                return last,filled,float(avg) if avg else None
            if status in ('canceled','cancelled','rejected','expired'): return last,0,None
        except Exception as exc:
            logger.warning('order confirmation attempt %s failed: %s',attempt+1,exc)
        time.sleep(ORDER_CONFIRM_DELAY*(attempt+1))
    return last,0,None


def _register_real_ambiguity(chat_id, symbol, message):
    _halt_real_trading(chat_id, f"⚠️ وضعیت سفارش `{symbol}` نامشخص است: {message}")


def execute_trade(chat_id,symbol,side,signal_price,sl,tp,reason=''):
    lock=get_entry_lock(chat_id)
    if not lock.acquire(timeout=ENTRY_LOCK_TIMEOUT):
        logger.warning('entry lock timeout chat=%s symbol=%s',chat_id,symbol); return False
    try:
        s=get_session(chat_id)
        if not s['is_bot_active'] or s['daily_stopped'] or s.get('real_reconciliation_required') or not risk_guard(chat_id): return False
        now=time.time(); cd=float(s['cooldowns'].get(symbol,0))
        if now<cd: return False
        if s['filters'].get('no_short_filter') and 'SELL' in side: return False
        if s['filters'].get('no_buy_filter') and 'BUY' in side: return False
        if s['max_open_positions']>0:
            local_count=len(s['paper_positions'])
            if local_count>=s['max_open_positions']: return False
            if s['trading_mode']=='REAL' and _live_symbol_count(chat_id)>=s['max_open_positions']: return False
        if any(p['symbol']==symbol for p in s['paper_positions']): return False
        if s['trading_mode']=='REAL' and find_position(chat_id,symbol): return False

        price=latest_price(symbol) or float(signal_price)
        gap_sl=abs(float(signal_price)-float(sl)); gap_tp=abs(float(tp)-float(signal_price))
        if gap_sl<=0 or gap_tp<=0: return False
        if side_long(side): sl=price-gap_sl; tp=price+gap_tp
        else: sl=price+gap_sl; tp=price-gap_tp
        margin,amount=safe_size(chat_id,s,symbol,price,sl)
        if margin<=0: logger.info('entry blocked %s: %s',symbol,amount); return False
        leverage=int(s['leverage'])
        trade={'symbol':symbol,'side':side,'entry_price':price,'sl':sl,'tp':tp,'margin':margin,'leverage':leverage,'amount':0,'timeframe':s['timeframe'],'is_real':False,'opened_at':time.time(),'signal_reason':reason[:500],'risk_pct':float(s['risk_per_trade_pct']),'trailing_activated':False}

        if s['trading_mode']=='REAL':
            ex=get_exchange(chat_id)
            if not ex:
                send_message(chat_id,'❌ حساب CoinEx این کاربر پیکربندی نشده یا اتصال برقرار نیست.'); return False
            sym=ccxt_symbol(symbol)
            try:
                market=ex.market(sym)
                lev_info=market.get('info') or {}
                max_lev=float(lev_info.get('max_leverage') or market.get('maxLeverage') or leverage)
                if leverage>max_lev: leverage=int(max_lev); trade['leverage']=leverage
                try: ex.set_margin_mode(MARGIN_MODE,sym,{'leverage':leverage})
                except Exception: ex.set_leverage(leverage,sym,{'marginMode':MARGIN_MODE})
                amount=normalize_amount(chat_id,symbol,(margin*leverage)/price)
                min_amt=float(((market.get('limits') or {}).get('amount') or {}).get('min') or 0)
                min_cost=float(((market.get('limits') or {}).get('cost') or {}).get('min') or 0)
                if amount<=0 or (min_amt and amount<min_amt) or (min_cost and amount*price<min_cost):
                    send_message(chat_id,f'❌ حجم معامله `{symbol}` از حداقل مجاز بازار کمتر است.'); return False
                order=ex.create_order(sym,'market','buy' if side_long(side) else 'sell',amount)
                confirmed,filled,avg=_confirm_order_fill(ex,sym,order)
                if filled<=0:
                    # The order may have executed while the HTTP response was lost. Never retry blindly.
                    live=find_position(chat_id,symbol)
                    if live and live.get('amount',0)>0:
                        filled=float(live['amount']); avg=float(live.get('entry_price') or price); confirmed=order
                    else:
                        _register_real_ambiguity(chat_id,symbol,'fill قابل تأیید نبود و retry خودکار انجام نشد')
                        return False
                exec_price=float(avg or price)
                trade['entry_price']=exec_price; trade['amount']=filled; trade['margin']=exec_price*filled/max(leverage,1); trade['is_real']=True; trade['order_id']=confirmed.get('id') or order.get('id')
                if side_long(side): trade['sl']=exec_price-gap_sl; trade['tp']=exec_price+gap_tp
                else: trade['sl']=exec_price+gap_sl; trade['tp']=exec_price-gap_tp
                trade['sl']=normalize_price(chat_id,symbol,trade['sl']); trade['tp']=normalize_price(chat_id,symbol,trade['tp'])
                ok,err=set_protection(chat_id,symbol,trade['sl'],trade['tp'])
                if not ok:
                    _halt_real_trading(chat_id, f"SL/TP برای `{symbol}` ثبت یا تأیید نشد: {err}")
                    try: ex.close_position(sym,None,{'type':'market','amount':filled})
                    except Exception as close_exc: send_message(chat_id,f'🚨 *بستن اضطراری هم شکست خورد.* `{symbol}`\n{close_exc}')
                    return False
            except Exception as exc:
                # A transport/API error after order submission is ambiguous. Stop instead of placing a duplicate.
                logger.exception('real order failed')
                _halt_real_trading(chat_id, f"خطای سفارش REAL `{symbol}`: {exc}")
                return False
        else:
            if float(s['paper_balance'])-reserved_margin(s)<margin: return False
            trade['amount']=(margin*leverage)/price
            s['paper_positions'].append(trade); save_session(chat_id)
        if trade.get('is_real'): s['paper_positions'].append(trade); save_session(chat_id)
        df=get_klines(symbol,'5min' if s['timeframe']=='multi' else s['timeframe'],80)
        if not df.empty: chart(chat_id,symbol,calculate_indicators(df),trade)
        return True
    finally:
        lock.release()

def realized_history_value(chat_id,symbol,opened_at):
    rows=position_history_for(chat_id,symbol,max(0,int((opened_at-120)*1000)))
    if not rows: return None
    best=None; best_ts=0
    for r in rows:
        n=normalize_real_position(r) if r.get('symbol') else {}
        rp=r.get('realizedPnl') or r.get('info',{}).get('realized_pnl') if isinstance(r,dict) else None
        try: rp=float(rp)
        except: continue
        ts=float(r.get('timestamp') or r.get('datetime') and time.mktime(time.strptime(r['datetime'],'%Y-%m-%dT%H:%M:%S.%fZ'))*1000 or 0)
        if ts>=best_ts: best_ts=ts; best=rp
    return best


def close_position(chat_id,pos,price=None,reason='manual'):
    s=get_session(chat_id)
    if pos not in s['paper_positions']: return False
    if pos.get('is_real'):
        ex=get_exchange(chat_id)
        if not ex: send_message(chat_id,'❌ اتصال CoinEx در دسترس نیست.'); return False
        try:
            sym=ccxt_symbol(pos['symbol'])
            live=find_position(chat_id,pos['symbol'])
            if not live or float(live.get('amount',0))<=0:
                # Already closed on the exchange; reconcile will record the final state.
                reconcile_real(chat_id)
                return pos not in s['paper_positions']
            amount=float(live['amount'])
            order=ex.close_position(sym,None,{'type':'market','amount':amount})
            order_id=order.get('id') if isinstance(order,dict) else None
            # Never mark local state closed until the exchange confirms the position is gone.
            deadline=time.time()+10
            last_error=None
            while time.time()<deadline:
                try:
                    current=find_position(chat_id,pos['symbol'])
                    if not current: break
                except Exception as exc:
                    last_error=exc
                time.sleep(.75)
            else:
                _halt_real_trading(chat_id, f"بستن `{pos['symbol']}` تأیید نشد؛ order={order_id} error={last_error}")
                return False
            price=float(order.get('average') or order.get('price') or latest_price(pos['symbol']) or pos['entry_price'])
            realized=realized_history_value(chat_id,pos['symbol'],float(pos.get('opened_at',time.time()-60)))
            if realized is None:
                entry=float(pos['entry_price']); frac=((price-entry)/entry) if side_long(pos['side']) else ((entry-price)/entry); realized=float(pos['margin'])*frac*float(pos['leverage'])
                pos['pnl_is_estimate']=True
            else: pos['pnl_is_estimate']=False
            pnl=realized; pos['close_price']=price
        except Exception as exc:
            send_message(chat_id,f'❌ بستن REAL `{pos["symbol"]}` شکست خورد: `{exc}`',parse_mode=None); return False
    else:
        if price is None: price=latest_price(pos['symbol']) or pos['entry_price']
        entry=float(pos['entry_price']); frac=((price-entry)/entry) if side_long(pos['side']) else ((entry-price)/entry); pnl=float(pos['margin'])*frac*float(pos['leverage']); s['paper_balance']+=pnl; pos['close_price']=price; pos['pnl_is_estimate']=False
    pos['pnl_usdt']=float(pnl); pos['close_timestamp']=time.time(); pos['close_reason']=reason
    s['cooldowns'][pos['symbol']]=time.time()+300; s['closed_positions'].append(pos.copy()); s['paper_positions'].remove(pos); save_session(chat_id)
    est=' تقریبی' if pos.get('pnl_is_estimate') else ''
    send_message(chat_id,f"📌 *پوزیشن {'REAL' if pos.get('is_real') else 'PAPER'} بسته شد*\n• `{pos['symbol']}`\n• خروج: `{fmt(pos['close_price'])}`\n• PnL{est}: `{pnl:+.2f} USDT`\n• علت: `{reason}`")
    return True


def reconcile_real(chat_id):
    s=get_session(chat_id)
    if s['trading_mode']!='REAL': return True
    try:
        live_raw=get_open_positions(chat_id)
    except ExchangeStateError as exc:
        _halt_real_trading(chat_id, f'عدم دسترسی به وضعیت پوزیشن‌های CoinEx: {exc}')
        return False
    live={normalize_real_position(p)['symbol']:normalize_real_position(p) for p in live_raw}
    known={p['symbol']:p for p in s['paper_positions'] if p.get('is_real')}
    unknown=[x for k,x in live.items() if k not in known]
    if unknown:
        _halt_real_trading(chat_id, 'پوزیشن REAL ناشناخته پیدا شد: '+', '.join(x['symbol'] for x in unknown[:15]))
        return False
    changed=False
    for sym,p in list(known.items()):
        if sym in live:
            p.update(live[sym]); changed=True
        else:
            hist=position_history_for(chat_id,sym,max(0,int((p.get('opened_at',time.time()-3600)-120)*1000)))
            rp=None; best_ts=-1
            for h in hist:
                try:
                    value=h.get('realizedPnl') or h.get('info',{}).get('realized_pnl')
                    if value is None: continue
                    ts=float(h.get('timestamp') or 0)
                    if ts>=best_ts: best_ts=ts; rp=float(value)
                except Exception: continue
            p['pnl_usdt']=rp if rp is not None else 0.0; p['pnl_is_estimate']=rp is None; p['close_timestamp']=time.time(); p['close_reason']='external TP/SL or exchange close'
            s['closed_positions'].append(p.copy());
            try: s['paper_positions'].remove(p)
            except ValueError: pass
            s['cooldowns'][sym]=time.time()+300; changed=True
            send_message(chat_id,f"📌 پوزیشن REAL `{sym}` توسط صرافی بسته شد.\nPnL ثبت‌شده: `{p['pnl_usdt']:+.2f} USDT`")
    s['last_reconcile']=time.time()
    if changed: save_session(chat_id)
    return True

def update_positions(chat_id):
    s=get_session(chat_id)
    if not s['paper_positions']: return
    if s['trading_mode']=='REAL':
        if not reconcile_real(chat_id): return
        for p in s['paper_positions'][:]:
            if not p.get('is_real'): continue
            price=latest_price(p['symbol'])
            if not price: continue
            entry=float(p['entry_price']); pnl=float(p.get('margin',0))*(((price-entry)/entry) if side_long(p['side']) else ((entry-price)/entry))*float(p['leverage'])
            p['last_unrealized_pnl']=pnl
            if s['filters'].get('trailing_stop',True) and not p.get('trailing_activated') and pnl>=float(p['margin'])*.10:
                new_sl=entry
                ok,err=move_stop_loss(chat_id,p['symbol'],normalize_price(chat_id,p['symbol'],new_sl))
                if ok: p['sl']=new_sl; p['trailing_activated']=True; send_message(chat_id,f"🛡️ حد سر‌به‌سر فعال شد: `{p['symbol']}`")
                else: logger.warning('trailing %s: %s',p['symbol'],err)
        save_session(chat_id); return
    for p in s['paper_positions'][:]:
        df=get_klines(p['symbol'],p.get('timeframe','5min') if p.get('timeframe')!='multi' else '5min',5)
        if df.empty: continue
        c=df.iloc[-1]; high=float(c['high']); low=float(c['low']); close=float(c['close']); exit_price=None; reason=None
        if side_long(p['side']):
            hit_tp=high>=float(p['tp']); hit_sl=low<=float(p['sl'])
            if hit_tp and hit_sl:
                # OHLC cannot reveal intrabar order. Conservative mode assumes SL was hit first.
                reason='SL/TP same candle → SL (conservative)' if PAPER_CONSERVATIVE_OHLC else 'TP/SL ambiguous'
                exit_price=float(p['sl'] if PAPER_CONSERVATIVE_OHLC else close)
            elif hit_tp: exit_price=float(p['tp']); reason='TP'
            elif hit_sl: exit_price=float(p['sl']); reason='SL'
        else:
            hit_tp=low<=float(p['tp']); hit_sl=high>=float(p['sl'])
            if hit_tp and hit_sl:
                reason='SL/TP same candle → SL (conservative)' if PAPER_CONSERVATIVE_OHLC else 'TP/SL ambiguous'
                exit_price=float(p['sl'] if PAPER_CONSERVATIVE_OHLC else close)
            elif hit_tp: exit_price=float(p['tp']); reason='TP'
            elif hit_sl: exit_price=float(p['sl']); reason='SL'
        pnl=float(p['margin'])*(((close-float(p['entry_price']))/float(p['entry_price'])) if side_long(p['side']) else ((float(p['entry_price'])-close)/float(p['entry_price'])))*float(p['leverage'])
        if s['filters'].get('trailing_stop',True) and not p.get('trailing_activated') and pnl>=float(p['margin'])*.10:
            p['sl']=float(p['entry_price']); p['trailing_activated']=True
        if reason: close_position(chat_id,p,exit_price,reason)
    save_session(chat_id)



def latest_closed_row(df, target_ts=None):
    if df is None or df.empty or len(df)<2: return None
    closed=df.iloc[:-1]
    if target_ts is None: return closed.iloc[-1]
    eligible=closed[closed['timestamp']<=target_ts]
    return eligible.iloc[-1] if not eligible.empty else None


def align_multi_tf_data(md, primary_ts):
    aligned={}
    for tf,df in (md or {}).items():
        row=latest_closed_row(df, primary_ts)
        if row is not None:
            aligned[tf]=df.loc[:row.name].copy()
    return aligned


async def scan_symbol(http,chat_id,symbol):
    s=get_session(chat_id)
    if not s['is_bot_active'] or s['daily_stopped']: return
    if time.time() < float(s['cooldowns'].get(symbol,0)): return
    tf=s['timeframe']; strat=s['active_strategy']; md={}
    if tf=='multi' or strat=='multi':
        for k,v in [('1d','1day'),('4h','4hour'),('1h','1hour'),('15m','15min'),('5m','5min')]:
            d=await get_klines_async(http,symbol,v,140)
            if not d.empty: md[k]=calculate_indicators(d)
        primary=md.get('5m')
        if primary is None or len(primary)<60: return
        primary_tf='5min'; mode='multi'
        primary_closed=latest_closed_row(primary)
        if primary_closed is None: return
        md=align_multi_tf_data(md,float(primary_closed['timestamp']))
    else:
        d=await get_klines_async(http,symbol,tf,160)
        if d.empty: return
        primary=calculate_indicators(d); primary_tf=tf; mode='single'
    if not risk_guard(chat_id): return
    sig,reason=get_signal_with_reason(primary,md,mode,primary_tf,strat,s['filters'],s['strategy_config'])
    if not sig: return
    c=latest_closed_row(primary)
    if c is None: return
    entry=float(c['close']); atr=float(c['atr']); p=get_strategy_params(primary_tf,s['strategy_config'])
    if not math.isfinite(atr) or atr<=0: return
    sl=entry-atr*p['sl'] if sig=='BUY' else entry+atr*p['sl']; tp=entry+atr*p['tp'] if sig=='BUY' else entry-atr*p['tp']
    execute_trade(chat_id,symbol,'BUY (Long)' if sig=='BUY' else 'SELL (Short)',entry,sl,tp,reason)


def performance(chat_id):
    s=get_session(chat_id); closed=s['closed_positions']; total=sum(float(p.get('pnl_usdt',0)) for p in closed); wins=sum(1 for p in closed if float(p.get('pnl_usdt',0))>0); wr=wins/len(closed)*100 if closed else 0
    return f"📈 *گزارش عملکرد*\n\nمعاملات: `{len(closed)}`\nبرد: `{wins}`\nWin Rate: `{wr:.1f}%`\nPnL خالص ثبت‌شده: `{total:+.2f} USDT`\nPaper balance: `${s['paper_balance']:.2f}`"


def analyze(chat_id,symbol):
    s=get_session(chat_id); tf='5min' if s['timeframe']=='multi' else s['timeframe']; d=get_klines(symbol,tf,160)
    if d.empty: return f'❌ داده برای `{symbol}` پیدا نشد.'
    d=calculate_indicators(d); c=d.iloc[-2]
    a,r1=strategy_trend_following(d,tf,s['filters'],s['strategy_config']); b,r2=strategy_breakout(d,s['filters'],s['strategy_config']); m,r3=strategy_mean_reversion(d,s['filters'],s['strategy_config'])
    return f"🔍 *تحلیل `{symbol}`*\n\nClose: `{fmt(c.close)}`\nEMA20: `{fmt(c.ema20)}` | EMA50: `{fmt(c.ema50)}`\nADX: `{float(c.adx):.1f}` | RSI: `{float(c.rsi):.1f}` | ATR: `{fmt(c.atr)}`\n\nTrend: `{a or 'NO'}` — {r1}\nBreakout: `{b or 'NO'}` — {r2}\nMean Reversion: `{m or 'NO'}` — {r3}"


def menu(chat_id,message_id=None):
    s=get_session(chat_id)
    if s['trading_mode']=='REAL':
        try: bal=exchange_balance(chat_id)
        except ExchangeStateError: bal=float('nan')
    else: bal=s['paper_balance']
    maxp=s['max_open_positions'] if s['max_open_positions']>0 else '∞'
    status='فعال' if s['is_bot_active'] else 'متوقف'
    alert=f"\n\n🚨 *Safe Stop:* `{s.get('trading_halted_reason')}`" if s.get('trading_halted_reason') else ''
    text=f"📊 *پنل ربات*\n\nحالت: `{s['trading_mode']}`\nوضعیت: `{status}`\nاستراتژی: `{s['active_strategy'].upper()}`\nEquity/Balance: `${bal:.2f}`\nMargin: `${s['trade_amount_usdt']:.0f}` | Leverage: `{s['leverage']}X`\nPositions: `{maxp}`\nTimeframe: `{TF_DISPLAY.get(s['timeframe'],s['timeframe'])}`\nRisk/trade: `{s['risk_per_trade_pct']:.2f}%`\nDaily loss: `{s['daily_loss_limit_pct']:.2f}%`{alert}"
    send_message(chat_id,text,get_main_menu_keyboard(s['is_bot_active']),message_id)


def process_command(cmd,chat_id,message_id=None):
    s=get_session(chat_id); c=(cmd or '').strip(); cl=c.lower()
    sensitive_prefixes=('/mode_paper','/mode_real','/set_bal_','/set_margin_','/set_lev_','/set_max_','/set_tf_','/toggle_','/adx_','/sl_','/tp_')
    if s['is_bot_active'] and cl.startswith(sensitive_prefixes): send_message(chat_id,'⚠️ ابتدا اسکن را متوقف کنید.'); return
    if cl=='/start': s['is_bot_active']=False; s['user_state']=None; save_session(chat_id); send_message(chat_id,'🤖 *ربات معامله‌گر*\n\nحالت حساب را انتخاب کنید.',get_start_keyboard()); return
    if cl in ('/menu',): s['user_state']=None; menu(chat_id,message_id); return
    if cl=='/cancel': s['user_state']=None; save_session(chat_id); menu(chat_id); return
    if cl=='/toggle_active' or any(x in c for x in ('شروع اسکن','توقف اسکن','روشن کردن اسکن')):
        if not s['is_bot_active']:
            if s['daily_stopped']:
                try: new_equity=exchange_balance(chat_id) if s['trading_mode']=='REAL' else current_paper_equity(s)
                except ExchangeStateError:
                    send_message(chat_id,'❌ داده حساب برای فعال‌سازی در دسترس نیست.'); return
                s['daily_stopped']=False; s['daily_start_equity']=new_equity
            if s['trading_mode']=='REAL':
                if not get_exchange(chat_id): send_message(chat_id,'❌ برای این کاربر حساب CoinEx تنظیم نشده.'); return
                if not reconcile_real(chat_id): return
                s['real_reconciliation_required']=False
                s['trading_halted_reason']=None
        s['is_bot_active']=not s['is_bot_active']; save_session(chat_id); menu(chat_id,message_id); return
    if cl=='/mode_paper':
        if s['paper_positions']: send_message(chat_id,'❌ تا وقتی پوزیشن باز دارید نمی‌توانید به PAPER بروید.'); return
        s['trading_mode']='PAPER'; s['is_bot_active']=False; save_session(chat_id); send_message(chat_id,'⚙️ موجودی PAPER را انتخاب کنید.',get_balance_keyboard()); return
    if cl=='/mode_real':
        if s['paper_positions']: send_message(chat_id,'❌ ابتدا تمام پوزیشن‌های فعلی را ببندید.'); return
        if not get_exchange(chat_id): send_message(chat_id,'❌ حساب CoinEx این کاربر در `COINEX_ACCOUNTS_JSON` تنظیم نشده یا اتصال ناموفق است.'); return
        try: bal=exchange_balance(chat_id)
        except ExchangeStateError as exc: send_message(chat_id,f'❌ دریافت موجودی شکست خورد: `{exc}`',parse_mode=None); return
        if bal<=0: send_message(chat_id,'❌ موجودی USDT معتبر پیدا نشد.'); return
        s['trading_mode']='REAL'; s['is_bot_active']=False; s['daily_start_equity']=bal; s['daily_start_date']=time.strftime('%Y-%m-%d',time.gmtime()); s['daily_stopped']=False; s['real_reconciliation_required']=not reconcile_real(chat_id); save_session(chat_id); send_message(chat_id,f'🔴 موجودی REAL: `{bal:.2f} USDT`\n\n⚙️ مارجین هر معامله:',get_margin_keyboard()); return
    if cl.startswith('/set_bal_'):
        v=float(cl.replace('/set_bal_','')); s['paper_balance']=v; s['daily_start_equity']=v; s['daily_start_date']=time.strftime('%Y-%m-%d',time.gmtime()); s['daily_stopped']=False; save_session(chat_id); send_message(chat_id,'✅ موجودی ثبت شد.\n\n⚙️ مارجین:',get_margin_keyboard()); return
    if cl.startswith('/set_margin_'): s['trade_amount_usdt']=float(cl.replace('/set_margin_','')); save_session(chat_id); send_message(chat_id,'⚙️ اهرم:',get_leverage_keyboard()); return
    if cl.startswith('/set_lev_'): s['leverage']=int(cl.replace('/set_lev_','')); save_session(chat_id); send_message(chat_id,'⚙️ حداکثر پوزیشن:',get_max_positions_keyboard()); return
    if cl.startswith('/set_max_'): s['max_open_positions']=int(cl.replace('/set_max_','')); save_session(chat_id); send_message(chat_id,'⚙️ تایم‌فریم:',get_timeframe_keyboard()); return
    if cl.startswith('/set_tf_'):
        s['timeframe']={'/set_tf_5m':'5min','/set_tf_15m':'15min','/set_tf_1h':'1hour','/set_tf_4h':'4hour','/set_tf_1d':'1day','/set_tf_multi':'multi'}[cl]; save_session(chat_id); menu(chat_id); return
    if cl.startswith('/set_strat_'):
        key=cl.replace('/set_strat_','')
        if key in ('dynamic','trend','breakout','mean_reversion','multi'): s['active_strategy']=key; save_session(chat_id); menu(chat_id)
        return
    if cl=='/market_report':
        vals=[]
        for sym in ['BTC','ETH','SOL','BNB','XRP']:
            d=get_klines(sym,'5min' if s['timeframe']=='multi' else s['timeframe'],120)
            if not d.empty:
                c=calculate_indicators(d).iloc[-2]; vals.append((c.close>c.ema50,float(c.adx)))
        if not vals: send_message(chat_id,'❌ داده بازار موجود نیست.'); return
        up=sum(x[0] for x in vals); adx=sum(x[1] for x in vals)/len(vals); send_message(chat_id,f'📊 *وضعیت بازار*\n\nBullish: `{up}/{len(vals)}`\nAverage ADX: `{adx:.1f}`\nRegime: `{"Trending" if adx>25 else "Ranging" if adx<20 else "Transition"}`'); return
    if cl in ('/strategies_menu',): send_message(chat_id,'📊 *انتخاب استراتژی*',get_strategies_selection_keyboard()); return
    if cl in ('/filters_menu',): send_message(chat_id,'⚙️ *فیلترها*',get_filters_menu_keyboard(s)); return
    if cl in ('/params_menu',): send_message(chat_id,'🎛️ *پارامترها*',get_params_menu_keyboard(s)); return
    if cl=='/strategy_desc_menu': send_message(chat_id,'📚 *توضیح استراتژی*',get_strategies_menu_keyboard()); return
    if cl.startswith('/desc_'):
        tf=cl.replace('/desc_',''); tf={'multi':'multi'}.get(tf,tf); send_message(chat_id,get_strategy_description(tf,s['strategy_config'],s['filters'])); return
    if cl in ('/toggle_vol','/toggle_trail','/toggle_candle','/toggle_short','/toggle_buy'):
        key={'/toggle_vol':'volume_filter','/toggle_trail':'trailing_stop','/toggle_candle':'candlestick_filter','/toggle_short':'no_short_filter','/toggle_buy':'no_buy_filter'}[cl]; s['filters'][key]=not s['filters'].get(key,False); save_session(chat_id); send_message(chat_id,'⚙️ *فیلترها*',get_filters_menu_keyboard(s)); return
    if cl in ('/adx_up','/adx_down','/sl_up','/sl_down','/tp_up','/tp_down'):
        c=s['strategy_config'];
        if cl=='/adx_up': c['min_adx']=min(50,c['min_adx']+1)
        elif cl=='/adx_down': c['min_adx']=max(10,c['min_adx']-1)
        elif cl=='/sl_up': c['sl_multiplier']=round(c['sl_multiplier']+.2,1)
        elif cl=='/sl_down': c['sl_multiplier']=max(.5,round(c['sl_multiplier']-.2,1))
        elif cl=='/tp_up': c['tp_multiplier']=round(c['tp_multiplier']+.5,1)
        else: c['tp_multiplier']=max(.5,round(c['tp_multiplier']-.5,1))
        save_session(chat_id); send_message(chat_id,'🎛️ *پارامترها*',get_params_menu_keyboard(s)); return
    if cl=='/analyze_single': s['user_state']='WAIT_SYMBOL'; save_session(chat_id); send_message(chat_id,'🔍 نماد را ارسال کنید، مثال `BTC`'); return
    if cl=='/open_positions' or 'پوزیشن‌های باز' in c:
        if not s['paper_positions']: send_message(chat_id,'پوزیشن بازی وجود ندارد.'); return
        lines=[f'🔄 *پوزیشن‌ها ({len(s["paper_positions"])})*']
        for p in s['paper_positions']: lines.append(f"{'🟢' if side_long(p['side']) else '🔴'} `{p['symbol']}` | {p['side']} | Entry `{fmt(p['entry_price'])}` | SL `{fmt(p['sl'])}` | TP `{fmt(p['tp'])}`")
        send_message(chat_id,'\n'.join(lines),get_positions_keyboard(s['paper_positions'])); return
    if cl=='/performance' or 'گزارش عملکرد' in c: send_message(chat_id,performance(chat_id)); return
    if cl=='/check_wizard': send_message(chat_id,'⚙️ *تنظیمات معامله*',get_margin_keyboard()); return
    if cl=='/manage_watchlist': send_message(chat_id,f'📋 واچ‌لیست: `{len(s["active_symbols"])}`',get_watchlist_manage_keyboard()); return
    if cl=='/watchlist_list': send_message(chat_id,'📋 *واچ‌لیست*\n\n`'+', '.join(s['active_symbols'])+'`'); return
    if cl=='/add_symbol_prompt': s['user_state']='ADD_SYMBOL'; save_session(chat_id); send_message(chat_id,'➕ نماد را بفرستید'); return
    if cl=='/remove_symbol_prompt': s['user_state']='REMOVE_SYMBOL'; save_session(chat_id); send_message(chat_id,'➖ نماد را بفرستید'); return
    if cl=='/close_all_prompt': send_message(chat_id,'⚠️ *تأیید بستن همه پوزیشن‌ها*',get_confirm_close_all_keyboard()); return
    if cl=='/confirm_close_all':
        s['is_bot_active']=False; save_session(chat_id)
        for p in s['paper_positions'][:]: close_position(chat_id,p,reason='close_all')
        menu(chat_id); return
    if cl.startswith('/close_') and cl not in ('/close_longs','/close_shorts','/close_all_prompt','/close_all'):
        sym=cl.replace('/close_','').upper()
        for p in s['paper_positions'][:]:
            if p['symbol']==sym: close_position(chat_id,p,reason='manual'); return
        send_message(chat_id,f'❌ پوزیشن `{sym}` پیدا نشد.'); return
    if cl=='/close_longs':
        for p in s['paper_positions'][:]:
            if side_long(p['side']): close_position(chat_id,p,reason='manual_longs')
        return
    if cl=='/close_shorts':
        for p in s['paper_positions'][:]:
            if not side_long(p['side']): close_position(chat_id,p,reason='manual_shorts')
        return


def handle_text(chat_id,text):
    s=get_session(chat_id); val=text.strip().upper()
    if s['user_state']=='WAIT_SYMBOL': s['user_state']=None; save_session(chat_id); send_message(chat_id,analyze(chat_id,val)); return
    if s['user_state']=='ADD_SYMBOL':
        if val not in s['active_symbols'] and len(val)<=12 and not get_klines(val,'5min',60).empty: s['active_symbols'].append(val); send_message(chat_id,f'✅ `{val}` اضافه شد.')
        else: send_message(chat_id,'❌ نماد معتبر نیست یا قبلاً وجود دارد.')
        s['user_state']=None; save_session(chat_id); return
    if s['user_state']=='REMOVE_SYMBOL':
        if val in s['active_symbols']: s['active_symbols'].remove(val); send_message(chat_id,f'✅ `{val}` حذف شد.')
        else: send_message(chat_id,'❌ نماد در واچ‌لیست نیست.')
        s['user_state']=None; save_session(chat_id); return
    if 2<=len(val)<=12 and (val.isalpha() or val.replace('1','').isalnum()): send_message(chat_id,analyze(chat_id,val))
    else: process_command(text,chat_id)


def _process_telegram_update(u):
    callback=u.get('callback_query') or {}
    msg=callback.get('message') or u.get('message') or {}
    chat=(msg.get('chat') or {}).get('id')
    if not chat: return
    if callback.get('id'): answer_callback(callback['id'])
    if not is_allowed(chat): return
    data=callback.get('data') or (u.get('message') or {}).get('text')
    if callback: process_command(data,chat,msg.get('message_id'))
    elif data: handle_text(chat,data)


def telegram_listener():
    global TELEGRAM_OFFSET
    backlog_checked=False
    while True:
        if not TELEGRAM_TOKEN: time.sleep(5); continue
        try:
            params={'timeout':25}
            if TELEGRAM_OFFSET>0: params['offset']=TELEGRAM_OFFSET
            elif TELEGRAM_SKIP_BACKLOG and not backlog_checked:
                # One-time migration safety: acknowledge old queued updates without executing their commands.
                params['limit']=100
                params['timeout']=0
                r=requests.get(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates',params=params,timeout=10)
                if r.ok:
                    updates=r.json().get('result',[])
                    if updates:
                        save_telegram_offset(int(updates[-1].get('update_id',0))+1)
                backlog_checked=True
                time.sleep(1)
                continue
            r=requests.get(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates',params=params,timeout=30)
            if not r.ok: time.sleep(2); continue
            updates=r.json().get('result',[])
            for u in updates:
                upd=int(u.get('update_id',0))
                try:
                    _process_telegram_update(u)
                    save_telegram_offset(upd+1)
                except Exception:
                    logger.exception('Telegram update %s failed; offset not advanced',upd)
                    # Do not acknowledge a failed update; retry it after a short delay.
                    time.sleep(1)
                    break
        except Exception as exc:
            logger.exception('Telegram listener: %s',exc); time.sleep(2)


async def scan_loop():
    global ASYNC_SEMAPHORE, HTTP_SESSION
    ASYNC_SEMAPHORE=asyncio.Semaphore(MAX_ASYNC_REQUESTS)
    timeout=aiohttp.ClientTimeout(total=10)
    conn=aiohttp.TCPConnector(limit=MAX_ASYNC_REQUESTS,ttl_dns_cache=300)
    async with aiohttp.ClientSession(timeout=timeout,connector=conn) as http:
        HTTP_SESSION=http
        while True:
            try:
                for cid,s in list(USER_SESSIONS.items()):
                    if s['trading_mode']=='REAL':
                        if s['is_bot_active']: reconcile_real(cid)
                        update_positions(cid)
                    else:
                        update_positions(cid)
                tasks=[]
                for cid,s in list(USER_SESSIONS.items()):
                    if not s['is_bot_active'] or s['daily_stopped'] or s.get('real_reconciliation_required'): continue
                    if not risk_guard(cid): continue
                    if s['max_open_positions']>0:
                        local_count=len(s['paper_positions'])
                        if local_count>=s['max_open_positions']: continue
                    for sym in list(s['active_symbols']): tasks.append(scan_symbol(http,cid,sym))
                if tasks:
                    results=await asyncio.gather(*tasks,return_exceptions=True)
                    for result in results:
                        if isinstance(result,Exception): logger.error('scanner task error: %r',result)
            except Exception as exc: logger.exception('scan loop: %s',exc)
            await asyncio.sleep(SCAN_INTERVAL_SECONDS)


@app.get('/')
def home(): return f"OK - Sessions: {len(USER_SESSIONS)} | Active: {sum(1 for s in USER_SESSIONS.values() if s.get('is_bot_active'))}",200
@app.get('/health')
def health(): return 'OK',200
@app.get('/status')
def status(): return {'status':'ok','sessions':len(USER_SESSIONS),'active_bots':sum(1 for s in USER_SESSIONS.values() if s.get('is_bot_active'))},200


def main():
    init_db(); load_sessions(); load_telegram_offset(); logger.info('Loaded %s sessions',len(USER_SESSIONS))
    Thread(target=telegram_listener,daemon=True,name='telegram').start(); Thread(target=lambda:(time.sleep(3),asyncio.run(scan_loop())),daemon=True,name='scanner').start()
    app.run(host='0.0.0.0',port=PORT,threaded=True)

if __name__=='__main__': main()
