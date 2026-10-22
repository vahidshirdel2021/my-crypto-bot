"""V3.44.53: محافظ BTC (بستن بخشی + استاپ سر به سر وقتی BTC به سطح واکنش تاییدشده نشان می‌دهد)."""
import os, time, logging
from threading import RLock
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()
a = src.index("# ===== V3.44.53: محافظ BTC")
b = src.index("# ===== END btc guard =====")
sent, partials = [], []
S = {}
state = {'info': None, 'vote': (None, ''), 'price': {}, 'vote_calls': 0}
def side_long(side): return 'BUY' in str(side).upper() or 'LONG' in str(side).upper()
def _be_state(p, price):
    rd = float(p.get('risk_distance') or abs(float(p['entry_price']) - float(p['sl'])))
    mv = ((price - p['entry_price']) if side_long(p['side']) else (p['entry_price'] - price)) / rd
    return mv, mv, 0.0
def partial(chat_id, p, price, frac, label=''):
    partials.append((p['symbol'], frac, label)); p['margin'] = p['margin'] * (1 - frac); return True
def vote_fn(tf, cfg=None):
    state['vote_calls'] += 1; return state['vote']
g = {'os': os, 'time': time, 'RLock': RLock, 'logger': logging.getLogger('t'), 'TAKER_FEE_PCT': 0.05, 'side_long': side_long,
     'USER_SESSIONS': S, 'fmt': lambda x: f'{float(x):g}', '_be_state': _be_state, 'partial_close_position': partial,
     'get_entry_lock': lambda c: RLock(), 'save_session': lambda c: None, '_btc_pattern_vote': vote_fn,
     'send_message': lambda c, tx, *a, **k: sent.append(tx), 'latest_price': lambda sym: state['price'].get(sym),
     'exchange_latest_price': lambda c, sym: state['price'].get(sym),
     'btc_front_level_info': lambda s, tf, is_long: state['info']}
exec(src[a:b], g)
scan, WATCH = g['btc_guard_scan_once'], g['_BTC_GUARD_WATCH']

def short(sym='AAA', entry=100.0, sl=102.0, **kw):
    return {'symbol': sym, 'side': 'SELL', 'entry_price': entry, 'sl': sl, 'risk_distance': abs(sl - entry), 'margin': 100.0, **kw}
def long_(sym='BBB', entry=100.0, sl=98.0, **kw):
    return {'symbol': sym, 'side': 'BUY', 'entry_price': entry, 'sl': sl, 'risk_distance': abs(sl - entry), 'margin': 100.0, **kw}
def setup(positions, **sk):
    S.clear(); S[1] = {'paper_positions': positions, 'btc_guard_enabled': True, **sk}
    sent.clear(); partials.clear(); WATCH.clear(); state.update(info=None, vote=(None, ''), vote_calls=0)

NEAR = {'front_price': 81859.0, 'dist_atr': 0.5}
FAR = {'front_price': 81859.0, 'dist_atr': 3.0}

# ۱) فروش در سود ۰٫۸R، BTC نزدیک حمایت، واکنش خرید تاییدشده ⇒ ۵۰٪ بسته + SL سر به سر (کمی زیر ورود)
p = short(); setup([p]); state['price']['AAA'] = 99.2; state['info'] = NEAR; state['vote'] = ('BUY', 'BTC: خرید (شکست کاذب)')
scan()
assert partials == [('AAA', 0.5, 'محافظ BTC')], partials
assert p['btc_guard_done'] and p['btc_guard']['sl_moved'] and p['btc_guard']['r_at_trigger'] == 0.4
assert 99.8 < p['sl'] < 100.0, p['sl']               # ورود ۱۰۰ منهای پوشش کارمزد
assert p['sl_initial'] == 102.0
assert any('حالت مراقبت' in m for m in sent) and any('محافظ BTC' in m and 'بسته شد' in m for m in sent), sent
n = len(partials); scan(); assert len(partials) == n, 'برای هر معامله فقط یک‌بار'

