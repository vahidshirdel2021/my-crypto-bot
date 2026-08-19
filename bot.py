import os, json, time, asyncio, aiohttp, requests, sqlite3, logging, math, io, hashlib, hmac, re, importlib
import urllib.parse as urlparse
from threading import Thread, RLock
from typing import Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import ccxt
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from flask import Flask, request

import strategy
from strategy import (
    FILTER_DEFAULTS, STRATEGY_DEFAULTS, calculate_indicators, get_signal_with_reason,
    strategy_trend_following,
    strategy_breakout, strategy_mean_reversion, build_trade_plan, get_timeframe_preset,
    _compute_prev_day_levels, evaluate_trend_weakness,
)
from ui import (
    get_start_keyboard, get_balance_keyboard, get_margin_keyboard, get_leverage_keyboard,
    get_max_positions_keyboard, get_timeframe_keyboard, get_main_menu_keyboard,
    get_watchlist_manage_keyboard,
    get_params_menu_keyboard, get_positions_keyboard,
    get_bottom_menu_keyboard, get_confirm_close_all_keyboard, get_learn_menu_keyboard,
    get_performance_keyboard, get_entry_diag_keyboard, get_manual_side_keyboard,
    get_confirm_close_longs_keyboard, get_confirm_close_shorts_keyboard,
)

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
MINIAPP_BASE_URL = os.environ.get('MINIAPP_BASE_URL', '').strip().rstrip('/')
PORT = int(os.environ.get('PORT', '10000'))
DB_PATH = os.environ.get('BOT_DB_PATH', 'trader_bot.sqlite3')
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()
SCAN_INTERVAL_SECONDS = max(20, int(os.environ.get('SCAN_INTERVAL_SECONDS', '45')))
NO_ENTRY_REPORT_SECONDS = max(120, int(os.environ.get('NO_ENTRY_REPORT_SECONDS', '600')))
DATA_CACHE_SECONDS = max(5, int(os.environ.get('DATA_CACHE_SECONDS', '20')))
MAX_ASYNC_REQUESTS = max(2, int(os.environ.get('MAX_ASYNC_REQUESTS', '10')))
DAILY_LOSS_LIMIT_PCT = float(os.environ.get('DAILY_LOSS_LIMIT_PCT', '3'))
RISK_PER_TRADE_PCT = float(os.environ.get('RISK_PER_TRADE_PCT', '0.5'))
MAX_MARGIN_USAGE_PCT = float(os.environ.get('MAX_MARGIN_USAGE_PCT', '50'))
TAKER_FEE_PCT = max(0.0, float(os.environ.get('TAKER_FEE_PCT', '0.05')))
MIN_RISK_TO_FEE_RATIO = max(0.0, float(os.environ.get('MIN_RISK_TO_FEE_RATIO', '3.0')))
REAL_RESTART_LOCK = os.environ.get('REAL_RESTART_LOCK', 'true').lower() not in ('0', 'false', 'no')
MARGIN_MODE = os.environ.get('MARGIN_MODE', 'isolated').lower()
PROTECTION_TRIGGER = os.environ.get('PROTECTION_TRIGGER', 'mark_price').lower()

ENTRY_ORDER_TYPE = os.environ.get('ENTRY_ORDER_TYPE', 'limit').lower()
ORDER_CONFIRM_RETRIES = max(1, int(os.environ.get('ORDER_CONFIRM_RETRIES', '6')))
ORDER_CONFIRM_DELAY = max(0.25, float(os.environ.get('ORDER_CONFIRM_DELAY', '1.0')))
PAPER_CONSERVATIVE_OHLC = os.environ.get('PAPER_CONSERVATIVE_OHLC', 'true').lower() not in ('0', 'false', 'no')
TELEGRAM_SKIP_BACKLOG = os.environ.get('TELEGRAM_SKIP_BACKLOG', 'true').lower() not in ('0', 'false', 'no')

COINEX_ACCOUNTS_JSON = os.environ.get('COINEX_ACCOUNTS_JSON', '{}').strip()
try:
    COINEX_ACCOUNTS = json.loads(COINEX_ACCOUNTS_JSON) if COINEX_ACCOUNTS_JSON else {}
except Exception:
    COINEX_ACCOUNTS = {}

ALLOWED_CHAT_IDS_RAW = os.environ.get('ALLOWED_CHAT_IDS', '').strip()
ALLOWED_CHAT_IDS = {int(x.strip()) for x in ALLOWED_CHAT_IDS_RAW.split(',') if x.strip().lstrip('-').isdigit()}

ALL_SYMBOLS = [
    'BTC','ETH','YFI','MKR','BCH','COMP','KSM','LTC','AAVE','ZEC','EGLD','BNB','DASH','FIL','ZEN','SOL','UNI','DOT','BAL','LIT','BAND','UNFI','SUSHI','SNX','AVAX','ATOM','TRB','ETC','NEO','SFP','BEL','IOTA','AXS','RLC','SXP','GRT','RUNE','ONT','KAVA','OCEAN','1INCH','REN','KNC','HNT','ENJ','ICX','CRV','NEAR','CTK','EOS','THETA','QTUM','MANA','OMG','SAND','ADA','XEM','FTM','RVN','MTL','SC','STORJ','ZIL','SLP','BTS','XRP','BLZ','FET','ALGO','DODO','CHR','AKRO','CVC','STMX','CELR','HBAR','SKL','RSR','REEF','CHZ','LINK','ALICE','ZRX','COTI','ONE','MATIC','XTZ','NKN','ANKR','LINA','HOT','LRC','DOGE','DENT','DGB','WIN','IOST','TRX','BTT','FLM','BAT','VET','SHIB','ARPA','AR','C98','DYDX','TLM','GALA','AUDIO','MASK','BAKE','KEEP','OGN','RAY','KLAY','ATA','GTC','CELO','YFII','CTSI','LUNA','WAVES'
]
DEFAULT_ACTIVE_SYMBOLS = ALL_SYMBOLS[:]
LEGACY_DEFAULT_ACTIVE_SYMBOLS = ['BTC','ETH','SOL','BNB','XRP','ADA','DOGE','LTC','LINK','DOT','AVAX','ATOM','NEAR','TRX','ETC','FIL','UNI','AAVE','MATIC','XTZ']
TIMEFRAME_MAP = {'5min':'5min','15min':'15min','1hour':'1hour','4hour':'4hour','1day':'1day'}
TF_DISPLAY = {'5min':'5م','15min':'15م','1hour':'1س','4hour':'4س','1day':'روزانه','multi':'مولتی'}

SHARED_LONG_WATCHLIST = ['AAVE','ADA','ANKR','ATOM','AVAX','BCH','BNB','BTC','BTT','CRV','DASH','DOGE','DOT','DYDX','EGLD','ETC','ETH','FIL','GALA','HNT','HOT','KSM','LINK','LTC','MATIC','NEAR','QTUM','RUNE','SHIB','SOL','STORJ','THETA','TRX','UNI','WAVES','XRP','XTZ','ZEC']
WINNING_WATCHLISTS = {
    '5min': SHARED_LONG_WATCHLIST,
    '15min': SHARED_LONG_WATCHLIST,
    '1hour': SHARED_LONG_WATCHLIST,
    '4hour': SHARED_LONG_WATCHLIST,
    'multi': SHARED_LONG_WATCHLIST,
}
SUPPORTED_TRADING_TIMEFRAMES = tuple(WINNING_WATCHLISTS.keys())
SHARED_SHORT_WATCHLIST = ['AAVE','ADA','ALGO','ANKR','AR','ATOM','AVAX','AXS','BCH','BNB','BTC','BTT','CHZ','COMP','DASH','DOGE','DOT','DYDX','EGLD','ENJ','ETC','ETH','FIL','GALA','IOTA','KSM','LINK','LTC','LUNA','MANA','MASK','MATIC','NEAR','NEO','ONE','QTUM','RAY','RSR','RUNE','RVN','SAND','SHIB','SKL','SLP','SNX','SOL','STORJ','SUSHI','TRB','TRX','UNI','VET','WAVES','XRP','XTZ','ZEC','ZIL','ZRX']
WINNING_SHORT_WATCHLISTS = {
    '5min': SHARED_SHORT_WATCHLIST,
    '15min': SHARED_SHORT_WATCHLIST,
    '1hour': SHARED_SHORT_WATCHLIST,
    '4hour': SHARED_SHORT_WATCHLIST,
    'multi': SHARED_SHORT_WATCHLIST,
}
LEADER_SYMBOLS = ('BTC','ETH')
COINEX_PUBLIC = 'https://api.coinex.com/v2'
KUCOIN_PUBLIC = 'https://api.kucoin.com/api/v1'

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format='%(asctime)s | %(levelname)s | %(threadName)s | %(message)s')
logger = logging.getLogger('trader_bot')
app = Flask(__name__)
STATE_LOCK = RLock()
DB_LOCK = RLock()
DATA_LOCK = RLock()
USER_SESSIONS: Dict[int, Dict[str, Any]] = {}
ENTRY_DIAG_STATE: Dict[int, Dict[str, Any]] = {}
EXCHANGE_CACHE: Dict[int, Any] = {}
DATA_CACHE: Dict[str, Any] = {}
PRICE_CACHE: Dict[str, Any] = {}
ASYNC_SEMAPHORE = None
ENTRY_LOCKS: Dict[int, RLock] = {}
ENTRY_LOCKS_GUARD = RLock()
TELEGRAM_OFFSET = 0

class ExchangeStateError(RuntimeError):
    pass


def json_default(obj):
    if isinstance(obj, set): return list(obj)
    raise TypeError


def init_db():
    db_existed_before = os.path.exists(DB_PATH)
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
    # هشدار سطح کد برای جلوگیری از تکرار بی‌صدای مشکل «پاک شدن پوزیشن‌ها/عملکرد بعد از Restart»:
    # اگر BOT_DB_PATH صریحاً تنظیم نشده باشد، دیتابیس روی مسیر محلی پیش‌فرض کنار کد قرار می‌گیرد که
    # در اغلب پلتفرم‌های هاست (بدون Persistent Disk/Volume جداگانه) با هر Deploy/Restart از بین می‌رود.
    if not os.environ.get('BOT_DB_PATH', '').strip():
        logger.warning(
            'هشدار ماندگاری داده: BOT_DB_PATH تنظیم نشده؛ دیتابیس روی مسیر پیش‌فرض محلی (%s) ذخیره '
            'می‌شود. اگر هاست شما دیسک دائمی جداگانه (Persistent Disk/Volume) نداشته باشد، این فایل با '
            'هر Restart/Deploy پاک می‌شود و تمام پوزیشن‌ها، تاریخچه و آمار عملکرد از بین می‌رود.', DB_PATH
        )
    if not db_existed_before:
        logger.warning(
            'فایل دیتابیس (%s) هم‌اکنون از صفر ساخته شد. اگر قبلاً سشن یا پوزیشنی برای کاربران وجود '
            'داشته، این یعنی فایل قبلی از بین رفته — احتمالاً چون روی دیسک غیردائمی بوده.', DB_PATH
        )


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


def audit_event(chat_id, trade_id, stage, data=None):
    try:
        s = get_session(chat_id)
        event = {
            'trade_id': str(trade_id),
            'stage': str(stage),
            'ts': time.time(),
            'data': data or {},
        }
        s.setdefault('trade_audit', []).append(event)
        s['trade_audit'] = s['trade_audit'][-2000:]
        save_session(chat_id)
        return event
    except Exception:
        logger.exception('trade audit event failed chat=%s trade=%s stage=%s', chat_id, trade_id, stage)
        return None


def new_trade_id(chat_id, symbol):
    raw = f"{chat_id}:{symbol}:{time.time_ns()}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12].upper()


def audit_trade_record(p):
    return {
        'trade_id': p.get('trade_id'), 'symbol': p.get('symbol'), 'side': p.get('side'),
        'timeframe': p.get('timeframe'), 'strategy': p.get('strategy'),
        'opened_at': p.get('opened_at'), 'closed_at': p.get('close_timestamp'),
        'entry_price': p.get('entry_price'), 'close_price': p.get('close_price'),
        'sl': p.get('sl'), 'tp': p.get('tp'), 'amount': p.get('amount'),
        'margin': p.get('margin'), 'leverage': p.get('leverage'),
        'planned_rr': p.get('planned_rr'), 'quality_score': p.get('quality_score'),
        'quality_label': p.get('quality_label'), 'risk_usdt': p.get('risk_usdt'),
        'pnl_usdt': p.get('pnl_usdt'), 'close_reason': p.get('close_reason'),
        'is_real': p.get('is_real', False), 'order_id': p.get('order_id'),
        'entry_reason': p.get('entry_reason'),
        'fee_usdt': p.get('fee_usdt'), 'pnl_gross_usdt': p.get('pnl_gross_usdt'),
        'duration_seconds': p.get('duration_seconds'),
        'realized_r': p.get('realized_r'),
        'mfe_usdt': p.get('mfe_usdt', 0.0), 'mae_usdt': p.get('mae_usdt', 0.0),
        'mfe_r': p.get('mfe_r', 0.0), 'mae_r': p.get('mae_r', 0.0),
        'last_price': p.get('last_price'),
        'peak_favorable_price': p.get('peak_favorable_price'),
        'peak_adverse_price': p.get('peak_adverse_price'),
        'trailing_activated': p.get('trailing_activated', False),
        'trailing_locked_r': p.get('trailing_locked_r', 0.0),
    }


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
        'trade_audit': [],
        'scan_stats': {'scans': 0, 'symbols': 0, 'signals': 0, 'entries': 0, 'blocked': 0, 'data_errors': 0, 'reason_counts': {}},
        'cooldowns': {},
        'traded_levels': {},
        'user_state': None,
        'active_symbols': DEFAULT_ACTIVE_SYMBOLS[:],
        'filters': FILTER_DEFAULTS.copy(),
        'strategy_config': get_timeframe_preset('5min'),
        'daily_loss_limit_pct': DAILY_LOSS_LIMIT_PCT,
        'risk_per_trade_pct': RISK_PER_TRADE_PCT,
        'max_margin_usage_pct': MAX_MARGIN_USAGE_PCT,
        'real_reconciliation_required': False,
        'last_risk_check': 0,
        'last_reconcile': 0,
        'telegram_offset': None,
        'created_at': int(time.time()),
        'bottom_menu_open': True,
        'entry_diag_enabled': True,
    }


