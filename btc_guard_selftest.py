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
# ۱۰) پوزیشن REAL در جلسه‌ی غیر REAL (ناسازگار) نادیده گرفته می‌شود؛ کلید خاموش؛ (REAL واقعی در بخش ۱۳)
p = short(is_real=True); setup([p]); state['price']['AAA'] = 99.0; state['info'] = NEAR; state['vote'] = ('BUY', 'x'); scan(); assert not partials
p = short(); setup([p], btc_guard_enabled=False); state['price']['AAA'] = 99.0; state['info'] = NEAR; state['vote'] = ('BUY', 'x'); scan(); assert not partials
# ۱۱) SL قبلاً (مثلاً تریلینگ) از سر به سر بهتر است: دست نمی‌خورد ولی بخشی بسته می‌شود
p = short(sl=99.5); p['risk_distance'] = 2.0; setup([p]); state['price']['AAA'] = 98.5; state['info'] = NEAR; state['vote'] = ('BUY', 'x'); scan()
assert partials and p['sl'] == 99.5 and p['btc_guard']['sl_moved'] is False
# ۱۲) دو معامله‌ی فروش، یکی سودده یکی ضررده: فقط سودده
p1 = short('AAA'); p2 = short('CCC'); setup([p1, p2]); state['price'].update(AAA=99.0, CCC=101.0); state['info'] = NEAR; state['vote'] = ('BUY', 'x'); scan()
assert [x[0] for x in partials] == ['AAA'] and not p2.get('btc_guard_done')

# ---------------- V3.44.54: REAL ----------------
real_calls = {'partial': [], 'sl': [], 'sl_ok': True, 'partial_ok': True}
def real_partial(chat_id, p, price, frac, label=''):
    real_calls['partial'].append((p['symbol'], frac, label)); return real_calls['partial_ok']
def real_move_sl(chat_id, symbol, sl):
    real_calls['sl'].append((symbol, sl)); return (True, 'OK') if real_calls['sl_ok'] else (False, 'boom')
g['partial_close_real_position'] = real_partial; g['move_stop_loss'] = real_move_sl
g['normalize_price'] = lambda c, sym, px: round(float(px), 2)
def setup_real(positions, **sk):
    setup(positions, trading_mode='REAL', **sk); real_calls.update(partial=[], sl=[], sl_ok=True, partial_ok=True)

# ۱۳) REAL: خرید در سود، BTC نزدیک مقاومت، واکنش فروش ⇒ بستن بخشی reduce-only + انتقال SL روی صرافی؛ paper دست نمی‌خورد
p = long_(is_real=True); setup_real([p]); state['price']['BBB'] = 100.8; state['info'] = {'front_price': 90000.0, 'dist_atr': 0.4}; state['vote'] = ('SELL', 'BTC: فروش')
scan()
assert real_calls['partial'] == [('BBB', 0.5, 'محافظ BTC')] and not partials, (real_calls, partials)
assert len(real_calls['sl']) == 1 and real_calls['sl'][0][0] == 'BBB' and 100.0 < real_calls['sl'][0][1] < 100.2, real_calls
assert p['btc_guard_done'] and p['btc_guard']['sl_moved'] and p['btc_guard']['partial_ok'] and p['sl'] == real_calls['sl'][0][1] and p['sl_initial'] == 98.0
n = len(real_calls['partial']); scan(); assert len(real_calls['partial']) == n, 'REAL هم فقط یک‌بار'
# ۱۴) REAL: جابه‌جایی SL روی صرافی شکست بخورد ⇒ p['sl'] تغییر نکند، هشدار صریح؛ بستن بخشی همچنان انجام شود
p = long_(is_real=True); setup_real([p]); real_calls['sl_ok'] = False; state['price']['BBB'] = 100.8; state['info'] = {'front_price': 90000.0, 'dist_atr': 0.4}; state['vote'] = ('SELL', 'x')
scan(); assert p['sl'] == 98.0 and p['btc_guard']['sl_failed'] and not p['btc_guard']['sl_moved'] and real_calls['partial'], p
assert any('ناموفق بود' in m and 'Binance' in m for m in sent), sent
# ۱۵) REAL: بستن بخشی شکست بخورد ⇒ SL همچنان سر به سر می‌شود و پیام «ممکن نبود»
p = long_(is_real=True); setup_real([p]); real_calls['partial_ok'] = False; state['price']['BBB'] = 100.8; state['info'] = {'front_price': 90000.0, 'dist_atr': 0.4}; state['vote'] = ('SELL', 'x')
scan(); assert p['btc_guard']['sl_moved'] and not p['btc_guard']['partial_ok'] and any('بستن بخشی ممکن نبود' in m for m in sent)
# ۱۶) جلسه‌ی REAL: پوزیشن کاغذیِ باقی‌مانده نادیده گرفته می‌شود
pp = long_(); setup_real([pp]); state['price']['BBB'] = 100.8; state['info'] = {'front_price': 90000.0, 'dist_atr': 0.4}; state['vote'] = ('SELL', 'x'); scan()
assert not real_calls['partial'] and not partials and not pp.get('btc_guard_done')
# ۱۷) REAL: غیرسودی/واکنش تاییدنشده/کلید خاموش ⇒ هیچ سفارشی به صرافی نمی‌رود
p = long_(is_real=True); setup_real([p]); state['price']['BBB'] = 99.5; state['info'] = {'front_price': 90000.0, 'dist_atr': 0.4}; state['vote'] = ('SELL', 'x'); scan(); assert not real_calls['partial'] and not real_calls['sl']
p = long_(is_real=True); setup_real([p], btc_guard_enabled=False); state['price']['BBB'] = 100.8; state['info'] = {'front_price': 90000.0, 'dist_atr': 0.4}; state['vote'] = ('SELL', 'x'); scan(); assert not real_calls['partial']

