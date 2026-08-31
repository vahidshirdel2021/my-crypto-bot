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

from strategy import (
    FILTER_DEFAULTS, STRATEGY_DEFAULTS, calculate_indicators, get_signal_with_reason,
    compute_swing_stop_v2,
    strategy_trend_following,
    strategy_breakout, strategy_mean_reversion, build_trade_plan, get_timeframe_preset,
    compute_swing_stop,
    compute_log_grid_levels, nearest_grid_level,
)
from pdh_eq_pdl_engine import min_klines_for_levels, get_reference_levels
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
    get_trend_management_keyboard,
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
    '5min': '1min',
    '15min': '5min',
    '1hour': '15min',
    '4hour': '1hour',
}
POSITION_MANAGEMENT_MIN_LOSS_R = -0.10
POSITION_MANAGEMENT_LOSS_WEAKNESS_SCORE = 45.0
POSITION_MANAGEMENT_EARLY_LOSS_R = -0.10


def _seconds_to_local_day_end():
    """ثانیه‌های باقی‌مانده تا پایان روز جاری بر اساس منطقه‌زمانی DAILY_CLOSE_TZ."""
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
# Platform fee: applied consistently to PAPER and REAL trades after a trade is realized.
PLATFORM_FEE_RATE_PCT = min(100.0, max(0.0, float(os.environ.get('PLATFORM_FEE_RATE_PCT', '10.0'))))
PLATFORM_FEE_MIN_PROFIT_USDT = max(0.0, float(os.environ.get('PLATFORM_FEE_MIN_PROFIT_USDT', '0.01')))
ADMIN_CHAT_IDS_RAW = os.environ.get('ADMIN_CHAT_IDS', os.environ.get('ALLOWED_CHAT_IDS', '')).strip()
ADMIN_CHAT_IDS = {int(x.strip()) for x in ADMIN_CHAT_IDS_RAW.split(',') if x.strip().lstrip('-').isdigit()}
# Fixed project admins. Environment ADMIN_CHAT_IDS may add additional admins.
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

# --- مدیریت روند معاملات: تنظیمات مستقل به‌ازای هر تایم‌فریم ---
# هر تایم‌فریم (5min/15min/1hour/4hour) یک نسخه‌ی جداگانه از این ۶ سوییچ دارد.
# این دیکشنری هرگز مستقیماً در strategy_config نوشته نمی‌شود، چون
# normalize_session و reload_and_restart_scan هر بار strategy_config را از
# روی پریست تایم‌فریم بازسازی می‌کنند و هر مقداری که آنجا نوشته شود از بین
# می‌رود. این تنظیمات جدا نگه داشته می‌شوند و در لحظه‌ی محاسبه‌ی سیگنال
# (effective_strategy_config) روی مقادیر پریست تزریق می‌شوند.
TREND_MGMT_DEFAULTS = {
    'allow_buy_in_bearish': False,
    'allow_sell_in_bullish': False,
    'allow_buy_in_range': True,
    'allow_sell_in_range': True,
    'b7_s7_enabled': True,
    'quality_profile': 'balanced',
}

# کیفیت معاملات: override روی min_trade_score/min_rr/min_adx پریست تایم‌فریم.
# 'balanced' یعنی هیچ overrideـی اعمال نشود و مقادیر خودِ پریست تایم‌فریم
# دست‌نخورده باقی بماند (چون هر تایم‌فریم پریست خودش را دارد و 'متعادل'
# باید یعنی «همون پیش‌فرض همین تایم‌فریم»، نه یک عدد ثابت مشترک بین همه).
QUALITY_PROFILE_OVERRIDES = {
    'conservative': {'min_trade_score': 78.0, 'min_rr': 1.60, 'min_adx': 24.0},
    'balanced': None,
    'opportunity': {'min_trade_score': 60.0, 'min_rr': 1.25, 'min_adx': 18.0},
}


def get_trend_mgmt(s, tf=None):
    """تنظیمات «مدیریت روند معاملات» مخصوص یک تایم‌فریم مشخص را برمی‌گرداند
    (پیش‌فرض: تایم‌فریم فعال همین سشن). دیکشنری برگشتی همان آبجکت داخل
    سشن است — تغییر مستقیم روی آن با save_session ذخیره می‌شود."""
    tf = tf if tf in SUPPORTED_TRADING_TIMEFRAMES else s.get('timeframe', '5min')
    if tf not in SUPPORTED_TRADING_TIMEFRAMES:
        tf = '5min'
    tm = s.setdefault('trend_mgmt', {})
    entry = tm.get(tf)
    if not isinstance(entry, dict):
        entry = dict(TREND_MGMT_DEFAULTS)
        tm[tf] = entry
    else:
        for k, v in TREND_MGMT_DEFAULTS.items():
            entry.setdefault(k, v)
    return entry

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

# Dynamic DEX-aware trading universe.  CoinGecko supplies the current market-cap
# ranking; the candidate set below is deliberately limited to liquid/perpetual-style
# assets commonly available on major on-chain venues (e.g. Hyperliquid/GMX).
# The existing CoinEx/KuCoin market-data layer remains the execution/data source, so
# a symbol is only useful to the scanner when candles are actually available there.
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
DEX_WATCHLIST_CACHE = {
    'ts': 0.0, 'symbols': [], 'source': 'fallback', 'tiers': {},
    # below_cutoff_since: {symbol: ts} از چه زمانی نماد پیوسته زیر آستانه‌ی
    # بافردار رتبه‌بندی بوده (برای منطق چسبندگی/hysteresis پایین).
    'below_cutoff_since': {},
    # changes: تاریخچه‌ی افزوده/حذف‌شدن نمادها از واچ‌لیست (برای شفافیت/آدیت).
    'changes': [],
}
# --- چسبندگی واچ‌لیست (Watchlist Hysteresis) ---
# قبلاً واچ‌لیست هر ۳۰ دقیقه صرفاً «تاپ-N رتبه‌بندی زنده‌ی مارکت‌کپ» را
# جایگزین می‌کرد؛ یعنی نمادی که مرز رتبه (مثلاً ۴۰) نوسان می‌کرد می‌توانست
# پشت‌سرهم وارد/خارج شود و باعث ناپایداری مجموعه‌ی معامله‌شونده بین
# جلسات/روزها شود. حالا: یک نماد که از قبل توی لیست بوده فقط وقتی حذف
# می‌شود که رتبه‌اش به‌طور *پیوسته* از آستانه‌ی بافردار (cutoff + buffer)
# پایین‌تر بماند و این افت حداقل DEX_WATCHLIST_MIN_DWELL_SECONDS دوام
# داشته باشد؛ نمادهای جدید فقط وقتی اضافه می‌شوند که واقعاً داخل رتبه‌ی
# اصلی (بدون بافر) باشند.
DEX_WATCHLIST_HYSTERESIS_BUFFER = int(os.environ.get('DEX_WATCHLIST_HYSTERESIS_BUFFER', '10'))
DEX_WATCHLIST_MIN_DWELL_SECONDS = int(os.environ.get('DEX_WATCHLIST_MIN_DWELL_SECONDS', str(6 * 3600)))

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
        # --- مدیریت روند معاملات (منوی جدید) ---
        # پیش‌فرض‌ها دقیقاً منطبق با تصمیم پیش‌فرض استراتژی: در روند قطعی
        # خلاف‌جهت خاموش، در رنج هر دو جهت روشن، B7/S7 روشن، کیفیت متعادل.
        # این تنظیمات مستقل به‌ازای هر تایم‌فریم نگه‌داری می‌شوند (به get_trend_mgmt نگاه کنید).
        'trend_mgmt': {tf: dict(TREND_MGMT_DEFAULTS) for tf in SUPPORTED_TRADING_TIMEFRAMES},
        # کدام تایم‌فریم داخل منوی «مدیریت روند معاملات» در حال نمایش/ویرایش است
        # (مستقل از تایم‌فریم فعال اسکن ربات، صرفاً برای مرور/تنظیم بقیه‌ی تایم‌فریم‌ها).
        'trend_mgmt_view_tf': '5min',
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
    s['trade_pipeline_enabled'] = bool(s.get('trade_pipeline_enabled', False))
    s['trade_pipeline_audit'] = list(data.get('trade_pipeline_audit') or [])[-5000:]
    s['platform_fee_rate_pct'] = min(100.0, max(0.0, float(s.get('platform_fee_rate_pct', PLATFORM_FEE_RATE_PCT))))
    s['platform_fee_total_usdt'] = max(0.0, float(s.get('platform_fee_total_usdt', 0.0)))
    s['platform_fee_trade_count'] = max(0, int(s.get('platform_fee_trade_count', 0) or 0))
    # --- مهاجرت داده‌ی قدیمی: نسخه‌ی قبلی این ۶ سوییچ را به‌صورت مشترک بین
    # همه‌ی تایم‌فریم‌ها (کلیدهای تخت trend_mgmt_*) نگه می‌داشت. اگر سشنِ
    # ذخیره‌شده هنوز به آن شکل قدیمی است، مقادیرش را به همه‌ی تایم‌فریم‌ها
    # کپی می‌کنیم تا کاربر رفتار قبلی را از دست ندهد؛ از این پس هرکدام
    # مستقل و جدا خواهند بود.
    legacy_flat_keys = ('trend_mgmt_allow_buy_in_bearish', 'trend_mgmt_allow_sell_in_bullish',
                         'trend_mgmt_allow_buy_in_range', 'trend_mgmt_allow_sell_in_range',
                         'b7_s7_enabled', 'quality_profile')
    raw = data or {}
    if not isinstance(raw.get('trend_mgmt'), dict) and any(k in raw for k in legacy_flat_keys):
        legacy_entry = {
            'allow_buy_in_bearish': bool(raw.get('trend_mgmt_allow_buy_in_bearish', False)),
            'allow_sell_in_bullish': bool(raw.get('trend_mgmt_allow_sell_in_bullish', False)),
            'allow_buy_in_range': bool(raw.get('trend_mgmt_allow_buy_in_range', True)),
            'allow_sell_in_range': bool(raw.get('trend_mgmt_allow_sell_in_range', True)),
            'b7_s7_enabled': bool(raw.get('b7_s7_enabled', True)),
            'quality_profile': raw.get('quality_profile') if raw.get('quality_profile') in ('conservative', 'balanced', 'opportunity') else 'balanced',
        }
        s['trend_mgmt'] = {tf: dict(legacy_entry) for tf in SUPPORTED_TRADING_TIMEFRAMES}
    else:
        raw_tm = raw.get('trend_mgmt') if isinstance(raw.get('trend_mgmt'), dict) else {}
        normalized_tm = {}
        for tf in SUPPORTED_TRADING_TIMEFRAMES:
            entry_raw = raw_tm.get(tf) if isinstance(raw_tm.get(tf), dict) else {}
            entry = dict(TREND_MGMT_DEFAULTS)
            entry.update({k: entry_raw[k] for k in TREND_MGMT_DEFAULTS if k in entry_raw})
            entry['allow_buy_in_bearish'] = bool(entry['allow_buy_in_bearish'])
            entry['allow_sell_in_bullish'] = bool(entry['allow_sell_in_bullish'])
            entry['allow_buy_in_range'] = bool(entry['allow_buy_in_range'])
            entry['allow_sell_in_range'] = bool(entry['allow_sell_in_range'])
            entry['b7_s7_enabled'] = bool(entry['b7_s7_enabled'])
            entry['quality_profile'] = entry['quality_profile'] if entry['quality_profile'] in ('conservative', 'balanced', 'opportunity') else 'balanced'
            normalized_tm[tf] = entry
        s['trend_mgmt'] = normalized_tm
    # کلیدهای قدیمیِ تخت را پاک می‌کنیم تا در سشن باقی نمانند و کسی سهواً به آن‌ها رجوع نکند.
    for k in legacy_flat_keys:
        s.pop(k, None)
    s['trend_mgmt_view_tf'] = s.get('trend_mgmt_view_tf') if s.get('trend_mgmt_view_tf') in SUPPORTED_TRADING_TIMEFRAMES else s.get('timeframe', '5min')
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


# ============================================================================
# مدیریت هوشمند/زودهنگام پوزیشن باز حذف شد (بند ۳ درخواست کاربر):
# PROFIT_LADDERS_R، trailing_locked_r() و _apply_profit_protection() که پیش‌تر
# اینجا بودند، جایگزین شدند با: Break-even دقیقاً پس از برخورد پله اول TP
# (EQ) + تریلینگ‌استاپ ساختاری بر اساس سوینگ (_check_swing_trailing_stop، که
# بدون تغییر در معماری باقی مانده). دیگر هیچ ladder یا منطق زودهنگامی SL را
# پیش از رسیدن واقعی قیمت به آن جابه‌جا نمی‌کند.
# ============================================================================


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
        # اگر use_advanced_swing_stop فعال باشد، به‌جای پنجره‌ی ثابت lookback از
        # کتابخانه swing_detection.py (سوینگ واقعی رجکشن/فراکتال تاییدشده)
        # استفاده می‌شود؛ در غیر این صورت (پیش‌فرض) دقیقاً رفتار قبلی حفظ می‌شود.
        if bool(cfg.get('use_advanced_swing_stop', False)):
            atr_period = int(cfg.get('advanced_swing_atr_period', 14))
            atr_buffer_mult = float(cfg.get('advanced_swing_atr_buffer_mult', 0.25))
            pct_buffer = float(cfg.get('advanced_swing_pct_buffer', 0.0015))
            new_sl, swing_level = compute_swing_stop_v2(sdf, is_long, atr_period, atr_buffer_mult, pct_buffer)
            if new_sl is None or swing_level is None:
                # اگر کتابخانه جدید سوینگی پیدا نکرد، به روش قدیمی به‌عنوان
                # fallback ایمن برمی‌گردیم تا تریلینگ‌استاپ کلاً غیرفعال نشود.
                lookback_n = int(cfg.get('swing_lookback', 12))
                confirm_n = int(cfg.get('swing_confirm_candles', 2))
                buffer_atr = float(cfg.get('swing_buffer_atr', 0.40))
                buffer_wick_pct = float(cfg.get('swing_buffer_wick_pct', 0.0015))
                new_sl, swing_level = compute_swing_stop(sdf, is_long, lookback_n, buffer_atr, confirm_n, buffer_wick_pct)
        else:
            lookback_n = int(cfg.get('swing_lookback', 12))
            confirm_n = int(cfg.get('swing_confirm_candles', 2))
            buffer_atr = float(cfg.get('swing_buffer_atr', 0.40))
            buffer_wick_pct = float(cfg.get('swing_buffer_wick_pct', 0.0015))
            new_sl, swing_level = compute_swing_stop(sdf, is_long, lookback_n, buffer_atr, confirm_n, buffer_wick_pct)
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
                logger.warning('swing SL move failed symbol=%s: %s', p['symbol'], err)
                return
        old_sl = cur_sl
        p['sl'] = new_sl
        p['swing_sl_level'] = swing_level
        p['trailing_activated'] = True
        # نوتیفیکیشن این رویداد به درخواست کاربر غیرفعال شد؛ خود جابه‌جایی SL
        # و تریلینگ (از جمله رفع باگ Giveback) دست‌نخورده باقی می‌ماند.
    except Exception as exc:
        logger.debug('swing trailing check failed symbol=%s: %s', p.get('symbol'), exc)