def normalize_session(data):
    s = default_session(); s.update(data or {})
    s['filters'] = {**FILTER_DEFAULTS, **(data.get('filters') or {})}
    s['user_experience'] = data.get('user_experience') if data.get('user_experience') in ('simple','advanced') else 'simple'
    s['paper_positions'] = list(data.get('paper_positions') or [])
    s['closed_positions'] = list(data.get('closed_positions') or [])
    s['trade_audit'] = list(data.get('trade_audit') or [])[-2000:]
    ss = data.get('scan_stats') or {}
    s['scan_stats'] = {**default_session()['scan_stats'], **ss}
    s['scan_stats'].setdefault('reason_counts', {})
    s['cooldowns'] = dict(data.get('cooldowns') or {})
    s['traded_levels'] = dict(data.get('traded_levels') or {})
    stored_symbols = list(data.get('active_symbols') or [])
    if not stored_symbols or set(stored_symbols) == set(LEGACY_DEFAULT_ACTIVE_SYMBOLS):
        s['active_symbols'] = DEFAULT_ACTIVE_SYMBOLS[:]
    else:
        s['active_symbols'] = stored_symbols
    for k in ('paper_balance','daily_start_equity','trade_amount_usdt','daily_loss_limit_pct','risk_per_trade_pct','max_margin_usage_pct'):
        s[k] = float(s.get(k, default_session()[k]))
    if s.get('timeframe') not in SUPPORTED_TRADING_TIMEFRAMES:
        s['timeframe'] = '5min'
    s['strategy_config'] = get_timeframe_preset(s['timeframe'])
    s['is_bot_active'] = False if REAL_RESTART_LOCK else bool(s.get('is_bot_active', False))
    s['scan_generation'] = int(s.get('scan_generation', 0) or 0)
    s['bottom_menu_open'] = bool(s.get('bottom_menu_open', True))
    s['entry_diag_enabled'] = bool(s.get('entry_diag_enabled', True))
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
    fingerprint = hashlib.sha256((creds[0] + '|' + creds[1]).encode('utf-8')).hexdigest()
    cached = EXCHANGE_CACHE.get(chat_id)
    if cached and cached.get('fingerprint') == fingerprint:
        return cached.get('exchange')
    try:
        ex = ccxt.coinex({'apiKey':creds[0],'secret':creds[1],'enableRateLimit':True,'options':{'defaultType':'swap','defaultMarginMode':MARGIN_MODE}})
        ex.load_markets()
        EXCHANGE_CACHE[chat_id] = {'fingerprint': fingerprint, 'exchange': ex}
        logger.info('CoinEx connected/refreshed for chat_id=%s', chat_id)
        return ex
    except Exception as exc:
        EXCHANGE_CACHE.pop(chat_id, None)
        logger.exception('CoinEx init failed for %s: %s', chat_id, exc)
        return None


def is_allowed(chat_id):
    return (not ALLOWED_CHAT_IDS) or (chat_id in ALLOWED_CHAT_IDS)


def tg(method, payload=None, timeout=10):
    if not TELEGRAM_TOKEN: return None
    try:
        r = requests.post(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}', json=payload or {}, timeout=timeout)
        if r.status_code != 200: logger.warning('Telegram %s: %s', method, r.text[:300]); return None
        return r.json()
    except Exception as exc:
        logger.warning('Telegram request failed: %s', exc); return None


TELEGRAM_COMMANDS = [
    {'command':'menu','description':'منوی اصلی'},
]

def configure_telegram_native_menu():
    if not TELEGRAM_TOKEN:
        return
    r=tg('setMyCommands', {'commands': TELEGRAM_COMMANDS}, 10)
    if not r or not r.get('ok'):
        logger.warning('setMyCommands failed')
    r=tg('setChatMenuButton', {'menu_button': {'type':'commands'}}, 10)
    if not r or not r.get('ok'):
        logger.warning('setChatMenuButton failed')


def answer_callback(cid):
    if cid: tg('answerCallbackQuery', {'callback_query_id':cid}, 5)


def send_message(chat_id, text, markup=None, message_id=None, parse_mode='Markdown'):
    if not is_allowed(chat_id): return False
    s = get_session(chat_id)
    if markup is None: markup = get_bottom_menu_keyboard(s['is_bot_active'], s.get('bottom_menu_open', True))
    if message_id:
        body = {'chat_id':chat_id,'message_id':message_id,'text':text,'reply_markup':markup}
        if parse_mode: body['parse_mode'] = parse_mode
        res = tg('editMessageText', body, 10)
        if res and res.get('ok'): return True
        desc = ((res or {}).get('description') or '').lower()
        if 'message is not modified' in desc:
            return True
    body = {'chat_id':chat_id,'text':text,'reply_markup':markup}
    if parse_mode: body['parse_mode'] = parse_mode
    res = tg('sendMessage', body, 10)
    return bool(res and res.get('ok'))


def edit_page(chat_id, text, markup=None, message_id=None, parse_mode='Markdown'):
    return send_message(chat_id, text, markup, message_id=message_id, parse_mode=parse_mode)


def sync_bottom_keyboard(chat_id, status_message=None):
    s = get_session(chat_id)
    active = bool(s.get('is_bot_active'))
    text = status_message or (
        "🟢 اسکن فعال است.\n🔒 تنظیمات حساس تا توقف اسکن قفل هستند."
        if active else
        "🔴 اسکن متوقف است.\n⚙️ تنظیمات آماده تغییر هستند."
    )
    return send_message(chat_id, text, get_bottom_menu_keyboard(active), parse_mode=None)


def send_photo(chat_id, img, caption='', markup=None):
    if not is_allowed(chat_id) or not TELEGRAM_TOKEN: return False
    s = get_session(chat_id)
    if markup is None:
        markup = get_bottom_menu_keyboard(s['is_bot_active'], s.get('bottom_menu_open', True))
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
    except Exception as exc:
        logger.debug('fmt fallback value=%r: %s', v, exc)
        return str(v)


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
    try:
        raw=_live_position_raw(chat_id,symbol)
        if not raw: return False,'position disappeared after protection setup'
        sls=_extract_numbers(responses,{'stop_loss_price','stoploss_price','stop_loss','stoplossprice'})
        tps=_extract_numbers(responses,{'take_profit_price','takeprofit_price','take_profit','takeprofitprice'})
        sls += _extract_numbers(raw,{'stop_loss_price','stoploss_price','stop_loss','stoplossprice'})
        tps += _extract_numbers(raw,{'take_profit_price','takeprofit_price','take_profit','takeprofitprice'})
        if sls and not any(_price_matches(x,sl) for x in sls): return False,f'SL verification mismatch: expected {sl}'
        if tps and not any(_price_matches(x,tp) for x in tps): return False,f'TP verification mismatch: expected {tp}'
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


def round_trip_fee_usdt(margin, leverage):
    try:
        notional = abs(float(margin)) * abs(float(leverage))
        if not math.isfinite(notional): return 0.0
        return notional * (TAKER_FEE_PCT / 100.0) * 2
    except Exception:
        return 0.0


def trailing_locked_r(entry, risk_distance, current_price, is_long):
    try:
        entry=float(entry); risk_distance=float(risk_distance); current_price=float(current_price)
    except Exception:
        return None
    if risk_distance<=0 or not math.isfinite(risk_distance): return None
    r=(current_price-entry)/risk_distance if is_long else (entry-current_price)/risk_distance
    if r<1.0: return None
    step=math.floor(r*2)/2.0
    return max(0.0, step-1.0)


def reset_daily_if_needed(chat_id, equity):
    s=get_session(chat_id); today=time.strftime('%Y-%m-%d',time.gmtime())
    if s.get('daily_start_date')!=today:
        s['daily_start_date']=today; s['daily_start_equity']=float(equity); s['daily_stopped']=False; s['traded_levels']={}; save_session(chat_id)


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
        stop_scan(chat_id, 'daily-risk')
        s=get_session(chat_id)
        s['daily_stopped']=True
        save_session(chat_id)
        sync_bottom_keyboard(chat_id, "🛑 اسکن به‌دلیل حد ضرر روزانه متوقف شد.\n⚙️ تنظیمات آماده تغییر هستند.")
        send_message(chat_id,f"🛑 *حد ضرر روزانه فعال شد.*\n\nشروع روز: `${start:.2f}`\nسرمایه: `${equity:.2f}`\nحد: `{s['daily_loss_limit_pct']:.2f}%`\n\nورود جدید متوقف شد؛ پوزیشن‌های باز دست‌نخورده باقی می‌مانند.")
        return False
    return True


def market_meta(chat_id,symbol):
    ex=get_exchange(chat_id)
    if not ex: return None
    try: return ex.market(ccxt_symbol(symbol))
    except Exception as exc:
        logger.debug('market_meta fallback symbol=%s: %s', symbol, exc)
        return None


def normalize_amount(chat_id,symbol,amount):
    ex=get_exchange(chat_id)
    if not ex: return 0.0
    try: return float(ex.amount_to_precision(ccxt_symbol(symbol),amount))
    except Exception as exc:
        logger.debug('normalize_amount fallback symbol=%s amount=%s: %s', symbol, amount, exc)
        return float(amount)


def normalize_price(chat_id,symbol,price):
    ex=get_exchange(chat_id)
    if not ex: return float(price)
    try: return float(ex.price_to_precision(ccxt_symbol(symbol),price))
    except Exception as exc:
        logger.debug('normalize_price fallback symbol=%s price=%s: %s', symbol, price, exc)
        return float(price)


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
    risk_notional=risk_budget/stop_dist
    risk_margin=risk_notional/leverage
    margin=min(requested_margin,available,risk_margin)
    if margin<=0: return 0,'risk/margin cap blocks entry'
    amount=(margin*leverage)/entry
    if s['trading_mode']=='REAL':
        amount=normalize_amount(chat_id,s.get('_symbol_tmp',''),amount)
    return margin,amount


def expected_trade_metrics(trade):
    try:
        entry=float(trade.get('entry_price') or 0)
        tp=float(trade.get('tp') or 0)
        sl=float(trade.get('sl') or 0)
        amount=abs(float(trade.get('amount') or 0))
        if entry <= 0 or tp <= 0 or sl <= 0 or amount <= 0:
            return {'tp_pnl':0.0,'sl_pnl':0.0,'risk':0.0,'reward':0.0,'rr':0.0,'valid':False}
        if side_long(trade.get('side','BUY')):
            tp_pnl=(tp-entry)*amount
            sl_pnl=(sl-entry)*amount
            valid=(tp > entry and sl < entry)
        else:
            tp_pnl=(entry-tp)*amount
            sl_pnl=(entry-sl)*amount
            valid=(tp < entry and sl > entry)
        risk=abs(sl_pnl)
        reward=abs(tp_pnl)
        rr=(reward/risk) if risk > 0 else 0.0
        return {'tp_pnl':tp_pnl,'sl_pnl':sl_pnl,'risk':risk,'reward':reward,'rr':rr,
                'valid':bool(valid and risk > 0 and reward > 0)}
    except Exception:
        return {'tp_pnl':0.0,'sl_pnl':0.0,'risk':0.0,'reward':0.0,'rr':0.0,'valid':False}


def trade_action_keyboard(symbol, chart_url=None):
    rows = []
    if chart_url:
        rows.append([{'text':'🌐 چارت تعاملی (MiniApp)','web_app':{'url':chart_url}}])
    rows.append([
        {'text':'🖼 دریافت تصویر چارت','callback_data':f'/view_chart_{symbol}'}
    ])
    rows.append([
        {'text':'🛑 تغییر حد ضرر (SL)','callback_data':f'/edit_sl_{symbol}'},
        {'text':'🎯 تغییر حد سود (TP)','callback_data':f'/edit_tp_{symbol}'}
    ])
    rows.append([
        {'text':'🔴 بستن معامله','callback_data':f'/close_prompt_{symbol}'},
        {'text':'🔄 بروزرسانی','callback_data':f'/manage_{symbol}'}
    ])
    rows.append([{'text':'🏠 منوی اصلی','callback_data':'/menu'}])
    return {'inline_keyboard': rows}


def close_confirm_keyboard(symbol):
    return {'inline_keyboard': [
        [{'text':'✅ بله، ببند','callback_data':f'/confirm_close_{symbol}'}, {'text':'❌ انصراف','callback_data':'/cancel'}]
    ]}


def format_trade_status(p, price=None):
    entry=float(p.get('entry_price') or 0)
    sl=float(p.get('sl') or 0)
    tp=float(p.get('tp') or 0)
    if price is None:
        price=latest_price(p['symbol']) or entry
    price=float(price)
    amount=abs(float(p.get('amount') or 0))
    long_side=side_long(p.get('side','BUY'))
    pnl=(price-entry)*amount if long_side else (entry-price)*amount
    metrics=expected_trade_metrics(p)
    mode='REAL' if p.get('is_real') else 'PAPER'

    tp_dist_pct=abs(tp-entry)/entry*100 if entry else 0
    sl_dist_pct=abs(sl-entry)/entry*100 if entry else 0
    fee_est=round_trip_fee_usdt(p.get('margin'), p.get('leverage'))
    net_reward=max(0.0, metrics['reward']-fee_est)
    net_risk=metrics['risk']+fee_est
    net_rr=(net_reward/net_risk) if net_risk>0 else 0.0
    tf_str = TF_DISPLAY.get(p.get('timeframe'), p.get('timeframe', '5min'))

    lines=[
        f'📊 *مدیریت معامله* — `{p["symbol"]}`',
        '',
        f'📌 وضعیت: `{"🟢 LONG" if long_side else "🔴 SHORT"}` | `{mode}` | تایم‌فریم: `{tf_str}`',
        f'💰 ورود: `{fmt(entry)}`',
        f'📍 قیمت فعلی: `{fmt(price)}`',
        f'🎯 حد سود: `{fmt(tp)}`',
        f'🛑 حد ضرر: `{fmt(sl)}`',
        f'📦 حجم: `{amount:.6f}`',
        '',
        f'💵 سود/زیان فعلی: `{pnl:+.2f} USDT`',
        f'🟢 پاداش ناخالص در صورت TP: `+{metrics["reward"]:.2f} USDT`',
        f'🔴 ریسک ناخالص در صورت SL: `-{metrics["risk"]:.2f} USDT`',
        f'⚖️ R:R ناخالص: `{metrics["rr"]:.2f}R`',
        f'💸 کارمزد تخمینی رفت‌وبرگشت: `{fee_est:.2f} USDT`',
        f'🟢 *پاداش خالص در صورت TP:* `+{net_reward:.2f} USDT`',
        f'🔴 *ریسک خالص در صورت SL:* `-{net_risk:.2f} USDT`',
        f'⚖️ *R:R خالص:* `{net_rr:.2f}R`',
        '',
        f'📏 فاصله تا TP: `{tp_dist_pct:.2f}%`',
        f'📏 فاصله تا SL: `{sl_dist_pct:.2f}%`',
    ]
    if not metrics['valid']:
        lines += ['', '⚠️ *هشدار:* ورود، TP، SL و جهت معامله با هم سازگار نیستند.']
    lines += ['', 'ℹ️ برای تغییر حد سود و ضرر از دکمه‌های زیر استفاده کنید.']
    return '\n'.join(lines)


