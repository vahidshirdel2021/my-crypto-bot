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
    strategy_breakout, strategy_mean_reversion, build_trade_plan,
)
from ui import (
    get_start_keyboard, get_balance_keyboard, get_margin_keyboard, get_leverage_keyboard,
    get_max_positions_keyboard, get_timeframe_keyboard, get_main_menu_keyboard,
    get_watchlist_manage_keyboard, get_strategies_selection_keyboard,
    get_filters_menu_keyboard, get_params_menu_keyboard, get_positions_keyboard,
    get_bottom_menu_keyboard, get_confirm_close_all_keyboard, get_strategies_menu_keyboard, get_learn_menu_keyboard,
    get_performance_keyboard, get_ai_settings_keyboard, get_ai_chat_keyboard, get_entry_diag_keyboard,
)

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
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
REAL_RESTART_LOCK = os.environ.get('REAL_RESTART_LOCK', 'true').lower() not in ('0', 'false', 'no')
MARGIN_MODE = os.environ.get('MARGIN_MODE', 'isolated').lower()
PROTECTION_TRIGGER = os.environ.get('PROTECTION_TRIGGER', 'mark_price').lower()
ORDER_CONFIRM_RETRIES = max(1, int(os.environ.get('ORDER_CONFIRM_RETRIES', '5')))
ORDER_CONFIRM_DELAY = max(0.25, float(os.environ.get('ORDER_CONFIRM_DELAY', '1.0')))
PAPER_CONSERVATIVE_OHLC = os.environ.get('PAPER_CONSERVATIVE_OHLC', 'true').lower() not in ('0', 'false', 'no')
TELEGRAM_SKIP_BACKLOG = os.environ.get('TELEGRAM_SKIP_BACKLOG', 'true').lower() not in ('0', 'false', 'no')

# AI Multi-Provider (analysis only; never controls orders or risk)
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '').strip()
OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-5.6').strip()
GEMINI_API_KEY = (os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY') or '').strip()
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-3.5-flash').strip()
AI_TIMEOUT_SECONDS = max(10, int(os.environ.get('AI_TIMEOUT_SECONDS', '45')))
AI_CACHE = {}
AI_CACHE_TTL = 120


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
# وضعیت موقت گزارش تشخیصی عدم ورود؛ برای هر کاربر در حافظه نگهداری می‌شود.
ENTRY_DIAG_STATE: Dict[int, Dict[str, Any]] = {}
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
        'ai_chat_history': [],
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
        'bottom_menu_open': True,
        # گزارش تشخیصی عدم ورود در تلگرام به‌صورت پیش‌فرض فعال است.
        # لاگ سرور ENTRY_DIAG مستقل از این گزینه و همیشه فعال می‌ماند.
        'entry_diag_enabled': True,
        'ai_provider': ('gemini' if GEMINI_API_KEY else ('openai' if OPENAI_API_KEY else 'off')),
    }


def normalize_session(data):
    s = default_session(); s.update(data or {})
    s['filters'] = {**FILTER_DEFAULTS, **(data.get('filters') or {})}
    s['strategy_config'] = {**STRATEGY_DEFAULTS, **(data.get('strategy_config') or {})}
    s['user_experience'] = data.get('user_experience') if data.get('user_experience') in ('simple','advanced') else 'simple'
    s['paper_positions'] = list(data.get('paper_positions') or [])
    s['closed_positions'] = list(data.get('closed_positions') or [])
    s['cooldowns'] = dict(data.get('cooldowns') or {})
    s['ai_chat_history'] = list(data.get('ai_chat_history') or [])[-12:]
    s['active_symbols'] = list(data.get('active_symbols') or ALL_SYMBOLS[:])
    for k in ('paper_balance','daily_start_equity','trade_amount_usdt','daily_loss_limit_pct','risk_per_trade_pct','max_margin_usage_pct'):
        s[k] = float(s.get(k, default_session()[k]))
    s['is_bot_active'] = False if REAL_RESTART_LOCK else bool(s.get('is_bot_active', False))
    s['scan_generation'] = int(s.get('scan_generation', 0) or 0)
    s['bottom_menu_open'] = bool(s.get('bottom_menu_open', True))
    s['entry_diag_enabled'] = bool(s.get('entry_diag_enabled', True))
    if s.get('ai_provider') not in ('gemini','openai','off'):
        s['ai_provider'] = 'gemini' if GEMINI_API_KEY else ('openai' if OPENAI_API_KEY else 'off')
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


TELEGRAM_COMMANDS = [
    {'command':'menu','description':'منوی اصلی'},
    {'command':'ai_chat','description':'گفت‌وگو با هوش مصنوعی'},
    {'command':'ai_market','description':'تحلیل هوشمند بازار'},
    {'command':'market_report','description':'گزارش وضعیت بازار'},
    {'command':'open_positions','description':'پوزیشن‌های باز'},
    {'command':'performance','description':'گزارش عملکرد'},
    {'command':'ai_settings','description':'تنظیمات هوش مصنوعی'},
]

def configure_telegram_native_menu():
    """منوی بومی تلگرام را کنار کادر پیام فعال می‌کند و Reply Keyboard قبلی را حذف می‌کند."""
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
        # اگر محتوا دقیقاً همان قبلی باشد، نباید پیام تکراری ساخته شود.
        desc = ((res or {}).get('description') or '').lower()
        if 'message is not modified' in desc:
            return True
    body = {'chat_id':chat_id,'text':text,'reply_markup':markup}
    if parse_mode: body['parse_mode'] = parse_mode
    res = tg('sendMessage', body, 10)
    return bool(res and res.get('ok'))


def edit_page(chat_id, text, markup=None, message_id=None, parse_mode='Markdown'):
    """نمایش یک صفحه از رابط کاربری؛ در callback همان پیام را ویرایش می‌کند.
    اگر message_id مربوط به پیام کاربر باشد، send_message به‌صورت خودکار fallback می‌کند.
    """
    return send_message(chat_id, text, markup, message_id=message_id, parse_mode=parse_mode)


def sync_bottom_keyboard(chat_id, status_message=None):
    """ReplyKeyboard را مستقل از InlineKeyboard منوی اصلی به‌روز می‌کند."""
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



def ai_extract_text(data):
    if not isinstance(data, dict): return ''
    if isinstance(data.get('output_text'), str) and data.get('output_text').strip():
        return data['output_text'].strip()
    chunks=[]
    for item in data.get('output', []) or []:
        for content in item.get('content', []) or []:
            text=content.get('text')
            if isinstance(text, str) and text.strip(): chunks.append(text.strip())
    if chunks: return '\n'.join(chunks).strip()
    for cand in data.get('candidates', []) or []:
        content=cand.get('content') or {}
        for part in content.get('parts', []) or []:
            text=part.get('text')
            if isinstance(text, str) and text.strip(): chunks.append(text.strip())
    return '\n'.join(chunks).strip()


def ai_provider_status(s):
    provider=s.get('ai_provider','off')
    if provider=='gemini': return 'Gemini' if GEMINI_API_KEY else 'Gemini — کلید تنظیم نشده'
    if provider=='openai': return 'OpenAI' if OPENAI_API_KEY else 'OpenAI — کلید تنظیم نشده'
    return 'خاموش'


def ai_settings_text(chat_id):
    s=get_session(chat_id)
    return ('🤖 *تنظیمات هوش مصنوعی*\n\n'
            f'ارائه‌دهنده فعلی: *{ai_provider_status(s)}*\n\n'
            f'Gemini: {"🟢 آماده" if GEMINI_API_KEY else "🔴 کلید ندارد"}\n'
            f'OpenAI: {"🟢 آماده" if OPENAI_API_KEY else "🔴 کلید ندارد"}\n\n'
            '🔐 کلیدها فقط از محیط اجرای ربات خوانده می‌شوند و در تلگرام نمایش داده نمی‌شوند.\n'
            '🛡️ هوش مصنوعی فقط تحلیل می‌کند و اجازه اجرای معامله یا تغییر ریسک را ندارد.')


def _ai_system_prompt():
    return (
        'تو تحلیل‌گر کمکی یک ربات معامله‌گری فارسی‌زبان هستی. '
        'خروجی نهایی باید ۱۰۰٪ فارسی و راست‌خوان باشد و نباید هیچ جمله انگلیسی داشته باشد. '
        'فقط نام نمادها و اصطلاحات فنی استاندارد مانند BTC، ETH، SOL، EMA50، RSI، ADX، ATR، Entry، SL، TP و R:R '
        'می‌توانند به همان شکل انگلیسی باقی بمانند. '
        'هر پاسخ را با یک جمله کامل فارسی شروع کن و هرگز پاسخ را از وسط یک جمله یا سناریو آغاز نکن. '
        'ساختار پیشنهادی: خلاصه تحلیل، وضعیت بازار، سناریوهای محتمل، نکات ریسک. '
        'اگر داده ناقص است صریحاً بگو. هرگز تضمین سود نده و هرگز دستور قطعی خرید/فروش صادر نکن. '
        'وظیفه تو تحلیل و توضیح است، نه اجرای معامله. هیچ پارامتری را خودکار تغییر نده. '
        'اگر درباره معامله نظر می‌دهی Entry/SL/TP/R:R و شرایط بازار را جداگانه بررسی کن و در پایان سطح ریسک را بگو. '
        'مهم: حتی اگر بخشی از ورودی انگلیسی باشد، خروجی را به فارسی روان بازنویسی کن و متن انگلیسی ورودی را کپی نکن.'
    )


def _ai_needs_persian_rewrite(text):
    """تشخیص می‌دهد آیا پاسخ AI عملاً انگلیسی/ناقص است و باید دوباره بازنویسی شود."""
    if not text or len(text.strip()) < 25:
        return True
    import re
    fa = len(re.findall(r'[\u0600-\u06FF]', text))
    latin = len(re.findall(r'[A-Za-z]', text))
    # اگر فارسی بسیار کم باشد، پاسخ احتمالاً انگلیسی است. اصطلاحات فنی کوتاه مجازند.
    if fa == 0:
        return True
    if latin > max(45, fa * 0.65):
        return True
    # پاسخ نباید با یک قطعه انگلیسی یا جمله نیمه‌کاره شروع شود.
    first = text.strip().splitlines()[0].strip()
    if re.match(r'^[A-Za-z0-9].{8,}', first) and not re.match(r'^(BTC|ETH|SOL|BNB|XRP|DOGE|ADA)\b', first):
        return True
    return False


