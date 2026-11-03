"""V3.44.133: کلید «بدون جهت غالب بازار = بدون معامله». اجرا: python3 need_dominant_selftest.py"""
import sys, types, os, tempfile, time
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
bot.init_db()

CID = 111
s = bot.get_session(CID)
cfg = s.setdefault('strategy_config', {})
K = 'gate_touch_need_dominant_enabled'
KB = 'gate_touch_bias_block_enabled'

# ثبت کلید: پیش‌فرض خاموش، بخش قوانین ورود، در پریست‌ها مدیریت می‌شود
assert bot.GATE_REGISTRY[K][1] is False and bot.GATE_REGISTRY[K][2] == 'entry_rules'
import presets; assert presets.BASE_CFG.get(K) is False
assert bot.BOT_VERSION == '3.44.136'

bot.save_session = lambda *a, **k: None
bot._touch_update_card = lambda *a, **k: True
bot._fn_touch_final = lambda *a, **k: None
bot._fn_touch_created = lambda *a, **k: None
bot.latest_price = lambda sym: 100.0
bot.exchange_latest_price = lambda c, sy: 100.0
bot._touch_eval_one = lambda chat_id, rec: None
s['is_bot_active'] = True; s['daily_stopped'] = False; s['paper_positions'] = []
reached = {'n': 0}
class _Stop(Exception): pass
# نقطه‌ی بعد از سدها: اگر کد به اینجا برسد یعنی سد نگهش نداشته
bot._touch_manual_block = None
orig_gate_on = bot.gate_on

def mk(sym, d, status='waiting'):
    now = time.time()
    return {'id': sym, 'symbol': sym, 'touch_sig': d, 'dir': d, 'status': status, 'created_at': now, 'expires_at': now + 1800, 'votes': [], 'tf': '15min'}

def load(buys, sells):
    s['touch_wait'] = {}
    for i in range(buys):
        r = mk(f'B{i}', 'BUY'); s['touch_wait'][r['id']] = r
    for i in range(sells):
        r = mk(f'S{i}', 'SELL'); s['touch_wait'][r['id']] = r

# سناریوی عکس: ۰ خرید / ۱ فروش → غلبه نیست
cfg[KB] = False
cfg[K] = True; load(0, 1)
r = s['touch_wait']['S0']; r['auto_ok'] = True
res = bot._touch_auto_enter_core(CID, r)
assert res is False and r['status'] == 'waiting', (res, r['status'])
assert 'جهت غالب بازار مشخص نیست' in r['block_note'] and '0 خرید / 1 فروش' in r['block_note'], r.get('block_note')

# ۴ فروش / ۴ خرید (۵۰٪) هم غلبه ندارد
load(4, 4); r = s['touch_wait']['S0']
assert bot._touch_auto_enter_core(CID, r) is False and 'مشخص نیست' in r['block_note']

# غلبه‌ی مشخص (۷ فروش / ۳ خرید) این سد را رد می‌کند: اگر بلاک شود دلیلش غیر از «مشخص نیست» است
load(3, 7); r = s['touch_wait']['S0']
try:
    bot._touch_auto_enter_core(CID, r)
except Exception:
    pass            # سدهای بعدی (قیمت/اکسچنج) در تست ساختگی ممکن است خطا بدهند؛ مهم این است که سد جدید نگه نداشته
assert 'مشخص نیست' not in (r.get('block_note') or ''), r.get('block_note')

# کلید خاموش: هیچ سد جدیدی نیست (رفتار قبلی)
cfg[K] = False; load(0, 1); r = s['touch_wait']['S0']
try:
    bot._touch_auto_enter_core(CID, r)
except Exception:
    pass
assert 'مشخص نیست' not in (r.get('block_note') or ''), r.get('block_note')

# نمایش لیست برای ادمین
sent = []
bot.send_message = lambda chat_id, text, markup=None, message_id=None, **k: sent.append(text) or True
bot.is_restricted_user = lambda c: False
for kk, kb, b, sl in ((True, False, 0, 1), (True, True, 3, 7), (False, False, 0, 1)):
    cfg[K] = kk; cfg[KB] = kb; load(b, sl); sent.clear(); bot.assist_pending_list(CID)
    assert 'جهت بازار' not in sent[-1] and 'فشار' not in sent[-1] and '📊' not in sent[-1] and 'بدون غلبه' not in sent[-1], sent[-1][:400]   # V3.44.136: خطوط بالای لیست حذف شد
    assert '📋' in sent[-1] and 'برخورد با سطح' in sent[-1]
print('need_dominant_selftest ALL OK')