def chart(chat_id, symbol, df, trade):
    try:
        if df.empty or len(df) < 5:
            return

        tf = trade.get('timeframe', '5min')
        tf_label = TF_DISPLAY.get(tf, tf)
        pdh = pdl = None

        if tf in ('5min', '15min'):
            try:
                dated_df, pdh, pdl = _compute_prev_day_levels(df)
            except Exception:
                dated_df = None
            if dated_df is not None and '_date' in dated_df.columns:
                today_date = dated_df['_date'].iloc[-1]
                today_df = dated_df[dated_df['_date'] == today_date]
                d = today_df.copy().reset_index(drop=True) if len(today_df) >= 10 else df.tail(60).copy().reset_index(drop=True)
            else:
                d = df.tail(60).copy().reset_index(drop=True)
        else:
            d = df.tail(50).copy().reset_index(drop=True)

        fig, ax = plt.subplots(figsize=(11.5, 6.2), dpi=120)
        fig.patch.set_facecolor('#0f172a')
        ax.set_facecolor('#0f172a')

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

        levels = [
            (entry, '#60a5fa', 'ENTRY', '-', 1.8),
            (tp, '#22c55e', 'TP', '--', 2.0),
            (sl, '#ef4444', 'SL', '--', 2.0),
        ]
        if pdh is not None:
            levels.append((float(pdh), '#f97316', 'PDH', ':', 1.4))
        if pdl is not None:
            levels.append((float(pdl), '#f97316', 'PDL', ':', 1.4))

        x_right = len(d) + 1.8
        for value, color, label, style, width in levels:
            ax.axhline(value, color=color, linestyle=style, linewidth=width, alpha=0.95, zorder=1)
            ax.text(x_right, value, f' {label}  {fmt(value)} ',
                    va='center', ha='left', fontsize=9.5, fontweight='bold',
                    color='white',
                    bbox=dict(boxstyle='round,pad=0.28', facecolor=color, edgecolor='none', alpha=0.95),
                    clip_on=False, zorder=5)

        entry_idx = int((d['close'] - entry).abs().idxmin())
        entry_y = float(d.loc[entry_idx, 'low'] if is_long else d.loc[entry_idx, 'high'])
        ax.scatter([entry_idx], [entry_y], s=42, color='#60a5fa', edgecolors='white', linewidths=0.8, zorder=6)

        mode = 'REAL' if trade.get('is_real') else 'PAPER'
        direction = 'LONG' if is_long else 'SHORT'
        ax.set_title(f'{symbol}  •  {direction}  •  {tf_label}  •  {mode}', loc='left',
                     color='white', fontsize=15, fontweight='bold', pad=14)

        summary = f"TF: {tf_label} | Entry: {fmt(entry)} | TP: {fmt(tp)} | SL: {fmt(sl)}"
        ax.text(0.01, 0.015, summary, transform=ax.transAxes, color='#cbd5e1',
                fontsize=9.5, va='bottom', ha='left',
                bbox=dict(boxstyle='round,pad=0.35', facecolor='#1e293b', edgecolor='#334155', alpha=0.95))

        ax.set_xlim(-1, len(d) + 5.5)
        ymin = float(d['low'].min()); ymax = float(d['high'].max())
        pad = max((ymax - ymin) * 0.08, abs(entry) * 0.002)
        extra_vals = [v for v in (pdh, pdl) if v is not None]
        ax.set_ylim(min([ymin, sl, tp, *extra_vals]) - pad, max([ymax, sl, tp, *extra_vals]) + pad)
        ax.grid(True, axis='y', color='#334155', alpha=0.45, linewidth=0.7)
        ax.grid(False, axis='x')
        ax.tick_params(axis='both', colors='#94a3b8', labelsize=8.5)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.set_xticks([])
        ax.set_ylabel('Price', color='#94a3b8', fontsize=9)

        plt.subplots_adjust(left=0.06, right=0.82, top=0.90, bottom=0.10)
        b = io.BytesIO()
        plt.savefig(b, format='png', dpi=120, bbox_inches='tight', facecolor=fig.get_facecolor())
        plt.close(fig)
        b.seek(0)

        metrics = expected_trade_metrics(trade)
        send_photo(
            chat_id, b.getvalue(),
            f"📊 *پوزیشن معامله [{mode}]*\n"
            f"• نماد: `{symbol}` ({trade['side']})\n"
            f"• تایم‌فریم: `{tf_label}`\n"
            f"• ورود: `{fmt(entry)}`\n"
            f"• حد سود: `{fmt(tp)}` → `+{metrics['reward']:.2f} USDT`\n"
            f"• حد ضرر: `{fmt(sl)}` → `-{metrics['risk']:.2f} USDT`\n"
            f"• نسبت پاداش به ریسک: `{metrics['rr']:.2f}R`",
            trade_action_keyboard(symbol, miniapp_chart_url(symbol, tf))
        )
    except Exception:
        logger.exception('chart error')


def update_trade_excursions(pos, high, low):
    try:
        entry = float(pos.get('entry_price') or 0)
        margin = float(pos.get('margin') or 0)
        leverage = float(pos.get('leverage') or 1)
        risk = float(pos.get('risk_usdt') or 0)
        if entry <= 0 or margin <= 0 or leverage <= 0:
            return
        if side_long(pos.get('side')):
            favorable = max(0.0, float(high) - entry)
            adverse = max(0.0, entry - float(low))
            fav_price = float(high)
            adv_price = float(low)
        else:
            favorable = max(0.0, entry - float(low))
            adverse = max(0.0, float(high) - entry)
            fav_price = float(low)
            adv_price = float(high)
        scale = margin * leverage / entry
        mfe_usdt = favorable * scale
        mae_usdt = adverse * scale
        if mfe_usdt > float(pos.get('mfe_usdt') or 0.0):
            pos['mfe_usdt'] = mfe_usdt
            pos['peak_favorable_price'] = fav_price
        if mae_usdt > float(pos.get('mae_usdt') or 0.0):
            pos['mae_usdt'] = mae_usdt
            pos['peak_adverse_price'] = adv_price
        pos['mfe_r'] = (float(pos.get('mfe_usdt') or 0.0) / risk) if risk > 0 else 0.0
        pos['mae_r'] = (float(pos.get('mae_usdt') or 0.0) / risk) if risk > 0 else 0.0
        pos['last_price'] = float((float(high) + float(low)) / 2.0)
    except Exception as exc:
        logger.debug('excursion tracking failed trade=%s symbol=%s: %s', pos.get('trade_id'), pos.get('symbol'), exc)


def _execute_trade_unlocked(chat_id,symbol,side,signal_price,sl,tp,reason='',generation=None,require_active=True,structural_tp=False):
    s=get_session(chat_id)
    trade_id = new_trade_id(chat_id, symbol)
    quality_score = None; quality_label = None; planned_rr = None
    m_score=re.search(r'کیفیت (\d+)/100 \(([^)]+)\)', reason or '')
    if m_score:
        quality_score=int(m_score.group(1)); quality_label=m_score.group(2)
    m_rr=re.search(r'R:R ([0-9.]+)R', reason or '')
    if m_rr:
        planned_rr=float(m_rr.group(1))
    level_key = None
    m_level = re.search(r'PD([HL])=([0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)', reason or '')
    if m_level:
        level_key = f"{symbol}:{m_level.group(1)}:{m_level.group(2)}"
    audit_event(chat_id, trade_id, 'signal_and_plan', {'symbol': symbol, 'side': side, 'signal_price': signal_price, 'sl': sl, 'tp': tp, 'reason': reason, 'timeframe': s.get('timeframe'), 'strategy': s.get('active_strategy'), 'quality_score': quality_score, 'quality_label': quality_label, 'planned_rr': planned_rr})
    if (require_active and not s['is_bot_active']) or s['daily_stopped'] or not risk_guard(chat_id):
        return False
    now=time.time(); cd=float(s['cooldowns'].get(symbol,0))
    if now<cd:
        return False
    s['cooldowns'].pop(symbol,None)
    if level_key and level_key in s.get('traded_levels', {}):
        return False
    is_dynamic_strategy = s.get('active_strategy') == 'dynamic'
    if not is_dynamic_strategy and s['filters'].get('no_short_filter') and 'SELL' in side:
        return False
    if not is_dynamic_strategy and s['filters'].get('no_buy_filter') and 'BUY' in side:
        return False
    if s['max_open_positions']>0 and len(s['paper_positions'])>=s['max_open_positions']:
        return False
    if any(p['symbol']==symbol for p in s['paper_positions']):
        return False

    price=latest_price(symbol) or float(signal_price)
    gap_sl=abs(float(signal_price)-float(sl))
    gap_tp=abs(float(tp)-float(signal_price))
    if side_long(side):
        sl=price-gap_sl
        tp=float(tp) if (structural_tp and float(tp)>price) else price+gap_tp
    else:
        sl=price+gap_sl
        tp=float(tp) if (structural_tp and float(tp)<price) else price-gap_tp
    s['_symbol_tmp']=symbol
    margin, amount_or_reason=safe_size(chat_id,s,price,sl)
    s.pop('_symbol_tmp',None)
    if margin<=0:
        return False
    leverage=int(s['leverage'])
    risk_dist=abs(float(price)-float(sl))
    risk_usdt=float(margin)*((risk_dist/float(price))*float(leverage)) if price>0 else 0.0
    fee_estimate=round_trip_fee_usdt(margin,leverage)
    if MIN_RISK_TO_FEE_RATIO>0 and risk_usdt < fee_estimate*MIN_RISK_TO_FEE_RATIO:
        return False
    trade={'trade_id':trade_id,'symbol':symbol,'side':side,'entry_price':price,'sl':sl,'tp':tp,'margin':margin,'leverage':leverage,'amount':0,'timeframe':s['timeframe'],'strategy':s['active_strategy'],'is_real':False,'opened_at':time.time(),'signal_reason':reason[:500],'entry_reason':reason[:500],'risk_pct':float(s['risk_per_trade_pct']),'risk_usdt':risk_usdt,'quality_score':quality_score,'quality_label':quality_label,'planned_rr':planned_rr,'mfe_usdt':0.0,'mae_usdt':0.0,'mfe_r':0.0,'mae_r':0.0,'peak_favorable_price':None,'peak_adverse_price':None,'last_price':price,'duration_seconds':0.0,'realized_r':None,'trailing_activated':False,'risk_distance':gap_sl,'trailing_locked_r':0.0}

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
            ex.set_margin_mode(MARGIN_MODE,sym,{'leverage':leverage})
        except Exception:
            try:
                ex.set_leverage(leverage,sym,{'marginMode':MARGIN_MODE})
            except Exception as exc:
                send_message(chat_id,f'❌ تنظیم اهرم `{symbol}` شکست خورد: `{exc}`'); return False
        amount=(margin*leverage)/price
        amount=normalize_amount(chat_id,symbol,amount)
        min_amt=float(((market.get('limits') or {}).get('amount') or {}).get('min') or 0)
        if amount<=0 or (min_amt and amount<min_amt):
            send_message(chat_id,f'❌ حجم معامله `{symbol}` از حداقل مجاز بازار کمتر است.'); return False
        try:
            norm_price = normalize_price(chat_id, symbol, price)
            if ENTRY_ORDER_TYPE == 'limit':
                order = ex.create_order(sym, 'limit', 'buy' if side_long(side) else 'sell', amount, norm_price)
            else:
                order = ex.create_order(sym, 'market', 'buy' if side_long(side) else 'sell', amount)

            order_id = order.get('id')
            confirmed = None
            for _ in range(ORDER_CONFIRM_RETRIES):
                try:
                    confirmed = ex.fetch_order(order_id, sym) if order_id else order
                except Exception:
                    confirmed = order
                filled = float((confirmed or {}).get('filled') or 0)
                status = str((confirmed or {}).get('status') or '').lower()
                if filled > 0 and (status in ('closed', 'filled') or not status): break
                time.sleep(ORDER_CONFIRM_DELAY)

            if confirmed is None: confirmed = order
            filled = float(confirmed.get('filled') or 0)

            if filled <= 0:
                if order_id:
                    try:
                        ex.cancel_order(order_id, sym)
                    except Exception:
                        pass
                live = find_position(chat_id, symbol)
                if live and float(live.get('amount') or 0) > 0:
                    filled = float(live['amount'])
                    exec_price = float(live.get('entry_price') or norm_price)
                else:
                    send_message(chat_id, f'⏱ سفارش Limit نماد `{symbol}` در قیمت `{fmt(norm_price)}` پر نشد و لغو شد.')
                    return False
            else:
                exec_price = float(confirmed.get('average') or confirmed.get('price') or norm_price)

            trade['entry_price'] = exec_price
            trade['amount'] = filled
            trade['margin'] = exec_price * filled / max(leverage, 1)
            trade['is_real'] = True
            trade['order_id'] = order_id

            if side_long(side):
                trade['sl'] = exec_price - gap_sl
                trade['tp'] = exec_price + gap_tp
            else:
                trade['sl'] = exec_price + gap_sl
                trade['tp'] = exec_price - gap_tp

            trade['sl'] = normalize_price(chat_id, symbol, trade['sl'])
            trade['tp'] = normalize_price(chat_id, symbol, trade['tp'])
            trade['risk_usdt'] = abs(float(trade['entry_price']) - float(trade['sl'])) / max(float(trade['entry_price']), 1e-12) * float(trade['margin']) * float(trade['leverage'])

            audit_event(chat_id, trade_id, 'order_filled', {'entry_price': trade['entry_price'], 'amount': trade['amount'], 'order_id': order_id})
            ok, err = set_protection(chat_id, symbol, trade['sl'], trade['tp'])
            audit_event(chat_id, trade_id, 'protection_set', {'ok': ok, 'detail': err, 'sl': trade.get('sl'), 'tp': trade.get('tp')})
            if not ok:
                _halt_real_trading(chat_id, f'ثبت SL/TP برای {symbol} ناموفق بود: {err}')
                try: ex.close_position(sym, None, {'type': 'market', 'amount': filled})
                except Exception as close_exc: send_message(chat_id, f'🚨 *حفاظت شکست و بستن خودکار هم شکست.* `{symbol}`\nSL/TP: `{err}`\nخطای بستن: `{close_exc}`')
                else: send_message(chat_id, f'⚠️ معامله `{symbol}` به‌دلیل عدم ثبت SL/TP فوراً بسته شد.')
                return False

            current = get_session(chat_id)
            if (require_active and not current['is_bot_active']) or int(current.get('scan_generation', 0)) != generation:
                try: ex.close_position(sym, None, {'type': 'market', 'amount': filled})
                except Exception as close_exc:
                    _halt_real_trading(chat_id, f'توقف هنگام ورود رخ داد ولی بستن {symbol} ناموفق بود: {close_exc}')
                return False
        except Exception as exc:
            _halt_real_trading(chat_id, f'وضعیت سفارش REAL {symbol} قابل تأیید نیست: {exc}')
            send_message(chat_id, f'❌ سفارش REAL `{symbol}` به‌طور قطعی تأیید نشد؛ ربات متوقف شد.', parse_mode=None)
            return False
    else:
        if float(s['paper_balance']) - reserved_margin(s) < margin:
            return False
        trade['amount'] = (margin * leverage) / price
        audit_event(chat_id, trade_id, 'paper_opened', {'entry_price': price, 'amount': trade['amount'], 'margin': margin, 'quality_score': quality_score, 'quality_label': quality_label, 'planned_rr': planned_rr})
        s['paper_positions'].append(trade)
        save_session(chat_id)

    if trade.get('is_real'):
        s['paper_positions'].append(trade)
        save_session(chat_id)
    if level_key:
        s['traded_levels'][level_key] = time.strftime('%Y-%m-%d', time.gmtime())
        save_session(chat_id)

    audit_event(chat_id, trade_id, 'position_opened', audit_trade_record(trade))
    chart_tf = s['timeframe'] if s['timeframe'] != 'multi' else '5min'
    df = get_klines(symbol, chart_tf, 650 if chart_tf in ('5min', '15min') else 200)
    if not df.empty:
        chart(chat_id, symbol, calculate_indicators(df), trade)
    return True


def scan_watchlist_for_timeframe(timeframe, regime=None):
    if regime == 'BEARISH':
        return list(WINNING_SHORT_WATCHLISTS.get(timeframe, WINNING_SHORT_WATCHLISTS['5min']))
    if regime == 'BULLISH':
        return list(WINNING_WATCHLISTS.get(timeframe, WINNING_WATCHLISTS['5min']))
    long_list = WINNING_WATCHLISTS.get(timeframe, WINNING_WATCHLISTS['5min'])
    short_list = WINNING_SHORT_WATCHLISTS.get(timeframe, WINNING_SHORT_WATCHLISTS['5min'])
    return list(dict.fromkeys(list(long_list) + list(short_list)))


MARKET_REGIME_CACHE = {'ts': 0.0, 'regime': 'NEUTRAL', 'detail': '', 'ttl': 90}
MARKET_REGIME_MIN_ADX = float(os.environ.get('MARKET_REGIME_MIN_ADX', '18'))
MARKET_REGIME_TIMEFRAME = os.environ.get('MARKET_REGIME_TIMEFRAME', '4hour')