def _gemini_persian_rewrite(draft):
    """یک بار پاسخ Gemini را در همان مدل، به فارسی روان و کامل بازنویسی می‌کند."""
    instruction = (
        'متن زیر پیش‌نویس تحلیل است. آن را از نو و بدون حذف اطلاعات مهم به فارسی روان، کامل و حرفه‌ای بازنویسی کن. '
        'هیچ جمله انگلیسی باقی نگذار؛ فقط نمادها و اصطلاحات فنی استاندارد مانند EMA50، RSI، ADX، ATR، Entry، SL، TP و R:R مجازند. '
        'پاسخ باید با یک جمله کامل فارسی شروع شود و از وسط جمله شروع نشود. هیچ توضیحی درباره فرایند بازنویسی نده.\n\n'
        f'پیش‌نویس:\n{draft}'
    )
    body = {
        'systemInstruction': {'parts':[{'text': _ai_system_prompt()}]},
        'contents':[{'role':'user','parts':[{'text': instruction}]}],
        'generationConfig': {'maxOutputTokens': 1400, 'temperature': 0.2},
    }
    url=f'https://generativelanguage.googleapis.com/v1/models/{GEMINI_MODEL}:generateContent'
    try:
        r=requests.post(url, headers={'x-goog-api-key':GEMINI_API_KEY,'Content-Type':'application/json'}, json=body, timeout=AI_TIMEOUT_SECONDS)
        if r.status_code == 200:
            rewritten=ai_extract_text(r.json())
            if rewritten:
                return rewritten
        logger.warning('Gemini Persian rewrite failed: %s', r.status_code)
    except Exception:
        logger.exception('Gemini Persian rewrite failed')
    return draft


def ai_call_gemini(payload):
    if not GEMINI_API_KEY:
        return None, '⚠️ کلید Gemini تنظیم نشده است. متغیر GEMINI_API_KEY را در محیط اجرا قرار دهید.'
    body={'systemInstruction': {'parts':[{'text':_ai_system_prompt()}]},
          'contents':[{'role':'user','parts':[{'text':json.dumps(payload,ensure_ascii=False,indent=2,default=str)}]}],
          'generationConfig': {'maxOutputTokens':1200}}
    url=f'https://generativelanguage.googleapis.com/v1/models/{GEMINI_MODEL}:generateContent'
    try:
        r=requests.post(url,headers={'x-goog-api-key':GEMINI_API_KEY,'Content-Type':'application/json'},json=body,timeout=AI_TIMEOUT_SECONDS)
        if r.status_code!=200:
            logger.warning('Gemini API error %s: %s',r.status_code,r.text[:700])
            if GEMINI_API_KEY.startswith('AQ') and r.status_code in (401,403):
                return None, '❌ Gemini کلید AQ فعلاً توسط API پذیرفته نشد (401/403). کلید را در AI Studio بررسی و در صورت نیاز کلید جدید بسازید.'
            return None, f'❌ ارتباط با Gemini ناموفق بود. کد خطا: {r.status_code}'
        text=ai_extract_text(r.json())
        if not text:
            return None,'❌ Gemini پاسخی تولید نکرد.'
        # اگر مدل برخلاف دستور، انگلیسی یا ناقص جواب داد، یک بار همان پاسخ را
        # با دستور سخت‌گیرانه به فارسی روان بازنویسی می‌کنیم.
        if _ai_needs_persian_rewrite(text):
            text=_gemini_persian_rewrite(text)
        return (text,None) if text else (None,'❌ Gemini پاسخی تولید نکرد.')
    except Exception:
        logger.exception('Gemini call failed')
        return None,'❌ خطا در ارتباط با Gemini. اتصال اینترنت و کلید API را بررسی کنید.'


def ai_call_openai(payload):
    if not OPENAI_API_KEY: return None,'⚠️ کلید OpenAI تنظیم نشده است.'
    body={'model':OPENAI_MODEL,'input':[{'role':'system','content':_ai_system_prompt()},
          {'role':'user','content':json.dumps(payload,ensure_ascii=False,indent=2,default=str)}], 'max_output_tokens':1200}
    try:
        r=requests.post('https://api.openai.com/v1/responses',headers={'Authorization':f'Bearer {OPENAI_API_KEY}','Content-Type':'application/json'},json=body,timeout=AI_TIMEOUT_SECONDS)
        if r.status_code!=200:
            logger.warning('OpenAI API error %s: %s',r.status_code,r.text[:500])
            return None,f'❌ ارتباط با OpenAI ناموفق بود. کد خطا: {r.status_code}'
        text=ai_extract_text(r.json())
        return (text,None) if text else (None,'❌ OpenAI پاسخی تولید نکرد.')
    except Exception:
        logger.exception('OpenAI call failed')
        return None,'❌ خطا در ارتباط با OpenAI. کلید و اتصال را بررسی کنید.'


def ai_call(chat_id,purpose,payload,force=False):
    s=get_session(chat_id); provider=s.get('ai_provider','off')
    if provider=='off': return '🤖 هوش مصنوعی خاموش است. از «تنظیمات هوش مصنوعی» یک ارائه‌دهنده را انتخاب کنید.'
    key=hashlib.sha256((str(chat_id)+'|'+provider+'|'+purpose+'|'+json.dumps(payload,ensure_ascii=False,sort_keys=True,default=str)).encode()).hexdigest()
    cached=AI_CACHE.get(key)
    if not force and cached and time.time()-cached['ts']<AI_CACHE_TTL: return cached['text']
    text,err=(ai_call_gemini(payload) if provider=='gemini' else ai_call_openai(payload))
    if err: return err
    result='🤖 *تحلیل هوش مصنوعی*\n\n'+text
    AI_CACHE[key]={'ts':time.time(),'text':result}
    return result


def ai_market_report(chat_id):
    s=get_session(chat_id); tf='5min' if s['timeframe']=='multi' else s['timeframe']; rows=[]
    for sym in ['BTC','ETH','SOL','BNB','XRP','DOGE','ADA']:
        d=get_klines(sym,tf,140)
        if d.empty: continue
        ind=calculate_indicators(d); c=ind.iloc[-2]
        rows.append({'نماد':sym,'قیمت':float(c.close),'EMA20':float(c.ema20),'EMA50':float(c.ema50),'ADX':float(c.adx),'RSI':float(c.rsi),'ATR':float(c.atr),'بالای EMA50':bool(c.close>c.ema50)})
    return ai_call(chat_id,'market',{'نوع':'گزارش کلی بازار','تایم‌فریم':TF_DISPLAY.get(s['timeframe'],s['timeframe']),'داده':rows,'استراتژی فعال':s['active_strategy'],'حداکثر پوزیشن':s['max_open_positions'],'ریسک هر معامله':s['risk_per_trade_pct']},force=True)


def ai_performance_report(chat_id):
    s=get_session(chat_id); closed=s['closed_positions']; pnls=[float(p.get('pnl_usdt',0)) for p in closed]; wins=[x for x in pnls if x>0]; losses=[x for x in pnls if x<0]
    payload={'تعداد معاملات':len(closed),'برد':len(wins),'باخت':len(losses),'Win Rate':(len(wins)/len(closed)*100 if closed else 0),'سود ناخالص':sum(wins),'زیان ناخالص':sum(losses),'PnL خالص':sum(pnls),'موجودی فعلی':s.get('paper_balance')}
    return ai_call(chat_id,'performance',{'نوع':'تحلیل عملکرد ربات','داده':payload},force=True)


def ai_position_report(chat_id,pos):
    payload={'نوع':'بررسی یک پوزیشن باز','نماد':pos.get('symbol'),'سمت':pos.get('side'),'ورود':pos.get('entry_price'),'حد ضرر':pos.get('sl'),'حد سود':pos.get('tp'),'مارجین':pos.get('margin'),'اهرم':pos.get('leverage'),'استراتژی':pos.get('strategy'),'امتیاز':pos.get('score'),'دلیل سیگنال':pos.get('signal_reason'),'زمان ورود':pos.get('opened_at')}
    return ai_call(chat_id,'position',payload,force=True)

def ai_chat_market_snapshot(chat_id):
    """آخرین داده بازار را از منبع داده خود ربات برای چت AI آماده می‌کند."""
    s=get_session(chat_id)
    tf='5min' if s.get('timeframe')=='multi' else s.get('timeframe','15min')
    symbols=list(s.get('active_symbols') or [])[:8]
    if not symbols:
        symbols=['BTC','ETH','SOL','BNB']
    rows=[]
    for sym in symbols:
        try:
            d=get_klines(sym,tf,80)
            if d is None or d.empty: continue
            ind=calculate_indicators(d)
            c=ind.iloc[-2] if len(ind)>=2 else ind.iloc[-1]
            close=float(c.close); ema20=float(c.ema20); ema50=float(c.ema50)
            adx=float(c.adx); rsi=float(c.rsi)
            rows.append({
                'نماد':sym,
                'قیمت':round(close,8),
                'وضعیت نسبت به EMA20':'بالای EMA20' if close>ema20 else 'پایین EMA20',
                'وضعیت نسبت به EMA50':'بالای EMA50' if close>ema50 else 'پایین EMA50',
                'قدرت روند':'قوی' if adx>=25 else 'متوسط' if adx>=20 else 'ضعیف',
                'RSI وضعیت':'اشباع خرید' if rsi>=70 else 'اشباع فروش' if rsi<=30 else 'متعادل',
            })
        except Exception as exc:
            logger.debug('AI market snapshot %s failed: %s', sym, exc)
    return {'تایم‌فریم':TF_DISPLAY.get(tf,tf),'نمادها':rows}


def ai_chat_context(chat_id):
    s=get_session(chat_id)
    positions=[]
    for p in s.get('paper_positions',[])[:10]:
        positions.append({
            'نماد':p.get('symbol'),'سمت':p.get('side'),'ورود':p.get('entry_price'),
            'حد ضرر':p.get('sl'),'حد سود':p.get('tp'),'PnL':p.get('pnl_usdt'),
            'استراتژی':p.get('strategy'),'امتیاز':p.get('score')
        })
    return {
        'نوع':'گفت‌وگوی مستقیم با کاربر',
        'وضعیت ربات':'فعال' if s.get('is_bot_active') else 'متوقف',
        'نوع حساب':'واقعی' if s.get('trading_mode')=='REAL' else 'کاغذی',
        'ارائه‌دهنده هوش مصنوعی':ai_provider_status(s),
        'استراتژی':s.get('active_strategy'),
        'تایم‌فریم':TF_DISPLAY.get(s.get('timeframe'),s.get('timeframe')),
        'پوزیشن‌های باز':positions,
        'تعداد پوزیشن‌های باز':len(positions),
        'ریسک هر معامله':s.get('risk_per_trade_pct'),
        'حداکثر پوزیشن':s.get('max_open_positions'),
        'موجودی کاغذی':s.get('paper_balance'),
        'آخرین وضعیت بازار':ai_chat_market_snapshot(chat_id),
    }

def ai_chat_reply(chat_id, user_text):
    s=get_session(chat_id)
    provider=s.get('ai_provider','off')
    if provider=='off':
        return '🤖 هوش مصنوعی خاموش است. ابتدا از «تنظیمات هوش مصنوعی» یک ارائه‌دهنده را فعال کنید.'
    text=(user_text or '').strip()
    if not text:
        return '💬 سؤال یا درخواستت را بنویس.'
    history=s.get('ai_chat_history',[])
    history.append({'نقش':'کاربر','متن':text})
    history=history[-12:]
    payload={
        'نوع':'چت تعاملی و پاسخ به سؤال کاربر',
        'دستور مهم':'فقط پاسخ و توضیح بده؛ هیچ معامله، تنظیمات، ریسک یا پارامتری را اجرا یا تغییر نده.',
        'درخواست فعلی':text,
        'زمینه ربات':ai_chat_context(chat_id),
        'گفت‌وگوی اخیر':history,
    }
    raw,err=(ai_call_gemini(payload) if provider=='gemini' else ai_call_openai(payload))
    if err:
        return err
    reply=(raw or '').strip()
    if not reply:
        return '❌ هوش مصنوعی پاسخی تولید نکرد.'
    history.append({'نقش':'هوش مصنوعی','متن':reply})
    s['ai_chat_history']=history[-12:]
    save_session(chat_id)
    return '🤖 *پاسخ هوش مصنوعی*\n\n'+reply

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


