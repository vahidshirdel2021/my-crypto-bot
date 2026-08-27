import hashlib
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

try:
    from strategy import (
        evaluate_scenarios,
        compute_swing_stop,
        calculate_indicators,
        compute_prev_day_levels,
        compute_prev_week_levels,
        FILTER_DEFAULTS,
        STRATEGY_DEFAULTS
    )
except ImportError:
    # ایمپورت امن برای جلوگیری از کرش ربات
    pass
from ui import (
    get_start_keyboard, get_balance_keyboard, get_margin_keyboard, get_leverage_keyboard,
    get_max_positions_keyboard, get_timeframe_keyboard, get_main_menu_keyboard,
    get_watchlist_manage_keyboard,
    get_params_menu_keyboard, get_positions_keyboard,
    get_bottom_menu_keyboard, get_confirm_close_all_keyboard, get_learn_menu_keyboard,
    get_confirm_emergency_close_keyboard,
    get_performance_keyboard, get_entry_diag_keyboard, get_manual_side_keyboard,
    get_confirm_close_longs_keyboard, get_confirm_close_shorts_keyboard,
    get_fee_menu_keyboard, get_admin_panel_keyboard, get_admin_fee_menu_keyboard,
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
POSITION_MANAGEMENT_EARLY_LOSS_R = -0.10


def _seconds_to_local_day_end():
    tz = None
    if ZoneInfo is not None:
        try:
            tz = ZoneInfo(DAILY_CLOSE_TZ)
        except Exception:
            tz = None
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
ADMIN_CHAT_IDS.update({115981067, 8621862979, 1878257830, 8714168271})
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
TIMEFRAME_MAP = {'1min':'1min','5min':'5min','15min':'15min','1hour':'1hour','4hour':'4hour','1day':'1day'}
TF_DISPLAY = {'5min':'5م','15min':'15م','1hour':'1س','4hour':'4س','1day':'روزانه'}

LONG_WATCHLIST = ['ATOM','BCH','AVAX','UNI','HOT','FIL','ANKR','DOT','THETA','LINK','BNB','SHIB','TRX','DASH','BTT','QTUM','ADA','ZEC','CRV','GALA','EGLD','NEAR','WAVES','RUNE','KSM','HNT','DYDX','ETC','STORJ']
WINNING_WATCHLISTS = {tf: LONG_WATCHLIST for tf in ('5min', '15min', '1hour', '4hour')}
SUPPORTED_TRADING_TIMEFRAMES = tuple(WINNING_WATCHLISTS.keys())

SHORT_WATCHLIST = ['IOTA','ALGO','MASK','NEO','UNI','STORJ','BTC','DASH','RUNE','COMP','BNB','ONE','GALA','AR','LUNA','MANA','ETH','ETC','SOL','SUSHI','LINK','SKL','CHZ','TRB','EGLD','BTT','VET','NEAR','SLP','ANKR','ADA','ZIL','BCH','AAVE','DYDX','RVN','SHIB','TRX','ATOM','ENJ','WAVES','ZEC','XTZ','AVAX','AXS','SNX','SAND','RSR','ZRX','RAY','QTUM']
WINNING_SHORT_WATCHLISTS = {tf: SHORT_WATCHLIST for tf in ('5min', '15min', '1hour', '4hour')}

SHARED_LONG_WATCHLIST = LONG_WATCHLIST
SHARED_SHORT_WATCHLIST = SHORT_WATCHLIST
LEADER_SYMBOLS = ('BTC','ETH')
COINEX_PUBLIC = 'https://api.coinex.com/v2'
KUCOIN_PUBLIC = 'https://api.kucoin.com/api/v1'

DEX_WATCHLIST_ENABLED = os.environ.get('DEX_WATCHLIST_ENABLED', 'true').lower() not in ('0','false','no')
DEX_WATCHLIST_SIZE = max(20, int(os.environ.get('DEX_WATCHLIST_SIZE', '100')))
DEX_WATCHLIST_REFRESH_SECONDS = max(300, int(os.environ.get('DEX_WATCHLIST_REFRESH_SECONDS', '1800')))
DEX_CANDIDATE_SYMBOLS = {
    'BTC','ETH','BNB','SOL','XRP','DOGE','ADA','TRX','AVAX','LINK','DOT','TON','SUI','SHIB','LTC',
    'BCH','UNI','AAVE','NEAR','APT','ARB','OP','INJ','ATOM','FIL','ETC','XLM','HBAR','ICP','CRO',
    'ALGO','VET','MKR','QNT','EGLD','TIA','SEI','STX','IMX','RUNE','JUP','WIF','PEPE','BONK','ENA',
    'ONDO','JTO','PYTH','JASMY','TAO','FET','RENDER','THETA','GRT','SAND','MANA','AXS','APE','CRV',
    'SNX','DYDX','GMX','LDO','RPL','PENDLE','COMP','MKR','RAY','JTO','WLD','STRK','ZK','ZRO','POL',
    'FLOW','XTZ','KAS','AR','MINA','KAVA','ROSE','ONE','ZEC','DASH','NEO','IOTA','KSM','WAVES','RUNE',
    'RLC','ANKR','CHZ','ENJ','GALA','MASK','STORJ','ZIL','RSR','ZRX','SKL','RVN','HNT','SUSHI','YGG',
    'BLUR','MEME','MANTA','ALT','DYM','ORDI','SATS','1000SATS','MEW','POPCAT','TURBO','FLOKI','BRETT',
    'JUP','APT','SUI','SEI','TIA','INJ','TON','NEAR','ARB','OP','WIF','PEPE','BONK'
}
DEX_WATCHLIST_CACHE = {'ts': 0.0, 'symbols': [], 'source': 'fallback', 'tiers': {}}

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format='%(asctime)s | %(levelname)s | %(threadName)s | %(message)s')
logger = logging.getLogger('trader_bot')
app = Flask(__name__)
STATE_LOCK = RLock()
DB_LOCK = RLock()
DATA_LOCK = RLock()
USER_SESSIONS: Dict[int, Dict[str, Any]] = {}
ENTRY_DIAG_STATE: Dict[int, Dict[str, Any]] = {}
HEARTBEAT_LAST_SENT: Dict[int, float] = {}
HEARTBEAT_INTERVAL_SECONDS = 600.0
HEARTBEAT_TEXT = '🤖 ربات معاملاتی فعال و درحال اسکن بازار و فرصت یابی می باشد'
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
            conn.execute('CREATE TABLE IF NOT EXISTS sessions(chat_id INTEGER PRIMARY KEY, data TEXT NOT NULL, updated_at INTEGER NOT NULL)')
            conn.execute('CREATE TABLE IF NOT EXISTS bot_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at INTEGER NOT NULL)')
            conn.execute('''CREATE TABLE IF NOT EXISTS fee_ledger(
                id %s,
                trade_id TEXT NOT NULL UNIQUE,
                chat_id INTEGER NOT NULL,
                mode TEXT NOT NULL,
                gross_pnl_usdt %s NOT NULL DEFAULT 0,
                trading_cost_usdt %s NOT NULL DEFAULT 0,
                net_profit_before_platform_fee_usdt %s NOT NULL DEFAULT 0,
                fee_rate_pct %s NOT NULL DEFAULT 0,
                platform_fee_usdt %s NOT NULL DEFAULT 0,
                user_net_profit_usdt %s NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'SETTLED',
                created_at %s NOT NULL,
                settled_at %s
            )''' % ((fee_id_type,) + (real_type,)*8))
            conn.execute('''CREATE TABLE IF NOT EXISTS user_fee_settings(
                chat_id INTEGER PRIMARY KEY,
                fee_rate_pct %s NOT NULL,
                updated_at INTEGER NOT NULL
            )''' % real_type)
            conn.execute('''CREATE TABLE IF NOT EXISTS users(
                chat_id INTEGER PRIMARY KEY,
                telegram_user_id INTEGER,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                first_seen INTEGER NOT NULL,
                last_seen INTEGER NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            )''')
            conn.commit()
        finally:
            conn.close()
    if DB_BACKEND == 'postgres':
        logger.info('Database backend: PostgreSQL (remote/Neon compatible)')
    else:
        if not os.environ.get('BOT_DB_PATH', '').strip():
            logger.warning('هشدار ماندگاری داده: BOT_DB_PATH تنظیم نشده؛ دیتابیس روی مسیر پیش‌فرض محلی (%s) ذخیره می‌شود.', DB_PATH)
        if not db_existed_before:
            logger.warning('فایل دیتابیس (%s) از صفر ساخته شد.', DB_PATH)


