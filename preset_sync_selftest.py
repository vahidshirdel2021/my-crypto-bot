"""تست همگام‌سازی خودکار کاربران بعد از ذخیره/بازگشت کلید پریست. اجرا: python3 preset_sync_selftest.py"""
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
_tmp = tempfile.mkdtemp()
os.environ['TELEGRAM_TOKEN'] = '123:abc'
os.environ['ADMIN_CHAT_IDS'] = '111'
os.environ['BOT_DB_PATH'] = os.path.join(_tmp, 'bot.sqlite3')
os.environ['PRESETS_CUSTOM_PATH'] = os.path.join(_tmp, 'presets_custom.json')
os.environ['TELEGRAM_SKIP_BACKLOG'] = 'true'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
bot = importlib.import_module('bot')
bot.init_db()
P = bot.presets_mod

sent = []
bot.send_message = lambda chat_id, text, markup=None, message_id=None, parse_mode='Markdown', keep=False: sent.append((chat_id, text, markup)) or True
bot.edit_page = lambda chat_id, text, markup=None, message_id=None, parse_mode='Markdown': sent.append((chat_id, text, markup)) or True

ADMIN, U1, U2, U3 = 111, 222, 333, 444
ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, info)

# کاربران: U1 و U3 حالت محافظه‌کار (کلید ۴)، U2 معمولی (کلید ۳)
for cid, mode in ((U1, '4'), (U2, '3'), (U3, '4')):
    s = bot.get_session(cid)
    P.apply_preset(s, mode)
check("شروع: کاربران روی پیش‌فرض کد", bot.get_session(U1)['strategy_config']['halving_k_atr'] == 4.0)

# کاربر عادی نمی‌تواند ذخیره کند
sent.clear(); bot.process_command('/preset_save_4', U1)
check("کاربر عادی: ذخیره ممنوع و چیزی ذخیره نشد", len(sent) == 1 and not P.has_custom('4'), sent[0][1][:40] if sent else '')

# ادمین تنظیمات را عوض و در کلید ۴ ذخیره می‌کند
a = bot.get_session(ADMIN)
a['strategy_config']['halving_k_atr'] = 2.0
a['strategy_config']['gate_fc_rsi_enabled'] = False
a['touch_auto_mode'] = 'majority'
sent.clear(); bot.process_command('/preset_save_4', ADMIN)
check("ادمین: ذخیره شد", P.has_custom('4') and a['active_preset'] == '4')
for cid in (U1, U3):
    s = bot.get_session(cid)
    check(f"کاربر {cid} روی کلید ۴ خودکار نسخه‌ی جدید را گرفت",
          s['strategy_config']['halving_k_atr'] == 2.0 and s['strategy_config']['gate_fc_rsi_enabled'] is False and s['touch_auto_mode'] == 'majority' and s['active_preset'] == '4')
check("کاربر روی کلید ۳ دست‌نخورده", bot.get_session(U2)['strategy_config']['halving_k_atr'] == 4.0 and bot.get_session(U2)['touch_auto_mode'] == 'majority')
check("پیام ادمین تعداد کاربران همگام‌شده را می‌گوید", any('۲ نفر' in m[1] for m in sent), [m[1][-80:] for m in sent][:1])

# ذخیره‌شده در دیتابیس هم نوشته شد (بعد از ریستارت می‌ماند)
import json, sqlite3
row = sqlite3.connect(os.environ['BOT_DB_PATH']).execute('SELECT data FROM sessions WHERE chat_id=?', (U1,)).fetchone()
check("نسخه‌ی جدید در دیتابیس کاربر ذخیره شد", row and json.loads(row[0])['strategy_config']['halving_k_atr'] == 2.0)

# کاربری که قبل از ذخیره حالتش را عوض کرده بود (کلید ۵) تغییری نمی‌کند
s3 = bot.get_session(U3); P.apply_preset(s3, '5')
a['strategy_config']['halving_k_atr'] = 3.0
bot.process_command('/preset_save_4', ADMIN)
check("کاربر روی کلید ۵ از ذخیره‌ی کلید ۴ تاثیر نگرفت", bot.get_session(U3)['strategy_config']['halving_k_atr'] == 4.0 and bot.get_session(U3)['active_preset'] == '5')
check("U1 باز هم روی کلید ۴ به‌روز شد", bot.get_session(U1)['strategy_config']['halving_k_atr'] == 3.0)

# ادمین دیگر دست‌نخورده می‌ماند
bot.ADMIN_CHAT_IDS.add(555)
a2 = bot.get_session(555); P.apply_preset(a2, '4'); a2['strategy_config']['halving_k_atr'] = 9.0
a['strategy_config']['halving_k_atr'] = 2.5
bot.process_command('/preset_save_4', ADMIN)
check("ادمین دوم با تنظیم دستی خودش دست‌نخورده", a2['strategy_config']['halving_k_atr'] == 9.0)

# بازگشت به پیش‌فرض: کاربران کلید ۴ هم برمی‌گردند
sent.clear(); bot.process_command('/preset_reset_4', ADMIN)
check("بعد از reset کلید ۴ پیش‌فرض کد است", not P.has_custom('4'))
check("کاربر روی کلید ۴ خودکار به پیش‌فرض برگشت", bot.get_session(U1)['strategy_config']['halving_k_atr'] == 4.0 and bot.get_session(U1)['strategy_config']['gate_fc_rsi_enabled'] is True)
check("خود ادمین هم برگشت", a['strategy_config']['halving_k_atr'] == 4.0)
print("\nALL PASS" if ok else "\nSOME FAILED")
raise SystemExit(0 if ok else 1)
