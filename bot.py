import os, json, time, asyncio, aiohttp, requests, sqlite3, logging, math, io, hashlib, hmac, re
import urllib.parse as urlparse
from threading import Thread, RLock
from typing import Dict, Any

try:
    import psycopg
    from psycopg.rows import tuple_row
except Exception:
    psycopg = None
    tuple_row = None
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

import pandas as pd
import ccxt
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from flask import Flask, request

from strategy import (
    FILTER_DEFAULTS, STRATEGY_DEFAULTS, calculate_indicators, get_signal_with_reason,
    strategy_trend_following,
    strategy_breakout, strategy_mean_reversion, build_trade_plan, get_timeframe_preset,
    _compute_prev_day_levels, evaluate_trend_weakness, compute_swing_stop,
    compute_log_grid_levels, nearest_grid_level,
)
from ui import (
    get_start_keyboard, get_balance_keyboard, get_margin_keyboard, get_leverage_keyboard,
    get_max_positions_keyboard, get_timeframe_keyboard, get_main_menu_keyboard,
    get_watchlist_manage_keyboard,
    get_params_menu_keyboard, get_positions_keyboard,
    get_bottom_menu_keyboard, get_confirm_close_all_keyboard, get_learn_menu_keyboard,
    get_confirm_emergency_close_keyboard,
    get_performance_keyboard, get_entry_diag_keyboard, get_manual_side_keyboard,
    get_confirm_close_longs_keyboard, get_confirm_close_shorts_keyboard,
)

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
MINIAPP_BASE_URL = os.environ.get('MINIAPP_BASE_URL', '').strip().rstrip('/')
PORT = int(os.environ.get('PORT', '10000'))
DB_PATH = os.environ.get('BOT_DB_PATH', 'trader_bot.sqlite3')
DB_URL = (os.environ.get('DATABASE_URL') or os.environ.get('NEON_DATABASE_URL') or os.environ.get('POSTGRES_URL') or '').strip()
DB_BACKEND = 'postgres' if DB_URL.lower().startswith(('postgres://', 'postgresql://')) else 'sqlite'
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()
SCAN_INTERVAL_SECONDS = max(20, int(os.environ.get('SCAN_INTERVAL_SECONDS', '45')))
NO_ENTRY_REPORT_SECONDS = max(120, int(os.environ.get('NO_ENTRY_REPORT_SECONDS', '600')))
DATA_CACHE_SECONDS = max(5, int(os.environ.get('DATA_CACHE_SECONDS', '20')))
MAX_ASYNC_REQUESTS = max(2, int(os.environ.get('MAX_ASYNC_REQUESTS', '10')))
DAILY_LOSS_LIMIT_PCT = float(os.environ.get('DAILY_LOSS_LIMIT_PCT', '3'))
RISK_PER_TRADE_PCT = float(os.environ.get('RISK_PER_TRADE_PCT', '0.5'))
NO_OVERNIGHT_TIMEFRAMES = ('5min', '15min')
DAILY_CLOSE_TZ = os.environ.get('DAILY_CLOSE_TZ', 'Asia/Tehran')

POSITION_MANAGEMENT_TIMEFRAME_MAP = {
    '5min': '1min',
    '15min': '5min',
    '1hour': '15min',
    '4hour': '1hour',
}
POSITION_MANAGEMENT_MIN_LOSS_R = -0.10
POSITION_MANAGEMENT_LOSS_WEAKNESS_SCORE = 45.0


def _seconds_to_local_day_end():
    tz = None
    if ZoneInfo is not None:
        try: tz = ZoneInfo(DAILY_CLOSE_TZ)
        except Exception: tz = None
    now = datetime.now(tz) if tz else datetime.utcnow()
    day_end = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (day_end - now).total_seconds()


MAX_MARGIN_USAGE_PCT = float(os.environ.get('MAX_MARGIN_USAGE_PCT', '50'))
TAKER_FEE_PCT = max(0.0, float(os.environ.get('TAKER_FEE_PCT', '0.05')))
MIN_RISK_TO_FEE_RATIO = max(0.0, float(os.environ.get('MIN_RISK_TO_FEE_RATIO', '3.0')))
PLATFORM_FEE_RATE_PCT = min(100.0, max(0.0, float(os.environ.get('PLATFORM_FEE_RATE_PCT', '10.0'))))
PLATFORM_FEE_MIN_PROFIT_USDT = max(0.0, float(os.environ.get('PLATFORM_FEE_MIN_PROFIT_USDT', '0.01')))
ADMIN_CHAT_IDS_RAW = os.environ.get('ADMIN_CHAT_IDS', os.environ.get('ALLOWED_CHAT_IDS', '')).strip()
ADMIN_CHAT_IDS = {int(x.strip()) for x in ADMIN_CHAT_IDS_RAW.split(',') if x.strip().lstrip('-').isdigit()}
REAL_RESTART_LOCK = os.environ.get('REAL_RESTART_LOCK', 'true').lower() not in ('0', 'false', 'no')
MARGIN_MODE = os.environ.get('MARGIN_MODE', 'isolated').lower()
PROTECTION_TRIGGER = os.environ.get('PROTECTION_TRIGGER', 'mark_price').lower()

ENTRY_ORDER_TYPE = os.environ.get('ENTRY_ORDER_TYPE', 'limit').lower()
ORDER_CONFIRM_RETRIES = max(1, int(os.environ.get('ORDER_CONFIRM_RETRIES', '6')))
ORDER_CONFIRM_DELAY = max(0.25, float(os.environ.get('ORDER_CONFIRM_DELAY', '1.0')))
PAPER_CONSERVATIVE_OHLC = os.environ.get('PAPER_CONSERVATIVE_OHLC', 'true').lower() not in ('0', 'false', 'no')
PAPER_ONLY = os.environ.get('PAPER_ONLY', 'true').lower() not in ('0', 'false', 'no')
PAPER_SLIPPAGE_BPS = max(0.0, float(os.environ.get('PAPER_SLIPPAGE_BPS', '2.0')))
PAPER_FUNDING_RATE_PCT_8H = max(0.0, float(os.environ.get('PAPER_FUNDING_RATE_PCT_8H', '0.01')))
TELEGRAM_SKIP_BACKLOG = os.environ.get('TELEGRAM_SKIP_BACKLOG', 'true').lower() not in ('0', 'false', 'no')

COINEX_ACCOUNTS_JSON = os.environ.get('COINEX_ACCOUNTS_JSON', '{}').strip()
try:
    COINEX_ACCOUNTS = json.loads(COINEX_ACCOUNTS_JSON) if COINEX_ACCOUNTS_JSON else {}
except Exception:
    COINEX_ACCOUNTS = {}

