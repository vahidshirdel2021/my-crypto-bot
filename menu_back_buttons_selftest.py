# -*- coding: utf-8 -*-
"""V3.44.84: همه‌ی منوها دکمه‌ی برگشت/منوی اصلی دارند؛ تایم‌فریم فقط ۵ و ۱۵ دقیقه. اجرا: python3 menu_back_buttons_selftest.py"""
import sys, types, os, tempfile, inspect
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
import ui, access_policy as ap

def cbs(mk): return [b.get('callback_data') for r in mk['inline_keyboard'] for b in r if b.get('callback_data')]
def has_exit(c):
    return any(x in ('/menu', '/cancel') or x.startswith(('/back:', '/menu_')) or x in ('/admin_panel', '/trade_filter_management', '/wiz_lev', '/wiz_max', '/wiz_same', '/check_wizard', '/mode_paper')
               for x in c)

# 1) همه‌ی کیبوردهای ui.py (به‌جز صفحه‌ی اولِ انتخاب حساب، منوی اصلی و کیبورد ثابت) راه خروج دارند
EXEMPT = {'get_start_keyboard', 'get_main_menu_keyboard', 'get_bottom_menu_keyboard'}
samples = {'get_positions_keyboard': ([{'symbol': 'BTC', 'side': 'BUY'}],), 'get_admin_fee_menu_keyboard': ('daily', True)}
n = 0
for name, f in inspect.getmembers(ui, inspect.isfunction):
    if not (name.startswith('get_') and name.endswith('keyboard')) or name in EXEMPT: continue
    try: mk = f(*samples.get(name, ()))
    except TypeError: mk = f({})
    assert isinstance(mk, dict) and 'inline_keyboard' in mk, name
    assert has_exit(cbs(mk)), ('منو بدون دکمه‌ی برگشت/منوی اصلی', name, cbs(mk))
    n += 1
assert n >= 20, n

# 2) تایم‌فریم: فقط ۵ و ۱۵ دقیقه
tf = [c for c in cbs(ui.get_timeframe_keyboard()) if c != '/dummy']
assert [c for c in tf if c.startswith('/set_tf_')] == ['/set_tf_5m', '/set_tf_15m'], tf
txt = ' '.join(b['text'] for r in ui.get_timeframe_keyboard()['inline_keyboard'] for b in r)
assert 'ساعته' not in txt and 'روندی' not in txt, txt

# 3) زنجیره‌ی برگشتِ ویزارد «تنظیمات معامله»
mk = ui.get_margin_keyboard(); assert '/menu_settings' in cbs(mk) and '/menu' in cbs(mk)
assert '/mode_paper' in cbs(ui.get_margin_keyboard(back='/mode_paper'))
assert '/check_wizard' in cbs(ui.get_leverage_keyboard())
assert '/wiz_lev' in cbs(ui.get_max_positions_keyboard())
assert '/wiz_max' in cbs(bot.wizard_same_dir_keyboard(111))
assert '/wiz_same' in cbs(ui.get_timeframe_keyboard())
assert '/menu' in cbs(ui.get_balance_keyboard())

# 4) این دکمه‌ها برای کاربر عادی هم کار می‌کنند (قفل نقش نباید ببندد)
for kb in (ui.get_balance_keyboard(), ui.get_margin_keyboard(), ui.get_leverage_keyboard(), ui.get_max_positions_keyboard(),
           ui.get_timeframe_keyboard(), bot.wizard_same_dir_keyboard(222)):
    assert [c for c in cbs(ap.filter_markup(kb))] == [c for c in cbs(kb) if c != '/dummy'], cbs(kb)

# 5) دستورهای برگشت واقعاً صفحه‌ی قبل را نشان می‌دهند
out = []
bot.send_message = lambda chat_id, text, markup=None, message_id=None, **k: out.append((text, markup)) or True
bot.edit_page = lambda chat_id, text, markup=None, message_id=None, **k: out.append((text, markup)) or True
for cmd, expect in (('/check_wizard', '/set_margin_10'), ('/wiz_lev', '/set_lev_3'), ('/wiz_max', '/set_max_2'), ('/wiz_same', '/set_wsame_1')):
    for chat in (111, 222):
        out.clear(); bot.process_command(cmd, chat)
        assert out and expect in cbs(out[-1][1]), (cmd, chat, out)
print('menu_back_buttons_selftest OK')