async def refresh_market_regime(http):
    now = time.time()
    if now - MARKET_REGIME_CACHE['ts'] < MARKET_REGIME_CACHE['ttl']:
        return MARKET_REGIME_CACHE['regime'], MARKET_REGIME_CACHE['detail']
    tf = MARKET_REGIME_TIMEFRAME if MARKET_REGIME_TIMEFRAME in TIMEFRAME_MAP else '4hour'
    states = {}
    for leader in LEADER_SYMBOLS:
        try:
            d = await get_klines_async(http, leader, tf, 120)
            if d is None or d.empty or len(d) < 60:
                detail = f'داده کافی برای {leader} در دسترس نیست'
                MARKET_REGIME_CACHE.update(ts=now, regime='NEUTRAL', detail=detail)
                return 'NEUTRAL', detail
            x = calculate_indicators(d).iloc[-2]
            adx = float(x.get('adx') or 0)
            bullish = bool(x['close'] > x['ema20'] > x['ema50'] and x['plus_di'] > x['minus_di'] and adx >= MARKET_REGIME_MIN_ADX)
            bearish = bool(x['close'] < x['ema20'] < x['ema50'] and x['minus_di'] > x['plus_di'] and adx >= MARKET_REGIME_MIN_ADX)
            states[leader] = ('BULLISH' if bullish else 'BEARISH' if bearish else 'NEUTRAL', adx)
        except Exception as exc:
            detail = f'خطا در دریافت داده {leader}: {exc}'
            MARKET_REGIME_CACHE.update(ts=now, regime='NEUTRAL', detail=detail)
            return 'NEUTRAL', detail
    detail = ' | '.join(f'{leader}={states[leader][0]} (ADX={states[leader][1]:.1f})' for leader in LEADER_SYMBOLS)
    unique_dirs = {v[0] for v in states.values()}
    if 'BULLISH' in unique_dirs and 'BEARISH' not in unique_dirs:
        regime = 'BULLISH'
    elif 'BEARISH' in unique_dirs and 'BULLISH' not in unique_dirs:
        regime = 'BEARISH'
    else:
        regime = 'NEUTRAL'
    MARKET_REGIME_CACHE.update(ts=now, regime=regime, detail=detail)
    return regime, detail


async def leader_correlation_guard(http, chat_id, symbol, primary_df, timeframe, side='BUY'):
    if symbol.upper() in LEADER_SYMBOLS:
        return True, 'لیدر بازار است'
    try:
        if primary_df is None or primary_df.empty:
            return False, 'داده کافی برای سنجش همبستگی موجود نیست'
        leader_frames = {}
        for leader in LEADER_SYMBOLS:
            d = await get_klines_async(http, leader, timeframe if timeframe in TIMEFRAME_MAP else '5min', 100)
            if d is None or d.empty or len(d) < 65:
                return False, f'داده کافی برای {leader} جهت محافظت بازار دریافت نشد'
            leader_frames[leader] = calculate_indicators(d)

        alt = primary_df.copy()
        if len(alt) < 65:
            return False, 'داده کافی برای محاسبه همبستگی ارز هدف موجود نیست'
        alt_ret = pd.to_numeric(alt['close'], errors='coerce').pct_change().dropna().tail(60)

        leader_states = []
        correlations = []
        for leader, frame in leader_frames.items():
            c = frame.iloc[-2]
            ret = pd.to_numeric(frame['close'], errors='coerce').pct_change().dropna().tail(60)
            corr = float(alt_ret.corr(ret)) if len(alt_ret) >= 20 and len(ret) >= 20 else 0.0
            if not math.isfinite(corr):
                corr = 0.0
            correlations.append((leader, corr))
            change_1 = (float(c.close) / float(frame.iloc[-3].close) - 1.0) * 100 if float(frame.iloc[-3].close) else 0.0
            change_3 = (float(c.close) / float(frame.iloc[-5].close) - 1.0) * 100 if float(frame.iloc[-5].close) else 0.0
            bearish = bool(float(c.close) < float(c.ema20) < float(c.ema50) and float(c.adx) >= 20 and change_3 <= -0.8)
            bullish = bool(float(c.close) > float(c.ema20) > float(c.ema50) and float(c.adx) >= 20 and change_3 >= 0.8)
            crash = bool(change_1 <= -1.0 or change_3 <= -2.0)
            pump = bool(change_1 >= 1.0 or change_3 >= 2.0)
            leader_states.append((leader, bearish, crash, change_1, change_3, bullish, pump))

        both_bearish = all(x[1] for x in leader_states)
        both_bullish = all(x[5] for x in leader_states)
        any_crash = any(x[2] for x in leader_states)
        any_pump = any(x[6] for x in leader_states)
        max_corr = max(abs(x[1]) for x in correlations) if correlations else 0.0
        avg_positive_corr = sum(max(0.0, x[1]) for x in correlations) / len(correlations) if correlations else 0.0

        is_long = side_long(side)
        detail = ', '.join(f'{k}={v:+.2f}' for k, v in correlations)
        if is_long:
            if both_bearish and (max_corr >= 0.40 or avg_positive_corr >= 0.55):
                return False, f'محافظ بازار فعال شد؛ BTC و ETH در روند نزولی تأییدشده هستند | همبستگی: {detail}'
            if any_crash and max_corr >= 0.65:
                return False, f'محافظ بازار فعال شد؛ سقوط شدید یکی از لیدرها و همبستگی بالا | همبستگی: {detail}'
        else:
            if both_bullish and (max_corr >= 0.40 or avg_positive_corr >= 0.55):
                return False, f'محافظ بازار فعال شد؛ BTC و ETH در روند صعودی تأییدشده هستند | همبستگی: {detail}'
            if any_pump and max_corr >= 0.65:
                return False, f'محافظ بازار فعال شد؛ جهش شدید یکی از لیدرها و همبستگی بالا | همبستگی: {detail}'

        return True, f'محافظ بازار عبور کرد | همبستگی: {detail}'
    except Exception as exc:
        return False, f'محافظ بازار به دلیل خطا متوقف شد: {exc}'


def execute_trade(chat_id,symbol,side,signal_price,sl,tp,reason='',structural_tp=False):
    s=get_session(chat_id)
    generation=int(s.get('scan_generation',0))
    if not s['is_bot_active'] or s['daily_stopped']:
        return False
    lock=get_entry_lock(chat_id)
    with lock:
        s=get_session(chat_id)
        if not s['is_bot_active'] or s['daily_stopped'] or int(s.get('scan_generation',0)) != generation:
            return False
        return _execute_trade_unlocked(chat_id,symbol,side,signal_price,sl,tp,reason,generation,structural_tp=structural_tp)


def execute_manual_trade(chat_id,symbol,side,sl,tp,entry_price=None):
    s=get_session(chat_id)
    if s['daily_stopped']:
        return False, 'محدودیت ضرر روزانه فعال است؛ ورود دستی هم مسدود است.'
    live_price=latest_price(symbol)
    if not live_price:
        return False, f'قیمت لحظه‌ای `{symbol}` دریافت نشد.'
    price=float(entry_price) if entry_price else live_price
    generation=int(s.get('scan_generation',0))
    lock=get_entry_lock(chat_id)
    with lock:
        s=get_session(chat_id)
        if s['daily_stopped']:
            return False, 'محدودیت ضرر روزانه فعال است؛ ورود دستی هم مسدود است.'
        ok=_execute_trade_unlocked(chat_id,symbol,side,price,sl,tp,'معامله دستی کاربر',generation,require_active=False)
    if ok:
        return True, ''
    return False, 'ورود دستی رد شد (ممکن است ظرفیت پوزیشن پر باشد، نماد از قبل باز باشد، یا حجم/ریسک معتبر نباشد).'


def realized_history_value(chat_id,symbol,opened_at):
    rows=position_history_for(chat_id,symbol,max(0,int((opened_at-120)*1000)))
    if not rows: return None
    best=None; best_ts=0
    for r in rows:
        rp=r.get('realizedPnl') or r.get('info',{}).get('realized_pnl') if isinstance(r,dict) else None
        try: rp=float(rp)
        except: continue
        ts=float(r.get('timestamp') or r.get('datetime') and time.mktime(time.strptime(r['datetime'],'%Y-%m-%dT%H:%M:%S.%fZ'))*1000 or 0)
        if ts>=best_ts: best_ts=ts; best=rp
    return best


def close_position(chat_id,pos,price=None,reason='manual'):
    s=get_session(chat_id)
    if pos not in s['paper_positions']: return False
    fee=round_trip_fee_usdt(pos.get('margin'), pos.get('leverage'))
    fee_note=''
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
            realized=realized_history_value(chat_id,pos['symbol'],float(pos.get('opened_at',time.time()-60)))
            if realized is None:
                entry=float(pos['entry_price']); frac=((price-entry)/entry) if side_long(pos['side']) else ((entry-price)/entry)
                pnl_gross=float(pos['margin'])*frac*float(pos['leverage'])
                realized=pnl_gross-fee
                pos['pnl_is_estimate']=True
                pos['pnl_gross_usdt']=pnl_gross
                fee_note=' (کسر شده در برآورد)'
            else:
                pos['pnl_is_estimate']=False
                fee_note=' (لحاظ شده در صرافی)'
            pnl=realized; pos['close_price']=price
        except Exception as exc: send_message(chat_id,f'❌ بستن REAL `{pos["symbol"]}` شکست خورد: `{exc}`',parse_mode=None); return False
    else:
        if price is None: price=latest_price(pos['symbol']) or pos['entry_price']
        entry=float(pos['entry_price']); frac=((price-entry)/entry) if side_long(pos['side']) else ((entry-price)/entry)
        pnl_gross=float(pos['margin'])*frac*float(pos['leverage'])
        pnl=pnl_gross-fee
        s['paper_balance']+=pnl; pos['close_price']=price; pos['pnl_is_estimate']=False
        pos['pnl_gross_usdt']=pnl_gross
        fee_note=' (کسر شده)'
    pos['fee_usdt']=fee
    if not pos.get('risk_usdt'):
        try: pos['risk_usdt']=abs(float(pos['entry_price'])-float(pos['sl']))/max(float(pos['entry_price']),1e-12)*float(pos['margin'])*float(pos['leverage'])
        except Exception: pos['risk_usdt']=0.0
    pos['pnl_usdt']=float(pnl); pos['close_timestamp']=time.time(); pos['close_reason']=reason
    pos['duration_seconds']=max(0, pos['close_timestamp']-float(pos.get('opened_at', pos['close_timestamp'])))
    pos['realized_r']=(float(pos.get('pnl_usdt') or 0.0)/float(pos.get('risk_usdt') or 0.0)) if float(pos.get('risk_usdt') or 0.0)>0 else None
    update_trade_excursions(pos, float(price), float(price))
    audit_event(chat_id, pos.get('trade_id') or new_trade_id(chat_id, pos.get('symbol','?')), 'position_closed', {'close_price': price, 'pnl_usdt': pnl, 'fee_usdt': fee, 'reason': reason, 'duration_seconds': pos['duration_seconds'], 'realized_r': pos.get('realized_r'), 'mfe_usdt': pos.get('mfe_usdt',0.0), 'mae_usdt': pos.get('mae_usdt',0.0), 'mfe_r': pos.get('mfe_r',0.0), 'mae_r': pos.get('mae_r',0.0)})
    cooldown_len = int(s.get('strategy_config', {}).get('cooldown_seconds', 1200))
    s['cooldowns'][pos['symbol']]=time.time()+cooldown_len; s['closed_positions'].append(pos.copy()); s['paper_positions'].remove(pos); save_session(chat_id)
    est=' تقریبی' if pos.get('pnl_is_estimate') else ''
    fee_line=f"\n• کارمزد تخمینی رفت‌وبرگشت: `{fee:.2f} USDT`{fee_note}" if fee>0 else ''
    send_message(chat_id,f"📌 *پوزیشن {'REAL' if pos.get('is_real') else 'PAPER'} بسته شد*\n• `{pos['symbol']}`\n• خروج: `{fmt(pos['close_price'])}`\n• PnL{est}: `{pnl:+.2f} USDT`{fee_line}\n• علت: `{reason}`")
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
            if rp is None:
                p['pnl_usdt']=0.0
                p['pnl_is_estimate']=True
            else:
                p['pnl_usdt']=rp
                p['pnl_is_estimate']=False
            p['close_timestamp']=time.time()
            p['close_reason']='external TP/SL or exchange close'
            p['duration_seconds']=max(0, p['close_timestamp']-float(p.get('opened_at',p['close_timestamp'])))
            p['realized_r']=(float(p.get('pnl_usdt') or 0.0)/float(p.get('risk_usdt') or 0.0)) if float(p.get('risk_usdt') or 0.0)>0 else None
            cooldown_len = int(s.get('strategy_config', {}).get('cooldown_seconds', 1200))
            s['closed_positions'].append(p.copy()); s['paper_positions'].remove(p); s['cooldowns'][sym]=time.time()+cooldown_len
            audit_event(chat_id, p.get('trade_id') or new_trade_id(chat_id, sym), 'position_closed', {'close_price': p.get('close_price'), 'pnl_usdt': p.get('pnl_usdt'), 'reason': p.get('close_reason'), 'duration_seconds': p.get('duration_seconds'), 'realized_r': p.get('realized_r'), 'mfe_usdt': p.get('mfe_usdt',0.0), 'mae_usdt': p.get('mae_usdt',0.0), 'external': True})
            send_message(chat_id,f"📌 پوزیشن REAL `{sym}` توسط صرافی بسته شد.\nPnL ثبت‌شده: `{p['pnl_usdt']:+.2f} USDT`")
    s['last_reconcile']=time.time(); save_session(chat_id); return True


