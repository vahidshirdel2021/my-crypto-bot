"""V3.44.63: کلید تغییر حساب کاغذی ⇄ واقعی در منوی اصلیِ همه‌ی کاربران. اجرا: python3 mode_toggle_selftest.py"""
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
import access_policy as ap, ui
out = []
bot.send_message = lambda chat_id, text, markup=None, message_id=None, **k: out.append((text, markup)) or True
bot.edit_page = lambda chat_id, text, markup=None, message_id=None, **k: out.append((text, markup)) or True
bot.exchange_balance = lambda chat_id: 100.0
USER, ADMIN = 222, 111

def cbs(mk): return [b['callback_data'] for r in mk['inline_keyboard'] for b in r]

# کیبورد: متن و دستور بر اساس حالت فعلی
kp = ui.get_main_menu_keyboard(False, True, False, 'PAPER'); kr = ui.get_main_menu_keyboard(False, True, False, 'REAL')
assert '/mode_real' in cbs(kp) and '/mode_paper' not in cbs(kp)
assert '/mode_paper' in cbs(kr) and '/mode_real' not in cbs(kr)
# V3.44.91: با باز شدن «🧭 رژیم BTC/ETH» برای کاربر عادی، چیدمان دوتایی عوض شد؛ کلید حساب در ردیف آخر است (نه لزوماً اولین دکمه)
assert any('واقعی' in b['text'] for b in kp['inline_keyboard'][-1]) and any('کاغذی' in b['text'] for b in kr['inline_keyboard'][-1])
# برای کاربر عادی بعد از فیلتر نقش هم می‌ماند (و برای ادمین هم کنار پنل مدیریت)
assert '/mode_real' in cbs(ap.filter_markup(kp)) and '/mode_paper' in cbs(ap.filter_markup(kr))
ka = ui.get_main_menu_keyboard(False, True, True, 'PAPER'); assert '/mode_real' in cbs(ka) and cbs(ka)[-1] == '/admin_panel'

# منوی اصلی واقعاً دکمه را می‌فرستد
for cid in (USER, ADMIN):
    s = bot.get_session(cid); s['trading_mode'] = 'PAPER'
    out.clear(); bot.menu(cid)
    assert '/mode_real' in cbs(out[-1][1]), cid
    s['trading_mode'] = 'REAL'
    out.clear(); bot.menu(cid)
    assert '/mode_paper' in cbs(out[-1][1]) and '/mode_real' not in cbs(out[-1][1]), cid
    s['trading_mode'] = 'PAPER'

# رفتار پشت دکمه (دستورهای موجود)
s = bot.get_session(USER); s['paper_positions'] = []
bot.PAPER_ONLY = True
out.clear(); bot.process_command('/mode_real', USER)
assert 'قفل' in out[-1][0] and s['trading_mode'] == 'PAPER', out[-1][0]          # بیلد PAPER_ONLY: قفل
bot.PAPER_ONLY = False
picked = []; bot.real_start_picker = lambda chat_id, mid=None: picked.append(chat_id)
s['paper_positions'] = [{'symbol': 'X'}]
out.clear(); bot.process_command('/mode_real', USER)
assert 'ابتدا تمام پوزیشن' in out[-1][0] and not picked                           # پوزیشن باز: ممنوع
s['paper_positions'] = []
bot.process_command('/mode_real', USER); assert picked == [USER]                  # شروع انتخاب صرافی
s['trading_mode'] = 'REAL'; s['real_positions'] = s.get('real_positions') or []
out.clear(); bot.process_command('/mode_paper', USER)
assert s['trading_mode'] == 'PAPER' and out, out
print('MODE TOGGLE OK')