# ============================================================================
# قفل‌سود پله‌ای بر اساس R + تریلینگ ATR فعال (بازگرداندن مشروط بند حذف‌شده‌ی
# PROFIT_LADDERS_R، با طراحی سبک‌تر و مبتنی بر شواهد واقعی معاملات)
# ============================================================================
# چرا برگشت: بررسی گزارش‌های واقعی معاملات نشان داد معاملاتی که تا +۱.۵ تا
# +۲.۵R سود شناور داشتند (mfe_r)، در نبود هیچ قفل سودی پیش از TP1، تقریباً
# تمام آن سود را پس می‌دادند — گاهی حتی به ضرر کامل تبدیل می‌شد (مثال‌های
# TAO/S5 و NEAR/S5: از سود قابل توجه به ضرر منفی). تریلینگ ساختاری سوینگ
# به‌تنهایی برای این حرکت‌های بزرگ به‌موقع واکنش نشان نمی‌دهد، چون به شکل‌گیری
# یک سوینگ فرکتال کامل نیاز دارد که می‌تواند فاصله‌ی زیادی از قیمت داشته باشد.
# این تابع دو مکانیزم مستقل را کنار تریلینگ سوینگ موجود اضافه می‌کند (هر سه با
# هم رقابت می‌کنند؛ سخت‌گیرترین/بهترین برای پوزیشن انتخاب می‌شود):
#   ۱) پله‌ی قفل سود بر مبنای R واقعی معامله (risk_usdt/amount)
#   ۲) تریلینگ ATR فعال از همان لحظه‌ای که معامله به‌اندازه‌ی کافی در سود رفت
#      (نه فقط بعد از برخورد TP1)
def _check_profit_lock_and_atr_trailing(chat_id, s, p, price, sdf=None):
    try:
        cfg = s.get('strategy_config') or STRATEGY_DEFAULTS
        amount = float(p.get('amount') or 0)
        risk_usdt = float(p.get('risk_usdt') or 0)
        if amount <= 0 or risk_usdt <= 0:
            return
        risk_per_unit = risk_usdt / amount
        if risk_per_unit <= 0:
            return
        is_long = side_long(p['side'])
        entry = float(p['entry_price'])
        cur_r = ((price - entry) / risk_per_unit) if is_long else ((entry - price) / risk_per_unit)
        cur_sl = float(p['sl'])

        candidates = []  # هر عضو: (سطح پیشنهادی SL, برچسب برای پیام)

        # --- ۱) پله‌ی قفل سود بر مبنای R ---
        ladder = cfg.get('profit_lock_r_ladder', [(0.5, 0.0), (1.0, 0.30), (1.5, 0.70), (2.0, 1.10)])
        locked_r = None
        for trigger_r, lock_r in ladder:
            if cur_r >= float(trigger_r):
                locked_r = float(lock_r) if locked_r is None else max(locked_r, float(lock_r))
        if locked_r is not None:
            level = entry + locked_r * risk_per_unit if is_long else entry - locked_r * risk_per_unit
            candidates.append((level, f"قفل سود {locked_r:.2f}R"))

        # --- ۲) تریلینگ ATR فعال (از رسیدن به آستانه‌ی سود کافی) ---
        atr_trail_start_r = float(cfg.get('atr_trail_start_r', 0.8))
        if cur_r >= atr_trail_start_r:
            if sdf is None:
                sdf = get_klines(p['symbol'], p.get('timeframe', '5min'), 100)
            if sdf is not None and not sdf.empty:
                sdf_i = calculate_indicators(sdf)
                if not sdf_i.empty and 'atr' in sdf_i.columns:
                    atr_now = _safe_float(sdf_i.iloc[-1].get('atr'))
                    if atr_now and atr_now > 0:
                        trail_mult = float(cfg.get('atr_trail_mult', 1.8))
                        level = price - atr_now * trail_mult if is_long else price + atr_now * trail_mult
                        candidates.append((level, "تریلینگ ATR فعال"))

        if not candidates:
            return
        if is_long:
            new_sl, label = max(candidates, key=lambda x: x[0])
            improved = new_sl > cur_sl
            behind_price = new_sl < price
        else:
            new_sl, label = min(candidates, key=lambda x: x[0])
            improved = new_sl < cur_sl
            behind_price = new_sl > price
        if not (improved and behind_price):
            return

        if p.get('is_real'):
            ok, err = move_stop_loss(chat_id, p['symbol'], normalize_price(chat_id, p['symbol'], new_sl))
            if not ok:
                logger.warning('profit-lock SL move failed symbol=%s: %s', p['symbol'], err)
                return
        old_sl = cur_sl
        p['sl'] = new_sl
        p['trailing_activated'] = True
        send_message(chat_id, f"🔒 استاپ‌لاس *{p['symbol']}* برای قفل سود تغییر کرد ({label}، سود فعلی {cur_r:.2f}R)\n• قبلی: `{fmt(old_sl)}`\n• جدید: `{fmt(new_sl)}`")
    except Exception as exc:
        logger.debug('profit-lock/ATR trailing check failed symbol=%s: %s', p.get('symbol'), exc)


def _maybe_close_before_day_end(chat_id, p, price):
    """
    برای معاملات تایم‌فریم ۵ و ۱۵ دقیقه: پوزیشن هرگز نباید به روز بعد منتقل شود، چه با سود
    چه با ضرر. اگر تا پایان روز (بر اساس DAILY_CLOSE_TZ) کمتر از یک چرخه اسکن باقی مانده
    باشد، پوزیشن همین الان با قیمت بازار بسته می‌شود.
    """
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


def _merge_chart_levels(levels):
    """چند سطح قیمتی که عملاً برابرند (مثلاً وقتی TP1=TP2=TP3 یا SL1=SL3 یا
    SL2(Break-even)=ENTRY) را در یک خط/برچسب واحد ادغام می‌کند تا برچسب‌های
    تکراری روی هم ننشینند. اولین عضو هر گروه رنگ/استایل خط را تعیین می‌کند و
    برچسب‌ها با '/' به هم متصل می‌شوند (مثلاً 'ENTRY/SL2')."""
    groups = []
    for lv in levels:
        placed = False
        for g in groups:
            ref = g[0][0]
            tol = max(abs(ref), 1e-9) * 1e-6
            if abs(lv[0] - ref) <= tol:
                g.append(lv)
                placed = True
                break
        if not placed:
            groups.append([lv])
    merged = []
    for g in groups:
        value = g[0][0]
        seen = []
        for x in g:
            if x[2] not in seen:
                seen.append(x[2])
        label = '/'.join(seen)
        color = g[0][1]
        style = g[0][3]
        width = max(x[4] for x in g)
        merged.append((value, color, label, style, width))
    return merged


def chart(chat_id, symbol, df, trade):
    try:
        if df.empty or len(df) < 5:
            return

        tf = trade.get('timeframe', '5min')
        tf_label = TF_DISPLAY.get(tf, tf)

        # سطوح مرجع رنج: PDH/PDL/EQ برای 5m/15m و PWH/PWL/EQ برای 1h/4h
        # (get_reference_levels خودش بر اساس تایم‌فریم منبع درست را انتخاب می‌کند).
        range_hi = range_lo = range_eq = None
        hi_label, lo_label = 'PDH', 'PDL'
        dated_df = None
        try:
            dated_df, range_hi, range_lo, range_eq, range_label, _src = get_reference_levels(df, tf)
            if range_label and '/' in range_label:
                hi_label, lo_label = range_label.split('/', 1)
        except Exception:
            dated_df = None

        if tf in ('5min', '15min'):
            if dated_df is not None and '_period' in dated_df.columns:
                today_period = dated_df['_period'].iloc[-1]
                today_df = dated_df[dated_df['_period'] == today_period]
                d = today_df.copy().reset_index(drop=True) if len(today_df) >= 10 else df.tail(60).copy().reset_index(drop=True)
            else:
                d = df.tail(60).copy().reset_index(drop=True)
        else:
            d = df.tail(50).copy().reset_index(drop=True)

        # اکستنشن بالا/پایین رنج (همان extension_atr_mult که موتور PDH/EQ/PDL
        # برای tier3/TP3 استفاده می‌کند): EXT+ = HI + عرض‌رنج×ضریب، EXT- = LO - عرض‌رنج×ضریب
        range_ext_up = range_ext_down = None
        try:
            sess = get_session(chat_id)
            strat_cfg = (sess.get('strategy_config') if isinstance(sess, dict) else None) or STRATEGY_DEFAULTS
            ext_mult = float(strat_cfg.get('extension_atr_mult', STRATEGY_DEFAULTS.get('extension_atr_mult', 0.5)))
        except Exception:
            ext_mult = float(STRATEGY_DEFAULTS.get('extension_atr_mult', 0.5))
        if range_hi is not None and range_lo is not None and float(range_hi) > float(range_lo):
            range_width = float(range_hi) - float(range_lo)
            range_ext_up = float(range_hi) + range_width * ext_mult
            range_ext_down = float(range_lo) - range_width * ext_mult

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
        tp = float(trade['tp'])          # = TP3 نهایی
        sl = float(trade['sl'])          # SL فعال کنونی (= SL3)
        is_long = side_long(trade.get('side', 'BUY'))

        tp1 = float(trade['tp1']) if trade.get('tp1') is not None else tp
        tp2 = float(trade['tp2']) if trade.get('tp2') is not None else tp
        tp3 = float(trade['tp3']) if trade.get('tp3') is not None else tp
        initial_sl = float(trade['initial_sl']) if trade.get('initial_sl') is not None else sl

        # پلکان سه‌مرحله‌ای TP + سه‌مرحله‌ی SL (اولیه→برک‌اِوِن→تریل کنونی).
        # وقتی معامله دستی باشد یا هنوز به برک‌اِوِن نرسیده باشد، مقادیر برابر
        # می‌شوند و _merge_chart_levels آن‌ها را در یک برچسب ادغام می‌کند.
        levels = [
            (entry, '#60a5fa', 'ENTRY', '-', 1.8),
            (entry, '#60a5fa', 'SL2 (BE)', '-', 1.8),
            (tp1, '#86efac', 'TP1', '--', 1.4),
            (tp2, '#4ade80', 'TP2', '--', 1.7),
            (tp3, '#16a34a', 'TP3', '--', 2.0),
            (initial_sl, '#fca5a5', 'SL1', ':', 1.4),
            (sl, '#ef4444', 'SL3', '--', 2.0),
        ]
        if range_hi is not None:
            levels.append((float(range_hi), '#f97316', hi_label, ':', 1.4))
        if range_lo is not None:
            levels.append((float(range_lo), '#f97316', lo_label, ':', 1.4))
        if range_eq is not None:
            levels.append((float(range_eq), '#a78bfa', 'EQ', '-.', 1.3))
        if range_ext_up is not None:
            levels.append((range_ext_up, '#38bdf8', 'EXT+', '-.', 1.1))
        if range_ext_down is not None:
            levels.append((range_ext_down, '#38bdf8', 'EXT-', '-.', 1.1))

        merged_levels = sorted(_merge_chart_levels(levels), key=lambda x: x[0])

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
        all_vals = [lv[0] for lv in merged_levels] + [ymin, ymax]
        y_lo_data = min(all_vals); y_hi_data = max(all_vals)
        pad = max((y_hi_data - y_lo_data) * 0.08, abs(entry) * 0.002)
        y_lo, y_hi = y_lo_data - pad, y_hi_data + pad
        ax.set_ylim(y_lo, y_hi)

        # چیدمان برچسب‌های سمت راست: وقتی چند سطح به هم خیلی نزدیک‌اند، برچسب‌ها
        # را عمودی از هم فاصله می‌دهیم و با یک خط رابط نازک به قیمت واقعی وصل
        # می‌کنیم تا روی هم ننشینند و PDH/EQ/PDL/EXT/TP/SL همه خوانا بمانند.
        min_gap = (y_hi - y_lo) * 0.052
        label_positions = []
        last_y = None
        for value, color, label, style, width in merged_levels:
            ax.axhline(value, color=color, linestyle=style, linewidth=width, alpha=0.92, zorder=1)
            label_y = value if last_y is None else max(value, last_y + min_gap)
            label_positions.append((value, label_y, color, label))
            last_y = label_y

        x_right = len(d) + 1.8
        for value, label_y, color, label in label_positions:
            if abs(label_y - value) > (y_hi - y_lo) * 0.004:
                ax.plot([len(d) + 0.3, x_right - 0.25], [value, label_y],
                        color=color, linewidth=0.7, alpha=0.55, zorder=4, clip_on=False)
            ax.text(x_right, label_y, f' {label}  {fmt(value)} ',
                    va='center', ha='left', fontsize=8.6, fontweight='bold',
                    color='white',
                    bbox=dict(boxstyle='round,pad=0.22', facecolor=color, edgecolor='none', alpha=0.95),
                    clip_on=False, zorder=5)

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