def expected_trade_metrics(trade):
    """TP/SL gross outcome from the actual position amount; fees/funding excluded."""
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

def expected_trade_pnl(trade):
    """Backward-compatible wrapper."""
    m=expected_trade_metrics(trade)
    return m['tp_pnl'],m['sl_pnl']

def historical_expectancy_r(chat_id, min_samples=10):
    """Historical average R from closed trades; None until enough valid samples exist."""
    s=get_session(chat_id); vals=[]
    for p in s.get('closed_positions',[]):
        try:
            risk=float(p.get('risk_usdt') or 0)
            pnl=float(p.get('pnl_usdt') or 0)
            if risk>0 and math.isfinite(risk) and math.isfinite(pnl):
                vals.append(pnl/risk)
        except Exception:
            continue
    if len(vals)<min_samples: return None, len(vals)
    return sum(vals)/len(vals), len(vals)


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
    direction='LONG' if long_side else 'SHORT'
    mode='REAL' if p.get('is_real') else 'PAPER'

    tp_dist_pct=abs(tp-entry)/entry*100 if entry else 0
    sl_dist_pct=abs(sl-entry)/entry*100 if entry else 0

    lines=[
        f'📊 *مدیریت معامله* — `{p["symbol"]}`',
        '',
        f'📌 وضعیت: `{"🟢 LONG" if long_side else "🔴 SHORT"}` | `{mode}`',
        f'💰 ورود: `{fmt(entry)}`',
        f'📍 قیمت فعلی: `{fmt(price)}`',
        f'🎯 حد سود: `{fmt(tp)}`',
        f'🛑 حد ضرر: `{fmt(sl)}`',
        f'📦 حجم: `{amount:.6f}`',
        '',
        f'💵 سود/زیان فعلی: `{pnl:+.2f} USDT`',
        f'🟢 *پاداش در صورت فعال شدن TP:* `+{metrics["reward"]:.2f} USDT`',
        f'🔴 *ریسک در صورت فعال شدن SL:* `-{metrics["risk"]:.2f} USDT`',
        f'⚖️ *نسبت پاداش به ریسک:* `{metrics["rr"]:.2f}R`',
        '',
        f'📏 فاصله تا TP: `{tp_dist_pct:.2f}%`',
        f'📏 فاصله تا SL: `{sl_dist_pct:.2f}%`',
    ]
    if not metrics['valid']:
        lines += ['', '⚠️ *هشدار:* ورود، TP، SL و جهت معامله با هم سازگار نیستند.']
    lines += ['', 'ℹ️ اعداد TP/SL ناخالص‌اند و قبل از کارمزد و Funding محاسبه شده‌اند.']
    return '\n'.join(lines)



def _fa_num(x, digits=2):
    try:
        return f"{float(x):,.{digits}f}"
    except Exception:
        return "—"

def _closed_trades(s):
    return [t for t in s.get('trade_history', []) if t.get('closed_at')]

def _performance_dashboard(chat_id):
    """Professional Persian performance dashboard using the bot's existing trade history."""
    s = get_session(chat_id)
    trades = _closed_trades(s)

    wins = [t for t in trades if float(t.get('pnl', 0) or 0) > 0]
    losses = [t for t in trades if float(t.get('pnl', 0) or 0) < 0]
    breakeven = [t for t in trades if abs(float(t.get('pnl', 0) or 0)) < 1e-9]

    buys = [t for t in trades if side_long(t.get('side',''))]
    sells = [t for t in trades if not side_long(t.get('side',''))]

    tp_count = sum(1 for t in trades if str(t.get('exit_reason','')).lower() in ('tp','take_profit','target'))
    sl_count = sum(1 for t in trades if str(t.get('exit_reason','')).lower() in ('sl','stop_loss','stop'))
    manual_count = sum(1 for t in trades if str(t.get('exit_reason','')).lower() in ('manual','user','manual_close'))

    net = sum(float(t.get('pnl', 0) or 0) for t in trades)
    gross_profit = sum(max(float(t.get('pnl', 0) or 0), 0) for t in trades)
    gross_loss = abs(sum(min(float(t.get('pnl', 0) or 0), 0) for t in trades))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0)

    avg = net / len(trades) if trades else 0
    avg_win = sum(float(t.get('pnl',0) or 0) for t in wins) / len(wins) if wins else 0
    avg_loss = sum(float(t.get('pnl',0) or 0) for t in losses) / len(losses) if losses else 0
    best = max((float(t.get('pnl',0) or 0) for t in trades), default=0)
    worst = min((float(t.get('pnl',0) or 0) for t in trades), default=0)

    # Equity/drawdown from closed-trade sequence. This is strategy/account history,
    # not an assertion about exchange wallet equity.
    starting = float(s.get('paper_balance', 0) or 0)
    equity = starting
    peak = equity
    max_dd = 0.0
    for t in sorted(trades, key=lambda x: x.get('closed_at', x.get('opened_at', 0))):
        equity += float(t.get('pnl',0) or 0)
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak-equity)/peak*100)

    open_positions = s.get('paper_positions', [])
    open_pnl = sum(float(p.get('unrealized_pnl', p.get('pnl', 0)) or 0) for p in open_positions)
    margin_open = sum(float(p.get('margin', 0) or 0) for p in open_positions)

    # Today
    day_key = time.strftime('%Y-%m-%d')
    today = [t for t in trades if time.strftime('%Y-%m-%d', time.localtime(float(t.get('closed_at',0) or 0))) == day_key]
    today_net = sum(float(t.get('pnl',0) or 0) for t in today)
    today_wins = sum(1 for t in today if float(t.get('pnl',0) or 0) > 0)

    win_rate = (len(wins)/len(trades)*100) if trades else 0

    # By symbol
    by_symbol = {}
    for t in trades:
        sym = t.get('symbol','?')
        by_symbol.setdefault(sym, {'n':0,'pnl':0.0,'wins':0})
        by_symbol[sym]['n'] += 1
        by_symbol[sym]['pnl'] += float(t.get('pnl',0) or 0)
        by_symbol[sym]['wins'] += int(float(t.get('pnl',0) or 0) > 0)

    top_symbols = sorted(by_symbol.items(), key=lambda kv: kv[1]['pnl'], reverse=True)[:5]
    worst_symbols = sorted(by_symbol.items(), key=lambda kv: kv[1]['pnl'])[:5]

    # By strategy
    by_strategy = {}
    for t in trades:
        name = t.get('strategy') or t.get('strategy_name') or 'نامشخص'
        by_strategy.setdefault(name, {'n':0,'pnl':0.0,'wins':0})
        by_strategy[name]['n'] += 1
        by_strategy[name]['pnl'] += float(t.get('pnl',0) or 0)
        by_strategy[name]['wins'] += int(float(t.get('pnl',0) or 0) > 0)

    lines = []
    lines.append("📊 *داشبورد حرفه‌ای عملکرد*")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"💼 حساب: {'واقعی' if s.get('real_mode') else 'کاغذی'}")
    lines.append(f"🤖 وضعیت ربات: {'🟢 فعال' if s.get('is_bot_active') else '🔴 متوقف'}")
    lines.append(f"💰 موجودی پایه: `{_fa_num(starting)} USDT`")
    lines.append(f"📌 پوزیشن باز: `{len(open_positions)}` | مارجین درگیر: `{_fa_num(margin_open)} USDT`")
    lines.append("")
    lines.append("📈 *خلاصه معاملات*")
    lines.append(f"• کل معاملات بسته‌شده: `{len(trades)}`")
    lines.append(f"• 🟢 خرید: `{len(buys)}`   🔴 فروش: `{len(sells)}`")
    lines.append(f"• ✅ موفق: `{len(wins)}`   ❌ ناموفق: `{len(losses)}`   ➖ سر‌به‌سر: `{len(breakeven)}`")
    lines.append(f"• 🎯 حد سود: `{tp_count}`   🛑 حد ضرر: `{sl_count}`   ✋ دستی: `{manual_count}`")
    lines.append(f"• 🎯 نرخ موفقیت: `{win_rate:.1f}%`")
    lines.append("")
    lines.append("💰 *سود و زیان*")
    lines.append(f"• سود ناخالص: `+{_fa_num(gross_profit)} USDT`")
    lines.append(f"• زیان ناخالص: `-{_fa_num(gross_loss)} USDT`")
    pnl_icon = "🟢" if net > 0 else ("🔴" if net < 0 else "🟡")
    lines.append(f"• {pnl_icon} سود/زیان خالص: `{net:+,.2f} USDT`")
    lines.append(f"• میانگین هر معامله: `{avg:+,.2f} USDT`")
    lines.append(f"• میانگین موفق: `+{avg_win:,.2f} USDT`")
    lines.append(f"• میانگین ناموفق: `{avg_loss:+,.2f} USDT`")
    lines.append(f"• بهترین معامله: `+{best:,.2f} USDT`")
    lines.append(f"• بدترین معامله: `{worst:+,.2f} USDT`")
    lines.append(f"• ضریب سودآوری: `{profit_factor:.2f}`" if profit_factor != float('inf') else "• ضریب سودآوری: `∞`")
    lines.append(f"• بیشترین افت سرمایه: `{max_dd:.2f}%`")
    lines.append("")
    lines.append("📅 *عملکرد امروز*")
    lines.append(f"• معاملات: `{len(today)}` | موفق: `{today_wins}`")
    lines.append(f"• سود/زیان امروز: `{today_net:+,.2f} USDT`")
    lines.append("")
    lines.append("🏆 *بهترین نمادها*")
    if top_symbols:
        for sym, d in top_symbols:
            lines.append(f"• `{sym}` — {d['n']} معامله | {d['wins']}/{d['n']} موفق | `{d['pnl']:+,.2f} USDT`")
    else:
        lines.append("• هنوز داده‌ای ثبت نشده است.")
    lines.append("")
    lines.append("⚠️ *ضعیف‌ترین نمادها*")
    if worst_symbols:
        for sym, d in worst_symbols:
            lines.append(f"• `{sym}` — {d['n']} معامله | {d['wins']}/{d['n']} موفق | `{d['pnl']:+,.2f} USDT`")
    else:
        lines.append("• هنوز داده‌ای ثبت نشده است.")
    lines.append("")
    lines.append("🧠 *نکته*")
    lines.append("این گزارش بر اساس تاریخچه ثبت‌شده در ربات است؛ سود/زیان شناور پوزیشن‌های باز جداگانه نمایش داده می‌شود و جایگزین موجودی قطعی صرافی نیست.")

    # Keep existing report buttons if available.
    try:
        kb = report_keyboard(chat_id)
    except Exception:
        kb = None
    send_message(chat_id, "\n".join(lines), kb, parse_mode='Markdown')


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

        metrics=expected_trade_metrics(trade)
        warning='' if metrics['valid'] else '\n⚠️ بررسی جهت TP/SL: مقادیر با جهت معامله سازگار نیستند.'
        hist_r, hist_n = historical_expectancy_r(chat_id)
        quality_line=''
        if trade.get('quality_score') is not None:
            quality_line=f"\n• امتیاز کیفیت معامله: `{trade.get('quality_score')}/100` — {trade.get('quality_label','')}"
        if hist_r is not None:
            quality_line+=f"\n• امیدریاضی تاریخی: `{hist_r:+.2f}R` بر اساس `{hist_n}` معامله"
        send_photo(
            chat_id, b.getvalue(),
            f"📊 *معامله جدید [{mode}]*\n"
            f"• `{symbol}` {trade['side']}\n"
            f"• ورود: `{fmt(entry)}`\n"
            f"• مارجین: `${trade['margin']:.2f}` | `{trade['leverage']}X`\n"
            f"• حد سود: `{fmt(tp)}` → 🟢 `+{metrics['reward']:.2f} USDT`\n"
            f"• حد ضرر: `{fmt(sl)}` → 🔴 `-{metrics['risk']:.2f} USDT`\n"
            f"• نسبت پاداش به ریسک: `{metrics['rr']:.2f}R`\n"
            f"{quality_line}"
            f"{warning}\n\n"
            f"ℹ️ سود/زیان بالا قبل از کارمزد و Funding است.",
            trade_action_keyboard(symbol)
        )
    except Exception:
        logger.exception('chart error')