# ۲) غیرسودی: هیچ‌کاری نمی‌کند ولی بعداً که سودده شد می‌تواند اجرا شود
p = short(); setup([p]); state['price']['AAA'] = 100.5; state['info'] = NEAR; state['vote'] = ('BUY', 'x')
scan(); assert not partials and not p.get('btc_guard_done') and p['sl'] == 102.0
state['price']['AAA'] = 99.0; scan(); assert partials and p['btc_guard_done']
# ۳) سود کمتر از حداقل (۰٫۳R)
p = short(); setup([p]); state['price']['AAA'] = 99.7; state['info'] = NEAR; state['vote'] = ('BUY', 'x'); scan(); assert not partials
# ۴) واکنش تایید نشده (None) یا هم‌جهت با معامله (SELL برای فروش)
for v in (None, 'SELL'):
    p = short(); setup([p]); state['price']['AAA'] = 99.0; state['info'] = NEAR; state['vote'] = (v, ''); scan(); assert not partials and not p.get('btc_guard_done')
# ۵) BTC دور از سطح و مراقبت هیچ‌وقت روشن نشده: نه اقدام، نه حتی خواندن الگوی BTC
p = short(); setup([p]); state['price']['AAA'] = 99.0; state['info'] = FAR; state['vote'] = ('BUY', 'x'); scan()
assert not partials and state['vote_calls'] == 0
# ۶) مراقبت می‌چسبد: اول نزدیک، بعد که BTC دور شد (کندل واکنش) هنوز در پنجره‌ی مراقبت است
p = short(); setup([p]); state['price']['AAA'] = 100.2; state['info'] = NEAR; state['vote'] = (None, ''); scan()   # مراقبت روشن، معامله منفی
alerts = [m for m in sent if 'حالت مراقبت' in m]; assert len(alerts) == 1
state['info'] = FAR; state['price']['AAA'] = 99.0; state['vote'] = ('BUY', 'BTC: خرید'); scan()
assert partials, 'مراقبتِ قبلی باید هنوز فعال باشد'
assert len([m for m in sent if 'حالت مراقبت' in m]) == 1, 'هشدار مراقبت تکراری نیاید'
# ۷) پنجره‌ی مراقبت تمام شده ⇒ اقدام نه
p = short(); setup([p]); state['price']['AAA'] = 99.0; state['info'] = FAR; state['vote'] = ('BUY', 'x')
WATCH['short'] = {'ts': time.time() - 3 * 3600, 'alerted': set()}; scan(); assert not partials
# ۸) خرید: متقارن (BTC نزدیک مقاومت، واکنش فروش)
p = long_(); setup([p]); state['price']['BBB'] = 100.8; state['info'] = {'front_price': 90000.0, 'dist_atr': 0.4}; state['vote'] = ('SELL', 'BTC: فروش (برگشت)')
scan(); assert partials == [('BBB', 0.5, 'محافظ BTC')] and 100.0 < p['sl'] < 100.2, (partials, p['sl'])
# ۹) سهم بستن ۷۵٪
p = short(); setup([p], btc_guard_frac=0.75); state['price']['AAA'] = 99.0; state['info'] = NEAR; state['vote'] = ('BUY', 'x'); scan(); assert partials[0][1] == 0.75
# ۱۰) REAL و کلید خاموش و قبلاً اجرا‌شده
p = short(is_real=True); setup([p]); state['price']['AAA'] = 99.0; state['info'] = NEAR; state['vote'] = ('BUY', 'x'); scan(); assert not partials
p = short(); setup([p], btc_guard_enabled=False); state['price']['AAA'] = 99.0; state['info'] = NEAR; state['vote'] = ('BUY', 'x'); scan(); assert not partials
# ۱۱) SL قبلاً (مثلاً تریلینگ) از سر به سر بهتر است: دست نمی‌خورد ولی بخشی بسته می‌شود
p = short(sl=99.5); p['risk_distance'] = 2.0; setup([p]); state['price']['AAA'] = 98.5; state['info'] = NEAR; state['vote'] = ('BUY', 'x'); scan()
assert partials and p['sl'] == 99.5 and p['btc_guard']['sl_moved'] is False
# ۱۲) دو معامله‌ی فروش، یکی سودده یکی ضررده: فقط سودده
p1 = short('AAA'); p2 = short('CCC'); setup([p1, p2]); state['price'].update(AAA=99.0, CCC=101.0); state['info'] = NEAR; state['vote'] = ('BUY', 'x'); scan()
assert [x[0] for x in partials] == ['AAA'] and not p2.get('btc_guard_done')
print('btc_guard_selftest OK')
