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

from backtest import run_backtest, fetch_ohlcv_coinex

from strategy import (
    FILTER_DEFAULTS, STRATEGY_DEFAULTS, calculate_indicators, get_signal_with_reason,
    strategy_trend_following,
    strategy_breakout, strategy_mean_reversion, build_trade_plan, get_timeframe_preset,
    _compute_prev_day_levels, evaluate_trend_weakness, compute_swing_stop,
    compute_log_grid_levels, nearest_grid_level, _select_v2_setup, get_v2_config,
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
# تایم‌فریم‌هایی که هرگز نباید معامله‌شان به روز بعد منتقل شود (چه با سود چه با ضرر)
NO_OVERNIGHT_TIMEFRAMES = ('5min', '15min')
DAILY_CLOSE_TZ = os.environ.get('DAILY_CLOSE_TZ', 'Asia/Tehran')

# تایم‌فریم مدیریت سریع‌تر از تایم‌فریم اصلی معامله است.
# این نگاشت فقط برای مدیریت پوزیشن است و هیچ اثری روی منطق ورود/سیگنال ندارد.
POSITION_MANAGEMENT_TIMEFRAME_MAP = {
    # مدیریت پوزیشن با تایم‌فریم پایین‌تر انجام می‌شود تا ضعف روند زودتر دیده شود.
    # این بخش فقط برای مدیریت معامله است و روی منطق ورود تأثیری ندارد.
    '5min': '1min',
    '15min': '5min',
    '1hour': '15min',
    '4hour': '1hour',
}
POSITION_MANAGEMENT_MIN_LOSS_R = -0.10
POSITION_MANAGEMENT_LOSS_WEAKNESS_SCORE = 45.0


def _seconds_to_local_day_end():
    """ثانیه‌های باقی‌مانده تا پایان روز جاری بر اساس منطقه‌زمانی DAILY_CLOSE_TZ."""
    tz = None
    if ZoneInfo is not None:
        try:
            tz = ZoneInfo(DAILY_CLOSE_TZ)
        except Exception:
            tz = None
    now = datetime.now(tz) if tz else datetime.utcnow()
    return _seconds_until_next_midnight(now)


MAX_MARGIN_USAGE_PCT = float(os.environ.get('MAX_MARGIN_USAGE_PCT', '50'))
from trading_math import TAKER_FEE_PCT
from trading_math import (
    _seconds_until_next_midnight, _clamp_pct, fmt, market_name, ccxt_symbol,
    _extract_numbers, _price_matches, _verify_protection_prices,
    side_long, _same_direction_guard_allows, round_trip_fee_usdt,
    trailing_locked_r, _compute_trailing_update, _should_update_swing_stop,
    _should_close_before_day_end, _directional_price_fraction, _gross_pnl_usdt,
    _paper_funding_cost_usdt, _risk_usdt_from_stop, _realized_r,
    _daily_loss_limit_breached, _parse_signal_reason, _compute_setup_id,
    _risk_usdt_for_entry, _passes_min_risk_to_fee_ratio, _is_order_filled,
    _capped_leverage, _meets_min_amount, _leader_correlation_decision,
    _platform_fee_amount, _live_position_metrics,
)
MIN_RISK_TO_FEE_RATIO = max(0.0, float(os.environ.get('MIN_RISK_TO_FEE_RATIO', '3.0')))
# Platform fee: applied consistently to PAPER and REAL trades after a trade is realized.
PLATFORM_FEE_RATE_PCT = _clamp_pct(os.environ.get('PLATFORM_FEE_RATE_PCT', '10.0'))
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

# لیست Short جدا و اختصاصی: نمادهایی که رفتار خوبی هنگام افت قیمت/روند نزولی نشان می‌دهند،
# لزوماً همان نمادهای مناسب Long نیستند (طبق بک‌تست جداگانه هر جهت).
SHORT_WATCHLIST = ['IOTA','ALGO','MASK','NEO','UNI','STORJ','BTC','DASH','RUNE','COMP','BNB','ONE','GALA','AR','LUNA','MANA','ETH','ETC','SOL','SUSHI','LINK','SKL','CHZ','TRB','EGLD','BTT','VET','NEAR','SLP','ANKR','ADA','ZIL','BCH','AAVE','DYDX','RVN','SHIB','TRX','ATOM','ENJ','WAVES','ZEC','XTZ','AVAX','AXS','SNX','KSM','SAND','RSR','ZRX','RAY','QTUM']
WINNING_SHORT_WATCHLISTS = {tf: SHORT_WATCHLIST for tf in ('5min', '15min', '1hour', '4hour')}

# اجتماع دو لیست فقط برای مصارف عمومی (fallback نمادهای فعال در حالت REAL) استفاده می‌شود.
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
    """One-time, idempotent migration of legacy SQLite state into PostgreSQL/Neon."""
    if DB_BACKEND != 'postgres':
        return
    legacy_path = os.environ.get('LEGACY_SQLITE_PATH', DB_PATH).strip() or DB_PATH
    if not os.path.exists(legacy_path):
        logger.info('No legacy SQLite database found at %s; nothing to migrate.', legacy_path)
        return
    with DB_LOCK:
        pg = db_connect()
        try:
            marker = pg.execute("SELECT value FROM bot_meta WHERE key=?", ('sqlite_migration_v1',)).fetchone()
            if marker and str(marker[0]).lower() in ('done','completed'):
                logger.info('SQLite→PostgreSQL migration already completed.')
                return
            src = sqlite3.connect(legacy_path, timeout=15)
            try:
                src.row_factory = sqlite3.Row
                if not _sqlite_table_exists(src, 'sessions'):
                    pg.execute("INSERT INTO bot_meta(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at", ('sqlite_migration_v1','done',int(time.time())))
                    pg.commit()
                    logger.info('Legacy SQLite has no sessions table; migration marked complete.')
                    return
                counts = {'sessions':0,'fees':0,'fee_settings':0,'users':0,'meta':0}
                for r in src.execute('SELECT chat_id,data,updated_at FROM sessions').fetchall():
                    existing = pg.execute('SELECT updated_at FROM sessions WHERE chat_id=?', (int(r['chat_id']),)).fetchone()
                    if not existing or int(r['updated_at'] or 0) > int(existing[0] or 0):
                        if existing:
                            pg.execute('UPDATE sessions SET data=?,updated_at=? WHERE chat_id=?', (r['data'], int(r['updated_at']), int(r['chat_id'])))
                        else:
                            pg.execute('INSERT INTO sessions(chat_id,data,updated_at) VALUES(?,?,?)', (int(r['chat_id']), r['data'], int(r['updated_at'])))
                        counts['sessions'] += 1
                if _sqlite_table_exists(src, 'fee_ledger'):
                    cols = ['id','trade_id','chat_id','mode','gross_pnl_usdt','trading_cost_usdt','net_profit_before_platform_fee_usdt','fee_rate_pct','platform_fee_usdt','user_net_profit_usdt','status','created_at','settled_at']
                    for r in src.execute('SELECT '+','.join(cols)+' FROM fee_ledger').fetchall():
                        vals=[r[c] for c in cols]
                        try:
                            pg.execute("""INSERT INTO fee_ledger(id,trade_id,chat_id,mode,gross_pnl_usdt,trading_cost_usdt,net_profit_before_platform_fee_usdt,fee_rate_pct,platform_fee_usdt,user_net_profit_usdt,status,created_at,settled_at)
                                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(trade_id) DO NOTHING""", vals)
                            counts['fees'] += 1
                        except Exception:
                            logger.exception('fee migration failed trade_id=%s', r['trade_id'])
                if _sqlite_table_exists(src, 'user_fee_settings'):
                    for r in src.execute('SELECT chat_id,fee_rate_pct,updated_at FROM user_fee_settings').fetchall():
                        pg.execute("""INSERT INTO user_fee_settings(chat_id,fee_rate_pct,updated_at) VALUES(?,?,?)
                            ON CONFLICT(chat_id) DO UPDATE SET fee_rate_pct=excluded.fee_rate_pct,updated_at=excluded.updated_at
                            WHERE excluded.updated_at > user_fee_settings.updated_at""", (int(r['chat_id']), float(r['fee_rate_pct']), int(r['updated_at'])))
                        counts['fee_settings'] += 1
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
                        counts['users'] += 1
                if _sqlite_table_exists(src, 'bot_meta'):
                    for r in src.execute('SELECT key,value,updated_at FROM bot_meta').fetchall():
                        existing=pg.execute('SELECT updated_at FROM bot_meta WHERE key=?',(r['key'],)).fetchone()
                        if not existing:
                            pg.execute('INSERT INTO bot_meta(key,value,updated_at) VALUES(?,?,?)',(r['key'],r['value'],int(r['updated_at'])))
                            counts['meta'] += 1
                # Advance BIGSERIAL after importing explicit SQLite IDs.
                pg.execute("SELECT setval(pg_get_serial_sequence('fee_ledger','id'), COALESCE((SELECT MAX(id) FROM fee_ledger),1), true)")
                pg.execute("INSERT INTO bot_meta(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at", ('sqlite_migration_v1','done',int(time.time())))
                pg.commit()
                logger.info('SQLite→PostgreSQL migration completed: %s', counts)
            except Exception:
                pg.rollback()
                logger.exception('SQLite→PostgreSQL migration failed; transaction rolled back.')
                raise
            finally:
                src.close()
        finally:
            pg.close()

def upsert_telegram_user(user, chat_id=None):
    """ثبت/به‌روزرسانی پروفایل غیرحساس تلگرام برای نمایش به ادمین."""
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
    logger.info('Telegram offset loaded: %s', TELEGRAM_OFFSET)


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
        'same_direction_entry_cooldown_seconds': 120,
        'last_direction_entry_ts': {},
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
        'platform_fee_rate_pct': PLATFORM_FEE_RATE_PCT,
        'platform_fee_total_usdt': 0.0,
        'platform_fee_trade_count': 0,
        'positions_message_id': None,
        'positions_message_last_edit': 0.0,
        'opportunity_pool': [],
        'near_miss': [],
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
    s['last_direction_entry_ts'] = dict(data.get('last_direction_entry_ts') or {})
    s['opportunity_pool'] = list(data.get('opportunity_pool') or [])[-50:]
    s['near_miss'] = list(data.get('near_miss') or [])[-50:]
    s['max_same_direction_positions'] = int(s.get('max_same_direction_positions', default_session()['max_same_direction_positions']) or 0)
    s['same_direction_entry_cooldown_seconds'] = float(s.get('same_direction_entry_cooldown_seconds', default_session()['same_direction_entry_cooldown_seconds']) or 0)
    stored_symbols = list(data.get('active_symbols') or [])
    if PAPER_ONLY:
        # Paper validation should use a stable, liquid universe by default.
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
    s['platform_fee_rate_pct'] = _clamp_pct(s.get('platform_fee_rate_pct', PLATFORM_FEE_RATE_PCT))
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
        if r.status_code != 200:
            logger.warning('Telegram %s: %s', method, r.text[:300])
            # Telegram still returns a JSON body (with "description") on 4xx errors —
            # e.g. Markdown parse failures. Return it instead of None so callers like
            # send_message() can detect *why* it failed and retry (e.g. without
            # parse_mode) instead of silently dropping the message.
            try:
                return r.json()
            except Exception:
                return None
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


def _tg_is_parse_error(res):
    desc = ((res or {}).get('description') or '').lower()
    return ("can't parse" in desc) or ('can\u2019t parse' in desc) or ('parse entities' in desc) or ('entity' in desc and 'offset' in desc)


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
        if parse_mode and _tg_is_parse_error(res):
            # The text broke Telegram's Markdown parser (unescaped brackets/backticks/
            # underscores are common in raw reason/exception strings). Retry once as
            # plain text instead of dropping the message silently.
            logger.warning('Telegram editMessageText Markdown parse error for chat=%s, retrying as plain text', chat_id)
            body.pop('parse_mode', None)
            res = tg('editMessageText', body, 10)
            if res and res.get('ok'): return True
    body = {'chat_id':chat_id,'text':text,'reply_markup':markup}
    if parse_mode: body['parse_mode'] = parse_mode
    res = tg('sendMessage', body, 10)
    if res and res.get('ok'): return True
    if parse_mode and _tg_is_parse_error(res):
        logger.warning('Telegram sendMessage Markdown parse error for chat=%s, retrying as plain text', chat_id)
        body.pop('parse_mode', None)
        res = tg('sendMessage', body, 10)
        return bool(res and res.get('ok'))
    return False


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
    """Public CoinEx price for PAPER/non-exchange-specific operations."""
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
    """REAL price must come from the same CoinEx account/exchange used by the position."""
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
        return _verify_protection_prices(sls, tps, sl, tp)
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


def reserved_margin(s): return sum(float(p.get('margin',0)) for p in s['paper_positions'])


def _apply_profit_protection(chat_id, s, p, favorable_price, current_price=None):
    """Apply the position-management trailing ladder without changing entries."""
    try:
        entry=float(p['entry_price'])
        risk_distance=float(p.get('risk_distance') or 0.0)
        if risk_distance <= 0:
            risk_distance=abs(entry-float(p.get('sl', entry)))
        if risk_distance <= 0:
            return False
        is_long=side_long(p['side'])
        probe=float(favorable_price if favorable_price is not None else current_price)
        update = _compute_trailing_update(
            entry, risk_distance, float(p['sl']), is_long,
            p.get('trailing_locked_r'), p.get('trailing_activated'), probe,
        )
        if update is None:
            return False
        new_sl = update['new_sl']; lr = update['locked_r']; first_activation = update['first_activation']
        locked = float(p.get('trailing_locked_r') or 0.0)
        if p.get('is_real'):
            ok,err=move_stop_loss(chat_id,p['symbol'],normalize_price(chat_id,p['symbol'],new_sl))
            if not ok:
                logger.warning('profit-protection SL move failed symbol=%s: %s',p.get('symbol'),err)
                return False
        p['sl']=new_sl
        p['trailing_activated']=True
        p['trailing_locked_r']=lr
        if first_activation or lr>locked:
            send_message(chat_id, f"🛡️ مدیریت سود فعال شد: `{p['symbol']}`\n• قفل سود: `{lr:.1f}R`\n• حد ضرر جدید: `{fmt(new_sl)}`")
        return True
    except Exception as exc:
        logger.debug('profit protection failed trade=%s symbol=%s: %s',p.get('trade_id'),p.get('symbol'),exc)
        return False


def _check_swing_trailing_stop(chat_id, s, p, price, sdf=None):
    """
    استاپ‌لاس را بر اساس آخرین سوینگ معاملاتی تأییدشده بازبینی می‌کند (هر بار که پوزیشن
    چک می‌شود، یعنی هر SCAN_INTERVAL_SECONDS). اگر سوینگ جدیدی شکل گرفته باشد و جابه‌جایی
    استاپ به آن، وضعیت را بهتر کند (هرگز بازتر نمی‌شود)، استاپ جابه‌جا شده و پیام اطلاع‌رسانی
    ارسال می‌شود.
    """
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
        prev_level = p.get('swing_sl_level')
        if not _should_update_swing_stop(new_sl, swing_level, price, cur_sl, is_long, prev_level):
            return
        if p.get('is_real'):
            ok, err = move_stop_loss(chat_id, p['symbol'], normalize_price(chat_id, p['symbol'], new_sl))
            if not ok:
                logger.warning('swing SL move failed symbol=%s: %s', p['symbol'], err)
                return
        old_sl = cur_sl
        p['sl'] = new_sl
        p['swing_sl_level'] = swing_level
        p['trailing_activated'] = True
        send_message(chat_id, f"🔄 استاپ‌لاس *{p['symbol']}* به‌دلیل تشکیل سوینگ جدید تغییر کرد\n• قبلی: `{fmt(old_sl)}`\n• جدید: `{fmt(new_sl)}`")
    except Exception as exc:
        logger.debug('swing trailing check failed symbol=%s: %s', p.get('symbol'), exc)


def _maybe_close_before_day_end(chat_id, p, price):
    """
    برای معاملات تایم‌فریم ۵ و ۱۵ دقیقه: پوزیشن هرگز نباید به روز بعد منتقل شود، چه با سود
    چه با ضرر. اگر تا پایان روز (بر اساس DAILY_CLOSE_TZ) کمتر از یک چرخه اسکن باقی مانده
    باشد، پوزیشن همین الان با قیمت بازار بسته می‌شود.
    """
    tf = p.get('timeframe', '5min')
    if not _should_close_before_day_end(tf, _seconds_to_local_day_end(), SCAN_INTERVAL_SECONDS, NO_OVERNIGHT_TIMEFRAMES):
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
        frac = _directional_price_fraction(p['side'], p['entry_price'], price)
        eq += _gross_pnl_usdt(p.get('margin',0), p.get('leverage',1), frac)
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
    breached, limit = _daily_loss_limit_breached(equity, start, s['daily_loss_limit_pct'])
    if breached:
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


TV_INTERVAL_MAP = {'5min': '5', '15min': '15', '1hour': '60', '4hour': '240', '1day': 'D'}


def tradingview_chart_url(symbol, timeframe='5min'):
    """
    لینک چارت TradingView برای نماد/تایم‌فریم فعال می‌سازد (نماد پرپچوال روی CoinEx،
    همان صرافی‌ای که ربات معامله می‌کند: COINEX:{SYMBOL}USDT.P).
    این یک لینک معمولی tradingview.com است؛ تلگرام و سیستم‌عامل موبایل به‌صورت خودکار
    اگر اپلیکیشن TradingView نصب باشد آن را در اپ باز می‌کنند (universal/app link)،
    وگرنه در مرورگر پیش‌فرض باز می‌شود - نیازی به منطق تشخیص اپ در سمت سرور نیست.
    """
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


def _execute_trade_unlocked(chat_id,symbol,side,signal_price,sl,tp,reason='',generation=None,require_active=True,structural_tp=False):
    s=get_session(chat_id)
    trade_id = new_trade_id(chat_id, symbol)
    parsed = _parse_signal_reason(reason)
    quality_score = parsed['quality_score']; quality_label = parsed['quality_label']; planned_rr = parsed['planned_rr']
    level_key = f"{symbol}:{parsed['level_suffix']}" if parsed['level_suffix'] else None
    # A setup is consumable only once. Use the latest closed signal identity so
    # repeated scan loops cannot create duplicate audit signals or re-enter the
    # exact same liquidity event.
    setup_id = _compute_setup_id(symbol, side, s.get('timeframe'), signal_price, sl, tp, reason)
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
    # Adaptive correlated-exposure guard: the normal same-direction cap remains,
    # but one exceptional setup may exceed it by exactly one position when final
    # quality and RR are strong enough. The cooldown still blocks burst entries.
    dir_key = 'BUY' if side_long(side) else 'SELL'
    if not _same_direction_guard_allows(s, side, time.time(), quality_score=quality_score, planned_rr=planned_rr):
        return False
    audit_event(chat_id, trade_id, 'signal_and_plan', {
        'symbol': symbol, 'side': side, 'signal_price': signal_price, 'sl': sl, 'tp': tp,
        'reason': reason, 'setup_id': setup_id, 'timeframe': s.get('timeframe'),
        'strategy': s.get('active_strategy'), 'quality_score': quality_score,
        'quality_label': quality_label, 'planned_rr': planned_rr
    })

    price=latest_price(symbol) or float(signal_price)
    # Conservative paper execution: adverse entry slippage only.
    if PAPER_ONLY and PAPER_SLIPPAGE_BPS > 0:
        slip = PAPER_SLIPPAGE_BPS / 10000.0
        price = price * (1.0 + slip) if side_long(side) else price * (1.0 - slip)
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
    risk_usdt=_risk_usdt_for_entry(price, sl, margin, leverage)
    fee_estimate=round_trip_fee_usdt(margin,leverage)
    if not _passes_min_risk_to_fee_ratio(risk_usdt, fee_estimate, MIN_RISK_TO_FEE_RATIO):
        return False
    trade={'trade_id':trade_id,'setup_id':setup_id,'symbol':symbol,'side':side,'entry_price':price,'sl':sl,'tp':tp,'margin':margin,'leverage':leverage,'amount':0,'timeframe':s['timeframe'],'strategy':s['active_strategy'],'is_real':False,'paper_slippage_bps':PAPER_SLIPPAGE_BPS if PAPER_ONLY else 0.0,'paper_funding_rate_pct_8h':PAPER_FUNDING_RATE_PCT_8H if PAPER_ONLY else 0.0,'opened_at':time.time(),'signal_reason':reason[:500],'entry_reason':reason[:500],'risk_pct':float(s['risk_per_trade_pct']),'risk_usdt':risk_usdt,'quality_score':quality_score,'quality_label':quality_label,'planned_rr':planned_rr,'mfe_usdt':0.0,'mae_usdt':0.0,'mfe_r':0.0,'mae_r':0.0,'peak_favorable_price':None,'peak_adverse_price':None,'last_price':price,'duration_seconds':0.0,'realized_r':None,'trailing_activated':False,'risk_distance':gap_sl,'trailing_locked_r':0.0,'swing_sl_level':None}

    if s['trading_mode']=='REAL':
        ex=get_exchange(chat_id)
        if not ex:
            send_message(chat_id,'❌ حساب CoinEx این کاربر پیکربندی نشده یا اتصال برقرار نیست.'); return False
        sym=ccxt_symbol(symbol)
        try:
            market=ex.market(sym)
            lev_info=market.get('info') or {}
            max_lev=float(lev_info.get('max_leverage') or market.get('maxLeverage') or leverage)
            leverage=_capped_leverage(leverage, max_lev); trade['leverage']=leverage
            ex.set_margin_mode(MARGIN_MODE,sym,{'leverage':leverage})
        except Exception:
            try:
                ex.set_leverage(leverage,sym,{'marginMode':MARGIN_MODE})
            except Exception as exc:
                send_message(chat_id,f'❌ تنظیم اهرم `{symbol}` شکست خورد: `{exc}`'); return False
        amount=(margin*leverage)/price
        amount=normalize_amount(chat_id,symbol,amount)
        min_amt=float(((market.get('limits') or {}).get('amount') or {}).get('min') or 0)
        if not _meets_min_amount(amount, min_amt):
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
                if _is_order_filled(confirmed): break
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
    last_dir_ts_map = s.setdefault('last_direction_entry_ts', {})
    last_dir_ts_map[dir_key] = time.time()
    consumed = s.setdefault('consumed_setups', [])
    if setup_id not in consumed:
        consumed.append(setup_id)
        # Keep memory bounded while preserving enough recent setup identities.
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


def scan_watchlist_for_timeframe(timeframe, regime=None):
    if regime == 'BEARISH':
        return list(WINNING_SHORT_WATCHLISTS.get(timeframe, WINNING_SHORT_WATCHLISTS['5min']))
    if regime == 'BULLISH':
        return list(WINNING_WATCHLISTS.get(timeframe, WINNING_WATCHLISTS['5min']))
    long_list = WINNING_WATCHLISTS.get(timeframe, WINNING_WATCHLISTS['5min'])
    short_list = WINNING_SHORT_WATCHLISTS.get(timeframe, WINNING_SHORT_WATCHLISTS['5min'])
    return list(dict.fromkeys(list(long_list) + list(short_list)))


MARKET_REGIME_CACHE = {'ts': 0.0, 'regime': 'NEUTRAL', 'detail': '', 'extreme': None, 'ttl': 90}
MARKET_REGIME_MIN_ADX = float(os.environ.get('MARKET_REGIME_MIN_ADX', '18'))
# آستانه «روند به‌شدت یک‌طرفه»: بسیار سخت‌گیرانه‌تر از MARKET_REGIME_MIN_ADX (که فقط برای
# انتخاب واچ‌لیست است). این مقدار فقط وقتی هر دو لیدر (BTC/ETH) هم‌جهت و با ADX بالا باشند
# فعال می‌شود و باعث بلاک‌شدن معاملات خلاف‌جهت (fade/sweep) می‌شود.
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
            if d is None or d.empty or len(d) < 60:
                detail = f'داده کافی برای {leader} در دسترس نیست'
                MARKET_REGIME_CACHE.update(ts=now, regime='NEUTRAL', detail=detail, extreme=None)
                return 'NEUTRAL', detail, None
            x = calculate_indicators(d).iloc[-2]
            adx = float(x.get('adx') or 0)
            bullish = bool(x['close'] > x['ema20'] > x['ema50'] and x['plus_di'] > x['minus_di'] and adx >= MARKET_REGIME_MIN_ADX)
            bearish = bool(x['close'] < x['ema20'] < x['ema50'] and x['minus_di'] > x['plus_di'] and adx >= MARKET_REGIME_MIN_ADX)
            states[leader] = ('BULLISH' if bullish else 'BEARISH' if bearish else 'NEUTRAL', adx)
        except Exception as exc:
            detail = f'خطا در دریافت داده {leader}: {exc}'
            MARKET_REGIME_CACHE.update(ts=now, regime='NEUTRAL', detail=detail, extreme=None)
            return 'NEUTRAL', detail, None
    detail = ' | '.join(f'{leader}={states[leader][0]} (ADX={states[leader][1]:.1f})' for leader in LEADER_SYMBOLS)
    unique_dirs = {v[0] for v in states.values()}
    if 'BULLISH' in unique_dirs and 'BEARISH' not in unique_dirs:
        regime = 'BULLISH'
    elif 'BEARISH' in unique_dirs and 'BULLISH' not in unique_dirs:
        regime = 'BEARISH'
    else:
        regime = 'NEUTRAL'
    # حالت «شدید»: همه‌ی لیدرها هم‌جهت و با ADX بالای آستانه‌ی سخت‌گیرانه - فقط همین حالت
    # باعث بلاک شدن معاملات خلاف‌جهت می‌شود، نه regime عادی بالا (که صرفاً برای واچ‌لیست است)
    extreme_bull = all(v[0] == 'BULLISH' and v[1] >= MARKET_REGIME_EXTREME_ADX for v in states.values())
    extreme_bear = all(v[0] == 'BEARISH' and v[1] >= MARKET_REGIME_EXTREME_ADX for v in states.values())
    extreme = 'BULLISH' if extreme_bull else ('BEARISH' if extreme_bear else None)
    MARKET_REGIME_CACHE.update(ts=now, regime=regime, detail=detail, extreme=extreme)
    return regime, detail, extreme


# --- شبکه سطوح لگاریتمی (بر اساس اسکریپت Pine کاربر) --------------------------------
# ساختار کلان و کم‌تغییر است (بر پایه‌ی کف/سقف تاریخچه‌ی روزانه)، پس مثل رژیم بازار کش
# می‌شود و فقط هر چند ساعت یک‌بار به‌روزرسانی می‌شود، نه در هر اسکن.
LOG_GRID_BASE_STEPS = int(os.environ.get('LOG_GRID_BASE_STEPS', '20'))
LOG_GRID_LOOKBACK_DAYS = int(os.environ.get('LOG_GRID_LOOKBACK_DAYS', '500'))
LOG_GRID_TTL = float(os.environ.get('LOG_GRID_TTL_SECONDS', '21600'))  # هر ۶ ساعت
LOG_GRID_CACHE: Dict[str, Dict[str, Any]] = {}


async def get_log_grid_levels(http, symbol):
    """
    سطوح شبکه‌ی لگاریتمی یک نماد را برمی‌گرداند (کش‌شده). بر پایه‌ی داده‌ی روزانه
    (تا LOG_GRID_LOOKBACK_DAYS کندل، برای تخمین نزدیک به کف/سقف کل تاریخچه‌ی نماد -
    دقیقاً مثل chart_low/chart_high در اسکریپت اصلی که کل چارت را می‌بیند).
    """
    now = time.time()
    c = LOG_GRID_CACHE.get(symbol)
    if c and now - c['ts'] < LOG_GRID_TTL:
        return c['levels']
    d = await get_klines_async(http, symbol, '1day', LOG_GRID_LOOKBACK_DAYS)
    levels = compute_log_grid_levels(d, LOG_GRID_BASE_STEPS) if d is not None and not d.empty else []
    LOG_GRID_CACHE[symbol] = {'ts': now, 'levels': levels}
    return levels


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
        allowed, block_reason = _leader_correlation_decision(leader_states, correlations, is_long)
        if not allowed:
            messages = {
                'bearish_leaders_correlated': f'محافظ بازار فعال شد؛ BTC و ETH در روند نزولی تأییدشده هستند | همبستگی: {detail}',
                'leader_crash_correlated': f'محافظ بازار فعال شد؛ سقوط شدید یکی از لیدرها و همبستگی بالا | همبستگی: {detail}',
                'bullish_leaders_correlated': f'محافظ بازار فعال شد؛ BTC و ETH در روند صعودی تأییدشده هستند | همبستگی: {detail}',
                'leader_pump_correlated': f'محافظ بازار فعال شد؛ جهش شدید یکی از لیدرها و همبستگی بالا | همبستگی: {detail}',
            }
            return False, messages[block_reason]

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


def is_admin(chat_id):
    return int(chat_id) in ADMIN_CHAT_IDS


def get_user_fee_rate(chat_id):
    try:
        with DB_LOCK:
            conn = db_connect()
            try:
                row = conn.execute('SELECT fee_rate_pct FROM user_fee_settings WHERE chat_id=?', (int(chat_id),)).fetchone()
            finally:
                conn.close()
        if row is not None:
            return _clamp_pct(row[0])
    except Exception:
        logger.exception('get user fee rate failed chat=%s', chat_id)
    s = get_session(chat_id)
    return _clamp_pct(s.get('platform_fee_rate_pct', PLATFORM_FEE_RATE_PCT))


def set_user_fee_rate(chat_id, rate_pct):
    rate = _clamp_pct(rate_pct)
    with DB_LOCK:
        conn = db_connect()
        try:
            conn.execute('PRAGMA busy_timeout=15000')
            conn.execute('INSERT INTO user_fee_settings(chat_id,fee_rate_pct,updated_at) VALUES(?,?,?) ON CONFLICT(chat_id) DO UPDATE SET fee_rate_pct=excluded.fee_rate_pct, updated_at=excluded.updated_at', (int(chat_id), rate, int(time.time())))
            conn.commit()
        finally:
            conn.close()
    s = get_session(chat_id)
    s['platform_fee_rate_pct'] = rate
    save_session(chat_id)
    return rate


def settle_platform_fee(chat_id, pos, net_profit_before_platform_fee):
    '''Idempotent platform fee settlement for PAPER and REAL.
    Fee is charged only on realized positive profit and is recorded once per trade_id.
    REAL mode records the payable fee in the ledger; actual wallet transfer is intentionally
    separate and requires an explicitly configured exchange settlement mechanism.
    '''
    try:
        trade_id = str(pos.get('trade_id') or '')
        profit = float(net_profit_before_platform_fee or 0.0)
        if not trade_id or profit <= PLATFORM_FEE_MIN_PROFIT_USDT:
            return 0.0
        with DB_LOCK:
            conn = db_connect()
            try:
                conn.execute('PRAGMA busy_timeout=15000')
                existing = conn.execute('SELECT platform_fee_usdt FROM fee_ledger WHERE trade_id=?', (trade_id,)).fetchone()
                if existing is not None:
                    return float(existing[0] or 0.0)
                rate = get_user_fee_rate(chat_id)
                fee = _platform_fee_amount(profit, rate, PLATFORM_FEE_MIN_PROFIT_USDT)
                mode = 'REAL' if pos.get('is_real') else 'PAPER'
                gross = float(pos.get('pnl_gross_usdt') or profit)
                trading_cost = max(0.0, gross - profit)
                user_net = profit - fee
                conn.execute('''INSERT INTO fee_ledger(trade_id,chat_id,mode,gross_pnl_usdt,trading_cost_usdt,net_profit_before_platform_fee_usdt,fee_rate_pct,platform_fee_usdt,user_net_profit_usdt,status,created_at,settled_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''', (trade_id,int(chat_id),mode,gross,trading_cost,profit,rate,fee,user_net,'SETTLED',time.time(),time.time()))
                conn.commit()
            finally:
                conn.close()
        s = get_session(chat_id)
        s['platform_fee_rate_pct'] = rate
        s['platform_fee_total_usdt'] = float(s.get('platform_fee_total_usdt', 0.0)) + fee
        s['platform_fee_trade_count'] = int(s.get('platform_fee_trade_count', 0)) + 1
        pos['platform_fee_usdt'] = fee
        pos['platform_fee_rate_pct'] = rate
        pos['platform_fee_status'] = 'SETTLED'
        save_session(chat_id)
        return fee
    except sqlite3.IntegrityError:
        return 0.0
    except Exception:
        logger.exception('platform fee settlement failed chat=%s trade=%s', chat_id, pos.get('trade_id'))
        return 0.0


def fee_report(chat_id, period='all'):
    now=time.time()
    since=0
    if period=='day': since=now-86400
    elif period=='week': since=now-7*86400
    elif period=='month': since=now-30*86400
    with DB_LOCK:
        conn=db_connect()
        try:
            row=conn.execute('SELECT COALESCE(SUM(platform_fee_usdt),0), COUNT(*), COALESCE(SUM(net_profit_before_platform_fee_usdt),0) FROM fee_ledger WHERE chat_id=? AND created_at>=?',(int(chat_id),since)).fetchone()
        finally: conn.close()
    fee,count,profit=row or (0,0,0)
    return f'💰 *کارمزد پلتفرم*\n\n• بازه: `{period}`\n• معاملات سودده: `{count}`\n• سود قبل از کارمزد پلتفرم: `{profit:.2f} USDT`\n• کارمزد شما: `{fee:.2f} USDT`\n• نرخ فعلی: `{get_user_fee_rate(chat_id):.2f}%`'


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
    lines=[f'👑 *گزارش درآمد پلتفرم — {period}*','',f'• درآمد کارمزد: `{fee:.2f} USDT`',f'• معاملات کارمزدخورده: `{count}`',f'• کاربران فعال: `{users}`','', '*برترین کاربران:*']
    lines += [f'• `{uid}` → `{amt:.2f} USDT` ({cnt} معامله)' for uid,amt,cnt in rows] or ['• هنوز داده‌ای ثبت نشده است.']
    return '\n'.join(lines)


def admin_set_fee_command(chat_id, text):
    if not is_admin(chat_id):
        send_message(chat_id,'⛔ دسترسی ادمین ندارید.'); return
    parts=(text or '').split()
    if len(parts) != 3:
        send_message(chat_id,'فرمت: `/set_fee USER_CHAT_ID RATE_PERCENT`\nمثال: `/set_fee 123456789 10`',parse_mode='Markdown'); return
    try:
        uid=int(parts[1]); rate=float(parts[2])
        set_user_fee_rate(uid, rate)
        send_message(chat_id,f'✅ نرخ کارمزد کاربر `{uid}` روی `{rate:.2f}%` تنظیم شد.',parse_mode='Markdown')
    except Exception as exc:
        send_message(chat_id,f'❌ خطا: `{exc}`',parse_mode='Markdown')


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
                frac = _directional_price_fraction(pos['side'], pos['entry_price'], price)
                pnl_gross = _gross_pnl_usdt(pos['margin'], pos['leverage'], frac)
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
        # Conservative paper exit slippage.
        if PAPER_ONLY and PAPER_SLIPPAGE_BPS > 0:
            slip = PAPER_SLIPPAGE_BPS / 10000.0
            price = float(price) * (1.0 - slip) if side_long(pos['side']) else float(price) * (1.0 + slip)
        entry=float(pos['entry_price']); frac = _directional_price_fraction(pos['side'], entry, price)
        pnl_gross = _gross_pnl_usdt(pos['margin'], pos['leverage'], frac)
        funding_cost = _paper_funding_cost_usdt(pos['margin'], pos['leverage'], pos.get('opened_at', time.time()), time.time(), PAPER_FUNDING_RATE_PCT_8H)
        pnl=pnl_gross-fee-funding_cost
        s['paper_balance']+=pnl; pos['close_price']=price; pos['pnl_is_estimate']=False
        pos['pnl_gross_usdt']=pnl_gross
        pos['funding_usdt']=funding_cost
        fee_note=f' (کارمزد + فاندینگ کسر شد: {funding_cost:.2f} USDT)'
    # Exchange/trading costs are already represented by `pnl`; platform fee is a separate layer.
    platform_fee = settle_platform_fee(chat_id, pos, float(pnl)) if float(pnl) > PLATFORM_FEE_MIN_PROFIT_USDT else 0.0
    if platform_fee > 0:
        pos['pnl_before_platform_fee_usdt'] = float(pnl)
        pnl = float(pnl) - platform_fee
        if not pos.get('is_real'):
            s['paper_balance'] -= platform_fee
    pos['platform_fee_usdt'] = platform_fee
    pos['fee_usdt']=fee
    if not pos.get('risk_usdt'):
        try: pos['risk_usdt']=_risk_usdt_from_stop(pos['entry_price'], pos['sl'], pos['margin'], pos['leverage'])
        except Exception: pos['risk_usdt']=0.0
    pos['pnl_usdt']=float(pnl); pos['close_timestamp']=time.time(); pos['close_reason']=reason
    pos['duration_seconds']=max(0, pos['close_timestamp']-float(pos.get('opened_at', pos['close_timestamp'])))
    pos['realized_r']=_realized_r(pos.get('pnl_usdt'), pos.get('risk_usdt'))
    update_trade_excursions(pos, float(price), float(price))
    audit_event(chat_id, pos.get('trade_id') or new_trade_id(chat_id, pos.get('symbol','?')), 'position_closed', {'close_price': price, 'pnl_usdt': pnl, 'pnl_before_platform_fee_usdt': pos.get('pnl_before_platform_fee_usdt'), 'fee_usdt': fee, 'platform_fee_usdt': pos.get('platform_fee_usdt', 0.0), 'reason': reason, 'duration_seconds': pos['duration_seconds'], 'realized_r': pos.get('realized_r'), 'mfe_usdt': pos.get('mfe_usdt',0.0), 'mae_usdt': pos.get('mae_usdt',0.0), 'mfe_r': pos.get('mfe_r',0.0), 'mae_r': pos.get('mae_r',0.0)})
    cooldown_len = int(s.get('strategy_config', {}).get('cooldown_seconds', 1200))
    s['cooldowns'][pos['symbol']]=time.time()+cooldown_len; s['closed_positions'].append(pos.copy()); s['paper_positions'].remove(pos); save_session(chat_id)
    est=' تقریبی' if pos.get('pnl_is_estimate') else ''
    fee_line=f"\n• کارمزد تخمینی رفت‌وبرگشت: `{fee:.2f} USDT`{fee_note}" if fee>0 else ''
    platform_line = f'\n• سهم پلتفرم: `{platform_fee:.2f} USDT` ({get_user_fee_rate(chat_id):.2f}%)' if platform_fee > 0 else ''
    send_message(chat_id,f"📌 *پوزیشن {'REAL' if pos.get('is_real') else 'PAPER'} بسته شد*\n• `{pos['symbol']}`\n• خروج: `{fmt(pos['close_price'])}`\n• PnL خالص کاربر{est}: `{pnl:+.2f} USDT`{fee_line}{platform_line}\n• علت: `{reason}`")
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
            if float(p.get('pnl_usdt') or 0.0) > PLATFORM_FEE_MIN_PROFIT_USDT:
                pf = settle_platform_fee(chat_id, p, float(p.get('pnl_usdt') or 0.0))
                p['pnl_before_platform_fee_usdt'] = float(p.get('pnl_usdt') or 0.0)
                p['platform_fee_usdt'] = pf
                p['pnl_usdt'] = float(p.get('pnl_usdt') or 0.0) - pf
            cooldown_len = int(s.get('strategy_config', {}).get('cooldown_seconds', 1200))
            s['closed_positions'].append(p.copy()); s['paper_positions'].remove(p); s['cooldowns'][sym]=time.time()+cooldown_len
            audit_event(chat_id, p.get('trade_id') or new_trade_id(chat_id, sym), 'position_closed', {'close_price': p.get('close_price'), 'pnl_usdt': p.get('pnl_usdt'), 'reason': p.get('close_reason'), 'duration_seconds': p.get('duration_seconds'), 'realized_r': p.get('realized_r'), 'mfe_usdt': p.get('mfe_usdt',0.0), 'mae_usdt': p.get('mae_usdt',0.0), 'external': True})
            send_message(chat_id,f"📌 پوزیشن REAL `{sym}` توسط صرافی بسته شد.\nPnL ثبت‌شده: `{p['pnl_usdt']:+.2f} USDT`")
    s['last_reconcile']=time.time(); save_session(chat_id); return True


def _position_management_timeframe(p):
    """Faster timeframe used to confirm trend weakness for position management.

    Applies the SAME faster-timeframe technique symmetrically to both directions:
    protecting an open profit (pullback from peak) and catching an early move
    toward the stop. Entry/signal logic is untouched — this only affects how
    quickly an already-open position reacts to a developing reversal.
    """
    primary = str(p.get('timeframe') or '5min')
    return POSITION_MANAGEMENT_TIMEFRAME_MAP.get(primary, primary)


def _weakness_exit_check(chat_id, s, p, current_r, wdf=None, current_price=None):
    """Fast multi-timeframe position protection; entries remain untouched."""
    try:
        cfg=s.get('strategy_config') or STRATEGY_DEFAULTS
        min_profit_r=float(cfg.get('weakness_exit_min_r',1.0))
        min_profit_r=max(1.0, min_profit_r)
        primary_tf=str(p.get('timeframe') or '5min')
        management_tf=_position_management_timeframe(p)
        p['management_timeframe']=management_tf
        peak_r=float(p.get('mfe_r') or 0.0)

        # Fast profit protection is based on live price/MFE and remains independent
        # of indicator weakness. Indicator weakness starts only after a real profit
        # buffer (>= 1R), so normal pullbacks cannot close a marginally profitable trade.
        if peak_r>=1.0 and current_r <= peak_r-0.30 and current_r>=0.50:
            return True,[f"مدیریت {management_tf}: بازگشت از اوج سود {peak_r:.1f}R به {current_r:.1f}R"]

        early_loss_enabled=bool(cfg.get('early_loss_weakness_exit_enabled',False))
        loss_score = POSITION_MANAGEMENT_LOSS_WEAKNESS_SCORE if early_loss_enabled and current_r <= POSITION_MANAGEMENT_MIN_LOSS_R else 999.0
        need_weakness = current_r>=min_profit_r or (early_loss_enabled and current_r<=POSITION_MANAGEMENT_MIN_LOSS_R)
        if not need_weakness:
            return False,[]
        if wdf is None:
            wdf=get_klines(p['symbol'],management_tf,150)
        if wdf is None or wdf.empty or len(wdf)<60:
            return False,[]
        wdf=calculate_indicators(wdf)
        if wdf.empty or len(wdf)<60:
            return False,[]
        is_weak,wscore,wreasons=evaluate_trend_weakness(wdf,p['side'],cfg)

        # Profitable trades can use confirmed weakness; the early-loss path uses a
        # faster management timeframe (see _position_management_timeframe) and a
        # looser score threshold, since catching a real reversal early — before the
        # full SL distance is given back — matters more than being conservative here.
        if current_r>=min_profit_r and is_weak:
            return True,[f"تایم‌فریم مدیریت: {management_tf}",f"امتیاز ضعف: {wscore}/100"]+list(wreasons)
        if early_loss_enabled and current_r<=POSITION_MANAGEMENT_MIN_LOSS_R and wscore>=loss_score:
            return True,[f"کاهش ریسک قبل از SL | تایم‌فریم مدیریت: {management_tf}",f"زیان فعلی: {current_r:.2f}R",f"آستانه ضعف متناسب با ضرر: {loss_score:.0f}",f"امتیاز ضعف: {wscore}/100"]+list(wreasons)
        return False,[]
    except Exception as exc:
        logger.debug('weakness exit check failed trade=%s symbol=%s: %s',p.get('trade_id'),p.get('symbol'),exc)
        return False,[]


def _build_open_positions_view(chat_id, prices=None):
    """Build the live open-position card. Prices are fetched fresh (with normal caches)."""
    s = get_session(chat_id)
    positions = list(s.get('paper_positions') or [])
    if not positions:
        return 'پوزیشن بازی وجود ندارد.', get_positions_keyboard([])
    prices = prices or {}
    lines = [f'🔄 *پوزیشن‌ها ({len(positions)})*', '━━━━━━━━━━━━━━━━━━━━']
    for p in positions:
        try:
            symbol = p['symbol']
            live = prices.get(symbol)
            if live is None:
                live = exchange_latest_price(chat_id, symbol) if p.get('is_real') else latest_price(symbol)
            live = float(live or p.get('last_price') or p.get('entry_price') or 0)
            entry = float(p.get('entry_price') or live or 0)
            amount = abs(float(p.get('amount') or 0))
            pnl, pct, r = _live_position_metrics(p['side'], entry, live, amount, p.get('risk_usdt'))
            side_label = '🟢 LONG' if side_long(p['side']) else '🔴 SHORT'
            lines += [
                f'\n{side_label} `{symbol}`',
                f'↳ ورود: `{fmt(entry)}` | فعلی: `{fmt(live)}`',
                f'↳ 📈 سود/زیان لحظه‌ای: `{pnl:+.2f} USDT`',
                f'↳ 📊 بازده: `{pct:+.2f}%` | R: `{r:+.2f}`',
                f'↳ 🎯 TP: `{fmt(p["tp"])}` | 🛑 SL: `{fmt(p["sl"])}`',
            ]
        except Exception as exc:
            logger.debug('open positions view failed chat=%s trade=%s: %s', chat_id, p.get('trade_id'), exc)
    return '\n'.join(lines), get_positions_keyboard(positions)


def _send_or_edit_positions_view(chat_id, message_id=None, force_send=False):
    """Send/edit the positions card and remember its Telegram message id for live refresh."""
    s = get_session(chat_id)
    text, markup = _build_open_positions_view(chat_id)
    target_id = message_id or s.get('positions_message_id')
    if target_id and not force_send:
        res = tg('editMessageText', {
            'chat_id': chat_id,
            'message_id': int(target_id),
            'text': text,
            'reply_markup': markup,
            'parse_mode': 'Markdown'
        }, 10)
        if res and res.get('ok'):
            s['positions_message_id'] = int(target_id)
            s['positions_message_last_edit'] = time.time()
            save_session(chat_id)
            return int(target_id)
        desc = ((res or {}).get('description') or '').lower()
        if 'message is not modified' in desc:
            s['positions_message_id'] = int(target_id)
            s['positions_message_last_edit'] = time.time()
            save_session(chat_id)
            return int(target_id)
        # Stale/deleted message: fall through and create a fresh card.
        # (No positions and the edit above already failed on this same target_id —
        # retrying the identical edit here would just fail again; go straight to sendMessage.)
    res = tg('sendMessage', {
        'chat_id': chat_id, 'text': text,
        'reply_markup': markup, 'parse_mode': 'Markdown'
    }, 10)
    if res and res.get('ok'):
        mid = ((res.get('result') or {}).get('message_id'))
        if mid:
            s['positions_message_id'] = int(mid)
            s['positions_message_last_edit'] = time.time()
            save_session(chat_id)
            return int(mid)
    return None


def refresh_live_position_messages():
    """Refresh visible position cards every ~10s without running the heavy management engine."""
    now = time.time()
    for chat_id, s in list(USER_SESSIONS.items()):
        if not s.get('paper_positions') or not s.get('positions_message_id'):
            continue
        if now - float(s.get('positions_message_last_edit') or 0.0) < 10.0:
            continue
        prices = {}
        for p in list(s.get('paper_positions') or []):
            try:
                price = exchange_latest_price(chat_id, p['symbol']) if p.get('is_real') else latest_price(p['symbol'])
                if price:
                    prices[p['symbol']] = float(price)
                    p['last_price'] = float(price)
            except Exception:
                pass
        text, markup = _build_open_positions_view(chat_id, prices)
        res = tg('editMessageText', {
            'chat_id': chat_id,
            'message_id': int(s['positions_message_id']),
            'text': text,
            'reply_markup': markup,
            'parse_mode': 'Markdown'
        }, 10)
        if res and res.get('ok'):
            s['positions_message_last_edit'] = now
            save_session(chat_id)
        else:
            desc = ((res or {}).get('description') or '').lower()
            if 'message is not modified' in desc:
                s['positions_message_last_edit'] = now


def update_positions(chat_id):
    s=get_session(chat_id)
    if not s['paper_positions']: return
    if s['trading_mode']=='REAL':
        if not reconcile_real(chat_id): return
    for p in s['paper_positions'][:]:
        if s['trading_mode']=='REAL' and not p.get('is_real'): continue
        if s['trading_mode']=='REAL':
            price=exchange_latest_price(chat_id,p['symbol'])
            if not price: continue
        else:
            price=None
        primary_tf=p.get('timeframe','5min')
        management_tf=_position_management_timeframe(p)
        # One market-data fetch per required timeframe per cycle; downstream management
        # functions reuse these frames instead of issuing duplicate requests.
        primary_df=get_klines(p['symbol'],primary_tf,120)
        management_df=primary_df if management_tf==primary_tf else get_klines(p['symbol'],management_tf,150)
        if s['trading_mode']!='REAL':
            if primary_df.empty: continue
            c=primary_df.iloc[-1]
            high,low,close=float(c['high']),float(c['low']),float(c['close'])
            live_market = latest_price(p['symbol'])
            price = float(live_market) if live_market else close
            # PAPER excursion remains candle-based for deterministic backtests, while
            # current PnL/management decisions use the freshest available market price.
            update_trade_excursions(p,high,low)
            p['last_unrealized_pnl'] = ((price-float(p['entry_price']))*abs(float(p.get('amount') or 0))
                                        if side_long(p['side']) else
                                        (float(p['entry_price'])-price)*abs(float(p.get('amount') or 0)))
            p['last_price']=float(price)
        else:
            # REAL: excursion/MFE/MAE starts at the actual position lifetime.
            # Never feed historical candles from before the position opened.
            update_trade_excursions(p, float(price), float(price))
            p['last_unrealized_pnl']=float(p.get('margin',0))*(((price-float(p['entry_price']))/float(p['entry_price'])) if side_long(p['side']) else ((float(p['entry_price'])-price)/float(p['entry_price'])))*float(p['leverage'])
            p['last_price']=float(price)
        if _maybe_close_before_day_end(chat_id,p,price):
            continue

        entry=float(p['entry_price'])
        risk_distance=float(p.get('risk_distance') or 0.0)
        if risk_distance<=0: risk_distance=abs(entry-float(p.get('sl',entry)))
        current_r=((price-entry)/risk_distance if side_long(p['side']) else (entry-price)/risk_distance) if risk_distance>0 else 0.0

        # Hard SL/TP is always checked before any discretionary stop movement.
        exit_price=None; reason=None
        if s['trading_mode']=='PAPER' and not primary_df.empty:
            if side_long(p['side']):
                hit_tp=high>=float(p['tp']); hit_sl=low<=float(p['sl'])
            else:
                hit_tp=low<=float(p['tp']); hit_sl=high>=float(p['sl'])
            if hit_tp and hit_sl and PAPER_CONSERVATIVE_OHLC:
                exit_price=float(p['sl']); reason='SL (same candle)'
            elif hit_tp: exit_price=float(p['tp']); reason='TP'
            elif hit_sl: exit_price=float(p['sl']); reason='SL'

        if reason is None and s['filters'].get('trailing_stop',True) and risk_distance>0:
            favorable_price=(high if side_long(p['side']) else low) if s['trading_mode']=='PAPER' else (p.get('peak_favorable_price') or price)
            _apply_profit_protection(chat_id,s,p,favorable_price,price)
            # Re-read current R after a possible stop update.
            current_r=((price-entry)/risk_distance if side_long(p['side']) else (entry-price)/risk_distance)

        if reason is None:
            # Structural swing stop intentionally remains on the primary trading timeframe.
            if not primary_df.empty:
                _check_swing_trailing_stop(chat_id,s,p,price,primary_df)

        if reason is None:
            should_exit,wreasons=_weakness_exit_check(chat_id,s,p,current_r,management_df,price)
            if should_exit:
                exit_price=price; reason='مدیریت هوشمند (ضعف روند / کاهش ریسک)'; p['weakness_exit_reasons']=wreasons

        if reason:
            close_position(chat_id,p,exit_price,reason)
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
    """Turn internal strategy reasons into short, human trading language.
    The diagnostic log is for decision transparency, not for exposing indicator math.
    """
    r = str(reason or '').strip()
    if not r:
        return 'شرایط ورود هنوز کامل نشده'

    # Keep the explanation at the level a trader actually needs: what is missing,
    # not which indicator number failed.
    rules = [
        (r'داده کافی|داده بازار خالی|سطوح روز قبل هنوز آماده|یک روز کامل قبلی', 'هنوز داده یا سطح معتبر کافی برای تصمیم‌گیری نداریم'),
        (r'ظرفیت پوزیشن|محدودیت ریسک|ریسک به کارمزد|وضعیت ربات|توقف', 'فعلاً اجازه ورود از سمت مدیریت ریسک/ربات داده نمی‌شود'),
        (r'cooldown|دوره انتظار', 'ربات بعد از معامله قبلی در زمان انتظار است'),
        (r'R:R کافی نیست|نسبت سود به ضرر', 'ستاپ خوب به نظر می‌رسد، اما سود احتمالی به ریسک آن نمی‌ارزد'),
        (r'امتیاز کیفیت پایین', 'ستاپ شکل گرفته، ولی کیفیت کلی هنوز به حد ورود نرسیده'),
        (r'فاصله .* معتبر نیست|فاصله .* حد ضرر', 'برای این معامله حد ضرر منطقی پیدا نشد'),
        (r'کندل تأیید|قدرت بدنه|تأیید معتبر|برگشت تأیید نشده', 'قیمت به ناحیه مناسب نزدیک شده، اما تأیید نهایی هنوز نیامده'),
        (r'حجم .*کافی نیست|حجم .* تأیید', 'حرکت دیده می‌شود، ولی قدرت لازم برای تأیید آن هنوز کافی نیست'),
        (r'شکست جدیدی ثبت نشد|شکست معتبر ثبت نشده', 'هنوز شکست معناداری برای ورود شکل نگرفته'),
        (r'شکست تأیید نشد|هم‌جهت نیست|خلاف جهت بازار', 'حرکت دیده شده با جهت کلی بازار هماهنگ نیست؛ ورود رد شد'),
        (r'روند ضعیف|شرایط روندی برقرار نیست', 'بازار هنوز روند واضحی برای ورود ندارد'),
        (r'Mean Reversion|محدوده میانگین|RSI خنثی|اشباع .*برگشت', 'بازار هنوز به نقطه مناسب برای برگشت نرسیده'),
        (r'ستاپ جدیدی ثبت نشد|ستاپ مناسب پیدا نشد|بدون Pullback|V2:', 'فعلاً ستاپ تمیز و قابل معامله‌ای شکل نگرفته'),
        (r'ACTIVE_SETUP|فرصت بازیابی', 'یک ستاپ قبلی زیر نظر است، اما ورود هنوز تأیید نشده'),
    ]
    import re as _re
    for pattern, label in rules:
        if _re.search(pattern, r, flags=_re.I):
            return label
    return 'هنوز شرایط کامل یک ورود کم‌ریسک فراهم نشده'


def _entry_diag_stage(item):
    """Map an internal scan result to a small human stage machine."""
    status = str(item.get('status') or '')
    reason = str(item.get('reason') or '')
    if status == 'entry_opened':
        return '🟢', 'سیگنال آماده', 'ورود انجام شد'
    if status in ('data_error', 'insufficient_data'):
        return '⚠️', 'داده ناقص', 'برای تصمیم‌گیری داده کافی نیست'
    if status in ('risk_blocked', 'blocked', 'execute_blocked', 'leader_guard_blocked'):
        if 'دوره انتظار' in reason or 'cooldown' in reason.lower():
            return '⏳', 'در انتظار', 'بعد از معامله قبلی هنوز زمان انتظار تمام نشده'
        return '🛑', 'ورود محافظت شد', 'قواعد محافظتی فعلاً اجازه ورود نمی‌دهند'
    r = reason.lower()
    if 'trade_plan' in str(item.get('stage','')).lower() or 'حد ضرر منطقی' in reason or 'rr' in r:
        return '❌', 'رد شد', 'طرح معامله کیفیت لازم را نداشت'
    if 'pullback' in r or 'پولبک' in reason or 'retest' in r or 'بازآزمایی' in reason:
        return '🔄', 'منتظر پولبک', 'حرکت انجام شده؛ منتظر برگشت امن به ناحیه ورودیم'
    if 'active_setup' in r or 'ستاپ قبلی' in reason or 'نزدیک' in reason:
        return '👀', 'نزدیک ورود', 'ستاپ در حال شکل‌گیری است و یک تأیید دیگر لازم دارد'
    if 'تأیید' in reason or 'confirmation' in r or 'قدرت' in reason or 'حجم' in reason:
        return '⏳', 'منتظر تأیید', 'ناحیه مناسب است ولی تأیید نهایی هنوز نیامده'
    if 'شکست' in reason or 'breakout' in r or 'روند' in reason:
        return '⏳', 'منتظر حرکت واضح', 'هنوز حرکت معناداری برای ورود تأیید نشده'
    if 'ستاپ' in reason or 'شرایط ورود' in reason or 'محدوده' in reason:
        return '💤', 'بدون ستاپ', 'فعلاً ناحیه و ساختار مناسبی برای معامله نداریم'
    return '💤', 'بدون ستاپ', 'فعلاً ورود تمیزی دیده نشده'


def _entry_diag_next_step(results):
    stages = [_entry_diag_stage(x)[1] for x in results if x.get('status') != 'entry_opened']
    if 'نزدیک ورود' in stages:
        return '👀 چند نماد به ورود نزدیک‌اند؛ ربات فقط منتظر تأیید لازم می‌ماند.'
    if 'منتظر پولبک' in stages:
        return '🔄 شکست‌هایی دیده شده؛ ربات وسط حرکت وارد نمی‌شود و منتظر پولبک می‌ماند.'
    if 'منتظر تأیید' in stages:
        return '⏳ ستاپ‌ها بررسی شده‌اند؛ هنوز تأیید نهایی برای ورود کم‌ریسک کامل نیست.'
    if 'منتظر حرکت واضح' in stages:
        return '⏳ بازار هنوز حرکت واضحی نداده؛ ورود اجباری نداریم.'
    return '🛡️ فعلاً ستاپ تمیزی نیست؛ ربات صبر می‌کند تا فرصت ارزشمندتری شکل بگیرد.'


def _entry_diag_direction(item):
    """Return the relevant LONG/SHORT context for a diagnostic row."""
    sig = str(item.get('signal') or '').upper()
    if sig == 'BUY':
        return '🟢 LONG'
    if sig == 'SELL':
        return '🔴 SHORT'
    sym = str(item.get('symbol') or '').upper()
    in_long = sym in SHARED_LONG_WATCHLIST
    in_short = sym in SHARED_SHORT_WATCHLIST
    if in_long and in_short:
        return '🟡 LONG/SHORT'
    if in_long:
        return '🟢 LONG'
    if in_short:
        return '🔴 SHORT'
    return '⚪️'


def _entry_diag_report(chat_id, results, elapsed, symbol_states=None, transitions=None):
    """Compact opportunity dashboard: show only active/non-idle opportunities."""
    s = get_session(chat_id)
    results = list(results or [])
    symbol_states = symbol_states or {}
    transitions = transitions or []
    opened = sum(1 for x in results if x.get('status') == 'entry_opened')
    data_issues = sum(1 for x in results if x.get('status') in ('data_error','insufficient_data'))
    tf = TF_DISPLAY.get(s.get('timeframe'), s.get('timeframe'))

    all_items = list(symbol_states.values()) or results
    # گزارش دوره‌ای باید همه نمادهای بررسی‌شده را نشان دهد؛ این کار اجازه می‌دهد
    # بعداً دقیقاً بفهمیم کدام فیلتر بیشتر از همه جلوی ورود را گرفته است.
    report_items = []
    for item in all_items:
        icon, stage, desc = _entry_diag_stage(item)
        report_items.append((item, icon, stage, desc))
    active_items = [x for x in report_items if x[2] not in ('بدون ستاپ', 'داده ناقص')]

    long_active = sum(1 for item, *_ in active_items if 'LONG' in _entry_diag_direction(item))
    short_active = sum(1 for item, *_ in active_items if 'SHORT' in _entry_diag_direction(item))
    confirm_wait = sum(1 for _, _, stage, _ in active_items if stage in ('منتظر تأیید', 'نزدیک ورود', 'منتظر حرکت واضح', 'در انتظار'))
    pullback_wait = sum(1 for _, _, stage, _ in active_items if stage == 'منتظر پولبک')

    lines = [
        '🧠 *داشبورد زنده فرصت‌ها*',
        '━━━━━━━━━━━━━━━━━━━━',
        f'⏱ گزارش دوره‌ای: هر ۱۰ دقیقه | تایم‌فریم: `{tf}`',
        f'🟢 LONG زیر نظر: `{len(SHARED_LONG_WATCHLIST)}` نماد',
        f'🔴 SHORT زیر نظر: `{len(SHARED_SHORT_WATCHLIST)}` نماد',
        f'🔎 مجموع مسیرهای بررسی: `{len(SHARED_LONG_WATCHLIST) + len(SHARED_SHORT_WATCHLIST)}`',
    ]
    if opened:
        lines.append(f'🟢 در این چرخه `{opened}` ورود انجام شد.')
    elif active_items:
        lines.append(f'📌 فرصت‌های فعال: `{len(active_items)}`')
    else:
        lines.append('💤 فعلاً فرصت فعال نداریم؛ وضعیت همه نمادهای بررسی‌شده پایین گزارش آمده است.')
    if data_issues:
        lines.append(f'⚠️ `{data_issues}` مورد مشکل داده داشت و در فهرست فرصت‌های فعال نمایش داده نشده است.')

    for item, icon, stage, desc in report_items:
        sym = item.get('symbol','?')
        direction = _entry_diag_direction(item)
        prev = item.get('previous_stage')
        change = ''
        if prev and prev != stage:
            change = f' | تغییر: {prev} → {stage}'
        lines.append(f'\n{icon} *{sym}* — {direction} — {stage}{change}\n   {desc}')

    if report_items:
        lines.append('\n━━━━━━━━━━━━━━━━━━━━')
        lines.append(f'📊 *خلاصه فرصت‌ها:* `{len(active_items)}` فعال | 🟢 LONG: `{long_active}` | 🔴 SHORT: `{short_active}`')
        lines.append(f'⏳ منتظر تأیید: `{confirm_wait}` | 🔄 منتظر پولبک: `{pullback_wait}`')

    # Only show transitions that are still relevant to the compact active dashboard.
    relevant_transitions = [t for t in transitions if not any(x in t for x in ('→ بدون ستاپ', '→ داده ناقص'))]
    if relevant_transitions:
        lines.append('\n*تغییرات مهم از گزارش قبل:*')
        for t in relevant_transitions[-5:]:
            lines.append(f'• `{t}`')

    if active_items:
        lines.append('\n' + _entry_diag_next_step([x[0] for x in active_items]))
    return '\n'.join(lines)

def _entry_diag_batch_update(chat_id, results):
    now = time.time()
    state = ENTRY_DIAG_STATE.setdefault(chat_id, {
        'no_entry_since': now,
        'last_report_at': 0.0,
        'last_entry_at': 0.0,
        'window_results': [],
        'symbol_states': {},
        'transitions': [],
    })
    if not results:
        return
    if not get_session(chat_id).get('entry_diag_enabled', True):
        return

    state.setdefault('symbol_states', {})
    state.setdefault('transitions', [])
    state.setdefault('window_results', [])
    state['window_results'].extend(results)
    state['window_results'] = state['window_results'][-300:]

    # Keep the latest state for every symbol, and remember only meaningful stage changes.
    for item in results:
        sym = item.get('symbol')
        if not sym:
            continue
        old = state['symbol_states'].get(sym)
        old_stage = old.get('stage') if old else None
        icon, stage, desc = _entry_diag_stage(item)
        updated = dict(item)
        updated['stage'] = stage
        updated['stage_icon'] = icon
        updated['stage_desc'] = desc
        updated['previous_stage'] = old_stage
        updated['last_update_at'] = now
        state['symbol_states'][sym] = updated
        if old_stage and old_stage != stage:
            state['transitions'].append(f'{sym}: {old_stage} → {stage}')
    state['transitions'] = state['transitions'][-20:]

    # Always report periodically, even if a trade happened. This makes the log a real
    # live dashboard instead of only a "why no entry" alarm.
    if not state.get('no_entry_since'):
        state['no_entry_since'] = now
    last_report = float(state.get('last_report_at', 0.0) or 0.0)
    if (not last_report) or now - last_report >= NO_ENTRY_REPORT_SECONDS:
        try:
            elapsed = now - float(state.get('no_entry_since') or now)
            report = _entry_diag_report(
                chat_id,
                list(state['window_results']),
                elapsed,
                symbol_states=state['symbol_states'],
                transitions=state['transitions'],
            )
            send_message(chat_id, report, parse_mode='Markdown')
            state['last_report_at'] = now
            state['window_results'] = []
            state['transitions'] = []
            state['no_entry_since'] = now
        except Exception as exc:
            logger.warning('ENTRY_DIAG telegram report failed chat=%s error=%s', chat_id, exc)


def _entry_diag_raw_summary(chat_id):
    """Show the exact, un-simplified 'reason' string behind every symbol's current
    non-entry state, grouped by frequency. The compact live dashboard collapses many
    different underlying reasons into the same generic 'بدون ستاپ' label; this view
    exists specifically to see which single condition is blocking the most symbols,
    instead of guessing which filter to loosen next.
    """
    state = ENTRY_DIAG_STATE.get(chat_id) or {}
    symbol_states = state.get('symbol_states') or {}
    if not symbol_states:
        return None
    from collections import Counter
    reason_counts = Counter()
    examples = {}
    for sym, item in symbol_states.items():
        if item.get('status') == 'entry_opened':
            continue
        raw_reason = str(item.get('reason') or '').strip() or f"(بدون متن دلیل — status={item.get('status')})"
        reason_counts[raw_reason] += 1
        examples.setdefault(raw_reason, []).append(sym)
    if not reason_counts:
        return None
    # Plain text (no Markdown parse_mode) on purpose — see note at the call site.
    lines = ['🧬 دلایل خام رد شدن (بدون ساده‌سازی، به ترتیب تکرار)', '━━━━━━━━━━━━━━━━━━━━']
    for reason, count in reason_counts.most_common(15):
        syms = '، '.join(examples[reason][:6])
        lines.append(f'• {count}x — {reason}\n   نمونه: {syms}')
    return '\n'.join(lines)


async def _scan_symbol_impl(http,chat_id,symbol,regime=None):
    s=get_session(chat_id)
    if not s['is_bot_active'] or s['daily_stopped']:
        return _entry_diag_result(chat_id, symbol, 'blocked', 'ربات متوقف است یا محدودیت روزانه فعال است', 'precheck')
    scan_generation=int(s.get('scan_generation',0))
    if time.time() < float(s['cooldowns'].get(symbol,0)):
        return _entry_diag_result(chat_id, symbol, 'blocked', 'نماد در دوره انتظار پس از معامله قبلی است', 'cooldown')
    tf=s['timeframe']; strat=s['active_strategy']; md={}
    try:
        klimit = 650 if tf in ('5min', '15min') else 160
        d=await get_klines_async(http,symbol,tf,klimit)
    except Exception as exc:
        return _entry_diag_result(chat_id, symbol, 'data_error', f'خطا در دریافت داده: {exc}', 'data')
    if d.empty:
        return _entry_diag_result(chat_id, symbol, 'data_error', 'داده بازار خالی دریافت شد', 'data')
    primary=calculate_indicators(d); primary_tf=tf; mode='single'
    # V2 نیاز به context واقعی HTF دارد: اجرای 5m/15m با 1h/4h،
    # 1h با 4h/1d و 4h با 1d بررسی می‌شود. HTF فقط filter است و execution نیست.
    if strat == 'dynamic':
        htf_specs = {
            '5min': [('1h', '1hour'), ('4h', '4hour')],
            '15min': [('1h', '1hour'), ('4h', '4hour')],
            '1hour': [('4h', '4hour'), ('1d', '1day')],
            '4hour': [('1d', '1day')],
        }.get(tf, [])
        for htf_key, htf_tf in htf_specs:
            try:
                hd=await get_klines_async(http,symbol,htf_tf,160)
                if not hd.empty:
                    md[htf_key]=calculate_indicators(hd)
            except Exception as exc:
                logger.warning('ENTRY_DIAG chat=%s symbol=%s htf=%s data_error=%s', chat_id, symbol, htf_tf, exc)
    s=get_session(chat_id)
    if not s['is_bot_active'] or s['daily_stopped'] or int(s.get('scan_generation',0)) != scan_generation:
        return _entry_diag_result(chat_id, symbol, 'blocked', 'وضعیت ربات هنگام اسکن تغییر کرد', 'state')
    if not risk_guard(chat_id):
        return _entry_diag_result(chat_id, symbol, 'risk_blocked', 'محدودیت ریسک اجازه ورود نمی‌دهد', 'risk')
    s=get_session(chat_id)
    if not s['is_bot_active'] or int(s.get('scan_generation',0)) != scan_generation:
        return _entry_diag_result(chat_id, symbol, 'blocked', 'وضعیت ربات پس از بررسی ریسک تغییر کرد', 'state')

    is_scalp_strategy = (strat == 'dynamic' and primary_tf in ('5min', '15min'))
    # برای 5m/15m، استراتژی هنوز بر اساس کندل بسته‌شده و PDH/PDL تصمیم می‌گیرد؛
    # فقط برای بازیابی یک ستاپ خیلی تازه، قیمت زنده جهت جلوگیری از تعقیب قیمت استفاده می‌شود.
    live_entry_price = None
    if is_scalp_strategy:
        try:
            live_entry_price = exchange_latest_price(chat_id, symbol) if s.get('trading_mode') == 'REAL' else latest_price(symbol)
        except Exception:
            live_entry_price = None
    # For dynamic V2 on 5m/15m, select the candidate and build its plan exactly
    # once. Previously the signal pass selected a candidate and the later plan
    # pass ran the selector again; if two families had the same BUY/SELL side,
    # the second pass could silently attach a different Entry/SL/TP to the first
    # signal's reason. The selected plan is now the single source of truth.
    grid_levels = await get_log_grid_levels(http, symbol) if is_scalp_strategy else None
    v2_scalp = bool(is_scalp_strategy and strat == 'dynamic' and get_v2_config(s.get('strategy_config')).get('v2_enabled', True))
    if v2_scalp:
        sig, plan, reason = _select_v2_setup(
            primary, md, primary_tf, s['filters'], s['strategy_config'],
            regime, grid_levels, live_entry_price
        )
        diagnostics = {}
    else:
        # regime این‌جا یعنی «روند به‌شدت یک‌طرفه» (EXTREME_ADX) و برای همه‌ی استراتژی‌ها اعمال
        # می‌شود تا هیچ سیگنال خلاف‌جهتی (نه فقط dynamic/sweep) وسط یک روند شدید باز نشود
        sig, reason = get_signal_with_reason(primary, md, mode, primary_tf, strat, s['filters'], s['strategy_config'], regime, live_price=live_entry_price)
        diagnostics = _breakout_filter_diagnostics(primary, s['filters'], s['strategy_config']) if (strat == 'dynamic' and not is_scalp_strategy) else {}
        plan = None

    if not sig:
        return _entry_diag_result(chat_id, symbol, 'no_signal', reason or 'شرایط ورود کامل نیست', 'signal', diagnostics=diagnostics)

    if not v2_scalp:
        # Legacy/non-scalp paths keep their existing planner unchanged.
        plan_strategy_type = 'dynamic' if (strat == 'dynamic' and s.get('strategy_config', {}).get('v2_enabled', True)) else ('liquidity_sweep' if is_scalp_strategy else strat)
        active_setup_index = None
        if is_scalp_strategy:
            m_active = re.search(r'ACTIVE_SETUP_INDEX=(\d+)', reason or '')
            if m_active:
                active_setup_index = int(m_active.group(1))
        plan, plan_reason = build_trade_plan(
            primary, sig, s['strategy_config'], plan_strategy_type,
            strategy_timeframe=primary_tf, grid_levels=grid_levels,
            setup_index=active_setup_index, live_price=live_entry_price,
            market_data_dict=md, filters=s['filters'], regime=regime
        )
        if not plan:
            return _entry_diag_result(chat_id, symbol, 'trade_plan_blocked', plan_reason or 'طرح معامله معتبر نشد', 'trade_plan', sig)
    else:
        plan_reason = reason or plan.get('reason', '')
        if not plan:
            return _entry_diag_result(chat_id, symbol, 'trade_plan_blocked', plan_reason or 'طرح معامله معتبر نشد', 'trade_plan', sig)
    entry=float(plan['entry']); sl=float(plan['sl']); tp=float(plan['tp'])
    # The V2 planner may return the same setup reason already emitted by the
    # signal engine. Do not concatenate duplicate evidence/EdgeProxy values.
    signal_reason = (reason or '').strip()
    planner_reason = (plan_reason or '').strip()
    if not planner_reason or planner_reason == signal_reason or planner_reason in signal_reason:
        full_reason = signal_reason
    elif signal_reason and signal_reason in planner_reason:
        full_reason = planner_reason
    else:
        full_reason = f"{signal_reason} | {planner_reason}"
    full_reason = full_reason[:500]

    # V2 Adaptive Opportunity Engine: V1 has already produced a valid plan.
    # This layer ranks the opportunity and can delay execution without weakening
    # any existing score/RR/risk gate.
    opportunity = build_opportunity(symbol, sig, plan, primary_tf, live_price=live_entry_price)
    update_pool(s, opportunity)
    rank = top_rank(s, opportunity)
    plan['confidence'] = opportunity['confidence']
    plan['opportunity_rank'] = opportunity['rank']
    plan['timing_state'] = opportunity['timing']
    full_reason = (
        f"{full_reason} | V2 Quality={opportunity['quality']} "
        f"Confidence={opportunity['confidence']:.1f} Rank={rank} "
        f"Timing={opportunity['timing']}"
    )[:500]
    if opportunity['timing'] != 'TRADE_NOW':
        return _entry_diag_result(
            chat_id, symbol, 'wait', opportunity['timing_reason'],
            'smart_timing', sig,
            diagnostics={
                'setup_family': opportunity['setup_family'],
                'quality': opportunity['quality'],
                'confidence': opportunity['confidence'],
                'rr': opportunity['rr'],
                'rank': rank,
                'timing': opportunity['timing'],
            }
        )

    guard_ok, guard_reason = await leader_correlation_guard(http, chat_id, symbol, primary, primary_tf, side=sig)
    if not guard_ok:
        return _entry_diag_result(chat_id, symbol, 'leader_guard_blocked', guard_reason, 'leader_guard', sig)
    ok=execute_trade(chat_id,symbol,'BUY (Long)' if sig=='BUY' else 'SELL (Short)',entry,sl,tp,full_reason,structural_tp=bool(plan.get('structural_target', False)))
    if ok:
        return _entry_diag_result(chat_id, symbol, 'entry_opened', full_reason, 'entry', sig)
    return _entry_diag_result(chat_id, symbol, 'execute_blocked', 'سیگنال ایجاد شد اما اجرای ورود موفق نشد', 'execute', sig)


async def scan_symbol(http, chat_id, symbol, regime=None):
    """Fail-safe scan wrapper: no symbol may disappear silently.

    The implementation is kept separate so every unexpected exception is
    converted into the same diagnostic result consumed by the scan dashboard.
    asyncio.CancelledError is intentionally re-raised so shutdown/cancellation
    semantics remain correct.
    """
    try:
        return await _scan_symbol_impl(http, chat_id, symbol, regime)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception('ENTRY_DIAG unexpected scan error chat=%s symbol=%s', chat_id, symbol)
        return _entry_diag_result(
            chat_id, symbol, 'scan_error',
            f'خطای غیرمنتظره در اسکن؛ نماد حذف نشد و باید بررسی شود: {type(exc).__name__}: {exc}',
            'scan_exception',
        )


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

    longs=[p for p in closed if side_long(p.get('side'))]
    shorts=[p for p in closed if not side_long(p.get('side'))]
    long_wins=sum(1 for p in longs if float(p.get('pnl_usdt',0) or 0)>0)
    short_wins=sum(1 for p in shorts if float(p.get('pnl_usdt',0) or 0)>0)
    long_net=sum(float(p.get('pnl_usdt',0) or 0) for p in longs)
    short_net=sum(float(p.get('pnl_usdt',0) or 0) for p in shorts)

    lines=['📊 *گزارش عملکرد '+label+'*','━━━━━━━━━━━━━━━━━━━━',f'معاملات بسته‌شده: `{n}`',f'موفق: `{len(wins)}` | ناموفق: `{len(losses)}`',f'نرخ موفقیت: `{(len(wins)/n*100 if n else 0):.1f}%`',f'سود/زیان خالص: `{net:+.2f} USDT`',f'Profit Factor: `{("∞" if pf==float("inf") else f"{pf:.2f}")}`']
    lines.append('━━━━━━━━━━━━━━━━━━━━')
    lines.append(f"🟢 خرید (Long): `{len(longs)}` معامله | موفق: `{long_wins}` | ناموفق: `{len(longs)-long_wins}` | نرخ موفقیت: `{(long_wins/len(longs)*100 if longs else 0):.1f}%` | سود/زیان: `{long_net:+.2f} USDT`")
    lines.append(f"🔴 فروش (Short): `{len(shorts)}` معامله | موفق: `{short_wins}` | ناموفق: `{len(shorts)-short_wins}` | نرخ موفقیت: `{(short_wins/len(shorts)*100 if shorts else 0):.1f}%` | سود/زیان: `{short_net:+.2f} USDT`")
    if rvals:
        lines.append('━━━━━━━━━━━━━━━━━━━━')
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
    tf=s['timeframe']
    d=get_klines(symbol,tf,160)
    if d.empty:
        return f'❌ داده کافی برای تحلیل `{symbol}` پیدا نشد.', None
    d=calculate_indicators(d); c=d.iloc[-2]
    a,r1=strategy_trend_following(d,tf,s['filters'],s['strategy_config'])
    b,r2=strategy_breakout(d,s['filters'],s['strategy_config'])
    m,r3=strategy_mean_reversion(d,s['filters'],s['strategy_config'])

    close=float(c.close); ema20=float(c.ema20); ema50=float(c.ema50)
    adx=float(c.adx or 0); plus_di=float(c.plus_di or 0); minus_di=float(c.minus_di or 0)

    if close>ema20>ema50 and plus_di>minus_di and adx>=MARKET_REGIME_MIN_ADX:
        trend_text='📈 صعودی'
    elif close<ema20<ema50 and minus_di>plus_di and adx>=MARKET_REGIME_MIN_ADX:
        trend_text='📉 نزولی'
    else:
        trend_text='➡️ رنج (بدون روند مشخص)'

    good_entry=bool(a or b or m)
    if good_entry:
        strategy_text='✅ موقعیت مناسب برای ورود بر اساس استراتژی'
    else:
        reason=r1 or r2 or r3 or 'شرایط استراتژی هنوز کامل نشده است'
        strategy_text=f'⚠️ موقعیت مناسب ورود نیست\n_({reason})_'

    live_price=latest_price(symbol)
    price_to_show=live_price if live_price is not None else close

    text = (
        f"🔍 *تحلیل {symbol}*\n\n"
        f"💰 قیمت لحظه‌ای: `{fmt(price_to_show)}`\n"
        f"⏱ تایم‌فریم: `{TF_DISPLAY.get(s['timeframe'],s['timeframe'])}`\n"
        f"📊 روند: {trend_text}\n"
        f"🎯 وضعیت نسبت به استراتژی: {strategy_text}"
    )
    keyboard = {'inline_keyboard': [
        [{'text':'📈 چارت در TradingView','url':tradingview_chart_url(symbol, tf)}],
        [{'text':'🏠 منوی اصلی','callback_data':'/menu'}],
    ]}
    return text, keyboard


def menu(chat_id,message_id=None):
    s=get_session(chat_id)
    bal=exchange_balance(chat_id) if s['trading_mode']=='REAL' else s['paper_balance']
    maxp=s['max_open_positions'] if s['max_open_positions']>0 else '∞'
    max_same=s.get('max_same_direction_positions',0)
    max_same_disp = max_same if max_same>0 else '∞'
    dir_cd = s.get('same_direction_entry_cooldown_seconds',0)
    diag = "🟢 فعال" if s.get('entry_diag_enabled', True) else "🔴 خاموش"
    text=f"📊 *پنل اصلی ربات*\n\n🟢 اسکن: `{'فعال' if s['is_bot_active'] else 'متوقف'}`\n💳 حساب: `{'واقعی' if s['trading_mode']=='REAL' else 'کاغذی'}`  |  ⏱ تایم‌فریم: `{TF_DISPLAY.get(s['timeframe'],s['timeframe'])}`\n📈 استراتژی: `{'پویا (دوطرفه)' if s['active_strategy']=='dynamic' else s['active_strategy']}`\n💰 موجودی: `{bal:.2f} USDT`  |  ⚙️ مارجین: `{s['trade_amount_usdt']:.0f} USDT`\n📌 پوزیشن‌های باز: `{maxp}`  |  🔍 لاگ ورود: `{diag}`\n🛡 ریسک هر معامله: `{s['risk_per_trade_pct']:.2f}%`  |  حد ضرر روزانه: `{s['daily_loss_limit_pct']:.2f}%`\n🧭 سقف هم‌جهت هم‌زمان: `{max_same_disp}`  |  فاصله ورود هم‌جهت: `{dir_cd:.0f}s`\n\nاز منوی زیر بخش موردنظر را انتخاب کن:"
    send_message(chat_id,text,get_main_menu_keyboard(s['is_bot_active'], s.get('entry_diag_enabled', True), is_admin(chat_id)),message_id)


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
    """
    توجه: این تابع فقط تنظیمات استراتژی (strategy_config) را بر اساس تایم‌فریم
    فعلی همین اکانت بازسازی و اسکن را دوباره فعال می‌کند. عمداً importlib.reload
    حذف شد — در بات چندکاربره‌ای که چند اکانت روی یک پردازه اجرا می‌شوند، بازخوانی
    زنده‌ی ماژول strategy نه اثر واقعی داشت (چون bot.py توابع را یک‌بار در ابتدای
    اجرا import کرده و دیگر آپدیت نمی‌شدند) و نه بی‌خطر بود (می‌توانست هم‌زمان با
    اجرای اسکن سایر اکانت‌ها تداخل ایجاد کند). timeframe و تنظیمات این اکانت دست
    نخورده باقی می‌ماند؛ اگر بعد از این دکمه بازهم تنظیمات به‌طور کامل به حالت
    پیش‌فرض برگشت، علتش خارج از این تابع است — احتمالاً ری‌استارت کل پردازه/کانتینر
    میزبان و نبودِ دیسک دائمی برای BOT_DB_PATH (به هشدار init_db مراجعه کنید).
    """
    try:
        s = get_session(chat_id)
        s['strategy_config'] = get_timeframe_preset(s.get('timeframe', '5min'))
        save_session(chat_id)
        start_scan(chat_id, message_id)
        send_message(chat_id, "🔄 *تنظیمات استراتژی بر اساس تایم‌فریم فعلی بازسازی شد و اسکن فعال گردید.*")
    except Exception as exc:
        send_message(chat_id, f"❌ خطا در بازسازی تنظیمات استراتژی: `{exc}`")


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


MARKET_REPORT_SYMBOLS = ['BTC','ETH','SOL','BNB','XRP','DOGE','ADA','AVAX','LINK','DOT']
# --- رژیم «اجماع فوری» - همان روش و همان آستانه‌ی گزارش «وضعیت بازار»، ولی وصل به --------
# تصمیم‌گیری معامله. برخلاف MARKET_REGIME_CACHE (که فقط BTC/ETH را روی 4 ساعته با آستانه‌ی
# خیلی سخت‌گیرانه می‌بیند)، این یکی همان ۱۰ ارز برتر و همان تایم‌فریم معاملاتی کاربر را
# می‌بیند - یعنی دقیقاً همان چیزی که خودِ کاربر در «وضعیت بازار» می‌بیند، و با همان قانون
# اکثریت ساده (>=۵۰٪) که آنجا هم استفاده می‌شود. یعنی هر وقت «وضعیت بازار» صعودی/نزولی
# اعلام شود، دقیقاً همان لحظه ورود خلاف‌جهت روی همه‌ی نمادها بلاک می‌شود؛ فقط وقتی بازار
# رنج/نامشخص باشد (نه اکثریت صعودی نه نزولی) هر دو جهت آزاد هستند.
TIMEFRAME_REGIME_TTL = float(os.environ.get('TIMEFRAME_REGIME_TTL_SECONDS', '150'))
TIMEFRAME_REGIME_MIN_SYMBOLS = int(os.environ.get('TIMEFRAME_REGIME_MIN_SYMBOLS', '8'))
TIMEFRAME_REGIME_CACHE: Dict[str, Dict[str, Any]] = {}


async def _market_snapshot_async(http, symbol, tf):
    try:
        d = await get_klines_async(http, symbol, tf, 160)
        if d is None or d.empty or len(d) < 60: return None
        d = calculate_indicators(d); c = d.iloc[-2]
        close = float(c.close); ema20 = float(c.ema20); ema50 = float(c.ema50)
        score = 1 if close > ema50 and ema20 >= ema50 else (-1 if close < ema50 and ema20 <= ema50 else 0)
        return score
    except Exception:
        return None


async def refresh_timeframe_regime(http, timeframe):
    """رژیم اجماع فوری را برای یک تایم‌فریم مشخص برمی‌گرداند: 'BULLISH'/'BEARISH'/None (کش‌شده).
    دقیقاً همان فرمول market_report(): اکثریت ساده (>=۵۰٪) از همان ۱۰ ارز، نه اجماع افراطی."""
    tf = timeframe
    now = time.time()
    c = TIMEFRAME_REGIME_CACHE.get(tf)
    if c and now - c['ts'] < TIMEFRAME_REGIME_TTL:
        return c['extreme']
    scores = await asyncio.gather(*[_market_snapshot_async(http, sym, tf) for sym in MARKET_REPORT_SYMBOLS])
    scores = [x for x in scores if x is not None]
    extreme = None
    if len(scores) >= TIMEFRAME_REGIME_MIN_SYMBOLS:
        bullish = sum(1 for x in scores if x > 0)
        bearish = sum(1 for x in scores if x < 0)
        total = len(scores)
        # 5/10 یا حتی 6/10 فقط «تمایل» است و نباید هیچ مسیری را ببندد.
        # برای تبدیل اجماع به محافظ قوی، حداقل 70% و برتری حداقل 3 نماد لازم است.
        strong_share = 0.70
        if bullish > bearish and bullish >= total * strong_share and (bullish - bearish) >= 3:
            extreme = 'BULLISH'
        elif bearish > bullish and bearish >= total * strong_share and (bearish - bullish) >= 3:
            extreme = 'BEARISH'
    TIMEFRAME_REGIME_CACHE[tf] = {'ts': now, 'extreme': extreme}
    return extreme


def combine_extreme_regime(macro, micro):
    """اگر با هم تناقض داشتند (نادر) به‌جای بلاک‌کردن اشتباه، خنثی در نظر گرفته می‌شود."""
    if macro and micro and macro != micro:
        return None
    return macro or micro


def market_report(chat_id):
    s = get_session(chat_id)
    tf = s['timeframe']
    symbols = MARKET_REPORT_SYMBOLS
    results = []
    with ThreadPoolExecutor(max_workers=min(6, len(symbols))) as ex:
        futures = [ex.submit(_market_snapshot, sym, tf) for sym in symbols]
        for f in as_completed(futures):
            item = f.result()
            if item: results.append(item)
    if not results:
        return '❌ داده کافی برای ساخت داشبورد بازار دریافت نشد.'
    total = len(results)
    bullish = sum(1 for x in results if x['score'] > 0)
    bearish = sum(1 for x in results if x['score'] < 0)
    ranged = total - bullish - bearish

    bull_share = bullish / total if total else 0.0
    bear_share = bearish / total if total else 0.0
    if bullish > bearish and bull_share >= 0.70 and (bullish - bearish) >= 3:
        overall = '🟢 بازار تمایل صعودی قوی دارد؛ با این حال مسیر مخالف کاملاً بسته نیست.'
    elif bearish > bullish and bear_share >= 0.70 and (bearish - bullish) >= 3:
        overall = '🔴 بازار تمایل نزولی قوی دارد؛ با این حال مسیر مخالف کاملاً بسته نیست.'
    elif bullish > bearish and bull_share >= 0.60:
        overall = '🟡 بازار تمایل صعودی دارد، اما اجماع هنوز برای بستن Short کافی نیست.'
    elif bearish > bullish and bear_share >= 0.60:
        overall = '🟡 بازار تمایل نزولی دارد، اما اجماع هنوز برای بستن Long کافی نیست.'
    else:
        overall = '⚪️ بازار دوطرفه/خنثی است؛ هر دو مسیر آزاد هستند و کیفیت خود ستاپ تصمیم می‌گیرد.'

    return (
        '🌐 *داشبورد بازار*\n'
        f"⏱ تایم‌فریم: `{TF_DISPLAY.get(tf, tf)}`\n\n"
        f"{overall}\n"
        f"📊 از بین {total} ارز بررسی‌شده: {bullish} صعودی، {bearish} نزولی، {ranged} رنج"
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


def manual_signal_scan(chat_id, symbol=None):
    """بررسی دستی یک نماد انتخابی کاربر با منطق سیگنال فعلی."""
    s = get_session(chat_id)
    tf = s.get('timeframe', '5min')
    symbols = [symbol.upper()] if symbol else scan_watchlist_for_timeframe(tf)
    results = []
    send_message(chat_id, f"⏳ لطفاً منتظر بمانید...\nدر حال بررسی {len(symbols)} نماد با تایم‌فریم {TF_DISPLAY.get(tf, tf)}")
    async def _run():
        async with aiohttp.ClientSession() as http:
            for sym in symbols:
                try:
                    df = await get_klines_async(http, sym, tf, 180)
                    if df is None or df.empty or len(df) < 80:
                        continue
                    ind = calculate_indicators(df)
                    strategy_type = s.get('active_strategy', 'dynamic')
                    md = {}
                    if strategy_type == 'dynamic':
                        htf_specs = {
                            '5min': [('1h', '1hour'), ('4h', '4hour')],
                            '15min': [('1h', '1hour'), ('4h', '4hour')],
                            '1hour': [('4h', '4hour'), ('1d', '1day')],
                            '4hour': [('1d', '1day')],
                        }.get(tf, [])
                        for htf_key, htf_tf in htf_specs:
                            try:
                                hd = await get_klines_async(http, sym, htf_tf, 160)
                                if hd is not None and not hd.empty:
                                    md[htf_key] = calculate_indicators(hd)
                            except Exception:
                                continue
                    sig, reason = get_signal_with_reason(
                        ind, md, 'single', tf, strategy_type,
                        s.get('filters'), s.get('strategy_config', STRATEGY_DEFAULTS)
                    )
                    if sig not in ('BUY','SELL'):
                        continue
                    plan, _plan_reason = build_trade_plan(
                        ind, sig, s.get('strategy_config', STRATEGY_DEFAULTS), strategy_type,
                        strategy_timeframe=tf, market_data_dict=md, filters=s.get('filters')
                    )
                    if plan:
                        results.append((sym, sig, plan, reason))
                except Exception:
                    continue
    try:
        asyncio.run(_run())
    except RuntimeError:
        loop = asyncio.new_event_loop(); loop.run_until_complete(_run()); loop.close()
    if not results:
        send_message(chat_id, '❌ در بررسی فعلی، نمادی مطابق شرایط استراتژی آماده ورود پیدا نشد.')
        return
    lines = ['🚀 *سیگنال‌های آماده ورود دستی*']
    for sym, sig, plan, reason in results[:5]:
        lines.append(
            f"\n{'🟢 LONG' if sig=='BUY' else '🔴 SHORT'} `{sym}`"
            f"\nورود: `{plan.get('entry')}`"
            f"\nحد ضرر: `{plan.get('sl')}`"
            f"\nحد سود: `{plan.get('tp')}`"
            f"\nدلیل: {reason}"
        )
    send_message(chat_id, '\n'.join(lines))


def process_command(cmd,chat_id,message_id=None):
    if cmd == '/backtest_start':
        start_backtest_flow(chat_id); return
    if cmd == '/scan_signal_start':
        s=get_session(chat_id); s['user_state']='WAIT_SCAN_SYMBOL'; save_session(chat_id)
        send_message(chat_id,'🔍 لطفاً نماد مورد نظر برای بررسی با استراتژی فعال را وارد کنید.\nمثال: BTC یا ETH')
        return
    # Admin revenue / fee management commands.
    if str(cmd).startswith('/set_fee '):
        admin_set_fee_command(chat_id, cmd)
        return
    if cmd in ('/admin_fee_report','/admin_fee_day','/admin_fee_week','/admin_fee_month'):
        if not is_admin(chat_id):
            send_message(chat_id,'⛔ دسترسی ادمین ندارید.'); return
        period={'/admin_fee_report':'all','/admin_fee_day':'day','/admin_fee_week':'week','/admin_fee_month':'month'}[cmd]
        edit_page(chat_id, admin_fee_report(period), get_admin_fee_menu_keyboard(), message_id)
        return
    if cmd == '/admin_fee_menu':
        if not is_admin(chat_id):
            send_message(chat_id,'⛔ دسترسی ادمین ندارید.'); return
        edit_page(chat_id, admin_fee_report('all'), get_admin_fee_menu_keyboard(), message_id)
        return
    if cmd == '/admin_panel':
        if not is_admin(chat_id):
            send_message(chat_id,'⛔ دسترسی ادمین ندارید.'); return
        edit_page(chat_id, '👑 *پنل مدیریت*\n\nاز منوی زیر بخش موردنظر را انتخاب کن:', get_admin_panel_keyboard(), message_id)
        return
    if cmd in ('/admin_users_list','/users'):
        if not is_admin(chat_id):
            send_message(chat_id,'⛔ دسترسی ادمین ندارید.'); return
        edit_page(chat_id, admin_users_report(), get_admin_panel_keyboard(), message_id)
        return
    if cmd == '/admin_set_fee_prompt':
        if not is_admin(chat_id):
            send_message(chat_id,'⛔ دسترسی ادمین ندارید.'); return
        s=get_session(chat_id); s['user_state']='WAIT_ADMIN_SET_FEE'; save_session(chat_id)
        send_message(chat_id, '⚙️ *تنظیم نرخ کارمزد کاربر*\n\nشناسه چت کاربر و درصد کارمزد را با فاصله ارسال کنید.\nمثال: `123456789 10`')
        return
    if str(cmd).startswith('/user '):
        if not is_admin(chat_id):
            send_message(chat_id,'⛔ دسترسی ادمین ندارید.'); return
        try:
            target_id=int(str(cmd).split()[1])
            send_message(chat_id, admin_user_detail(chat_id, target_id), parse_mode='Markdown')
        except Exception:
            send_message(chat_id,'فرمت: `/user USER_CHAT_ID`', parse_mode='Markdown')
        return
    if cmd in ('/fee_menu','/my_fees','/my_fee_report','/fee_today','/fee_week','/fee_month','/fee_all'):
        period={'/fee_today':'day','/fee_week':'week','/fee_month':'month'}.get(cmd,'all')
        edit_page(chat_id, fee_report(chat_id,period), get_fee_menu_keyboard(), message_id)
        return
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
        if PAPER_ONLY:
            send_message(chat_id,'🟢 این Build برای تست PAPER قفل شده و ورود REAL عمداً غیرفعال است.')
            return
        if s['paper_positions']: send_message(chat_id,'❌ ابتدا تمام پوزیشن‌های فعلی را ببندید.'); return
        if not get_exchange(chat_id): send_message(chat_id,'❌ حساب CoinEx این کاربر در `COINEX_ACCOUNTS_JSON` تنظیم نشده است.'); return
        bal=exchange_balance(chat_id)
        s['trading_mode']='REAL'; s['is_bot_active']=False; s['daily_start_equity']=bal; s['daily_start_date']=time.strftime('%Y-%m-%d',time.gmtime()); s['daily_stopped']=False; save_session(chat_id); edit_page(chat_id,f'🔴 موجودی REAL: `{bal:.2f} USDT`\n\n⚙️ مارجین هر معامله:',get_margin_keyboard(),message_id); return
    if cl.startswith('/set_bal_'):
        v=float(cl.replace('/set_bal_','')); s['paper_balance']=v; s['daily_start_equity']=v; s['daily_start_date']=time.strftime('%Y-%m-%d',time.gmtime()); s['daily_stopped']=False; save_session(chat_id); edit_page(chat_id,'✅ موجودی ثبت شد.\n\n⚙️ مارجین:',get_margin_keyboard(),message_id); return
    if cl.startswith('/set_margin_'): s['trade_amount_usdt']=float(cl.replace('/set_margin_','')); save_session(chat_id); edit_page(chat_id,'⚙️ اهرم:',get_leverage_keyboard(),message_id); return
    if cl.startswith('/set_lev_'): s['leverage']=int(cl.replace('/set_lev_','')); save_session(chat_id); edit_page(chat_id,'⚙️ حداکثر پوزیشن:',get_max_positions_keyboard(),message_id); return
    if cl.startswith('/set_max_same_'):
        s['max_same_direction_positions']=max(0,int(cl.replace('/set_max_same_',''))); save_session(chat_id)
        send_message(chat_id, f"✅ حداکثر پوزیشن هم‌جهت هم‌زمان: `{s['max_same_direction_positions'] or '∞'}`"); menu(chat_id); return
    if cl.startswith('/set_dir_cooldown_'):
        s['same_direction_entry_cooldown_seconds']=max(0.0,float(cl.replace('/set_dir_cooldown_',''))); save_session(chat_id)
        send_message(chat_id, f"✅ فاصله حداقل بین ورودهای هم‌جهت: `{s['same_direction_entry_cooldown_seconds']:.0f} ثانیه`"); menu(chat_id); return
    if cl.startswith('/set_max_'):
        s['max_open_positions']=int(cl.replace('/set_max_','')); save_session(chat_id)
        edit_page(chat_id, "⏱ تایم‌فریم و استراتژی موردنظر را انتخاب کنید:", get_timeframe_keyboard(), message_id); return
    if cl.startswith('/set_tf_'):
        tf_map={'/set_tf_5m':'5min','/set_tf_15m':'15min','/set_tf_1h':'1hour','/set_tf_4h':'4hour'}
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
    if cl == '/entry_diag_log':
        window = list((ENTRY_DIAG_STATE.get(chat_id) or {}).get('window_results') or [])
        if not window:
            edit_page(chat_id, '📋 هنوز داده‌ی تشخیصی ثبت نشده است.', get_entry_diag_keyboard(s.get('entry_diag_enabled', True)), message_id); return
        data_errs = [x for x in window if x.get('status') in ('data_error', 'insufficient_data')]
        lines = ['📋 آخرین موارد خطای داده (نماد مشخص)', '━━━━━━━━━━━━━━━━━━━━']
        if data_errs:
            seen_syms = {}
            for x in reversed(data_errs):
                seen_syms.setdefault(x.get('symbol', '?'), x.get('reason', ''))
            for sym, reason in list(seen_syms.items())[:20]:
                lines.append(f'• {sym} — {reason}')
        else:
            lines.append('موردی یافت نشد.')
        edit_page(chat_id, '\n'.join(lines), get_entry_diag_keyboard(s.get('entry_diag_enabled', True)), message_id, parse_mode=None); return
    if cl == '/entry_diag_raw':
        summary = _entry_diag_raw_summary(chat_id)
        if not summary:
            edit_page(chat_id, '📋 هنوز داده‌ی تشخیصی ثبت نشده است.', get_entry_diag_keyboard(s.get('entry_diag_enabled', True)), message_id); return
        # Raw reason strings come straight from the strategy/exception layer and can
        # contain unescaped Markdown-special characters (brackets, parentheses, stray
        # backticks/underscores) that make Telegram reject the Markdown parse. When that
        # happens, both the edit AND the sendMessage fallback fail silently — the button
        # looks like it does nothing. This view is meant to be raw text anyway, so send
        # it with no parse_mode instead of trying to escape every possible character.
        edit_page(chat_id, summary, get_entry_diag_keyboard(s.get('entry_diag_enabled', True)), message_id, parse_mode=None); return
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
    # NOTE: keywords on the right must ALSO have ZWNJ stripped, otherwise a keyword like
    # 'پوزیشن‌ها' (which still contains the ZWNJ char) can never match against `c` with
    # ZWNJ removed — that comparison was always False, silently disabling this fallback.
    _c_norm = c.replace('\u200c', '')
    if cl in ('/open_positions','/positions','positions') or any(x.replace('\u200c','') in _c_norm for x in ('پوزیشن‌ها','پوزیشنهای باز','پوزیشن باز','پوزیشن')):
        _send_or_edit_positions_view(chat_id, message_id=message_id)
        return
    if cl in ('/add_long_symbol','/remove_long_symbol','/add_short_symbol','/remove_short_symbol'):
        s['user_state']=cl.upper(); save_session(chat_id)
        send_message(chat_id,'📝 نام نماد را ارسال کنید (مثال BTC)')
        return

    if cl in ('/manage_watchlist','/watchlist_list'):
        long_list='، '.join(SHARED_LONG_WATCHLIST)
        short_list='، '.join(SHARED_SHORT_WATCHLIST)
        edit_page(
            chat_id,
            f"📋 *واچ‌لیست فعال*\n\n"
            f"🟢 *Long* ({len(SHARED_LONG_WATCHLIST)} نماد):\n`{long_list}`\n\n"
            f"🔴 *Short* ({len(SHARED_SHORT_WATCHLIST)} نماد):\n`{short_list}`",
            get_watchlist_manage_keyboard(),message_id); return
    if cl.startswith('/manage_'):
        sym=cl.replace('/manage_','').upper()
        for p in s['paper_positions']:
            if p['symbol']==sym:
                send_message(chat_id,format_trade_status(p),trade_action_keyboard(sym, miniapp_chart_url(sym, p.get('timeframe','5min')), p.get('timeframe','5min'))); return
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
    if cl=='/emergency_close_all':
        n = len(s['paper_positions'])
        if n==0: send_message(chat_id,'❌ پوزیشن بازی وجود ندارد.'); return
        send_message(chat_id,f'🆘 *تأیید بستن اضطراری*\n\n{n} پوزیشن فوراً با قیمت بازار بسته می‌شود و اسکن متوقف می‌شود.',get_confirm_emergency_close_keyboard()); return
    if cl=='/confirm_emergency_close_all':
        # بدون تأخیر: اسکن را متوقف می‌کند تا معامله جدیدی باز نشود و همه پوزیشن‌ها را می‌بندد
        stop_scan(chat_id, 'emergency-close-all')
        n = len(s['paper_positions'])
        for p in s['paper_positions'][:]: close_position(chat_id,p,reason='emergency_close_all')
        send_message(chat_id, f'🆘 *بستن اضطراری انجام شد*\n\n{n} پوزیشن بسته شد و اسکن متوقف شد.')
        return
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

    # Nothing matched above: this used to fail completely silently, which is exactly
    # the kind of hidden bug that's hardest to diagnose from the user side (a button
    # that "does nothing"). Log it so a stale-deploy / renamed-callback mismatch shows
    # up in server logs instead of vanishing.
    logger.warning('process_command: unmatched command cl=%r chat=%s', cl, chat_id)


def start_backtest_flow(chat_id):
    s=get_session(chat_id)
    s['user_state']='WAIT_BACKTEST_SYMBOL'
    save_session(chat_id)
    send_message(chat_id,'🧪 تست استراتژی\n\nنماد را وارد کنید (مثال: BTC/USDT:USDT):')


def run_user_backtest(chat_id):
    s=get_session(chat_id)
    try:
        send_message(chat_id,'⏳ لطفاً منتظر بمانید...\nدر حال دریافت داده‌های تاریخی از سرور و آماده‌سازی تست.')
        df=fetch_ohlcv_coinex(s['backtest_symbol'], s['backtest_tf'], s['backtest_start'], s['backtest_end'])
        send_message(chat_id,'✅ داده‌ها دریافت شد.\nدر حال اجرای تست استراتژی...')
        result=run_backtest(df, strategy_type=s.get('active_strategy','dynamic'), side='both', strategy_timeframe=s.get('timeframe','1hour'))
        send_message(chat_id, f'🧪 نتیجه تست\n\nنماد: {s["backtest_symbol"]}\nتعداد معاملات: {len(result.get("trades",[])) if isinstance(result,dict) else "انجام شد"}')
    except Exception as e:
        send_message(chat_id,f'❌ خطا در تست: {e}')
    finally:
        s['user_state']=None
        save_session(chat_id)


def handle_text(chat_id,text):
    raw=(text or '').strip()
    fixed_buttons={
        '🏠 منوی اصلی':'/menu', 'منوی اصلی':'/menu',
        '🔄 پوزیشن‌های باز':'/open_positions', 'پوزیشن‌های باز':'/open_positions',
        '🔄 پوزیشن‌ها':'/open_positions', 'پوزیشن‌ها':'/open_positions',
        '📈 گزارش عملکرد کلی':'/performance', 'گزارش عملکرد کلی':'/performance',
        '📊 وضعیت بازار':'/market_report', 'وضعیت بازار':'/market_report',
        '⚙️ تنظیمات معامله':'/check_wizard', 'تنظیمات معامله':'/check_wizard',
        '📋 واچ‌لیست':'/manage_watchlist', 'واچ‌لیست':'/manage_watchlist',
        '❌ بستن همه':'/close_all_prompt', 'بستن همه':'/close_all_prompt',
        '🆘 بستن اضطراری همه':'/emergency_close_all', 'بستن اضطراری همه':'/emergency_close_all',
        '🖐 معامله دستی':'/manual_trade', '🧪 تست استراتژی':'/backtest_start', '🔍 پیشنهاد نماد با استراتژی فعال':'/scan_signal_start', 'معامله دستی':'/manual_trade',
    }
    if raw in fixed_buttons:
        process_command(fixed_buttons[raw],chat_id); return

    s=get_session(chat_id); val=raw.upper()
    current_state = str(s.get('user_state') or '')

    if current_state in ('/ADD_LONG_SYMBOL','/REMOVE_LONG_SYMBOL','/ADD_SHORT_SYMBOL','/REMOVE_SHORT_SYMBOL'):
        sym=raw.upper().replace('USDT','')
        if current_state=='/ADD_LONG_SYMBOL' and sym not in SHARED_LONG_WATCHLIST: SHARED_LONG_WATCHLIST.append(sym)
        elif current_state=='/REMOVE_LONG_SYMBOL' and sym in SHARED_LONG_WATCHLIST: SHARED_LONG_WATCHLIST.remove(sym)
        elif current_state=='/ADD_SHORT_SYMBOL' and sym not in SHARED_SHORT_WATCHLIST: SHARED_SHORT_WATCHLIST.append(sym)
        elif current_state=='/REMOVE_SHORT_SYMBOL' and sym in SHARED_SHORT_WATCHLIST: SHARED_SHORT_WATCHLIST.remove(sym)
        s['user_state']=None; save_session(chat_id)
        send_message(chat_id,'✅ واچ‌لیست اصلاح شد.')
        return

    if current_state == 'WAIT_SCAN_SYMBOL':
        s['user_state']=None; save_session(chat_id)
        sym=raw.upper().replace('USDT','')+'USDT' if '/' not in raw else raw.upper()
        manual_signal_scan(chat_id, sym)
        return

    if current_state == 'WAIT_BACKTEST_SYMBOL':
        s['backtest_symbol']=raw.upper()
        s['user_state']='WAIT_BACKTEST_TF'
        save_session(chat_id)
        send_message(chat_id,'⏱ تایم‌فریم را وارد کنید (5m / 15m / 1h / 4h):')
        return
    if current_state == 'WAIT_BACKTEST_TF':
        s['backtest_tf']=raw
        s['user_state']='WAIT_BACKTEST_START'
        save_session(chat_id)
        send_message(chat_id,'📅 تاریخ شروع را وارد کنید (YYYY-MM-DD):')
        return
    if current_state == 'WAIT_BACKTEST_START':
        s['backtest_start']=raw
        s['user_state']='WAIT_BACKTEST_END'
        save_session(chat_id)
        send_message(chat_id,'📅 تاریخ پایان را وارد کنید (YYYY-MM-DD):')
        return
    if current_state == 'WAIT_BACKTEST_END':
        s['backtest_end']=raw
        save_session(chat_id)
        run_user_backtest(chat_id)
        return

    if current_state == 'WAIT_ADMIN_SET_FEE':
        s['user_state'] = None
        save_session(chat_id)
        if not is_admin(chat_id):
            send_message(chat_id, '⛔ دسترسی ادمین ندارید.'); return
        parts = raw.split()
        if len(parts) != 2:
            send_message(chat_id, 'فرمت نامعتبر است. مثال: `123456789 10`', get_admin_fee_menu_keyboard()); return
        try:
            target_id = int(parts[0]); rate = float(parts[1])
            set_user_fee_rate(target_id, rate)
            send_message(chat_id, f'✅ نرخ کارمزد کاربر `{target_id}` روی `{rate:.2f}%` تنظیم شد.', get_admin_fee_menu_keyboard())
        except Exception:
            send_message(chat_id, '⚠️ مقادیر وارد شده نامعتبر است.', get_admin_fee_menu_keyboard())
        return

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
        send_message(chat_id, f"✅ حد ضرر پوزیشن `{sym}` به `{fmt(new_sl)}` تغییر یافت.", trade_action_keyboard(sym, timeframe=pos.get('timeframe','5min')))
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
        send_message(chat_id, f"✅ حد سود پوزیشن `{sym}` به `{fmt(new_tp)}` تغییر یافت.", trade_action_keyboard(sym, timeframe=pos.get('timeframe','5min')))
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
    if 2<=len(val)<=12 and (val.isalpha() or val.replace('1','').isalnum()):
        atext, akeyboard = analyze(chat_id,val)
        send_message(chat_id,atext,akeyboard)
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
                    telegram_user=callback.get('from') or (u.get('message') or {}).get('from') or {}
                    if not chat: continue
                    upsert_telegram_user(telegram_user, chat)
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
                    s.get('is_bot_active') and not s.get('daily_stopped')
                    for s in USER_SESSIONS.values()
                )
                if need_regime:
                    await refresh_market_regime(http)
                loose_regime = MARKET_REGIME_CACHE['regime']
                macro_extreme = MARKET_REGIME_CACHE['extreme']
                # رژیم اجماع فوری (همان روش «وضعیت بازار») را برای هر تایم‌فریمی که واقعاً
                # در حال استفاده است جداگانه تازه می‌کنیم، چون هر کاربر می‌تواند تایم‌فریم
                # متفاوتی داشته باشد و این سیگنال برخلاف رژیم ماکرو، به تایم‌فریم وابسته است.
                active_timeframes = {
                    s.get('timeframe', '5min')
                    for s in USER_SESSIONS.values()
                    if s.get('is_bot_active') and not s.get('daily_stopped')
                }
                micro_extreme_by_tf = {}
                for tf in active_timeframes:
                    micro_extreme_by_tf[tf] = await refresh_timeframe_regime(http, tf)
                for cid,s in list(USER_SESSIONS.items()):
                    if not s['is_bot_active'] or s['daily_stopped']: continue
                    if not risk_guard(cid): continue
                    if s['max_open_positions']>0 and len(s['paper_positions'])>=s['max_open_positions']:
                        _entry_diag_batch_update(cid, [{'status':'blocked','reason':f"ظرفیت پوزیشن‌های باز پر است ({len(s['paper_positions'])}/{s['max_open_positions']})"}])
                        continue
                    # رژیم معمولی فقط اطلاع‌رسان است؛ فقط EXTREME اجازه دارد واچ‌لیست را یک‌طرفه کند.
                    watchlist = scan_watchlist_for_timeframe(s.get('timeframe','5min'), macro_extreme)
                    user_tf = s.get('timeframe', '5min')
                    combined_extreme = combine_extreme_regime(macro_extreme, micro_extreme_by_tf.get(user_tf))
                    for sym in watchlist:
                        tasks.append(scan_symbol(http,cid,sym,combined_extreme))
                if tasks:
                    batch = await asyncio.gather(*tasks, return_exceptions=True)
                    by_chat = {}
                    for item in batch:
                        if isinstance(item, dict) and item.get('chat_id') is not None:
                            by_chat.setdefault(item['chat_id'], []).append(item)
                        elif isinstance(item, BaseException):
                            logger.exception('scan loop task escaped wrapper', exc_info=item)
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
                msg += "\n\n🏠 برای شروع کار به منوی اصلی بروید و روی دکمه 🔄 بارگذاری مجدد و شروع اسکن بزنید."
            try:
                send_message(cid, msg)
            except Exception:
                pass
        logger.info('Boot status: sessions=%s total_open_positions=%s total_closed_positions=%s', len(USER_SESSIONS), total_open, total_closed)
    except Exception:
        logger.exception('boot status notification failed')


def _live_positions_loop():
    while True:
        try:
            refresh_live_position_messages()
        except Exception:
            logger.exception('live position refresh failed')
        time.sleep(10)

TELEGRAM_COMMANDS = [{'command':'menu','description':'منوی اصلی'}]

def configure_telegram_native_menu():
    if not TELEGRAM_TOKEN:
        return
    try:
        tg('setMyCommands', {'commands': TELEGRAM_COMMANDS}, 10)
        tg('setChatMenuButton', {'menu_button': {'type':'commands'}}, 10)
    except Exception:
        pass
def main():
    init_db()
    migrate_legacy_sqlite_to_postgres()
    load_telegram_offset()
    load_sessions()
    logger.info('Loaded %s sessions', len(USER_SESSIONS))
    _notify_boot_status()
    configure_telegram_native_menu()
    Thread(target=telegram_listener, daemon=True, name='telegram').start()
    Thread(target=lambda: (time.sleep(3), asyncio.run(scan_loop())), daemon=True, name='scanner').start()
    Thread(target=lambda: (time.sleep(5), _live_positions_loop()), daemon=True, name='live-pnl').start()
    app.run(host='0.0.0.0', port=PORT, threaded=True)


if __name__ == '__main__':
    main()