def _weakness_exit_check(chat_id, s, p, current_r):
    """
    وقتی معامله سود مناسبی دارد ولی هنوز به هدف ساختاری (PDL/PDH) نرسیده،
    این تابع علائم ضعف روند را بررسی می‌کند تا در صورت لزوم پوزیشن با سود
    بسته شود؛ در غیر این صورت اجازه می‌دهد معامله تا رسیدن به TP ادامه یابد.
    خروجی: (should_exit: bool, reasons: list[str])
    """
    try:
        cfg = s.get('strategy_config') or STRATEGY_DEFAULTS
        min_r = float(cfg.get('weakness_exit_min_r', 0.8))
        if current_r < min_r:
            return False, []
        tf = p.get('timeframe', '5min')
        if tf == 'multi':
            tf = '5min'
        wdf = get_klines(p['symbol'], tf, 150)
        if wdf.empty or len(wdf) < 60:
            return False, []
        wdf = calculate_indicators(wdf)
        if wdf.empty or len(wdf) < 60:
            return False, []
        is_weak, wscore, wreasons = evaluate_trend_weakness(wdf, p['side'], cfg)
        return bool(is_weak), wreasons
    except Exception as exc:
        logger.debug('weakness exit check failed trade=%s symbol=%s: %s', p.get('trade_id'), p.get('symbol'), exc)
        return False, []


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
            p['last_price']=float(price)
            try:
                edf=get_klines(p['symbol'],p.get('timeframe','5min') if p.get('timeframe')!='multi' else '5min',3)
                if not edf.empty:
                    update_trade_excursions(p, float(edf['high'].max()), float(edf['low'].min()))
            except Exception as exc:
                logger.debug('real excursion sample failed symbol=%s: %s', p.get('symbol'), exc)
            risk_distance=p.get('risk_distance')
            if not risk_distance and not p.get('trailing_activated'):
                risk_distance=abs(entry-float(p.get('sl',entry)))
            if s['filters'].get('trailing_stop',True):
                lr=trailing_locked_r(entry,risk_distance,price,side_long(p['side'])) if risk_distance else None
                if lr is not None:
                    new_sl=entry+(lr*risk_distance if side_long(p['side']) else -lr*risk_distance)
                    is_better=(new_sl>float(p['sl'])) if side_long(p['side']) else (new_sl<float(p['sl']))
                    if is_better and lr>float(p.get('trailing_locked_r') or 0.0):
                        ok,err=move_stop_loss(chat_id,p['symbol'],normalize_price(chat_id,p['symbol'],new_sl))
                        if ok:
                            first_activation=float(p.get('trailing_locked_r') or 0.0)==0.0
                            p['sl']=new_sl; p['trailing_activated']=True; p['trailing_locked_r']=lr
                            if first_activation: send_message(chat_id,f"🛡️ حد ضرر دنبال‌کننده فعال شد: `{p['symbol']}` (قفل روی {lr:.1f}R)")
            current_r=((price-entry)/risk_distance if side_long(p['side']) else (entry-price)/risk_distance) if risk_distance else 0.0
            should_exit,wreasons=_weakness_exit_check(chat_id,s,p,current_r)
            if should_exit:
                p['weakness_exit_reasons']=wreasons
                close_position(chat_id,p,price,'مدیریت هوشمند (ضعف روند)')
        save_session(chat_id); return
    for p in s['paper_positions'][:]:
        df=get_klines(p['symbol'],p.get('timeframe','5min') if p.get('timeframe')!='multi' else '5min',5)
        if df.empty: continue
        c=df.iloc[-1]; high=float(c['high']); low=float(c['low']); close=float(c['close']); exit_price=None; reason=None
        update_trade_excursions(p, high, low)
        p['last_price']=close
        if side_long(p['side']):
            hit_tp=high>=float(p['tp']); hit_sl=low<=float(p['sl'])
            if hit_tp and hit_sl and PAPER_CONSERVATIVE_OHLC: exit_price=float(p['sl']); reason='SL (same candle)'
            elif hit_tp: exit_price=float(p['tp']); reason='TP'
            elif hit_sl: exit_price=float(p['sl']); reason='SL'
        else:
            hit_tp=low<=float(p['tp']); hit_sl=high>=float(p['sl'])
            if hit_tp and hit_sl and PAPER_CONSERVATIVE_OHLC: exit_price=float(p['sl']); reason='SL (same candle)'
            elif hit_tp: exit_price=float(p['tp']); reason='TP'
            elif hit_sl: exit_price=float(p['sl']); reason='SL'
        entry_p=float(p['entry_price'])
        risk_distance=p.get('risk_distance')
        if not risk_distance and not p.get('trailing_activated'):
            risk_distance=abs(entry_p-float(p.get('sl',entry_p)))
        if s['filters'].get('trailing_stop',True):
            lr=trailing_locked_r(entry_p,risk_distance,close,side_long(p['side'])) if risk_distance else None
            if lr is not None:
                new_sl=entry_p+(lr*risk_distance if side_long(p['side']) else -lr*risk_distance)
                is_better=(new_sl>float(p['sl'])) if side_long(p['side']) else (new_sl<float(p['sl']))
                if is_better and lr>float(p.get('trailing_locked_r') or 0.0):
                    p['sl']=new_sl; p['trailing_activated']=True; p['trailing_locked_r']=lr
        if reason is None and risk_distance:
            current_r=(close-entry_p)/risk_distance if side_long(p['side']) else (entry_p-close)/risk_distance
            should_exit,wreasons=_weakness_exit_check(chat_id,s,p,current_r)
            if should_exit:
                exit_price=close; reason='مدیریت هوشمند (ضعف روند)'
                p['weakness_exit_reasons']=wreasons
        if reason: close_position(chat_id,p,exit_price,reason)
    save_session(chat_id)


def _breakout_filter_diagnostics(df, filters=None, strategy_config=None):
    out = {
        'adx_ok': False, 'volume_breakout_ok': False, 'body_ok': False,
        'trend_buy_ok': False, 'trend_sell_ok': False,
        'breakout_buy_ok': False, 'breakout_sell_ok': False,
        'candle_volume_ok': False, 'candle_buy_ok': False, 'candle_sell_ok': False,
        'final_buy_ok': False, 'final_sell_ok': False,
    }
    try:
        if df is None or df.empty or len(df) < 60:
            return out
        curr, prev = df.iloc[-2], df.iloc[-3]
        cfg = strategy_config if isinstance(strategy_config, dict) else STRATEGY_DEFAULTS
        f = filters if isinstance(filters, dict) else FILTER_DEFAULTS
        adx = float(curr.get('adx', 0) or 0)
        vr = float(curr.get('volume_ratio', 0) or 0)
        body_ratio = float(curr.get('body_ratio', 0) or 0)
        channel_high = curr.get('channel_high')
        channel_low = curr.get('channel_low')
        if pd.isna(channel_high) or pd.isna(channel_low):
            return out
        min_adx = float(cfg.get('min_adx', 20.0))
        min_vr = float(cfg.get('min_volume_ratio', 1.05))
        min_body = float(cfg.get('min_body_ratio', 0.45))
        out['adx_ok'] = adx >= max(15.0, min_adx - 5.0)
        out['volume_breakout_ok'] = (not f.get('volume_filter', True)) or vr >= min_vr
        out['body_ok'] = body_ratio >= min_body
        out['trend_buy_ok'] = bool(curr['close'] > curr['ema20'] > curr['ema50'] and curr['plus_di'] > curr['minus_di'])
        out['trend_sell_ok'] = bool(curr['close'] < curr['ema20'] < curr['ema50'] and curr['minus_di'] > curr['plus_di'])
        out['breakout_buy_ok'] = bool(curr['close'] > channel_high and prev['close'] <= prev.get('channel_high', float('inf')) and out['trend_buy_ok'] and adx >= min_adx)
        out['breakout_sell_ok'] = bool(curr['close'] < channel_low and prev['close'] >= prev.get('channel_low', -float('inf')) and out['trend_sell_ok'] and adx >= min_adx)

        if not f.get('volume_filter', True):
            out['candle_volume_ok'] = True
        else:
            out['candle_volume_ok'] = vr >= 1.0

        if not f.get('candlestick_filter', True):
            out['candle_buy_ok'] = True
            out['candle_sell_ok'] = True
        else:
            body = abs(float(curr['close']) - float(curr['open']))
            rng = max(float(curr['high']) - float(curr['low']), 1e-12)
            upper = float(curr['high']) - max(float(curr['close']), float(curr['open']))
            lower = min(float(curr['close']), float(curr['open'])) - float(curr['low'])
            bullish_pin = lower >= 2 * max(body, 1e-12) and upper <= max(body * 1.2, 1e-12) and curr['close'] > curr['open']
            bearish_pin = upper >= 2 * max(body, 1e-12) and lower <= max(body * 1.2, 1e-12) and curr['close'] < curr['open']
            prev_body = abs(float(prev['close']) - float(prev['open']))
            bull_engulf = prev['close'] < prev['open'] and curr['close'] > curr['open'] and curr['close'] >= prev['open'] and curr['open'] <= prev['close'] and body > prev_body
            bear_engulf = prev['close'] > prev['open'] and curr['close'] < curr['open'] and curr['close'] <= prev['open'] and curr['open'] >= prev['close'] and body > prev_body
            strong_bull = curr['close'] > curr['open'] and body / rng >= 0.60
            strong_bear = curr['close'] < curr['open'] and body / rng >= 0.60
            out['candle_buy_ok'] = bool(bullish_pin or strong_bull)
            out['candle_sell_ok'] = bool(bearish_pin or strong_bear)
        out['final_buy_ok'] = bool(out['adx_ok'] and out['volume_breakout_ok'] and out['body_ok'] and out['breakout_buy_ok'] and out['candle_volume_ok'] and (out['candle_buy_ok'] or not f.get('candlestick_filter', True)))
        out['final_sell_ok'] = bool(out['adx_ok'] and out['volume_breakout_ok'] and out['body_ok'] and out['breakout_sell_ok'] and out['candle_volume_ok'] and (out['candle_sell_ok'] or not f.get('candlestick_filter', True)))
    except Exception:
        pass
    return out


def _entry_diag_result(chat_id, symbol, status, reason='', stage='', signal=None, diagnostics=None):
    return {
        'chat_id': chat_id,
        'symbol': symbol,
        'status': status,
        'reason': str(reason or '').strip(),
        'stage': stage,
        'signal': signal,
        'diagnostics': diagnostics or {},
        'ts': time.time(),
    }


def _entry_diag_label(reason):
    r = str(reason or '').strip()
    if not r:
        return 'دلیل مشخصی ثبت نشد'
    replacements = {
        'روند ضعیف است': 'روند بازار ضعیف است',
        'شرایط روندی برقرار نیست': 'شرایط ورود روندی کامل نیست',
        'شکست جدیدی ثبت نشد': 'شکست معتبر ثبت نشده است',
        'حجم شکست کافی نیست': 'حجم برای تأیید شکست کافی نیست',
        'قدرت بدنه کافی نیست': 'قدرت کندل برای ورود کافی نیست',
        'RSI خنثی است': 'RSI در محدوده خنثی است',
        'قیمت از محدوده میانگین دور است': 'قیمت برای بازگشت به میانگین مناسب نیست',
        'کندل تأیید معتبر نبود': 'کندل تأیید لازم دیده نشد',
        'امتیاز کیفیت پایین است': 'امتیاز کیفیت معامله به حد لازم نرسید',
        'R:R کافی نیست': 'نسبت سود به ضرر مناسب نیست',
        'داده کافی نیست': 'داده کافی برای تصمیم‌گیری وجود ندارد',
        'داده کافی برای طراحی معامله وجود ندارد': 'داده کافی برای ساخت معامله وجود ندارد',
    }
    for old, new in replacements.items():
        if old in r:
            tail = r.split(old, 1)[1].strip()
            return (new + (' ' + tail if tail else '')).strip()[:180]
    return r[:180]


def _entry_diag_report(chat_id, results, elapsed):
    s = get_session(chat_id)
    scanned = len(results)
    opened = sum(1 for x in results if x.get('status') == 'entry_opened')
    signals = sum(1 for x in results if x.get('signal'))
    data_issues = sum(1 for x in results if x.get('status') in ('data_error','insufficient_data'))
    blocked = sum(1 for x in results if x.get('status') in ('blocked','risk_blocked','trade_plan_blocked','execute_blocked'))

    counts = {}
    for x in results:
        if x.get('status') == 'entry_opened':
            continue
        label = _entry_diag_label(x.get('reason'))
        if label and label != 'دلیل مشخصی ثبت نشد':
            counts[label] = counts.get(label, 0) + 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]

    tf = TF_DISPLAY.get(s.get('timeframe'), s.get('timeframe'))
    lines = [
        '🔎 *گزارش تشخیصی ورود*',
        '━━━━━━━━━━━━━━━━━━━━',
        f'⏱ بازه بدون ورود: `{max(1, int(elapsed/60))} دقیقه`',
        f'📊 تایم‌فریم: `{tf}` | استراتژی: `{s.get("active_strategy")}`',
        f'🔍 نمادهای بررسی‌شده: `{scanned}`',
        f'🎯 سیگنال معتبر: `{signals}`',
        f'📥 پوزیشن بازشده: `{opened}`',
    ]
    if data_issues:
        lines.append(f'⚠️ مشکل داده: `{data_issues}`')
    if blocked:
        lines.append(f'🛑 موارد متوقف‌شده قبل از ورود: `{blocked}`')

    if top:
        lines.append('\n*دلایل اصلی عدم ورود:*')
        for label, n in top:
            lines.append(f'• `{n}×` {label}')

    return '\n'.join(lines)


def _entry_diag_batch_update(chat_id, results):
    now = time.time()
    state = ENTRY_DIAG_STATE.setdefault(chat_id, {
        'no_entry_since': None,
        'last_report_at': 0.0,
        'last_entry_at': 0.0,
        'window_results': [],
    })
    opened = any(x.get('status') == 'entry_opened' for x in results)
    if opened:
        state['last_entry_at'] = now
        state['no_entry_since'] = None
        state['last_report_at'] = 0.0
        state['window_results'] = []
        return
    if not results:
        return
    state.setdefault('window_results', []).extend(results)
    state['window_results'] = state['window_results'][-240:]
    if state['no_entry_since'] is None:
        state['no_entry_since'] = now
    elapsed = now - float(state['no_entry_since'])
    last_report = float(state.get('last_report_at', 0.0) or 0.0)
    if not get_session(chat_id).get('entry_diag_enabled', True):
        return
    if elapsed >= NO_ENTRY_REPORT_SECONDS and (not last_report or now-last_report >= NO_ENTRY_REPORT_SECONDS):
        try:
            report_results = list(state.get('window_results') or results)
            send_message(chat_id, _entry_diag_report(chat_id, report_results, elapsed), parse_mode='Markdown')
            state['last_report_at'] = now
            state['window_results'] = []
        except Exception as exc:
            logger.warning('ENTRY_DIAG telegram report failed chat=%s error=%s', chat_id, exc)


async def scan_symbol(http,chat_id,symbol,regime=None):
    s=get_session(chat_id)
    if not s['is_bot_active'] or s['daily_stopped']:
        return _entry_diag_result(chat_id, symbol, 'blocked', 'ربات متوقف است یا محدودیت روزانه فعال است', 'precheck')
    scan_generation=int(s.get('scan_generation',0))
    if time.time() < float(s['cooldowns'].get(symbol,0)):
        return _entry_diag_result(chat_id, symbol, 'blocked', 'نماد در دوره انتظار پس از معامله قبلی است', 'cooldown')
    tf=s['timeframe']; strat=s['active_strategy']; md={}
    if tf=='multi' or strat=='multi':
        for k,v in [('1d','1day'),('4h','4hour'),('1h','1hour'),('15m','15min'),('5m','5min')]:
            try:
                d=await get_klines_async(http,symbol,v,140)
                if not d.empty: md[k]=calculate_indicators(d)
            except Exception as exc:
                logger.warning('ENTRY_DIAG chat=%s symbol=%s timeframe=%s data_error=%s', chat_id, symbol, v, exc)
        primary=md.get('5m')
        if primary is None or len(primary)<60:
            return _entry_diag_result(chat_id, symbol, 'insufficient_data', 'داده کافی نیست', 'data')
        primary_tf='5min'; mode='multi'
    else:
        try:
            klimit = 650 if tf in ('5min', '15min') else 160
            d=await get_klines_async(http,symbol,tf,klimit)
        except Exception as exc:
            return _entry_diag_result(chat_id, symbol, 'data_error', f'خطا در دریافت داده: {exc}', 'data')
        if d.empty:
            return _entry_diag_result(chat_id, symbol, 'data_error', 'داده بازار خالی دریافت شد', 'data')
        primary=calculate_indicators(d); primary_tf=tf; mode='single'
    s=get_session(chat_id)
    if not s['is_bot_active'] or s['daily_stopped'] or int(s.get('scan_generation',0)) != scan_generation:
        return _entry_diag_result(chat_id, symbol, 'blocked', 'وضعیت ربات هنگام اسکن تغییر کرد', 'state')
    if not risk_guard(chat_id):
        return _entry_diag_result(chat_id, symbol, 'risk_blocked', 'محدودیت ریسک اجازه ورود نمی‌دهد', 'risk')
    s=get_session(chat_id)
    if not s['is_bot_active'] or int(s.get('scan_generation',0)) != scan_generation:
        return _entry_diag_result(chat_id, symbol, 'blocked', 'وضعیت ربات پس از بررسی ریسک تغییر کرد', 'state')

    is_scalp_strategy = (strat == 'dynamic' and primary_tf in ('5min', '15min') and mode != 'multi')
    sig, reason = get_signal_with_reason(primary, md, mode, primary_tf, strat, s['filters'], s['strategy_config'], regime if strat == 'dynamic' else None)
    diagnostics = _breakout_filter_diagnostics(primary, s['filters'], s['strategy_config']) if (strat == 'dynamic' and not is_scalp_strategy) else {}
    if not sig:
        return _entry_diag_result(chat_id, symbol, 'no_signal', reason or 'شرایط ورود کامل نیست', 'signal', diagnostics=diagnostics)
    plan, plan_reason = build_trade_plan(primary, sig, s['strategy_config'], 'liquidity_sweep' if is_scalp_strategy else strat, strategy_timeframe=primary_tf)
    if not plan:
        return _entry_diag_result(chat_id, symbol, 'trade_plan_blocked', plan_reason or 'طرح معامله معتبر نشد', 'trade_plan', sig)
    entry=float(plan['entry']); sl=float(plan['sl']); tp=float(plan['tp'])
    full_reason=f"{reason} | {plan_reason}"[:500]
    guard_ok, guard_reason = await leader_correlation_guard(http, chat_id, symbol, primary, primary_tf, side=sig)
    if not guard_ok:
        return _entry_diag_result(chat_id, symbol, 'leader_guard_blocked', guard_reason, 'leader_guard', sig)
    ok=execute_trade(chat_id,symbol,'BUY (Long)' if sig=='BUY' else 'SELL (Short)',entry,sl,tp,full_reason,structural_tp=bool(plan.get('structural_target', False)))
    if ok:
        return _entry_diag_result(chat_id, symbol, 'entry_opened', full_reason, 'entry', sig)
    return _entry_diag_result(chat_id, symbol, 'execute_blocked', 'سیگنال ایجاد شد اما اجرای ورود موفق نشد', 'execute', sig)


