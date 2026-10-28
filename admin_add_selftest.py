"""V3.44.103: تعریف ادمین از پنل ادمین (دیتابیس موقت، بدون تلگرام). اجرا: python3 admin_add_selftest.py"""
import sys, types, os, tempfile
for name in ('aiohttp', 'ccxt', 'ccxt.async_support'):
    try:
        __import__(name)
    except Exception:
        sys.modules[name] = types.ModuleType(name)
if not hasattr(sys.modules['aiohttp'], 'ClientSession'):
    sys.modules['aiohttp'].ClientTimeout = lambda **k: None
    sys.modules['aiohttp'].TCPConnector = lambda **k: None
    sys.modules['aiohttp'].ClientSession = object
os.environ['TELEGRAM_TOKEN'] = '123:abc'
os.environ['ADMIN_CHAT_IDS'] = '111'
os.environ['BOT_DB_PATH'] = os.path.join(tempfile.mkdtemp(), 'bot.sqlite3')
os.environ['TELEGRAM_SKIP_BACKLOG'] = 'true'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
bot = importlib.import_module('bot')
bot.init_db(); bot.load_access_control(); bot.load_extra_admins()
sent = []
def fake_send(chat_id, text, markup=None, message_id=None, parse_mode='Markdown', keep=False):
    sent.append((chat_id, text, markup)); return True
bot.send_message = fake_send
bot.edit_page = lambda chat_id, text, markup=None, message_id=None, parse_mode='Markdown': sent.append((chat_id, text, markup)) or True
ADMIN, NEW, USER = 111, 555, 222
assert bot.is_admin(ADMIN) and not bot.is_admin(NEW) and bot.is_restricted_user(NEW)
cbs = lambda mk: [b['callback_data'] for r in (mk or {}).get('inline_keyboard', []) for b in r]
# 1) دکمه در پنل دسترسی هست
assert '/admin_access_admin_add_prompt' in cbs(bot.access_panel_keyboard())
# 2) کاربر عادی نمی‌تواند ادمین اضافه کند
sent.clear(); bot.process_command('/admin_access_admin_add_prompt', USER)
assert not bot.is_admin(USER) and sent and 'در دسترس نیست' in sent[0][1] or 'دسترسی ادمین' in sent[0][1], sent
# 3) ادمین: دکمه → حالت انتظار → آیدی
sent.clear(); bot.process_command('/admin_access_admin_add_prompt', ADMIN)
assert bot.get_session(ADMIN).get('user_state') == 'WAIT_ADMIN_ADMIN_ADD' and 'افزودن ادمین' in sent[0][1], sent
sent.clear(); bot.handle_text(ADMIN, '555 علی')
assert bot.is_admin(NEW) and not bot.is_restricted_user(NEW) and NEW in bot.ADMIN_CHAT_IDS, (sent, bot.ADMIN_CHAT_IDS)
assert any(c == NEW and 'ادمین' in t for c, t, _ in sent), 'new admin must be notified'
assert bot.get_session(ADMIN).get('user_state') is None
# 4) فهرست و دکمه‌ی حذف در پنل
txt = bot.access_panel_text(); assert '555' in txt and 'علی' in txt, txt
assert '/admin_access_admin_rm_555' in cbs(bot.access_panel_keyboard())
# 5) ماندگاری: با بارگذاری دوباره‌ی جدول (شبیه ری‌استارت) هنوز ادمین است
bot.ADMIN_CHAT_IDS.discard(NEW); bot._EXTRA_ADMIN_IDS.discard(NEW); assert not bot.is_admin(NEW)
bot.load_extra_admins(); assert bot.is_admin(NEW)
# 6) ادمین جدید خودش می‌تواند پنل مدیریت را ببیند و ادمین دیگری اضافه کند
sent.clear(); bot.process_command('/admin_access', NEW); assert sent and 'مدیریت دسترسی' in sent[0][1], sent
ok, msg = bot.admin_add(777, NEW, 'x'); assert ok and bot.is_admin(777)
# 7) خطاها: تکراری، منفی (گروه)، صفر، متن نامعتبر
assert bot.admin_add(555, ADMIN)[0] is False and bot.admin_add(111, ADMIN)[0] is False
assert bot.admin_add(-100123, ADMIN)[0] is False and bot.admin_add(0, ADMIN)[0] is False and bot.admin_add('abc', ADMIN)[0] is False
# 8) حذف: ادمین env و خودِ شخص قابل حذف نیست؛ ادمین پنل حذف می‌شود و بلافاصله دسترسی را از دست می‌دهد
assert bot.admin_remove(111, 555)[0] is False and bot.is_admin(111)
assert bot.admin_remove(555, 555)[0] is False and bot.is_admin(555)
sent.clear(); bot.process_command('/admin_access_admin_rm_777', ADMIN)
assert not bot.is_admin(777) and bot.is_restricted_user(777) and bot.is_admin(111) and bot.is_admin(555)
assert bot.admin_remove(777, ADMIN)[0] is False        # دوباره: در لیست نیست
# 9) مسیر برگشت دکمه‌ی پرامپت
assert bot._BACK_PARENT.get('/admin_access_admin_add_prompt') == '/admin_access'
print('admin_add_selftest ALL OK')
