# -*- coding: utf-8 -*-
"""V3.44.83: دکمه‌های ریست آمار / ریست کامل ربات فقط برای حساب کاغذی. اجرا: python3 paper_reset_buttons_selftest.py"""
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
bot.send_message = lambda *a, **k: True
bot.save_session = lambda *a, **k: None
bot._journal_reset_chat = lambda chat_id, real: (0, None)

def cbs(mk):
    return [b.get('callback_data') for r in mk['inline_keyboard'] for b in r if b.get('callback_data')]

CID = 987001
s = bot.get_session(CID)

# --- حساب کاغذی: دکمه‌ها هستند و برای کاربر عادی هم از فیلتر رد می‌شوند
s['trading_mode'] = 'PAPER'
k = bot.get_performance_keyboard(CID)
assert '/reset_stats_prompt' in cbs(k) and '/full_reset_prompt' in cbs(k), cbs(k)
assert bot._ap.user_command_allowed('/reset_stats_prompt', paper=bot._paper_account(CID))
assert bot._ap.user_command_allowed('/full_reset_confirm', paper=bot._paper_account(CID))
user_view = cbs(bot._ap.filter_markup(k, paper=bot._paper_account(CID)))
assert '/reset_stats_prompt' in user_view and '/full_reset_prompt' in user_view, user_view
assert '/trade_audit' not in user_view and '/export_trade_data' not in user_view      # بقیه‌ی دکمه‌های ادمین همچنان پنهان

# --- حساب واقعی: هیچ‌جا نه دکمه، نه اجازه، نه اجرا
s['trading_mode'] = 'REAL'
k = bot.get_performance_keyboard(CID)
assert not {'/reset_stats_prompt', '/full_reset_prompt'} & set(cbs(k)), cbs(k)
assert not bot._ap.user_command_allowed('/reset_stats_confirm', paper=bot._paper_account(CID))
out = []
bot.send_message = lambda chat_id, text, markup=None, message_id=None, **k: out.append(text) or True
s['closed_positions'] = [{'symbol': 'R', 'is_real': True, 'pnl': 2.0}]
ADMIN = 111
sa = bot.get_session(ADMIN); sa['trading_mode'] = 'REAL'; sa['paper_positions'] = []
sa['closed_positions'] = [{'symbol': 'R', 'is_real': True, 'pnl': 2.0}]
for c in ('/reset_stats_prompt', '/reset_stats_confirm', '/full_reset_prompt', '/full_reset_confirm'):
    out.clear(); bot.process_command(c, CID)                        # کاربر عادی در حساب واقعی: قفل نقش
    assert out and 'در دسترس نیست' in out[-1], (c, out)
    out.clear(); bot.process_command(c, ADMIN)                      # ادمین در حساب واقعی: خودِ دستور رد می‌کند
    assert out and 'فقط برای حساب کاغذی' in out[-1], (c, out)
assert len(s['closed_positions']) == 1 and len(sa['closed_positions']) == 1 and sa.get('trading_mode') == 'REAL'    # هیچ‌چیز پاک نشد
assert bot.get_performance_keyboard() and not {'/reset_stats_prompt'} & set(cbs(bot.get_performance_keyboard()))   # بدون chat_id هم امن

# --- حساب کاغذی: دستورها از process_command هم اجرا می‌شوند
s['trading_mode'] = 'PAPER'; out.clear(); bot.process_command('/reset_stats_prompt', CID)
assert out and 'ریست آمار و موجودی' in out[-1], out
s['closed_positions'] = [{'symbol': 'R', 'is_real': True, 'pnl': 2.0}]

# --- ریست آمار واقعاً کار می‌کند (کاغذی)
s['trading_mode'] = 'PAPER'
s['paper_positions'] = []
s['closed_positions'] = [{'symbol': 'X', 'is_real': False, 'pnl': 5.0}, {'symbol': 'Y', 'is_real': True, 'pnl': 1.0}]
ok, msg = bot.reset_stats(CID); assert ok, msg
assert [p for p in s['closed_positions'] if not p.get('is_real')] == [] and len(s['closed_positions']) == 1   # فقط کاغذی پاک شد

print('paper_reset_buttons_selftest OK')