def _execute_trade_unlocked(chat_id,symbol,side,signal_price,sl,tp,reason='',generation=None,require_active=True,structural_tp=False,swing_level=None,swing_sl_buffer=None,tp_ladder=None,htf_trend=None):
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
    # A setup is consumable only once. Use the latest closed signal identity so
    # repeated scan loops cannot create duplicate audit signals or re-enter the
    # exact same liquidity event.
    setup_source = f"{symbol}|{side}|{s.get('timeframe')}|{signal_price:.12g}|{sl:.12g}|{tp:.12g}|{reason}"
    setup_id = hashlib.sha256(setup_source.encode('utf-8')).hexdigest()[:24]
    if any(str(p.get('setup_id') or '') == setup_id for p in s.get('paper_positions', [])):
        _set_execute_block_reason(chat_id, 'همین ستاپ دقیقاً قبلاً به‌عنوان پوزیشن باز ثبت شده (تکراری)')
        return False
    if setup_id in set(s.get('consumed_setups') or []):
        _set_execute_block_reason(chat_id, 'این ستاپ قبلاً یک‌بار مصرف شده (consumed_setups) و دوباره معامله نمی‌شود')
        return False
    if (require_active and not s['is_bot_active']) or s['daily_stopped'] or not risk_guard(chat_id):
        _set_execute_block_reason(chat_id, 'ربات غیرفعال است، محدودیت ضرر روزانه فعال است، یا risk_guard رد کرد')
        return False
    now=time.time(); cd=float(s['cooldowns'].get(symbol,0))
    if now<cd:
        _set_execute_block_reason(chat_id, f'نماد {symbol} هنوز در کول‌داون است')
        return False
    s['cooldowns'].pop(symbol,None)
    if level_key and level_key in s.get('traded_levels', {}):
        _set_execute_block_reason(chat_id, 'همین سطح (PDH/PDL) قبلاً روی این نماد معامله شده')
        return False
    is_dynamic_strategy = s.get('active_strategy') == 'dynamic'
    if not is_dynamic_strategy and s['filters'].get('no_short_filter') and 'SELL' in side:
        _set_execute_block_reason(chat_id, 'فیلتر «بدون Short» فعال است')
        return False
    if not is_dynamic_strategy and s['filters'].get('no_buy_filter') and 'BUY' in side:
        _set_execute_block_reason(chat_id, 'فیلتر «بدون Long» فعال است')
        return False
    if s['max_open_positions']>0 and len(s['paper_positions'])>=s['max_open_positions']:
        _set_execute_block_reason(chat_id, f"ظرفیت پوزیشن‌های باز پر است ({len(s['paper_positions'])}/{s['max_open_positions']})")
        return False
    same_symbol_positions = [p for p in s['paper_positions'] if p['symbol']==symbol]
    if same_symbol_positions:
        # طبق تصمیم کاربر: محدودیت «پوزیشن همزمان روی یک نماد» فقط در بازار
        # رنج اعمال می‌شود، نه در روند قطعی (صعودی/نزولی).
        #   - htf_trend نامشخص (None، مثلاً معامله دستی): رفتار قدیمی/محافظه‌کارانه
        #     حفظ می‌شود — هر پوزیشن باز روی این نماد مانع پوزیشن جدید می‌شود.
        #   - htf_trend == 'RANGE': هر دو جهت مجازند اما نه بیش از یک پوزیشن
        #     در هر جهت (یعنی حداکثر یک Long و یک Short هم‌زمان).
        #   - htf_trend در ('BULLISH','BEARISH'): هیچ محدودیتی اعمال نمی‌شود
        #     (سقف واقعی تعداد پوزیشن‌های هم‌جهت را same_direction_guard و
        #     max_open_positions کنترل می‌کنند، نه این قانون).
        if htf_trend is None:
            _set_execute_block_reason(chat_id, f'{symbol} از قبل یک پوزیشن باز دارد')
            return False
        if htf_trend == 'RANGE':
            if any(side_long(p.get('side')) == side_long(side) for p in same_symbol_positions):
                _set_execute_block_reason(chat_id, f'{symbol} در بازار رنج از قبل یک پوزیشن هم‌جهت باز دارد (محدودیت پوزیشن همزمان مخصوص رنج)')
                return False
    same_ok, same_reason = _same_direction_guard_allows(s, side, quality_score, planned_rr, regime=htf_trend)
    if not same_ok:
        audit_event(chat_id, trade_id, 'same_direction_guard', {'allowed': False, 'reason': same_reason, 'score': quality_score, 'rr': planned_rr})
        _set_execute_block_reason(chat_id, f'same_direction_guard: {same_reason}')
        return False
    audit_event(chat_id, trade_id, 'same_direction_guard', {'allowed': True, 'reason': same_reason, 'score': quality_score, 'rr': planned_rr})
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
    # Structural SL (5m Swing->Break only, opt-in via swing_level/swing_sl_buffer):
    # if the real fill price slipped away from the signal price, re-anchor SL to
    # the actual swing level + its original ATR buffer instead of blindly
    # shifting the old fixed distance forward. A flat shift keeps the *distance*
    # but silently breaks the "SL sits behind the swing" guarantee once the
    # entry itself has moved. If the slip is bad enough that price is now at or
    # past the structural stop, the setup is stale and the trade is skipped.
    if swing_level is not None and swing_sl_buffer is not None:
        if side_long(side):
            structural_sl = float(swing_level) - float(swing_sl_buffer)
            if structural_sl >= price:
                _set_execute_block_reason(chat_id, 'قیمت زنده از SL ساختاری عبور کرده (ستاپ منقضی شده)')
                return False
            sl = structural_sl
        else:
            structural_sl = float(swing_level) + float(swing_sl_buffer)
            if structural_sl <= price:
                _set_execute_block_reason(chat_id, 'قیمت زنده از SL ساختاری عبور کرده (ستاپ منقضی شده)')
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

    # پلکان سه‌مرحله‌ای TP: اگر build_trade_plan یک ladder ساخته باشد (تیک‌های
    # tp1/tp2/tp3)، همان فاصله‌ی shift را که به `tp` نهایی (tier3) اعمال شد،
    # روی tp1/tp2 هم به‌صورت موازی اعمال می‌کنیم تا فاصله‌ی نسبی پله‌ها حفظ شود
    # (همان الگویی که برای sl/entry در این تابع استفاده می‌شود). اگر ladder
    # داده نشده باشد (مثلاً معامله دستی کاربر)، همه‌ی حجم روی همان tp واحد قرار
    # می‌گیرد (تک‌پله = ۱۰۰٪) تا کد مدیریت پوزیشن نیازی به شاخه‌ی جدا نداشته باشد.
    if tp_ladder and all(k in tp_ladder for k in ('tp1', 'tp2', 'tp3', 'tp1_pct', 'tp2_pct', 'tp3_pct')):
        shift = tp - float(tp_ladder['tp3'])
        tp1_final = float(tp_ladder['tp1']) + shift
        tp2_final = float(tp_ladder['tp2']) + shift
        tp1_pct, tp2_pct, tp3_pct = float(tp_ladder['tp1_pct']), float(tp_ladder['tp2_pct']), float(tp_ladder['tp3_pct'])
    else:
        tp1_final = tp2_final = tp
        tp1_pct, tp2_pct, tp3_pct = 0.0, 0.0, 1.0

    s['_symbol_tmp']=symbol
    margin, amount_or_reason=safe_size(chat_id,s,price,sl)
    s.pop('_symbol_tmp',None)
    if margin<=0:
        _set_execute_block_reason(chat_id, f'حجم/مارجین معتبر محاسبه نشد: {amount_or_reason}')
        return False
    leverage=int(s['leverage'])
    risk_dist=abs(float(price)-float(sl))
    risk_usdt=float(margin)*((risk_dist/float(price))*float(leverage)) if price>0 else 0.0
    fee_estimate=round_trip_fee_usdt(margin,leverage)
    if MIN_RISK_TO_FEE_RATIO>0 and risk_usdt < fee_estimate*MIN_RISK_TO_FEE_RATIO:
        _set_execute_block_reason(chat_id, f'نسبت ریسک به کارمزد کافی نیست ({risk_usdt:.2f} < {fee_estimate*MIN_RISK_TO_FEE_RATIO:.2f})')
        return False
    trade={'trade_id':trade_id,'setup_id':setup_id,'symbol':symbol,'side':side,'entry_price':price,'sl':sl,'tp':tp,'margin':margin,'leverage':leverage,'amount':0,'timeframe':s['timeframe'],'strategy':s['active_strategy'],'is_real':False,'paper_slippage_bps':PAPER_SLIPPAGE_BPS if PAPER_ONLY else 0.0,'paper_funding_rate_pct_8h':PAPER_FUNDING_RATE_PCT_8H if PAPER_ONLY else 0.0,'opened_at':time.time(),'signal_reason':reason[:500],'entry_reason':reason[:500],'risk_pct':float(s['risk_per_trade_pct']),'risk_usdt':risk_usdt,'quality_score':quality_score,'quality_label':quality_label,'planned_rr':planned_rr,'mfe_usdt':0.0,'mae_usdt':0.0,'mfe_r':0.0,'mae_r':0.0,'peak_favorable_price':None,'peak_adverse_price':None,'last_price':price,'duration_seconds':0.0,'realized_r':None,'trailing_activated':False,'risk_distance':risk_dist,'trailing_locked_r':0.0,'swing_sl_level':None,
        # initial_sl: مقدار اولیه‌ی SL در لحظه‌ی باز شدن معامله — برخلاف 'sl' که با
        # breakeven/تریل ساختاری تغییر می‌کند، این مقدار ثابت می‌ماند تا در چارت
        # پوزیشن به‌عنوان SL1 (مرجع تاریخی) در کنار SL3 (استاپ فعال کنونی) نمایش
        # داده شود (بند تصویر چارت پوزیشن - PDH/EQ/PDL + اکستنشن + TP1-3/SL1-3).
        'initial_sl': sl,
        # --- پلکان سه‌مرحله‌ای TP (بند ۴ درخواست کاربر) ---
        # original_amount/original_margin برای محاسبه‌ی درست سهم هر پله (٪) از
        # حجم *اولیه* معامله نگه داشته می‌شوند (چون amount/margin بعد از هر
        # بستن جزئی کاهش می‌یابند). tp1_done/tp2_done وضعیت رسیدن به هر پله را
        # پیگیری می‌کنند؛ breakeven_done یعنی SL کل باقی‌مانده به نقطه ورود
        # منتقل شده (بلافاصله پس از برخورد پله اول).
        'tp1':tp1_final,'tp2':tp2_final,'tp3':tp,
        'tp1_pct':tp1_pct,'tp2_pct':tp2_pct,'tp3_pct':tp3_pct,
        'tp1_done':False,'tp2_done':False,'breakeven_done':False,
        'original_amount':0.0,'original_margin':margin,
    }

    if s['trading_mode']=='REAL':
        ex=get_exchange(chat_id)
        if not ex:
            _set_execute_block_reason(chat_id, 'حساب CoinEx پیکربندی نشده یا اتصال برقرار نیست')
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
                _set_execute_block_reason(chat_id, f'تنظیم اهرم {symbol} شکست خورد: {exc}')
                send_message(chat_id,f'❌ تنظیم اهرم `{symbol}` شکست خورد: `{exc}`'); return False
        amount=(margin*leverage)/price
        amount=normalize_amount(chat_id,symbol,amount)
        min_amt=float(((market.get('limits') or {}).get('amount') or {}).get('min') or 0)
        if amount<=0 or (min_amt and amount<min_amt):
            _set_execute_block_reason(chat_id, f'حجم محاسبه‌شده {symbol} از حداقل مجاز بازار کمتر است')
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
                    _set_execute_block_reason(chat_id, f'سفارش Limit {symbol} در مهلت مقرر پر نشد و لغو شد')
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
            # فاصله‌ی واقعی fill نسبت به آنچه پلن پیش‌بینی کرده بود را روی پله‌های
            # tp1/tp2 هم به‌صورت موازی اعمال می‌کنیم تا نسبت‌های پلکان حفظ شوند.
            real_shift = float(trade['tp']) - float(trade['tp3'])
            trade['tp3'] = float(trade['tp'])
            trade['tp1'] = float(trade['tp1']) + real_shift
            trade['tp2'] = float(trade['tp2']) + real_shift
            trade['original_amount'] = filled
            trade['risk_usdt'] = abs(float(trade['entry_price']) - float(trade['sl'])) / max(float(trade['entry_price']), 1e-12) * float(trade['margin']) * float(trade['leverage'])

            audit_event(chat_id, trade_id, 'order_filled', {'entry_price': trade['entry_price'], 'amount': trade['amount'], 'order_id': order_id})
            ok, err = set_protection(chat_id, symbol, trade['sl'], trade['tp'])
            audit_event(chat_id, trade_id, 'protection_set', {'ok': ok, 'detail': err, 'sl': trade.get('sl'), 'tp': trade.get('tp')})
            if not ok:
                _halt_real_trading(chat_id, f'ثبت SL/TP برای {symbol} ناموفق بود: {err}')
                try: ex.close_position(sym, None, {'type': 'market', 'amount': filled})
                except Exception as close_exc: send_message(chat_id, f'🚨 *حفاظت شکست و بستن خودکار هم شکست.* `{symbol}`\nSL/TP: `{err}`\nخطای بستن: `{close_exc}`')
                else: send_message(chat_id, f'⚠️ معامله `{symbol}` به‌دلیل عدم ثبت SL/TP فوراً بسته شد.')
                _set_execute_block_reason(chat_id, f'ثبت SL/TP برای {symbol} ناموفق بود و پوزیشن فوراً بسته شد: {err}')
                return False

            current = get_session(chat_id)
            if (require_active and not current['is_bot_active']) or int(current.get('scan_generation', 0)) != generation:
                try: ex.close_position(sym, None, {'type': 'market', 'amount': filled})
                except Exception as close_exc:
                    _halt_real_trading(chat_id, f'توقف هنگام ورود رخ داد ولی بستن {symbol} ناموفق بود: {close_exc}')
                _set_execute_block_reason(chat_id, f'ربات هنگام ورود {symbol} متوقف/ری‌استارت شد؛ پوزیشن بسته شد')
                return False
        except Exception as exc:
            _halt_real_trading(chat_id, f'وضعیت سفارش REAL {symbol} قابل تأیید نیست: {exc}')
            send_message(chat_id, f'❌ سفارش REAL `{symbol}` به‌طور قطعی تأیید نشد؛ ربات متوقف شد.', parse_mode=None)
            _set_execute_block_reason(chat_id, f'وضعیت سفارش REAL {symbol} قابل تأیید نشد: {exc}')
            return False
    else:
        if float(s['paper_balance']) - reserved_margin(s) < margin:
            _set_execute_block_reason(chat_id, 'موجودی PAPER کافی نیست (با احتساب مارجین رزروشده‌ی پوزیشن‌های باز)')
            return False
        trade['amount'] = (margin * leverage) / price
        trade['original_amount'] = trade['amount']
        audit_event(chat_id, trade_id, 'paper_opened', {'entry_price': price, 'amount': trade['amount'], 'margin': margin, 'quality_score': quality_score, 'quality_label': quality_label, 'planned_rr': planned_rr})
        s['paper_positions'].append(trade)
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
    df = get_klines(symbol, chart_tf, min_klines_for_levels(chart_tf))
    if not df.empty:
        chart(chat_id, symbol, calculate_indicators(df), trade)
    return True


def _refresh_dynamic_dex_watchlist(force=False):
    """Build a single Long/Short universe from current market-cap ranking.

    This is intentionally best-effort: if CoinGecko is unavailable/rate-limited,
    the previous universe (or the curated fallback) is retained.  We do not let a
    watchlist refresh failure stop trading.
    """
    now = time.time()
    if not DEX_WATCHLIST_ENABLED:
        return list(dict.fromkeys(LONG_WATCHLIST + SHORT_WATCHLIST))
    if not force and DEX_WATCHLIST_CACHE['symbols'] and now - DEX_WATCHLIST_CACHE['ts'] < DEX_WATCHLIST_REFRESH_SECONDS:
        return list(DEX_WATCHLIST_CACHE['symbols'])
    try:
        r = requests.get(
            'https://api.coingecko.com/api/v3/coins/markets',
            params={'vs_currency':'usd','order':'market_cap_desc','per_page':max(200, DEX_WATCHLIST_SIZE * 2),'page':1,'sparkline':'false'},
            timeout=8,
        )
        if r.ok:
            rows = r.json() or []
            ranked_full = []
            for row in rows:
                sym = str(row.get('symbol') or '').upper()
                if sym in DEX_CANDIDATE_SYMBOLS and sym not in ranked_full:
                    ranked_full.append(sym)
            # Keep BTC/ETH as leaders and avoid directional Long/Short lists.
            ranked_full = [x for x in ranked_full if x not in ('1000SATS',)]
            if ranked_full:
                rank_of = {sym: i for i, sym in enumerate(ranked_full)}
                prev_symbols = list(DEX_WATCHLIST_CACHE.get('symbols') or [])
                below_since = dict(DEX_WATCHLIST_CACHE.get('below_cutoff_since') or {})
                changes = list(DEX_WATCHLIST_CACHE.get('changes') or [])

                cutoff = DEX_WATCHLIST_SIZE
                buffered_cutoff = cutoff + DEX_WATCHLIST_HYSTERESIS_BUFFER

                kept = []
                for sym in prev_symbols:
                    r_now = rank_of.get(sym)
                    if r_now is not None and r_now < buffered_cutoff:
                        # هنوز داخل آستانه‌ی بافردار — نگه داشته می‌شود و تایمر افت ریست می‌شود.
                        kept.append(sym)
                        below_since.pop(sym, None)
                        continue
                    # زیر آستانه‌ی بافردار (یا کلاً از رتبه‌بندی خارج شده)
                    first_seen_below = below_since.setdefault(sym, now)
                    if now - first_seen_below >= DEX_WATCHLIST_MIN_DWELL_SECONDS:
                        rank_txt = str(r_now) if r_now is not None else 'خارج از رده‌بندی'
                        changes.append({
                            'symbol': sym, 'action': 'removed', 'ts': now,
                            'reason': f'به مدت طولانی زیر آستانه‌ی بافردار ({buffered_cutoff}) مانده — رتبه فعلی: {rank_txt}',
                        })
                        below_since.pop(sym, None)
                        logger.info('DEX watchlist removed: %s (%s)', sym, changes[-1]['reason'])
                    else:
                        kept.append(sym)  # هنوز داخل دوره‌ی مهلت (grace period)

                # افزودن نمادهای جدیدی که واقعاً داخل رتبه‌ی اصلی (بدون بافر) هستند
                for sym in ranked_full[:cutoff]:
                    if sym not in kept:
                        kept.append(sym)
                        changes.append({
                            'symbol': sym, 'action': 'added', 'ts': now,
                            'reason': f'وارد رتبه‌ی برتر {cutoff} مارکت‌کپ شد (رتبه {rank_of[sym]})',
                        })
                        logger.info('DEX watchlist added: %s (%s)', sym, changes[-1]['reason'])

                kept = kept[:max(cutoff, DEX_WATCHLIST_SIZE)]
                DEX_WATCHLIST_CACHE.update({
                    'ts': now, 'symbols': kept, 'source': 'coingecko_ranked_sticky',
                    'tiers': {'A': kept[:40], 'B': kept[40:70], 'C': kept[70:DEX_WATCHLIST_SIZE]},
                    'below_cutoff_since': below_since,
                    'changes': changes[-100:],
                })
                return list(kept)
    except Exception as exc:
        logger.warning('dynamic DEX watchlist refresh failed: %s', exc)
    if DEX_WATCHLIST_CACHE['symbols']:
        return list(DEX_WATCHLIST_CACHE['symbols'])
    fallback = list(dict.fromkeys([x for x in PAPER_DEFAULT_SYMBOLS if x in DEX_CANDIDATE_SYMBOLS] + list(LONG_WATCHLIST) + list(SHORT_WATCHLIST)))
    fallback = fallback[:DEX_WATCHLIST_SIZE]
    DEX_WATCHLIST_CACHE.update({'ts': now, 'symbols': fallback, 'source':'curated_fallback', 'tiers': {'A':fallback[:40], 'B':fallback[40:70], 'C':fallback[70:]}})
    return fallback


def scan_watchlist_for_timeframe(timeframe, regime=None):
    # One shared universe for both directions.  Regime no longer hard-switches
    # Long vs Short symbols; it only affects scoring/filtering downstream.
    symbols = _refresh_dynamic_dex_watchlist()
    return symbols