# ---------------- partial_close_real_position (واحد، با صرافی جعلی) ----------------
a2 = src.index("def partial_close_real_position"); b2 = src.index("\n\n# ===================== V3.43.27")
class ExchangeStateError(Exception): pass
class Ex:
    def __init__(s): s.orders = []
    def amount_to_precision(s, sym, a): return f'{float(a):.3f}'
    def create_order(s, *a, **k): s.orders.append((a, k)); return {'id': '1', 'average': 101.0, 'filled': a[3]}
EX = Ex(); POS = {'amt': 10.0}
class FakeTime:
    def sleep(s, x): pass
    def time(s): return time.time()
MKT = {'limits': {'amount': {'min': 0.001}, 'cost': {'min': 5.0}}}
def run_real(pos, mkt=MKT, live_after=None, live=None, ex=EX):
    EX.orders.clear()
    seq = [live if live is not None else {'amount': POS['amt']}]
    after = live_after if live_after is not None else {'amount': POS['amt'] * 0.5}
    calls = {'n': 0}
    def find(chat_id, sym):
        calls['n'] += 1
        return seq[0] if calls['n'] == 1 else after
    g3 = {'time': FakeTime(), 'logger': logging.getLogger('t3'), 'TAKER_FEE_PCT': 0.05, 'side_long': side_long, 'ExchangeStateError': ExchangeStateError,
          'get_entry_lock': lambda c: RLock(), 'get_session': lambda c: {'paper_positions': [pos]}, 'get_exchange': lambda c: ex,
          '_fsym': lambda e, sym: ('X/USDT:USDT', 1, mkt), 'find_position': find, 'save_session': lambda c: None, 'audit_event': lambda *a, **k: None,
          'new_trade_id': lambda c, s: 't1',
          '_close_market': lambda e, sym, is_long, contracts: e.create_order(sym, 'market', 'sell' if is_long else 'buy', float(e.amount_to_precision(sym, contracts)), None, {'reduceOnly': True}),
          '_order_avg_price': lambda e, sym, order: float(order.get('average') or 0)}
    exec(src[a2:b2], g3)
    return g3['partial_close_real_position']('c', pos, 101.0, 0.5, 'محافظ BTC')
rp = {'symbol': 'X', 'side': 'BUY (Long)', 'is_real': True, 'entry_price': 100.0, 'margin': 20.0, 'amount': 10.0, 'leverage': 5}
assert run_real(rp) is True
assert len(EX.orders) == 1
assert EX.orders[0][0][2] == 'sell' and EX.orders[0][0][3] == 5.0 and EX.orders[0][0][5]['reduceOnly'] is True, EX.orders
assert rp['amount'] == 5.0 and abs(rp['margin'] - 10.0) < 1e-9 and rp['orig_amount'] == 10.0 and rp['orig_margin'] == 20.0
assert rp['partial_exits'][0]['real'] is True and 'pnl_usdt' not in rp['partial_exits'][0] and 'partial_pnl_usdt' not in rp   # PnL واقعی از صرافی می‌آید، دوباره جمع نشود
assert abs(rp['partial_real_gross_est_usdt'] - 5.0) < 1e-9 and rp['partial_real_est_usdt'] < 5.0
# شورت: جهت سفارش buy
rs = {'symbol': 'X', 'side': 'SELL (Short)', 'is_real': True, 'entry_price': 100.0, 'margin': 20.0, 'amount': 10.0, 'leverage': 5}
assert run_real(rs) and EX.orders[0][0][2] == 'buy'
# رد می‌شود: غیر REAL، حجم ریز، حداقل نماد، پوزیشن روی صرافی نیست
assert run_real({**rp, 'is_real': False}) is False and not EX.orders
tiny = {**rp, 'amount': 0.004}; POS['amt'] = 0.004
assert run_real(dict(tiny), mkt={'limits': {'amount': {'min': 0.01}, 'cost': {'min': 5.0}}}) is False and not EX.orders
POS['amt'] = 10.0
assert run_real(dict(rp), mkt={'limits': {'amount': {'min': 0.001}, 'cost': {'min': 600.0}}}) is False and not EX.orders   # ارزش باقی‌مانده کمتر از حداقل
class ExBoom(Ex):
    def create_order(s, *a, **k): raise RuntimeError('rejected')
r3 = {'symbol': 'X', 'side': 'BUY (Long)', 'is_real': True, 'entry_price': 100.0, 'margin': 20.0, 'amount': 10.0, 'leverage': 5}
assert run_real(r3, ex=ExBoom()) is False and r3['amount'] == 10.0 and 'partial_exits' not in r3   # سفارش رد شود ⇒ هیچ حالتی عوض نمی‌شود
print('btc_guard_selftest OK (REAL included)')