def _sqlite_table_exists(conn, table_name):
    try:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)).fetchone()
        return bool(row)
    except Exception:
        return False


def migrate_legacy_sqlite_to_postgres():
    if DB_BACKEND != 'postgres':
        return
    legacy_path = os.environ.get('LEGACY_SQLITE_PATH', DB_PATH).strip() or DB_PATH
    if not os.path.exists(legacy_path):
        return
    with DB_LOCK:
        pg = db_connect()
        try:
            marker = pg.execute("SELECT value FROM bot_meta WHERE key=?", ('sqlite_migration_v1',)).fetchone()
            if marker and str(marker[0]).lower() in ('done','completed'):
                return
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
                        if existing:
                            pg.execute('UPDATE sessions SET data=?,updated_at=? WHERE chat_id=?', (r['data'], int(r['updated_at']), int(r['chat_id'])))
                        else:
                            pg.execute('INSERT INTO sessions(chat_id,data,updated_at) VALUES(?,?,?)', (int(r['chat_id']), r['data'], int(r['updated_at'])))
                if _sqlite_table_exists(src, 'fee_ledger'):
                    cols = ['id','trade_id','chat_id','mode','gross_pnl_usdt','trading_cost_usdt','net_profit_before_platform_fee_usdt','fee_rate_pct','platform_fee_usdt','user_net_profit_usdt','status','created_at','settled_at']
                    for r in src.execute('SELECT '+','.join(cols)+' FROM fee_ledger').fetchall():
                        vals=[r[c] for c in cols]
                        try:
                            pg.execute("""INSERT INTO fee_ledger(id,trade_id,chat_id,mode,gross_pnl_usdt,trading_cost_usdt,net_profit_before_platform_fee_usdt,fee_rate_pct,platform_fee_usdt,user_net_profit_usdt,status,created_at,settled_at)
                                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(trade_id) DO NOTHING""", vals)
                        except Exception:
                            pass
                if _sqlite_table_exists(src, 'user_fee_settings'):
                    for r in src.execute('SELECT chat_id,fee_rate_pct,updated_at FROM user_fee_settings').fetchall():
                        pg.execute("""INSERT INTO user_fee_settings(chat_id,fee_rate_pct,updated_at) VALUES(?,?,?)
                            ON CONFLICT(chat_id) DO UPDATE SET fee_rate_pct=excluded.fee_rate_pct,updated_at=excluded.updated_at
                            WHERE excluded.updated_at > user_fee_settings.updated_at""", (int(r['chat_id']), float(r['fee_rate_pct']), int(r['updated_at'])))
                if _sqlite_table_exists(src, 'users'):
                    for r in src.execute('SELECT chat_id,telegram_user_id,username,first_name,last_name,first_seen,last_seen,is_active FROM users').fetchall():
                        pg.execute("""INSERT INTO users(chat_id,telegram_user_id,username,first_name,last_name,first_seen,last_seen,is_active)
                            VALUES(?,?,?,?,?,?,?,?)
                            ON CONFLICT(chat_id) DO UPDATE SET
                                telegram_user_id=COALESCE(EXCLUDED.telegram_user_id,users.telegram_user_id),
                                username=COALESCE(EXCLUDED.username,users.username),
                                first_name=COALESCE(EXCLUDED.first_name,users.first_name),
                                last_name=COALESCE(EXCLUDED.last_name,users.last_name),
                                first_seen=LEAST(users.first_seen,EXCLUDED.first_seen),
                                last_seen=GREATEST(users.last_seen,EXCLUDED.last_seen),
                                is_active=EXCLUDED.is_active""", (int(r['chat_id']), r['telegram_user_id'], r['username'], r['first_name'], r['last_name'], int(r['first_seen']), int(r['last_seen']), int(r['is_active'])))
                if _sqlite_table_exists(src, 'bot_meta'):
                    for r in src.execute('SELECT key,value,updated_at FROM bot_meta').fetchall():
                        existing=pg.execute('SELECT updated_at FROM bot_meta WHERE key=?',(r['key'],)).fetchone()
                        if not existing:
                            pg.execute('INSERT INTO bot_meta(key,value,updated_at) VALUES(?,?,?)',(r['key'],r['value'],int(r['updated_at'])))
                pg.execute("SELECT setval(pg_get_serial_sequence('fee_ledger','id'), COALESCE((SELECT MAX(id) FROM fee_ledger),1), true)")
                pg.execute("INSERT INTO bot_meta(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at", ('sqlite_migration_v1','done',int(time.time())))
                pg.commit()
            except Exception:
                pg.rollback()
                raise
            finally:
                src.close()
        finally:
            pg.close()