def performance_period_report(chat_id, period='all'):
    s=get_session(chat_id)
    closed=list(s.get('closed_positions') or [])
    now=time.time()
    seconds={'day':86400,'week':7*86400,'month':30*86400}.get(period)
    if seconds: closed=[p for p in closed if now-float(p.get('close_timestamp',p.get('opened_at',0)) or 0)<=seconds]
    label={'day':'امروز','week':'۷ روز اخیر','month':'۳۰ روز اخیر','all':'کل سابقه'}.get(period,'کل سابقه')
    n=len(closed); pnls=[float(p.get('pnl_usdt',0) or 0) for p in closed]
    wins=[x for x in pnls if x>0]; losses=[x for x in pnls if x<0]
    net=sum(pnls); gp=sum(wins); gl=abs(sum(losses)); pf=gp/gl if gl else (float('inf') if gp else 0)
    rvals=[]
    for p in closed:
        try:
            risk=float(p.get('risk_usdt') or 0); pnl=float(p.get('pnl_usdt') or 0)
            if risk>0: rvals.append(pnl/risk)
        except Exception: pass
    lines=['📊 *گزارش عملکرد '+label+'*','━━━━━━━━━━━━━━━━━━━━',f'معاملات بسته‌شده: `{n}`',f'موفق: `{len(wins)}` | ناموفق: `{len(losses)}`',f'نرخ موفقیت: `{(len(wins)/n*100 if n else 0):.1f}%`',f'سود/زیان خالص: `{net:+.2f} USDT`',f'Profit Factor: `{("∞" if pf==float("inf") else f"{pf:.2f}")}`']
    if rvals:
        lines.append(f'📐 R واقعی میانگین: `{sum(rvals)/len(rvals):+.2f}R`')
    return '\n'.join(lines)


def trade_audit_report(chat_id):
    s=get_session(chat_id); positions=list(s.get('paper_positions') or []); closed=list(s.get('closed_positions') or [])
    allp=closed+positions
    if not allp: return '🔎 *ممیزی معامله*\n\nهنوز معامله‌ای برای بررسی ثبت نشده است.'
    p=max(allp,key=lambda x: float(x.get('opened_at',0) or 0)); tid=p.get('trade_id','—')
    lines=['🔎 *ممیزی صفر تا صد آخرین پوزیشن*','━━━━━━━━━━━━━━━━━━━━',f'🆔 شناسه: `{tid}`',f'🪙 نماد: `{p.get("symbol")}` | {"LONG" if side_long(p.get("side")) else "SHORT"}',f'⏱ تایم‌فریم: `{TF_DISPLAY.get(p.get("timeframe"),p.get("timeframe"))}`',f'🎯 Entry: `{fmt(p.get("entry_price",0))}` | SL: `{fmt(p.get("sl",0))}` | TP: `{fmt(p.get("tp",0))}`',f'📦 وضعیت: `{"بسته‌شده" if p in closed else "باز"}`']
    if p in closed:
        lines += [f'🚪 خروج: `{fmt(p.get("close_price",0))}`',f'💰 PnL: `{float(p.get("pnl_usdt",0) or 0):+.2f} USDT`',f'📝 علت خروج: `{p.get("close_reason","—")}`']
    return '\n'.join(lines)


