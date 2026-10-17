"""V3.44.14: تست رأی‌گیری فیلترها بعد از برخورد با سطح (بدون نیاز به اجرای ربات)."""
import re, time, os, hashlib, logging
from threading import RLock
import pandas as pd
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()
a = src.index('TOUCH_AUTO_MODES = (')
b = src.index('# END V3.44.14')
block = src[a:b]
sent, calls = [], []
S = {'paper_positions': [], 'timeframe': '5min', 'trading_mode': 'PAPER', 'is_bot_active': True, 'daily_stopped': False,
     'assist_expiry_seconds': 900, 'touch_auto_mode': 'all', 'traded_levels': {}, 'strategy_config': {}}
ON = {f'gate_fc_{k}_enabled': True for k in ('btceth', 'h4', 'tf', 'rsi', 'macd', 'adx', 'level', 'vol')}
st = {'h4': 'BEARISH', 'tf': {'5min': 'BEARISH', '15min': 'BEARISH'}, 'btc': -2, 'eth': -1,
      'row': {'rsi': 40, 'macd_hist': -1.0, 'adx': 30, 'plus_di': 10, 'minus_di': 25, 'volume_ratio': 2.0, 'close': 99.0},
      'exec_ok': True}


class Row(dict):
    def to_dict(self): return dict(self)


class DF:
    def __init__(self, r): self.r = r
    empty = False
    def __len__(self): return 10
    @property
    def iloc(self):
        r = self.r
        class I:
            def __getitem__(s, i): return Row(r)
        return I()


def bias(row):
    out, raw = {'rsi': None, 'macd': None, 'adx': None}, {}
    if row.get('rsi') is not None:
        raw['rsi'] = row['rsi']; out['rsi'] = 'SELL' if row['rsi'] <= 45 and row['rsi'] > 30 else ('BUY' if row['rsi'] >= 55 else None)
    raw['macd'] = row['macd_hist']; out['macd'] = 'BUY' if row['macd_hist'] > 0 else 'SELL'
    raw['adx'] = row['adx']; out['adx'] = 'SELL' if row['minus_di'] > row['plus_di'] else 'BUY'
    return out, raw


g = dict(re=re, time=time, hashlib=hashlib, pd=pd, RLock=RLock, logger=logging.getLogger('t'),
         get_session=lambda c: S, save_session=lambda c: None, gate_on=lambda s, k: ON.get(k, k in ('gate_touch_vote_enabled', 'gate_touch_pattern_vote_enabled')),
         extract_setup_level=lambda r: ('t', 'HVL', '100.0'), extract_scenario_tag=lambda r: '1', ASSIST_SEEN_TTL_SECONDS=21600,
         _trend_snapshot_cached=lambda sym, tf: {'score': st['btc'] if sym == 'BTC' else st['eth']},
         _symbol_h4_regime=lambda sym: st['h4'], _symbol_tf_regimes=lambda sym: dict(st['tf']), _TFR_TIMEFRAMES=('5min', '15min'),
         TF_DISPLAY={'5min': '۵ دقیقه', '15min': '۱۵ دقیقه'}, get_klines=lambda *a: DF(st['row']), calculate_indicators=lambda d: d,
         _single_indicator_biases=bias, FULL_CONFIRM_MIN_VOLUME_RATIO=1.5, fmt=lambda v: str(v),
         _assist_describe_source=lambda reason, tok, val, scn: (f'{tok} = {val}', f'{scn} - تست'),
         tradingview_chart_url=lambda sym, tf: f'https://tv/{sym}', _from_signal_origin=lambda f: f,
         exchange_latest_price=lambda c, s_: 100.0, latest_price=lambda s_: 100.0, _LAST_BLOCK_REASON={},
         build_quick_plan_with_fallback=lambda sym, side, cfg, live, tf: ({'sl': 101.0, 'tp': 98.0, 'rr': 2.0, 'reason': 'q', 'tp_level_name': 'x'}, None),
         execute_trade=lambda *a, **k: (calls.append((a, k)) or st['exec_ok']),
         quick_channel_trade=lambda *a, **k: calls.append(('quick', a, k)), send_message=lambda c, t, *a, **k: sent.append(t), USER_SESSIONS={})