def _execute_trade_unlocked(chat_id,symbol,side,signal_price,sl,tp,reason=''):
    s=get_session(chat_id)
    logger.info('ENTRY_DIAG chat=%s symbol=%s stage=entry_start side=%s mode=%s', chat_id, symbol, side, s.get('trading_mode'))
    if not s['is_bot_active'] or s['daily_stopped'] or not risk_guard(chat_id):
        logger.info('ENTRY_DIAG chat=%s symbol=%s stage=entry_blocked reason=bot_inactive_or_daily_risk', chat_id, symbol)
        return False
    now=time.time(); cd=float(s['cooldowns'].get(symbol,0))
    if now<cd:
        logger.info('ENTRY_DIAG chat=%s symbol=%s stage=entry_blocked reason=cooldown remaining=%.1fs', chat_id, symbol, cd-now)
        return False
    s['cooldowns'].pop(symbol,None)
    if s['filters'].get('no_short_filter') and 'SELL' in side:
        logger.info('ENTRY_DIAG chat=%s symbol=%s stage=entry_blocked reason=no_short_filter', chat_id, symbol)
        return False
    if s['filters'].get('no_buy_filter') and 'BUY' in side:
        logger.info('ENTRY_DIAG chat=%s symbol=%s stage=entry_blocked reason=no_buy_filter', chat_id, symbol)
        return False
    if s['max_open_positions']>0 and len(s['paper_positions'])>=s['max_open_positions']:
        logger.info('ENTRY_DIAG chat=%s symbol=%s stage=entry_blocked reason=max_open_positions open=%s max=%s', chat_id, symbol, len(s['paper_positions']), s['max_open_positions'])
        return False
    if any(p['symbol']==symbol for p in s['paper_positions']):
        logger.info('ENTRY_DIAG chat=%s symbol=%s stage=entry_blocked reason=symbol_already_open', chat_id, symbol)
        return False

    price=latest_price(symbol) or float(signal_price)
    gap_sl=abs(float(signal_price)-float(sl)); gap_tp=abs(float(tp)-float(signal_price))
    if side_long(side): sl=price-gap_sl; tp=price+gap_tp
    else: sl=price+gap_sl; tp=price-gap_tp
    s['_symbol_tmp']=symbol
    margin, amount_or_reason=safe_size(chat_id,s,price,sl)
    s.pop('_symbol_tmp',None)
    if margin<=0:
        logger.info('ENTRY_DIAG chat=%s symbol=%s stage=entry_blocked reason=sizing margin=%s detail=%s price=%s sl=%s', chat_id, symbol, margin, amount_or_reason, price, sl)
        return False
    logger.info('ENTRY_DIAG chat=%s symbol=%s stage=sizing_ok price=%s sl=%s tp=%s margin=%s leverage=%s', chat_id, symbol, price, sl, tp, margin, s['leverage'])
    leverage=int(s['leverage'])
    risk_dist=abs(float(price)-float(sl))
    risk_usdt=float(margin)*((risk_dist/float(price))*float(leverage)) if price>0 else 0.0
    trade={'symbol':symbol,'side':side,'entry_price':price,'sl':sl,'tp':tp,'margin':margin,'leverage':leverage,'amount':0,'timeframe':s['timeframe'],'is_real':False,'opened_at':time.time(),'signal_reason':reason[:500],'risk_pct':float(s['risk_per_trade_pct']),'risk_usdt':risk_usdt,'trailing_activated':False}

    if s['trading_mode']=='REAL':
        ex=get_exchange(chat_id)
        if not ex:
            logger.info('ENTRY_DIAG chat=%s symbol=%s stage=entry_blocked reason=exchange_unavailable', chat_id, symbol)
            send_message(chat_id,'❌ حساب CoinEx این کاربر پیکربندی نشده یا اتصال برقرار نیست.'); return False
        logger.info('ENTRY_DIAG chat=%s symbol=%s stage=exchange_ready', chat_id, symbol)
        sym=ccxt_symbol(symbol)
        try:
            market=ex.market(sym)
            limits=market.get('limits') or {}
            lev_info=market.get('info') or {}
            max_lev=float(lev_info.get('max_leverage') or market.get('maxLeverage') or leverage)
            if leverage>max_lev: leverage=int(max_lev); trade['leverage']=leverage
            ex.set_margin_mode(MARGIN_MODE,sym,{'leverage':leverage})
            logger.info('ENTRY_DIAG chat=%s symbol=%s stage=leverage_ok leverage=%s', chat_id, symbol, leverage)
        except Exception as lev_exc:
            logger.info('ENTRY_DIAG chat=%s symbol=%s stage=leverage_fallback primary_error=%s', chat_id, symbol, lev_exc)
            try:
                ex.set_leverage(leverage,sym,{'marginMode':MARGIN_MODE})
                logger.info('ENTRY_DIAG chat=%s symbol=%s stage=leverage_ok_fallback leverage=%s', chat_id, symbol, leverage)
            except Exception as exc:
                logger.info('ENTRY_DIAG chat=%s symbol=%s stage=entry_blocked reason=leverage_error error=%s', chat_id, symbol, exc)
                send_message(chat_id,f'❌ تنظیم اهرم `{symbol}` شکست خورد: `{exc}`'); return False
        amount=(margin*leverage)/price
        amount=normalize_amount(chat_id,symbol,amount)
        min_amt=float(((market.get('limits') or {}).get('amount') or {}).get('min') or 0)
        if amount<=0 or (min_amt and amount<min_amt):
            logger.info('ENTRY_DIAG chat=%s symbol=%s stage=entry_blocked reason=invalid_amount amount=%s min_amount=%s', chat_id, symbol, amount, min_amt)
            send_message(chat_id,f'❌ حجم معامله `{symbol}` از حداقل مجاز بازار کمتر است.'); return False
        logger.info('ENTRY_DIAG chat=%s symbol=%s stage=order_submit side=%s amount=%s price=%s', chat_id, symbol, 'buy' if side_long(side) else 'sell', amount, price)
        try:
            order=ex.create_order(sym,'market','buy' if side_long(side) else 'sell',amount)
            logger.info('ENTRY_DIAG chat=%s symbol=%s stage=order_submitted order_id=%s status=%s', chat_id, symbol, order.get('id'), order.get('status'))
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
            logger.info('ENTRY_DIAG chat=%s symbol=%s stage=order_confirm status=%s filled=%s order_id=%s', chat_id, symbol, (confirmed or {}).get('status'), filled, order_id)
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
            trade['risk_usdt']=abs(float(trade['entry_price'])-float(trade['sl']))/max(float(trade['entry_price']),1e-12)*float(trade['margin'])*float(trade['leverage'])
            logger.info('ENTRY_DIAG chat=%s symbol=%s stage=filled entry=%s amount=%s', chat_id, symbol, trade['entry_price'], trade['amount'])
            ok,err=set_protection(chat_id,symbol,trade['sl'],trade['tp'])
            logger.info('ENTRY_DIAG chat=%s symbol=%s stage=protection_result ok=%s detail=%s', chat_id, symbol, ok, err)
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
            logger.exception('ENTRY_DIAG chat=%s symbol=%s stage=order_failed error=%s', chat_id, symbol, exc)
            _halt_real_trading(chat_id,f'وضعیت سفارش REAL {symbol} قابل تأیید نیست: {exc}')
            send_message(chat_id,f'❌ سفارش REAL `{symbol}` به‌طور قطعی تأیید نشد؛ برای جلوگیری از سفارش تکراری، ربات متوقف شد.',parse_mode=None)
            return False
    else:
        if float(s['paper_balance'])-reserved_margin(s)<margin:
            logger.info('ENTRY_DIAG chat=%s symbol=%s stage=entry_blocked reason=paper_balance_insufficient balance=%s reserved=%s margin=%s', chat_id, symbol, s['paper_balance'], reserved_margin(s), margin)
            return False
        trade['amount']=(margin*leverage)/price
        logger.info('ENTRY_DIAG chat=%s symbol=%s stage=paper_entry_opened amount=%s price=%s', chat_id, symbol, trade['amount'], price)
        s['paper_positions'].append(trade); save_session(chat_id)

    m_score=re.search(r'کیفیت (\d+)/100 \(([^)]+)\)', reason or '')
    if m_score:
        trade['quality_score']=int(m_score.group(1)); trade['quality_label']=m_score.group(2)
    m_rr=re.search(r'R:R ([0-9.]+)R', reason or '')
    if m_rr:
        trade['planned_rr']=float(m_rr.group(1))
    if trade.get('is_real'): s['paper_positions'].append(trade); save_session(chat_id)
    logger.info('ENTRY_DIAG chat=%s symbol=%s stage=entry_success side=%s entry=%s sl=%s tp=%s amount=%s mode=%s', chat_id, symbol, side, trade['entry_price'], trade['sl'], trade['tp'], trade['amount'], s['trading_mode'])
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
    if not pos.get('risk_usdt'):
        try: pos['risk_usdt']=abs(float(pos['entry_price'])-float(pos['sl']))/max(float(pos['entry_price']),1e-12)*float(pos['margin'])*float(pos['leverage'])
        except Exception: pos['risk_usdt']=0.0
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
            if rp is None:
                p['pnl_usdt']=0.0
                p['pnl_is_estimate']=True
                p['pnl_note']='PnL نهایی از تاریخچه صرافی قابل تأیید نبود؛ عدد 0 صرفاً موقت است.'
            else:
                p['pnl_usdt']=rp
                p['pnl_is_estimate']=False
            p['close_timestamp']=time.time()
            p['close_reason']='external TP/SL or exchange close'
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


def _entry_diag_result(chat_id, symbol, status, reason='', stage='', signal=None):
    return {
        'chat_id': chat_id,
        'symbol': symbol,
        'status': status,
        'reason': str(reason or '').strip(),
        'stage': stage,
        'signal': signal,
        'ts': time.time(),
    }


