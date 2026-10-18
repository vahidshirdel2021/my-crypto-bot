"""تست آفلاین کلید «رژیم بازار در مرحله‌ی آخر ورود». اجرا: python final_regime_selftest.py"""
import os, time, logging
import pandas as pd
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()

# --- ۱) حکم خالص رژیم ---
a = src.index("_FINAL_REGIME_FA = "); b = src.index("def _final_regime_check(")
g0 = {}
exec(src[a:b], g0)
v = g0['_final_regime_verdict']
assert v('BULLISH', 'BUY')[0] and v('BEARISH', 'SELL')[0]
for gate in ('BEARISH', 'RANGE', None):
    assert not v(gate, 'BUY')[0], gate
for gate in ('BULLISH', 'RANGE', None):
    assert not v(gate, 'SELL')[0], gate
print(v('BEARISH', 'BUY')[1]); print(v('RANGE', 'SELL')[1])

# --- ۲) رفتار در خروج از صف تایید حرکت (_fav_process_one) ---
a = src.index("def _fav_move_r("); b = src.index("FAV_CARDS_PER_LIST =")
S = {'cfg': {'gate_final_regime_enabled': True}, 'paper_positions': [], 'trading_mode': 'PAPER'}
calls = {'exec': 0, 'flip': 0, 'regime': 'RANGE', 'finish': []}
now0 = time.time()
rows = [{'timestamp': now0 - 120, 'close': 100.0}, {'timestamp': now0 - 60, 'close': 100.8}, {'timestamp': now0, 'close': 100.8}]
g = dict(os=os, logger=logging.getLogger('t'), time=time, FAV_CONFIRM_MIN_RR=0.0, FAV_CONFIRM_CANCEL_R=1.0, FAV_REVERSE_TO_TOUCH=True,
         _FAV_FLIP_TAG='x', _TF_SECONDS={'5min': 300}, _LAST_BLOCK_REASON={}, hashlib=__import__('hashlib'),
         exchange_latest_price=lambda c, s: 100.8, latest_price=lambda s: 100.8,
         get_klines=lambda sym, tf, n: pd.DataFrame(rows),
         get_session=lambda c: S, save_session=lambda c: None, _fav_update_card=lambda *a, **k: None,
         gate_on=lambda s, k: bool(S['cfg'].get(k, False)),
         _final_regime_check=lambda tf, sig: g['_final_regime_verdict'](calls['regime'], sig),
         execute_trade=lambda *a, **k: (calls.__setitem__('exec', calls['exec'] + 1) or True),
         _auto_trend_gate=lambda *a, **k: False, _assist_queue_signal=lambda *a, **k: 'ok',
         _touch_register=lambda *a, **k: (calls.__setitem__('flip', calls['flip'] + 1) or ('touch_wait', 'x')))
exec(src[src.index("_FINAL_REGIME_FA = "):src.index("def _final_regime_check(")], g)
exec(src[a:b], g)
g['_final_regime_check'] = lambda tf, sig: g['_final_regime_verdict'](calls['regime'], sig)   # جایگزین نسخه‌ی شبکه‌ای

def mk(expires=600):
    return {'id': 'r1', 'symbol': 'AAA', 'sig': 'BUY', 'side_label': 'BUY (Long)', 'entry': 100.0, 'sl': 98.0, 'tp': 110.0,
            'reason': 'r', 'tf': '5min', 'min_r': 0.3, 'max_r': 1.0, 'created_at': now0 - 200, 'expires_at': now0 + expires,
            'last_eval_ts': 0.0, 'status': 'waiting'}

# رنج: سیگنال باید در صف بماند (نه معامله، نه حذف)
r = mk(); calls.update(exec=0, regime='RANGE')
g['_fav_process_one'](1, S, r)
assert r['status'] == 'waiting' and calls['exec'] == 0 and 'رنج' in r['regime_hold'], r
# رژیم قطعاً نزولی (خلاف خرید): باز هم صبر
calls['regime'] = 'BEARISH'; g['_fav_process_one'](1, S, r)
assert r['status'] == 'waiting' and calls['exec'] == 0 and 'نزولی' in r['regime_hold']
# رژیم به نفع معامله شد: همان تیک بعدی وارد می‌شود
calls['regime'] = 'BULLISH'; g['_fav_process_one'](1, S, r)
assert r['status'] == 'opened' and calls['exec'] == 1 and not r.get('regime_blocked'), r
# مهلت تمام می‌شود و رژیم هرگز موافق نشده: بدون ورود، بدون برعکس‌شدن، علت = regime
r = mk(expires=-1); calls.update(exec=0, flip=0, regime='RANGE')
g['_fav_process_one'](1, S, r)
assert r['status'] == 'expired' and r['why'] == 'regime' and calls['exec'] == 0 and calls['flip'] == 0, r
# فروش در رژیم نزولی مجاز است
r = mk(); r.update(sig='SELL', side_label='SELL (Short)', entry=100.0, sl=102.0, tp=90.0)
rows[1]['close'] = rows[2]['close'] = 99.2; g['exchange_latest_price'] = g['latest_price'] = lambda *a: 99.2
calls.update(exec=0, regime='BEARISH'); g['_fav_process_one'](1, S, r)
assert r['status'] == 'opened' and calls['exec'] == 1, r
# کلید خاموش: رفتار قبلی (رژیم نادیده گرفته می‌شود)
S['cfg']['gate_final_regime_enabled'] = False
r = mk(); rows[1]['close'] = rows[2]['close'] = 100.8; g['exchange_latest_price'] = g['latest_price'] = lambda *a: 100.8
calls.update(exec=0, regime='RANGE'); g['_fav_process_one'](1, S, r)
assert r['status'] == 'opened' and calls['exec'] == 1, r

# --- ۳) ورود سریع دستی (رأی کاربر) از کلید عبور می‌کند؛ کلید پیش‌فرض خاموش و در منوی «شرایط ورود» است ---
fq = src[src.index("def fav_quick_entry("):src.index("def fav_queue_list(")]
assert '_final_regime' not in fq and 'gate_final_regime' not in fq
i = src.index("'gate_final_regime_enabled': ("); assert "False, 'entry_rules'" in src[i:i + 260]
print('ALL OK')