MARKET_REGIME_MIN_ADX = float(os.environ.get('MARKET_REGIME_MIN_ADX', '18'))  # فقط برای برچسب نمایشی /analyze استفاده می‌شود؛ دیگر در مسیر تصمیم‌گیری ورود اثر ندارد (حذف سیستم Regime/Extreme قدیمی طبق تصمیم مشترک با کاربر - جایگزین: تشخیص روند ساختاری تایم بالاتر خودِ نماد در strategy.py)


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


def _capped_leverage(leverage, max_leverage):
    """Behavior-preserving leverage cap extracted from the inline REAL path."""
    return min(float(leverage), float(max_leverage))


def _leader_correlation_decision(side, both_bearish, both_bullish, any_crash, any_pump, max_corr, avg_positive_corr, detail):
    """Pure/testable version of the BTC/ETH correlation guard decision."""
    is_long = side_long(side)
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


def _same_direction_guard_allows(session, side, score, rr, regime=None, now=None):
    """Soft cap + cooldown for same-direction entries; one exceptional setup may bypass it.
    طبق تصمیم صریح کاربر: سقف تعداد پوزیشن‌های هم‌جهت (max_same_direction_positions)
    فقط در بازار رنج معنا دارد (پیش‌فرض ۲ در هر جهت = حداکثر ۴ پوزیشن هم‌زمان:
    ۲ خرید + ۲ فروش). در روند قطعی (صعودی/نزولی)، هیچ سقفی روی تعداد
    پوزیشن‌های هم‌جهت نیست — فقط max_open_positions کلی (که جدا و قبل از
    این تابع چک می‌شود) محدودکننده است."""
    now = time.time() if now is None else float(now)
    positions = list(session.get('paper_positions') or [])
    target_long = side_long(side)
    same = [p for p in positions if side_long(p.get('side')) == target_long]
    if regime in ('BULLISH', 'BEARISH'):
        max_same = 0  # 0 یعنی بدون سقف (طبق قرارداد max_same>0 در شرط پایین)
    else:
        max_same = int(session.get('max_same_direction_positions', 2) or 0)
    cooldown = float(session.get('same_direction_entry_cooldown_seconds', 900) or 0)
    exceptional = float(score or 0) >= 80.0 and float(rr or 0) >= 1.60
    if max_same > 0 and len(same) >= max_same and not exceptional:
        return False, f'سقف پوزیشن‌های هم‌جهت پر است ({len(same)}/{max_same})'
    if cooldown > 0 and not exceptional and same:
        latest = max(float(p.get('opened_at', 0) or 0) for p in same)
        if latest and now - latest < cooldown:
            return False, f'کول‌داون ورود هم‌جهت فعال است ({cooldown-(now-latest):.0f}s باقی‌مانده)'
    return True, 'محافظ هم‌جهت عبور کرد'


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
                # قبلاً یک نقص لحظه‌ای/گذرا در دریافت دیتای لیدر (مثلاً یک
                # تایم‌اوت کوتاه شبکه) بلافاصله کل معامله را بلاک می‌کرد، حتی
                # اگر چند ثانیه بعد داده در دسترس بود (۴ مورد در گزارش pipeline
                # audit). یک بار تلاش مجدد کوتاه قبل از بلاک کردن، تفاوتی بین
                # نبود واقعی داده و یک گلیچ لحظه‌ای می‌گذارد.
                await asyncio.sleep(2)
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

        detail = ', '.join(f'{k}={v:+.2f}' for k, v in correlations)
        return _leader_correlation_decision(side, both_bearish, both_bullish, any_crash, any_pump, max_corr, avg_positive_corr, detail)
    except Exception as exc:
        return False, f'محافظ بازار به دلیل خطا متوقف شد: {exc}'


# دلیل دقیق آخرین رد شدن اجرای معامله برای هر chat_id — صرفاً برای گزارش
# ردیابی معاملات (pipeline audit)؛ هیچ اثری روی منطق/کنترل جریان معامله ندارد
# (به همین دلیل عمداً امضای execute_trade/_execute_trade_unlocked دست‌نخورده
# ماند تا ریسک تغییر در مسیر بحرانی اجرای معامله‌ی واقعی صفر باشد). یافته‌شده
# از بررسی گزارش pipeline_events: ۵ سیگنال معتبر با پیام خالی رد شده بودند و
# دلیل واقعی (ظرفیت پر؟ کول‌داون؟ same_direction_guard؟) قابل مشاهده نبود.
_EXECUTE_BLOCK_REASON: Dict[int, str] = {}


def _set_execute_block_reason(chat_id, reason):
    try:
        _EXECUTE_BLOCK_REASON[int(chat_id)] = reason
    except Exception:
        pass


def pop_execute_block_reason(chat_id):
    try:
        return _EXECUTE_BLOCK_REASON.pop(int(chat_id), None)
    except Exception:
        return None


def execute_trade(chat_id,symbol,side,signal_price,sl,tp,reason='',structural_tp=False,swing_level=None,swing_sl_buffer=None,tp_ladder=None,htf_trend=None):
    s=get_session(chat_id)
    generation=int(s.get('scan_generation',0))
    if not s['is_bot_active'] or s['daily_stopped']:
        _set_execute_block_reason(chat_id, 'ربات غیرفعال است یا محدودیت ضرر روزانه فعال شده')
        return False
    lock=get_entry_lock(chat_id)
    with lock:
        s=get_session(chat_id)
        if not s['is_bot_active'] or s['daily_stopped'] or int(s.get('scan_generation',0)) != generation:
            _set_execute_block_reason(chat_id, 'ربات غیرفعال شد یا نسل اسکن در حین قفل عوض شد (رقابت زمانی)')
            return False
        return _execute_trade_unlocked(chat_id,symbol,side,signal_price,sl,tp,reason,generation,structural_tp=structural_tp,swing_level=swing_level,swing_sl_buffer=swing_sl_buffer,tp_ladder=tp_ladder,htf_trend=htf_trend)


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
            return min(100.0, max(0.0, float(row[0])))
    except Exception:
        logger.exception('get user fee rate failed chat=%s', chat_id)
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
                fee = round(profit * rate / 100.0, 8)
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
        # Conservative paper exit slippage.
        if PAPER_ONLY and PAPER_SLIPPAGE_BPS > 0:
            slip = PAPER_SLIPPAGE_BPS / 10000.0
            price = float(price) * (1.0 - slip) if side_long(pos['side']) else float(price) * (1.0 + slip)
        entry=float(pos['entry_price']); frac=((price-entry)/entry) if side_long(pos['side']) else ((entry-price)/entry)
        pnl_gross=float(pos['margin'])*frac*float(pos['leverage'])
        hours=max(0.0, time.time()-float(pos.get('opened_at',time.time()))) / 3600.0
        funding_intervals=hours/8.0
        funding_cost=float(pos['margin'])*float(pos['leverage'])*(PAPER_FUNDING_RATE_PCT_8H/100.0)*funding_intervals
        pnl=pnl_gross-fee-funding_cost
        s['paper_balance']+=pnl; pos['close_price']=price; pos['pnl_is_estimate']=False
        pos['pnl_gross_usdt']=pnl_gross
        pos['funding_usdt']=funding_cost
        fee_note=f' (کارمزد + فاندینگ کسر شد: {funding_cost:.2f} USDT)'
    # پلتفرم فقط یک‌بار روی *کل* سود معامله (مجموع پله‌های جزئی قبلی + پای آخر)
    # کارمزد می‌گیرد؛ چون settle_platform_fee بر اساس trade_id در دیتابیس
    # idempotent است (فقط یک ردیف در هر trade_id ثبت می‌شود)، محاسبه باید همین‌جا
    # (تنها نقطه‌ی بسته‌شدن کامل پوزیشن) و روی مجموع کل انجام شود؛ در غیر این‌صورت
    # اگر جداگانه به‌ازای هر پله فراخوانی می‌شد، فقط اولین پله کارمزد پلتفرم
    # می‌داد و بقیه به‌اشتباه معاف می‌شدند.
    partial_pnl = float(pos.get('pnl_partial_realized_usdt', 0.0))
    total_before_platform_fee = float(pnl) + partial_pnl
    platform_fee = settle_platform_fee(chat_id, pos, total_before_platform_fee) if total_before_platform_fee > PLATFORM_FEE_MIN_PROFIT_USDT else 0.0
    if platform_fee > 0:
        pos['pnl_before_platform_fee_usdt'] = total_before_platform_fee
        total_before_platform_fee -= platform_fee
        if not pos.get('is_real'):
            s['paper_balance'] -= platform_fee
    pos['platform_fee_usdt'] = platform_fee
    pos['fee_usdt']=fee + float(pos.get('fee_partial_usdt', 0.0))
    pos['pnl_gross_usdt'] = float(pos.get('pnl_gross_usdt') or pnl) + float(pos.get('pnl_gross_partial_usdt', 0.0))
    if not pos.get('risk_usdt'):
        try: pos['risk_usdt']=abs(float(pos['entry_price'])-float(pos['sl']))/max(float(pos['entry_price']),1e-12)*float(pos.get('original_margin') or pos['margin'])*float(pos['leverage'])
        except Exception: pos['risk_usdt']=0.0
    pos['pnl_usdt']=float(total_before_platform_fee); pos['close_timestamp']=time.time(); pos['close_reason']=reason
    pos['duration_seconds']=max(0, pos['close_timestamp']-float(pos.get('opened_at', pos['close_timestamp'])))
    pos['realized_r']=(float(pos.get('pnl_usdt') or 0.0)/float(pos.get('risk_usdt') or 0.0)) if float(pos.get('risk_usdt') or 0.0)>0 else None
    update_trade_excursions(pos, float(price), float(price))
    audit_event(chat_id, pos.get('trade_id') or new_trade_id(chat_id, pos.get('symbol','?')), 'position_closed', {'close_price': price, 'pnl_usdt': pos['pnl_usdt'], 'pnl_before_platform_fee_usdt': pos.get('pnl_before_platform_fee_usdt'), 'fee_usdt': pos['fee_usdt'], 'platform_fee_usdt': pos.get('platform_fee_usdt', 0.0), 'reason': reason, 'duration_seconds': pos['duration_seconds'], 'realized_r': pos.get('realized_r'), 'mfe_usdt': pos.get('mfe_usdt',0.0), 'mae_usdt': pos.get('mae_usdt',0.0), 'mfe_r': pos.get('mfe_r',0.0), 'mae_r': pos.get('mae_r',0.0), 'partial_closes': pos.get('partial_closes', [])})
    cooldown_len = int(s.get('strategy_config', {}).get('cooldown_seconds', 1200))
    s['cooldowns'][pos['symbol']]=time.time()+cooldown_len; s['closed_positions'].append(pos.copy()); s['paper_positions'].remove(pos); save_session(chat_id)
    est=' تقریبی' if pos.get('pnl_is_estimate') else ''
    fee_line=f"\n• کارمزد تخمینی رفت‌وبرگشت: `{pos['fee_usdt']:.2f} USDT`{fee_note}" if pos['fee_usdt']>0 else ''
    platform_line = f'\n• سهم پلتفرم: `{platform_fee:.2f} USDT` ({get_user_fee_rate(chat_id):.2f}%)' if platform_fee > 0 else ''
    partials_line = ''
    if pos.get('partial_closes'):
        parts = ', '.join(f"{pc['tier']}: {pc['pnl_net_usdt']:+.2f} USDT" for pc in pos['partial_closes'])
        partials_line = f'\n• پله‌های قبلی: `{parts}`'
    total_pnl = float(pos['pnl_usdt'])
    send_message(chat_id,f"📌 *پوزیشن {'REAL' if pos.get('is_real') else 'PAPER'} بسته شد*\n• `{pos['symbol']}`\n• خروج: `{fmt(pos['close_price'])}`\n• PnL خالص کل معامله{est}: `{total_pnl:+.2f} USDT`{partials_line}{fee_line}{platform_line}\n• علت: `{reason}`")
    return True


def _partial_close_position(chat_id, pos, price, fraction, tier_label, reason):
    """
    بستن جزئی یک پوزیشن باز (پیاده‌سازی پلکان سه‌مرحله‌ای TP - بند ۴ درخواست کاربر).

    fraction: سهم مورد نظر از حجم *اولیه* معامله (original_amount/original_margin)،
    نه از باقی‌مانده‌ی فعلی — این‌طور پله‌ها مستقل از گرد شدن اعشار پله‌های قبلی
    محاسبه می‌شوند. کارمزد پلتفرم اینجا اعمال نمی‌شود (طبق طراحی idempotent
    settle_platform_fee فقط یک‌بار در close_position روی مجموع کل معامله اعمال
    می‌شود)؛ فقط کارمزد رفت‌وبرگشت صرافی و فاندینگ (PAPER) روی همین پله کسر
    و در پوزیشن انباشته می‌شود.

    خروجی: True در صورت موفقیت. اگر عملاً چیزی برای باقی‌ماندن نبود (مثلاً به‌خاطر
    خطای گرد شدن اعشار در آخرین پله)، به‌جای بستن جزئی، همان close_position کامل
    فراخوانی می‌شود تا حسابداری/کارمزد پلتفرم یک‌بار و درست نهایی شود.
    """
    s = get_session(chat_id)
    if pos not in s['paper_positions']:
        return False
    orig_margin = float(pos.get('original_margin') or pos.get('margin') or 0)
    orig_amount = float(pos.get('original_amount') or pos.get('amount') or 0)
    if orig_margin <= 0 or orig_amount <= 0:
        return False
    close_margin = min(orig_margin * float(fraction), float(pos.get('margin') or 0))
    close_amount = min(orig_amount * float(fraction), float(pos.get('amount') or 0))
    if close_margin <= 0 or close_amount <= 0:
        return False

    remaining_margin_after = float(pos['margin']) - close_margin
    remaining_amount_after = float(pos['amount']) - close_amount
    if remaining_margin_after <= 1e-9 or remaining_amount_after <= 1e-9:
        return close_position(chat_id, pos, price, reason)

    fee = round_trip_fee_usdt(close_margin, pos.get('leverage'))
    if pos.get('is_real'):
        ex = get_exchange(chat_id)
        if not ex:
            send_message(chat_id, '❌ اتصال CoinEx در دسترس نیست.'); return False
        try:
            sym = ccxt_symbol(pos['symbol'])
            amt = normalize_amount(chat_id, pos['symbol'], close_amount)
            if amt <= 0:
                return False
            order = ex.close_position(sym, None, {'type': 'market', 'amount': amt})
            fill_price = float(order.get('average') or order.get('price') or latest_price(pos['symbol']) or price or pos['entry_price'])
        except Exception as exc:
            send_message(chat_id, f'❌ بستن جزئی REAL `{pos["symbol"]}` شکست خورد: `{exc}`', parse_mode=None)
            return False
    else:
        fill_price = float(price) if price is not None else (latest_price(pos['symbol']) or pos['entry_price'])
        if PAPER_ONLY and PAPER_SLIPPAGE_BPS > 0:
            slip = PAPER_SLIPPAGE_BPS / 10000.0
            fill_price = fill_price * (1.0 - slip) if side_long(pos['side']) else fill_price * (1.0 + slip)

    entry = float(pos['entry_price'])
    frac_move = ((fill_price - entry) / entry) if side_long(pos['side']) else ((entry - fill_price) / entry)
    pnl_gross = close_margin * frac_move * float(pos['leverage'])
    funding_cost = 0.0
    if not pos.get('is_real'):
        hours = max(0.0, time.time() - float(pos.get('opened_at', time.time()))) / 3600.0
        funding_intervals = hours / 8.0
        funding_cost = close_margin * float(pos['leverage']) * (PAPER_FUNDING_RATE_PCT_8H / 100.0) * funding_intervals
    pnl_net = pnl_gross - fee - funding_cost

    if not pos.get('is_real'):
        s['paper_balance'] += pnl_net

    pos['margin'] = remaining_margin_after
    pos['amount'] = remaining_amount_after
    pos.setdefault('partial_closes', []).append({
        'tier': tier_label, 'price': fill_price, 'fraction': fraction,
        'margin_closed': close_margin, 'amount_closed': close_amount,
        'pnl_gross_usdt': pnl_gross, 'fee_usdt': fee, 'funding_usdt': funding_cost,
        'pnl_net_usdt': pnl_net, 'timestamp': time.time(),
    })
    pos['pnl_partial_realized_usdt'] = float(pos.get('pnl_partial_realized_usdt', 0.0)) + pnl_net
    pos['pnl_gross_partial_usdt'] = float(pos.get('pnl_gross_partial_usdt', 0.0)) + pnl_gross
    pos['fee_partial_usdt'] = float(pos.get('fee_partial_usdt', 0.0)) + fee
    pos['funding_partial_usdt'] = float(pos.get('funding_partial_usdt', 0.0)) + funding_cost
    audit_event(chat_id, pos.get('trade_id') or new_trade_id(chat_id, pos.get('symbol', '?')), 'position_partial_close', {
        'tier': tier_label, 'price': fill_price, 'fraction': fraction, 'pnl_net_usdt': pnl_net, 'reason': reason,
        'remaining_margin': remaining_margin_after, 'remaining_amount': remaining_amount_after,
    })
    save_session(chat_id)
    pct_label = f'{fraction * 100:.0f}%'
    send_message(chat_id, f"🎯 *پله {tier_label} پوزیشن {'REAL' if pos.get('is_real') else 'PAPER'} برخورد کرد*\n• `{pos['symbol']}`\n• بسته‌شده: `{pct_label}` حجم اولیه، در قیمت `{fmt(fill_price)}`\n• PnL این پله: `{pnl_net:+.2f} USDT`\n• باقی‌مانده حجم برای ادامه رنج/تارگت بعدی")
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


