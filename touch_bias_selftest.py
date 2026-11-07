"""V3.44.132: کلید «مانع جهت مخالف بازار» در لیست انتظار (روی خودِ bot.py، دیتابیس موقت). اجرا: python3 touch_bias_selftest.py"""
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
K = 'gate_touch_bias_block_enabled'

# --- ثبت کلید: پیش‌فرض خاموش، بخش قوانین ورود، مدیریت‌شده در پریست ---
assert bot.GATE_REGISTRY[K][1] is False and bot.GATE_REGISTRY[K][2] == 'entry_rules'
import presets; assert presets.BASE_CFG.get(K) is False

bot.save_session = lambda *a, **k: None
bot._touch_update_card = lambda *a, **k: True
bot._fn_touch_final = lambda *a, **k: None
bot._fn_touch_created = lambda *a, **k: None
bot.latest_price = lambda sym: 100.0
bot._touch_eval_one = lambda chat_id, rec: None            # dir را خودمان تنظیم می‌کنیم

def mk(sym, d, status='waiting', age=0):
    now = time.time()
    return {'id': sym, 'symbol': sym, 'touch_sig': d, 'dir': d, 'status': status, 'created_at': now - age, 'expires_at': now + 1800, 'votes': []}

def load(buys, sells):
    s['touch_wait'] = {}
    for i in range(buys):
        r = mk(f'B{i}', 'BUY'); s['touch_wait'][r['id']] = r
    for i in range(sells):
        r = mk(f'S{i}', 'SELL'); s['touch_wait'][r['id']] = r

def st(prefix):
    return sorted(r['status'] for r in s['touch_wait'].values() if r['id'].startswith(prefix))

# ۱) کلید خاموش: هیچ اتفاقی نمی‌افتد
cfg[K] = False; load(3, 7)
assert bot._touch_bias_apply(CID, s) == [] and st('B') == ['waiting'] * 3

# ۲) ۷ فروش / ۳ خرید → خرید بلاک، فروش‌ها دست‌نخورده
cfg[K] = True; load(3, 7)
assert bot._touch_bias_verdict(s) == ('BUY', 3, 7)
out = bot._touch_bias_apply(CID, s)
assert len(out) == 3 and st('B') == ['bias_blocked'] * 3 and st('S') == ['waiting'] * 7
assert all('جهت بازار فروش' in r['bias_note'] and 'مانع جهت مخالف بازار' in r['bias_note'] for r in out)
# رد‌شده‌ها هنوز در شمارش می‌مانند (جهت بازار پایدار است)، و دوباره اجرا چیزی عوض نمی‌کند
assert bot._touch_bias_verdict(s) == ('BUY', 3, 7) and bot._touch_bias_apply(CID, s) == []
# لیست انتظار فقط فروش‌ها را می‌بیند
assert sorted(r['symbol'] for r in bot._touch_waiting_recs(s)) == sorted(f'S{i}' for i in range(7))

# ۳) متقارن: ۷ خرید / ۳ فروش → فروش بلاک
load(7, 3); bot._touch_bias_apply(CID, s)
assert st('S') == ['bias_blocked'] * 3 and st('B') == ['waiting'] * 7

# ۴) مرز: ۶ به ۴ بلاک نمی‌کند؛ ۷ به ۳ دقیقاً بلاک می‌کند
load(4, 6); assert bot._touch_bias_verdict(s)[0] is None and bot._touch_bias_apply(CID, s) == []
load(3, 7); assert bot._touch_bias_verdict(s)[0] == 'BUY'

# ۵) نمونه‌ی کم: ۱ به ۲ (کمتر از ۴ برخورد) بلاک نمی‌کند حتی اگر ۱۰۰٪ یک‌طرف باشد
load(0, 3); assert bot._touch_bias_verdict(s)[0] is None
load(0, 4); assert bot._touch_bias_verdict(s)[0] == 'BUY'

# ۶) منقضی‌شده‌ها و رکوردهای تمام‌شده (entered/queued/expired) شمرده نمی‌شوند
load(3, 7)
s['touch_wait']['S0']['expires_at'] = time.time() - 5
s['touch_wait']['S1']['status'] = 'queued'
assert bot._touch_bias_verdict(s) == (None, 3, 5)       # ۳ به ۵ = ۶۲٪ → بدون بلاک

# ۷) جهتِ نامشخص (dir=None) از جهت الگوی برخورد می‌آید؛ جهت کاملاً نامشخص شمرده نمی‌شود
load(3, 7)
for r in s['touch_wait'].values():
    r['dir'] = None
