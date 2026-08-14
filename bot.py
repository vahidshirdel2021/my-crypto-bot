import os, json, time, asyncio, aiohttp, requests, sqlite3, logging, math, io, hashlib, threading
from threading import Thread, RLock
from typing import Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import ccxt
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from flask import Flask, request

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
    get_performance_keyboard,
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
ORDER_CONFIRM_RETRIES = max(1, int(os.environ.get('ORDER_CONFIRM_RETRIES', '5')))
ORDER_CONFIRM_DELAY = max(0.25, float(os.environ.get('ORDER_CONFIRM_DELAY', '1.0')))
PAPER_CONSERVATIVE_OHLC = os.environ.get('PAPER_CONSERVATIVE_OHLC', 'true').lower() not in ('0', 'false', 'no')
TELEGRAM_SKIP_BACKLOG = os.environ.get('TELEGRAM_SKIP_BACKLOG', 'true').lower() not in ('0', 'false', 'no')


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
MARKET_REPORT_CACHE = {}
MARKET_REPORT_CACHE_LOCK = RLock()

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


def default_session():
    return {
        'is_bot_active': False,
        'scan_generation': 0,
        'last_stop_reason': None,
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
    s['scan_generation'] = int(s.get('scan_generation', 0) or 0)
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


def send_photo(chat_id, img, caption='', markup=None):
    if not is_allowed(chat_id) or not TELEGRAM_TOKEN: return False
    s = get_session(chat_id)
    if markup is None:
        markup = get_bottom_menu_keyboard(s['is_bot_active'])
    try:
        r = requests.post(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto', data={'chat_id':chat_id,'caption':caption,'parse_mode':'Markdown','reply_markup':json.dumps(markup, ensure_ascii=False)}, files={'photo':('chart.png',img,'image/png')}, timeout=20)
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
        value=float(total)
        if not math.isfinite(value) or value < 0: raise ExchangeStateError('invalid USDT balance')
        return value
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


def _extract_numbers(obj, names):
    found=[]
    if isinstance(obj, dict):
        for k,v in obj.items():
            key=str(k).lower().replace('-','_')
            if key in names:
                try: found.append(float(v))
                except Exception: pass
            found.extend(_extract_numbers(v,names))
    elif isinstance(obj, list):
        for v in obj: found.extend(_extract_numbers(v,names))
    return found


def _price_matches(a,b):
    try:
        a=float(a); b=float(b); scale=max(abs(a),abs(b),1.0)
        return abs(a-b) <= max(1e-8,scale*2e-5)
    except Exception:
        return False


def _live_position_raw(chat_id, symbol):
    ex=get_exchange(chat_id)
    try:
        rows=ex.fetch_positions([ccxt_symbol(symbol)]) if callable(getattr(ex,'fetch_positions',None)) else ex.fetch_positions()
    except Exception:
        rows=ex.fetch_positions()
    for p in rows:
        n=normalize_real_position(p)
        if n['symbol']==symbol.upper(): return p
    return None


def _halt_real_trading(chat_id, reason):
    s=get_session(chat_id)
    s['is_bot_active']=False
    s['real_reconciliation_required']=True
    s['trading_halted_reason']=str(reason)[:500]
    s['scan_generation']=int(s.get('scan_generation',0))+1
    save_session(chat_id)
    send_message(chat_id,f"🚨 *توقف ایمنی REAL فعال شد.*\n\n{reason}\n\nتا بررسی وضعیت CoinEx، معامله جدید مجاز نیست.")


def set_protection(chat_id, symbol, sl, tp):
    ex=get_exchange(chat_id)
    if not ex: return False,'exchange unavailable'
    m=market_name(symbol); errors=[]; responses=[]
    params={'market':m,'market_type':'FUTURES','stop_loss_type':PROTECTION_TRIGGER,'stop_loss_price':str(sl)}
    try: responses.append(call_implicit_any(ex,['v2PrivatePostFuturesSetPositionStopLoss','v2_private_post_futures_set_position_stop_loss'],params))
    except Exception as e: errors.append(f'SL:{e}')
    params={'market':m,'market_type':'FUTURES','take_profit_type':PROTECTION_TRIGGER,'take_profit_price':str(tp)}
    try: responses.append(call_implicit_any(ex,['v2PrivatePostFuturesSetPositionTakeProfit','v2_private_post_futures_set_position_take_profit'],params))
    except Exception as e: errors.append(f'TP:{e}')
    if errors: return False,' | '.join(errors)
    # Verify both response payload and the live position where the exchange exposes them.
    try:
        raw=_live_position_raw(chat_id,symbol)
        if not raw: return False,'position disappeared after protection setup'
        sls=_extract_numbers(responses,{'stop_loss_price','stoploss_price','stop_loss','stoplossprice'})
        tps=_extract_numbers(responses,{'take_profit_price','takeprofit_price','take_profit','takeprofitprice'})
        sls += _extract_numbers(raw,{'stop_loss_price','stoploss_price','stop_loss','stoplossprice'})
        tps += _extract_numbers(raw,{'take_profit_price','takeprofit_price','take_profit','takeprofitprice'})
        if sls and not any(_price_matches(x,sl) for x in sls): return False,f'SL verification mismatch: expected {sl}'
        if tps and not any(_price_matches(x,tp) for x in tps): return False,f'TP verification mismatch: expected {tp}'
        if not sls or not tps:
            # Some CCXT versions omit these fields from the position response; the successful
            # private API calls plus live position are still a weaker verification.
            logger.warning('CoinEx did not expose both protection prices for %s; calls succeeded',symbol)
        return True,'OK'
    except Exception as exc:
        return False,f'protection verification failed: {exc}'


def move_stop_loss(chat_id, symbol, sl):
    ex=get_exchange(chat_id)
    if not ex: return False,'exchange unavailable'
    try:
        call_implicit_any(ex,['v2PrivatePostFuturesSetPositionStopLoss','v2_private_post_futures_set_position_stop_loss'],{'market':market_name(symbol),'market_type':'FUTURES','stop_loss_type':'mark_price','stop_loss_price':str(sl)})
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
    if now-s.get('last_risk_check',0)<15: return not s['daily_stopped']
    s['last_risk_check']=now
    try:
        equity=exchange_balance(chat_id) if s['trading_mode']=='REAL' else current_paper_equity(s)
    except ExchangeStateError as exc:
        if s['trading_mode']=='REAL':
            _halt_real_trading(chat_id,f'اطلاعات حساب CoinEx قابل اعتماد نیست: {exc}')
        return False
    reset_daily_if_needed(chat_id,equity)
    start=float(s['daily_start_equity'])
    if start<=0: return True
    limit=start*(1-float(s['daily_loss_limit_pct'])/100)
    if equity<=limit:
        s['daily_stopped']=True; s['is_bot_active']=False; s['scan_generation']=int(s.get('scan_generation',0))+1; save_session(chat_id)
        send_message(chat_id,f"🛑 *حد ضرر روزانه فعال شد.*\n\nشروع روز: `${start:.2f}`\nEquity: `${equity:.2f}`\nحد: `{s['daily_loss_limit_pct']:.2f}%`\n\nورود جدید متوقف شد؛ پوزیشن‌های باز دست‌نخورده باقی می‌مانند.")
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


def safe_size(chat_id,s,entry,sl):
    try:
        balance=exchange_balance(chat_id) if s['trading_mode']=='REAL' else float(s['paper_balance'])
    except ExchangeStateError as exc:
        return 0,f'account state unavailable: {exc}'
    stop_dist=abs(entry-sl)/max(abs(entry),1e-12)
    if stop_dist<=0 or not math.isfinite(stop_dist): return 0,'invalid stop distance'
    risk_budget=balance*float(s['risk_per_trade_pct'])/100
    leverage=max(1,int(s['leverage']))
    requested_margin=float(s['trade_amount_usdt'])
    cap=balance*float(s['max_margin_usage_pct'])/100
    available=max(0,cap-reserved_margin(s))
    # Risk is based on notional, leverage only converts notional to required margin.
    risk_notional=risk_budget/stop_dist
    risk_margin=risk_notional/leverage
    margin=min(requested_margin,available,risk_margin)
    if margin<=0: return 0,'risk/margin cap blocks entry'
    amount=(margin*leverage)/entry
    if s['trading_mode']=='REAL':
        amount=normalize_amount(chat_id,s.get('_symbol_tmp',''),amount)
    return margin,amount


def expected_trade_pnl(trade):
    """Gross PnL at TP/SL from the actual position amount; excludes fees/funding."""
    try:
        entry=float(trade['entry_price']); tp=float(trade['tp']); sl=float(trade['sl']); amount=abs(float(trade.get('amount') or 0))
        if amount <= 0: return 0.0, 0.0
        if side_long(trade.get('side','BUY')):
            return (tp-entry)*amount, (sl-entry)*amount
        return (entry-tp)*amount, (entry-sl)*amount
    except Exception:
        return 0.0, 0.0

def trade_action_keyboard(symbol):
    return {'inline_keyboard': [
        [{'text':'📊 مدیریت معامله','callback_data':f'/manage_{symbol}'}, {'text':'🔴 بستن معامله','callback_data':f'/close_prompt_{symbol}'}],
        [{'text':'🔄 بروزرسانی','callback_data':f'/manage_{symbol}'}]
    ]}

def close_confirm_keyboard(symbol):
    return {'inline_keyboard': [
        [{'text':'✅ بله، ببند','callback_data':f'/confirm_close_{symbol}'}, {'text':'❌ انصراف','callback_data':'/cancel'}]
    ]}

def format_trade_status(p, price=None):
    entry=float(p.get('entry_price') or 0); sl=float(p.get('sl') or 0); tp=float(p.get('tp') or 0)
    if price is None: price=latest_price(p['symbol']) or entry
    price=float(price)
    amount=abs(float(p.get('amount') or 0))
    if side_long(p.get('side','BUY')):
        pnl=(price-entry)*amount
    else:
        pnl=(entry-price)*amount
    tp_pnl, sl_pnl=expected_trade_pnl(p)
    risk=abs(sl_pnl)
    reward=abs(tp_pnl)
    rr=(reward/risk) if risk>0 else 0
    direction='LONG' if side_long(p.get('side','BUY')) else 'SHORT'
    mode='REAL' if p.get('is_real') else 'PAPER'
    lines=[f'📊 *مدیریت معامله* — `{p["symbol"]}`', '', f'📌 وضعیت: `{"🟢 LONG" if direction=="LONG" else "🔴 SHORT"}` | `{mode}`', f'💰 ورود: `{fmt(entry)}`', f'📍 قیمت فعلی: `{fmt(price)}`', f'🎯 TP: `{fmt(tp)}`', f'🛑 SL: `{fmt(sl)}`', f'📦 حجم: `{amount:.6f}`', '', f'💵 سود/زیان فعلی: `{pnl:+.2f} USDT`', f'🟢 اگر TP فعال شود: `{tp_pnl:+.2f} USDT`', f'🔴 اگر SL فعال شود: `{sl_pnl:+.2f} USDT`', f'⚖️ نسبت سود به ضرر: `{rr:.2f}R`']
    return '\n'.join(lines)

def chart(chat_id,symbol,df,trade):
    """Render a clean trade chart: no EMA overlays, only candles + Entry/TP/SL levels."""
    try:
        if df.empty or len(df) < 5:
            return

        d = df.tail(60).copy().reset_index(drop=True)
        fig, ax = plt.subplots(figsize=(11.5, 6.2), dpi=120)
        fig.patch.set_facecolor('#0f172a')
        ax.set_facecolor('#0f172a')

        # Candlesticks without an external charting dependency.
        body_width = 0.62
        for i, row in d.iterrows():
            o = float(row['open']); h = float(row['high'])
            l = float(row['low']); c = float(row['close'])
            up = c >= o
            candle_color = '#22c55e' if up else '#ef4444'
            ax.vlines(i, l, h, color=candle_color, linewidth=1.1, alpha=0.95, zorder=2)
            bottom = min(o, c)
            height = max(abs(c - o), max((h - l) * 0.003, 1e-12))
            rect = plt.Rectangle((i - body_width / 2, bottom), body_width, height,
                                 facecolor=candle_color, edgecolor=candle_color,
                                 linewidth=0.7, alpha=0.92, zorder=3)
            ax.add_patch(rect)

        entry = float(trade['entry_price'])
        tp = float(trade['tp'])
        sl = float(trade['sl'])
        is_long = side_long(trade.get('side', 'BUY'))

        # Clear horizontal levels. Labels are placed at the right edge so they
        # remain readable even when the chart is viewed inside Telegram.
        levels = [
            (entry, '#60a5fa', 'ENTRY', '-', 1.8),
            (tp, '#22c55e', 'TP', '--', 2.0),
            (sl, '#ef4444', 'SL', '--', 2.0),
        ]
        x_right = len(d) + 1.8
        for value, color, label, style, width in levels:
            ax.axhline(value, color=color, linestyle=style, linewidth=width, alpha=0.95, zorder=1)
            ax.text(x_right, value, f' {label}  {fmt(value)} ',
                    va='center', ha='left', fontsize=9.5, fontweight='bold',
                    color='white',
                    bbox=dict(boxstyle='round,pad=0.28', facecolor=color, edgecolor='none', alpha=0.95),
                    clip_on=False, zorder=5)

        # Highlight the actual entry candle.
        entry_idx = int((d['close'] - entry).abs().idxmin())
        entry_y = float(d.loc[entry_idx, 'low'] if is_long else d.loc[entry_idx, 'high'])
        ax.scatter([entry_idx], [entry_y], s=42, color='#60a5fa', edgecolors='white',
                   linewidths=0.8, zorder=6)
        ax.annotate('ENTRY', xy=(entry_idx, entry_y),
                    xytext=(entry_idx, entry_y + (float(d['high'].max()) - float(d['low'].min())) * (0.07 if is_long else -0.07)),
                    color='white', fontsize=9, fontweight='bold', ha='center',
                    arrowprops=dict(arrowstyle='-|>', color='#60a5fa', lw=1.2), zorder=7)

        # Compact title/header.
        mode = 'REAL' if trade.get('is_real') else 'PAPER'
        direction = 'LONG' if is_long else 'SHORT'
        ax.set_title(f'{symbol}  •  {direction}  •  {mode}', loc='left',
                     color='white', fontsize=15, fontweight='bold', pad=14)

        # Small trade summary inside the chart.
        summary = f"Entry  {fmt(entry)}    TP  {fmt(tp)}    SL  {fmt(sl)}"
        ax.text(0.01, 0.015, summary, transform=ax.transAxes, color='#cbd5e1',
                fontsize=9.5, va='bottom', ha='left',
                bbox=dict(boxstyle='round,pad=0.35', facecolor='#1e293b', edgecolor='#334155', alpha=0.95))

        ax.set_xlim(-1, len(d) + 5.5)
        ymin = float(d['low'].min()); ymax = float(d['high'].max())
        pad = max((ymax - ymin) * 0.08, abs(entry) * 0.002)
        ax.set_ylim(min(ymin, sl, tp) - pad, max(ymax, sl, tp) + pad)
        ax.grid(True, axis='y', color='#334155', alpha=0.45, linewidth=0.7)
        ax.grid(False, axis='x')
        ax.tick_params(axis='both', colors='#94a3b8', labelsize=8.5)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.set_xticks([])
        ax.set_ylabel('Price', color='#94a3b8', fontsize=9)

        # Give the right-side level labels enough room.
        plt.subplots_adjust(left=0.06, right=0.82, top=0.90, bottom=0.10)
        b = io.BytesIO()
        plt.savefig(b, format='png', dpi=120, bbox_inches='tight', facecolor=fig.get_facecolor())
        plt.close(fig)
        b.seek(0)

        tp_pnl, sl_pnl = expected_trade_pnl(trade)
        risk_abs=abs(sl_pnl); reward_abs=abs(tp_pnl); rr=(reward_abs/risk_abs) if risk_abs>0 else 0
        send_photo(
            chat_id, b.getvalue(),
            f"📊 *معامله جدید [{mode}]*\n"
            f"• `{symbol}` {trade['side']}\n"
            f"• ورود: `{fmt(entry)}`\n"
            f"• مارجین: `${trade['margin']:.2f}` | `{trade['leverage']}X`\n"
            f"• حد سود: `{fmt(tp)}` → 🟢 `{tp_pnl:+.2f} USDT`\n"
            f"• حد ضرر: `{fmt(sl)}` → 🔴 `{sl_pnl:+.2f} USDT`\n"
            f"• نسبت سود به ضرر: `{rr:.2f}R`\n\n"
            f"ℹ️ سود/زیان بالا قبل از کارمزد و Funding است.",
            trade_action_keyboard(symbol)
        )
    except Exception:
        logger.exception('chart error')


def _execute_trade_unlocked(chat_id,symbol,side,signal_price,sl,tp,reason=''):
    s=get_session(chat_id)
    if not s['is_bot_active'] or s['daily_stopped'] or not risk_guard(chat_id): return False
    now=time.time(); cd=float(s['cooldowns'].get(symbol,0))
    if now<cd: return False
    s['cooldowns'].pop(symbol,None)
    if s['filters'].get('no_short_filter') and 'SELL' in side: return False
    if s['filters'].get('no_buy_filter') and 'BUY' in side: return False
    if s['max_open_positions']>0 and len(s['paper_positions'])>=s['max_open_positions']: return False
    if any(p['symbol']==symbol for p in s['paper_positions']): return False

    price=latest_price(symbol) or float(signal_price)
    gap_sl=abs(float(signal_price)-float(sl)); gap_tp=abs(float(tp)-float(signal_price))
    if side_long(side): sl=price-gap_sl; tp=price+gap_tp
    else: sl=price+gap_sl; tp=price-gap_tp
    s['_symbol_tmp']=symbol
    margin, amount_or_reason=safe_size(chat_id,s,price,sl)
    s.pop('_symbol_tmp',None)
    if margin<=0: logger.info('entry blocked %s: %s',symbol,amount_or_reason); return False
    leverage=int(s['leverage'])
    trade={'symbol':symbol,'side':side,'entry_price':price,'sl':sl,'tp':tp,'margin':margin,'leverage':leverage,'amount':0,'timeframe':s['timeframe'],'is_real':False,'opened_at':time.time(),'signal_reason':reason[:500],'risk_pct':float(s['risk_per_trade_pct']),'trailing_activated':False}

    if s['trading_mode']=='REAL':
        ex=get_exchange(chat_id)
        if not ex:
            send_message(chat_id,'❌ حساب CoinEx این کاربر پیکربندی نشده یا اتصال برقرار نیست.'); return False
        sym=ccxt_symbol(symbol)
        try:
            market=ex.market(sym)
            limits=market.get('limits') or {}
            lev_info=market.get('info') or {}
            max_lev=float(lev_info.get('max_leverage') or market.get('maxLeverage') or leverage)
            if leverage>max_lev: leverage=int(max_lev); trade['leverage']=leverage
            ex.set_margin_mode(MARGIN_MODE,sym,{'leverage':leverage})
        except Exception:
            try: ex.set_leverage(leverage,sym,{'marginMode':MARGIN_MODE})
            except Exception as exc: send_message(chat_id,f'❌ تنظیم اهرم `{symbol}` شکست خورد: `{exc}`'); return False
        amount=(margin*leverage)/price
        amount=normalize_amount(chat_id,symbol,amount)
        min_amt=float(((market.get('limits') or {}).get('amount') or {}).get('min') or 0)
        if amount<=0 or (min_amt and amount<min_amt):
            send_message(chat_id,f'❌ حجم معامله `{symbol}` از حداقل مجاز بازار کمتر است.'); return False
        try:
            order=ex.create_order(sym,'market','buy' if side_long(side) else 'sell',amount)
            order_id=order.get('id')
            confirmed=None
            for _ in range(ORDER_CONFIRM_RETRIES):
                try:
                    confirmed=ex.fetch_order(order_id,sym) if order_id else order
                except Exception:
                    confirmed=order
                filled=float((confirmed or {}).get('filled') or 0)
                status=str((confirmed or {}).get('status') or '').lower()
                if filled>0 and (status in ('closed','filled') or not status): break
                time.sleep(ORDER_CONFIRM_DELAY)
            if confirmed is None: confirmed=order
            filled=float(confirmed.get('filled') or 0)
            if filled<=0:
                live=find_position(chat_id,symbol)
                if live and float(live.get('amount') or 0)>0:
                    filled=float(live['amount'])
                    exec_price=float(live.get('entry_price') or price)
                else:
                    raise ExchangeStateError('order fill could not be confirmed')
            else:
                exec_price=float(confirmed.get('average') or confirmed.get('price') or price)
            trade['entry_price']=exec_price; trade['amount']=filled; trade['margin']=exec_price*filled/max(leverage,1); trade['is_real']=True; trade['order_id']=order_id
            if side_long(side): trade['sl']=exec_price-gap_sl; trade['tp']=exec_price+gap_tp
            else: trade['sl']=exec_price+gap_sl; trade['tp']=exec_price-gap_tp
            trade['sl']=normalize_price(chat_id,symbol,trade['sl']); trade['tp']=normalize_price(chat_id,symbol,trade['tp'])
            ok,err=set_protection(chat_id,symbol,trade['sl'],trade['tp'])
            if not ok:
                _halt_real_trading(chat_id,f'ثبت SL/TP برای {symbol} ناموفق بود: {err}')
                try: ex.close_position(sym,None,{'type':'market','amount':filled})
                except Exception as close_exc: send_message(chat_id,f'🚨 *حفاظت شکست و بستن خودکار هم شکست.* `{symbol}`\nSL/TP: `{err}`\nخطای بستن: `{close_exc}`')
                else: send_message(chat_id,f'⚠️ معامله `{symbol}` به‌دلیل عدم ثبت SL/TP فوراً بسته شد.')
                return False
            # If STOP happened while the order was in-flight, do not leave a fresh position running.
            current=get_session(chat_id)
            if not current['is_bot_active'] or int(current.get('scan_generation',0)) != generation:
                try: ex.close_position(sym,None,{'type':'market','amount':filled})
                except Exception as close_exc:
                    _halt_real_trading(chat_id,f'توقف هنگام ورود رخ داد ولی بستن {symbol} ناموفق بود: {close_exc}')
                return False
        except Exception as exc:
            logger.exception('real order failed')
            _halt_real_trading(chat_id,f'وضعیت سفارش REAL {symbol} قابل تأیید نیست: {exc}')
            send_message(chat_id,f'❌ سفارش REAL `{symbol}` به‌طور قطعی تأیید نشد؛ برای جلوگیری از سفارش تکراری، ربات متوقف شد.',parse_mode=None)
            return False
    else:
        if float(s['paper_balance'])-reserved_margin(s)<margin: return False
        trade['amount']=(margin*leverage)/price
        s['paper_positions'].append(trade); save_session(chat_id)

    if trade.get('is_real'): s['paper_positions'].append(trade); save_session(chat_id)
    df=get_klines(symbol,'5min' if s['timeframe']=='multi' else s['timeframe'],80)
    if not df.empty: chart(chat_id,symbol,calculate_indicators(df),trade)
    return True


def execute_trade(chat_id,symbol,side,signal_price,sl,tp,reason=''):
    """Serialize entry transactions so STOP cannot race an order submission."""
    s=get_session(chat_id)
    generation=int(s.get('scan_generation',0))
    if not s['is_bot_active'] or s['daily_stopped']:
        return False
    lock=get_entry_lock(chat_id)
    with lock:
        s=get_session(chat_id)
        if not s['is_bot_active'] or s['daily_stopped'] or int(s.get('scan_generation',0)) != generation:
            return False
        return _execute_trade_unlocked(chat_id,symbol,side,signal_price,sl,tp,reason)



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
            sym=ccxt_symbol(pos['symbol']); amount=float(pos.get('amount') or 0)
            live=find_position(chat_id,pos['symbol']); amount=float(live['amount']) if live else amount
            if amount<=0: return False
            order=ex.close_position(sym,None,{'type':'market','amount':amount})
            price=float(order.get('average') or order.get('price') or latest_price(pos['symbol']) or pos['entry_price'])
            await_until=time.time()+12
            while time.time()<await_until:
                try:
                    if not find_position(chat_id,pos['symbol']): break
                except ExchangeStateError:
                    time.sleep(.5); continue
                time.sleep(.5)
            try:
                if find_position(chat_id,pos['symbol']):
                    raise RuntimeError('exchange still reports an open position after close order')
            except ExchangeStateError as state_exc:
                raise RuntimeError(f'cannot verify close: {state_exc}') from state_exc
            realized=realized_history_value(chat_id,pos['symbol'],float(pos.get('opened_at',time.time()-60)))
            if realized is None:
                # last-resort estimate, explicitly labeled as estimate
                entry=float(pos['entry_price']); frac=((price-entry)/entry) if side_long(pos['side']) else ((entry-price)/entry); realized=float(pos['margin'])*frac*float(pos['leverage'])
                pos['pnl_is_estimate']=True
            else: pos['pnl_is_estimate']=False
            pnl=realized; pos['close_price']=price
        except Exception as exc: send_message(chat_id,f'❌ بستن REAL `{pos["symbol"]}` شکست خورد: `{exc}`',parse_mode=None); return False
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
        rows=get_open_positions(chat_id)
    except ExchangeStateError as exc:
        _halt_real_trading(chat_id,f'تطبیق پوزیشن‌های REAL ممکن نیست: {exc}')
        return False
    live={normalize_real_position(p)['symbol']:normalize_real_position(p) for p in rows}
    known={p['symbol']:p for p in s['paper_positions'] if p.get('is_real')}
    unknown=[x for k,x in live.items() if k not in known]
    if unknown:
        _halt_real_trading(chat_id,'پوزیشن REAL ناشناخته پیدا شد: '+', '.join(x['symbol'] for x in unknown[:15]))
        return False
    for sym,p in list(known.items()):
        if sym in live: p.update(live[sym])
        else:
            hist=position_history_for(chat_id,sym,max(0,int((p.get('opened_at',time.time()-3600)-120)*1000)))
            rp=None
            for h in hist:
                try: rp=float(h.get('realizedPnl') or h.get('info',{}).get('realized_pnl'))
                except: continue
                if rp is not None: break
            p['pnl_usdt']=rp if rp is not None else 0.0; p['pnl_is_estimate']=rp is None; p['close_timestamp']=time.time(); p['close_reason']='external TP/SL or exchange close'
            s['closed_positions'].append(p.copy()); s['paper_positions'].remove(p); s['cooldowns'][sym]=time.time()+300
            send_message(chat_id,f"📌 پوزیشن REAL `{sym}` توسط صرافی بسته شد.\nPnL ثبت‌شده: `{p['pnl_usdt']:+.2f} USDT`")
    s['last_reconcile']=time.time(); save_session(chat_id); return True


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
                ok,err=move_stop_loss(chat_id,p['symbol'],normalize_price(chat_id,p['symbol'],entry))
                if ok: p['sl']=entry; p['trailing_activated']=True; send_message(chat_id,f"🛡️ حد ضرر دنبال‌کننده فعال شد: `{p['symbol']}`")
                else: logger.warning('trailing %s: %s',p['symbol'],err)
        save_session(chat_id); return
    for p in s['paper_positions'][:]:
        df=get_klines(p['symbol'],p.get('timeframe','5min') if p.get('timeframe')!='multi' else '5min',5)
        if df.empty: continue
        c=df.iloc[-1]; high=float(c['high']); low=float(c['low']); close=float(c['close']); exit_price=None; reason=None
        if side_long(p['side']):
            hit_tp=high>=float(p['tp']); hit_sl=low<=float(p['sl'])
            if hit_tp and hit_sl and PAPER_CONSERVATIVE_OHLC: exit_price=float(p['sl']); reason='SL (same candle)'
            elif hit_tp: exit_price=float(p['tp']); reason='TP'
            elif hit_sl: exit_price=float(p['sl']); reason='SL'
            pnl=float(p['margin'])*((close-float(p['entry_price']))/float(p['entry_price']))*float(p['leverage'])
        else:
            hit_tp=low<=float(p['tp']); hit_sl=high>=float(p['sl'])
            if hit_tp and hit_sl and PAPER_CONSERVATIVE_OHLC: exit_price=float(p['sl']); reason='SL (same candle)'
            elif hit_tp: exit_price=float(p['tp']); reason='TP'
            elif hit_sl: exit_price=float(p['sl']); reason='SL'
            pnl=float(p['margin'])*((float(p['entry_price'])-close)/float(p['entry_price']))*float(p['leverage'])
        if s['filters'].get('trailing_stop',True) and not p.get('trailing_activated') and pnl>=float(p['margin'])*.10: p['sl']=float(p['entry_price']); p['trailing_activated']=True
        if reason: close_position(chat_id,p,exit_price,reason)
    save_session(chat_id)


async def scan_symbol(http,chat_id,symbol):
    s=get_session(chat_id)
    if not s['is_bot_active'] or s['daily_stopped']: return
    scan_generation=int(s.get('scan_generation',0))
    if time.time() < float(s['cooldowns'].get(symbol,0)): return
    tf=s['timeframe']; strat=s['active_strategy']; md={}
    if tf=='multi' or strat=='multi':
        for k,v in [('1d','1day'),('4h','4hour'),('1h','1hour'),('15m','15min'),('5m','5min')]:
            d=await get_klines_async(http,symbol,v,140)
            if not d.empty: md[k]=calculate_indicators(d)
        primary=md.get('5m')
        if primary is None or len(primary)<60: return
        primary_tf='5min'; mode='multi'
    else:
        d=await get_klines_async(http,symbol,tf,160)
        if d.empty: return
        primary=calculate_indicators(d); primary_tf=tf; mode='single'
    s=get_session(chat_id)
    if not s['is_bot_active'] or s['daily_stopped'] or int(s.get('scan_generation',0)) != scan_generation: return
    if not risk_guard(chat_id): return
    s=get_session(chat_id)
    if not s['is_bot_active'] or int(s.get('scan_generation',0)) != scan_generation: return
    sig,reason=get_signal_with_reason(primary,md,mode,primary_tf,strat,s['filters'],s['strategy_config'])
    if not sig: return
    c=primary.iloc[-2]; entry=float(c['close']); atr=float(c['atr']); p=get_strategy_params(primary_tf,s['strategy_config'])
    if not math.isfinite(atr) or atr<=0: return
    sl=entry-atr*p['sl'] if sig=='BUY' else entry+atr*p['sl']; tp=entry+atr*p['tp'] if sig=='BUY' else entry-atr*p['tp']
    execute_trade(chat_id,symbol,'BUY (Long)' if sig=='BUY' else 'SELL (Short)',entry,sl,tp,reason)


def performance(chat_id):
    s=get_session(chat_id); closed=s['closed_positions']; total=sum(float(p.get('pnl_usdt',0)) for p in closed); wins=sum(1 for p in closed if float(p.get('pnl_usdt',0))>0); losses=sum(1 for p in closed if float(p.get('pnl_usdt',0))<0); wr=wins/len(closed)*100 if closed else 0
    gross_profit=sum(max(0.0,float(p.get('pnl_usdt',0))) for p in closed)
    gross_loss=sum(min(0.0,float(p.get('pnl_usdt',0))) for p in closed)
    return f"📈 *گزارش عملکرد*\n\nمعاملات: `{len(closed)}`\nبرد: `{wins}` | باخت: `{losses}`\nنرخ برد: `{wr:.1f}%`\nسود ناخالص: `{gross_profit:+.2f} USDT`\nزیان ناخالص: `{gross_loss:+.2f} USDT`\nسود/زیان خالص: `{total:+.2f} USDT`\nموجودی کاغذی: `${s['paper_balance']:.2f}`\n\nبرای شروع یک تست آماری جدید، از دکمه زیر استفاده کنید."


def reset_stats(chat_id):
    s=get_session(chat_id)
    if s.get('paper_positions'):
        return False, '❌ تا وقتی پوزیشن باز دارید، ریست آمار مجاز نیست. ابتدا پوزیشن‌ها را ببندید.'
    # Only performance/history state is reset. User settings, watchlist, credentials
    # and strategy configuration remain untouched.
    s['closed_positions'] = []
    s['daily_stopped'] = False
    if s.get('trading_mode') == 'REAL':
        try:
            equity = exchange_balance(chat_id)
        except Exception:
            return False, '❌ موجودی REAL برای تنظیم مبنای جدید قابل دریافت نیست؛ آمار ریست نشد.'
    else:
        equity = float(s.get('paper_balance', 1000.0))
    s['daily_start_equity'] = float(equity)
    s['daily_start_date'] = time.strftime('%Y-%m-%d', time.gmtime())
    save_session(chat_id)
    return True, f"✅ *آمار تست ریست شد*\n\nتاریخچه معاملات: `0`\nسود/زیان خالص: `0.00 USDT`\nمبنای ریسک روزانه جدید: `{equity:.2f} USDT`\n\n⚙️ تنظیمات، واچ‌لیست، استراتژی و موجودی حذف نشده‌اند."


def analyze(chat_id,symbol):
    s=get_session(chat_id); tf='5min' if s['timeframe']=='multi' else s['timeframe']; d=get_klines(symbol,tf,160)
    if d.empty: return f'❌ داده برای `{symbol}` پیدا نشد.'
    d=calculate_indicators(d); c=d.iloc[-2]
    a,r1=strategy_trend_following(d,tf,s['filters'],s['strategy_config']); b,r2=strategy_breakout(d,s['filters'],s['strategy_config']); m,r3=strategy_mean_reversion(d,s['filters'],s['strategy_config'])
    return f"🔍 *تحلیل `{symbol}`*\n\nقیمت بسته‌شدن: `{fmt(c.close)}`\nEMA20: `{fmt(c.ema20)}` | EMA50: `{fmt(c.ema50)}`\nADX: `{float(c.adx):.1f}` | RSI: `{float(c.rsi):.1f}` | ATR: `{fmt(c.atr)}`\n\nروند: `{a or 'NO'}` — {r1}\nشکست: `{b or 'NO'}` — {r2}\nبازگشت به میانگین: `{m or 'NO'}` — {r3}"


def menu(chat_id,message_id=None):
    s=get_session(chat_id); bal=exchange_balance(chat_id) if s['trading_mode']=='REAL' else s['paper_balance']; maxp=s['max_open_positions'] if s['max_open_positions']>0 else '∞'
    text=f"📊 *پنل ربات*\n\nحالت: `{s['trading_mode']}`\nوضعیت: `{'فعال' if s['is_bot_active'] else 'متوقف'}`\nاستراتژی: `{s['active_strategy'].upper()}`\nموجودی: `${bal:.2f}`\nمارجین: `${s['trade_amount_usdt']:.0f}` | اهرم: `{s['leverage']}X`\nپوزیشن‌ها: `{maxp}`\nتایم‌فریم: `{TF_DISPLAY.get(s['timeframe'],s['timeframe'])}`\nریسک هر معامله: `{s['risk_per_trade_pct']:.2f}%`\nحد ضرر روزانه: `{s['daily_loss_limit_pct']:.2f}%`"
    send_message(chat_id,text,get_main_menu_keyboard(s['is_bot_active']),message_id)


def stop_scan(chat_id, reason='manual'):
    s=get_session(chat_id)
    with STATE_LOCK:
        s['scan_generation']=int(s.get('scan_generation',0))+1
        s['is_bot_active']=False
        s['last_stop_reason']=reason
    save_session(chat_id)
    # منتظر تراکنش ورود جاری می‌مانیم؛ بعد از این نقطه سفارش جدیدی اجازه عبور ندارد.
    with get_entry_lock(chat_id):
        pass
    logger.info('SCAN STOP chat=%s generation=%s reason=%s',chat_id,s['scan_generation'],reason)
    return s


def start_scan(chat_id,message_id=None):
    s=get_session(chat_id)
    if s['daily_stopped']:
        try:
            equity=exchange_balance(chat_id) if s['trading_mode']=='REAL' else current_paper_equity(s)
        except Exception:
            send_message(chat_id,'❌ اطلاعات حساب برای شروع اسکن در دسترس نیست.')
            return
        s['daily_stopped']=False
        s['daily_start_equity']=equity
    if s['trading_mode']=='REAL':
        if not get_exchange(chat_id):
            send_message(chat_id,'❌ حساب CoinEx برای این کاربر تنظیم نشده است.')
            return
        try:
            exchange_balance(chat_id)
        except ExchangeStateError as exc:
            send_message(chat_id,f'❌ اطلاعات حساب REAL قابل اعتماد نیست: `{exc}`',parse_mode=None)
            return
        if not reconcile_real(chat_id):
            return
        s['real_reconciliation_required']=False
    with get_entry_lock(chat_id):
        s['scan_generation']=int(s.get('scan_generation',0))+1
        s['is_bot_active']=True
        s['last_stop_reason']=None
        save_session(chat_id)
    menu(chat_id,message_id)



def _market_snapshot(symbol, tf):
    """Build one market snapshot from the latest CLOSED candle."""
    try:
        d = get_klines(symbol, tf, 160)
        if d.empty or len(d) < 60:
            return None
        d = calculate_indicators(d)
        c = d.iloc[-2]
        prev = d.iloc[-3]
        close = float(c.close)
        ema20 = float(c.ema20)
        ema50 = float(c.ema50)
        adx = float(c.adx)
        rsi = float(c.rsi)
        atr = float(c.atr)
        volume_ratio = float(c.volume / d['volume'].rolling(20).mean().iloc[-2]) if float(d['volume'].rolling(20).mean().iloc[-2]) > 0 else 0.0
        atr_pct = atr / close * 100 if close else 0.0
        # Simple, transparent regime classification from the existing indicators.
        if close > ema20 > ema50 and adx >= 25:
            regime = 'صعودی قوی'
            score = 2
        elif close < ema20 < ema50 and adx >= 25:
            regime = 'نزولی قوی'
            score = -2
        elif close > ema50 and ema20 >= ema50:
            regime = 'صعودی'
            score = 1
        elif close < ema50 and ema20 <= ema50:
            regime = 'نزولی'
            score = -1
        else:
            regime = 'خنثی / گذار'
            score = 0
        if adx < 20:
            regime = 'رنج / کم‌روند'
        elif 20 <= adx < 25 and score == 0:
            regime = 'گذار'
        change_pct = (close / float(prev.close) - 1) * 100 if float(prev.close) else 0.0
        return {'symbol': symbol, 'close': close, 'adx': adx, 'rsi': rsi, 'atr_pct': atr_pct,
                'volume_ratio': volume_ratio, 'regime': regime, 'score': score, 'change_pct': change_pct}
    except Exception as exc:
        logger.warning('market snapshot %s failed: %s', symbol, exc)
        return None


def _market_score(results, avg_adx, avg_rsi, avg_atr, avg_vol):
    """0-100 market quality score. Direction and tradability are scored separately."""
    if not results:
        return 0, 'نامشخص'
    bullish = sum(1 for x in results if x['score'] > 0)
    bearish = sum(1 for x in results if x['score'] < 0)
    breadth = bullish / len(results)
    # Trend quality: strongest around ADX 25-35, with diminishing reward after that.
    trend = max(0.0, min(100.0, (avg_adx - 10.0) * 4.0))
    # RSI neutrality avoids rewarding exhausted extremes.
    rsi_quality = max(0.0, 100.0 - abs(avg_rsi - 50.0) * 1.6)
    # Volume confirmation; 1x is baseline.
    volume_quality = max(0.0, min(100.0, avg_vol * 55.0))
    # Moderate volatility is usually more tradable than either dead or chaotic conditions.
    if avg_atr <= 0.6:
        vol_quality = 45.0
    elif avg_atr <= 2.0:
        vol_quality = 90.0
    elif avg_atr <= 4.0:
        vol_quality = 75.0
    else:
        vol_quality = 40.0
    direction_quality = max(breadth, 1.0 - breadth) * 100.0
    score = round(
        trend * 0.30 + direction_quality * 0.25 + rsi_quality * 0.15 +
        volume_quality * 0.15 + vol_quality * 0.15
    )
    if score >= 80:
        label = 'عالی'
    elif score >= 68:
        label = 'خوب'
    elif score >= 52:
        label = 'متوسط'
    elif score >= 38:
        label = 'ضعیف'
    else:
        label = 'پرریسک'
    return max(0, min(100, score)), label


def _volatility_risk(avg_atr):
    if avg_atr >= 4.0:
        return '🔴 زیاد', 'حرکت‌ها شدید است؛ حجم معامله و اهرم باید محافظه‌کارانه‌تر باشد.'
    if avg_atr >= 2.0:
        return '🟠 متوسط رو به زیاد', 'شرایط قابل معامله است ولی نوسان می‌تواند SL را سریع‌تر فعال کند.'
    if avg_atr >= 1.0:
        return '🟢 متعادل', 'نوسان برای معاملات روندی معمولاً مناسب‌تر است.'
    return '🟡 پایین', 'بازار آرام است و احتمال شکست‌های کاذب و حرکت‌های کم‌دامنه بیشتر است.'


def _strategy_market_fit(regime, avg_adx, avg_atr, breadth):
    """Market-level suitability, not a trade signal."""
    trend_ok = avg_adx >= 23 and (breadth >= 0.55 or breadth <= 0.45)
    range_ok = avg_adx < 22 and 35 <= (sum(1 for _ in [1]) * 50) <= 65
    if trend_ok:
        return {
            'dynamic': ('🟢 مناسب', 'روند و اجماع بازار قابل قبول است'),
            'trend': ('🟢 مناسب', 'قدرت روند برای دنبال‌کردن حرکت مناسب است'),
            'breakout': ('🟢 مناسب', 'روند/مومنتوم از شرایط شکست حمایت می‌کند'),
            'mean_reversion': ('🟡 با احتیاط', 'بازار بیش از حد روندی است و برگشت‌گیری ریسک بیشتری دارد'),
            'multi': ('🟢 مناسب', 'هم‌جهتی تایم‌فریم‌ها برای رویکرد ترکیبی بهتر است'),
        }
    if avg_adx < 20:
        return {
            'dynamic': ('🟡 متوسط', 'بازار کم‌روند است'),
            'trend': ('🔴 نامناسب', 'قدرت روند کافی نیست'),
            'breakout': ('🔴 نامناسب', 'شکست‌های کاذب محتمل‌ترند'),
            'mean_reversion': ('🟢 مناسب', 'رنج و نوسان محدود برای برگشت‌گیری مناسب‌تر است'),
            'multi': ('🟡 متوسط', 'سیگنال‌های چندتایم‌فریمی ممکن است دیرتر شکل بگیرند'),
        }
    return {
        'dynamic': ('🟢 مناسب', 'شرایط ترکیبی و نیازمند انتخاب پویاست'),
        'trend': ('🟡 متوسط', 'روند هنوز اجماع کافی ندارد'),
        'breakout': ('🟡 متوسط', 'برای شکست نیاز به تأیید حجم دارد'),
        'mean_reversion': ('🟡 متوسط', 'رنج کامل شکل نگرفته است'),
        'multi': ('🟡 متوسط', 'شرایط بینابینی است'),
    }


def market_report(chat_id):
    """Professional market dashboard. Informational only; never places an order."""
    s = get_session(chat_id)
    tf = '5min' if s['timeframe'] == 'multi' else s['timeframe']
    symbols = ['BTC','ETH','SOL','BNB','XRP','DOGE','ADA','AVAX','LINK','DOT','TRX','LTC']
    now = time.time()
    with MARKET_REPORT_CACHE_LOCK:
        cached = MARKET_REPORT_CACHE.get((chat_id, tf))
        if cached and now - cached[0] < 30:
            return cached[1]
    results = []
    with ThreadPoolExecutor(max_workers=min(6, len(symbols))) as ex:
        futures = [ex.submit(_market_snapshot, sym, tf) for sym in symbols]
        for f in as_completed(futures):
            try:
                item = f.result()
                if item:
                    results.append(item)
            except Exception as exc:
                logger.warning('market dashboard worker failed: %s', exc)
    if not results:
        return '❌ داده کافی برای ساخت داشبورد بازار دریافت نشد. چند لحظه بعد دوباره تلاش کنید.'

    results.sort(key=lambda x: x['score'], reverse=True)
    bullish = sum(1 for x in results if x['score'] > 0)
    bearish = sum(1 for x in results if x['score'] < 0)
    neutral = len(results) - bullish - bearish
    avg_adx = sum(x['adx'] for x in results) / len(results)
    avg_rsi = sum(x['rsi'] for x in results) / len(results)
    avg_atr = sum(x['atr_pct'] for x in results) / len(results)
    avg_vol = sum(x['volume_ratio'] for x in results) / len(results)
    breadth = bullish / len(results)
    market_score, score_label = _market_score(results, avg_adx, avg_rsi, avg_atr, avg_vol)
    vol_label, vol_note = _volatility_risk(avg_atr)

    btc = next((x for x in results if x['symbol'] == 'BTC'), None)
    alts = [x for x in results if x['symbol'] != 'BTC']
    alt_bull = sum(1 for x in alts if x['score'] > 0)
    alt_breadth = alt_bull / len(alts) * 100 if alts else 0
    fit = _strategy_market_fit('', avg_adx, avg_atr, breadth)

    if breadth >= .70 and avg_adx >= 25:
        regime = '🟢 صعودی / رونددار'
        bias = 'کفه بازار به سمت خرید است؛ معاملات روندی اولویت بیشتری دارند.'
    elif breadth <= .30 and avg_adx >= 25:
        regime = '🔴 نزولی / رونددار'
        bias = 'فشار فروش غالب است؛ از ورود خلاف‌روند بدون تأیید قوی پرهیز شود.'
    elif avg_adx < 20:
        regime = '🟡 رنج / کم‌روند'
        bias = 'قدرت روند پایین است؛ کیفیت شکست‌ها را سخت‌گیرانه بررسی کنید.'
    else:
        regime = '🟠 ترکیبی / گذار'
        bias = 'بازار اجماع کاملی ندارد؛ انتخاب معامله باید گزینشی‌تر باشد.'

    def coin_line(x):
        arrow = '🟢' if x['score'] > 0 else '🔴' if x['score'] < 0 else '⚪'
        return f"{arrow} `{x['symbol']}` {x['change_pct']:+.1f}% | ADX {x['adx']:.0f} | RSI {x['rsi']:.0f}"

    top = results[:4]
    weak = sorted(results, key=lambda x: x['score'])[:4]
    btc_line = coin_line(btc) if btc else '⚪ داده BTC موجود نیست'
    fit_lines = [
        f"• روندی: {fit['trend'][0]} — {fit['trend'][1]}",
        f"• شکست: {fit['breakout'][0]} — {fit['breakout'][1]}",
        f"• میانگین‌گرایی: {fit['mean_reversion'][0]} — {fit['mean_reversion'][1]}",
        f"• مولتی‌تایم‌فریم: {fit['multi'][0]} — {fit['multi'][1]}",
        f"• داینامیک: {fit['dynamic'][0]} — {fit['dynamic'][1]}",
    ]
    bar = '█' * round(market_score / 10) + '░' * (10 - round(market_score / 10))
    lines = [
        '🌐 *داشبورد حرفه‌ای بازار*',
        f"⏱ تایم‌فریم: `{TF_DISPLAY.get(tf, tf)}` | بررسی: `{len(results)}` نماد",
        '',
        f"🎯 *امتیاز کیفیت بازار: `{market_score}/100`* — {score_label}",
        f"`{bar}`",
        f"🧭 رژیم بازار: {regime}",
        f"📈 پهنا: `{bullish}` صعودی | `{bearish}` نزولی | `{neutral}` خنثی | `{breadth*100:.0f}%` صعودی",
        f"💪 قدرت روند: ADX میانگین `{avg_adx:.1f}` | RSI میانگین `{avg_rsi:.1f}`",
        f"🌪 ریسک نوسان: {vol_label} | ATR `{avg_atr:.2f}%`",
        f"📦 حجم نسبی: `{avg_vol:.2f}x`",
        '',
        '₿ *وضعیت BTC*',
        btc_line,
        f"🪙 *آلت‌کوین‌ها:* `{alt_bull}/{len(alts)}` صعودی | پهنا `{alt_breadth:.0f}%`",
        '',
        '🏆 *قوی‌ترها*',
        *[coin_line(x) for x in top],
        '',
        '⚠️ *ضعیف‌ترها*',
        *[coin_line(x) for x in weak],
        '',
        '🤖 *تناسب استراتژی با شرایط فعلی*',
        *fit_lines,
        '',
        f"🧠 *برداشت سیستم:* {bias}",
        f"💡 {vol_note}",
        '⚠️ این داشبورد فیلتر تصمیم‌گیری است، نه سیگنال ورود مستقل. قبل از معامله، سیگنال، ریسک، SL/TP و وضعیت پوزیشن بررسی می‌شود.'
    ]
    text = '\n'.join(lines)
    with MARKET_REPORT_CACHE_LOCK:
        MARKET_REPORT_CACHE[(chat_id, tf)] = (now, text)
    return text



def process_command(cmd,chat_id,message_id=None):
    s=get_session(chat_id); c=(cmd or '').strip(); cl=c.lower()
    sensitive_prefixes=('/mode_paper','/mode_real','/set_bal_','/set_margin_','/set_lev_','/set_max_','/set_tf_','/toggle_','/adx_','/sl_','/tp_')
    if s['is_bot_active'] and cl.startswith(sensitive_prefixes): send_message(chat_id,'⚠️ ابتدا اسکن را متوقف کنید.'); return
    if cl=='/start': s['is_bot_active']=False; s['user_state']=None; save_session(chat_id); send_message(chat_id,'🤖 *ربات معامله‌گر*\n\nحالت حساب را انتخاب کنید.',get_start_keyboard()); return
    if cl in ('/menu',): s['user_state']=None; menu(chat_id,message_id); return
    if cl=='/cancel': s['user_state']=None; save_session(chat_id); menu(chat_id); return
    if cl in ('/stop_scan',) or c in ('🔴 توقف اسکن','توقف اسکن'):
        stop_scan(chat_id, 'manual')
        menu(chat_id,message_id)
        return
    if cl in ('/start_scan',) or c in ('🟢 شروع اسکن','شروع اسکن','روشن کردن اسکن'):
        start_scan(chat_id,message_id)
        return
    # سازگاری با دکمه‌های قدیمی نسخه‌های قبلی
    if cl=='/toggle_active':
        if s['is_bot_active']:
            stop_scan(chat_id, 'manual-toggle')
            menu(chat_id,message_id)
        else:
            start_scan(chat_id,message_id)
        return
    if cl=='/mode_paper':
        if s['paper_positions']: send_message(chat_id,'❌ تا وقتی پوزیشن باز دارید نمی‌توانید به PAPER بروید.'); return
        s['trading_mode']='PAPER'; s['is_bot_active']=False; save_session(chat_id); send_message(chat_id,'⚙️ موجودی PAPER را انتخاب کنید.',get_balance_keyboard()); return
    if cl=='/mode_real':
        if s['paper_positions']: send_message(chat_id,'❌ ابتدا تمام پوزیشن‌های فعلی را ببندید.'); return
        if not get_exchange(chat_id): send_message(chat_id,'❌ حساب CoinEx این کاربر در `COINEX_ACCOUNTS_JSON` تنظیم نشده یا اتصال ناموفق است.'); return
        bal=exchange_balance(chat_id)
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
        send_message(chat_id, '⏳ *در حال تهیه گزارش جامع بازار...*\nداده چندین نماد در حال بررسی است.', get_bottom_menu_keyboard(s['is_bot_active']))
        send_message(chat_id, market_report(chat_id))
        return
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
    if cl=='/performance' or 'گزارش عملکرد' in c: send_message(chat_id,performance(chat_id),get_performance_keyboard()); return
    if cl=='/reset_stats_prompt':
        if s.get('paper_positions'):
            send_message(chat_id,'❌ تا وقتی پوزیشن باز دارید، ریست آمار مجاز نیست. ابتدا پوزیشن‌ها را ببندید.'); return
        send_message(chat_id,'⚠️ *ریست آمار تست*\n\nتاریخچه معاملات، PnL و آمار عملکرد صفر می‌شود.\nتنظیمات، واچ‌لیست، استراتژی و موجودی حفظ می‌شوند.\n\nاین عملیات قابل برگشت نیست. ادامه می‌دهید؟', {"inline_keyboard": [[{"text":"🔄 بله، ریست کن","callback_data":"/reset_stats_confirm"},{"text":"❌ انصراف","callback_data":"/cancel"}]]}); return
    if cl=='/reset_stats_confirm':
        ok,msg=reset_stats(chat_id); send_message(chat_id,msg,get_performance_keyboard() if ok else get_bottom_menu_keyboard(s['is_bot_active'])); return
    if cl=='/check_wizard': send_message(chat_id,'⚙️ *تنظیمات معامله*',get_margin_keyboard()); return
    if cl=='/manage_watchlist': send_message(chat_id,f'📋 واچ‌لیست: `{len(s["active_symbols"])}`',get_watchlist_manage_keyboard()); return
    if cl=='/watchlist_list': send_message(chat_id,'📋 *واچ‌لیست*\n\n`'+', '.join(s['active_symbols'])+'`'); return
    if cl=='/add_symbol_prompt': s['user_state']='ADD_SYMBOL'; save_session(chat_id); send_message(chat_id,'➕ نماد را بفرستید'); return
    if cl=='/remove_symbol_prompt': s['user_state']='REMOVE_SYMBOL'; save_session(chat_id); send_message(chat_id,'➖ نماد را بفرستید'); return
    if cl.startswith('/manage_'):
        sym=cl.replace('/manage_','').upper()
        for p in s['paper_positions']:
            if p['symbol']==sym:
                send_message(chat_id,format_trade_status(p),trade_action_keyboard(sym)); return
        send_message(chat_id,f'❌ پوزیشن `{sym}` پیدا نشد.'); return
    if cl.startswith('/close_prompt_'):
        sym=cl.replace('/close_prompt_','').upper()
        for p in s['paper_positions']:
            if p['symbol']==sym:
                price=latest_price(sym) or p.get('entry_price')
                status=format_trade_status(p,price)
                send_message(chat_id,status+'\n\n⚠️ اگر مطمئن هستید، تأیید کنید که پوزیشن با قیمت بازار بسته شود.',close_confirm_keyboard(sym)); return
        send_message(chat_id,f'❌ پوزیشن `{sym}` پیدا نشد.'); return
    if cl.startswith('/confirm_close_'):
        sym=cl.replace('/confirm_close_','').upper()
        for p in s['paper_positions'][:]:
            if p['symbol']==sym:
                close_position(chat_id,p,reason='manual'); return
        send_message(chat_id,f'❌ پوزیشن `{sym}` پیدا نشد.'); return
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
    # دکمه‌های ثابت Reply Keyboard به صورت متن ارسال می‌شوند، نه callback_query.
    # آن‌ها را قبل از منطق state به command داخلی تبدیل می‌کنیم تا همه کلیدهای ثابت کار کنند.
    raw=(text or '').strip()
    fixed_buttons={
        '🏠 منوی اصلی':'/menu',
        'منوی اصلی':'/menu',
        '🔄 پوزیشن‌های باز':'/open_positions',
        'پوزیشن‌های باز':'/open_positions',
        '📈 گزارش عملکرد کلی':'/performance',
        'گزارش عملکرد کلی':'/performance',
        '📊 گزارش وضعیت بازار':'/market_report',
        'وضعیت بازار':'/market_report',
        '📊 وضعیت بازار':'/market_report',
        '⚙️ تنظیمات فیلترها':'/filters_menu',
        'تنظیمات فیلترها':'/filters_menu',
        '🎛️ تنظیم پارامترها':'/params_menu',
        'تنظیم پارامترها':'/params_menu',
        '⚙️ تنظیمات معامله':'/check_wizard',
        'تنظیمات معامله':'/check_wizard',
        '📊 استراتژی':'/strategies_menu',
        'استراتژی':'/strategies_menu',
        '📋 واچ‌لیست':'/manage_watchlist',
        'واچ‌لیست':'/manage_watchlist',
        '❌ بستن همه':'/close_all_prompt',
        'بستن همه':'/close_all_prompt',
        '🔍 تحلیل ارز':'/analyze_single',
        'تحلیل ارز':'/analyze_single',
    }
    if raw in fixed_buttons:
        process_command(fixed_buttons[raw],chat_id)
        return
    s=get_session(chat_id); val=raw.upper()
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


def telegram_listener():
    global TELEGRAM_OFFSET
    backlog_checked=False
    while True:
        if not TELEGRAM_TOKEN:
            time.sleep(5); continue
        try:
            params={'timeout':25}
            if TELEGRAM_OFFSET>0:
                params['offset']=TELEGRAM_OFFSET
            elif TELEGRAM_SKIP_BACKLOG and not backlog_checked:
                # اولین اجرای نسخه جدید: پیام‌های قدیمی اجرا نشوند.
                params.update({'limit':100,'timeout':0})
                r=requests.get(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates',params=params,timeout=10)
                if r.ok:
                    updates=r.json().get('result',[])
                    if updates:
                        save_telegram_offset(int(updates[-1].get('update_id',0))+1)
                backlog_checked=True
                time.sleep(1)
                continue
            r=requests.get(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates',params=params,timeout=30)
            if not r.ok:
                time.sleep(2); continue
            updates=r.json().get('result',[])
            for u in updates:
                upd=int(u.get('update_id',0))
                # قبل از اجرای فرمان ACK می‌کنیم تا خطای ارسال پاسخ باعث اجرای دوباره فرمان نشود.
                save_telegram_offset(upd+1)
                try:
                    callback=u.get('callback_query') or {}
                    msg=callback.get('message') or u.get('message') or {}
                    chat=(msg.get('chat') or {}).get('id')
                    if not chat: continue
                    if callback.get('id'): answer_callback(callback['id'])
                    if not is_allowed(chat): continue
                    data=callback.get('data') or (u.get('message') or {}).get('text')
                    if callback: process_command(data,chat,msg.get('message_id'))
                    elif data: handle_text(chat,data)
                except Exception:
                    logger.exception('Telegram update %s processing failed',upd)
        except Exception as exc:
            logger.exception('Telegram listener: %s',exc); time.sleep(2)


async def scan_loop():
    global ASYNC_SEMAPHORE
    ASYNC_SEMAPHORE=asyncio.Semaphore(MAX_ASYNC_REQUESTS)
    while True:
        try:
            for cid,s in list(USER_SESSIONS.items()):
                if s['trading_mode']=='REAL' and s['is_bot_active']:
                    reconcile_real(cid)
                update_positions(cid)
            timeout=aiohttp.ClientTimeout(total=10)
            conn=aiohttp.TCPConnector(limit=MAX_ASYNC_REQUESTS,ttl_dns_cache=300)
            async with aiohttp.ClientSession(timeout=timeout,connector=conn) as http:
                tasks=[]
                for cid,s in list(USER_SESSIONS.items()):
                    if not s['is_bot_active'] or s['daily_stopped']: continue
                    if not risk_guard(cid): continue
                    # If capacity is full there is no point launching scanner tasks.
                    if s['max_open_positions']>0 and len(s['paper_positions'])>=s['max_open_positions']: continue
                    for sym in list(s['active_symbols']): tasks.append(scan_symbol(http,cid,sym))
                if tasks: await asyncio.gather(*tasks,return_exceptions=True)
        except Exception as exc: logger.exception('scan loop: %s',exc)
        await asyncio.sleep(SCAN_INTERVAL_SECONDS)


@app.get('/')
def home(): return f"OK - Sessions: {len(USER_SESSIONS)} | Active: {sum(1 for s in USER_SESSIONS.values() if s.get('is_bot_active'))}",200
@app.get('/health')
def health(): return 'OK',200
@app.get('/status')
def status():
    key=os.environ.get('STATUS_KEY','').strip()
    if key and request.headers.get('X-Status-Key')!=key: return {'status':'unauthorized'},401
    return {'status':'ok','sessions':len(USER_SESSIONS),'active_bots':sum(1 for s in USER_SESSIONS.values() if s.get('is_bot_active')),'multi_user_real':bool(COINEX_ACCOUNTS)},200


def main():
    init_db(); load_telegram_offset(); load_sessions(); logger.info('Loaded %s sessions',len(USER_SESSIONS))
    Thread(target=telegram_listener,daemon=True,name='telegram').start(); Thread(target=lambda:(time.sleep(3),asyncio.run(scan_loop())),daemon=True,name='scanner').start()
    app.run(host='0.0.0.0',port=PORT,threaded=True)

if __name__=='__main__': main()
