"""V3.44.64: «💰 گزارش کارمزد پلتفرم» (پنل مدیریت) کار می‌کند: متنش Markdown معتبر است و اگر Markdown جایی خراب باشد
پیام به‌صورت ساده ارسال می‌شود (به‌جای سکوتِ کامل). اجرا: python3 admin_fee_report_markdown_selftest.py"""
import sys, types, os, tempfile, re, time
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
import importlib
bot = importlib.import_module('bot'); bot.init_db()

def md_valid(text):
    """شبیه‌ساز ساده‌ی Markdown قدیمی تلگرام: بیرون از `کد`، تعداد «_» و «*» باید زوج باشد."""
    plain = re.sub(r'`[^`]*`', '', text)
    return plain.count('_') % 2 == 0 and plain.count('*') % 2 == 0 and text.count('`') % 2 == 0

# شبیه‌ساز تلگرام (۴۰۰ روی Markdown خراب)
sent = []
def fake_tg(method, payload=None, timeout=10):
    bot._TG_ERR.last = None
    if method in ('sendMessage', 'editMessageText'):
        if payload.get('parse_mode') and not md_valid(payload['text']):
            bot._TG_ERR.last = (400, "Bad Request: can't parse entities: Can't find end of the entity")
            return None
        sent.append((method, payload))
        return {'ok': True, 'result': {'message_id': 7}}
    return {'ok': True, 'result': {}}
bot.tg = fake_tg
bot.is_allowed = lambda c: True

# ۱) متن گزارش (هر دو حالت کارمزد، همه‌ی بازه‌ها، با داده‌ی واقعی) Markdown معتبر است
now = time.time()
with bot.DB_LOCK:
    c = bot.db_connect()
    for i, uid in enumerate((222, 333, 444)):
        c.execute('INSERT INTO fee_invoices(chat_id,day,profit_usdt,fee_rate_pct,fee_usdt,trades,status,created_at,due_ts) VALUES(?,?,?,?,?,?,?,?,?)',
                  (uid, '2026-10-2%d' % i, 10.0 + i, 10.0, 1.0 + i, 2, 'PAID' if i else 'PENDING', now, now + 3600))
        c.execute('INSERT INTO fee_ledger(trade_id,chat_id,mode,net_profit_before_platform_fee_usdt,fee_rate_pct,platform_fee_usdt,user_net_profit_usdt,created_at) VALUES(?,?,?,?,?,?,?,?)',
                  (f't{i}', uid, 'PAPER', 10.0, 10.0, 1.0, 9.0, now))
    c.commit(); c.close()
for mode in ('daily', 'per_trade'):
    bot.PLATFORM_FEE_MODE = mode
    for period in ('all', 'day', 'week', 'month'):
        t = bot.admin_fee_report(period)
        assert md_valid(t), (mode, period, 'markdown نامعتبر', t)
assert '`/fee_debts`' in bot._admin_fee_report_daily('all') and '/fee_debts' in bot._admin_fee_report_daily('all')
# گزارش کاربر هم معتبر است
bot.PLATFORM_FEE_MODE = 'daily'; assert md_valid(bot.fee_report(222, 'all'))

# ۲) رفتار پشت دکمه: واقعاً ارسال/ویرایش می‌شود (قبل از اصلاح: هیچ پیامی نمی‌رفت)
for mode in ('daily', 'per_trade'):
    bot.PLATFORM_FEE_MODE = mode
    for cmd in ('/admin_fee_menu', '/admin_fee_report', '/admin_fee_day', '/admin_fee_week', '/admin_fee_month'):
        sent.clear(); bot.process_command(cmd, 111, 5)
        assert sent and 'گزارش درآمد پلتفرم' in sent[-1][1]['text'], (mode, cmd, sent)

# ۳) تضمین: متن قدیمی (با /fee_debts بدون بک‌تیک) در شبیه‌ساز رد می‌شد؛ لایه‌ی ایمنی حالا آن را ساده می‌فرستد
bad = '👑 *گزارش*\n\nلیست بدهکاران: /fee_debts'
assert not md_valid(bad)
sent.clear(); ok = bot.send_message(111, bad, {'inline_keyboard': []})
assert ok and sent and 'parse_mode' not in sent[-1][1] and 'fee_debts' in sent[-1][1]['text'] and '*' not in sent[-1][1]['text'], sent
# خطای غیرِ parse دوباره‌ارسال نمی‌شود (جلوگیری از پیام تکراری)
calls = []
def fake_tg2(method, payload=None, timeout=10):
    calls.append(method); bot._TG_ERR.last = (500, 'Internal Server Error'); return None
bot.tg = fake_tg2
assert bot.send_message(111, 'سلام *x', {'inline_keyboard': []}) is False and calls.count('sendMessage') == 1, calls
print('ADMIN FEE REPORT MARKDOWN OK')