def _entry_diag_label(reason):
    """یک دلیل قابل فهم برای گزارش کاربر از متن دلیل استراتژی استخراج می‌کند."""
    r = str(reason or '').strip()
    if not r:
        return 'دلیل مشخصی ثبت نشد'
    # متن‌های طولانی مدل/استراتژی را کوتاه نگه می‌داریم، اما اعداد تشخیصی را حفظ می‌کنیم.
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
    """گزارش خلاصه و کاربرپسند زمانی که مدتی هیچ ورودی ایجاد نشده است."""
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
    else:
        lines.append('\n• هنوز دلیل مشخصی از اسکن‌ها ثبت نشده است.')

    lines += [
        '\n💡 *نتیجه:*',
        'ربات در حال اسکن است و در این بازه شرایط ورود با فیلترهای فعلی کامل نشده است.',
        'این گزارش فقط تشخیصی است و هیچ تنظیمی را تغییر نمی‌دهد.',
    ]
    return '\n'.join(lines)


def _entry_diag_batch_update(chat_id, results):
    """بعد از هر دور اسکن، در صورت طولانی شدن نبود ورود یک گزارش تلگرام بفرست."""
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
            logger.info('ENTRY_DIAG chat=%s stage=telegram_report elapsed=%ss symbols=%s', chat_id, int(elapsed), len(results))
        except Exception as exc:
            logger.warning('ENTRY_DIAG telegram report failed chat=%s error=%s', chat_id, exc)


async def scan_symbol(http,chat_id,symbol):
    s=get_session(chat_id)
    if not s['is_bot_active'] or s['daily_stopped']:
        return _entry_diag_result(chat_id, symbol, 'blocked', 'ربات متوقف است یا محدودیت روزانه فعال است', 'precheck')
    scan_generation=int(s.get('scan_generation',0))
    if time.time() < float(s['cooldowns'].get(symbol,0)):
        logger.info('ENTRY_DIAG chat=%s symbol=%s stage=scan_skipped reason=cooldown', chat_id, symbol)
        return _entry_diag_result(chat_id, symbol, 'blocked', 'نماد در دوره انتظار پس از معامله قبلی است', 'cooldown')
    logger.info('ENTRY_DIAG chat=%s symbol=%s stage=scan_start tf=%s strategy=%s', chat_id, symbol, s['timeframe'], s['active_strategy'])
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
            reason=f'داده کافی برای تایم‌فریم اصلی دریافت نشد ({0 if primary is None else len(primary)} کندل)'
            logger.info('ENTRY_DIAG chat=%s symbol=%s stage=scan_blocked reason=insufficient_primary_data rows=%s', chat_id, symbol, 0 if primary is None else len(primary))
            return _entry_diag_result(chat_id, symbol, 'insufficient_data', reason, 'data')
        primary_tf='5min'; mode='multi'
    else:
        try:
            d=await get_klines_async(http,symbol,tf,160)
        except Exception as exc:
            logger.info('ENTRY_DIAG chat=%s symbol=%s stage=scan_blocked reason=data_error error=%s', chat_id, symbol, exc)
            return _entry_diag_result(chat_id, symbol, 'data_error', f'خطا در دریافت داده بازار: {exc}', 'data')
        if d.empty:
            logger.info('ENTRY_DIAG chat=%s symbol=%s stage=scan_blocked reason=empty_market_data tf=%s', chat_id, symbol, tf)
            return _entry_diag_result(chat_id, symbol, 'data_error', 'داده بازار خالی دریافت شد', 'data')
        primary=calculate_indicators(d); primary_tf=tf; mode='single'
    s=get_session(chat_id)
    if not s['is_bot_active'] or s['daily_stopped'] or int(s.get('scan_generation',0)) != scan_generation:
        logger.info('ENTRY_DIAG chat=%s symbol=%s stage=scan_blocked reason=scan_generation_or_bot_state_changed', chat_id, symbol)
        return _entry_diag_result(chat_id, symbol, 'blocked', 'وضعیت ربات هنگام اسکن تغییر کرد', 'state')
    if not risk_guard(chat_id):
        logger.info('ENTRY_DIAG chat=%s symbol=%s stage=scan_blocked reason=risk_guard', chat_id, symbol)
        return _entry_diag_result(chat_id, symbol, 'risk_blocked', 'محدودیت ریسک اجازه ورود نمی‌دهد', 'risk')
    s=get_session(chat_id)
    if not s['is_bot_active'] or int(s.get('scan_generation',0)) != scan_generation:
        logger.info('ENTRY_DIAG chat=%s symbol=%s stage=scan_blocked reason=state_changed_after_risk_check', chat_id, symbol)
        return _entry_diag_result(chat_id, symbol, 'blocked', 'وضعیت ربات پس از بررسی ریسک تغییر کرد', 'state')
    sig,reason=get_signal_with_reason(primary,md,mode,primary_tf,strat,s['filters'],s['strategy_config'])
    logger.info('ENTRY_DIAG chat=%s symbol=%s stage=signal_result signal=%s reason=%s', chat_id, symbol, sig or 'NONE', str(reason or 'بدون دلیل')[:350])
    if not sig:
        return _entry_diag_result(chat_id, symbol, 'no_signal', reason or 'شرایط ورود کامل نیست', 'signal')
    plan, plan_reason = build_trade_plan(primary, sig, s['strategy_config'], strat)
    if not plan:
        logger.info('ENTRY_DIAG chat=%s symbol=%s stage=entry_blocked reason=trade_plan detail=%s', chat_id, symbol, plan_reason)
        return _entry_diag_result(chat_id, symbol, 'trade_plan_blocked', plan_reason or 'طرح معامله معتبر نشد', 'trade_plan', sig)
    entry=float(plan['entry']); sl=float(plan['sl']); tp=float(plan['tp'])
    full_reason=f"{reason} | {plan_reason}"[:500]
    logger.info('ENTRY_DIAG chat=%s symbol=%s stage=plan_ok signal=%s entry=%s sl=%s tp=%s detail=%s', chat_id, symbol, sig, entry, sl, tp, plan_reason)
    ok=execute_trade(chat_id,symbol,'BUY (Long)' if sig=='BUY' else 'SELL (Short)',entry,sl,tp,full_reason)
    logger.info('ENTRY_DIAG chat=%s symbol=%s stage=execute_result ok=%s', chat_id, symbol, ok)
    if ok:
        return _entry_diag_result(chat_id, symbol, 'entry_opened', full_reason, 'entry', sig)
    return _entry_diag_result(chat_id, symbol, 'execute_blocked', 'سیگنال و طرح معامله ایجاد شد، اما اجرای ورود موفق نشد', 'execute', sig)