ALLOWED_CHAT_IDS_RAW = os.environ.get('ALLOWED_CHAT_IDS', '').strip()
ALLOWED_CHAT_IDS = {int(x.strip()) for x in ALLOWED_CHAT_IDS_RAW.split(',') if x.strip().lstrip('-').isdigit()}

ALL_SYMBOLS = ['ATOM','BCH','AVAX','UNI','HOT','FIL','ANKR','DOT','THETA','LINK','BNB','SHIB','TRX','DASH','BTT','QTUM','ADA','ZEC','CRV','GALA','EGLD','NEAR','WAVES','RUNE','KSM','HNT','DYDX','ETC','STORJ','IOTA','ALGO','MASK','NEO','BTC','COMP','ONE','AR','LUNA','MANA','ETH','SOL','SUSHI','SKL','CHZ','TRB','VET','SLP','ZIL','AAVE','RVN','ENJ','XTZ','AXS','SNX','SAND','RSR','ZRX','RAY']
PAPER_DEFAULT_SYMBOLS = ['BTC','ETH','SOL','BNB','XRP','DOGE','ADA','LINK','AVAX','DOT','TRX','LTC','BCH','UNI','AAVE','NEAR','ATOM','ETC','FIL','SUI','APT','ARB','OP','INJ','SEI','TIA','TON','SHIB','PEPE','WIF']
PAPER_SYMBOLS = [x.strip().upper() for x in os.environ.get('PAPER_SYMBOLS', ','.join(PAPER_DEFAULT_SYMBOLS)).split(',') if x.strip()]
DEFAULT_ACTIVE_SYMBOLS = ALL_SYMBOLS[:]
LEGACY_DEFAULT_ACTIVE_SYMBOLS = ['BTC','ETH','SOL','BNB','XRP','ADA','DOGE','LTC','LINK','DOT','AVAX','ATOM','NEAR','TRX','ETC','FIL','UNI','AAVE','MATIC','XTZ']
TIMEFRAME_MAP = {'5min':'5min','15min':'15min','1hour':'1hour','4hour':'4hour','1day':'1day'}
TF_DISPLAY = {'5min':'5م','15min':'15م','1hour':'1س','4hour':'4س','1day':'روزانه'}

LONG_WATCHLIST = ['ATOM','BCH','AVAX','UNI','HOT','FIL','ANKR','DOT','THETA','LINK','BNB','SHIB','TRX','DASH','BTT','QTUM','ADA','ZEC','CRV','GALA','EGLD','NEAR','WAVES','RUNE','KSM','HNT','DYDX','ETC','STORJ']
WINNING_WATCHLISTS = {tf: LONG_WATCHLIST for tf in ('5min', '15min', '1hour', '4hour')}
SUPPORTED_TRADING_TIMEFRAMES = tuple(WINNING_WATCHLISTS.keys())

SHORT_WATCHLIST = ['IOTA','ALGO','MASK','NEO','UNI','STORJ','BTC','DASH','RUNE','COMP','BNB','ONE','GALA','AR','LUNA','MANA','ETH','ETC','SOL','SUSHI','LINK','SKL','CHZ','TRB','EGLD','BTT','VET','NEAR','SLP','ANKR','ADA','ZIL','BCH','AAVE','DYDX','RVN','SHIB','TRX','ATOM','ENJ','WAVES','ZEC','XTZ','AVAX','AXS','SNX','KSM','SAND','RSR','ZRX','RAY','QTUM']
WINNING_SHORT_WATCHLISTS = {tf: SHORT_WATCHLIST for tf in ('5min', '15min', '1hour', '4hour')}

SHARED_LONG_WATCHLIST = LONG_WATCHLIST
SHARED_SHORT_WATCHLIST = SHORT_WATCHLIST
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
REAL_PRICE_CACHE: Dict[str, Dict[str, Any]] = {}
ASYNC_SEMAPHORE = None
ENTRY_LOCKS: Dict[int, RLock] = {}
ENTRY_LOCKS_GUARD = RLock()
TELEGRAM_OFFSET = 0

class ExchangeStateError(RuntimeError):
    pass


def json_default(obj):
    if isinstance(obj, set): return list(obj)
    raise TypeError


class _DBNoopCursor:
    def fetchone(self): return None
    def fetchall(self): return []


class _DBConnection:
    def __init__(self, raw, backend):
        self.raw = raw
        self.backend = backend

    def execute(self, sql, params=None):
        if self.backend == 'postgres':
            if sql.lstrip().upper().startswith('PRAGMA '):
                return _DBNoopCursor()
            sql = sql.replace('?', '%s')
        try:
            return self.raw.execute(sql) if params is None else self.raw.execute(sql, params)
        except Exception as exc:
            if self.backend == 'postgres' and psycopg is not None:
                if isinstance(exc, psycopg.errors.UniqueViolation):
                    raise sqlite3.IntegrityError(str(exc)) from exc
            raise

    def commit(self): return self.raw.commit()
    def rollback(self): return self.raw.rollback()
    def close(self): return self.raw.close()


def db_connect():
    if DB_BACKEND == 'postgres':
        if psycopg is None:
            raise RuntimeError('DATABASE_URL تنظیم شده ولی psycopg نصب نیست.')
        url = DB_URL
        if 'sslmode=' not in url.lower():
            url += ('&' if '?' in url else '?') + 'sslmode=require'
        return _DBConnection(psycopg.connect(url, connect_timeout=15, row_factory=tuple_row), 'postgres')
    return _DBConnection(sqlite3.connect(DB_PATH, timeout=15), 'sqlite')