# ============================================================================
# _position_management_timeframe / _mfe_protection_exit_check /
# _weakness_exit_check حذف شدند (بند ۳ درخواست کاربر): این‌ها منطق «مدیریت
# هوشمند/خروج زودهنگام» بودند که پوزیشن سودده یا زیان‌ده را بر اساس اندیکاتور
# یا بازگشت از MFE، پیش از رسیدن واقعی قیمت به TP/SL می‌بستند. اکنون تنها
# راه‌های خروج، پلکان سه‌مرحله‌ای TP و برخورد واقعی به SL (اولیه یا
# Break-even/تریل‌شده با سوینگ) در update_positions() هستند.
# ============================================================================


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
            pnl = (live-entry)*amount if side_long(p['side']) else (entry-live)*amount
            pct = ((live-entry)/entry*100.0) if side_long(p['side']) and entry>0 else ((entry-live)/entry*100.0 if entry>0 else 0.0)
            risk = float(p.get('risk_usdt') or 0.0)
            r = (pnl/risk) if risk>0 else 0.0
            side_label = '🟢 LONG' if side_long(p['side']) else '🔴 SHORT'
            lines += [
                f'\n{side_label} `{symbol}`',
                f'↳ ورود: `{fmt(entry)}` | فعلی: `{fmt(live)}`',
                f'↳ 📈 سود/زیان لحظه‌ای: `{pnl:+.2f} USDT`',
                f'↳ 📊 بازده: `{pct:+.2f}%` | R: `{r:+.2f}`',
            ]
            tp1, tp2, tp3 = p.get('tp1'), p.get('tp2'), (p.get('tp3') if p.get('tp3') is not None else p.get('tp'))
            if tp1 is not None and tp2 is not None:
                tp1_done = bool(p.get('tp1_done')); tp2_done = bool(p.get('tp2_done'))
                m1 = '✅' if tp1_done else '⏳'
                m2 = '✅' if tp2_done else ('⏳' if tp1_done else '🔒')
                m3 = '⏳' if tp2_done else '🔒'  # اگر TP3 هم بخورد کل پوزیشن بسته و از این لیست حذف می‌شود
                p1 = p.get('tp1_pct'); p2 = p.get('tp2_pct'); p3 = p.get('tp3_pct')
                lbl1 = f' ({p1*100:.0f}٪)' if p1 else ''
                lbl2 = f' ({p2*100:.0f}٪)' if p2 else ''
                lbl3 = f' ({p3*100:.0f}٪)' if p3 else ''
                lines += [
                    f'↳ 🎯 TP1{lbl1}: `{fmt(tp1)}` {m1}',
                    f'↳ 🎯 TP2{lbl2}: `{fmt(tp2)}` {m2}',
                    f'↳ 🎯 TP3{lbl3}: `{fmt(tp3)}` {m3}',
                ]
            else:
                lines.append(f'↳ 🎯 TP: `{fmt(p.get("tp"))}`')
            sl_state = 'Break-even/تریل‌شده 🟢' if p.get('breakeven_done') else 'اولیه'
            lines.append(f'↳ 🛑 SL: `{fmt(p.get("sl"))}` ({sl_state})')
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
    if not s.get('paper_positions'):
        # Keep the last message if possible; otherwise a short notification is enough.
        if target_id:
            res = tg('editMessageText', {
                'chat_id': chat_id, 'message_id': int(target_id),
                'text': text, 'reply_markup': markup, 'parse_mode': 'Markdown'
            }, 10)
            if res and res.get('ok'):
                s['positions_message_id'] = int(target_id)
                s['positions_message_last_edit'] = time.time()
                save_session(chat_id)
                return int(target_id)
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
        # مدیریت هوشمند/تایم‌فریم ثانویه که management_df را مصرف می‌کرد حذف شده
        # (بند ۳)؛ فقط primary_df لازم است.
        primary_df=get_klines(p['symbol'],primary_tf,120)
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
        is_long=side_long(p['side'])

        # ------------------------------------------------------------------
        # پلکان سه‌مرحله‌ای TP (بند ۴ درخواست کاربر) + Break-even پس از پله اول
        # ------------------------------------------------------------------
        # توجه مهم درباره‌ی حذف «مدیریت هوشمند» (بند ۳): از این‌جا به بعد هیچ
        # منطقی پوزیشن را زودتر از رسیدن به یکی از پله‌های TP یا به SL نمی‌بندد.
        # تنها راه‌های خروج: TP1/TP2/TP3، برخورد به SL (که پس از TP1 روی
        # Break-even و سپس با سوینگ ساختاری تریل می‌شود)، یا بستن اجباری
        # پایان‌روز/سشن (_maybe_close_before_day_end، که قانون rollover است نه
        # مدیریت هوشمند و بالاتر همچنان بررسی می‌شود).
        def _crossed(level):
            if level is None:
                return False
            lvl = float(level)
            if s['trading_mode']=='PAPER' and not primary_df.empty:
                return (high >= lvl) if is_long else (low <= lvl)
            return (price >= lvl) if is_long else (price <= lvl)

        tp1_pct=float(p.get('tp1_pct') or 0.0); tp2_pct=float(p.get('tp2_pct') or 0.0)

        # Tier 1: نیمی از حجم دقیقاً روی EQ
        if not p.get('tp1_done', False) and tp1_pct > 0 and _crossed(p.get('tp1')):
            fill = float(p['tp1']) if (s['trading_mode']=='PAPER' and not primary_df.empty) else price
            ok = _partial_close_position(chat_id, p, fill, tp1_pct, 'TP1 (EQ)', 'TP1 - رسیدن به EQ، پله اول از پلکان سه‌مرحله‌ای')
            if ok:
                if p not in s['paper_positions']:
                    continue  # کل پوزیشن (به‌خاطر باقی‌مانده‌ی ناچیز) به‌طور کامل بسته شد
                p['tp1_done']=True
                be=entry
                if p.get('is_real'):
                    ok_sl, err_sl = move_stop_loss(chat_id, p['symbol'], normalize_price(chat_id, p['symbol'], be))
                    if not ok_sl:
                        logger.warning('breakeven SL move failed symbol=%s: %s', p['symbol'], err_sl)
                p['sl']=be
                p['breakeven_done']=True

        # Tier 2: ۳۰٪ حجم روی مرز مقابل رنج (فقط پس از تکمیل پله اول)
        if p.get('tp1_done', False) and not p.get('tp2_done', False) and tp2_pct > 0 and _crossed(p.get('tp2')):
            fill = float(p['tp2']) if (s['trading_mode']=='PAPER' and not primary_df.empty) else price
            ok = _partial_close_position(chat_id, p, fill, tp2_pct, 'TP2 (مرز مقابل)', 'TP2 - رسیدن به مرز مقابل رنج، پله دوم از پلکان سه‌مرحله‌ای')
            if ok:
                if p not in s['paper_positions']:
                    continue
                p['tp2_done']=True

        # Tier 3 (باقی‌مانده - اکستنشن رنج) و SL نهایی
        exit_price=None; reason=None
        if s['trading_mode']=='PAPER' and not primary_df.empty:
            # --- رفع باگ Giveback (بررسی مشترک با کاربر، گزارش pipeline audit) ---
            # قبلاً تریلینگ/قفل‌سود فقط *بعد* از این چک اجرا می‌شد (پایین‌تر، در
            # شرط `if reason is None`). یعنی اگر قیمت در همین یک کندل ابتدا
            # به‌اندازه‌ی کافی سود می‌کرد (مثلاً تا ۱.۳R) و سپس در همان کندل
            # برمی‌گشت و به SL *قدیمی* می‌خورد، تریلینگ اصلاً فرصت اجرا شدن پیدا
            # نمی‌کرد و معامله با SL آپدیت‌نشده بسته می‌شد — نمونه‌های واقعی:
            # ADA/OP/COMP در گزارش pipeline audit، هرکدام با mfe_r بین ۰.۷ تا
            # ۱.۳ که در نهایت با ضرر بسته شدند.
            # اصلاح: قبل از تشخیص برخورد نهایی، تریلینگ/قفل‌سود را بر اساس
            # حداکثر نوسان *مطلوب* همین کندل (high برای Long / low برای Short)
            # اعمال می‌کنیم؛ اگر آستانه‌ی قفل‌سود در همین کندل رد شده باشد، SL
            # واقعاً جلوتر می‌رود و برخورد به SL نهایی روی سطح *جدید* سنجیده
            # می‌شود، نه سطح قدیمی. دیتای OHLC هنوز توالی دقیق حرکت داخل کندل
            # را نشان نمی‌دهد، ولی این حداقلِ صادقانه‌ی قابل‌استخراج از آن است.
            favorable_extreme = high if is_long else low
            _check_swing_trailing_stop(chat_id, s, p, favorable_extreme, primary_df)
            _check_profit_lock_and_atr_trailing(chat_id, s, p, favorable_extreme, primary_df)

            hit_tp = (high>=float(p['tp'])) if is_long else (low<=float(p['tp']))
            hit_sl = (low<=float(p['sl'])) if is_long else (high>=float(p['sl']))
            if hit_tp and hit_sl and PAPER_CONSERVATIVE_OHLC:
                exit_price=float(p['sl']); reason='SL (همان کندل)'
            elif hit_tp:
                exit_price=float(p['tp']); reason='TP3 (اکستنشن نهایی)'
            elif hit_sl:
                exit_price=float(p['sl']); reason='SL (Break-even)' if p.get('breakeven_done') else 'SL'
        # REAL: خروج نهایی (TP3/SL) از طریق حفاظت سمت صرافی (set_protection در
        # زمان ورود و move_stop_loss هنگام تریل) و reconcile_real شناسایی
        # می‌شود؛ فقط پله‌های ۱/۲ بالاتر نیاز به مانیتورینگ دستی این حلقه داشتند.

        if reason is None:
            # استاپ‌لاس ساختاری بر اساس سوینگ (بند ۵)، همچنان روی تایم‌فریم اصلی معامله.
            # پس از Break-even (تیر ۱) هم ادامه پیدا می‌کند و فقط SL را بهتر می‌کند،
            # هرگز بدتر (این تضمین از قبل داخل خود تابع وجود دارد).
            # توجه: برای PAPER این تابع بالاتر با favorable_extreme همین کندل
            # از قبل صدا زده شده؛ اینجا فقط برای REAL (که از price لحظه‌ای
            # زنده استفاده می‌کند، نه کندل) لازم است دوباره اجرا شود.
            if not primary_df.empty and s['trading_mode'] != 'PAPER':
                _check_swing_trailing_stop(chat_id,s,p,price,primary_df)
                _check_profit_lock_and_atr_trailing(chat_id,s,p,price,primary_df)

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


def _pipeline_record(chat_id, symbol, stage, status='', reason='', signal=None, data=None):
    """Persist an end-to-end scan/entry pipeline event when the audit toggle is on."""
    try:
        s = get_session(chat_id)
        if not s.get('trade_pipeline_enabled', False):
            return
        wl = _refresh_dynamic_dex_watchlist()
        event = {
            'pipeline_id': f"{symbol}:{s.get('timeframe','5min')}:{int(time.time()*1000)}",
            'symbol': symbol, 'timeframe': s.get('timeframe','5min'),
            'stage': str(stage), 'status': str(status or ''),
            'reason': str(reason or ''), 'signal': signal, 'ts': time.time(),
            'watchlist_source': DEX_WATCHLIST_CACHE.get('source','fallback'),
            'watchlist_size': len(wl), 'watchlist_tier': ('A' if symbol in DEX_WATCHLIST_CACHE.get('tiers',{}).get('A',[]) else 'B' if symbol in DEX_WATCHLIST_CACHE.get('tiers',{}).get('B',[]) else 'C' if symbol in DEX_WATCHLIST_CACHE.get('tiers',{}).get('C',[]) else '—'),
            'data': data or {},
        }
        s.setdefault('trade_pipeline_audit', []).append(event)
        s['trade_pipeline_audit'] = s['trade_pipeline_audit'][-5000:]
        save_session(chat_id)
    except Exception:
        logger.exception('pipeline audit failed chat=%s symbol=%s stage=%s', chat_id, symbol, stage)


def _pipeline_start(chat_id, symbol):
    _pipeline_record(chat_id, symbol, 'watchlist_review', 'review_started', 'نماد وارد مرحله بررسی شد')


def _entry_diag_result(chat_id, symbol, status, reason='', stage='', signal=None, diagnostics=None):
    _pipeline_record(chat_id, symbol, stage or status, status, reason, signal, diagnostics)
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


def _why_no_entry_line(item):
    """یک خط خلاصه برای یک نماد: نماد + جهت مرتبط + دلیل انسانی کوتاه.
    از همان _entry_diag_label استفاده می‌کند (تبدیل دلیل خام داخلی به جمله‌ی
    کوتاه قابل‌فهم برای کاربر) تا هیچ منطق تکراری/جدیدی برای تفسیر دلیل ساخته نشود.
    """
    sym = item.get('symbol', '?')
    direction = _entry_diag_direction(item)
    label = _entry_diag_label(item.get('reason', ''))
    return f'`{sym}` ({direction}): {label}'


def _why_no_entry_report(chat_id):
    """گزارش یک‌خطی-به‌ازای-هر-نماد از آخرین وضعیت ثبت‌شده در ردیابی تشخیصی
    (ENTRY_DIAG_STATE) — برای پاسخ سریع به «چرا الان وارد معامله نمی‌شویم؟»
    بدون نیاز به خوندن گزارش کامل/طولانی داشبورد فرصت‌ها.
    """
    state = ENTRY_DIAG_STATE.get(chat_id) or {}
    symbol_states = state.get('symbol_states') or {}
    if not symbol_states:
        return '📋 هنوز داده‌ی تشخیصی ثبت نشده است (اسکن هنوز اجرا نشده یا لاگ تشخیصی خاموش است).'
    # بازشده‌ها (entry_opened) از این گزارش کنار گذاشته می‌شوند چون سوال
    # صرفاً درباره‌ی «چرا وارد نمی‌شویم» است.
    pending = [x for x in symbol_states.values() if x.get('status') != 'entry_opened']
    if not pending:
        return '🟢 در آخرین اسکن، همه‌ی نمادهای بررسی‌شده وارد معامله شدند یا موردی برای گزارش نیست.'
    pending.sort(key=lambda x: float(x.get('last_update_at') or 0), reverse=True)
    lines = ['🔎 *چرا الان وارد معامله نمی‌شویم — یک خط به‌ازای هر نماد*', '━━━━━━━━━━━━━━━━━━━━']
    lines.extend(f'• {_why_no_entry_line(item)}' for item in pending[:30])
    return '\n'.join(lines)