exec(block, g)
V, SM = g['_touch_votes'], g['_touch_summarize']


def mk(votes):
    return [{'key': k, 'label': k, 'vote': v, 'detail': ''} for k, v in votes]


# --- جمع‌بندی آرا ---
r = SM(mk([('h4', 'SELL'), ('tf', 'SELL'), ('rsi', 'SELL'), ('macd', 'SELL'), ('adx', None)]), 'all')
assert (r['dir'], r['agree'], r['total'], r['auto_ok']) == ('SELL', 4, 5, False), r      # ۴ از ۵: خودکار نه
assert SM(mk([('h4', 'SELL'), ('tf', 'SELL'), ('rsi', 'SELL'), ('macd', 'SELL'), ('adx', None)]), 'minus1')['auto_ok']
v = mk([('h4', 'BUY'), ('tf', 'BUY'), ('rsi', 'BUY'), ('macd', 'SELL'), ('adx', 'SELL')])
r = SM(v, 'majority'); assert r['dir'] == 'BUY' and r['agree'] == 3 and r['auto_ok']
assert [x['status'] for x in v] == ['ok', 'ok', 'ok', 'against', 'against']
assert not SM(v, 'minus1')['auto_ok']
r = SM(mk([('h4', 'BUY'), ('tf', 'SELL')]), 'all'); assert r['dir'] is None and not r['auto_ok']          # مساوی = جهت نامشخص
r = SM(mk([('h4', 'SELL'), ('rsi', 'SELL'), ('macd', 'SELL'), ('vol', None)]), 'all')
assert r['dir'] == 'SELL' and r['agree'] == 3 and r['total'] == 4 and not r['auto_ok']                      # حجم کم = شرط ناقص
assert SM(mk([('h4', 'SELL'), ('rsi', 'SELL'), ('macd', 'SELL'), ('vol', 'OK')]), 'all')['auto_ok']
assert not SM([], 'all')['auto_ok']
assert not SM(mk([('vol', 'OK')]), 'all')['auto_ok']                                                          # فقط حجم = بدون جهت

# --- رأی هر فیلتر ---
keys = ['btceth', 'h4', 'tf', 'rsi', 'macd', 'adx', 'level', 'vol']
vs = {x['key']: x for x in V('ABC', '5min', 'HVL=100.0', keys)}
assert all(vs[k]['vote'] == 'SELL' for k in ('btceth', 'h4', 'tf', 'rsi', 'macd', 'adx', 'level')) and vs['vol']['vote'] == 'OK', vs
st['btc'] = 2                                                                                                  # BTC صعودی، ETH نزولی => خنثی
assert {x['key']: x for x in V('ABC', '5min', 'HVL=100.0', ['btceth'])}['btceth']['vote'] is None
assert {x['key']: x for x in V('BTC', '5min', 'HVL=100.0', ['btceth'])}['btceth']['vote'] == 'SELL'             # نماد خودش حذف می‌شود
st['tf']['15min'] = 'BULLISH'
assert {x['key']: x for x in V('ABC', '5min', 'HVL=100.0', ['tf'])}['tf']['vote'] is None
st['row']['volume_ratio'] = 1.0
assert {x['key']: x for x in V('ABC', '5min', 'HVL=100.0', ['vol'])}['vol']['vote'] is None