def performance(chat_id):
    s=get_session(chat_id)
    closed=list(s.get('closed_positions') or [])
    open_pos=list(s.get('paper_positions') or [])

    def pnl(p):
        try:
            return float(p.get('pnl_usdt', 0) or 0)
        except Exception:
            return 0.0

    def is_buy(p):
        return side_long(p.get('side',''))

    total=len(closed)
    buys=sum(1 for p in closed if is_buy(p))
    sells=total-buys
    wins=sum(1 for p in closed if pnl(p)>0)
    losses=sum(1 for p in closed if pnl(p)<0)
    breakeven=total-wins-losses
    net=sum(pnl(p) for p in closed)
    gross_profit=sum(pnl(p) for p in closed if pnl(p)>0)
    gross_loss=abs(sum(pnl(p) for p in closed if pnl(p)<0))
    win_rate=(wins/total*100) if total else 0.0
    avg_trade=(net/total) if total else 0.0
    avg_win=(gross_profit/wins) if wins else 0.0
    avg_loss=(gross_loss/losses) if losses else 0.0
    r_values=[]
    for p in closed:
        try:
            risk=float(p.get('risk_usdt') or 0); val=float(p.get('pnl_usdt') or 0)
            if risk>0 and math.isfinite(risk) and math.isfinite(val): r_values.append(val/risk)
        except Exception: pass
    expectancy_r=(sum(r_values)/len(r_values)) if r_values else None
    profit_factor=(gross_profit/gross_loss) if gross_loss>0 else (float('inf') if gross_profit>0 else 0.0)
    best=max((pnl(p) for p in closed), default=0.0)
    worst=min((pnl(p) for p in closed), default=0.0)

    # افت سرمایه بر اساس توالی زمانی معاملات بسته‌شده
    start_equity=float(s.get('daily_start_equity') or s.get('paper_balance') or 0.0)
    equity=start_equity
    peak=equity
    max_drawdown=0.0
    ordered=sorted(closed, key=lambda p: float(p.get('close_timestamp', p.get('opened_at', 0)) or 0))
    for p in ordered:
        equity += pnl(p)
        peak=max(peak,equity)
        if peak>0:
            max_drawdown=max(max_drawdown,(peak-equity)/peak*100)

    # موجودی فعلی
    if s.get('trading_mode')=='REAL':
        try:
            balance=float(exchange_balance(chat_id))
            balance_label='موجودی حساب واقعی'
        except Exception:
            balance=float(s.get('paper_balance',0) or 0)
            balance_label='موجودی ثبت‌شده'
    else:
        balance=float(s.get('paper_balance',0) or 0)
        balance_label='موجودی حساب کاغذی'

    open_margin=sum(float(p.get('margin',0) or 0) for p in open_pos)
    open_pnl=sum(float(p.get('last_unrealized_pnl', p.get('pnl_usdt', 0)) or 0) for p in open_pos)
    tp_count=sum(1 for p in closed if str(p.get('close_reason','')).lower() in ('tp','take_profit','take profit','target'))
    sl_count=sum(1 for p in closed if str(p.get('close_reason','')).lower() in ('sl','stop_loss','stop loss','stop'))
    manual_count=sum(1 for p in closed if str(p.get('close_reason','')).lower() in ('manual','close_all','user'))
    other_count=max(0,total-tp_count-sl_count-manual_count)

    today=time.strftime('%Y-%m-%d',time.gmtime())
    today_closed=[p for p in closed if time.strftime('%Y-%m-%d',time.gmtime(float(p.get('close_timestamp',0) or 0)))==today]
    today_pnl=sum(pnl(p) for p in today_closed)
    today_wins=sum(1 for p in today_closed if pnl(p)>0)

    if profit_factor==float('inf'):
        pf='بی‌نهایت'
    else:
        pf=f'{profit_factor:.2f}'

    status='🟢 سودده' if net>0 else ('🔴 زیان‌ده' if net<0 else '🟡 خنثی')
    mode='حساب واقعی' if s.get('trading_mode')=='REAL' else 'حساب کاغذی'
    active='🟢 فعال' if s.get('is_bot_active') else '🔴 متوقف'

    return (
        '📊 *گزارش حرفه‌ای عملکرد*\n'
        '━━━━━━━━━━━━━━━━━━━━\n'
        f'💼 نوع حساب: `{mode}`\n'
        f'🤖 وضعیت ربات: `{active}`\n'
        f'💰 {balance_label}: `{balance:,.2f} USDT`\n'
        f'📌 نتیجه کلی: {status}\n\n'
        '📈 *آمار معاملات*\n'
        f'• کل معاملات بسته‌شده: `{total}`\n'
        f'• خرید: `🟢 {buys}`\n'
        f'• فروش: `🔴 {sells}`\n'
        f'• موفق: `🟢 {wins}`\n'
        f'• ناموفق: `🔴 {losses}`\n'
        f'• سر‌به‌سر: `🟡 {breakeven}`\n'
        f'• نرخ موفقیت: `{win_rate:.1f}%`\n\n'
        '🎯 *نحوه بسته‌شدن معاملات*\n'
        f'• حد سود: `{tp_count}`\n'
        f'• حد ضرر: `{sl_count}`\n'
        f'• بستن دستی: `{manual_count}`\n'
        f'• سایر: `{other_count}`\n\n'
        '💵 *سود و زیان*\n'
        f'• سود ناخالص: `+{gross_profit:,.2f} USDT`\n'
        f'• زیان ناخالص: `-{gross_loss:,.2f} USDT`\n'
        f'• سود/زیان خالص: `{net:+,.2f} USDT`\n'
        f'• میانگین هر معامله: `{avg_trade:+,.2f} USDT`\n'
        f'• میانگین معامله موفق: `+{avg_win:,.2f} USDT`\n'
        f'• میانگین معامله ناموفق: `-{avg_loss:,.2f} USDT`\n'
        f'• بهترین معامله: `+{best:,.2f} USDT`\n'
        f'• بدترین معامله: `{worst:+,.2f} USDT`\n'
        f'• ضریب سودآوری: `{pf}`\n'
        + (f'• امیدریاضی تاریخی: `{expectancy_r:+.2f}R`\n' if expectancy_r is not None else '• امیدریاضی تاریخی: `داده کافی نیست`\n')
        + f'• بیشترین افت سرمایه: `{max_drawdown:.2f}%`\n\n'
        '🔄 *پوزیشن‌های باز*\n'
        f'• تعداد پوزیشن: `{len(open_pos)}`\n'
        f'• مارجین درگیر: `{open_margin:,.2f} USDT`\n'
        f'• سود/زیان شناور ثبت‌شده: `{open_pnl:+,.2f} USDT`\n\n'
        '📅 *عملکرد امروز*\n'
        f'• معاملات بسته‌شده: `{len(today_closed)}`\n'
        f'• معاملات موفق: `{today_wins}`\n'
        f'• سود/زیان امروز: `{today_pnl:+,.2f} USDT`\n\n'
        '━━━━━━━━━━━━━━━━━━━━\n'
        'ℹ️ سود و زیان بر اساس معاملات ثبت‌شده ربات است؛ در حساب واقعی، عدد نهایی صرافی پس از کارمزد و تسویه ملاک نهایی است.'
    )


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
    # گزارش عمومی ساده و قابل فهم؛ اعداد فنی برای موتور تصمیم‌گیری باقی می‌مانند.
    s=get_session(chat_id)
    tf='5min' if s['timeframe']=='multi' else s['timeframe']
    d=get_klines(symbol,tf,160)
    if d.empty:
        return f'❌ داده کافی برای تحلیل `{symbol}` پیدا نشد.'
    d=calculate_indicators(d); c=d.iloc[-2]
    a,r1=strategy_trend_following(d,tf,s['filters'],s['strategy_config'])
    b,r2=strategy_breakout(d,s['filters'],s['strategy_config'])
    m,r3=strategy_mean_reversion(d,s['filters'],s['strategy_config'])

    adx=float(c.adx or 0)
    rsi=float(c.rsi or 50)
    close=float(c.close)
    ema20=float(c.ema20)
    ema50=float(c.ema50)

    # وضعیت کلی بازار به زبان ساده
    if adx < 20:
        market_state='🟡 آرام و بدون روند مشخص'
        market_desc='بازار فعلاً قدرت و جهت مشخصی ندارد و احتمال ورود کم‌کیفیت بیشتر است.'
        risk='متوسط'
    elif adx < 25:
        market_state='🟠 در حال شکل‌گیری روند'
        market_desc='نشانه‌هایی از شکل‌گیری حرکت وجود دارد، اما هنوز قدرت روند کافی نیست.'
        risk='متوسط'
    else:
        market_state='🟢 دارای روند مشخص'
        market_desc='بازار حرکت مشخص‌تری دارد و در صورت تأیید سایر شرایط، فرصت‌های معاملاتی بهتری ممکن است شکل بگیرد.'
        risk='متوسط' if adx < 35 else 'بالا'

    if close > ema20 and close > ema50:
        direction='📈 متمایل به صعود'
        direction_desc='قیمت بالاتر از میانگین‌های مهم قرار دارد.'
    elif close < ema20 and close < ema50:
        direction='📉 متمایل به نزول'
        direction_desc='قیمت پایین‌تر از میانگین‌های مهم قرار دارد.'
    else:
        direction='↔️ خنثی'
        direction_desc='قیمت بین محدوده میانگین‌های مهم قرار گرفته و جهت قطعی ندارد.'

    active_count=sum(bool(x) for x in (a,b,m))
    if active_count:
        decision='🟢 شرایط اولیه برای بررسی معامله وجود دارد'
        if a:
            opportunity='روند'
        elif b:
            opportunity='شکست'
        else:
            opportunity='بازگشت به میانگین'
    else:
        decision='⛔ فعلاً معامله نمی‌کنیم'
        opportunity='هیچ‌کدام'
    if not active_count:
        decision_reason='شرایط لازم برای ورود هنوز به اندازه کافی قوی نیست؛ بهتر است منتظر تأیید بیشتر بمانیم.'
    else:
        decision_reason='یکی از الگوهای استراتژی فعال شده، اما قبل از ورود نهایی همه فیلترهای ریسک بررسی می‌شوند.'

    # جزئیات فنی در انتهای گزارش و به صورت اختیاری/کم‌اهمیت نمایش داده می‌شوند.
    technical=(f"\n\n⚙️ *جزئیات فنی*\n"
               f"قدرت روند: `{adx:.1f}` | وضعیت مومنتوم: `{rsi:.1f}` | "
               f"نوسان قیمت: `{fmt(float(c.atr))}`")

    return (
        f"🔍 *تحلیل {symbol}*\n\n"
        f"*وضعیت فعلی:* {market_state}\n"
        f"{market_desc}\n\n"
        f"*جهت بازار:* {direction}\n"
        f"{direction_desc}\n\n"
        f"*روند:* {'فعال' if a else 'ضعیف/تأییدنشده'}\n"
        f"*احتمال شکست:* {'مناسب برای بررسی' if b else 'پایین'}\n"
        f"*بازگشت به میانگین:* {'قابل بررسی' if m else 'خنثی'}\n\n"
        f"🎯 *تصمیم ربات:* {decision}\n"
        f"دلیل: {decision_reason}\n"
        f"ریسک فعلی: *{risk}*\n"
        f"فرصت احتمالی: *{opportunity}*"
        + technical
    )


def menu(chat_id,message_id=None):
    s=get_session(chat_id); bal=exchange_balance(chat_id) if s['trading_mode']=='REAL' else s['paper_balance']; maxp=s['max_open_positions'] if s['max_open_positions']>0 else '∞'
    diag = "🟢 فعال" if s.get('entry_diag_enabled', True) else "🔴 خاموش"
    text=f"📊 *پنل اصلی ربات*\n\n🟢 اسکن: `{'فعال' if s['is_bot_active'] else 'متوقف'}`  |  🤖 هوش مصنوعی: `{ai_provider_status(s)}`\n💳 حساب: `{'واقعی' if s['trading_mode']=='REAL' else 'کاغذی'}`  |  ⏱ تایم‌فریم: `{TF_DISPLAY.get(s['timeframe'],s['timeframe'])}`\n📈 استراتژی: `{'روندی' if s['active_strategy']=='trend' else 'شکست' if s['active_strategy']=='breakout' else 'بازگشت به میانگین' if s['active_strategy']=='mean_reversion' else 'چندزمانه'}`\n💰 موجودی: `{bal:.2f} USDT`  |  ⚙️ مارجین: `{s['trade_amount_usdt']:.0f} USDT`\n📌 پوزیشن‌های باز: `{maxp}`  |  🔍 لاگ ورود: `{diag}`\n🛡 ریسک هر معامله: `{s['risk_per_trade_pct']:.2f}%`  |  حد ضرر روزانه: `{s['daily_loss_limit_pct']:.2f}%`\n\nاز منوی زیر بخش موردنظر را انتخاب کن:"
    send_message(chat_id,text,get_main_menu_keyboard(s['is_bot_active'], s.get('entry_diag_enabled', True)),message_id)


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
    sync_bottom_keyboard(chat_id, "🟢 اسکن فعال شد.\n🔒 تنظیمات حساس تا توقف اسکن قفل هستند.")


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



def runtime_audit(chat_id):
    """Quick self-check of state invariants; does not place/cancel any order."""
    s=get_session(chat_id)
    issues=[]
    # Position uniqueness and basic numeric validity.
    symbols=[p.get('symbol') for p in s.get('paper_positions',[])]
    if len(symbols)!=len(set(symbols)):
        issues.append('پوزیشن تکراری برای یک نماد وجود دارد')
    for p in s.get('paper_positions',[]):
        try:
            e=float(p.get('entry_price') or 0); sl=float(p.get('sl') or 0); tp=float(p.get('tp') or 0); a=float(p.get('amount') or 0)
            if min(e,sl,tp,a)<=0: issues.append(f'اعداد نامعتبر در {p.get("symbol","?")}')
            m=expected_trade_metrics(p)
            if not m['valid']: issues.append(f'TP/SL ناسازگار در {p.get("symbol","?")}')
        except Exception:
            issues.append(f'ساختار پوزیشن خراب در {p.get("symbol","?")}')
    if s.get('is_bot_active') and s.get('daily_stopped'):
        issues.append('ربات همزمان ACTIVE و DAILY_STOPPED است')
    if s.get('max_open_positions',0)>0 and len(s.get('paper_positions',[]))>int(s['max_open_positions']):
        issues.append('تعداد پوزیشن‌ها از سقف تنظیم‌شده بیشتر است')
    if s.get('trading_mode')=='REAL' and s.get('real_reconciliation_required') and s.get('is_bot_active'):
        issues.append('REAL در وضعیت نیازمند تطبیق ولی اسکن فعال است')
    status='✅ بدون مغایرت ساختاری مهم' if not issues else '⚠️ مغایرت پیدا شد'
    lines=[
        '🧪 *ممیزی سریع وضعیت ربات*',
        '',
        f'🤖 اسکن: `{"فعال" if s.get("is_bot_active") else "متوقف"}`',
        f'💼 حساب: `{"REAL" if s.get("trading_mode")=="REAL" else "PAPER"}`',
        f'📦 پوزیشن باز: `{len(s.get("paper_positions",[]))}`',
        f'🔢 نسل اسکن: `{s.get("scan_generation",0)}`',
        f'🔐 تطبیق REAL: `{"لازم است" if s.get("real_reconciliation_required") else "OK"}`',
        '',
        status
    ]
    if issues:
        lines.append('')
        lines.append('• ' + '\n• '.join(issues[:10]))
    return '\n'.join(lines)