def init_db():
    db_existed_before = os.path.exists(DB_PATH) if DB_BACKEND == 'sqlite' else True
    with DB_LOCK:
        conn = db_connect()
        try:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA synchronous=NORMAL')
            conn.execute('PRAGMA busy_timeout=15000')
            fee_id_type = 'BIGSERIAL PRIMARY KEY' if DB_BACKEND == 'postgres' else 'INTEGER PRIMARY KEY AUTOINCREMENT'
            real_type = 'DOUBLE PRECISION' if DB_BACKEND == 'postgres' else 'REAL'
            conn.execute('CREATE TABLE IF NOT EXISTS sessions(chat_id BIGINT PRIMARY KEY, data TEXT NOT NULL, updated_at INTEGER NOT NULL)')
            conn.execute('CREATE TABLE IF NOT EXISTS bot_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at INTEGER NOT NULL)')
            conn.execute('''CREATE TABLE IF NOT EXISTS fee_ledger(
                id %s, trade_id TEXT NOT NULL UNIQUE, chat_id BIGINT NOT NULL, mode TEXT NOT NULL,
                gross_pnl_usdt %s NOT NULL DEFAULT 0, trading_cost_usdt %s NOT NULL DEFAULT 0,
                net_profit_before_platform_fee_usdt %s NOT NULL DEFAULT 0, fee_rate_pct %s NOT NULL DEFAULT 0,
                platform_fee_usdt %s NOT NULL DEFAULT 0, user_net_profit_usdt %s NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'SETTLED', created_at %s NOT NULL, settled_at %s
            )''' % ((fee_id_type,) + (real_type,)*8))
            conn.execute('''CREATE TABLE IF NOT EXISTS user_fee_settings(
                chat_id BIGINT PRIMARY KEY, fee_rate_pct %s NOT NULL, updated_at INTEGER NOT NULL
            )''' % real_type)
            conn.execute('''CREATE TABLE IF NOT EXISTS users(
                chat_id BIGINT PRIMARY KEY, telegram_user_id BIGINT, username TEXT, first_name TEXT,
                last_name TEXT, first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL, is_active INTEGER NOT NULL DEFAULT 1
            )''')
            conn.commit()
        finally:
            conn.close()


def _sqlite_table_exists(conn, table_name):
    try:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)).fetchone()
        return bool(row)
    except Exception:
        return False


def migrate_legacy_sqlite_to_postgres():
    if DB_BACKEND != 'postgres': return
    legacy_path = os.environ.get('LEGACY_SQLITE_PATH', DB_PATH).strip() or DB_PATH
    if not os.path.exists(legacy_path): return
    with DB_LOCK:
        pg = db_connect()
        try:
            marker = pg.execute("SELECT value FROM bot_meta WHERE key=?", ('sqlite_migration_v1',)).fetchone()
            if marker and str(marker[0]).lower() in ('done','completed'): return
            src = sqlite3.connect(legacy_path, timeout=15)
            try:
                src.row_factory = sqlite3.Row
                if not _sqlite_table_exists(src, 'sessions'):
                    pg.execute("INSERT INTO bot_meta(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at", ('sqlite_migration_v1','done',int(time.time())))
                    pg.commit()
                    return
                for r in src.execute('SELECT chat_id,data,updated_at FROM sessions').fetchall():
                    existing = pg.execute('SELECT updated_at FROM sessions WHERE chat_id=?', (int(r['chat_id']),)).fetchone()
                    if not existing or int(r['updated_at'] or 0) > int(existing[0] or 0):
                        if existing: pg.execute('UPDATE sessions SET data=?,updated_at=? WHERE chat_id=?', (r['data'], int(r['updated_at']), int(r['chat_id'])))
                        else: pg.execute('INSERT INTO sessions(chat_id,data,updated_at) VALUES(?,?,?)', (int(r['chat_id']), r['data'], int(r['updated_at'])))
                pg.commit()
            except Exception:
                pg.rollback()
                raise
            finally: src.close()
        finally: pg.close()


def upsert_telegram_user(user, chat_id=None):
    if not user: return
    try:
        uid = int(user.get('id') or chat_id)
        cid = int(chat_id if chat_id is not None else uid)
    except Exception: return
    username = str(user.get('username') or '').strip() or None
    first_name = str(user.get('first_name') or '').strip() or None
    last_name = str(user.get('last_name') or '').strip() or None
    now = int(time.time())
    with DB_LOCK:
        conn = db_connect()
        try:
            conn.execute('''INSERT INTO users(chat_id,telegram_user_id,username,first_name,last_name,first_seen,last_seen,is_active)
                VALUES(?,?,?,?,?,?,?,1) ON CONFLICT(chat_id) DO UPDATE SET
                telegram_user_id=excluded.telegram_user_id, username=COALESCE(excluded.username, users.username),
                first_name=COALESCE(excluded.first_name, users.first_name), last_name=COALESCE(excluded.last_name, users.last_name),
                last_seen=excluded.last_seen, is_active=1''', (cid, uid, username, first_name, last_name, now, now))
            conn.commit()
        finally: conn.close()


def admin_users_report(limit=100):
    with DB_LOCK:
        conn=db_connect()
        try:
            rows=conn.execute('''SELECT u.chat_id,u.username,u.first_name,u.last_name,u.first_seen,u.last_seen,u.is_active,
                    (SELECT COUNT(*) FROM fee_ledger f WHERE f.chat_id=u.chat_id) AS fee_trades,
                    (SELECT COALESCE(SUM(f.platform_fee_usdt),0) FROM fee_ledger f WHERE f.chat_id=u.chat_id) AS fee_total
                FROM users u ORDER BY u.last_seen DESC LIMIT ?''',(int(limit),)).fetchall()
        finally: conn.close()
    if not rows: return '👥 *کاربران ربات*\n\nهنوز کاربری ثبت نشده است.'
    active = sum(1 for r in rows if r[6])
    lines = [f'👥 *کاربران ربات*', '', f'• تعداد نمایش‌داده‌شده: `{len(rows)}`', f'• فعال در ۳۰ روز اخیر: `{active}`', '', '*فهرست:*']
    for i, (cid, username, first, last, first_seen, last_seen, is_active, fee_trades, fee_total) in enumerate(rows, 1):
        name = ' '.join(x for x in (first, last) if x) or 'بدون نام'
        uname = f'@{username}' if username else 'بدون username'
        status = '🟢' if is_active else '⚪️'
        lines.append(f'{status} `{i}` {name} — `{uname}`\n   ID: `{cid}` | کارمزد: `{fee_total:.2f}` USDT ({fee_trades})')
    return '\n'.join(lines)


def admin_user_detail(chat_id, target_id):
    with DB_LOCK:
        conn=db_connect()
        try:
            row=conn.execute('SELECT chat_id,telegram_user_id,username,first_name,last_name,first_seen,last_seen,is_active FROM users WHERE chat_id=?',(int(target_id),)).fetchone()
            fee=conn.execute('SELECT COALESCE(SUM(platform_fee_usdt),0),COUNT(*) FROM fee_ledger WHERE chat_id=?',(int(target_id),)).fetchone()
        finally: conn.close()
    if not row: return f'❌ کاربری با ID `{target_id}` پیدا نشد.'
    cid, uid, username, first, last, first_seen, last_seen, is_active = row
    fee_total, fee_count = fee or (0, 0)
    name = ' '.join(x for x in (first, last) if x) or 'بدون نام'
    return f'👤 *پروفایل کاربر*\nنام: `{name}`\nChat ID: `{cid}`\nکارمزد ثبت‌شده: `{fee_total:.2f} USDT` در `{fee_count}` معامله'