def upsert_telegram_user(user, chat_id=None):
    if not user:
        return
    try:
        uid = int(user.get('id') or chat_id)
        cid = int(chat_id if chat_id is not None else uid)
    except Exception:
        return
    username = str(user.get('username') or '').strip() or None
    first_name = str(user.get('first_name') or '').strip() or None
    last_name = str(user.get('last_name') or '').strip() or None
    now = int(time.time())
    with DB_LOCK:
        conn = db_connect()
        try:
            conn.execute('PRAGMA busy_timeout=15000')
            conn.execute('''INSERT INTO users(chat_id,telegram_user_id,username,first_name,last_name,first_seen,last_seen,is_active)
                VALUES(?,?,?,?,?,?,?,1)
                ON CONFLICT(chat_id) DO UPDATE SET
                    telegram_user_id=excluded.telegram_user_id,
                    username=COALESCE(excluded.username, users.username),
                    first_name=COALESCE(excluded.first_name, users.first_name),
                    last_name=COALESCE(excluded.last_name, users.last_name),
                    last_seen=excluded.last_seen,
                    is_active=1''',
                (cid, uid, username, first_name, last_name, now, now))
            conn.commit()
        finally:
            conn.close()

def mark_stale_users(days=30):
    cutoff = int(time.time()) - int(days * 86400)
    with DB_LOCK:
        conn = db_connect()
        try:
            conn.execute('PRAGMA busy_timeout=15000')
            conn.execute('UPDATE users SET is_active=0 WHERE last_seen < ?', (cutoff,))
            conn.commit()
        finally:
            conn.close()