def _entry_diag_direction(item):
    """Return the relevant LONG/SHORT context for a diagnostic row."""
    sig = str(item.get('signal') or '').upper()
    if sig == 'BUY':
        return '🟢 LONG'
    if sig == 'SELL':
        return '🔴 SHORT'
    sym = str(item.get('symbol') or '').upper()
    dynamic_wl = set(_refresh_dynamic_dex_watchlist())
    if sym in dynamic_wl:
        return '🟡 LONG/SHORT'
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
    active_items = []
    for item in all_items:
        icon, stage, desc = _entry_diag_stage(item)
        # Keep the report focused on actionable/watch states. Pure idle/no-setup
        # symbols are intentionally omitted from Telegram.
        if stage in ('بدون ستاپ', 'داده ناقص'):
            continue
        active_items.append((item, icon, stage, desc))

    long_active = sum(1 for item, *_ in active_items if 'LONG' in _entry_diag_direction(item))
    short_active = sum(1 for item, *_ in active_items if 'SHORT' in _entry_diag_direction(item))
    confirm_wait = sum(1 for _, _, stage, _ in active_items if stage in ('منتظر تأیید', 'نزدیک ورود', 'منتظر حرکت واضح', 'در انتظار'))
    pullback_wait = sum(1 for _, _, stage, _ in active_items if stage == 'منتظر پولبک')

    dynamic_wl = _refresh_dynamic_dex_watchlist()
    wl_source = DEX_WATCHLIST_CACHE.get('source','fallback')
    lines = [
        '🧠 *داشبورد زنده فرصت‌ها*',
        '━━━━━━━━━━━━━━━━━━━━',
        f'⏱ گزارش دوره‌ای: هر ۱۰ دقیقه | تایم‌فریم: `{tf}`',
        f'📋 واچ‌لیست فعال: `{len(dynamic_wl)}` نماد | منبع: `{wl_source}`',
        f'🧭 بررسی جهت‌دار: `Long/Short مشترک`',
    ]
    if opened:
        lines.append(f'🟢 در این چرخه `{opened}` ورود انجام شد.')
    elif active_items:
        lines.append(f'📌 فرصت‌های فعال: `{len(active_items)}`')
    else:
        lines.append('💤 فعلاً فرصت فعال و قابل پیگیری وجود ندارد؛ موارد بدون ستاپ نمایش داده نمی‌شوند.')
    if data_issues:
        lines.append(f'⚠️ `{data_issues}` مورد مشکل داده داشت و در فهرست فرصت‌های فعال نمایش داده نشده است.')

    for item, icon, stage, desc in active_items:
        sym = item.get('symbol','?')
        direction = _entry_diag_direction(item)
        prev = item.get('previous_stage')
        change = ''
        if prev and prev != stage:
            change = f' | تغییر: {prev} → {stage}'
        lines.append(f'\n{icon} *{sym}* — {direction} — {stage}{change}\n   {desc}')

    if active_items:
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

    # Diagnostic results remain stored for the admin/audit UI, but are no longer
    # pushed as periodic Telegram reports. A simple heartbeat is sent every 10 minutes.


async def scan_symbol(http,chat_id,symbol,regime=None):
    s=get_session(chat_id)
    _pipeline_start(chat_id, symbol)
    if not s['is_bot_active'] or s['daily_stopped']:
        return _entry_diag_result(chat_id, symbol, 'blocked', 'ربات متوقف است یا محدودیت روزانه فعال است', 'precheck')
    scan_generation=int(s.get('scan_generation',0))
    if time.time() < float(s['cooldowns'].get(symbol,0)):
        return _entry_diag_result(chat_id, symbol, 'blocked', 'نماد در دوره انتظار پس از معامله قبلی است', 'cooldown')
    tf=s['timeframe']; strat=s['active_strategy']; md={}
    try:
        # قبلاً این مقدار hardcode بود (650 برای 5m/15m، 1500 برای 1h، 400 برای
        # 4h) و برای تایم‌فریم ۵ دقیقه از حداقلی که خودِ موتور
        # (min_klines_for_levels) برای محاسبه‌ی معتبر PDH/PDL اعلام می‌کند
        # (۸۸۴ کندل) کمتر بود؛ همین کمبود می‌توانست باعث None شدن سطوح و رد
        # بی‌دلیل نماد شود، حتی وقتی همان نماد با /analyze (که درست از همین
        # تابع استفاده می‌کرد) ستاپ معتبر نشان می‌داد. حالا هر ۴ تایم‌فریم از
        # همان منبع واحد (min_klines_for_levels) با کمی حاشیه‌ی اطمینان اضافه
        # می‌خوانند تا مسیر اسکن زنده هم دقیقاً همان تضمین چارت/تحلیل دستی را داشته باشد.
        klimit = min_klines_for_levels(tf) + 50
        d=await get_klines_async(http,symbol,tf,klimit)
    except Exception as exc:
        return _entry_diag_result(chat_id, symbol, 'data_error', f'خطا در دریافت داده: {exc}', 'data')
    if d.empty:
        return _entry_diag_result(chat_id, symbol, 'data_error', 'داده بازار خالی دریافت شد', 'data')
    primary=calculate_indicators(d); primary_tf=tf; mode='single'
    # V2 نیاز به context واقعی HTF دارد: اجرای 5m/15m با 1h/4h/1d،
    # 1h با 4h/1d و 4h با 1d بررسی می‌شود. HTF فقط filter است و execution نیست.
    # توجه: '1d' (روزانه) از این‌جا به بعد صرفاً برای فیلتر break/entry نیست؛
    # پایه‌ی محاسبه‌ی روند ساختاری تایم بالاتر خودِ نماد هم هست (روزانه برای
    # 5m/15m/4h، و از روی همان روزانه، هفتگی هم با resample ساخته می‌شود —
    # طبق تصمیم مشترک با کاربر: «تشخیص روند از تایم بالاتر باید انجام شود»).
    if strat == 'dynamic':
        htf_specs = {
            '5min': [('1h', '1hour'), ('4h', '4hour'), ('1d', '1day')],
            '15min': [('1h', '1hour'), ('4h', '4hour'), ('1d', '1day')],
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
    # مهم: تشخیص «روند قطعی» که تعیین می‌کند خرید/فروش خلاف‌جهت مجاز است یا
    # نه، بر اساس روند خودِ این نماد (GRT/... ) نیست — بر اساس وضعیت کلی
    # بازار (همان «داشبورد بازار»، سبد ۱۰ ارز شاخص) است. طبق تصمیم صریح
    # کاربر: «در صورت قطعی بودن بازار صعودی حق باز کردن معامله فروش نداریم
    # و برعکس؛ فقط در بازار رنج با احتیاط هر دو جهت بررسی می‌شود» — این یک
    # قانون سراسری روی کل بازار است، نه یک فیلتر جداگانه به‌ازای هر نماد.
    signal_diag = {}
    global_regime = await get_global_market_regime(tf)
    # مدیریت روند معاملات: سوئیچ‌های دستی کاربر (منوی «مدیریت روند معاملات»)،
    # مستقل به‌ازای همین تایم‌فریم (tf)، روی همین یک درخواست، بدون دست‌کاری
    # strategy_config ذخیره‌شده در session، به تنظیمات مؤثر تزریق می‌شوند —
    # چون normalize_session در ری‌استارت‌ها strategy_config را از روی
    # پیش‌فرض تایم‌فریم بازسازی می‌کند و این سوئیچ‌ها جدا نگه داشته شده‌اند
    # تا آن ری‌ست را دور بزنند.
    tm = get_trend_mgmt(s, tf)
    effective_strategy_config = {
        **s['strategy_config'],
        'allow_buy_in_bearish_trend': tm['allow_buy_in_bearish'],
        'allow_sell_in_bullish_trend': tm['allow_sell_in_bullish'],
        'allow_buy_in_range': tm['allow_buy_in_range'],
        'allow_sell_in_range': tm['allow_sell_in_range'],
        'b7_s7_enabled': tm['b7_s7_enabled'],
        # وضعیت کلی بازار (BULLISH/BEARISH/RANGE/None) — به get_signal_with_reason
        # می‌گوید گیت روند قطعی را روی همین مقدار (نه روند خودِ نماد) بسنجد.
        'global_market_regime': global_regime,
    }
    # «کیفیت معاملات»: override روی امتیاز/RR/ADX پریست همین تایم‌فریم.
    # 'balanced' یعنی هیچ تغییری اعمال نشود (مقادیر خودِ پریست دست‌نخورده بماند).
    q_override = QUALITY_PROFILE_OVERRIDES.get(tm['quality_profile'])
    if q_override:
        effective_strategy_config.update(q_override)
    sig, reason = get_signal_with_reason(primary, md, mode, primary_tf, strat, s['filters'], effective_strategy_config, regime, live_price=live_entry_price, diag_out=signal_diag)
    # قبلاً برای مسیر اسکالپ (۵/۱۵ دقیقه) دیکشنری diagnostics همیشه خالی
    # ({}) ذخیره می‌شد چون _breakout_filter_diagnostics فقط برای مسیر
    # غیراسکالپ صدا زده می‌شد. حالا جزئیات موتور PDH/EQ/PDL (گیت رد شدن،
    # تعداد سوینگ‌های شناسایی‌شده) هم برای اسکالپ در فیلد data آدیت ذخیره
    # می‌شود تا در گزارش خروجی قابل بررسی باشد.
    diagnostics = _breakout_filter_diagnostics(primary, s['filters'], s['strategy_config']) if (strat == 'dynamic' and not is_scalp_strategy) else {}
    if signal_diag:
        diagnostics = {**diagnostics, **signal_diag}
    if not sig:
        return _entry_diag_result(chat_id, symbol, 'no_signal', reason or 'شرایط ورود کامل نیست', 'signal', diagnostics=diagnostics)
    grid_levels = await get_log_grid_levels(http, symbol) if is_scalp_strategy else None
    # V2 dynamic must use the same adaptive candidate-selection engine for BOTH
    # signal and plan. The seller build previously forced 5m/15m into the legacy
    # liquidity-sweep planner here, which could make signal and SL/TP come from
    # different strategy families.
    plan_strategy_type = 'dynamic' if (strat == 'dynamic' and s.get('strategy_config', {}).get('v2_enabled', True)) else ('liquidity_sweep' if is_scalp_strategy else strat)
    active_setup_index = None
    if is_scalp_strategy:
        m_active = re.search(r'ACTIVE_SETUP_INDEX=(\d+)', reason or '')
        if m_active:
            active_setup_index = int(m_active.group(1))
    plan, plan_reason = build_trade_plan(
        primary, sig, effective_strategy_config, plan_strategy_type,
        strategy_timeframe=primary_tf, grid_levels=grid_levels,
        setup_index=active_setup_index, live_price=live_entry_price,
        market_data_dict=md, filters=s['filters'], regime=regime
    )
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
    guard_ok, guard_reason = await leader_correlation_guard(http, chat_id, symbol, primary, primary_tf, side=sig)
    if not guard_ok:
        return _entry_diag_result(chat_id, symbol, 'leader_guard_blocked', guard_reason, 'leader_guard', sig)
    # 5m Swing->Break only: carry the structural swing level + its original ATR
    # buffer through to execution so a slipped fill re-anchors SL to real
    # structure instead of shifting the signal-time SL by a fixed distance.
    swing_level = None; swing_sl_buffer = None
    if primary_tf == '5min' and plan.get('setup_family') == 'swing_break' and plan.get('swing_level') is not None:
        swing_level = float(plan['swing_level'])
        swing_sl_buffer = abs(float(plan['swing_level']) - sl)
    ok=execute_trade(chat_id,symbol,'BUY (Long)' if sig=='BUY' else 'SELL (Short)',entry,sl,tp,full_reason,structural_tp=bool(plan.get('structural_target', False)),swing_level=swing_level,swing_sl_buffer=swing_sl_buffer,htf_trend=signal_diag.get('htf_trend'),tp_ladder={
        'tp1': plan.get('tp1'), 'tp2': plan.get('tp2'), 'tp3': plan.get('tp3', tp),
        'tp1_pct': plan.get('tp1_pct'), 'tp2_pct': plan.get('tp2_pct'), 'tp3_pct': plan.get('tp3_pct'),
    } if plan.get('tp1') is not None else None)
    if ok:
        return _entry_diag_result(chat_id, symbol, 'entry_opened', full_reason, 'entry', sig)
    block_reason = pop_execute_block_reason(chat_id)
    return _entry_diag_result(chat_id, symbol, 'execute_blocked',
                               f'سیگنال ایجاد شد اما اجرای ورود موفق نشد: {block_reason}' if block_reason
                               else 'سیگنال ایجاد شد اما اجرای ورود موفق نشد (دلیل دقیق ثبت نشد)',
                               'execute', sig)


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


def today_trades_report(chat_id):
    """Detailed list of trades closed on the current calendar day."""
    s = get_session(chat_id)
    closed = list(s.get('closed_positions') or [])

    tz = None
    if ZoneInfo is not None:
        try:
            tz = ZoneInfo(DAILY_CLOSE_TZ)
        except Exception:
            tz = None
    now_local = datetime.now(tz) if tz else datetime.utcnow()
    day_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start_ts = day_start.timestamp()

    trades = [
        p for p in closed
        if float(p.get('close_timestamp', 0) or 0) >= day_start_ts
    ]
    trades.sort(key=lambda p: float(p.get('close_timestamp', 0) or 0), reverse=True)

    if not trades:
        return (
            '📋 *معاملات امروز*\\n'
            '━━━━━━━━━━━━━━━━━━━━\\n'
            'امروز هنوز معامله بسته‌شده‌ای ثبت نشده است.'
        )

    lines = [
        f'📋 *معاملات امروز* — `{len(trades)}` معامله',
        '━━━━━━━━━━━━━━━━━━━━'
    ]

    for idx, p in enumerate(trades, 1):
        pnl = float(p.get('pnl_usdt', 0) or 0)
        side = '🟢 LONG' if side_long(p.get('side')) else '🔴 SHORT'
        close_ts = float(p.get('close_timestamp', 0) or 0)
        try:
            close_dt = datetime.fromtimestamp(close_ts, tz=tz) if tz else datetime.fromtimestamp(close_ts)
            close_time = close_dt.strftime('%H:%M')
        except Exception:
            close_time = '—'

        lines.extend([
            f'*{idx}. {p.get("symbol", "—")} | {side} | `{close_time}`*',
            f'• ورود: `{fmt(p.get("entry_price", 0))}`',
            f'• TP: `{fmt(p.get("tp", 0))}` | SL: `{fmt(p.get("sl", 0))}`',
            f'• سود/زیان: `{pnl:+.2f} USDT`',
            f'• علت بسته‌شدن: `{p.get("close_reason") or "—"}`',
            '━━━━━━━━━━━━━━━━━━━━'
        ])

    return '\\n'.join(lines).rstrip('━\\n ')

def trade_audit_report(chat_id):
    s=get_session(chat_id); positions=list(s.get('paper_positions') or []); closed=list(s.get('closed_positions') or [])
    allp=closed+positions
    if not allp: return '🔎 *ممیزی معامله*\n\nهنوز معامله‌ای برای بررسی ثبت نشده است.'
    p=max(allp,key=lambda x: float(x.get('opened_at',0) or 0)); tid=p.get('trade_id','—')
    lines=['🔎 *ممیزی صفر تا صد آخرین پوزیشن*','━━━━━━━━━━━━━━━━━━━━',f'🆔 شناسه: `{tid}`',f'🪙 نماد: `{p.get("symbol")}` | {"LONG" if side_long(p.get("side")) else "SHORT"}',f'⏱ تایم‌فریم: `{TF_DISPLAY.get(p.get("timeframe"),p.get("timeframe"))}`',f'🎯 Entry: `{fmt(p.get("entry_price",0))}` | SL: `{fmt(p.get("sl",0))}` | TP: `{fmt(p.get("tp",0))}`',f'📦 وضعیت: `{"بسته‌شده" if p in closed else "باز"}`']
    if p in closed:
        lines += [f'🚪 خروج: `{fmt(p.get("close_price",0))}`',f'💰 PnL: `{float(p.get("pnl_usdt",0) or 0):+.2f} USDT`',f'📝 علت خروج: `{p.get("close_reason","—")}`']
    return '\n'.join(lines)


def trade_tracking_keyboard(chat_id):
    s = get_session(chat_id)
    enabled = bool(s.get('trade_pipeline_enabled', False))
    icon = '🟢' if enabled else '🔴'
    state = 'روشن' if enabled else 'خاموش'
    return {
        'inline_keyboard': [
            [{'text': f'{icon} ردیابی معاملات: {state}', 'callback_data': '/toggle_trade_pipeline'}],
            [{'text': '📦 خروجی JSON کامل مسیر معاملات', 'callback_data': '/export_trade_pipeline'}],
            [{'text': '🧭 نمایش آخرین مسیرهای ثبت‌شده', 'callback_data': '/trade_pipeline'}],
            [{'text': '📈 عملکرد و گزارش‌ها', 'callback_data': '/performance'}],
            [{'text': '🗑 ریست کامل ربات (شروع از صفر)', 'callback_data': '/full_reset_prompt'}],
            [{'text': '🏠 منوی اصلی', 'callback_data': '/menu'}],
        ]
    }


def trade_pipeline_report(chat_id):
    s=get_session(chat_id)
    events=list(s.get('trade_pipeline_audit') or [])
    if not events:
        return '🔎 *ممیزی کامل مسیر معاملات*\n\nهنوز داده‌ای ثبت نشده است.'
    events=events[-120:]
    lines=['🔎 *ممیزی کامل مسیر معاملات*','━━━━━━━━━━━━━━━━━━━━',f'📌 آخرین رویدادها: `{len(events)}`','📍 واچ‌لیست: Dynamic DEX | هر دو جهت از یک Universe مشترک','']
    grouped={}
    for e in events:
        key=f"{e.get('symbol','?')}|{e.get('timeframe','?')}"
        grouped.setdefault(key,[]).append(e)
    for key, rows in list(grouped.items())[-40:]:
        last=rows[-1]
        path=' → '.join(str(x.get('stage') or '—') for x in rows[-8:])
        status=last.get('status','—')
        reason=last.get('reason','—')
        lines.append(f"• `{key}` → `{status}`\n  مسیر: `{path}`\n  علت نهایی: {reason}")
    return '\n'.join(lines)


def _export_timeframe_context(s, records):
    """Build an explicit, validated timeframe identity for every export."""
    account_tf = str(s.get('timeframe') or '5min')
    counts = {}
    for r in records:
        tf = str(r.get('timeframe') or '')
        if tf:
            counts[tf] = counts.get(tf, 0) + 1
    # An export belongs to exactly one Telegram session/timeframe. Mixed records are
    # retained for diagnostics but flagged so an external model cannot mistake them.
    present = sorted(counts)
    consistent = all(tf == account_tf for tf in present)
    return {
        'account_timeframe': account_tf,
        'account_timeframe_display': TF_DISPLAY.get(account_tf, account_tf),
        'timeframes_present': present,
        'timeframe_counts': counts,
        'timeframe_consistent': consistent,
        'export_scope': 'single_telegram_session',
    }

def _export_filename(prefix, timeframe):
    tf = str(timeframe or '5min').replace('min','m').replace('/','_')
    stamp = time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime())
    return f'{prefix}_{tf}_{stamp}.json'

