"""V3.44.63: «💰 کارمزد من» با تفکیک روز + جمع کل (حالت روزانه و هر معامله) و کلید منوی اصلی. اجرا: python3 fee_report_by_day_selftest.py"""
import sys, types, os, tempfile, time
for name in ('aiohttp', 'ccxt', 'ccxt.async_support'):
    try: __import__(name)
    except Exception: sys.modules[name] = types.ModuleType(name)
if not hasattr(sys.modules['aiohttp'], 'ClientSession'):
    sys.modules['aiohttp'].ClientTimeout = lambda **k: None
    sys.modules['aiohttp'].TCPConnector = lambda **k: None
    sys.modules['aiohttp'].ClientSession = object
os.environ['TELEGRAM_TOKEN'] = '123:abc'; os.environ['ADMIN_CHAT_IDS'] = '111'
os.environ['BOT_DB_PATH'] = os.path.join(tempfile.mkdtemp(), 'bot.sqlite3'); os.environ['TELEGRAM_SKIP_BACKLOG'] = 'true'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib, re
bot = importlib.import_module('bot'); bot.init_db()
import access_policy as ap, ui
USER = 222
tz = bot._fee_tz(); now = time.time(); today = bot._df.day_key(now, tz)
d = lambda n: bot._df.shift_day(today, -n)
bot.get_user_fee_rate = lambda c: 10.0

def ins(day, profit, fee, status):
    with bot.DB_LOCK:
        c = bot.db_connect(); c.execute('INSERT INTO fee_invoices(chat_id,day,profit_usdt,fee_rate_pct,fee_usdt,trades,status,created_at,due_ts) VALUES(?,?,?,?,?,?,?,?,?)',
                                        (USER, day, profit, 10.0, fee, 3, status, now, now + 3600)); c.commit(); c.close()
ins(d(1), 20.0, 2.0, 'PAID'); ins(d(2), 10.0, 1.0, 'PENDING'); ins(d(3), 5.0, 0.5, 'WAIVED'); ins(d(10), 30.0, 3.0, 'PAID'); ins(d(40), 100.0, 10.0, 'PAID')
s = bot.get_session(USER)
st_ts, _ = bot._df.day_bounds(today, tz)
s['closed_positions'] = [{'close_timestamp': st_ts + 60, 'pnl_usdt': 8.0, 'is_real': False}]      # سود امروز ← کارمزد تخمینی 0.80

bot.PLATFORM_FEE_MODE = 'daily'
r_all = bot.fee_report(USER, 'all'); r_w = bot.fee_report(USER, 'week'); r_d = bot.fee_report(USER, 'day'); r_m = bot.fee_report(USER, 'month')
print(r_all)
def total(t): return float(re.search(r'جمع کل کارمزد: `([\d.]+) USDT`', t).group(1))
# کل: 0.80(امروز تخمینی)+2+1+3+10 = 16.80 ؛ بخشوده شمرده نمی‌شود
assert abs(total(r_all) - 16.80) < 1e-6, total(r_all)
assert abs(total(r_m) - 6.80) < 1e-6, total(r_m)      # ۳۰ روز: بدون روز ۴۰ (0.8+2+1+3)
assert abs(total(r_w) - 3.80) < 1e-6, total(r_w)      # ۷ روز: 0.8+2+1 (بخشوده نه، روز ۱۰ بیرون)
assert abs(total(r_d) - 0.80) < 1e-6, total(r_d)      # فقط امروز
assert 'تخمینی' in r_all and d(1) in r_all and d(2) in r_all and 'بخشوده' in r_all
assert d(1) not in r_d and today in r_d
assert 'پرداخت‌نشده (کل): `1.00 USDT`' in r_all and 'پرداخت‌شده: `15.00 USDT`' in r_all
assert r_all.index(today) < r_all.index(d(1)) < r_all.index(d(2)), 'جدیدترین اول'
# فاصله‌ی روز ۴۰ هم در «کل» می‌آید
assert d(40) in r_all and d(40) not in r_m
# بدون داده
bot.get_session(333)['closed_positions'] = []
e = bot.fee_report(333, 'all'); assert 'هنوز کارمزدی ثبت نشده' in e and total(e) == 0.0, e
# بیش از ۳۱ روز: خلاصه‌ی قدیمی‌ترها، جمع کل همچنان درست
for i in range(50, 90): ins(d(i), 10.0, 1.0, 'PAID')
r_big = bot.fee_report(USER, 'all'); assert 'روز قدیمی‌تر' in r_big and abs(total(r_big) - (16.80 + 40.0)) < 1e-6, (total(r_big), r_big[-600:])
assert len(r_big) < 4000, len(r_big)

# حالت هر معامله
bot.PLATFORM_FEE_MODE = 'per_trade'
with bot.DB_LOCK:
    c = bot.db_connect()
    for i, (ts, p, f) in enumerate([(st_ts + 100, 10.0, 1.0), (st_ts + 200, 4.0, 0.4), (st_ts - 86400 + 100, 6.0, 0.6)]):
        c.execute('INSERT INTO fee_ledger(trade_id,chat_id,mode,net_profit_before_platform_fee_usdt,fee_rate_pct,platform_fee_usdt,user_net_profit_usdt,created_at) VALUES(?,?,?,?,?,?,?,?)',
                  (f't{i}', 444, 'PAPER', p, 10.0, f, p - f, ts))
    c.commit(); c.close()
r_pt = bot.fee_report(444, 'all'); print(r_pt)
assert abs(total(r_pt) - 2.0) < 1e-6 and r_pt.count('• `20') == 2 and 'پرداخت‌نشده' not in r_pt
bot.PLATFORM_FEE_MODE = 'daily'

# دکمه‌ی منوی اصلی + دسترسی کاربر عادی
mk = ui.get_main_menu_keyboard(False, True, False, 'PAPER')
assert ['/fee_menu'] in [[b['callback_data'] for b in r] for r in mk['inline_keyboard']] and '/fee_menu' in [b['callback_data'] for r in ap.filter_markup(mk)['inline_keyboard'] for b in r]
assert all(ap.user_command_allowed(c) for c in ('/fee_menu', '/fee_today', '/fee_week', '/fee_month', '/fee_all'))
print('FEE REPORT BY DAY OK')