assert bot._touch_bias_verdict(s) == ('BUY', 3, 7)
s['touch_wait']['S2']['touch_sig'] = None
assert bot._touch_bias_verdict(s) == ('BUY', 3, 6)      # ۶۷٪ ≥ آستانه‌ی ۶۵٪ (V3.44.135)
s['touch_wait']['S3']['touch_sig'] = None
assert bot._touch_bias_verdict(s) == (None, 3, 5)       # ۶۲٫۵٪ < ۶۵٪ → غلبه ندارد

# ۸) ثبت برخورد تازه (مسیر واقعی _touch_register): جهت مخالفِ غالب ثبت نمی‌شود، جهت آزاد ثبت می‌شود
load(0, 6); s['touch_wait_seen'] = {}; s['paper_positions'] = []
reason = 'سناریو ۱ | HVL=100.0'
def fake_eval(chat_id, rec):
    rec['dir'] = rec['touch_sig']
bot._touch_eval_one = fake_eval
bot._touch_auto_enter = lambda chat_id, rec: False
status, txt = bot._touch_register(CID, 'NEWBUY', 'BUY', reason, '15min')
assert status == 'blocked' and 'جهت بازار فروش' in txt, (status, txt)
blocked_rec = [r for r in s['touch_wait'].values() if r['symbol'] == 'NEWBUY'][0]
assert blocked_rec['status'] == 'bias_blocked'
status, txt = bot._touch_register(CID, 'NEWSELL', 'SELL', reason, '15min')
assert status == 'touch_wait', (status, txt)
# کلید خاموش: همان ثبتِ خرید پذیرفته می‌شود (رفتار قبلی)
cfg[K] = False; s['touch_wait_seen'] = {}
status, txt = bot._touch_register(CID, 'NEWBUY2', 'BUY', reason, '15min'); assert status == 'touch_wait', (status, txt)
cfg[K] = True

# ۹) سد آخر در ورود خودکار: رکورد خلاف جهت غالب هرگز به صف تایید نمی‌رسد
load(0, 6)
r = mk('LATE', 'BUY'); r['auto_ok'] = True; s['touch_wait'][r['id']] = r
called = {'fav': 0}
bot._fav_confirm_hold = lambda *a, **k: called.__setitem__('fav', called['fav'] + 1) or True
bot.exchange_latest_price = lambda c, sy: 100.0
s['is_bot_active'] = True; s['daily_stopped'] = False
res = bot._touch_auto_enter_core(CID, r)
assert res is False and r['status'] == 'bias_blocked' and called['fav'] == 0, (res, r['status'])

# ۱۰) تیک: ترکیب لیست عوض شد → جهت مخالفِ جدید رد می‌شود
load(7, 3)
bot._touch_bias_apply(CID, s)            # فروش‌ها (۳) بلاک
assert st('S') == ['bias_blocked'] * 3
for i in range(7):                       # ۷ خرید تمام می‌شوند؛ ۲ برخورد تازه‌ی فروش و ۱ خرید اضافه می‌شود
    s['touch_wait'][f'B{i}']['status'] = 'expired'
for sy, d in (('N1', 'SELL'), ('N2', 'SELL'), ('N3', 'SELL'), ('N4', 'BUY')):
    s['touch_wait'][sy] = mk(sy, d)
bot._touch_wait_loop  # وجود دارد
bot._touch_tick(CID)
# شمارش: رد‌شده‌های قبلی (۳ فروش) + ۳ فروش تازه = ۶ فروش، ۱ خرید → خرید بلاک
assert s['touch_wait']['N4']['status'] == 'bias_blocked' and s['touch_wait']['N1']['status'] == 'waiting'

# ۱۱) نمایش لیست: خط جهت بازار برای ادمین
sent = []
bot.send_message = lambda chat_id, text, markup=None, message_id=None, **k: sent.append(text) or True
bot.is_restricted_user = lambda c: False
load(3, 7)
bot.assist_pending_list(CID)
assert sent and 'جهت بازار: فروش' in sent[-1] and 'جهت خرید بلاک است' in sent[-1] and 'فشار' not in sent[-1] and '📊' not in sent[-1], sent[-1][:400]   # V3.44.137: خط 🚦 برگشت، 📊 و فشار بازار حذف‌شده
cfg[K] = False; sent.clear(); bot.assist_pending_list(CID)
assert 'جهت بازار' not in sent[-1]
print('touch_bias_selftest ALL OK')