def export_trade_pipeline(chat_id):
    if not is_admin(chat_id) or not TELEGRAM_TOKEN:
        return False
    s=get_session(chat_id)
    pipeline=list(s.get('trade_pipeline_audit') or [])
    opens=[audit_trade_record(p) for p in s.get('paper_positions',[])]
    closes=[audit_trade_record(p) for p in s.get('closed_positions',[])]
    records=opens+closes+pipeline
    tfmeta=_export_timeframe_context(s, records)
    payload={
        'report_metadata': {
            'report_type': 'trade_pipeline_audit',
            'generated_at': time.time(),
            'chat_id': chat_id,
            **tfmeta,
            'audit_enabled': bool(s.get('trade_pipeline_enabled', False)),
        },
        'watchlist': {
            'source': DEX_WATCHLIST_CACHE.get('source','fallback'),
            'size': len(_refresh_dynamic_dex_watchlist()),
            'symbols': _refresh_dynamic_dex_watchlist(),
            'tiers': DEX_WATCHLIST_CACHE.get('tiers',{}),
            # تاریخچه‌ی افزوده/حذف‌شدن نمادها از واچ‌لیست (منطق چسبندگی جدید) —
            # برای این‌که بشه دید آیا و کِی مجموعه‌ی نمادهای معامله‌شونده
            # واقعاً تغییر کرده، نه فقط اسنپ‌شات لحظه‌ای.
            'changes': DEX_WATCHLIST_CACHE.get('changes', []),
            'hysteresis_buffer': DEX_WATCHLIST_HYSTERESIS_BUFFER,
            'min_dwell_seconds': DEX_WATCHLIST_MIN_DWELL_SECONDS,
        },
        'pipeline_events': pipeline,
        'open_positions': opens,
        'closed_positions': closes,
    }
    raw=json.dumps(payload,ensure_ascii=False,indent=2,default=str).encode('utf-8')
    try:
        fname=_export_filename('trade_pipeline_audit', s.get('timeframe'))
        caption=f'🧭 خروجی کامل ممیزی Pipeline | تایم‌فریم: {TF_DISPLAY.get(s.get("timeframe"),s.get("timeframe"))} | {"✅ یکسان" if tfmeta["timeframe_consistent"] else "⚠️ مخلوط"}'
        resp = requests.post(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument',data={'chat_id':chat_id,'caption':caption},files={'document':(fname,io.BytesIO(raw),'application/json')},timeout=30)
        if not resp.ok or not (resp.json() or {}).get('ok', False):
            logger.warning('export trade pipeline telegram send failed: %s', resp.text[:500])
            send_message(chat_id, '❌ خروجی JSON ممیزی ساخته شد اما ارسال فایل به تلگرام ناموفق بود.')
            return False
        return True
    except Exception as exc:
        logger.warning('export trade pipeline failed: %s',exc)
        send_message(chat_id, f'❌ خطا در خروجی JSON ممیزی: {exc}')
        return False

def export_trade_data(chat_id):
    if not is_allowed(chat_id) or not TELEGRAM_TOKEN: return False
    s=get_session(chat_id)
    opens=[audit_trade_record(p) for p in s.get('paper_positions',[])]
    closes=[audit_trade_record(p) for p in s.get('closed_positions',[])]
    audit=list(s.get('trade_audit',[]))
    pipeline=list(s.get('trade_pipeline_audit',[]))
    records=opens+closes+audit+pipeline
    tfmeta=_export_timeframe_context(s, records)
    payload={
        'report_metadata': {
            'report_type': 'complete_trade_export',
            'generated_at': time.time(),
            'chat_id': chat_id,
            **tfmeta,
            'trade_count': len(opens)+len(closes),
        },
        'open_positions': opens,
        'closed_positions': closes,
        'trade_audit': audit,
        'trade_pipeline_audit': pipeline,
    }
    raw=json.dumps(payload,ensure_ascii=False,indent=2,default=str).encode('utf-8')
    try:
        fname=_export_filename('trades', s.get('timeframe'))
        caption=f'📦 خروجی کامل معاملات | تایم‌فریم: {TF_DISPLAY.get(s.get("timeframe"),s.get("timeframe"))} | {"✅ یکسان" if tfmeta["timeframe_consistent"] else "⚠️ مخلوط"}'
        requests.post(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument',data={'chat_id':chat_id,'caption':caption},files={'document':(fname,io.BytesIO(raw),'application/json')},timeout=30)
        return True
    except Exception as exc: logger.warning('export trade data failed: %s',exc); return False


def reset_stats(chat_id):
    s=get_session(chat_id)
    if s.get('paper_positions'):
        return False, '❌ تا وقتی پوزیشن باز دارید، ریست آمار مجاز نیست. ابتدا پوزیشن‌ها را ببندید.'
    s['closed_positions'] = []
    s['trade_audit'] = []
    s['trade_pipeline_audit'] = []
    s['scan_stats'] = {'scans':0,'symbols':0,'signals':0,'entries':0,'blocked':0,'data_errors':0,'reason_counts':{}}
    s['daily_stopped'] = False
    equity = exchange_balance(chat_id) if s.get('trading_mode') == 'REAL' else float(s.get('paper_balance', 1000.0))
    s['daily_start_equity'] = float(equity)
    s['daily_start_date'] = time.strftime('%Y-%m-%d', time.gmtime())
    save_session(chat_id)
    return True, f"✅ *آمار تست ریست شد*\n\nمبنای ریسک جدید: `{equity:.2f} USDT`"


def full_reset(chat_id):
    """پاک کردن کامل سشن این کاربر (پوزیشن‌ها، آمار، تنظیمات، فیلترها، همه‌چیز) و
    بازگشت به حالت پیش‌فرض کاملاً تازه — دقیقاً مثل یک کاربر جدید."""
    s = get_session(chat_id)
    if s.get('paper_positions'):
        return False, '❌ تا وقتی پوزیشن باز دارید، ریست کامل مجاز نیست. ابتدا همه پوزیشن‌ها را ببندید.'
    if s.get('is_bot_active'):
        stop_scan(chat_id, 'full-reset')
    with STATE_LOCK:
        USER_SESSIONS[chat_id] = default_session()
    save_session(chat_id)
    return True, '✅ *همه‌چیز پاک شد.*\nحالا از صفر شروع می‌کنیم؛ لطفاً تنظیمات را قدم‌به‌قدم دوباره انتخاب کنید.'


def analyze(chat_id,symbol):
    s=get_session(chat_id)
    tf=s['timeframe']
    d=get_klines(symbol,tf,min_klines_for_levels(tf))
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
    diag = "🟢 فعال" if s.get('entry_diag_enabled', True) else "🔴 خاموش"
    text=f"📊 *پنل اصلی ربات*\n\n🟢 اسکن: `{'فعال' if s['is_bot_active'] else 'متوقف'}`\n💳 حساب: `{'واقعی' if s['trading_mode']=='REAL' else 'کاغذی'}`  |  ⏱ تایم‌فریم: `{TF_DISPLAY.get(s['timeframe'],s['timeframe'])}`\n📈 استراتژی: `{'پویا (دوطرفه)' if s['active_strategy']=='dynamic' else s['active_strategy']}`\n💰 موجودی: `{bal:.2f} USDT`  |  ⚙️ مارجین: `{s['trade_amount_usdt']:.0f} USDT`\n📌 پوزیشن‌های باز: `{maxp}`  |  🔍 لاگ ورود: `{diag}`\n🛡 ریسک هر معامله: `{s['risk_per_trade_pct']:.2f}%`  |  حد ضرر روزانه: `{s['daily_loss_limit_pct']:.2f}%`\n\nاز منوی زیر بخش موردنظر را انتخاب کن:"
    send_message(chat_id,text,get_main_menu_keyboard(s['is_bot_active'], s.get('entry_diag_enabled', True), is_admin(chat_id), s),message_id)


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

# --- وضعیت کلی بازار: منبع واحد، هم برای «داشبورد بازار» (دستی) و هم برای
# گیت واقعی روند قطعی در scan_symbol. طبق تصمیم کاربر این دو باید همیشه
# دقیقاً یک عدد را نشان بدهند/استفاده کنند، نه دو منطق جدا (وگرنه دوباره
# می‌شود همون تناقض «داشبورد رنج ولی معامله‌ی خلاف‌جهت باز شد»).
MARKET_REGIME_CACHE: Dict[str, dict] = {}
MARKET_REGIME_CACHE_TTL_SECONDS = 120.0


def _classify_market_regime(tf):
    """طبقه‌بندی وضعیت کلی بازار بر مبنای سبد MARKET_REPORT_SYMBOLS.
    خروجی: (regime, bullish, bearish, ranged, total) — regime یکی از
    'BULLISH'|'BEARISH'|'RANGE' است، یا None اگر هیچ داده‌ای در دسترس نبود."""
    symbols = MARKET_REPORT_SYMBOLS
    results = []
    with ThreadPoolExecutor(max_workers=min(6, len(symbols))) as ex:
        futures = [ex.submit(_market_snapshot, sym, tf) for sym in symbols]
        for f in as_completed(futures):
            item = f.result()
            if item: results.append(item)
    if not results:
        return None, 0, 0, 0, 0
    total = len(results)
    bullish = sum(1 for x in results if x['score'] > 0)
    bearish = sum(1 for x in results if x['score'] < 0)
    ranged = total - bullish - bearish
    if bullish > bearish and bullish >= total * 0.5:
        regime = 'BULLISH'
    elif bearish > bullish and bearish >= total * 0.5:
        regime = 'BEARISH'
    else:
        regime = 'RANGE'
    return regime, bullish, bearish, ranged, total


async def get_global_market_regime(tf):
    """نسخه‌ی کش‌شده و async-safe از _classify_market_regime، برای صدا زدن
    از داخل scan_symbol بدون بلاک کردن event loop. اگر تازه‌سازی fail شود،
    آخرین مقدار معتبر کش برگردانده می‌شود (fail-safe، نه fail-open کامل)."""
    now = time.time()
    c = MARKET_REGIME_CACHE.get(tf)
    if c and now - c['ts'] < MARKET_REGIME_CACHE_TTL_SECONDS:
        return c['regime']
    try:
        regime, bullish, bearish, ranged, total = await asyncio.to_thread(_classify_market_regime, tf)
    except Exception as exc:
        logger.warning('global market regime classify failed tf=%s: %s', tf, exc)
        return c['regime'] if c else None
    if total == 0:
        return c['regime'] if c else None
    MARKET_REGIME_CACHE[tf] = {'ts': now, 'regime': regime, 'bullish': bullish, 'bearish': bearish, 'ranged': ranged, 'total': total}
    return regime


def market_report(chat_id):
    s = get_session(chat_id)
    tf = s['timeframe']
    regime, bullish, bearish, ranged, total = _classify_market_regime(tf)
    if not regime:
        return '❌ داده کافی برای ساخت داشبورد بازار دریافت نشد.'
    overall = {
        'BULLISH': '📈 بازار در مجموع در این تایم‌فریم تمایل صعودی دارد.',
        'BEARISH': '📉 بازار در مجموع در این تایم‌فریم تمایل نزولی دارد.',
        'RANGE': '➡️ بازار در مجموع در این تایم‌فریم رنج و بدون روند مشخص است.',
    }[regime]
    # همان مقدار تازه‌محاسبه‌شده را در کش هم می‌گذاریم تا اسکن زنده و پیام
    # دوره‌ای هم بلافاصله همین عدد تازه را ببینند، نه نسخه‌ی قدیمی‌تر کش.
    MARKET_REGIME_CACHE[tf] = {'ts': time.time(), 'regime': regime, 'bullish': bullish, 'bearish': bearish, 'ranged': ranged, 'total': total}
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


def process_command(cmd,chat_id,message_id=None):
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
        send_message(chat_id, performance_period_report(chat_id, 'all'), get_performance_keyboard(chat_id, s)); return
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

    TF_LABELS = {'5min': '۵ دقیقه', '15min': '۱۵ دقیقه', '1hour': '۱ ساعته', '4hour': '۴ ساعته'}
    if cl in ('/trend_management','🧭 مدیریت روند معاملات'):
        view_tf = s.get('trend_mgmt_view_tf') if s.get('trend_mgmt_view_tf') in SUPPORTED_TRADING_TIMEFRAMES else s.get('timeframe', '5min')
        s['trend_mgmt_view_tf'] = view_tf
        save_session(chat_id)
        edit_page(chat_id,
            f'🧭 *مدیریت روند معاملات — تایم‌فریم {TF_LABELS.get(view_tf, view_tf)}*\n\n'
            'این تنظیمات مستقل برای هر تایم‌فریم است. با دکمه‌های زیر می‌توانید '
            'تایم‌فریمی که می‌خواهید تنظیماتش را ببینید/تغییر دهید انتخاب کنید '
            '(بدون این‌که تایم‌فریم فعلی اسکن ربات عوض شود).\n\n'
            'پیش‌فرض طبق تشخیص خودکار استراتژی است:\n'
            '📉 روند نزولی قطعی → خرید بسته\n'
            '📈 روند صعودی قطعی → فروش بسته\n'
            '➡️ رنج → هر دو جهت با حساسیت بالا باز\n\n'
            'هرکدام را می‌توانید دستی تغییر دهید:',
            get_trend_management_keyboard(s), message_id)
        return
    if cl.startswith('/tm_tf_'):
        tf_key = cl.replace('/tm_tf_', '')
        if tf_key in SUPPORTED_TRADING_TIMEFRAMES:
            s['trend_mgmt_view_tf'] = tf_key
            save_session(chat_id)
            edit_page(chat_id, f'🧭 *مدیریت روند معاملات — تایم‌فریم {TF_LABELS.get(tf_key, tf_key)}*', get_trend_management_keyboard(s), message_id)
        return
    if cl == '/toggle_trend_buy_bearish':
        tm = get_trend_mgmt(s, s.get('trend_mgmt_view_tf'))
        tm['allow_buy_in_bearish'] = not bool(tm['allow_buy_in_bearish'])
        save_session(chat_id)
        edit_page(chat_id, f"🛒 خرید در روند نزولی قطعی ({TF_LABELS.get(s.get('trend_mgmt_view_tf'), '')}): {'🟢 روشن شد' if tm['allow_buy_in_bearish'] else '🔴 خاموش شد (پیش‌فرض استراتژی)'}", get_trend_management_keyboard(s), message_id); return
    if cl == '/toggle_trend_sell_bullish':
        tm = get_trend_mgmt(s, s.get('trend_mgmt_view_tf'))
        tm['allow_sell_in_bullish'] = not bool(tm['allow_sell_in_bullish'])
        save_session(chat_id)
        edit_page(chat_id, f"📤 فروش در روند صعودی قطعی ({TF_LABELS.get(s.get('trend_mgmt_view_tf'), '')}): {'🟢 روشن شد' if tm['allow_sell_in_bullish'] else '🔴 خاموش شد (پیش‌فرض استراتژی)'}", get_trend_management_keyboard(s), message_id); return
    if cl == '/toggle_trend_buy_range':
        tm = get_trend_mgmt(s, s.get('trend_mgmt_view_tf'))
        tm['allow_buy_in_range'] = not bool(tm['allow_buy_in_range'])
        save_session(chat_id)
        edit_page(chat_id, f"🛒 خرید در بازار رنج ({TF_LABELS.get(s.get('trend_mgmt_view_tf'), '')}): {'🟢 روشن' if tm['allow_buy_in_range'] else '🔴 خاموش شد'}", get_trend_management_keyboard(s), message_id); return
    if cl == '/toggle_trend_sell_range':
        tm = get_trend_mgmt(s, s.get('trend_mgmt_view_tf'))
        tm['allow_sell_in_range'] = not bool(tm['allow_sell_in_range'])
        save_session(chat_id)
        edit_page(chat_id, f"📤 فروش در بازار رنج ({TF_LABELS.get(s.get('trend_mgmt_view_tf'), '')}): {'🟢 روشن' if tm['allow_sell_in_range'] else '🔴 خاموش شد'}", get_trend_management_keyboard(s), message_id); return
    if cl == '/toggle_b7s7':
        tm = get_trend_mgmt(s, s.get('trend_mgmt_view_tf'))
        tm['b7_s7_enabled'] = not bool(tm['b7_s7_enabled'])
        save_session(chat_id)
        edit_page(chat_id, f"⚙️ حالت B7/S7 ({TF_LABELS.get(s.get('trend_mgmt_view_tf'), '')}): {'🟢 فعال شد' if tm['b7_s7_enabled'] else '🔴 خاموش شد'}", get_trend_management_keyboard(s), message_id); return
    if cl in ('/qp_conservative','/qp_balanced','/qp_opportunity'):
        profile={'/qp_conservative':'conservative','/qp_balanced':'balanced','/qp_opportunity':'opportunity'}[cl]
        tm = get_trend_mgmt(s, s.get('trend_mgmt_view_tf'))
        tm['quality_profile'] = profile
        save_session(chat_id)
        label = {'conservative':'کیفیت بالاتر (سیگنال کمتر)','balanced':'حالت پیش‌فرض (متعادل)','opportunity':'کیفیت پایین‌تر (سیگنال بیشتر)'}[profile]
        edit_page(chat_id,f"🟢 *کیفیت معاملات ({TF_LABELS.get(s.get('trend_mgmt_view_tf'), '')}) روی «{label}» تنظیم شد.*",get_trend_management_keyboard(s),message_id); return
    if cl == '/trend_mgmt_reset':
        view_tf = s.get('trend_mgmt_view_tf') if s.get('trend_mgmt_view_tf') in SUPPORTED_TRADING_TIMEFRAMES else s.get('timeframe', '5min')
        s.setdefault('trend_mgmt', {})[view_tf] = dict(TREND_MGMT_DEFAULTS)
        save_session(chat_id)
        edit_page(chat_id,f'♻️ *تنظیمات «مدیریت روند معاملات» برای تایم‌فریم {TF_LABELS.get(view_tf, view_tf)} به پیش‌فرض استراتژی بازگشت.*',get_trend_management_keyboard(s),message_id); return

    if cl.startswith('/view_chart_'):
        sym = cl.replace('/view_chart_', '').upper()
        pos = next((p for p in s.get('paper_positions', []) if p['symbol'] == sym), None)
        if not pos:
            send_message(chat_id, f'❌ پوزیشن باز برای `{sym}` یافت نشد.')
            return
        tf = pos.get('timeframe', '5min')
        df = get_klines(sym, tf, min_klines_for_levels(tf))
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
    if cl == '/why_no_entry':
        edit_page(chat_id, _why_no_entry_report(chat_id), get_entry_diag_keyboard(s.get('entry_diag_enabled', True)), message_id); return
    if cl == '/entry_diag_log':
        window = list((ENTRY_DIAG_STATE.get(chat_id) or {}).get('window_results') or [])
        if not window:
            edit_page(chat_id, '📋 هنوز داده‌ی تشخیصی ثبت نشده است.', get_entry_diag_keyboard(s.get('entry_diag_enabled', True)), message_id); return
        data_errs = [x for x in window if x.get('status') in ('data_error', 'insufficient_data')]
        lines = ['📋 *آخرین موارد خطای داده (نماد مشخص)*', '━━━━━━━━━━━━━━━━━━━━']
        if data_errs:
            seen_syms = {}
            for x in reversed(data_errs):
                seen_syms.setdefault(x.get('symbol', '?'), x.get('reason', ''))
            for sym, reason in list(seen_syms.items())[:20]:
                lines.append(f'• `{sym}` — {reason}')
        else:
            lines.append('موردی یافت نشد.')
        edit_page(chat_id, '\n'.join(lines), get_entry_diag_keyboard(s.get('entry_diag_enabled', True)), message_id); return
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
        _send_or_edit_positions_view(chat_id, message_id=message_id)
        return
    if cl in ('/manage_watchlist','/watchlist_list'):
        wl = _refresh_dynamic_dex_watchlist(force=True)
        tiers = DEX_WATCHLIST_CACHE.get('tiers', {})
        source = DEX_WATCHLIST_CACHE.get('source','fallback')
        lines = [f'📋 *واچ‌لیست فعال Dynamic DEX*', '━━━━━━━━━━━━━━━━━━━━', f'📊 تعداد: `{len(wl)}` نماد', f'🔄 منبع: `{source}`', '', f'🅰️ Tier A: `{len(tiers.get("A",[]))}` نماد', f'🅱️ Tier B: `{len(tiers.get("B",[]))}` نماد', f'🅲 Tier C: `{len(tiers.get("C",[]))}` نماد', '']
        if wl:
            lines.append('`' + '، '.join(wl) + '`')
        edit_page(chat_id, '\n'.join(lines), get_watchlist_manage_keyboard(), message_id); return
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
    if cl == '/trade_tracking':
        if not is_admin(chat_id):
            send_message(chat_id, '⛔ این بخش فقط برای Admin است.')
            return
        send_message(chat_id, '🧭 *ردیابی معاملات*\n\nاز این بخش می‌توانید ثبت مسیر معاملات را روشن/خاموش کنید یا خروجی کامل JSON بگیرید.', trade_tracking_keyboard(chat_id))
        return
    if cl == '/full_reset_prompt':
        send_message(chat_id, '⚠️ *ریست کامل ربات*\n\nاین کار همه‌چیز را برای همیشه پاک می‌کند: پوزیشن‌ها، تاریخچه معاملات، آمار، فیلترها و تمام تنظیمات شما (تایم‌فریم، حالت حساب، مارجین، اهرم و...).\nبعد از تأیید، دوباره از صفر و قدم‌به‌قدم تنظیمات را از شما می‌پرسیم.\n\nآیا مطمئن هستید؟', {"inline_keyboard": [[{"text":"🗑 بله، همه‌چیز پاک شود","callback_data":"/full_reset_confirm"},{"text":"❌ انصراف","callback_data":"/cancel"}]]})
        return
    if cl == '/full_reset_confirm':
        ok, msg = full_reset(chat_id)
        send_message(chat_id, msg)
        if ok:
            send_message(chat_id, '🤖 *ربات معامله‌گر*\n\nحالت حساب را انتخاب کنید.', get_start_keyboard())
            sync_bottom_keyboard(chat_id, "🔴 اسکن متوقف است.\n⚙️ تنظیمات آماده تغییر هستند.")
        return
    if cl in ('/performance_today','/performance_week','/performance_month','/performance','/today_trades','/trade_audit','/trade_pipeline','/toggle_trade_pipeline','/export_trade_pipeline','/export_trade_data','/reset_stats_prompt','/reset_stats_confirm'):
        if cl=='/performance_today': send_message(chat_id, performance_period_report(chat_id, 'day'), get_performance_keyboard(chat_id, s))
        elif cl=='/performance_week': send_message(chat_id, performance_period_report(chat_id, 'week'), get_performance_keyboard(chat_id, s))
        elif cl=='/performance_month': send_message(chat_id, performance_period_report(chat_id, 'month'), get_performance_keyboard(chat_id, s))
        elif cl=='/performance': send_message(chat_id, performance_period_report(chat_id, 'all'), get_performance_keyboard(chat_id, s))
        elif cl=='/today_trades': send_message(chat_id, today_trades_report(chat_id), get_performance_keyboard(chat_id, s))
        elif cl=='/trade_audit': send_message(chat_id, trade_audit_report(chat_id), get_performance_keyboard(chat_id, s))
        elif cl=='/toggle_trade_pipeline':
            if not is_admin(chat_id):
                send_message(chat_id, '⛔ این کنترل فقط برای Admin فعال است.'); return
            s['trade_pipeline_enabled'] = not s.get('trade_pipeline_enabled', False); save_session(chat_id); send_message(chat_id, f"🧭 ردیابی معاملات: {'🟢 روشن' if s['trade_pipeline_enabled'] else '🔴 خاموش'}", trade_tracking_keyboard(chat_id))
        elif cl=='/trade_pipeline':
            if not is_admin(chat_id):
                send_message(chat_id, '⛔ این بخش فقط برای Admin است.'); return
            send_message(chat_id, trade_pipeline_report(chat_id), trade_tracking_keyboard(chat_id))
        elif cl=='/export_trade_pipeline':
            if not is_admin(chat_id):
                send_message(chat_id, '⛔ این بخش فقط برای Admin است.'); return
            export_trade_pipeline(chat_id)
        elif cl=='/export_trade_data': export_trade_data(chat_id)

        elif cl=='/reset_stats_prompt':
            send_message(chat_id,'⚠️ آیا از ریست آمار عملکرد اطمینان دارید؟', {"inline_keyboard": [[{"text":"🔄 بله، ریست کن","callback_data":"/reset_stats_confirm"},{"text":"❌ انصراف","callback_data":"/cancel"}]]})
        elif cl=='/reset_stats_confirm':
            ok,msg=reset_stats(chat_id); send_message(chat_id,msg,get_performance_keyboard(chat_id, s) if ok else None)
        return


def handle_text(chat_id,text):
    raw=(text or '').strip()
    fixed_buttons={
        '🏠 منوی اصلی':'/menu', 'منوی اصلی':'/menu',
        '🔄 پوزیشن‌های باز':'/open_positions', 'پوزیشن‌های باز':'/open_positions',
        '🔄 پوزیشن‌ها':'/open_positions', 'پوزیشن‌ها':'/open_positions', '🔄 پیگیری پوزیشن‌ها':'/open_positions', 'پیگیری پوزیشن‌ها':'/open_positions',
        '📈 گزارش عملکرد کلی':'/performance', 'گزارش عملکرد کلی':'/performance',
        '📋 معاملات امروز':'/today_trades', 'معاملات امروز':'/today_trades',
        '📊 وضعیت بازار':'/market_report', 'وضعیت بازار':'/market_report',
        '⚙️ تنظیمات معامله':'/check_wizard', 'تنظیمات معامله':'/check_wizard',
        '📋 واچ‌لیست':'/manage_watchlist', 'واچ‌لیست':'/manage_watchlist',
        '❌ بستن همه':'/close_all_prompt', 'بستن همه':'/close_all_prompt',
        '🆘 بستن اضطراری همه':'/emergency_close_all', 'بستن اضطراری همه':'/emergency_close_all',
        '🖐 معامله دستی':'/manual_trade', 'معامله دستی':'/manual_trade',
    }
    if raw in fixed_buttons:
        process_command(fixed_buttons[raw],chat_id); return

    s=get_session(chat_id); val=raw.upper()
    current_state = str(s.get('user_state') or '')

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


# --- پیام دوره‌ای: وضعیت کلی بازار باید دقیقاً همون منبعی باشد که خودِ
# scan_symbol برای گیت «روند قطعی» چک می‌کند (get_global_market_regime،
# همان منطق «داشبورد بازار»)، نه یک محاسبه‌ی جداگانه — تا هیچ‌وقت پیامی که
# کاربر می‌بیند با تصمیم واقعی معامله در تناقض نباشد.
MARKET_REGIME_LABELS = {
    'BULLISH': '📈 صعودی',
    'BEARISH': '📉 نزولی',
    'RANGE': '➡️ رنج (خنثی)',
    None: '➡️ رنج (خنثی)',
}


async def _send_periodic_heartbeat():
    now = time.time()
    due = []
    for cid, sess in list(USER_SESSIONS.items()):
        if not sess.get('is_bot_active') or sess.get('daily_stopped'):
            continue
        last = float(HEARTBEAT_LAST_SENT.get(cid, 0.0) or 0.0)
        if not last or now - last >= HEARTBEAT_INTERVAL_SECONDS:
            due.append(cid)
    if not due:
        return
    price = latest_price('BTC')
    price_txt = f"${price:,.2f}" if price else "نامشخص (خطای دریافت قیمت)"
    regime_by_tf = {}
    for cid in due:
        sess = USER_SESSIONS.get(cid) or {}
        tf = sess.get('timeframe', '5min')
        if tf not in regime_by_tf:
            regime_by_tf[tf] = await get_global_market_regime(tf)
        regime_label = MARKET_REGIME_LABELS.get(regime_by_tf[tf], MARKET_REGIME_LABELS[None])
        message = (
            HEARTBEAT_TEXT + "\n\n"
            f"📊 وضعیت کلی بازار ( براساس داشبورد بازار ): {regime_label}\n"
            f"💰 قیمت لحظه‌ای BTC: {price_txt}"
        )
        try:
            send_message(cid, message)
            HEARTBEAT_LAST_SENT[cid] = now
        except Exception as exc:
            logger.warning('heartbeat send failed chat=%s: %s', cid, exc)



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
                    if s['max_open_positions']>0 and len(s['paper_positions'])>=s['max_open_positions']:
                        _entry_diag_batch_update(cid, [{'status':'blocked','reason':f"ظرفیت پوزیشن‌های باز پر است ({len(s['paper_positions'])}/{s['max_open_positions']})"}])
                        continue
                    watchlist = scan_watchlist_for_timeframe(s.get('timeframe','5min'))
                    for sym in watchlist:
                        tasks.append(scan_symbol(http,cid,sym))
                if tasks:
                    batch = await asyncio.gather(*tasks, return_exceptions=True)
                    by_chat = {}
                    for item in batch:
                        if isinstance(item, dict) and item.get('chat_id') is not None:
                            by_chat.setdefault(item['chat_id'], []).append(item)
                    for cid, results in by_chat.items():
                        _entry_diag_batch_update(cid, results)
                await _send_periodic_heartbeat()
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