# --- ثبت برخورد + ورود خودکار ---
st.update(btc=-2, eth=-1, tf={'5min': 'BEARISH', '15min': 'BEARISH'}); st['row']['volume_ratio'] = 2.0
res = g['_touch_register'](1, 'ABC', 'SELL', 'HVL=100.0 SCN=1', '5min')
assert res[0] == 'entry_opened', res
a_, k_ = calls[-1]; assert a_[2] == 'SELL (Short)' and a_[3] == 100.0, a_
rec = list(S['touch_wait'].values())[0]; assert rec['status'] == 'opened' and rec['dir'] == 'SELL'
assert 'رأی فیلترها: فروش (9/9)' in a_[6], a_[6]
# تکراری
assert g['_touch_register'](1, 'ABC', 'SELL', 'HVL=100.0 SCN=1', '5min')[0] in ('touch_skipped', 'touch_wait')
# فیلتر ناقص => می‌ماند در لیست و ورود خودکار ندارد
S['touch_wait'].clear(); S['touch_wait_seen'].clear(); calls.clear(); st['row']['rsi'] = 50
res = g['_touch_register'](1, 'XYZ', 'SELL', 'HVL=100.0 SCN=2', '5min')
assert res[0] == 'touch_wait' and not calls, (res, calls)
lines, rows, n = g['_touch_pending_section'](S)
txt = '\n'.join(lines)
assert n == 1 and 'XYZ' in txt and 'RSI: ⏳ منتظر تایید' in txt and 'جهت: 🔴 فروش (8 از 9 فیلتر موافق)' in txt, txt
assert rows[0][0]['callback_data'].startswith('/tw_qe_sell_') and rows[0][-1]['url'].endswith('XYZ')
# حالت «همه به‌جز یکی» => همان مورد با بروزرسانی بعدی خودکار وارد می‌شود
S['touch_auto_mode'] = 'minus1'; rec = list(S['touch_wait'].values())[0]; rec['last_eval'] = 0
g['_touch_tick'](1)
assert calls and calls[-1][0][2] == 'SELL (Short)' and rec['status'] == 'opened', (calls, rec['status'])
# جهت الگوی برخورد یک رأی است: ۷ فیلتر فروش + الگو خرید => جهت فروش، الگو ❌، و در حالت «همه» خودکار وارد نمی‌شود
S['touch_wait'].clear(); S['touch_wait_seen'].clear(); calls.clear(); st['row']['rsi'] = 40; S['touch_auto_mode'] = 'all'
g['_touch_register'](1, 'PAT', 'BUY', 'HVL=100.0 SCN=5', '5min')
rec = list(S['touch_wait'].values())[0]
assert rec['dir'] == 'SELL' and rec['votes'][0]['key'] == 'pattern' and rec['votes'][0]['status'] == 'against' and not calls, rec
assert 'الگوی برخورد با سطح: ❌ مخالف' in '\n'.join(g['_touch_pending_section'](S)[0])
# الگو خاموش => رأی نمی‌دهد
S['touch_wait'].clear(); S['touch_wait_seen'].clear(); calls.clear(); ON['gate_touch_pattern_vote_enabled'] = False
g['_touch_register'](1, 'PAT2', 'BUY', 'HVL=100.0 SCN=5', '5min')
assert all(v['key'] != 'pattern' for v in list(S['touch_wait'].values())[0]['votes']) and calls
ON.pop('gate_touch_pattern_vote_enabled')
# ورود سریع دستی
S['touch_wait'].clear(); S['touch_wait_seen'].clear(); calls.clear(); S['touch_auto_mode'] = 'all'; st['row']['rsi'] = 50
g['_touch_register'](1, 'QQQ', 'SELL', 'HVL=100.0 SCN=2', '5min')
tid = list(S['touch_wait'])[0]
g['touch_quick_entry'](1, tid, 'SELL')
assert calls[-1][0] == 'quick' and calls[-1][1][1:3] == ('QQQ', 'SELL')
# بلاک دستی خرید/فروش در ورود خودکار رعایت می‌شود
S['touch_wait'].clear(); S['touch_wait_seen'].clear(); calls.clear(); st['row']['rsi'] = 40; S['manual_block_sell_entries'] = True
g['_touch_register'](1, 'BLK', 'SELL', 'HVL=100.0 SCN=2', '5min')
assert not calls and 'بلاک دستی' in list(S['touch_wait'].values())[0]['block_note']
# انقضا
S['manual_block_sell_entries'] = False; rec = list(S['touch_wait'].values())[0]; rec['expires_at'] = time.time() - 1
g['_touch_tick'](1); assert rec['status'] == 'expired'
print('touch_vote_selftest OK')
