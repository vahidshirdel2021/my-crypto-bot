"""V3.44.134: بررسی دوباره‌ی جهت غالب بازار در خروج از «صف تایید حرکت». اجرا: python3 fav_dominance_selftest.py"""
import sys, types, os, tempfile, time
import pandas as pd
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
assert bot.BOT_VERSION == '3.44.134'

CID = 111
s = bot.get_session(CID)
cfg = s.setdefault('strategy_config', {})
KB, KN = 'gate_touch_bias_block_enabled', 'gate_touch_need_dominant_enabled'
for k in list(bot.GATE_REGISTRY):
    if k.startswith('gate_') and k not in (KB, KN):
        cfg[k] = False              # فقط گیت جدید را می‌سنجیم
s['is_bot_active'] = True; s['paper_positions'] = []; s['timeframe'] = '15min'; s['trading_mode'] = 'PAPER'; s['fav_confirm_enabled'] = True

bot.save_session = lambda *a, **k: None
bot._fav_update_card = lambda *a, **k: True
bot._fn_fav_final = lambda *a, **k: None
bot._touch_update_card = lambda *a, **k: True
bot._fn_touch_final = lambda *a, **k: None
bot._fav_flip_to_touch = lambda *a, **k: None
bot.latest_price = lambda sym: 100.3
bot.exchange_latest_price = lambda c, sy: 100.3
bot.btc_daily_enabled = lambda s: False
bot.btc_undecided_enabled = lambda c, s=None: False
bot._btc_front_flags = lambda s: (False, False)
bot._auto_trend_gate = lambda *a, **k: False
calls = []
bot.execute_trade = lambda *a, **k: (calls.append(a[1]) or True)
now = time.time()
def klines(sym, tf, n):
    return pd.DataFrame([{'timestamp': now - 3000, 'close': 100.0, 'open': 100, 'high': 100, 'low': 100},
                         {'timestamp': now - 200, 'close': 100.3, 'open': 100, 'high': 101, 'low': 100},     # کلوز +0.3R بعد از سیگنال
                         {'timestamp': now + 600, 'close': 100.3, 'open': 100, 'high': 101, 'low': 100}])
bot.get_klines = klines

def mtouch(sym, d, status='waiting'):
    return {'id': sym, 'symbol': sym, 'touch_sig': d, 'dir': d, 'status': status, 'created_at': now, 'expires_at': now + 1800, 'votes': []}
def load(buys, sells):
    s['touch_wait'] = {}
    for i in range(buys):
        r = mtouch(f'B{i}', 'BUY'); s['touch_wait'][r['id']] = r
    for i in range(sells):
        r = mtouch(f'S{i}', 'SELL'); s['touch_wait'][r['id']] = r

def queue(sym='COMP', sig='BUY', expires=None):
    s['fav_wait'] = {}; s.pop('fav_wait_seen', None)
    assert bot._fav_confirm_hold(CID, sym, sig, {'rr': 2.0}, 100.0, 99.0 if sig == 'BUY' else 101.0, 102.0 if sig == 'BUY' else 98.0, 'r') is True
    rec = list(s['fav_wait'].values())[0]; rec['created_at'] = now - 400
    if expires is not None:
        rec['expires_at'] = now + expires
    return rec

# --- تابع گیت ---
cfg[KB] = True; cfg[KN] = False
load(1, 3); assert bot._touch_bias_verdict(s)[0] == 'BUY'              # مثل عکس: ۱ خرید / ۳ فروش → خرید بلاک
ok, txt = bot._fav_dominance_gate(s, 'BUY'); assert not ok and 'جهت بازار فروش است' in txt and '1 خرید / 3 فروش' in txt, txt
assert bot._fav_dominance_gate(s, 'SELL')[0] is True
load(1, 1)                                                              # بدون غلبه: فقط با کلید دوم نگه می‌دارد
assert bot._fav_dominance_gate(s, 'BUY')[0] is True
cfg[KN] = True
ok, txt = bot._fav_dominance_gate(s, 'BUY'); assert not ok and 'مشخص نیست' in txt, txt
cfg[KB] = False; cfg[KN] = False
load(1, 3); assert bot._fav_dominance_gate(s, 'BUY')[0] is True          # هر دو خاموش = رفتار قبلی

# --- جریان صف: خرید داخل صف، غلبه‌ی فروش → ورود نمی‌شود و در صف می‌ماند ---
cfg[KB] = True; load(1, 3); calls.clear()
rec = queue(); bot._fav_process_one(CID, s, rec)
assert rec['status'] == 'waiting' and not calls and rec.get('domin_blocked') and 'جهت بازار فروش است' in rec['domin_hold'], (rec['status'], calls, rec.get('domin_hold'))
assert rec['hold_ticks']['domin']['n'] == 1
card = bot._fav_card_payload(rec); card = card[0] if isinstance(card, tuple) else card
assert 'جهت بازار فروش است' in str(card)
bot._fav_process_one(CID, s, rec)                                       # تیک بعدی هم همان را می‌سنجد
assert rec['status'] == 'waiting' and not calls and rec['hold_ticks']['domin']['n'] == 2

# غلبه برگشت (۳ خرید / ۱ فروش) → همین رکورد وارد می‌شود
load(3, 1); bot._fav_process_one(CID, s, rec)
assert rec['status'] == 'opened' and calls == ['COMP'] and not rec.get('domin_blocked'), (rec['status'], calls)

# جهت هم‌سو با غلبه (فروش در بازار فروش) بدون مانع وارد می‌شود
load(1, 3); calls.clear()
rec = queue('SOLX', 'SELL')
bot.get_klines = lambda sym, tf, n: pd.DataFrame([{'timestamp': now - 3000, 'close': 100.0, 'open': 100, 'high': 100, 'low': 100},
                                                  {'timestamp': now - 200, 'close': 99.7, 'open': 100, 'high': 100, 'low': 99},
                                                  {'timestamp': now + 600, 'close': 99.7, 'open': 100, 'high': 100, 'low': 99}])
bot.latest_price = lambda sym: 99.7; bot.exchange_latest_price = lambda c, sy: 99.7
bot._fav_process_one(CID, s, rec); assert rec['status'] == 'opened' and calls == ['SOLX'], (rec['status'], calls)

# پایان مهلت وقتی هنوز بلاک است: منقضی با دلیل dominance
bot.get_klines = klines; bot.latest_price = lambda sym: 100.3; bot.exchange_latest_price = lambda c, sy: 100.3
load(1, 3); calls.clear(); rec = queue(expires=-5)
bot._fav_process_one(CID, s, rec)
assert rec['status'] == 'expired' and rec['why'] == 'dominance' and not calls, (rec['status'], rec.get('why'))
print('fav_dominance_selftest ALL OK')