def save_session(chat_id):
    with STATE_LOCK:
        data = USER_SESSIONS.get(chat_id)
        if data is None: return
        payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'), default=json_default)
    with DB_LOCK:
        conn = db_connect()
        try:
            conn.execute('INSERT INTO sessions(chat_id,data,updated_at) VALUES(?,?,?) ON CONFLICT(chat_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at', (chat_id, payload, int(time.time())))
            conn.commit()
        finally: conn.close()


def audit_event(chat_id, trade_id, stage, data=None):
    try:
        s = get_session(chat_id)
        event = {'trade_id': str(trade_id), 'stage': str(stage), 'ts': time.time(), 'data': data or {}}
        s.setdefault('trade_audit', []).append(event)
        s['trade_audit'] = s['trade_audit'][-2000:]
        save_session(chat_id)
        return event
    except Exception: return None


def new_trade_id(chat_id, symbol):
    return hashlib.sha1(f"{chat_id}:{symbol}:{time.time_ns()}".encode()).hexdigest()[:12].upper()


def audit_trade_record(p):
    return {
        'trade_id': p.get('trade_id'), 'symbol': p.get('symbol'), 'side': p.get('side'),
        'timeframe': p.get('timeframe'), 'strategy': p.get('strategy'), 'opened_at': p.get('opened_at'),
        'entry_price': p.get('entry_price'), 'close_price': p.get('close_price'),
        'sl': p.get('sl'), 'tp': p.get('tp'), 'amount': p.get('amount'),
        'margin': p.get('margin'), 'leverage': p.get('leverage'), 'pnl_usdt': p.get('pnl_usdt'),
        'fee_usdt': p.get('fee_usdt'), 'platform_fee_usdt': p.get('platform_fee_usdt'),
    }


def get_entry_lock(chat_id):
    with ENTRY_LOCKS_GUARD: return ENTRY_LOCKS.setdefault(int(chat_id), RLock())


def load_telegram_offset():
    global TELEGRAM_OFFSET
    with DB_LOCK:
        conn = db_connect()
        try: row = conn.execute('SELECT value FROM bot_meta WHERE key=?', ('telegram_offset',)).fetchone()
        finally: conn.close()
    try: TELEGRAM_OFFSET = max(0, int(row[0])) if row else 0
    except Exception: TELEGRAM_OFFSET = 0


def save_telegram_offset(offset):
    global TELEGRAM_OFFSET
    TELEGRAM_OFFSET = max(0, int(offset))
    with DB_LOCK:
        conn = db_connect()
        try:
            conn.execute('INSERT INTO bot_meta(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at', ('telegram_offset', str(TELEGRAM_OFFSET), int(time.time())))
            conn.commit()
        finally: conn.close()


def default_session():
    return {
        'is_bot_active': False, 'scan_generation': 0, 'trading_mode': 'PAPER',
        'paper_balance': 1000.0, 'daily_start_equity': 1000.0,
        'daily_start_date': time.strftime('%Y-%m-%d', time.gmtime()), 'daily_stopped': False,
        'trade_amount_usdt': 50.0, 'leverage': 5, 'max_open_positions': 3,
        'timeframe': '5min', 'active_strategy': 'dynamic', 'paper_positions': [],
        'closed_positions': [], 'trade_audit': [],
        'scan_stats': {'scans': 0, 'symbols': 0, 'signals': 0, 'entries': 0, 'blocked': 0, 'data_errors': 0, 'reason_counts': {}},
        'cooldowns': {}, 'traded_levels': {}, 'user_state': None,
        'active_symbols': (PAPER_SYMBOLS[:] if PAPER_ONLY else DEFAULT_ACTIVE_SYMBOLS[:]),
        'filters': FILTER_DEFAULTS.copy(), 'strategy_config': get_timeframe_preset('5min'),
        'daily_loss_limit_pct': DAILY_LOSS_LIMIT_PCT, 'risk_per_trade_pct': RISK_PER_TRADE_PCT,
        'max_margin_usage_pct': MAX_MARGIN_USAGE_PCT, 'entry_diag_enabled': True,
        'platform_fee_rate_pct': PLATFORM_FEE_RATE_PCT, 'platform_fee_total_usdt': 0.0,
        'platform_fee_trade_count': 0, 'positions_message_id': None, 'positions_message_last_edit': 0.0,
    }


def normalize_session(data):
    s = default_session(); s.update(data or {})
    s['filters'] = {**FILTER_DEFAULTS, **(data.get('filters') or {})}
    s['paper_positions'] = list(data.get('paper_positions') or [])
    s['closed_positions'] = list(data.get('closed_positions') or [])
    s['trade_audit'] = list(data.get('trade_audit') or [])[-2000:]
    s['cooldowns'] = dict(data.get('cooldowns') or {})
    s['traded_levels'] = dict(data.get('traded_levels') or {})
    s['active_symbols'] = PAPER_SYMBOLS[:] if PAPER_ONLY else (list(data.get('active_symbols') or []) or DEFAULT_ACTIVE_SYMBOLS[:])
    for k in ('paper_balance','daily_start_equity','trade_amount_usdt','daily_loss_limit_pct','risk_per_trade_pct','max_margin_usage_pct'):
        s[k] = float(s.get(k, default_session()[k]))
    if s.get('timeframe') not in SUPPORTED_TRADING_TIMEFRAMES: s['timeframe'] = '5min'
    s['strategy_config'] = get_timeframe_preset(s['timeframe'])
    s['entry_diag_enabled'] = bool(s.get('entry_diag_enabled', True))
    s['platform_fee_rate_pct'] = min(100.0, max(0.0, float(s.get('platform_fee_rate_pct', PLATFORM_FEE_RATE_PCT))))
    return s


def load_sessions():
    with DB_LOCK:
        conn = db_connect()
        try: rows = conn.execute('SELECT chat_id,data FROM sessions').fetchall()
        finally: conn.close()
    with STATE_LOCK:
        for chat_id, raw in rows:
            try: USER_SESSIONS[int(chat_id)] = normalize_session(json.loads(raw))
            except Exception: pass


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
    if cached and cached.get('fingerprint') == fingerprint: return cached.get('exchange')
    try:
        ex = ccxt.coinex({'apiKey':creds[0],'secret':creds[1],'enableRateLimit':True,'options':{'defaultType':'swap','defaultMarginMode':MARGIN_MODE}})
        ex.load_markets()
        EXCHANGE_CACHE[chat_id] = {'fingerprint': fingerprint, 'exchange': ex}
        return ex
    except Exception:
        EXCHANGE_CACHE.pop(chat_id, None)
        return None


def is_allowed(chat_id):
    return (not ALLOWED_CHAT_IDS) or (chat_id in ALLOWED_CHAT_IDS)