def learning_text(topic):
    texts={
        'adx':"📈 *ADX چیست؟*\n\nADX برای سنجش *قدرت روند* است، نه جهت آن.\n\nربات از آن کمک می‌گیرد تشخیص دهد بازار رونددار است یا خنثی.\n\nلازم نیست عدد ADX را تنظیم کنید؛ در حالت ساده ربات خودش آن را مدیریت می‌کند.",
        'atr':"🌪 *ATR چیست؟*\n\nATR میزان *نوسان معمول قیمت* را اندازه می‌گیرد.\n\nربات از آن برای هماهنگ‌کردن حد ضرر و حد سود با نوسان بازار استفاده می‌کند.",
        'rsi':"📊 *RSI چیست؟*\n\nRSI به ربات کمک می‌کند قدرت و وضعیت حرکت قیمت را بسنجد.\n\nRSI به‌تنهایی سیگنال خرید یا فروش نیست و کنار عوامل دیگر بررسی می‌شود.",
        'rr':"⚖️ *R:R چیست؟*\n\nR:R یعنی پاداش احتمالی نسبت به ریسک احتمالی.\n\nمثلاً 2R یعنی پاداش هدف تقریباً دو برابر ریسک حد ضرر است.",
        'why':"🧠 *چرا ربات این شاخص‌ها را می‌بیند؟*\n\nهیچ شاخصی به‌تنهایی آینده را پیش‌بینی نمی‌کند. ربات قدرت روند، نوسان، حرکت قیمت، حجم، ساختار بازار و نسبت سود به ریسک را کنار هم بررسی می‌کند تا کاربر مجبور نباشد ده‌ها عدد فنی را دستی تنظیم کند."
    }
    return texts.get(topic,texts['why'])

def apply_user_profile(s, profile):
    presets={'conservative':(78.0,1.60,0.35,24.0,'محافظه‌کارانه'),'balanced':(68.0,1.30,0.50,20.0,'متعادل'),'opportunity':(62.0,1.25,0.50,18.0,'فرصت‌های بیشتر')}
    score,rr,risk,adx,label=presets[profile]
    s['strategy_config']['min_trade_score']=score; s['strategy_config']['min_rr']=rr; s['strategy_config']['min_adx']=adx; s['risk_per_trade_pct']=risk; s['user_experience']='simple'
    return label,score,rr,risk