def admin_users_report(limit=100):
    if not USER_SESSIONS and DB_BACKEND == 'sqlite' and not os.path.exists(DB_PATH):
        return '👥 *کاربران ربات*\n\nهنوز کاربری ثبت نشده است.'
    mark_stale_users(30)
    with DB_LOCK:
        conn=db_connect()
        try:
            rows=conn.execute('''SELECT u.chat_id,u.username,u.first_name,u.last_name,u.first_seen,u.last_seen,u.is_active,
                    (SELECT COUNT(*) FROM fee_ledger f WHERE f.chat_id=u.chat_id) AS fee_trades,
                    (SELECT COALESCE(SUM(f.platform_fee_usdt),0) FROM fee_ledger f WHERE f.chat_id=u.chat_id) AS fee_total
                FROM users u ORDER BY u.last_seen DESC LIMIT ?''',(int(limit),)).fetchall()
        finally:
            conn.close()
    if not rows:
        return '👥 *کاربران ربات*\n\nهنوز کاربری ثبت نشده است.'
    active=sum(1 for r in rows if r[6])
    lines=[f'👥 *کاربران ربات*', '', f'• تعداد نمایش‌داده‌شده: `{len(rows)}`', f'• فعال در ۳۰ روز اخیر: `{active}`', '', '*فهرست:*']
    for i,(cid,username,first,last,first_seen,last_seen,is_active,fee_trades,fee_total) in enumerate(rows,1):
        name=' '.join(x for x in (first,last) if x) or 'بدون نام'
        uname=f'@{username}' if username else 'بدون username'
        status='🟢' if is_active else '⚪️'
        last_txt=time.strftime('%Y-%m-%d %H:%M', time.localtime(last_seen))
        lines.append(f'{status} `{i}` {name} — `{uname}`\n   ID: `{cid}` | آخرین فعالیت: `{last_txt}` | کارمزد: `{fee_total:.2f}` USDT ({fee_trades})')
    return '\n'.join(lines)

def admin_user_detail(chat_id, target_id):
    with DB_LOCK:
        conn=db_connect()
        try:
            row=conn.execute('SELECT chat_id,telegram_user_id,username,first_name,last_name,first_seen,last_seen,is_active FROM users WHERE chat_id=?',(int(target_id),)).fetchone()
            fee=conn.execute('SELECT COALESCE(SUM(platform_fee_usdt),0),COUNT(*) FROM fee_ledger WHERE chat_id=?',(int(target_id),)).fetchone()
        finally:
            conn.close()
    if not row:
        return f'❌ کاربری با ID `{target_id}` در رجیستری پیدا نشد.'
    cid,uid,username,first,last,first_seen,last_seen,is_active=row
    fee_total,fee_count=fee or (0,0)
    name=' '.join(x for x in (first,last) if x) or 'بدون نام'
    uname=f'@{username}' if username else 'بدون username'
    return (f'👤 *پروفایل کاربر*\n\nنام: `{name}`\nUsername: `{uname}`\nChat ID: `{cid}`\nTelegram ID: `{uid}`\n'
            f'اولین فعالیت: `{time.strftime("%Y-%m-%d %H:%M", time.localtime(first_seen))}`\n'
            f'آخرین فعالیت: `{time.strftime("%Y-%m-%d %H:%M", time.localtime(last_seen))}`\n'
            f'وضعیت: `{"فعال" if is_active else "غیرفعال"}`\n'
            f'نرخ کارمزد فعلی: `{get_user_fee_rate(target_id):.2f}%`\n'
            f'کارمزد ثبت‌شده: `{fee_total:.2f} USDT` در `{fee_count}` معامله')


def save_session(chat_id):
    with STATE_LOCK:
        data = USER_SESSIONS.get(chat_id)
        if data is None: return
        payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'), default=json_default)
    with DB_LOCK:
        conn = db_connect()
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
        'fee_usdt': p.get('fee_usdt'), 'platform_fee_usdt': p.get('platform_fee_usdt'), 'platform_fee_rate_pct': p.get('platform_fee_rate_pct'), 'pnl_before_platform_fee_usdt': p.get('pnl_before_platform_fee_usdt'), 'pnl_gross_usdt': p.get('pnl_gross_usdt'),
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
        conn = db_connect()
        try:
            row = conn.execute('SELECT value FROM bot_meta WHERE key=?', ('telegram_offset',)).fetchone()
        finally:
            conn.close()
    try:
        TELEGRAM_OFFSET = max(0, int(row[0])) if row else 0
    except Exception:
        TELEGRAM_OFFSET = 0