def tg(method, payload=None, timeout=10):
    if not TELEGRAM_TOKEN: return None
    try:
        r = requests.post(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}', json=payload or {}, timeout=timeout)
        if r.status_code != 200: return None
        return r.json()
    except Exception: return None


TELEGRAM_COMMANDS = [{'command':'menu','description':'منوی اصلی'}]

def configure_telegram_native_menu():
    if not TELEGRAM_TOKEN: return
    tg('setMyCommands', {'commands': TELEGRAM_COMMANDS}, 10)
    tg('setChatMenuButton', {'menu_button': {'type':'commands'}}, 10)


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
    body = {'chat_id':chat_id,'text':text,'reply_markup':markup}
    if parse_mode: body['parse_mode'] = parse_mode
    res = tg('sendMessage', body, 10)
    return bool(res and res.get('ok'))


def edit_page(chat_id, text, markup=None, message_id=None, parse_mode='Markdown'):
    return send_message(chat_id, text, markup, message_id=message_id, parse_mode=parse_mode)


def sync_bottom_keyboard(chat_id, status_message=None):
    s = get_session(chat_id)
    active = bool(s.get('is_bot_active'))
    text = status_message or ("🟢 اسکن فعال است." if active else "🔴 اسکن متوقف است.")
    return send_message(chat_id, text, get_bottom_menu_keyboard(active), parse_mode=None)