def export_trade_data(chat_id):
    if not is_allowed(chat_id) or not TELEGRAM_TOKEN: return False
    s=get_session(chat_id)
    payload={'generated_at':time.time(),'chat_id':chat_id,'open_positions':[audit_trade_record(p) for p in s.get('paper_positions',[])],'closed_positions':[audit_trade_record(p) for p in s.get('closed_positions',[])],'trade_audit':s.get('trade_audit',[])}
    raw=json.dumps(payload,ensure_ascii=False,indent=2,default=str).encode('utf-8')
    try:
        requests.post(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument',data={'chat_id':chat_id,'caption':'📦 خروجی کامل داده‌های معاملات'},files={'document':('trade_audit.json',io.BytesIO(raw),'application/json')},timeout=30)
        return True
    except Exception as exc: logger.warning('export trade data failed: %s',exc); return False


def reset_stats(chat_id):
    s=get_session(chat_id)
    if s.get('paper_positions'):
        return False, '❌ تا وقتی پوزیشن باز دارید، ریست آمار مجاز نیست. ابتدا پوزیشن‌ها را ببندید.'
    s['closed_positions'] = []
    s['trade_audit'] = []
    s['scan_stats'] = {'scans':0,'symbols':0,'signals':0,'entries':0,'blocked':0,'data_errors':0,'reason_counts':{}}
    s['daily_stopped'] = False
    equity = exchange_balance(chat_id) if s.get('trading_mode') == 'REAL' else float(s.get('paper_balance', 1000.0))
    s['daily_start_equity'] = float(equity)
    s['daily_start_date'] = time.strftime('%Y-%m-%d', time.gmtime())
    save_session(chat_id)
    return True, f"✅ *آمار تست ریست شد*\n\nمبنای ریسک جدید: `{equity:.2f} USDT`"


def analyze(chat_id,symbol):
    s=get_session(chat_id)
    tf=s['timeframe'] if s['timeframe']!='multi' else '5min'
    d=get_klines(symbol,tf,160)
    if d.empty:
        return f'❌ داده کافی برای تحلیل `{symbol}` پیدا نشد.'
    d=calculate_indicators(d); c=d.iloc[-2]
    a,r1=strategy_trend_following(d,tf,s['filters'],s['strategy_config'])
    b,r2=strategy_breakout(d,s['filters'],s['strategy_config'])
    m,r3=strategy_mean_reversion(d,s['filters'],s['strategy_config'])

    adx=float(c.adx or 0); rsi=float(c.rsi or 50)
    return (
        f"🔍 *تحلیل {symbol}*\n\n"
        f"قدرت روند (ADX): `{adx:.1f}`\n"
        f"مومنتوم (RSI): `{rsi:.1f}`\n"
        f"روندی: {'فعال' if a else 'غیرفعال'}\n"
        f"شکست: {'فعال' if b else 'غیرفعال'}\n"
        f"بازگشت به میانگین: {'فعال' if m else 'غیرفعال'}"
    )


def menu(chat_id,message_id=None):
    s=get_session(chat_id)
    bal=exchange_balance(chat_id) if s['trading_mode']=='REAL' else s['paper_balance']
    maxp=s['max_open_positions'] if s['max_open_positions']>0 else '∞'
    diag = "🟢 فعال" if s.get('entry_diag_enabled', True) else "🔴 خاموش"
    text=f"📊 *پنل اصلی ربات*\n\n🟢 اسکن: `{'فعال' if s['is_bot_active'] else 'متوقف'}`\n💳 حساب: `{'واقعی' if s['trading_mode']=='REAL' else 'کاغذی'}`  |  ⏱ تایم‌فریم: `{TF_DISPLAY.get(s['timeframe'],s['timeframe'])}`\n📈 استراتژی: `{'پویا (دوطرفه)' if s['active_strategy']=='dynamic' else s['active_strategy']}`\n💰 موجودی: `{bal:.2f} USDT`  |  ⚙️ مارجین: `{s['trade_amount_usdt']:.0f} USDT`\n📌 پوزیشن‌های باز: `{maxp}`  |  🔍 لاگ ورود: `{diag}`\n🛡 ریسک هر معامله: `{s['risk_per_trade_pct']:.2f}%`  |  حد ضرر روزانه: `{s['daily_loss_limit_pct']:.2f}%`\n\nاز منوی زیر بخش موردنظر را انتخاب کن:"
    send_message(chat_id,text,get_main_menu_keyboard(s['is_bot_active'], s.get('entry_diag_enabled', True)),message_id)


def stop_scan(chat_id, reason='manual'):
    s=get_session(chat_id)
    with STATE_LOCK:
        s['scan_generation']=int(s.get('scan_generation',0))+1
        s['is_bot_active']=False
        s['last_stop_reason']=reason
    save_session(chat_id)
    with get_entry_lock(chat_id):
        pass
    return s


def start_scan(chat_id,message_id=None):
    s=get_session(chat_id)
    if s['daily_stopped']:
        equity=exchange_balance(chat_id) if s['trading_mode']=='REAL' else current_paper_equity(s)
        s['daily_stopped']=False
        s['daily_start_equity']=equity
    if s['trading_mode']=='REAL':
        if not get_exchange(chat_id):
            send_message(chat_id,'❌ حساب CoinEx برای این کاربر تنظیم نشده است.')
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
    sync_bottom_keyboard(chat_id, "🟢 اسکن فعال شد.\n🔒 تنظیمات حساس تا توقف اسکن قفل هستند.")


def reload_and_restart_scan(chat_id, message_id=None):
    try:
        importlib.reload(strategy)
        s = get_session(chat_id)
        s['strategy_config'] = get_timeframe_preset(s.get('timeframe', '5min'))
        save_session(chat_id)
        start_scan(chat_id, message_id)
        send_message(chat_id, "🔄 *استراتژی مجدداً بارگذاری شد و اسکن با تنظیمات به‌روز فعال گردید.*")
    except Exception as exc:
        send_message(chat_id, f"❌ خطا در بارگذاری مجدد استراتژی: `{exc}`")


def _market_snapshot(symbol, tf):
    try:
        d = get_klines(symbol, tf, 160)
        if d.empty or len(d) < 60: return None
        d = calculate_indicators(d); c = d.iloc[-2]
        close = float(c.close); ema20 = float(c.ema20); ema50 = float(c.ema50); adx = float(c.adx); rsi = float(c.rsi); atr = float(c.atr)
        vol_ratio = float(c.volume / d['volume'].rolling(20).mean().iloc[-2]) if float(d['volume'].rolling(20).mean().iloc[-2]) > 0 else 0.0
        score = 1 if close > ema50 and ema20 >= ema50 else (-1 if close < ema50 and ema20 <= ema50 else 0)
        return {'symbol': symbol, 'close': close, 'adx': adx, 'rsi': rsi, 'atr_pct': atr / close * 100 if close else 0.0, 'volume_ratio': vol_ratio, 'score': score}
    except Exception:
        return None


def market_report(chat_id):
    s = get_session(chat_id)
    tf = '5min' if s['timeframe'] == 'multi' else s['timeframe']
    symbols = ['BTC','ETH','SOL','BNB','XRP','DOGE','ADA','AVAX','LINK','DOT']
    results = []
    with ThreadPoolExecutor(max_workers=min(6, len(symbols))) as ex:
        futures = [ex.submit(_market_snapshot, sym, tf) for sym in symbols]
        for f in as_completed(futures):
            item = f.result()
            if item: results.append(item)
    if not results:
        return '❌ داده کافی برای ساخت داشبورد بازار دریافت نشد.'
    bullish = sum(1 for x in results if x['score'] > 0)
    bearish = sum(1 for x in results if x['score'] < 0)
    avg_adx = sum(x['adx'] for x in results) / len(results)
    avg_rsi = sum(x['rsi'] for x in results) / len(results)
    return (
        '🌐 *داشبورد بازار*\n'
        f"⏱ تایم‌فریم: `{TF_DISPLAY.get(tf, tf)}`\n"
        f"📈 وضعیت: `{bullish}` صعودی | `{bearish}` نزولی\n"
        f"💪 میانگین ADX: `{avg_adx:.1f}` | میانگین RSI: `{avg_rsi:.1f}`"
    )


def runtime_audit(chat_id):
    s=get_session(chat_id)
    return (
        '🧪 *ممیزی وضعیت ربات*\n\n'
        f'🤖 اسکن: `{"فعال" if s.get("is_bot_active") else "متوقف"}`\n'
        f'💼 حساب: `{"REAL" if s.get("trading_mode")=="REAL" else "PAPER"}`\n'
        f'📦 پوزیشن‌های باز: `{len(s.get("paper_positions",[]))}`\n'
        '✅ بدون مغایرت ساختاری'
    )


def learning_text(topic):
    texts={
        'adx':"📈 *ADX چیست؟*\n\nADX برای سنجش *قدرت روند* است، نه جهت آن.",
        'atr':"🌪 *ATR چیست؟*\n\nATR میزان *نوسان معمول قیمت* را اندازه می‌گیرد.",
        'rsi':"📊 *RSI چیست؟*\n\nRSI وضعیت اشباع خرید یا فروش را مشخص می‌کند.",
        'rr':"⚖️ *R:R چیست؟*\n\nنسبت پاداش به ریسک احتمالی معامله.",
        'why':"🧠 *چرا این شاخص‌ها؟*\n\nبرای ارزیابی چندبعدی بازار پیش از ورود."
    }
    return texts.get(topic,texts['why'])


def apply_user_profile(s, profile):
    presets={'conservative':(78.0,1.60,0.35,24.0,'محافظه‌کارانه'),'balanced':(65.0,1.30,0.50,20.0,'متعادل'),'opportunity':(60.0,1.25,0.50,18.0,'فرصت‌های بیشتر')}
    score,rr,risk,adx,label=presets[profile]
    s['strategy_config']['min_trade_score']=score; s['strategy_config']['min_rr']=rr; s['strategy_config']['min_adx']=adx; s['risk_per_trade_pct']=risk; s['user_experience']='simple'
    return label,score,rr,risk


def process_command(cmd,chat_id,message_id=None):
    if cmd in ('performance','report','📈 گزارش عملکرد کلی'):
        send_message(chat_id, performance_period_report(chat_id, 'all'), get_performance_keyboard()); return
    if cmd in ('/audit','audit','🧪 ممیزی ربات'):
        send_message(chat_id, runtime_audit(chat_id), get_bottom_menu_keyboard(get_session(chat_id)['is_bot_active'])); return
    s=get_session(chat_id); c=(cmd or '').strip(); cl=c.lower()

    if cl in ('/learn_menu','learn','🎓 آموزش مفاهیم'):
        edit_page(chat_id,'🎓 *آموزش ساده مفاهیم ربات*',get_learn_menu_keyboard(),message_id); return
    if cl in ('/learn_adx','/learn_atr','/learn_rsi','/learn_rr','/learn_why'):
        edit_page(chat_id,learning_text(cl.replace('/learn_','')),get_learn_menu_keyboard(),message_id); return
    if cl=='/profile_advanced':
        s['user_experience']='advanced'; save_session(chat_id); edit_page(chat_id,'🔵 *حالت حرفه‌ای فعال شد.*',get_params_menu_keyboard(s),message_id); return
    if cl=='/profile_simple':
        s['user_experience']='simple'; save_session(chat_id); edit_page(chat_id,'🟢 *حالت ساده فعال شد.*',get_params_menu_keyboard(s),message_id); return
    if cl in ('/profile_conservative','/profile_balanced','/profile_opportunity'):
        profile={'/profile_conservative':'conservative','/profile_balanced':'balanced','/profile_opportunity':'opportunity'}[cl]
        label,score,rr,risk=apply_user_profile(s,profile); save_session(chat_id)
        edit_page(chat_id,f'🟢 *پروفایل {label} فعال شد.*',get_params_menu_keyboard(s),message_id); return

    if cl.startswith('/view_chart_'):
        sym = cl.replace('/view_chart_', '').upper()
        pos = next((p for p in s.get('paper_positions', []) if p['symbol'] == sym), None)
        if not pos:
            send_message(chat_id, f'❌ پوزیشن باز برای `{sym}` یافت نشد.')
            return
        tf = pos.get('timeframe', '5min')
        df = get_klines(sym, tf, 200)
        if df.empty:
            send_message(chat_id, f'❌ دریافت داده کندل برای `{sym}` ناموفق بود.')
            return
        chart(chat_id, sym, calculate_indicators(df), pos)
        return

    if cl.startswith('/edit_sl_'):
        sym = cl.replace('/edit_sl_', '').upper()
        pos = next((p for p in s.get('paper_positions', []) if p['symbol'] == sym), None)
        if not pos:
            send_message(chat_id, f'❌ پوزیشن `{sym}` یافت نشد.')
            return
        s['user_state'] = f'WAIT_EDIT_SL_{sym}'
        save_session(chat_id)
        send_message(chat_id, f"🛑 *تغییر حد ضرر (SL)* برای `{sym}`\n\nورود: `{fmt(pos['entry_price'])}`\nحد ضرر فعلی: `{fmt(pos['sl'])}`\n\nلطفاً مقدار عددی جدید SL را ارسال کنید:")
        return

    if cl.startswith('/edit_tp_'):
        sym = cl.replace('/edit_tp_', '').upper()
        pos = next((p for p in s.get('paper_positions', []) if p['symbol'] == sym), None)
        if not pos:
            send_message(chat_id, f'❌ پوزیشن `{sym}` یافت نشد.')
            return
        s['user_state'] = f'WAIT_EDIT_TP_{sym}'
        save_session(chat_id)
        send_message(chat_id, f"🎯 *تغییر حد سود (TP)* برای `{sym}`\n\nورود: `{fmt(pos['entry_price'])}`\nحد سود فعلی: `{fmt(pos['tp'])}`\n\nلطفاً مقدار عددی جدید TP را ارسال کنید:")
        return

    if cl=='/start':
        if s.get('is_bot_active'): stop_scan(chat_id, 'start-reset')
        s['user_state']=None; save_session(chat_id)
        send_message(chat_id,'🤖 *ربات معامله‌گر*\n\nحالت حساب را انتخاب کنید.',get_start_keyboard())
        sync_bottom_keyboard(chat_id, "🔴 اسکن متوقف است.\n⚙️ تنظیمات آماده تغییر هستند.")
        return
    if cl in ('/menu','☰ منو','🏠 منوی اصلی'): s['user_state']=None; menu(chat_id,message_id); return
    if cl=='/cancel': s['user_state']=None; save_session(chat_id); menu(chat_id, message_id); return
    if cl in ('/stop_scan',) or c in ('🔴 توقف اسکن','توقف اسکن'):
        stop_scan(chat_id, 'manual'); menu(chat_id,message_id)
        sync_bottom_keyboard(chat_id, "🔴 اسکن متوقف شد.\n⚙️ تنظیمات آماده تغییر هستند."); return
    if cl in ('/start_scan',) or c in ('🟢 شروع اسکن','شروع اسکن'): start_scan(chat_id,message_id); return
    if cl == '/reload_and_start': reload_and_restart_scan(chat_id, message_id); return
    if cl=='/mode_paper':
        if s['paper_positions']: send_message(chat_id,'❌ تا وقتی پوزیشن باز دارید نمی‌توانید به PAPER بروید.'); return
        s['trading_mode']='PAPER'; s['is_bot_active']=False; save_session(chat_id); edit_page(chat_id,'⚙️ موجودی PAPER را انتخاب کنید.',get_balance_keyboard(),message_id); return
    if cl=='/mode_real':
        if s['paper_positions']: send_message(chat_id,'❌ ابتدا تمام پوزیشن‌های فعلی را ببندید.'); return
        if not get_exchange(chat_id): send_message(chat_id,'❌ حساب CoinEx این کاربر در `COINEX_ACCOUNTS_JSON` تنظیم نشده است.'); return
        bal=exchange_balance(chat_id)
        s['trading_mode']='REAL'; s['is_bot_active']=False; s['daily_start_equity']=bal; s['daily_start_date']=time.strftime('%Y-%m-%d',time.gmtime()); s['daily_stopped']=False; save_session(chat_id); edit_page(chat_id,f'🔴 موجودی REAL: `{bal:.2f} USDT`\n\n⚙️ مارجین هر معامله:',get_margin_keyboard(),message_id); return
    if cl.startswith('/set_bal_'):
        v=float(cl.replace('/set_bal_','')); s['paper_balance']=v; s['daily_start_equity']=v; s['daily_start_date']=time.strftime('%Y-%m-%d',time.gmtime()); s['daily_stopped']=False; save_session(chat_id); edit_page(chat_id,'✅ موجودی ثبت شد.\n\n⚙️ مارجین:',get_margin_keyboard(),message_id); return
    if cl.startswith('/set_margin_'): s['trade_amount_usdt']=float(cl.replace('/set_margin_','')); save_session(chat_id); edit_page(chat_id,'⚙️ اهرم:',get_leverage_keyboard(),message_id); return
    if cl.startswith('/set_lev_'): s['leverage']=int(cl.replace('/set_lev_','')); save_session(chat_id); edit_page(chat_id,'⚙️ حداکثر پوزیشن:',get_max_positions_keyboard(),message_id); return
    if cl.startswith('/set_max_'):
        s['max_open_positions']=int(cl.replace('/set_max_','')); save_session(chat_id)
        edit_page(chat_id, "⏱ تایم‌فریم و استراتژی موردنظر را انتخاب کنید:", get_timeframe_keyboard(), message_id); return
    if cl.startswith('/set_tf_'):
        tf_map={'/set_tf_5m':'5min','/set_tf_15m':'15min','/set_tf_1h':'1hour','/set_tf_4h':'4hour','/set_tf_multi':'multi'}
        if cl in tf_map:
            s['timeframe']=tf_map[cl]; s['strategy_config']=get_timeframe_preset(s['timeframe']); save_session(chat_id); menu(chat_id, message_id); return
    if cl=='/market_report':
        send_message(chat_id, market_report(chat_id)); return
    if cl=='/check_wizard': edit_page(chat_id,'⚙️ *تنظیمات معامله*',get_margin_keyboard(),message_id); return
    if cl=='/entry_diag':
        enabled = s.get('entry_diag_enabled', True)
        edit_page(chat_id, f"🔍 وضعیت لاگ تشخیصی: {'🟢 فعال' if enabled else '🔴 خاموش'}", get_entry_diag_keyboard(enabled), message_id); return
    if cl == '/toggle_entry_diag':
        s['entry_diag_enabled'] = not s.get('entry_diag_enabled', True)
        save_session(chat_id)
        edit_page(chat_id, f"🔍 لاگ تشخیصی: {'🟢 فعال شد' if s['entry_diag_enabled'] else '🔴 خاموش شد'}", get_entry_diag_keyboard(s['entry_diag_enabled']), message_id); return
    if cl in ('/manual_trade','🖐 معامله دستی'):
        s['user_state']='WAIT_MANUAL_SYMBOL'; s.pop('_manual_tmp',None); save_session(chat_id)
        send_message(chat_id,'🖐 *معامله دستی*\n\nنماد را ارسال کنید، مثال `BTC`'); return
    if cl in ('/manual_side_buy','/manual_side_sell'):
        tmp=s.get('_manual_tmp') or {}
        if not tmp.get('symbol'):
            send_message(chat_id,'⚠️ ابتدا نماد را ارسال کنید.'); s['user_state']='WAIT_MANUAL_SYMBOL'; save_session(chat_id); return
        tmp['side']='BUY' if cl=='/manual_side_buy' else 'SELL'
        s['_manual_tmp']=tmp; s['user_state']='WAIT_MANUAL_ENTRY'; save_session(chat_id)
        live=latest_price(tmp['symbol'])
        send_message(chat_id,f"🖐 *معامله دستی* — `{tmp['symbol']}`\nقیمت ورود را ارسال کنید یا کلمه `بازار` را بفرستید (قیمت لحظه‌ای: `{fmt(live)}`):"); return
    if cl=='/open_positions' or 'پوزیشن‌های باز' in c:
        if not s['paper_positions']: send_message(chat_id,'پوزیشن بازی وجود ندارد.'); return
        lines=[f'🔄 *پوزیشن‌ها ({len(s["paper_positions"])})*']
        for p in s['paper_positions']: lines.append(f"{'🟢' if side_long(p['side']) else '🔴'} `{p['symbol']}` | Entry `{fmt(p['entry_price'])}` | SL `{fmt(p['sl'])}` | TP `{fmt(p['tp'])}`")
        send_message(chat_id,'\n'.join(lines),get_positions_keyboard(s['paper_positions'])); return
    if cl.startswith('/manage_'):
        sym=cl.replace('/manage_','').upper()
        for p in s['paper_positions']:
            if p['symbol']==sym:
                send_message(chat_id,format_trade_status(p),trade_action_keyboard(sym, miniapp_chart_url(sym, p.get('timeframe','5min')))); return
        send_message(chat_id,f'❌ پوزیشن `{sym}` پیدا نشد.'); return
    if cl.startswith('/close_prompt_'):
        sym=cl.replace('/close_prompt_','').upper()
        for p in s['paper_positions']:
            if p['symbol']==sym:
                send_message(chat_id,format_trade_status(p)+'\n\n⚠️ آیا از بستن با قیمت بازار اطمینان دارید؟',close_confirm_keyboard(sym)); return
        send_message(chat_id,f'❌ پوزیشن `{sym}` پیدا نشد.'); return
    if cl.startswith('/confirm_close_') and cl not in ('/confirm_close_all','/confirm_close_longs','/confirm_close_shorts'):
        sym=cl.replace('/confirm_close_','').upper()
        for p in s['paper_positions'][:]:
            if p['symbol']==sym:
                close_position(chat_id,p,reason='manual'); return
        send_message(chat_id,f'❌ پوزیشن `{sym}` پیدا نشد.'); return
    if cl=='/close_all_prompt': send_message(chat_id,'⚠️ *تأیید بستن همه پوزیشن‌ها*',get_confirm_close_all_keyboard()); return
    if cl=='/confirm_close_all':
        stop_scan(chat_id, 'close-all')
        for p in s['paper_positions'][:]: close_position(chat_id,p,reason='close_all')
        menu(chat_id); return
    if cl=='/close_longs_prompt':
        n=sum(1 for p in s['paper_positions'] if side_long(p['side']))
        if n==0: send_message(chat_id,'❌ پوزیشن خریدی وجود ندارد.'); return
        send_message(chat_id,f'⚠️ تأیید بستن {n} پوزیشن خرید:',get_confirm_close_longs_keyboard()); return
    if cl=='/confirm_close_longs':
        for p in s['paper_positions'][:]:
            if side_long(p['side']): close_position(chat_id,p,reason='manual_longs')
        return
    if cl=='/close_shorts_prompt':
        n=sum(1 for p in s['paper_positions'] if not side_long(p['side']))
        if n==0: send_message(chat_id,'❌ پوزیشن فروشی وجود ندارد.'); return
        send_message(chat_id,f'⚠️ تأیید بستن {n} پوزیشن فروش:',get_confirm_close_shorts_keyboard()); return
    if cl=='/confirm_close_shorts':
        for p in s['paper_positions'][:]:
            if not side_long(p['side']): close_position(chat_id,p,reason='manual_shorts')
        return
    if cl in ('/performance_today','/performance_week','/performance_month','/performance','/trade_audit','/export_trade_data','/reset_stats_prompt','/reset_stats_confirm'):
        if cl=='/performance_today': send_message(chat_id, performance_period_report(chat_id, 'day'), get_performance_keyboard())
        elif cl=='/performance_week': send_message(chat_id, performance_period_report(chat_id, 'week'), get_performance_keyboard())
        elif cl=='/performance_month': send_message(chat_id, performance_period_report(chat_id, 'month'), get_performance_keyboard())
        elif cl=='/performance': send_message(chat_id, performance_period_report(chat_id, 'all'), get_performance_keyboard())
        elif cl=='/trade_audit': send_message(chat_id, trade_audit_report(chat_id), get_performance_keyboard())
        elif cl=='/export_trade_data': export_trade_data(chat_id)
        elif cl=='/reset_stats_prompt':
            send_message(chat_id,'⚠️ آیا از ریست آمار عملکرد اطمینان دارید؟', {"inline_keyboard": [[{"text":"🔄 بله، ریست کن","callback_data":"/reset_stats_confirm"},{"text":"❌ انصراف","callback_data":"/cancel"}]]})
        elif cl=='/reset_stats_confirm':
            ok,msg=reset_stats(chat_id); send_message(chat_id,msg,get_performance_keyboard() if ok else None)
        return
    if cl in ('/manage_watchlist','/watchlist_list'):
        edit_page(chat_id,f"📋 واچ‌لیست فعال:\nLong ({len(SHARED_LONG_WATCHLIST)} نماد)\nShort ({len(SHARED_SHORT_WATCHLIST)} نماد)",get_watchlist_manage_keyboard(),message_id); return


def handle_text(chat_id,text):
    raw=(text or '').strip()
    fixed_buttons={
        '🏠 منوی اصلی':'/menu', 'منوی اصلی':'/menu',
        '🔄 پوزیشن‌های باز':'/open_positions', 'پوزیشن‌های باز':'/open_positions',
        '📈 گزارش عملکرد کلی':'/performance', 'گزارش عملکرد کلی':'/performance',
        '📊 وضعیت بازار':'/market_report', 'وضعیت بازار':'/market_report',
        '⚙️ تنظیمات معامله':'/check_wizard', 'تنظیمات معامله':'/check_wizard',
        '📋 واچ‌لیست':'/manage_watchlist', 'واچ‌لیست':'/manage_watchlist',
        '❌ بستن همه':'/close_all_prompt', 'بستن همه':'/close_all_prompt',
        '🖐 معامله دستی':'/manual_trade', 'معامله دستی':'/manual_trade',
    }
    if raw in fixed_buttons:
        process_command(fixed_buttons[raw],chat_id); return

    s=get_session(chat_id); val=raw.upper()
    current_state = str(s.get('user_state') or '')

    if current_state.startswith('WAIT_EDIT_SL_'):
        sym = current_state.replace('WAIT_EDIT_SL_', '')
        s['user_state'] = None
        save_session(chat_id)
        try:
            new_sl = float(raw.replace(',', '').strip())
        except ValueError:
            send_message(chat_id, '⚠️ مقدار وارد شده نامعتبر است.')
            return
        pos = next((p for p in s.get('paper_positions', []) if p['symbol'] == sym), None)
        if not pos:
            send_message(chat_id, f'❌ پوزیشن `{sym}` پیدا نشد.')
            return
        is_long = side_long(pos['side'])
        entry = float(pos['entry_price'])
        if (is_long and new_sl >= entry) or (not is_long and new_sl <= entry):
            send_message(chat_id, f"⚠️ حد ضرر باید {'کمتر' if is_long else 'بیشتر'} از قیمت ورود ({fmt(entry)}) باشد.")
            return
        if pos.get('is_real'):
            ok, err = move_stop_loss(chat_id, sym, normalize_price(chat_id, sym, new_sl))
            if not ok:
                send_message(chat_id, f'❌ تغییر حد ضرر در صرافی ناموفق بود: {err}')
                return
        pos['sl'] = new_sl
        save_session(chat_id)
        send_message(chat_id, f"✅ حد ضرر پوزیشن `{sym}` به `{fmt(new_sl)}` تغییر یافت.", trade_action_keyboard(sym))
        return

    if current_state.startswith('WAIT_EDIT_TP_'):
        sym = current_state.replace('WAIT_EDIT_TP_', '')
        s['user_state'] = None
        save_session(chat_id)
        try:
            new_tp = float(raw.replace(',', '').strip())
        except ValueError:
            send_message(chat_id, '⚠️ مقدار وارد شده نامعتبر است.')
            return
        pos = next((p for p in s.get('paper_positions', []) if p['symbol'] == sym), None)
        if not pos:
            send_message(chat_id, f'❌ پوزیشن `{sym}` پیدا نشد.')
            return
        is_long = side_long(pos['side'])
        entry = float(pos['entry_price'])
        if (is_long and new_tp <= entry) or (not is_long and new_tp >= entry):
            send_message(chat_id, f"⚠️ حد سود باید {'بیشتر' if is_long else 'کمتر'} از قیمت ورود ({fmt(entry)}) باشد.")
            return
        if pos.get('is_real'):
            ok, err = set_protection(chat_id, sym, pos['sl'], normalize_price(chat_id, sym, new_tp))
            if not ok:
                send_message(chat_id, f'❌ تغییر حد سود در صرافی ناموفق بود: {err}')
                return
        pos['tp'] = new_tp
        save_session(chat_id)
        send_message(chat_id, f"✅ حد سود پوزیشن `{sym}` به `{fmt(new_tp)}` تغییر یافت.", trade_action_keyboard(sym))
        return

    if current_state == 'WAIT_MANUAL_SYMBOL':
        sym=re.sub(r'[^A-Z0-9]','',val)
        if not (2<=len(sym)<=12) or latest_price(sym) is None:
            send_message(chat_id,'⚠️ نماد نامعتبر است یا قیمت آن در دسترس نیست.'); return
        s['_manual_tmp']={'symbol':sym}; s['user_state']=None; save_session(chat_id)
        send_message(chat_id,f'🖐 جهت معامله `{sym}` را انتخاب کنید:',get_manual_side_keyboard()); return
    if current_state == 'WAIT_MANUAL_ENTRY':
        tmp=s.get('_manual_tmp') or {}
        symbol=tmp.get('symbol')
        live=latest_price(symbol)
        if raw.strip() in ('بازار','بازاری','market','Market'):
            entry=live
        else:
            try: entry=float(raw.replace(',','').strip())
            except Exception: send_message(chat_id,'⚠️ عدد معتبر نیست.'); return
        tmp['entry']=entry; s['_manual_tmp']=tmp; s['user_state']='WAIT_MANUAL_SL'; save_session(chat_id)
        send_message(chat_id,f'✅ قیمت ورود: `{fmt(entry)}`\nقیمت حد ضرر (SL) را ارسال کنید:'); return
    if current_state == 'WAIT_MANUAL_SL':
        tmp=s.get('_manual_tmp') or {}
        try: sl=float(raw.replace(',','').strip())
        except Exception: send_message(chat_id,'⚠️ عدد معتبر نیست.'); return
        tmp['sl']=sl; s['_manual_tmp']=tmp; s['user_state']='WAIT_MANUAL_TP'; save_session(chat_id)
        send_message(chat_id,'قیمت حد سود (TP) را ارسال کنید:'); return
    if current_state == 'WAIT_MANUAL_TP':
        tmp=s.get('_manual_tmp') or {}
        try: tp=float(raw.replace(',','').strip())
        except Exception: send_message(chat_id,'⚠️ عدد معتبر نیست.'); return
        symbol=tmp.get('symbol'); side=tmp.get('side'); sl=tmp.get('sl'); entry=tmp.get('entry')
        s['user_state']=None; s.pop('_manual_tmp',None); save_session(chat_id)
        is_long = side=='BUY'
        if not ((is_long and sl<entry<tp) or ((not is_long) and tp<entry<sl)):
            send_message(chat_id,'⚠️ نسبت SL و TP با جهت معامله همخوانی ندارد.'); return
        ok,err=execute_manual_trade(chat_id,symbol,'BUY (Long)' if is_long else 'SELL (Short)',sl,tp,entry_price=entry)
        if ok: send_message(chat_id,f'✅ معامله دستی `{symbol}` باز شد.')
        else: send_message(chat_id,f'❌ باز نشد: {err}')
        return
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
                need_regime = any(
                    s.get('is_bot_active') and not s.get('daily_stopped') and s.get('active_strategy') == 'dynamic'
                    for s in USER_SESSIONS.values()
                )
                if need_regime:
                    await refresh_market_regime(http)
                for cid,s in list(USER_SESSIONS.items()):
                    if not s['is_bot_active'] or s['daily_stopped']: continue
                    if not risk_guard(cid): continue
                    if s['max_open_positions']>0 and len(s['paper_positions'])>=s['max_open_positions']:
                        _entry_diag_batch_update(cid, [{'status':'blocked','reason':f"ظرفیت پوزیشن‌های باز پر است ({len(s['paper_positions'])}/{s['max_open_positions']})"}])
                        continue
                    watchlist = scan_watchlist_for_timeframe(s.get('timeframe','5min'), None)
                    for sym in watchlist:
                        tasks.append(scan_symbol(http,cid,sym,None))
                if tasks:
                    batch = await asyncio.gather(*tasks, return_exceptions=True)
                    by_chat = {}
                    for item in batch:
                        if isinstance(item, dict) and item.get('chat_id') is not None:
                            by_chat.setdefault(item['chat_id'], []).append(item)
                    for cid, results in by_chat.items():
                        _entry_diag_batch_update(cid, results)
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


def _validate_telegram_webapp_initdata(init_data: str, max_age_seconds: int = 3600):
    if not init_data or not TELEGRAM_TOKEN:
        return None
    try:
        pairs = urlparse.parse_qsl(init_data, keep_blank_values=True)
        data = dict(pairs)
        received_hash = data.pop('hash', None)
        if not received_hash:
            return None
        check_string = '\n'.join(f'{k}={v}' for k, v in sorted(data.items()))
        secret_key = hmac.new(b'WebAppData', TELEGRAM_TOKEN.encode(), hashlib.sha256).digest()
        computed_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed_hash, received_hash):
            return None
        auth_date = int(data.get('auth_date', '0') or '0')
        if auth_date and (time.time() - auth_date) > max_age_seconds:
            return None
        user_raw = data.get('user')
        if not user_raw:
            return None
        return json.loads(user_raw)
    except Exception:
        return None


