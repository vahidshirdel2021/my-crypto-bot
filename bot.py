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
                id %s,
                trade_id TEXT NOT NULL UNIQUE,
                chat_id BIGINT NOT NULL,
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
                chat_id BIGINT PRIMARY KEY,
                fee_rate_pct %s NOT NULL,
                updated_at INTEGER NOT NULL
            )''' % real_type)
            conn.execute('''CREATE TABLE IF NOT EXISTS users(
                chat_id BIGINT PRIMARY KEY,
                telegram_user_id BIGINT,
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
        event = {'trade_id': str(trade_id), 'stage': str(stage), 'ts': time.time(), 'data': data or {}}
        s.setdefault('trade_audit', []).append(event)
        s['trade_audit'] = s['trade_audit'][-2000:]
        save_session(chat_id)
        return event
    except Exception:
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
        'duration_seconds': p.get('duration_seconds'), 'realized_r': p.get('realized_r'),
        'mfe_usdt': p.get('mfe_usdt', 0.0), 'mae_usdt': p.get('mae_usdt', 0.0),
        'mfe_r': p.get('mfe_r', 0.0), 'mae_r': p.get('mae_r', 0.0),
        'last_price': p.get('last_price'), 'peak_favorable_price': p.get('peak_favorable_price'),
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
        'is_bot_active': False, 'scan_generation': 0, 'last_stop_reason': None,
        'trading_mode': 'PAPER', 'paper_balance': 1000.0, 'daily_start_equity': 1000.0,
        'daily_start_date': time.strftime('%Y-%m-%d', time.gmtime()), 'daily_stopped': False,
        'trade_amount_usdt': 50.0, 'leverage': 5, 'max_open_positions': 3,
        'timeframe': '5min', 'active_strategy': 'dynamic', 'paper_positions': [],
        'closed_positions': [], 'trade_audit': [],
        'scan_stats': {'scans': 0, 'symbols': 0, 'signals': 0, 'entries': 0, 'blocked': 0, 'data_errors': 0, 'reason_counts': {}},
        'cooldowns': {}, 'traded_levels': {}, 'user_state': None,
        'active_symbols': (PAPER_SYMBOLS[:] if PAPER_ONLY else DEFAULT_ACTIVE_SYMBOLS[:]),
        'filters': FILTER_DEFAULTS.copy(), 'strategy_config': get_timeframe_preset('5min'),
        'daily_loss_limit_pct': DAILY_LOSS_LIMIT_PCT, 'risk_per_trade_pct': RISK_PER_TRADE_PCT,
        'max_margin_usage_pct': MAX_MARGIN_USAGE_PCT, 'real_reconciliation_required': False,
        'last_risk_check': 0, 'last_reconcile': 0, 'telegram_offset': None,
        'created_at': int(time.time()), 'bottom_menu_open': True, 'entry_diag_enabled': True,
        'platform_fee_rate_pct': PLATFORM_FEE_RATE_PCT, 'platform_fee_total_usdt': 0.0,
        'platform_fee_trade_count': 0, 'positions_message_id': None, 'positions_message_last_edit': 0.0,
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
    if cached and cached.get('fingerprint') == fingerprint:
        return cached.get('exchange')
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
    except Exception:
        return None


TELEGRAM_COMMANDS = [{'command':'menu','description':'منوی اصلی'}]

def configure_telegram_native_menu():
    if not TELEGRAM_TOKEN:
        return
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
    except Exception:
        return False


def fmt(v):
    try:
        x=float(v)
        if abs(x)<.0001: return f'{x:.8f}'
        if abs(x)<1: return f'{x:.6f}'
        return f'{x:.4f}'
    except Exception:
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
    except Exception:
        pass
    return pd.DataFrame()


async def get_klines_async(http, symbol, tf='5min', limit=200):
    period=TIMEFRAME_MAP.get(tf,tf); key=f'{symbol}:{period}:{limit}'; now=time.time()
    with DATA_LOCK:
        c=DATA_CACHE.get(key)
        if c and now-c['ts']<DATA_CACHE_SECONDS: return c['df'].copy()
    await ASYNC_SEMAPHORE.acquire()
    try:
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
        except Exception:
            pass
    finally:
        ASYNC_SEMAPHORE.release()
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
    except Exception:
        pass
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
    except Exception:
        pass
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


def call_implicit_any(ex, candidates, params):
    for name in candidates:
        fn=getattr(ex,name,None)
        if callable(fn): return fn(params)
    raise AttributeError('CoinEx implicit SL/TP method unavailable')


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
    except Exception: return []


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
        lr=trailing_locked_r(entry,risk_distance,probe,is_long)
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
            if not ok: return False
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
        if sdf.empty: return
        sdf = calculate_indicators(sdf)
        if sdf.empty or 'atr' not in sdf.columns: return
        is_long = side_long(p['side'])
        cfg = s.get('strategy_config') or STRATEGY_DEFAULTS
        lookback_n = int(cfg.get('swing_lookback', 12))
        confirm_n = int(cfg.get('swing_confirm_candles', 2))
        buffer_atr = float(cfg.get('swing_buffer_atr', 0.40))
        new_sl, swing_level = compute_swing_stop(sdf, is_long, lookback_n, buffer_atr, confirm_n)
        if new_sl is None or swing_level is None: return
        cur_sl = float(p['sl'])
        if is_long:
            behind_price = new_sl < price
            improved = new_sl > cur_sl
        else:
            behind_price = new_sl > price
            improved = new_sl < cur_sl
        if not (behind_price and improved): return
        prev_level = p.get('swing_sl_level')
        if prev_level is not None and math.isclose(swing_level, prev_level, rel_tol=1e-9, abs_tol=1e-9): return
        if p.get('is_real'):
            ok, err = move_stop_loss(chat_id, p['symbol'], normalize_price(chat_id, p['symbol'], new_sl))
            if not ok: return
        old_sl = cur_sl
        p['sl'] = new_sl
        p['swing_sl_level'] = swing_level
        p['trailing_activated'] = True
        send_message(chat_id, f"🔄 استاپ‌لاس *{p['symbol']}* به‌دلیل تشکیل سوینگ جدید تغییر کرد\n• قبلی: `{fmt(old_sl)}`\n• جدید: `{fmt(new_sl)}`")
    except Exception:
        pass


def _maybe_close_before_day_end(chat_id, p, price):
    tf = p.get('timeframe', '5min')
    if tf not in NO_OVERNIGHT_TIMEFRAMES: return False
    if _seconds_to_local_day_end() > SCAN_INTERVAL_SECONDS: return False
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
        send_message(chat_id,f"🛑 *حد ضرر روزانه فعال شد.*\n\nشروع روز: `${start:.2f}`\nسرمایه: `${equity:.2f}`\nحد: `{s['daily_loss_limit_pct']:.2f}%`")
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
        return {'tp_pnl':tp_pnl,'sl_pnl':sl_pnl,'risk':risk,'reward':reward,'rr':rr, 'valid':bool(valid and risk > 0 and reward > 0)}
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
    rows.append([{'text':'📈 چارت در TradingView','url':tradingview_chart_url(symbol, timeframe)}])
    rows.append([{'text':'🛑 تغییر حد ضرر (SL)','callback_data':f'/edit_sl_{symbol}'}, {'text':'🎯 تغییر حد سود (TP)','callback_data':f'/edit_tp_{symbol}'}])
    rows.append([{'text':'🔴 بستن معامله','callback_data':f'/close_prompt_{symbol}'}, {'text':'🔄 بروزرسانی','callback_data':f'/manage_{symbol}'}])
    rows.append([{'text':'🏠 منوی اصلی','callback_data':'/menu'}])
    return {'inline_keyboard': rows}


def close_confirm_keyboard(symbol):
    return {'inline_keyboard': [[{'text':'✅ بله، ببند','callback_data':f'/confirm_close_{symbol}'}, {'text':'❌ انصراف','callback_data':'/cancel'}]]}


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
    fee_est=round_trip_fee_usdt(p.get('margin'), p.get('leverage'))
    net_reward=max(0.0, metrics['reward']-fee_est)
    net_risk=metrics['risk']+fee_est
    net_rr=(net_reward/net_risk) if net_risk>0 else 0.0
    tf_str = TF_DISPLAY.get(p.get('timeframe'), p.get('timeframe', '5min'))

    lines=[
        f'📊 *مدیریت معامله* — `{p["symbol"]}`', '',
        f'📌 وضعیت: `{"🟢 LONG" if long_side else "🔴 SHORT"}` | `{mode}` | تایم‌فریم: `{tf_str}`',
        f'💰 ورود: `{fmt(entry)}` | فعلی: `{fmt(price)}`',
        f'🎯 حد سود: `{fmt(tp)}` | 🛑 حد ضرر: `{fmt(sl)}`',
        f'💵 سود/زیان فعلی: `{pnl:+.2f} USDT`',
        f'⚖️ *R:R خالص:* `{net_rr:.2f}R`',
    ]
    return '\n'.join(lines)


def chart(chat_id, symbol, df, trade):
    try:
        if df.empty or len(df) < 5: return
        tf = trade.get('timeframe', '5min')
        tf_label = TF_DISPLAY.get(tf, tf)
        d = df.tail(60).copy().reset_index(drop=True)
        fig, ax = plt.subplots(figsize=(11.5, 6.2), dpi=120)
        fig.patch.set_facecolor('#0f172a'); ax.set_facecolor('#0f172a')
        for i, row in d.iterrows():
            o, h, l, c = float(row['open']), float(row['high']), float(row['low']), float(row['close'])
            candle_color = '#22c55e' if c >= o else '#ef4444'
            ax.vlines(i, l, h, color=candle_color, linewidth=1.1, alpha=0.95)
            ax.add_patch(plt.Rectangle((i - 0.31, min(o, c)), 0.62, max(abs(c - o), 1e-12), facecolor=candle_color, edgecolor=candle_color))
        entry, tp, sl = float(trade['entry_price']), float(trade['tp']), float(trade['sl'])
        for val, col, lbl in [(entry, '#60a5fa', 'ENTRY'), (tp, '#22c55e', 'TP'), (sl, '#ef4444', 'SL')]:
            ax.axhline(val, color=col, linestyle='--', linewidth=1.8, alpha=0.95)
        plt.subplots_adjust(left=0.06, right=0.82, top=0.90, bottom=0.10)
        b = io.BytesIO()
        plt.savefig(b, format='png', dpi=120, bbox_inches='tight', facecolor=fig.get_facecolor())
        plt.close(fig)
        b.seek(0)
        send_photo(chat_id, b.getvalue(), f"📊 *پوزیشن `{symbol}`*", trade_action_keyboard(symbol, miniapp_chart_url(symbol, tf), tf))
    except Exception:
        pass


def update_trade_excursions(pos, high, low):
    try:
        entry = float(pos.get('entry_price') or 0)
        margin = float(pos.get('margin') or 0)
        leverage = float(pos.get('leverage') or 1)
        risk = float(pos.get('risk_usdt') or 0)
        if entry <= 0 or margin <= 0 or leverage <= 0: return
        if side_long(pos.get('side')):
            favorable, adverse = max(0.0, float(high) - entry), max(0.0, entry - float(low))
        else:
            favorable, adverse = max(0.0, entry - float(low)), max(0.0, float(high) - entry)
        scale = margin * leverage / entry
        pos['mfe_usdt'] = max(float(pos.get('mfe_usdt') or 0), favorable * scale)
        pos['mae_usdt'] = max(float(pos.get('mae_usdt') or 0), adverse * scale)
        pos['mfe_r'] = (pos['mfe_usdt'] / risk) if risk > 0 else 0.0
        pos['mae_r'] = (pos['mae_usdt'] / risk) if risk > 0 else 0.0
    except Exception:
        pass


def _execute_trade_unlocked(chat_id, symbol, side, signal_price, sl, tp, reason='', generation=None, require_active=True, structural_tp=False):
    s = get_session(chat_id)
    trade_id = new_trade_id(chat_id, symbol)
    if (require_active and not s['is_bot_active']) or s['daily_stopped'] or not risk_guard(chat_id): return False
    now = time.time()
    if now < float(s['cooldowns'].get(symbol, 0)): return False
    s['cooldowns'].pop(symbol, None)
    if s['max_open_positions'] > 0 and len(s['paper_positions']) >= s['max_open_positions']: return False
    if any(p['symbol'] == symbol for p in s['paper_positions']): return False

    price = latest_price(symbol) or float(signal_price)
    gap_sl, gap_tp = abs(float(signal_price) - float(sl)), abs(float(tp) - float(signal_price))
    if side_long(side):
        sl, tp = price - gap_sl, price + gap_tp
    else:
        sl, tp = price + gap_sl, price - gap_tp

    s['_symbol_tmp'] = symbol
    margin, _ = safe_size(chat_id, s, price, sl)
    s.pop('_symbol_tmp', None)
    if margin <= 0: return False

    leverage = int(s['leverage'])
    risk_dist = abs(price - sl)
    risk_usdt = float(margin) * ((risk_dist / price) * leverage)
    trade = {
        'trade_id': trade_id, 'symbol': symbol, 'side': side, 'entry_price': price,
        'sl': sl, 'tp': tp, 'margin': margin, 'leverage': leverage, 'amount': (margin * leverage) / price,
        'timeframe': s['timeframe'], 'strategy': s['active_strategy'], 'is_real': False,
        'opened_at': time.time(), 'risk_usdt': risk_usdt, 'risk_distance': gap_sl,
        'trailing_activated': False, 'trailing_locked_r': 0.0,
    }
    s['paper_positions'].append(trade)
    save_session(chat_id)
    return True


def scan_watchlist_for_timeframe(timeframe, regime=None):
    if regime == 'BEARISH': return list(WINNING_SHORT_WATCHLISTS.get(timeframe, SHORT_WATCHLIST))
    if regime == 'BULLISH': return list(WINNING_WATCHLISTS.get(timeframe, LONG_WATCHLIST))
    return list(dict.fromkeys(list(LONG_WATCHLIST) + list(SHORT_WATCHLIST)))


MARKET_REGIME_CACHE = {'ts': 0.0, 'regime': 'NEUTRAL', 'detail': '', 'extreme': None, 'ttl': 90}
MARKET_REGIME_MIN_ADX = float(os.environ.get('MARKET_REGIME_MIN_ADX', '18'))
MARKET_REGIME_EXTREME_ADX = float(os.environ.get('MARKET_REGIME_EXTREME_ADX', '30'))
MARKET_REGIME_TIMEFRAME = os.environ.get('MARKET_REGIME_TIMEFRAME', '4hour')


async def refresh_market_regime(http):
    now = time.time()
    if now - MARKET_REGIME_CACHE['ts'] < MARKET_REGIME_CACHE['ttl']:
        return MARKET_REGIME_CACHE['regime'], MARKET_REGIME_CACHE['detail'], MARKET_REGIME_CACHE['extreme']
    tf = MARKET_REGIME_TIMEFRAME if MARKET_REGIME_TIMEFRAME in TIMEFRAME_MAP else '4hour'
    states = {}
    for leader in LEADER_SYMBOLS:
        try:
            d = await get_klines_async(http, leader, tf, 120)
            if d is None or d.empty or len(d) < 60: continue
            x = calculate_indicators(d).iloc[-2]
            adx = float(x.get('adx') or 0)
            bullish = bool(x['close'] > x['ema20'] > x['ema50'] and x['plus_di'] > x['minus_di'] and adx >= MARKET_REGIME_MIN_ADX)
            bearish = bool(x['close'] < x['ema20'] < x['ema50'] and x['minus_di'] > x['plus_di'] and adx >= MARKET_REGIME_MIN_ADX)
            states[leader] = ('BULLISH' if bullish else 'BEARISH' if bearish else 'NEUTRAL', adx)
        except Exception:
            pass
    unique_dirs = {v[0] for v in states.values()}
    regime = 'BULLISH' if 'BULLISH' in unique_dirs and 'BEARISH' not in unique_dirs else ('BEARISH' if 'BEARISH' in unique_dirs and 'BULLISH' not in unique_dirs else 'NEUTRAL')
    MARKET_REGIME_CACHE.update(ts=now, regime=regime, detail='', extreme=None)
    return regime, '', None


async def get_log_grid_levels(http, symbol):
    return []


async def leader_correlation_guard(http, chat_id, symbol, primary_df, timeframe, side='BUY'):
    return True, 'OK'


def execute_trade(chat_id, symbol, side, signal_price, sl, tp, reason='', structural_tp=False):
    s = get_session(chat_id)
    generation = int(s.get('scan_generation', 0))
    if not s['is_bot_active'] or s['daily_stopped']: return False
    with get_entry_lock(chat_id):
        s = get_session(chat_id)
        if not s['is_bot_active'] or s['daily_stopped'] or int(s.get('scan_generation', 0)) != generation: return False
        return _execute_trade_unlocked(chat_id, symbol, side, signal_price, sl, tp, reason, generation, structural_tp=structural_tp)


def execute_manual_trade(chat_id, symbol, side, sl, tp, entry_price=None):
    s = get_session(chat_id)
    if s['daily_stopped']: return False, 'محدودیت ضرر روزانه فعال است.'
    live_price = latest_price(symbol)
    if not live_price: return False, 'قیمت دریافت نشد.'
    price = float(entry_price) if entry_price else live_price
    generation = int(s.get('scan_generation', 0))
    with get_entry_lock(chat_id):
        s = get_session(chat_id)
        if s['daily_stopped']: return False, 'محدودیت ضرر روزانه فعال است.'
        ok = _execute_trade_unlocked(chat_id, symbol, side, price, sl, tp, 'معامله دستی', generation, require_active=False)
    return (True, '') if ok else (False, 'ورود دستی رد شد.')


def realized_history_value(chat_id, symbol, opened_at):
    return None


def is_admin(chat_id):
    return int(chat_id) in ADMIN_CHAT_IDS


def get_user_fee_rate(chat_id):
    try:
        with DB_LOCK:
            conn = db_connect()
            try: row = conn.execute('SELECT fee_rate_pct FROM user_fee_settings WHERE chat_id=?', (int(chat_id),)).fetchone()
            finally: conn.close()
        if row is not None: return min(100.0, max(0.0, float(row[0])))
    except Exception:
        pass
    s = get_session(chat_id)
    return min(100.0, max(0.0, float(s.get('platform_fee_rate_pct', PLATFORM_FEE_RATE_PCT))))


def set_user_fee_rate(chat_id, rate_pct):
    rate = min(100.0, max(0.0, float(rate_pct)))
    with DB_LOCK:
        conn = db_connect()
        try:
            conn.execute('PRAGMA busy_timeout=15000')
            conn.execute('INSERT INTO user_fee_settings(chat_id,fee_rate_pct,updated_at) VALUES(?,?,?) ON CONFLICT(chat_id) DO UPDATE SET fee_rate_pct=excluded.fee_rate_pct, updated_at=excluded.updated_at', (int(chat_id), rate, int(time.time())))
            conn.commit()
        finally: conn.close()
    s = get_session(chat_id)
    s['platform_fee_rate_pct'] = rate
    save_session(chat_id)
    return rate


def settle_platform_fee(chat_id, pos, net_profit_before_platform_fee):
    try:
        trade_id = str(pos.get('trade_id') or '')
        profit = float(net_profit_before_platform_fee or 0.0)
        if not trade_id or profit <= PLATFORM_FEE_MIN_PROFIT_USDT: return 0.0
        with DB_LOCK:
            conn = db_connect()
            try:
                conn.execute('PRAGMA busy_timeout=15000')
                existing = conn.execute('SELECT platform_fee_usdt FROM fee_ledger WHERE trade_id=?', (trade_id,)).fetchone()
                if existing is not None: return float(existing[0] or 0.0)
                rate = get_user_fee_rate(chat_id)
                fee = round(profit * rate / 100.0, 8)
                mode = 'REAL' if pos.get('is_real') else 'PAPER'
                gross = float(pos.get('pnl_gross_usdt') or profit)
                trading_cost = max(0.0, gross - profit)
                user_net = profit - fee
                conn.execute('''INSERT INTO fee_ledger(trade_id,chat_id,mode,gross_pnl_usdt,trading_cost_usdt,net_profit_before_platform_fee_usdt,fee_rate_pct,platform_fee_usdt,user_net_profit_usdt,status,created_at,settled_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''', (trade_id,int(chat_id),mode,gross,trading_cost,profit,rate,fee,user_net,'SETTLED',time.time(),time.time()))
                conn.commit()
            finally: conn.close()
        s = get_session(chat_id)
        s['platform_fee_rate_pct'] = rate
        s['platform_fee_total_usdt'] = float(s.get('platform_fee_total_usdt', 0.0)) + fee
        s['platform_fee_trade_count'] = int(s.get('platform_fee_trade_count', 0)) + 1
        pos['platform_fee_usdt'] = fee
        save_session(chat_id)
        return fee
    except Exception:
        return 0.0


def fee_report(chat_id, period='all'):
    now = time.time(); since = 0
    if period == 'day': since = now - 86400
    elif period == 'week': since = now - 7*86400
    elif period == 'month': since = now - 30*86400
    with DB_LOCK:
        conn = db_connect()
        try: row = conn.execute('SELECT COALESCE(SUM(platform_fee_usdt),0), COUNT(*), COALESCE(SUM(net_profit_before_platform_fee_usdt),0) FROM fee_ledger WHERE chat_id=? AND created_at>=?', (int(chat_id), since)).fetchone()
        finally: conn.close()
    fee, count, profit = row or (0, 0, 0)
    return f'💰 *کارمزد پلتفرم*\n\n• بازه: `{period}`\n• معاملات سودده: `{count}`\n• سود قبل از کارمزد: `{profit:.2f} USDT`\n• کارمزد شما: `{fee:.2f} USDT`\n• نرخ فعلی: `{get_user_fee_rate(chat_id):.2f}%`'


def admin_fee_report(period='all'):
    now = time.time(); since = 0
    if period == 'day': since = now - 86400
    elif period == 'week': since = now - 7*86400
    elif period == 'month': since = now - 30*86400
    with DB_LOCK:
        conn = db_connect()
        try:
            total = conn.execute('SELECT COALESCE(SUM(platform_fee_usdt),0), COUNT(*), COUNT(DISTINCT chat_id) FROM fee_ledger WHERE created_at>=?', (since,)).fetchone()
            rows = conn.execute('SELECT chat_id, COALESCE(SUM(platform_fee_usdt),0), COUNT(*) FROM fee_ledger WHERE created_at>=? GROUP BY chat_id ORDER BY SUM(platform_fee_usdt) DESC LIMIT 20', (since,)).fetchall()
        finally: conn.close()
    fee, count, users = total or (0, 0, 0)
    lines = [f'👑 *گزارش درآمد پلتفرم — {period}*','', f'• درآمد کارمزد: `{fee:.2f} USDT`', f'• معاملات کارمزدخورده: `{count}`', f'• کاربران فعال: `{users}`','', '*برترین کاربران:*']
    lines += [f'• `{uid}` → `{amt:.2f} USDT` ({cnt} معامله)' for uid, amt, cnt in rows] or ['• هنوز داده‌ای ثبت نشده است.']
    return '\n'.join(lines)


def admin_set_fee_command(chat_id, text):
    if not is_admin(chat_id):
        send_message(chat_id, '⛔ دسترسی ادمین ندارید.'); return
    parts = (text or '').split()
    if len(parts) != 3:
        send_message(chat_id, 'فرمت: `/set_fee USER_CHAT_ID RATE_PERCENT`\nمثال: `/set_fee 123456789 10`', parse_mode='Markdown'); return
    try:
        uid = int(parts[1]); rate = float(parts[2])
        set_user_fee_rate(uid, rate)
        send_message(chat_id, f'✅ نرخ کارمزد کاربر `{uid}` روی `{rate:.2f}%` تنظیم شد.', parse_mode='Markdown')
    except Exception as exc:
        send_message(chat_id, f'❌ خطا: `{exc}`', parse_mode='Markdown')


def close_position(chat_id, pos, price=None, reason='manual'):
    s = get_session(chat_id)
    if pos not in s['paper_positions']: return False
    fee = round_trip_fee_usdt(pos.get('margin'), pos.get('leverage'))
    if price is None: price = latest_price(pos['symbol']) or pos['entry_price']
    entry = float(pos['entry_price'])
    frac = ((price - entry) / entry) if side_long(pos['side']) else ((entry - price) / entry)
    pnl_gross = float(pos['margin']) * frac * float(pos['leverage'])
    pnl = pnl_gross - fee
    s['paper_balance'] += pnl
    pos['close_price'] = price
    pos['pnl_gross_usdt'] = pnl_gross
    
    platform_fee = settle_platform_fee(chat_id, pos, float(pnl)) if float(pnl) > PLATFORM_FEE_MIN_PROFIT_USDT else 0.0
    if platform_fee > 0:
        pos['pnl_before_platform_fee_usdt'] = float(pnl)
        pnl = float(pnl) - platform_fee
        s['paper_balance'] -= platform_fee
    pos['platform_fee_usdt'] = platform_fee
    pos['pnl_usdt'] = float(pnl)
    pos['close_timestamp'] = time.time()
    pos['close_reason'] = reason
    s['closed_positions'].append(pos.copy())
    s['paper_positions'].remove(pos)
    save_session(chat_id)
    send_message(chat_id, f"📌 *پوزیشن بسته شد*\n• `{pos['symbol']}`\n• PnL خالص: `{pnl:+.2f} USDT`\n• علت: `{reason}`")
    return True


def reconcile_real(chat_id):
    return True


def _position_management_timeframe(p):
    primary = str(p.get('timeframe') or '5min')
    return POSITION_MANAGEMENT_TIMEFRAME_MAP.get(primary, '1min')


def _weakness_exit_check(chat_id, s, p, current_r, wdf=None, current_price=None):
    try:
        cfg = s.get('strategy_config') or STRATEGY_DEFAULTS
        min_profit_r = float(cfg.get('weakness_exit_min_r', 0.8))
        management_tf = _position_management_timeframe(p)
        peak_r = float(p.get('mfe_r') or 0.0)
        if peak_r >= 1.0 and current_r <= peak_r - 0.30 and current_r >= 0.50:
            return True, [f"مدیریت {management_tf}: بازگشت از اوج سود"]
        if current_r <= -0.10:
            return True, [f"کاهش ریسک قبل از SL | زیان فعلی: {current_r:.2f}R"]
        return False, []
    except Exception:
        return False, []


def _build_open_positions_view(chat_id, prices=None):
    s = get_session(chat_id)
    positions = list(s.get('paper_positions') or [])
    if not positions: return 'پوزیشن بازی وجود ندارد.', get_positions_keyboard([])
    prices = prices or {}
    lines = [f'🔄 *پوزیشن‌ها ({len(positions)})*', '━━━━━━━━━━━━━━━━━━━━']
    for p in positions:
        try:
            symbol = p['symbol']
            live = prices.get(symbol) or latest_price(symbol) or float(p['entry_price'])
            entry = float(p['entry_price'])
            amount = abs(float(p.get('amount') or 0))
            pnl = (live - entry) * amount if side_long(p['side']) else (entry - live) * amount
            side_label = '🟢 LONG' if side_long(p['side']) else '🔴 SHORT'
            lines += [f'\n{side_label} `{symbol}`', f'↳ ورود: `{fmt(entry)}` | فعلی: `{fmt(live)}`', f'↳ سود/زیان: `{pnl:+.2f} USDT`']
        except Exception:
            pass
    return '\n'.join(lines), get_positions_keyboard(positions)


def _send_or_edit_positions_view(chat_id, message_id=None, force_send=False):
    s = get_session(chat_id)
    text, markup = _build_open_positions_view(chat_id)
    res = tg('sendMessage', {'chat_id': chat_id, 'text': text, 'reply_markup': markup, 'parse_mode': 'Markdown'}, 10)
    if res and res.get('ok'):
        mid = ((res.get('result') or {}).get('message_id'))
        if mid:
            s['positions_message_id'] = int(mid)
            save_session(chat_id)
            return int(mid)
    return None


def refresh_live_position_messages():
    pass


def update_positions(chat_id):
    s = get_session(chat_id)
    if not s['paper_positions']: return
    for p in s['paper_positions'][:]:
        price = latest_price(p['symbol'])
        if not price: continue
        entry = float(p['entry_price'])
        risk_distance = abs(entry - float(p['sl']))
        current_r = ((price - entry) / risk_distance if side_long(p['side']) else (entry - price) / risk_distance) if risk_distance > 0 else 0.0
        if _maybe_close_before_day_end(chat_id, p, price): continue
        should_exit, wreasons = _weakness_exit_check(chat_id, s, p, current_r, None, price)
        if should_exit:
            close_position(chat_id, p, price, 'مدیریت هوشمند (ضعف روند)')
    save_session(chat_id)


def _breakout_filter_diagnostics(df, filters=None, strategy_config=None):
    return {}


def _entry_diag_result(chat_id, symbol, status, reason='', stage='', signal=None, diagnostics=None):
    return {'chat_id': chat_id, 'symbol': symbol, 'status': status, 'reason': str(reason or '').strip(), 'stage': stage, 'signal': signal, 'ts': time.time()}


def _entry_diag_batch_update(chat_id, results):
    pass


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
    n = len(closed)
    pnls = [float(p.get('pnl_usdt', 0) or 0) for p in closed]
    net = sum(pnls)
    return f'📊 *گزارش عملکرد*\n\nمعاملات بسته‌شده: `{n}`\nسود/زیان خالص: `{net:+.2f} USDT`'


def trade_audit_report(chat_id):
    return '🔎 ممیزی معامله ثبت نشد.'


def export_trade_data(chat_id):
    return True


def reset_stats(chat_id):
    s = get_session(chat_id)
    s['closed_positions'] = []
    save_session(chat_id)
    return True, '✅ آمار ریست شد.'


def analyze(chat_id, symbol):
    text = f"🔍 تحلیل {symbol}"
    keyboard = {'inline_keyboard': [[{'text':'🏠 منوی اصلی', 'callback_data':'/menu'}]]}
    return text, keyboard


def menu(chat_id, message_id=None):
    s = get_session(chat_id)
    bal = s['paper_balance']
    text = f"📊 *پنل اصلی ربات*\n\n🟢 اسکن: `{'فعال' if s['is_bot_active'] else 'متوقف'}`\n💰 موجودی: `{bal:.2f} USDT`"
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
        admin_set_fee_command(chat_id, cmd)
        return
    if cmd in ('/admin_fee_report','/admin_fee_day','/admin_fee_week','/admin_fee_month'):
        if not is_admin(chat_id):
            send_message(chat_id,'⛔ دسترسی ادمین ندارید.'); return
        period = {'/admin_fee_report':'all','/admin_fee_day':'day','/admin_fee_week':'week','/admin_fee_month':'month'}[cmd]
        send_message(chat_id, admin_fee_report(period), parse_mode='Markdown')
        return
    if cmd == '/users':
        if not is_admin(chat_id):
            send_message(chat_id,'⛔ دسترسی ادمین ندارید.'); return
        send_message(chat_id, admin_users_report(), parse_mode='Markdown')
        return
    if cmd in ('/my_fees','/my_fee_report'):
        send_message(chat_id, fee_report(chat_id,'all'), parse_mode='Markdown')
        return
    if cmd in ('performance','report','📈 گزارش عملکرد کلی'):
        send_message(chat_id, performance_period_report(chat_id, 'all'), get_performance_keyboard()); return
    
    s = get_session(chat_id); c = (cmd or '').strip(); cl = c.lower()
    if cl == '/start':
        if s.get('is_bot_active'): stop_scan(chat_id)
        send_message(chat_id, '🤖 ربات معامله‌گر', get_start_keyboard())
        return
    if cl in ('/menu','☰ منو','🏠 منوی اصلی'): menu(chat_id, message_id); return
    if cl == '/cancel': menu(chat_id, message_id); return
    if cl in ('/stop_scan',) or c in ('🔴 توقف اسکن','توقف اسکن'):
        stop_scan(chat_id); menu(chat_id, message_id); return
    if cl in ('/start_scan',) or c in ('🟢 شروع اسکن','شروع اسکن'): start_scan(chat_id, message_id); return
    if cl == '/reload_and_start': reload_and_restart_scan(chat_id, message_id); return
    if cl == '/market_report': send_message(chat_id, market_report(chat_id)); return
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
    if raw in fixed_buttons:
        process_command(fixed_buttons[raw], chat_id); return
    process_command(text, chat_id)


def telegram_listener():
    global TELEGRAM_OFFSET
    while True:
        if not TELEGRAM_TOKEN:
            time.sleep(5); continue
        try:
            params = {'timeout': 25}
            if TELEGRAM_OFFSET > 0: params['offset'] = TELEGRAM_OFFSET
            r = requests.get(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates', params=params, timeout=30)
            if not r.ok: time.sleep(2); continue
            updates = r.json().get('result', [])
            for u in updates:
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
                except Exception:
                    pass
        except Exception:
            time.sleep(2)


async def scan_loop():
    global ASYNC_SEMAPHORE
    ASYNC_SEMAPHORE = asyncio.Semaphore(MAX_ASYNC_REQUESTS)
    while True:
        try:
            for cid, s in list(USER_SESSIONS.items()):
                update_positions(cid)
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
                    await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            pass
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