def save_telegram_offset(offset):
    global TELEGRAM_OFFSET
    TELEGRAM_OFFSET = max(0, int(offset))
    with DB_LOCK:
        conn = db_connect()
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
        'max_same_direction_positions': 2,
        'same_direction_entry_cooldown_seconds': 900,
        'timeframe': '5min',
        'active_strategy': 'dynamic',
        'paper_positions': [],
        'closed_positions': [],
        'trade_audit': [],
        'scan_stats': {'scans': 0, 'symbols': 0, 'signals': 0, 'entries': 0, 'blocked': 0, 'data_errors': 0, 'reason_counts': {}},
        'cooldowns': {},
        'traded_levels': {},
        'user_state': None,
        'active_symbols': (PAPER_SYMBOLS[:] if PAPER_ONLY else DEFAULT_ACTIVE_SYMBOLS[:]),
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
        'trade_pipeline_enabled': False,
        'trade_pipeline_audit': [],
        'platform_fee_rate_pct': PLATFORM_FEE_RATE_PCT,
        'platform_fee_total_usdt': 0.0,
        'platform_fee_trade_count': 0,
        'positions_message_id': None,
        'positions_message_last_edit': 0.0,
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
    if PAPER_ONLY:
        s['active_symbols'] = PAPER_SYMBOLS[:]
    elif not stored_symbols or set(stored_symbols) == set(LEGACY_DEFAULT_ACTIVE_SYMBOLS):
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
    s['trade_pipeline_enabled'] = bool(s.get('trade_pipeline_enabled', False))
    s['trade_pipeline_audit'] = list(data.get('trade_pipeline_audit') or [])[-5000:]
    s['platform_fee_rate_pct'] = min(100.0, max(0.0, float(s.get('platform_fee_rate_pct', PLATFORM_FEE_RATE_PCT))))
    s['platform_fee_total_usdt'] = max(0.0, float(s.get('platform_fee_total_usdt', 0.0)))
    s['platform_fee_trade_count'] = max(0, int(s.get('platform_fee_trade_count', 0) or 0))
    return s


def load_sessions():
    with DB_LOCK:
        conn = db_connect()
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
    except Exception as exc: logger.debug('price %s',symbol,exc)
    return None


def exchange_latest_price(chat_id, symbol):
    key=f'{chat_id}:{symbol.upper()}'; now=time.time()
    with DATA_LOCK:
        c=REAL_PRICE_CACHE.get(key)
        if c and now-c['ts']<3: return c['price']
    ex=get_exchange(chat_id)
    if not ex: return None
    try:
        ticker=ex.fetch_ticker(ccxt_symbol(symbol))
        price=float(ticker.get('last') or ticker.get('mark') or ticker.get('close') or 0)
        if price>0:
            with DATA_LOCK: REAL_PRICE_CACHE[key]={'ts':now,'price':price}
            return price
    except Exception as exc:
        logger.debug('exchange price chat=%s symbol=%s: %s',chat_id,symbol,exc)
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


PROFIT_LADDERS_R = {
    '5min':  [(0.50, 0.00), (0.75, 0.15), (1.00, 0.30), (1.25, 0.50), (1.50, 0.75), (2.00, 1.10)],
    '15min': [(0.75, 0.00), (1.00, 0.15), (1.50, 0.50), (2.00, 1.00), (2.50, 1.50), (3.00, 2.00)],
    '1hour': [(1.00, 0.00), (1.50, 0.50), (2.00, 1.00), (3.00, 1.75), (4.00, 2.50)],
    '4hour': [(1.25, 0.00), (2.00, 0.50), (3.00, 1.50), (4.00, 2.50), (5.00, 3.50)],
}

def trailing_locked_r(entry, risk_distance, current_price, is_long, timeframe=None):
    try:
        entry=float(entry); risk_distance=float(risk_distance); current_price=float(current_price)
    except Exception:
        return None
    if risk_distance<=0 or not math.isfinite(risk_distance): return None
    r=(current_price-entry)/risk_distance if is_long else (entry-current_price)/risk_distance
    ladder=PROFIT_LADDERS_R.get(str(timeframe or ''), [(1.0,0.0),(1.5,0.5),(2.0,1.0),(2.5,1.5)])
    locked=None
    for trigger,lock in ladder:
        if r >= trigger:
            locked=lock
        else:
            break
    return locked