def _miniapp_find_position(chat_id, symbol):
    s = USER_SESSIONS.get(int(chat_id))
    if not s: return None
    for p in s.get('paper_positions', []):
        if p.get('symbol', '').upper() == symbol.upper(): return p
    return None


_MINIAPP_CHART_HTML = """<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no"/>
<title>چارت پوزیشن</title>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
  html,body{margin:0;padding:0;background:#0e0e12;color:#eaeaea;font-family:-apple-system,Tahoma,sans-serif;height:100%;}
  #info{padding:10px 12px;font-size:13px;line-height:1.9;border-bottom:1px solid #23232b;}
  #chart{width:100%;height:calc(100% - 96px);position:relative;touch-action:none;}
  .row{display:flex;justify-content:space-between;}
  .buy{color:#26a69a;} .sell{color:#ef5350;}
  #err{padding:14px;color:#ef5350;font-size:13px;}
</style>
</head>
<body>
<div id="info">در حال بارگذاری...</div>
<div id="chart"></div>
<div id="err"></div>
<script>
const tg = window.Telegram && window.Telegram.WebApp;
if (tg) { tg.ready(); tg.expand(); }
const params = new URLSearchParams(window.location.search);
const symbol = params.get('symbol') || '';
const tf = params.get('tf') || '5min';
const initData = tg ? tg.initData : '';

async function load() {
  try {
    const res = await fetch('/miniapp/api/data', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({initData, symbol, tf})
    });
    const data = await res.json();
    if (!res.ok || data.error) {
      document.getElementById('err').textContent = data.error || 'خطا در دریافت داده';
      document.getElementById('info').textContent = '';
      return;
    }
    let p = data.position;
    const sideLabel = p ? (p.side.includes('BUY') ? 'خرید (Long)' : 'فروش (Short)') : '—';
    const sideClass = p && p.side.includes('BUY') ? 'buy' : 'sell';
    document.getElementById('info').innerHTML = `
      <div class="row"><span>نماد</span><b>${data.symbol} (${tf})</b></div>
      ${p ? `
      <div class="row"><span>جهت</span><b class="${sideClass}">${sideLabel}</b></div>
      <div class="row"><span>ورود</span><b>${p.entry_price}</b></div>
      <div class="row"><span>حد ضرر (SL)</span><b class="sell">${p.sl}</b></div>
      <div class="row"><span>حد سود (TP)</span><b class="buy">${p.tp}</b></div>
      ` : '<div class="row"><span>پوزیشن باز فعالی برای این نماد نیست</span></div>'}
    `;
    const chartEl = document.getElementById('chart');
    const chart = LightweightCharts.createChart(chartEl, {
      width: chartEl.clientWidth, height: chartEl.clientHeight,
      layout: {background:{color:'#0e0e12'}, textColor:'#c8c8d0'},
      grid: {vertLines:{color:'#1c1c24'}, horzLines:{color:'#1c1c24'}},
      timeScale: {timeVisible:true, secondsVisible:false},
      rightPriceScale: {borderColor:'#2a2a33'},
    });
    const series = chart.addCandlestickSeries({
      upColor:'#26a69a', downColor:'#ef5350', borderVisible:false,
      wickUpColor:'#26a69a', wickDownColor:'#ef5350',
    });
    series.setData(data.candles);
    if (p) {
      series.createPriceLine({price: p.entry_price, color:'#f0c419', lineWidth:1, lineStyle:2, title:'ورود'});
      series.createPriceLine({price: p.sl, color:'#ef5350', lineWidth:2, lineStyle:0, title:'SL'});
      series.createPriceLine({price: p.tp, color:'#26a69a', lineWidth:2, lineStyle:0, title:'TP'});
    }
    chart.timeScale().fitContent();
    window.addEventListener('resize', () => chart.applyOptions({width: chartEl.clientWidth, height: chartEl.clientHeight}));
  } catch (e) {
    document.getElementById('err').textContent = 'خطای شبکه: ' + e;
  }
}
load();
</script>
</body>
</html>"""


@app.get('/miniapp/chart')
def miniapp_chart_page():
    return _MINIAPP_CHART_HTML, 200, {'Content-Type': 'text/html; charset=utf-8'}


@app.post('/miniapp/api/data')
def miniapp_api_data():
    body = request.get_json(silent=True) or {}
    init_data = body.get('initData', '')
    symbol = str(body.get('symbol', '')).strip().upper()
    tf = str(body.get('tf', '5min')).strip()
    if not symbol: return {'error': 'نماد مشخص نشده'}, 400
    user = _validate_telegram_webapp_initdata(init_data)
    if not user or not user.get('id'): return {'error': 'احراز هویت تلگرام نامعتبر است'}, 401
    chat_id = user['id']
    if ALLOWED_CHAT_IDS and chat_id not in ALLOWED_CHAT_IDS: return {'error': 'دسترسی مجاز نیست'}, 403
    df = get_klines(symbol, tf, 200)
    if df.empty: return {'error': 'داده کندل در دسترس نیست'}, 404
    candles = [
        {'time': int(row['timestamp']) // 1000 if row['timestamp'] > 1e12 else int(row['timestamp']),
         'open': float(row['open']), 'high': float(row['high']), 'low': float(row['low']), 'close': float(row['close'])}
        for _, row in df.iterrows()
    ]
    pos = _miniapp_find_position(chat_id, symbol)
    position = None
    if pos:
        position = {
            'side': pos['side'],
            'entry_price': round(float(pos['entry_price']), 8),
            'sl': round(float(pos['sl']), 8),
            'tp': round(float(pos['tp']), 8),
            'is_real': bool(pos.get('is_real', False)),
        }
    return {'symbol': symbol, 'candles': candles, 'position': position}, 200


def miniapp_chart_url(symbol, timeframe='5min'):
    if not MINIAPP_BASE_URL:
        return None
    return f'{MINIAPP_BASE_URL}/miniapp/chart?symbol={symbol}&tf={timeframe}'


def _notify_boot_status():
    """بعد از هر بالا آمدن پروسه، به کاربران شناخته‌شده اطلاع می‌دهد چند سشن و پوزیشن باز بارگذاری
    شد. هدف این است که اگر دیتابیس به هر دلیل (مثلاً دیسک غیردائمی) خالی بارگذاری شود، کاربر همان
    لحظه متوجه شود، نه اینکه بعداً و تصادفی بفهمد پوزیشن‌ها و آمارش پاک شده‌اند."""
    try:
        targets = set(ALLOWED_CHAT_IDS) | set(USER_SESSIONS.keys())
        if not targets:
            return
        total_open = sum(len(s.get('paper_positions') or []) for s in USER_SESSIONS.values())
        total_closed = sum(len(s.get('closed_positions') or []) for s in USER_SESSIONS.values())
        for cid in targets:
            s = USER_SESSIONS.get(cid)
            open_n = len(s.get('paper_positions') or []) if s else 0
            closed_n = len(s.get('closed_positions') or []) if s else 0
            msg = f"🔄 *ربات بالا آمد.*\nپوزیشن‌های باز شما: `{open_n}` | تاریخچه بسته‌شده: `{closed_n}`"
            if s is None or (open_n == 0 and closed_n == 0):
                msg += "\n\n⚠️ اگر انتظار داشتید اینجا داده‌ای باشد، ممکن است دیتابیس ری‌ست شده باشد (مشکل ماندگاری دیسک هاست)."
            try:
                send_message(cid, msg)
            except Exception:
                pass
        logger.info('Boot status: sessions=%s total_open_positions=%s total_closed_positions=%s', len(USER_SESSIONS), total_open, total_closed)
    except Exception:
        logger.exception('boot status notification failed')


def main():
    init_db()
    load_telegram_offset()
    load_sessions()
    logger.info('Loaded %s sessions', len(USER_SESSIONS))
    _notify_boot_status()
    configure_telegram_native_menu()
    Thread(target=telegram_listener, daemon=True, name='telegram').start()
    Thread(target=lambda: (time.sleep(3), asyncio.run(scan_loop())), daemon=True, name='scanner').start()
    app.run(host='0.0.0.0', port=PORT, threaded=True)


if __name__ == '__main__':
    main()