def process_command(cmd,chat_id,message_id=None):

    if cmd in ('performance','report','📈 گزارش عملکرد کلی'):
        _performance_dashboard(chat_id)
        return
    if cmd in ('/audit','audit','🧪 ممیزی ربات'):
        send_message(chat_id, runtime_audit(chat_id), get_bottom_menu_keyboard(get_session(chat_id)['is_bot_active']))
        return
    s=get_session(chat_id); c=(cmd or '').strip(); cl=c.lower()
    if cl in ('/learn_menu','learn','🎓 آموزش مفاهیم'):
        edit_page(chat_id,'🎓 *آموزش ساده مفاهیم ربات*\n\nلازم نیست ADX، ATR یا RSI را بلد باشید. از اینجا توضیح ساده هرکدام را ببینید.',get_learn_menu_keyboard(),message_id); return
    if cl in ('/learn_adx','/learn_atr','/learn_rsi','/learn_rr','/learn_why'):
        edit_page(chat_id,learning_text(cl.replace('/learn_','')),get_learn_menu_keyboard(),message_id); return
    if cl=='/profile_advanced':
        s['user_experience']='advanced'; save_session(chat_id); edit_page(chat_id,'🔵 *حالت حرفه‌ای فعال شد.*\nپارامترهای فنی نمایش داده می‌شوند.',get_params_menu_keyboard(s),message_id); return
    if cl=='/profile_simple':
        s['user_experience']='simple'; save_session(chat_id); edit_page(chat_id,'🟢 *حالت ساده فعال شد.*\nپارامترهای فنی پشت صحنه مدیریت می‌شوند.',get_params_menu_keyboard(s),message_id); return
    if cl in ('/profile_conservative','/profile_balanced','/profile_opportunity'):
        profile={'/profile_conservative':'conservative','/profile_balanced':'balanced','/profile_opportunity':'opportunity'}[cl]
        label,score,rr,risk=apply_user_profile(s,profile); save_session(chat_id)
        edit_page(chat_id,f'🟢 *پروفایل {label} فعال شد.*\n\n🎯 حداقل کیفیت: `{score:.0f}/100`\n⚖️ حداقل سود به ضرر: `{rr:.2f}R`\n🛡️ ریسک هر معامله: `{risk:.2f}%`\n\nجزئیات فنی مثل ADX و ATR پشت صحنه مدیریت می‌شوند.',get_params_menu_keyboard(s),message_id); return
    sensitive_prefixes=('/ai_provider_','/mode_paper','/mode_real','/set_bal_','/set_margin_','/set_lev_','/set_max_','/set_tf_','/set_strat_','/profile_','/learn_','/toggle_','/adx_','/sl_','/tp_','/add_symbol_','/remove_symbol_','/watchlist_')
    if s['is_bot_active'] and (
        cl.startswith(sensitive_prefixes)
        or any(k in c for k in (
            'تنظیمات فیلترها', 'فیلترها',
            'تنظیم پارامترها', 'پارامترها',
            'استراتژی', 'واچ‌لیست', 'واچ لیست',
            '🔒'
        ))
    ):
        send_message(chat_id,'⚠️ اسکن در حال انجام است. برای تغییر تنظیمات ابتدا «توقف اسکن» را بزنید.', parse_mode=None)
        return
    if cl=='/start':
        if s.get('is_bot_active'):
            stop_scan(chat_id, 'start-reset')
        s['user_state']=None
        save_session(chat_id)
        send_message(chat_id,'🤖 *ربات معامله‌گر*\n\nحالت حساب را انتخاب کنید.',get_start_keyboard())
        sync_bottom_keyboard(chat_id, "🔴 اسکن متوقف است.\n⚙️ تنظیمات آماده تغییر هستند.")
        return
    if cl in ('/menu','☰ منو','🏠 منوی اصلی'): s['user_state']=None; menu(chat_id,message_id); return
    if cl in ('/toggle_bottom_menu','☰ منوی سریع','⬆️ منوی سریع'):
        s['bottom_menu_open']=True; save_session(chat_id); sync_bottom_keyboard(chat_id, '☰ منوی سریع باز شد.'); return
    if cl in ('/close_bottom_menu','⬇️ بستن منوی سریع'):
        s['bottom_menu_open']=False; save_session(chat_id); sync_bottom_keyboard(chat_id, '☰ منوی سریع بسته شد.'); return
    if cl in ('/entry_diag', '🔍 لاگ تشخیصی ورود'):
        enabled = s.get('entry_diag_enabled', True)
        text = (
            "🔍 *لاگ تشخیصی ورود*\n\n"
            f"وضعیت گزارش داخل تلگرام: {'🟢 فعال' if enabled else '🔴 خاموش'}\n\n"
            "این گزینه گزارش‌های تشخیصیِ عدم ورود را بعد از چند دقیقه بدون پوزیشن ارسال می‌کند.\n"
            "گزارش توضیح می‌دهد ربات چه چیزهایی را بررسی کرده و مهم‌ترین دلایل وارد نشدن چه بوده‌اند.\n\n"
            "📌 لاگ فنی `ENTRY_DIAG` روی سرور مستقل از این گزینه است و برای مراحل ورود ثبت می‌شود."
        )
        edit_page(chat_id, text, get_entry_diag_keyboard(enabled), message_id)
        return
    if cl == '/toggle_entry_diag':
        s['entry_diag_enabled'] = not s.get('entry_diag_enabled', True)
        save_session(chat_id)
        enabled = s['entry_diag_enabled']
        text = (
            "🔍 *لاگ تشخیصی ورود*\n\n"
            f"وضعیت گزارش داخل تلگرام: {'🟢 فعال' if enabled else '🔴 خاموش'}\n\n"
            "از این به بعد گزارش عدم ورود " + ("ارسال می‌شود." if enabled else "ارسال نمی‌شود.") +
            "\n\n📌 لاگ فنی `ENTRY_DIAG` روی سرور همیشه ثبت می‌شود."
        )
        edit_page(chat_id, text, get_entry_diag_keyboard(enabled), message_id)
        return
    if cl == '/entry_diag_log':
        state = ENTRY_DIAG_STATE.get(chat_id, {})
        results = list(state.get('window_results') or [])[-8:]
        if not results:
            msg = "📋 هنوز تشخیص ورودی در این نشست ثبت نشده است.\n\nاسکن را روشن نگه دار تا ربات بررسی‌ها را ثبت کند."
        else:
            lines = ["📋 *آخرین تشخیص‌های ورود*"]
            for r in results:
                sym = r.get('symbol','?')
                status = r.get('status','?')
                reason = r.get('reason') or r.get('detail') or ''
                lines.append(f"• `{sym}` — `{status}`" + (f" — {reason}" if reason else ""))
            msg = "\n".join(lines)
        send_message(chat_id, msg, get_entry_diag_keyboard(s.get('entry_diag_enabled', True)), parse_mode='Markdown')
        return
    if cl in ('/ai_settings','🤖 تنظیمات هوش مصنوعی'):
        edit_page(chat_id, ai_settings_text(chat_id), get_ai_settings_keyboard(s), message_id); return
    if cl.startswith('/ai_provider_'):
        provider=cl.replace('/ai_provider_','')
        if provider in ('gemini','openai','off'):
            s['ai_provider']=provider; save_session(chat_id); edit_page(chat_id, ai_settings_text(chat_id), get_ai_settings_keyboard(s), message_id)
        return
    if cl in ('/ai_chat','💬 گفت‌وگو با هوش مصنوعی'):
        s['user_state']='AI_CHAT'; save_session(chat_id)
        send_message(chat_id, '💬 *گفت‌وگو با هوش مصنوعی*\n\nهر سؤالی درباره بازار، وضعیت ربات، پوزیشن‌ها یا تحلیل‌ها داری بنویس.\n\n🔐 این گفتگو فقط برای تحلیل و پاسخ است و خودش هیچ معامله یا تنظیماتی را اجرا نمی‌کند.', get_ai_chat_keyboard(), parse_mode='Markdown')
        return
    if cl=='/ai_chat_clear':
        s['ai_chat_history']=[]; s['user_state']='AI_CHAT'; save_session(chat_id)
        send_message(chat_id,'🗑 گفت‌وگو پاک شد. سؤال جدیدت را بنویس.',get_ai_chat_keyboard(),parse_mode=None)
        return
    if cl in ('/ai_market','🤖 تحلیل هوشمند بازار'):
        send_message(chat_id, ai_market_report(chat_id), parse_mode=None); return
    if cl in ('/ai_performance','🤖 تحلیل هوشمند عملکرد'):
        send_message(chat_id, ai_performance_report(chat_id), parse_mode=None); return
    if cl.startswith('/ai_pos_'):
        sym=cl.replace('/ai_pos_','').upper(); pos=next((p for p in s['paper_positions'] if p.get('symbol','').upper()==sym),None)
        if not pos: send_message(chat_id,'❌ این پوزیشن دیگر باز نیست.'); return
        send_message(chat_id, ai_position_report(chat_id,pos), parse_mode=None); return
    if cl=='/cancel': s['user_state']=None; save_session(chat_id); menu(chat_id, message_id); return
    if cl in ('/stop_scan',) or c in ('🔴 توقف اسکن','توقف اسکن'):
        stop_scan(chat_id, 'manual')
        menu(chat_id,message_id)
        sync_bottom_keyboard(chat_id, "🔴 اسکن متوقف شد.\n⚙️ تنظیمات آماده تغییر هستند.")
        return
    if cl in ('/start_scan',) or c in ('🟢 شروع اسکن','شروع اسکن','روشن کردن اسکن'):
        start_scan(chat_id,message_id)
        return
    # سازگاری با دکمه‌های قدیمی نسخه‌های قبلی
    if cl=='/toggle_active':
        if s['is_bot_active']:
            stop_scan(chat_id, 'manual-toggle')
            menu(chat_id,message_id)
            sync_bottom_keyboard(chat_id, "🔴 اسکن متوقف شد.\n⚙️ تنظیمات آماده تغییر هستند.")
        else:
            start_scan(chat_id,message_id)
        return
    if cl=='/mode_paper':
        if s['paper_positions']: send_message(chat_id,'❌ تا وقتی پوزیشن باز دارید نمی‌توانید به PAPER بروید.'); return
        s['trading_mode']='PAPER'; s['is_bot_active']=False; save_session(chat_id); edit_page(chat_id,'⚙️ موجودی PAPER را انتخاب کنید.',get_balance_keyboard(),message_id); return
    if cl=='/mode_real':
        if s['paper_positions']: send_message(chat_id,'❌ ابتدا تمام پوزیشن‌های فعلی را ببندید.'); return
        if not get_exchange(chat_id): send_message(chat_id,'❌ حساب CoinEx این کاربر در `COINEX_ACCOUNTS_JSON` تنظیم نشده یا اتصال ناموفق است.'); return
        bal=exchange_balance(chat_id)
        if bal<=0: send_message(chat_id,'❌ موجودی USDT معتبر پیدا نشد.'); return
        s['trading_mode']='REAL'; s['is_bot_active']=False; s['daily_start_equity']=bal; s['daily_start_date']=time.strftime('%Y-%m-%d',time.gmtime()); s['daily_stopped']=False; s['real_reconciliation_required']=not reconcile_real(chat_id); save_session(chat_id); edit_page(chat_id,f'🔴 موجودی REAL: `{bal:.2f} USDT`\n\n⚙️ مارجین هر معامله:',get_margin_keyboard(),message_id); return
    if cl.startswith('/set_bal_'):
        v=float(cl.replace('/set_bal_','')); s['paper_balance']=v; s['daily_start_equity']=v; s['daily_start_date']=time.strftime('%Y-%m-%d',time.gmtime()); s['daily_stopped']=False; save_session(chat_id); edit_page(chat_id,'✅ موجودی ثبت شد.\n\n⚙️ مارجین:',get_margin_keyboard(),message_id); return
    if cl.startswith('/set_margin_'): s['trade_amount_usdt']=float(cl.replace('/set_margin_','')); save_session(chat_id); edit_page(chat_id,'⚙️ اهرم:',get_leverage_keyboard(),message_id); return
    if cl.startswith('/set_lev_'): s['leverage']=int(cl.replace('/set_lev_','')); save_session(chat_id); edit_page(chat_id,'⚙️ حداکثر پوزیشن:',get_max_positions_keyboard(),message_id); return
    if cl.startswith('/set_max_'): s['max_open_positions']=int(cl.replace('/set_max_','')); save_session(chat_id); edit_page(chat_id,'⚙️ تایم‌فریم:',get_timeframe_keyboard(),message_id); return
    if cl.startswith('/set_tf_'):
        s['timeframe']={'/set_tf_5m':'5min','/set_tf_15m':'15min','/set_tf_1h':'1hour','/set_tf_4h':'4hour','/set_tf_1d':'1day','/set_tf_multi':'multi'}[cl]; save_session(chat_id); menu(chat_id, message_id); return
    if cl.startswith('/set_strat_'):
        key=cl.replace('/set_strat_','')
        if key in ('dynamic','trend','breakout','mean_reversion','multi'): s['active_strategy']=key; save_session(chat_id); menu(chat_id, message_id)
        return
    if cl=='/market_report':
        send_message(chat_id, '⏳ *در حال تهیه گزارش جامع بازار...*\nداده چندین نماد در حال بررسی است.', get_bottom_menu_keyboard(s['is_bot_active'], s.get('bottom_menu_open', True)))
        send_message(chat_id, market_report(chat_id))
        return
    if cl in ('/strategies_menu',): edit_page(chat_id,'📊 *انتخاب استراتژی*',get_strategies_selection_keyboard(),message_id); return
    if cl in ('/filters_menu',): edit_page(chat_id,'⚙️ *فیلترها*',get_filters_menu_keyboard(s),message_id); return
    if cl in ('/params_menu',): edit_page(chat_id,'🎛️ *پارامترها*',get_params_menu_keyboard(s),message_id); return
    if cl=='/strategy_desc_menu': edit_page(chat_id,'📚 *توضیح استراتژی*',get_strategies_menu_keyboard(),message_id); return
    if cl.startswith('/desc_'):
        tf=cl.replace('/desc_',''); tf={'multi':'multi'}.get(tf,tf); edit_page(chat_id,get_strategy_description(tf,s['strategy_config'],s['filters'],simple=(s.get('user_experience','simple')!='advanced')),get_strategies_menu_keyboard(),message_id); return
    if cl in ('/toggle_vol','/toggle_trail','/toggle_candle','/toggle_short','/toggle_buy'):
        key={'/toggle_vol':'volume_filter','/toggle_trail':'trailing_stop','/toggle_candle':'candlestick_filter','/toggle_short':'no_short_filter','/toggle_buy':'no_buy_filter'}[cl]; s['filters'][key]=not s['filters'].get(key,False); save_session(chat_id); edit_page(chat_id,'⚙️ *فیلترها*',get_filters_menu_keyboard(s),message_id); return
    if cl in ('/adx_up','/adx_down','/sl_up','/sl_down','/tp_up','/tp_down'):
        c=s['strategy_config'];
        if cl=='/adx_up': c['min_adx']=min(50,c['min_adx']+1)
        elif cl=='/adx_down': c['min_adx']=max(10,c['min_adx']-1)
        elif cl=='/sl_up': c['sl_multiplier']=round(c['sl_multiplier']+.2,1)
        elif cl=='/sl_down': c['sl_multiplier']=max(.5,round(c['sl_multiplier']-.2,1))
        elif cl=='/tp_up': c['tp_multiplier']=round(c['tp_multiplier']+.5,1)
        else: c['tp_multiplier']=max(.5,round(c['tp_multiplier']-.5,1))
        save_session(chat_id); edit_page(chat_id,'🎛️ *پارامترها*',get_params_menu_keyboard(s),message_id); return
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
        ok,msg=reset_stats(chat_id); send_message(chat_id,msg,get_performance_keyboard() if ok else get_bottom_menu_keyboard(s['is_bot_active'], s.get('bottom_menu_open', True))); return
    if cl=='/check_wizard': edit_page(chat_id,'⚙️ *تنظیمات معامله*',get_margin_keyboard(),message_id); return
    if cl=='/manage_watchlist': edit_page(chat_id,f'📋 واچ‌لیست: `{len(s["active_symbols"])}`',get_watchlist_manage_keyboard(),message_id); return
    if cl=='/watchlist_list': edit_page(chat_id,'📋 *واچ‌لیست*\n\n`'+', '.join(s['active_symbols'])+'`',get_watchlist_manage_keyboard(),message_id); return
    if cl=='/add_symbol_prompt': s['user_state']='ADD_SYMBOL'; save_session(chat_id); send_message(chat_id,'➕ نماد را بفرستید'); return
    if cl=='/remove_symbol_prompt': s['user_state']='REMOVE_SYMBOL'; save_session(chat_id); send_message(chat_id,'➖ نماد را بفرستید'); return
    if cl.startswith('/manage_'):
        sym=cl.replace('/manage_','').upper()
        for p in s['paper_positions']:
            if p['symbol']==sym:
                send_message(chat_id,format_trade_status(p),trade_action_keyboard(sym)); return
        send_message(chat_id,f'❌ پوزیشن باز `{sym}` در وضعیت ربات پیدا نشد.'); return
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
        stop_scan(chat_id, 'close-all')
        sync_bottom_keyboard(chat_id, "🔴 اسکن متوقف شد؛ در حال بستن همه پوزیشن‌ها...")
        for p in s['paper_positions'][:]:
            close_position(chat_id,p,reason='close_all')
        menu(chat_id)
        sync_bottom_keyboard(chat_id, "🔴 اسکن متوقف است.\n⚙️ همه پوزیشن‌های انتخاب‌شده بسته شدند.")
        return
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
        '💬 گفت‌وگو با هوش مصنوعی':'/ai_chat',
        'گفت‌وگو با هوش مصنوعی':'/ai_chat',
    }
    if raw in fixed_buttons:
        process_command(fixed_buttons[raw],chat_id)
        return
    s=get_session(chat_id); val=raw.upper()
    if s['user_state']=='AI_CHAT':
        # پاسخ AI ممکن است چند ثانیه زمان ببرد؛ اول یک پیام انتظار واقعی نشان بده.
        wait_res=tg('sendMessage', {
            'chat_id':chat_id,
            'text':'⏳ در حال بررسی درخواستت…\nداده‌های فعلی بازار و وضعیت ربات را بررسی می‌کنم؛ لطفاً چند لحظه صبر کن.',
            'reply_markup':get_ai_chat_keyboard()
        }, 10)
        wait_id=((wait_res or {}).get('result') or {}).get('message_id')
        tg('sendChatAction', {'chat_id':chat_id, 'action':'typing'}, 5)
        reply=ai_chat_reply(chat_id, raw)
        if wait_id:
            send_message(chat_id, reply, get_ai_chat_keyboard(), message_id=wait_id, parse_mode=None)
        else:
            send_message(chat_id, reply, get_ai_chat_keyboard(), parse_mode=None)
        return
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
                    if s['max_open_positions']>0 and len(s['paper_positions'])>=s['max_open_positions']:
                        logger.info('ENTRY_DIAG chat=%s stage=scan_batch_skipped reason=max_open_positions open=%s max=%s', cid, len(s['paper_positions']), s['max_open_positions'])
                        continue
                    for sym in list(s['active_symbols']): tasks.append(scan_symbol(http,cid,sym))
                if tasks:
                    batch = await asyncio.gather(*tasks, return_exceptions=True)
                    by_chat = {}
                    for item in batch:
                        if isinstance(item, Exception):
                            logger.warning('ENTRY_DIAG scan task failed: %s', item)
                            continue
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


def main():
    init_db(); load_telegram_offset(); load_sessions(); logger.info('Loaded %s sessions',len(USER_SESSIONS))
    configure_telegram_native_menu()
    Thread(target=telegram_listener,daemon=True,name='telegram').start(); Thread(target=lambda:(time.sleep(3),asyncio.run(scan_loop())),daemon=True,name='scanner').start()
    app.run(host='0.0.0.0',port=PORT,threaded=True)

if __name__=='__main__': main()