def send_photo(chat_id, img, caption='', markup=None):
    if not is_allowed(chat_id) or not TELEGRAM_TOKEN: return False
    s = get_session(chat_id)
    if markup is None:
        markup = get_bottom_menu_keyboard(s['is_bot_active'], s.get('bottom_menu_open', True))
    try:
        r = requests.post(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto', data={'chat_id':chat_id,'caption':caption,'parse_mode':'Markdown','reply_markup':json.dumps(markup, ensure_ascii=False)}, files={'photo':('chart.png',img,'image/png')}, timeout=20)
        return r.status_code == 200
    except Exception: return False


def fmt(v):
    try:
        x=float(v)
        if abs(x)<.0001: return f'{x:.8f}'
        if abs(x)<1: return f'{x:.6f}'
        return f'{x:.4f}'
    except Exception: return str(v)


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
    except Exception: pass
    return pd.DataFrame()


async def get_klines_async(http, symbol, tf='5min', limit=200):
    period=TIMEFRAME_MAP.get(tf,tf); key=f'{symbol}:{period}:{limit}'; now=time.time()
    with DATA_LOCK:
        c=DATA_CACHE.get(key)
        if c and now-c['ts']<DATA_CACHE_SECONDS: return c['df'].copy()
    await ASYNC_SEMAPHORE.acquire()
    try:
        async with http.get(f'{COINEX_PUBLIC}/futures/kline', params={'market':market_name(symbol),'period':period,'limit':min(limit,1000)}) as r:
            if r.status == 200:
                p=await r.json()
                if p.get('code')==0:
                    df=normalize_klines(p.get('data'))
                    for c_col in ['timestamp','open','close','high','low','volume']: df[c_col]=pd.to_numeric(df[c_col],errors='coerce')
                    if len(df)>=60:
                        with DATA_LOCK: DATA_CACHE[key]={'ts':now,'df':df.copy()}
                        return df
    except Exception: pass
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
    except Exception: pass
    return None


def exchange_latest_price(chat_id, symbol):
    ex=get_exchange(chat_id)
    if not ex: return None
    try:
        ticker=ex.fetch_ticker(ccxt_symbol(symbol))
        price=float(ticker.get('last') or ticker.get('mark') or 0)
        if price>0: return price
    except Exception: pass
    return None


def exchange_balance(chat_id):
    ex=get_exchange(chat_id)
    if not ex: raise ExchangeStateError('exchange unavailable')
    try:
        b=ex.fetch_balance({'type':'swap'})
        total=(b.get('total') or {}).get('USDT')
        if total is None: raise ExchangeStateError('USDT balance missing')
        return float(total)
    except Exception as exc:
        raise ExchangeStateError(f'balance fetch failed: {exc}') from exc


def get_open_positions(chat_id):
    ex=get_exchange(chat_id)
    if not ex: raise ExchangeStateError('exchange unavailable')
    try:
        rows=ex.fetch_positions()
        return [p for p in rows if abs(float(p.get('contracts') or p.get('amount') or 0))>0]
    except Exception as exc:
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


def side_long(side): return 'BUY' in str(side).upper() or 'LONG' in str(side).upper()
def reserved_margin(s): return sum(float(p.get('margin',0)) for p in s['paper_positions'])


def round_trip_fee_usdt(margin, leverage):
    try:
        notional = abs(float(margin)) * abs(float(leverage))
        if not math.isfinite(notional): return 0.0
        return notional * (TAKER_FEE_PCT / 100.0) * 2
    except Exception: return 0.0


def _apply_profit_protection(chat_id, s, p, favorable_price, current_price=None):
    return False


def _check_swing_trailing_stop(chat_id, s, p, price, sdf=None):
    pass


def _maybe_close_before_day_end(chat_id, p, price):
    tf = p.get('timeframe', '5min')
    if tf not in NO_OVERNIGHT_TIMEFRAMES: return False
    if _seconds_to_local_day_end() > SCAN_INTERVAL_SECONDS: return False
    close_position(chat_id, p, price, 'پایان روز - بستن اجباری')
    return True


def reset_daily_if_needed(chat_id, equity):
    s=get_session(chat_id); today=time.strftime('%Y-%m-%d',time.gmtime())
    if s.get('daily_start_date')!=today:
        s['daily_start_date']=today; s['daily_start_equity']=float(equity); s['daily_stopped']=False; save_session(chat_id)


def risk_guard(chat_id):
    s=get_session(chat_id); now=time.time()
    if now-s.get('last_risk_check',0)<15: return not s['daily_stopped']
    s['last_risk_check']=now
    try: equity=exchange_balance(chat_id) if s['trading_mode']=='REAL' else s['paper_balance']
    except Exception: return False
    reset_daily_if_needed(chat_id,equity)
    start=float(s['daily_start_equity'])
    if start<=0: return True
    limit=start*(1-float(s['daily_loss_limit_pct'])/100)
    if equity<=limit:
        s['daily_stopped']=True; save_session(chat_id)
        return False
    return True


def normalize_amount(chat_id,symbol,amount):
    ex=get_exchange(chat_id)
    if not ex: return float(amount)
    try: return float(ex.amount_to_precision(ccxt_symbol(symbol),amount))
    except Exception: return float(amount)


def normalize_price(chat_id,symbol,price):
    ex=get_exchange(chat_id)
    if not ex: return float(price)
    try: return float(ex.price_to_precision(ccxt_symbol(symbol),price))
    except Exception: return float(price)


def safe_size(chat_id,s,entry,sl):
    try:
        balance=exchange_balance(chat_id) if s['trading_mode']=='REAL' else float(s['paper_balance'])
    except Exception: return 0, 'error'
    stop_dist=abs(entry-sl)/max(abs(entry),1e-12)
    if stop_dist<=0: return 0, 'invalid stop'
    risk_budget=balance*float(s['risk_per_trade_pct'])/100
    leverage=max(1,int(s['leverage']))
    requested_margin=float(s['trade_amount_usdt'])
    cap=balance*float(s['max_margin_usage_pct'])/100
    available=max(0,cap-reserved_margin(s))
    margin=min(requested_margin,available,(risk_budget/stop_dist)/leverage)
    if margin<=0: return 0, 'cap blocked'
    return margin, (margin*leverage)/entry


def expected_trade_metrics(trade):
    try:
        entry=float(trade.get('entry_price') or 0); tp=float(trade.get('tp') or 0); sl=float(trade.get('sl') or 0); amount=abs(float(trade.get('amount') or 0))
        if entry<=0 or tp<=0 or sl<=0 or amount<=0: return {'risk':0.0,'reward':0.0,'rr':0.0,'valid':False}
        risk, reward = abs((sl-entry)*amount), abs((tp-entry)*amount)
        return {'risk':risk,'reward':reward,'rr':(reward/risk) if risk>0 else 0.0,'valid':True}
    except Exception: return {'risk':0.0,'reward':0.0,'rr':0.0,'valid':False}


def fee_report(chat_id, period='all'):
    now=time.time(); since=0
    if period=='day': since=now-86400
    elif period=='week': since=now-7*86400
    elif period=='month': since=now-30*86400
    with DB_LOCK:
        conn=db_connect()
        try: row=conn.execute('SELECT COALESCE(SUM(platform_fee_usdt),0), COUNT(*), COALESCE(SUM(net_profit_before_platform_fee_usdt),0) FROM fee_ledger WHERE chat_id=? AND created_at>=?',(int(chat_id),since)).fetchone()
        finally: conn.close()
    fee,count,profit=row or (0,0,0)
    return f'💰 *کارمزد پلتفرم*\n\n• بازه: `{period}`\n• معاملات سودده: `{count}`\n• سود قبل از کارمزد: `{profit:.2f} USDT`\n• کارمزد شما: `{fee:.2f} USDT`\n• نرخ فعلی: `{get_user_fee_rate(chat_id):.2f}%`'


def admin_fee_report(period='all'):
    now=time.time(); since=0
    if period=='day': since=now-86400
    elif period=='week': since=now-7*86400
    elif period=='month': since=now-30*86400
    with DB_LOCK:
        conn=db_connect()
        try:
            total=conn.execute('SELECT COALESCE(SUM(platform_fee_usdt),0), COUNT(*), COUNT(DISTINCT chat_id) FROM fee_ledger WHERE created_at>=?',(since,)).fetchone()
            rows=conn.execute('SELECT chat_id, COALESCE(SUM(platform_fee_usdt),0), COUNT(*) FROM fee_ledger WHERE created_at>=? GROUP BY chat_id ORDER BY SUM(platform_fee_usdt) DESC LIMIT 20',(since,)).fetchall()
        finally: conn.close()
    fee,count,users=total or (0,0,0)
    lines=[f'👑 *گزارش درآمد پلتفرم — {period}*','',f'• درآمد کارمزد: `{fee:.2f} USDT`',f'• معاملات: `{count}`',f'• کاربران: `{users}`','','*برترین‌ها:*']
    lines += [f'• `{uid}` → `{amt:.2f} USDT` ({cnt})' for uid,amt,cnt in rows] or ['• ثبت نشده']
    return '\n'.join(lines)


def admin_set_fee_command(chat_id, text):
    if not is_admin(chat_id):
        send_message(chat_id,'⛔ دسترسی ادمین ندارید.'); return
    parts=(text or '').split()
    if len(parts) != 3:
        send_message(chat_id,'فرمت: `/set_fee USER_CHAT_ID RATE_PERCENT`',parse_mode='Markdown'); return
    try:
        uid=int(parts[1]); rate=float(parts[2])
        set_user_fee_rate(uid, rate)
        send_message(chat_id,f'✅ نرخ کارمزد کاربر `{uid}` روی `{rate:.2f}%` تنظیم شد.',parse_mode='Markdown')
    except Exception as exc:
        send_message(chat_id,f'❌ خطا: `{exc}`',parse_mode='Markdown')


def close_position(chat_id, pos, price=None, reason='manual'):
    s = get_session(chat_id)
    if pos not in s['paper_positions']: return False
    fee = round_trip_fee_usdt(pos.get('margin'), pos.get('leverage'))
    if price is None: price = latest_price(pos['symbol']) or pos['entry_price']
    entry = float(pos['entry_price'])
    frac = ((price - entry) / entry) if side_long(pos['side']) else ((entry - price) / entry)
    pnl = (float(pos['margin']) * frac * float(pos['leverage'])) - fee
    s['paper_balance'] += pnl
    pos['close_price'] = price
    platform_fee = settle_platform_fee(chat_id, pos, float(pnl)) if float(pnl) > PLATFORM_FEE_MIN_PROFIT_USDT else 0.0
    if platform_fee > 0:
        pnl -= platform_fee
        s['paper_balance'] -= platform_fee
    pos['platform_fee_usdt'] = platform_fee
    pos['pnl_usdt'] = float(pnl)
    s['closed_positions'].append(pos.copy())
    s['paper_positions'].remove(pos)
    save_session(chat_id)
    send_message(chat_id, f"📌 *پوزیشن بسته شد*\n• `{pos['symbol']}`\n• PnL: `{pnl:+.2f} USDT`\n• علت: `{reason}`")
    return True


def update_positions(chat_id):
    s = get_session(chat_id)
    if not s['paper_positions']: return
    for p in s['paper_positions'][:]:
        price = latest_price(p['symbol'])
        if not price: continue
        if _maybe_close_before_day_end(chat_id, p, price): continue
    save_session(chat_id)


def _entry_diag_result(chat_id, symbol, status, reason='', stage='', signal=None, diagnostics=None):
    return {'chat_id': chat_id, 'symbol': symbol, 'status': status, 'reason': str(reason or '').strip(), 'stage': stage, 'signal': signal, 'ts': time.time()}


def _entry_diag_label(reason):
    r = str(reason or '').strip()
    return r[:180] or 'دلیل مشخصی ثبت نشد'


def _entry_diag_report(chat_id, results, elapsed):
    s = get_session(chat_id)
    scanned = len(results)
    opened = sum(1 for x in results if x.get('status') == 'entry_opened')
    signals = sum(1 for x in results if x.get('signal'))
    lines = ['🔎 *گزارش تشخیصی ورود*', '━━━━━━━━━━━━━━━━━━━━', f'⏱ بازه: `{max(1, int(elapsed/60))} دقیقه`', f'🔍 بررسی‌شده: `{scanned}`', f'🎯 سیگنال: `{signals}`', f'📥 بازشده: `{opened}`']
    return '\n'.join(lines)


def _entry_diag_batch_update(chat_id, results):
    now = time.time()
    state = ENTRY_DIAG_STATE.setdefault(chat_id, {'no_entry_since': None, 'last_report_at': 0.0, 'window_results': []})
    opened = any(x.get('status') == 'entry_opened' for x in results)
    if opened:
        state['no_entry_since'] = None; state['window_results'] = []; return
    if not results: return
    state.setdefault('window_results', []).extend(results)
    state['window_results'] = state['window_results'][-240:]
    if state['no_entry_since'] is None: state['no_entry_since'] = now
    elapsed = now - float(state['no_entry_since'])
    last_report = float(state.get('last_report_at', 0.0) or 0.0)
    if not get_session(chat_id).get('entry_diag_enabled', True): return
    if elapsed >= NO_ENTRY_REPORT_SECONDS and (not last_report or now - last_report >= NO_ENTRY_REPORT_SECONDS):
        try:
            send_message(chat_id, _entry_diag_report(chat_id, list(state['window_results']), elapsed), parse_mode='Markdown')
            state['last_report_at'] = now
            state['window_results'] = []
        except Exception: pass


async def scan_symbol(http, chat_id, symbol, regime=None):
    s = get_session(chat_id)
    if not s['is_bot_active'] or s['daily_stopped']: return _entry_diag_result(chat_id, symbol, 'blocked', 'ربات متوقف است', 'precheck')
    d = await get_klines_async(http, symbol, s['timeframe'], 120)
    if d.empty: return _entry_diag_result(chat_id, symbol, 'data_error', 'داده خالی', 'data')
    primary = calculate_indicators(d)
    sig, reason = get_signal_with_reason(primary, {}, 'single', s['timeframe'], s['active_strategy'], s['filters'], s['strategy_config'], regime)
    if not sig: return _entry_diag_result(chat_id, symbol, 'no_signal', reason, 'signal')
    plan, plan_reason = build_trade_plan(primary, sig, s['strategy_config'], s['active_strategy'], strategy_timeframe=s['timeframe'])
    if not plan: return _entry_diag_result(chat_id, symbol, 'trade_plan_blocked', plan_reason, 'trade_plan', sig)
    ok = execute_trade(chat_id, symbol, 'BUY (Long)' if sig=='BUY' else 'SELL (Short)', plan['entry'], plan['sl'], plan['tp'], f"{reason} | {plan_reason}")
    if ok: return _entry_diag_result(chat_id, symbol, 'entry_opened', 'موفق', 'entry', sig)
    return _entry_diag_result(chat_id, symbol, 'execute_blocked', 'خطای اجرا', 'execute', sig)


def performance_period_report(chat_id, period='all'):
    s = get_session(chat_id)
    closed = list(s.get('closed_positions') or [])
    n = len(closed); pnls = [float(p.get('pnl_usdt', 0) or 0) for p in closed]
    net = sum(pnls)
    return f'📊 *گزارش عملکرد*\n\nمعاملات بسته‌شده: `{n}`\nسود/زیان خالص: `{net:+.2f} USDT`'


def trade_audit_report(chat_id):
    return '🔎 ممیزی معامله ثبت نشد.'


def export_trade_data(chat_id): return True


def reset_stats(chat_id):
    s = get_session(chat_id); s['closed_positions'] = []; save_session(chat_id)
    return True, '✅ آمار ریست شد.'


def analyze(chat_id, symbol):
    return f"🔍 تحلیل {symbol}", {'inline_keyboard': [[{'text':'🏠 منوی اصلی', 'callback_data':'/menu'}]]}


def menu(chat_id, message_id=None):
    s = get_session(chat_id)
    text = f"📊 *پنل اصلی ربات*\n\n🟢 اسکن: `{'فعال' if s['is_bot_active'] else 'متوقف'}`\n💰 موجودی: `{s['paper_balance']:.2f} USDT`"
    send_message(chat_id, text, get_main_menu_keyboard(s['is_bot_active'], s.get('entry_diag_enabled', True)), message_id)


def stop_scan(chat_id, reason='manual'):
    s = get_session(chat_id)
    with STATE_LOCK:
        s['scan_generation'] = int(s.get('scan_generation', 0)) + 1
        s['is_bot_active'] = False
    save_session(chat_id)
    return s


def start_scan(chat_id, message_id=None):
    s = get_session(chat_id)
    with get_entry_lock(chat_id):
        s['scan_generation'] = int(s.get('scan_generation', 0)) + 1
        s['is_bot_active'] = True
        save_session(chat_id)
    menu(chat_id, message_id)
    sync_bottom_keyboard(chat_id, "🟢 اسکن فعال شد.")


def reload_and_restart_scan(chat_id, message_id=None):
    try:
        s = get_session(chat_id)
        s['strategy_config'] = get_timeframe_preset(s.get('timeframe', '5min'))
        save_session(chat_id)
        start_scan(chat_id, message_id)
        send_message(chat_id, "🔄 تنظیمات استراتژی بازسازی شد.")
    except Exception as exc:
        send_message(chat_id, f"❌ خطا: `{exc}`")


def market_report(chat_id):
    return "🌐 *داشبورد بازار*\nوضعیت عادی است."


def runtime_audit(chat_id):
    s = get_session(chat_id)
    return f'🧪 اسکن: `{"فعال" if s.get("is_bot_active") else "متوقف"}`'


def process_command(cmd, chat_id, message_id=None):
    if str(cmd).startswith('/set_fee '):
        admin_set_fee_command(chat_id, cmd); return
    if cmd in ('/admin_fee_report','/admin_fee_day','/admin_fee_week','/admin_fee_month'):
        if not is_admin(chat_id): send_message(chat_id,'⛔ دسترسی ادمین ندارید.'); return
        period = {'/admin_fee_report':'all','/admin_fee_day':'day','/admin_fee_week':'week','/admin_fee_month':'month'}[cmd]
        send_message(chat_id, admin_fee_report(period), parse_mode='Markdown'); return
    if cmd == '/users':
        if not is_admin(chat_id): send_message(chat_id,'⛔ دسترسی ادمین ندارید.'); return
        send_message(chat_id, admin_users_report(), parse_mode='Markdown'); return
    if cmd in ('/my_fees','/my_fee_report'):
        send_message(chat_id, fee_report(chat_id,'all'), parse_mode='Markdown'); return
    if cmd in ('performance','report','📈 گزارش عملکرد کلی'):
        send_message(chat_id, performance_period_report(chat_id, 'all'), get_performance_keyboard()); return
    
    s = get_session(chat_id); c = (cmd or '').strip(); cl = c.lower()
    if cl == '/start':
        if s.get('is_bot_active'): stop_scan(chat_id)
        send_message(chat_id, '🤖 ربات معامله‌گر', get_start_keyboard()); return
    if cl in ('/menu','☰ منو','🏠 منوی اصلی'): menu(chat_id, message_id); return
    if cl == '/cancel': menu(chat_id, message_id); return
    if cl in ('/stop_scan',) or c in ('🔴 توقف اسکن','توقف اسکن'):
        stop_scan(chat_id); menu(chat_id, message_id); return
    if cl in ('/start_scan',) or c in ('🟢 شروع اسکن','شروع اسکن'): start_scan(chat_id, message_id); return
    if cl == '/reload_and_start': reload_and_restart_scan(chat_id, message_id); return
    if cl == '/market_report': send_message(chat_id, market_report(chat_id)); return
    if cl == '/entry_diag':
        enabled = s.get('entry_diag_enabled', True)
        edit_page(chat_id, f"🔍 وضعیت لاگ تشخیصی: {'🟢 فعال' if enabled else '🔴 خاموش'}", get_entry_diag_keyboard(enabled), message_id); return
    if cl == '/toggle_entry_diag':
        s['entry_diag_enabled'] = not s.get('entry_diag_enabled', True)
        save_session(chat_id)
        edit_page(chat_id, f"🔍 لاگ تشخیصی: {'🟢 فعال شد' if s['entry_diag_enabled'] else '🔴 خاموش شد'}", get_entry_diag_keyboard(s['entry_diag_enabled']), message_id); return
    if cl == '/open_positions' or 'پوزیشن‌های باز' in c:
        _send_or_edit_positions_view(chat_id, message_id=message_id); return
    if cl.startswith('/confirm_close_') and cl not in ('/confirm_close_all','/confirm_close_longs','/confirm_close_shorts'):
        sym = cl.replace('/confirm_close_', '').upper()
        for p in s['paper_positions'][:]:
            if p['symbol'] == sym: close_position(chat_id, p, reason='manual'); return
    if cl == '/confirm_close_all':
        stop_scan(chat_id)
        for p in s['paper_positions'][:]: close_position(chat_id, p, reason='close_all')
        menu(chat_id); return


def handle_text(chat_id, text):
    raw = (text or '').strip()
    fixed_buttons = {
        '🏠 منوی اصلی':'/menu', 'منوی اصلی':'/menu',
        '🔄 پوزیشن‌های باز':'/open_positions', 'پوزیشن‌های باز':'/open_positions',
        '📊 وضعیت بازار':'/market_report', 'وضعیت بازار':'/market_report',
        '🆘 بستن اضطراری همه':'/close_all_prompt', 'بستن اضطراری همه':'/close_all_prompt',
    }
    if raw in fixed_buttons: process_command(fixed_buttons[raw], chat_id); return
    process_command(text, chat_id)


def telegram_listener():
    global TELEGRAM_OFFSET
    while True:
        if not TELEGRAM_TOKEN: time.sleep(5); continue
        try:
            params = {'timeout': 25}
            if TELEGRAM_OFFSET > 0: params['offset'] = TELEGRAM_OFFSET
            r = requests.get(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates', params=params, timeout=30)
            if not r.ok: time.sleep(2); continue
            for u in r.json().get('result', []):
                upd = int(u.get('update_id', 0))
                save_telegram_offset(upd + 1)
                try:
                    callback = u.get('callback_query') or {}
                    msg = callback.get('message') or u.get('message') or {}
                    chat = (msg.get('chat') or {}).get('id')
                    telegram_user = callback.get('from') or (u.get('message') or {}).get('from') or {}
                    if not chat: continue
                    upsert_telegram_user(telegram_user, chat)
                    if callback.get('id'): answer_callback(callback['id'])
                    if not is_allowed(chat): continue
                    data = callback.get('data') or (u.get('message') or {}).get('text')
                    if callback: process_command(data, chat, msg.get('message_id'))
                    elif data: handle_text(chat, data)
                except Exception: pass
        except Exception: time.sleep(2)


async def scan_loop():
    global ASYNC_SEMAPHORE
    ASYNC_SEMAPHORE = asyncio.Semaphore(MAX_ASYNC_REQUESTS)
    while True:
        try:
            for cid, s in list(USER_SESSIONS.items()): update_positions(cid)
            timeout = aiohttp.ClientTimeout(total=10)
            conn = aiohttp.TCPConnector(limit=MAX_ASYNC_REQUESTS, ttl_dns_cache=300)
            async with aiohttp.ClientSession(timeout=timeout, connector=conn) as http:
                tasks = []
                for cid, s in list(USER_SESSIONS.items()):
                    if not s['is_bot_active'] or s['daily_stopped']: continue
                    if not risk_guard(cid): continue
                    watchlist = scan_watchlist_for_timeframe(s.get('timeframe', '5min'))
                    for sym in watchlist:
                        tasks.append(scan_symbol(http, cid, sym))
                if tasks:
                    batch = await asyncio.gather(*tasks, return_exceptions=True)
                    by_chat = {}
                    for item in batch:
                        if isinstance(item, dict) and item.get('chat_id') is not None:
                            by_chat.setdefault(item['chat_id'], []).append(item)
                    for cid, results in by_chat.items():
                        _entry_diag_batch_update(cid, results)
        except Exception: pass
        await asyncio.sleep(SCAN_INTERVAL_SECONDS)


@app.get('/')
def home(): return f"OK - Sessions: {len(USER_SESSIONS)}", 200
@app.get('/health')
def health(): return 'OK', 200


def main():
    init_db()
    migrate_legacy_sqlite_to_postgres()
    load_telegram_offset()
    load_sessions()
    configure_telegram_native_menu()
    Thread(target=telegram_listener, daemon=True, name='telegram').start()
    Thread(target=lambda: (time.sleep(3), asyncio.run(scan_loop())), daemon=True, name='scanner').start()
    app.run(host='0.0.0.0', port=PORT, threaded=True)


if __name__ == '__main__':
    main()