def _apply_profit_protection(chat_id, s, p, favorable_price, current_price=None):
    try:
        entry=float(p['entry_price'])
        risk_distance=float(p.get('risk_distance') or 0.0)
        if risk_distance <= 0:
            risk_distance=abs(entry-float(p.get('sl', entry)))
        if risk_distance <= 0:
            return False
        is_long=side_long(p['side'])
        probe=float(favorable_price if favorable_price is not None else current_price)
        tf=str(p.get('timeframe') or '')
        peak_price=p.get('peak_favorable_price')
        peak_probe=float(peak_price) if peak_price is not None else probe
        lr=trailing_locked_r(entry,risk_distance,peak_probe,is_long,tf)
        if lr is not None:
            proposed=entry+(lr*risk_distance if is_long else -lr*risk_distance)
            if (is_long and proposed > float(current_price)) or ((not is_long) and proposed < float(current_price)):
                lr=None
        if lr is None:
            return False
        new_sl=entry+(lr*risk_distance if is_long else -lr*risk_distance)
        old_sl=float(p['sl'])
        is_better=(new_sl>old_sl) if is_long else (new_sl<old_sl)
        locked=float(p.get('trailing_locked_r') or 0.0)
        first_activation=not bool(p.get('trailing_activated'))
        if not is_better or not (lr>locked or (first_activation and lr>=locked)):
            return False
        if p.get('is_real'):
            ok,err=move_stop_loss(chat_id,p['symbol'],normalize_price(chat_id,p['symbol'],new_sl))
            if not ok:
                return False
        p['sl']=new_sl
        p['trailing_activated']=True
        p['trailing_locked_r']=lr
        if first_activation or lr>locked:
            send_message(chat_id, f"🛡️ مدیریت سود فعال شد: `{p['symbol']}`\n• قفل سود: `{lr:.1f}R`\n• حد ضرر جدید: `{fmt(new_sl)}`")
        return True
    except Exception:
        return False


def _check_swing_trailing_stop(chat_id, s, p, price, sdf=None):
    try:
        tf = p.get('timeframe', '5min')
        if sdf is None:
            sdf = get_klines(p['symbol'], tf, 100)
        if sdf.empty:
            return
        sdf = calculate_indicators(sdf)
        if sdf.empty or 'atr' not in sdf.columns:
            return
        is_long = side_long(p['side'])
        cfg = s.get('strategy_config') or STRATEGY_DEFAULTS
        lookback_n = int(cfg.get('swing_lookback', 12))
        confirm_n = int(cfg.get('swing_confirm_candles', 2))
        buffer_atr = float(cfg.get('swing_buffer_atr', 0.40))
        new_sl, swing_level = compute_swing_stop(sdf, is_long, lookback_n, buffer_atr, confirm_n)
        if new_sl is None or swing_level is None:
            return
        cur_sl = float(p['sl'])
        if is_long:
            behind_price = new_sl < price
            improved = new_sl > cur_sl
        else:
            behind_price = new_sl > price
            improved = new_sl < cur_sl
        if not (behind_price and improved):
            return
        prev_level = p.get('swing_sl_level')
        if prev_level is not None and math.isclose(swing_level, prev_level, rel_tol=1e-9, abs_tol=1e-9):
            return
        if p.get('is_real'):
            ok, err = move_stop_loss(chat_id, p['symbol'], normalize_price(chat_id, p['symbol'], new_sl))
            if not ok:
                return
        old_sl = cur_sl
        p['sl'] = new_sl
        p['swing_sl_level'] = swing_level
        p['trailing_activated'] = True
        send_message(chat_id, f"🔄 استاپ‌لاس *{p['symbol']}* به‌دلیل تشکیل سوینگ جدید تغییر کرد\n• قبلی: `{fmt(old_sl)}`\n• جدید: `{fmt(new_sl)}`")
    except Exception:
        pass


def _maybe_close_before_day_end(chat_id, p, price):
    tf = p.get('timeframe', '5min')
    if tf not in NO_OVERNIGHT_TIMEFRAMES:
        return False
    if _seconds_to_local_day_end() > SCAN_INTERVAL_SECONDS:
        return False
    close_position(chat_id, p, price, 'پایان روز - بستن اجباری (معاملات ۵ و ۱۵ دقیقه هرگز به روز بعد منتقل نمی‌شوند)')
    return True


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
    except Exception: return None


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
    except ExchangeStateError:
        return 0,'account state unavailable'
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


TV_INTERVAL_MAP = {'5min': '5', '15min': '15', '1hour': '60', '4hour': '240', '1day': 'D'}


def tradingview_chart_url(symbol, timeframe='5min'):
    sym = symbol.upper().replace('USDT', '').replace('/', '')
    interval = TV_INTERVAL_MAP.get(timeframe, '15')
    tv_symbol = urlparse.quote(f'COINEX:{sym}USDT.P', safe='')
    return f'https://www.tradingview.com/chart/?symbol={tv_symbol}&interval={interval}'


