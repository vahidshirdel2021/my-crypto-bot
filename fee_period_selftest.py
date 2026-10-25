"""V3.44.68: دوره‌ی پرداخت (روزانه/هفتگی/ماهانه) + حساب واریز ادمین. اجرا: python3 fee_period_selftest.py"""
import sys, types, os, tempfile, time
for name in ('aiohttp', 'ccxt', 'ccxt.async_support'):
    try: __import__(name)
    except Exception: sys.modules[name] = types.ModuleType(name)
if not hasattr(sys.modules['aiohttp'], 'ClientSession'):
    sys.modules['aiohttp'].ClientTimeout = lambda **k: None
    sys.modules['aiohttp'].TCPConnector = lambda **k: None
    sys.modules['aiohttp'].ClientSession = object
os.environ.update({'TELEGRAM_TOKEN': '123:abc', 'ADMIN_CHAT_IDS': '111', 'TELEGRAM_SKIP_BACKLOG': 'true',
                   'BOT_DB_PATH': os.path.join(tempfile.mkdtemp(), 'b.sqlite3'), 'FEE_DAY_TZ': 'UTC', 'PLATFORM_FEE_MODE': 'daily'})
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
from datetime import datetime, timezone
bot = importlib.import_module('bot'); bot.init_db()
import daily_fee as df
sent = []
bot.send_message = lambda chat_id, text, markup=None, message_id=None, **k: sent.append((chat_id, text, markup)) or True
bot.edit_page = lambda chat_id, text, markup=None, message_id=None, **k: sent.append((chat_id, text, markup)) or True
ADMIN, USER = 111, 222

def ts(day, hour=12):
    y, m, d = map(int, day.split('-')); return datetime(y, m, d, hour, tzinfo=timezone.utc).timestamp()

s = bot.get_session(USER)
s['closed_positions'] = [{'is_real': True, 'pnl_usdt': 10.0, 'close_timestamp': ts(d), 'symbol': 'X'} for d in
                         ('2026-10-12', '2026-10-13', '2026-10-20', '2026-10-21', '2026-10-22')]
bot.FEE_INCLUDE_PAPER = True

def invoices():
    import sqlite3
    c = bot.db_connect()
    try:
        return c.execute('SELECT day,end_day,period,profit_usdt,fee_usdt FROM fee_invoices WHERE chat_id=? ORDER BY day', (USER,)).fetchall()
    finally:
        c.close()

# --- پیش‌فرض روزانه
assert bot.fee_period() == 'daily'
# --- ادمین: کلیدها در منو هست
kb = bot.get_admin_fee_menu_keyboard()
cds = [b['callback_data'] for row in kb['inline_keyboard'] for b in row]
for need in ('/admin_fee_period_daily', '/admin_fee_period_weekly', '/admin_fee_period_monthly', '/admin_fee_account_prompt'):
    assert need in cds, need
assert any('✅ روزانه' in b['text'] for row in kb['inline_keyboard'] for b in row)

# --- تغییر دوره به هفتگی فقط برای ادمین
sent.clear(); bot.process_command('/admin_fee_period_weekly', USER)
assert bot.fee_period() == 'daily'
sent.clear(); bot.process_command('/admin_fee_period_weekly', ADMIN)
assert bot.fee_period() == 'weekly' and any('هفتگی' in t for _c, t, _m in sent)
assert any('✅ هفتگی' in b['text'] for row in bot.get_admin_fee_menu_keyboard()['inline_keyboard'] for b in row)

# --- تعریف حساب واریز: دکمه → متن
sent.clear(); bot.process_command('/admin_fee_account_prompt', ADMIN)
assert bot.get_session(ADMIN)['user_state'] == 'WAIT_ADMIN_FEE_ACCOUNT'
bot.handle_text(ADMIN, 'TRC20: TXYZ-ADMIN-WALLET')
assert bot.fee_payment_account() == 'TRC20: TXYZ-ADMIN-WALLET' and bot.get_session(ADMIN)['user_state'] is None

# --- صدور هفتگی: شنبه 2026-10-24 شروع هفته (week_start=5)؛ آخرین فاکتور تا جمعه 10-16 → بازه‌ی 10-17..10-23
bot._fee_meta_set('fee_invoiced_through', '2026-10-16')
real_time = time.time
time.time = lambda: ts('2026-10-25', 1)          # یکشنبه
try:
    sent.clear(); bot.fee_daily_tick()
finally:
    time.time = real_time
inv = invoices()
assert len(inv) == 1 and inv[0][0] == '2026-10-17' and inv[0][1] == '2026-10-23' and inv[0][2] == 'weekly', inv
assert abs(inv[0][3] - 30.0) < 1e-9 and abs(inv[0][4] - 3.0) < 1e-9, inv        # 20,21,22 اکتبر = ۳۰ USDT (۱۲ و ۱۳ در بازه‌ی قبل)
user_msgs = [t for c, t, m in sent if c == USER]
assert any('کارمزد هفتگی' in t and 'TRC20: TXYZ-ADMIN-WALLET' in t and '1405/07/25 تا 1405/08/01' in t for t in user_msgs), user_msgs
assert bot._fee_meta_get('fee_invoiced_through') == '2026-10-23'

# --- تکرار تیک: فاکتور دوباره ساخته نمی‌شود
time.time = lambda: ts('2026-10-25', 2)
try: bot.fee_daily_tick()
finally: time.time = real_time
assert len(invoices()) == 1

# --- تغییر به ماهانه وسط راه: بازه از روز بعد از آخرین فاکتور (10-24) تا آخر ماه؛ هیچ روزی دوبار حساب نمی‌شود
s['closed_positions'].append({'is_real': True, 'pnl_usdt': 20.0, 'close_timestamp': ts('2026-10-27'), 'symbol': 'Y'})
bot.fee_set_period('monthly')
s['closed_positions'] += [{'is_real': True, 'pnl_usdt': 10.0, 'close_timestamp': ts('2026-11-10'), 'symbol': 'Z'}, {'is_real': True, 'pnl_usdt': 50.0, 'close_timestamp': ts('2026-11-22'), 'symbol': 'W'}]
time.time = lambda: ts('2026-11-02', 1)
try: bot.fee_daily_tick()
finally: time.time = real_time
assert len(invoices()) == 1, invoices()          # آبان ۱۴۰۵ هنوز تمام نشده
time.time = lambda: ts('2026-11-23', 1)           # ۲ آذر ۱۴۰۵ → آبان کامل شده
try: bot.fee_daily_tick()
finally: time.time = real_time
inv = invoices()
assert [(r[0], r[1], r[2]) for r in inv] == [('2026-10-17', '2026-10-23', 'weekly'), ('2026-10-24', '2026-11-21', 'monthly')], inv
assert abs(inv[1][3] - 30.0) < 1e-9 and abs(inv[1][4] - 3.0) < 1e-9, inv      # ۲۷ اکتبر (۲۰) + ۱۰ نوامبر (۱۰)؛ ۲۲ نوامبر = آذر، بعداً
assert bot._fee_meta_get('fee_invoiced_through') == '2026-11-21'
# --- پیام مسدودی/تسویه برچسب بازه را دارد
assert 'بازه‌ی 1405/07/25 تا 1405/08/01' in df.blocked_message('2026-10-17', 3.0, 'a', 'weekly', '2026-10-23')
assert 'روز 2026-10-17' in df.blocked_message('2026-10-17', 3.0, 'a')
print('fee_period_selftest OK')
