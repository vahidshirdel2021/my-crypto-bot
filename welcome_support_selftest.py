"""V3.44.76: پیام خوش‌آمدگویی با نام کاربر + شعار، و دکمه‌ی «پشتیبان ربات» در منوی اصلی. اجرا: python3 welcome_support_selftest.py"""
import sys, types, os, tempfile
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
sent, calls = [], []
bot.send_message = lambda chat_id, text, markup=None, message_id=None, parse_mode='Markdown', keep=False: sent.append((chat_id, text, markup)) or True
bot.sync_bottom_keyboard = lambda *a, **k: None
bot.tg = lambda method, payload=None, timeout=10: calls.append((method, payload)) or {'ok': True}
USER, ADMIN = 222, 111
bot.upsert_telegram_user({'id': USER, 'first_name': 'علی_*', 'username': 'ali'}, USER)
# 1) خوش‌آمدگویی با نام (بدون نویسه‌های خراب‌کننده‌ی مارک‌داون) و شعار
sent.clear(); bot.process_command('/start', USER)
t = sent[0][1]
assert 'سلام علی عزیز' in t and 'حفظ سرمایه اولین اولویت ماست' in t and 'حالت حساب را انتخاب کنید' in t and '*' not in t.split('🛡')[0] and '_' not in t.split('🛡')[0], t
# بدون نام: باز هم خوش‌آمد می‌گوید
sent.clear(); bot.process_command('/start', 333)
assert 'خوش آمدی' in sent[0][1] and 'حفظ سرمایه' in sent[0][1]
# 2) دکمه‌ی پشتیبان در منوی اصلی (کاربر عادی و ادمین)
import access_policy as ap
for cid in (USER, ADMIN):
    sent.clear(); bot.process_command('/menu', cid)
    cbs = [b['callback_data'] for r in sent[0][2]['inline_keyboard'] for b in r]
    assert '/support' in cbs, (cid, cbs)
assert ap.user_command_allowed('/support')
assert '/support' in [b['callback_data'] for r in ap.filter_markup(sent[0][2])['inline_keyboard'] for b in r]
# 3) صفحه‌ی پشتیبان: نام، سمت، شماره + کارت مخاطب
sent.clear(); calls.clear(); bot.process_command('/support', USER)
t = sent[0][1]
assert 'وحید شیردل' in t and 'تحلیلگر بازارهای مالی' in t and '09905493828' in t, t
assert calls and calls[0][0] == 'sendContact' and calls[0][1]['phone_number'] == '+989905493828' and calls[0][1]['first_name'] == 'وحید' and calls[0][1]['last_name'] == 'شیردل', calls
print('WELCOME SUPPORT OK')