def trade_action_keyboard(symbol, chart_url=None, timeframe='5min'):
    rows = []
    if chart_url:
        rows.append([{'text':'🌐 چارت تعاملی (MiniApp)','web_app':{'url':chart_url}}])
    rows.append([
        {'text':'📈 چارت در TradingView','url':tradingview_chart_url(symbol, timeframe)}
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
            trade_action_keyboard(symbol, miniapp_chart_url(symbol, tf), tf)
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


def _execute_trade_unlocked(chat_id,symbol,side,signal_price,sl,tp,reason='',generation=None,require_active=True,structural_tp=False,swing_level=None,swing_sl_buffer=None):
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
    setup_source = f"{symbol}|{side}|{s.get('timeframe')}|{signal_price:.12g}|{sl:.12g}|{tp:.12g}|{reason}"
    setup_id = hashlib.sha256(setup_source.encode('utf-8')).hexdigest()[:24]
    if any(str(p.get('setup_id') or '') == setup_id for p in s.get('paper_positions', [])):
        return False
    if setup_id in set(s.get('consumed_setups') or []):
        return False
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
    same_ok, same_reason = _same_direction_guard_allows(s, side, quality_score, planned_rr)
    if not same_ok:
        audit_event(chat_id, trade_id, 'same_direction_guard', {'allowed': False, 'reason': same_reason, 'score': quality_score, 'rr': planned_rr})
        return False
    audit_event(chat_id, trade_id, 'same_direction_guard', {'allowed': True, 'reason': same_reason, 'score': quality_score, 'rr': planned_rr})
    audit_event(chat_id, trade_id, 'signal_and_plan', {
        'symbol': symbol, 'side': side, 'signal_price': signal_price, 'sl': sl, 'tp': tp,
        'reason': reason, 'setup_id': setup_id, 'timeframe': s.get('timeframe'),
        'strategy': s.get('active_strategy'), 'quality_score': quality_score,
        'quality_label': quality_label, 'planned_rr': planned_rr
    })

    price=latest_price(symbol) or float(signal_price)
    if PAPER_ONLY and PAPER_SLIPPAGE_BPS > 0:
        slip = PAPER_SLIPPAGE_BPS / 10000.0
        price = price * (1.0 + slip) if side_long(side) else price * (1.0 - slip)
    gap_sl=abs(float(signal_price)-float(sl))
    gap_tp=abs(float(tp)-float(signal_price))
    if swing_level is not None and swing_sl_buffer is not None:
        if side_long(side):
            structural_sl = float(swing_level) - float(swing_sl_buffer)
            if structural_sl >= price:
                return False
            sl = structural_sl
        else:
            structural_sl = float(swing_level) + float(swing_sl_buffer)
            if structural_sl <= price:
                return False
            sl = structural_sl
    elif side_long(side):
        sl=price-gap_sl
    else:
        sl=price+gap_sl
    if side_long(side):
        tp=float(tp) if (structural_tp and float(tp)>price) else price+gap_tp
    else:
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
    trade={'trade_id':trade_id,'setup_id':setup_id,'symbol':symbol,'side':side,'entry_price':price,'sl':sl,'tp':tp,'margin':margin,'leverage':leverage,'amount':0,'timeframe':s['timeframe'],'strategy':s['active_strategy'],'is_real':False,'paper_slippage_bps':PAPER_SLIPPAGE_BPS if PAPER_ONLY else 0.0,'paper_funding_rate_pct_8h':PAPER_FUNDING_RATE_PCT_8H if PAPER_ONLY else 0.0,'opened_at':time.time(),'signal_reason':reason[:500],'entry_reason':reason[:500],'risk_pct':float(s['risk_per_trade_pct']),'risk_usdt':risk_usdt,'quality_score':quality_score,'quality_label':quality_label,'planned_rr':planned_rr,'mfe_usdt':0.0,'mae_usdt':0.0,'mfe_r':0.0,'mae_r':0.0,'peak_favorable_price':None,'peak_adverse_price':None,'last_price':price,'duration_seconds':0.0,'realized_r':None,'trailing_activated':False,'risk_distance':risk_dist,'trailing_locked_r':0.0,'swing_sl_level':None}

    if s['trading_mode']=='REAL':
        ex=get_exchange(chat_id)
        if not ex:
            send_message(chat_id,'❌ حساب CoinEx این کاربر پیکربندی نشده یا اتصال برقرار نیست.'); return False
        sym=ccxt_symbol(symbol)
        try:
            market=ex.market(sym)
            lev_info=market.get('info') or {}
            max_lev=float(lev_info.get('max_leverage') or market.get('maxLeverage') or leverage)
            capped = int(_capped_leverage(leverage, max_lev))
            if leverage > capped: leverage=capped; trade['leverage']=leverage
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
    consumed = s.setdefault('consumed_setups', [])
    if setup_id not in consumed:
        consumed.append(setup_id)
        if len(consumed) > 2000:
            del consumed[:-2000]
        save_session(chat_id)

    if trade.get('is_real'):
        s['paper_positions'].append(trade)
        save_session(chat_id)
    if level_key:
        s['traded_levels'][level_key] = time.strftime('%Y-%m-%d', time.gmtime())
        save_session(chat_id)

    audit_event(chat_id, trade_id, 'position_opened', audit_trade_record(trade))
    chart_tf = s['timeframe']
    df = get_klines(symbol, chart_tf, 650 if chart_tf in ('5min', '15min') else 200)
    if not df.empty:
        chart(chat_id, symbol, calculate_indicators(df), trade)
    return True


def update_positions(chat_id):
    s = get_session(chat_id)
    if not s['paper_positions']:
        return
    if s['trading_mode'] == 'REAL':
        if not reconcile_real(chat_id):
            return
            
    for p in s['paper_positions'][:]:
        if s['trading_mode'] == 'REAL' and not p.get('is_real'):
            continue
            
        if s['trading_mode'] == 'REAL':
            price = exchange_latest_price(chat_id, p['symbol'])
            if not price:
                continue
        else:
            price = None
            
        primary_tf = p.get('timeframe', '5min')
        primary_df = get_klines(p['symbol'], primary_tf, 120)
        
        if s['trading_mode'] != 'REAL':
            if primary_df.empty:
                continue
            c = primary_df.iloc[-1]
            high, low, close = float(c['high']), float(c['low']), float(c['close'])
            live_market = latest_price(p['symbol'])
            price = float(live_market) if live_market else close
            
            update_trade_excursions(p, high, low)
            p['last_unrealized_pnl'] = ((price - float(p['entry_price'])) * abs(float(p.get('amount') or 0))
                                        if side_long(p['side']) else
                                        (float(p['entry_price']) - price) * abs(float(p.get('amount') or 0)))
            p['last_price'] = float(price)
        else:
            update_trade_excursions(p, float(price), float(price))
            p['last_unrealized_pnl'] = float(p.get('margin', 0)) * (((price - float(p['entry_price'])) / float(p['entry_price'])) if side_long(p['side']) else ((float(p['entry_price']) - price) / float(p['entry_price']))) * float(p['leverage'])
            p['last_price'] = float(price)
            
        if _maybe_close_before_day_end(chat_id, p, price):
            continue

        entry = float(p['entry_price'])
        risk_distance = float(p.get('risk_distance') or 0.0)
        if risk_distance <= 0:
            risk_distance = abs(entry - float(p.get('sl', entry)))
        current_r = ((price - entry) / risk_distance if side_long(p['side']) else (entry - price) / risk_distance) if risk_distance > 0 else 0.0

        exit_price = None
        reason = None

        # -------------------------------------------------------------
        # پیاده‌سازی TP پله‌ای (Tier 1 @ EQ, Tier 2 @ PDH/PDL) و حذف مدیریت اضطراری
        # -------------------------------------------------------------
        ladder = p.get('tp_ladder') or {}
        tiers = ladder.get('tiers', [])
        
        if tiers and not p.get('ladder_completed', False):
            for tier_name, tier_price, tier_weight in tiers:
                hit_key = f"hit_{tier_name}"
                if not p.get(hit_key, False):
                    is_hit = (price >= tier_price) if side_long(p['side']) else (price <= tier_price)
                    if is_hit:
                        p[hit_key] = True
                        if 'eq' in tier_name or 'tp1' in tier_name:
                            p['sl'] = entry
                            p['trailing_activated'] = True
                            send_message(chat_id, f"🎯 *پله اول TP لمس شد* ({p['symbol']})\n• قیمت EQ: `{fmt(tier_price)}`\n• حد ضرر به نقطه ورود (Break-even) منتقل شد.")
                        elif 'opposite' in tier_name or 'tp2' in tier_name:
                            send_message(chat_id, f"🎯 *پله دوم TP لمس شد* ({p['symbol']})\n• قیمت مرزی: `{fmt(tier_price)}`")
                        elif 'extension' in tier_name or 'tp3' in tier_name:
                            p['ladder_completed'] = True
                            exit_price = price
                            reason = 'TP نهایی (اکستنشن)'
                            break

        if reason is None and s['trading_mode'] == 'PAPER' and not primary_df.empty:
            if side_long(p['side']):
                hit_tp = high >= float(p['tp'])
                hit_sl = low <= float(p['sl'])
            else:
                hit_tp = low <= float(p['tp'])
                hit_sl = high >= float(p['sl'])
                
            if hit_tp and hit_sl and PAPER_CONSERVATIVE_OHLC:
                exit_price = float(p['sl'])
                reason = 'SL (same candle)'
            elif hit_tp:
                exit_price = float(p['tp'])
                reason = 'TP'
            elif hit_sl:
                exit_price = float(p['sl'])
                reason = 'SL'

        if reason is None and s['filters'].get('trailing_stop', True) and risk_distance > 0:
            if not primary_df.empty:
                _check_swing_trailing_stop(chat_id, s, p, price, primary_df)

        if reason:
            close_position(chat_id, p, exit_price, reason)
            
    save_session(chat_id)
