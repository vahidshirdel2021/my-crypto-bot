"""V3.44.14: تست رأی‌گیری فیلترها بعد از برخورد با سطح (بدون نیاز به اجرای ربات)."""
import re, time, os, hashlib, logging
from threading import RLock
import pandas as pd
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()
a = src.index('TOUCH_AUTO_MODES = (')
b = src.index('# END V3.44.14')
block = src[a:b]
sent, calls, tgc = [], [], []
favc, astc = [], []
S = {'paper_positions': [], 'timeframe': '5min', 'trading_mode': 'PAPER', 'is_bot_active': True, 'daily_stopped': False,
     'assist_expiry_seconds': 1800, 'touch_auto_mode': 'all', 'traded_levels': {}, 'strategy_config': {}}
ON = {f'gate_fc_{k}_enabled': True for k in ('btceth', 'h4', 'tf', 'rsi', 'macd', 'adx', 'level', 'vol')}
st = {'h4': 'BEARISH', 'tf': {'5min': 'BEARISH', '15min': 'BEARISH'}, 'btc': -2, 'eth': -1,
      'row': {'rsi': 40, 'macd_hist': -1.0, 'adx': 30, 'plus_di': 10, 'minus_di': 25, 'volume_ratio': 2.0, 'close': 99.0},
      'exec_ok': True, 'live': 100.0}


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
         get_session=lambda c: S, save_session=lambda c: None, gate_on=lambda s, k: ON.get(k, k in ('gate_touch_vote_enabled', 'gate_touch_pattern_vote_enabled', 'gate_min_rr_enabled')),
         extract_setup_level=lambda r: ('t', 'HVL', '100.0'), extract_scenario_tag=lambda r: '1', ASSIST_SEEN_TTL_SECONDS=21600,
         _trend_snapshot_cached=lambda sym, tf: {'score': st['btc'] if sym == 'BTC' else st['eth']},
         _symbol_h4_regime=lambda sym: st['h4'], _symbol_tf_regimes=lambda sym: dict(st['tf']), _TFR_TIMEFRAMES=('5min', '15min'),
         TF_DISPLAY={'5min': '۵ دقیقه', '15min': '۱۵ دقیقه'}, get_klines=lambda *a: DF(st['row']), calculate_indicators=lambda d: d,
         _single_indicator_biases=bias, FULL_CONFIRM_MIN_VOLUME_RATIO=1.5, fmt=lambda v: str(v),
         _assist_describe_source=lambda reason, tok, val, scn: (f'{tok} = {val}', f'{scn} - تست'),
         tradingview_chart_url=lambda sym, tf: f'https://tv/{sym}', _from_signal_origin=lambda f: f,
         exchange_latest_price=lambda c, s_: st['live'], latest_price=lambda s_: st['live'], MIN_RR_FLOOR=1.5, os=os, _LAST_BLOCK_REASON={},
         build_quick_plan_with_fallback=lambda sym, side, cfg, live, tf: ({'sl': 101.0, 'tp': 98.0, 'rr': 2.0, 'reason': 'q', 'tp_level_name': 'x'}, None),
         execute_trade=lambda *a, **k: (calls.append((a, k)) or st['exec_ok']),
         quick_channel_trade=lambda *a, **k: calls.append(('quick', a, k)), is_allowed=lambda c: True, _fav_confirm_hold=lambda *a: (favc.append(a) or bool(S.get('fav_confirm_enabled'))), _assist_queue_signal=lambda *a, **k: (astc.append((a, k)) or 'card'), tg=lambda m, p=None, t=10: (tgc.append((m, p)) or {'ok': True, 'result': {'message_id': 1000 + len(tgc)}}), _CB_CTX=type('X', (), {})(), send_message=lambda c, t, *a, **k: sent.append(t), USER_SESSIONS={})
exec(block, g)
V, SM = g['_touch_votes'], g['_touch_summarize']


def mk(votes):
    return [{'key': k, 'label': k, 'vote': v, 'detail': ''} for k, v in votes]


# --- جمع‌بندی آرا ---
r = SM(mk([('h4', 'SELL'), ('tf', 'SELL'), ('rsi', 'SELL'), ('macd', 'SELL'), ('adx', None)]), 'all')
assert (r['dir'], r['agree'], r['total'], r['auto_ok']) == ('SELL', 4, 5, False), r      # ۴ از ۵: خودکار نه
assert SM(mk([('h4', 'SELL'), ('tf', 'SELL'), ('rsi', 'SELL'), ('macd', 'SELL'), ('adx', None)]), 'minus1')['auto_ok']
v = mk([('h4', 'BUY'), ('tf', 'BUY'), ('rsi', 'BUY'), ('macd', 'BUY'), ('adx', 'SELL')])
r = SM(v, 'majority'); assert r['dir'] == 'BUY' and r['agree'] == 4 and r['auto_ok']
assert [x['status'] for x in v] == ['ok', 'ok', 'ok', 'ok', 'against']
assert SM(v, 'minus1')['auto_ok'] and not SM(v, 'all')['auto_ok']
# استقلال: روند (۳ فیلتر) و مومنتوم (۳ فیلتر) هرکدام فقط یک رأی‌اند، پس ۶ فیلتر هم‌خانواده الگوی با وزن ۲ را به‌تنهایی خنثی می‌کنند اما کنار نمی‌زنند
six = [('pattern', 'BUY'), ('btceth', 'SELL'), ('h4', 'SELL'), ('tf', 'SELL'), ('rsi', 'SELL'), ('macd', 'SELL'), ('adx', 'SELL')]
r = SM(mk(six), 'majority'); assert r['dir'] is None and not r['auto_ok'], r
r = SM(mk(six + [('level', 'SELL')]), 'minus1')                                      # با گروه سوم (سطح) جهت فروش می‌شود
assert r['dir'] == 'SELL' and r['auto_ok'] and 'counter' not in r, r                 # خلاف الگو هم ممنوع نیست (ورود خودکار آزاد)
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
assert 'رأی فیلترها: فروش (9/9)' in a_[6] and 'طرح ورود سریع' in a_[6], a_[6]
# تکراری
assert g['_touch_register'](1, 'ABC', 'SELL', 'HVL=100.0 SCN=1', '5min')[0] in ('touch_skipped', 'touch_wait')
# فیلتر ناقص => می‌ماند در لیست و ورود خودکار ندارد
S['touch_wait'].clear(); S['touch_wait_seen'].clear(); calls.clear(); st['row']['rsi'] = 50
res = g['_touch_register'](1, 'XYZ', 'SELL', 'HVL=100.0 SCN=2', '5min')
assert res[0] == 'touch_wait' and not calls, (res, calls)
recs_ = g['_touch_waiting_recs'](S)
txt, mk_ = g['_touch_card_payload'](recs_[0])
assert len(recs_) == 1 and 'XYZ' in txt and 'RSI: ⏳ منتظر تایید' in txt and 'جهت: 🔴 فروش (8 از 9 فیلتر موافق)' in txt, txt
rows = mk_['inline_keyboard']                                     # دکمه‌ها زیر خودِ همین مورد: ورود سریع + چارت، و بروزرسانی
assert rows[0][0]['callback_data'].startswith('/tw_qe_sell_') and rows[0][-1]['url'].endswith('XYZ') and rows[1][0]['callback_data'].startswith('/tw_ref_')
# کارت مستقل: ارسال، ویرایش فقط وقتی متن عوض شد، و پیام قبلی هنگام ارسال دوباره حذف می‌شود
rec_ = recs_[0]; tgc.clear()
assert g['_touch_send_card'](1, rec_) and rec_['msg_id'] and tgc[-1][0] == 'sendMessage' and tgc[-1][1]['reply_markup'] == mk_
n0 = len(tgc); g['_touch_update_card'](1, rec_); assert len(tgc) == n0                                  # بدون تغییر => ویرایش نمی‌شود
rec_['agree'] = 3; g['_touch_update_card'](1, rec_); assert tgc[-1][0] == 'editMessageText' and tgc[-1][1]['message_id'] == rec_['msg_id']
old_mid = rec_['msg_id']; g['_touch_send_card'](1, rec_)
assert [m for m, _ in tgc][-2:] == ['deleteMessage', 'sendMessage'] and rec_['msg_id'] != old_mid
rec_['agree'] = 8; rec_['last_eval'] = time.time()
# حالت «همه به‌جز یکی» => همان مورد با بروزرسانی بعدی خودکار وارد می‌شود
S['touch_auto_mode'] = 'minus1'; rec = list(S['touch_wait'].values())[0]; rec['last_eval'] = 0
g['_touch_tick'](1)
assert calls and calls[-1][0][2] == 'SELL (Short)' and rec['status'] == 'opened', (calls, rec['status'])
fin = [x for x in tgc if x[0] == 'editMessageText'][-1][1]                                              # کارت نهایی: بدون دکمه + وضعیت
assert fin['reply_markup'] == {'inline_keyboard': []} and 'ربات بعد از تایید فیلترها وارد شد' in fin['text'] and '⏳' not in fin['text'].split('\n')[1]
# جهت الگوی برخورد یک رأی است: ۷ فیلتر فروش + الگو خرید => جهت فروش، الگو ❌، و در حالت «همه» خودکار وارد نمی‌شود
S['touch_wait'].clear(); S['touch_wait_seen'].clear(); calls.clear(); st['row']['rsi'] = 40; S['touch_auto_mode'] = 'all'
g['_touch_register'](1, 'PAT', 'BUY', 'HVL=100.0 SCN=5', '5min')
rec = list(S['touch_wait'].values())[0]
assert rec['dir'] == 'SELL' and rec['votes'][0]['key'] == 'pattern' and rec['votes'][0]['status'] == 'against' and not calls, rec
assert 'الگوی برخورد با سطح: ❌ مخالف' in g['_touch_card_text'](rec)
# الگو خاموش => رأی نمی‌دهد
S['touch_wait'].clear(); S['touch_wait_seen'].clear(); calls.clear(); ON['gate_touch_pattern_vote_enabled'] = False
g['_touch_register'](1, 'PAT2', 'BUY', 'HVL=100.0 SCN=5', '5min')
assert all(v['key'] != 'pattern' for v in list(S['touch_wait'].values())[0]['votes']) and calls
ON.pop('gate_touch_pattern_vote_enabled')
# خلاف جهت الگو بودن مانع ورود خودکار نیست (فقط شمارش موافق‌ها حد را تعیین می‌کند)
S['touch_wait'].clear(); S['touch_wait_seen'].clear(); calls.clear(); S['touch_auto_mode'] = 'minus1'; st['row']['rsi'] = 40
assert g['_touch_register'](1, 'CTR', 'BUY', 'HVL=100.0 SCN=5', '5min')[0] == 'entry_opened' and calls[-1][0][2] == 'SELL (Short)'
# --- طرح اصلی ستاپ + محافظ‌های R:R و دوری قیمت ---
def fresh(mode='all', rsi=40):
    S['touch_wait'].clear(); S['touch_wait_seen'].clear(); calls.clear(); S['touch_auto_mode'] = mode; st['row']['rsi'] = rsi; st['live'] = 100.0
plan = {'entry': 100.0, 'sl': 100.8, 'tp': 98.4, 'rr': 2.0, 'score': 77, 'quality_label': 'A', 'structural_target': True, 'tp_level_name': 'L1', 'tp_stages': None, 'reason': 'PLAN'}
fresh(); res = g['_touch_register'](1, 'PL1', 'SELL', 'HVL=100.0 SCN=1', '5min', plan)
a_, k_ = calls[-1]; assert res[0] == 'entry_opened' and (a_[4], a_[5]) == (100.8, 98.4) and k_['plan_score'] == 77 and k_['structural_tp'] and 'طرح اصلی ستاپ' in a_[6], (a_, k_)
fresh(); st['row']['rsi'] = 40                                   # جهت نهایی خلاف جهت برخورد => طرح اصلی (جهت مخالف) استفاده نمی‌شود
ON['gate_touch_pattern_vote_enabled'] = False
res = g['_touch_register'](1, 'PL2', 'BUY', 'HVL=100.0 SCN=1', '5min', {**plan, 'sl': 99.2, 'tp': 101.6})
a_, k_ = calls[-1]; assert a_[2] == 'SELL (Short)' and (a_[4], a_[5]) == (101.0, 98.0) and 'طرح ورود سریع' in a_[6], a_   # طرح ورود سریع
ON.pop('gate_touch_pattern_vote_enabled')
# R:R لحظه‌ای کمتر از حداقل => نمی‌ماند/وارد نمی‌شود و دلیلش روی مورد نوشته می‌شود
fresh(); res = g['_touch_register'](1, 'RR1', 'SELL', 'HVL=100.0 SCN=1', '5min', {**plan, 'sl': 101.0, 'tp': 99.2})
rec = list(S['touch_wait'].values())[0]
assert not calls and rec['status'] == 'waiting' and 'R:R' in rec['block_note'], (calls, rec.get('block_note'))
# قیمت از SL/TP طرح گذشته
fresh(); res = g['_touch_register'](1, 'PS1', 'SELL', 'HVL=100.0 SCN=1', '5min', {**plan, 'sl': 99.5, 'tp': 98.0})
assert not calls and 'گذشته' in list(S['touch_wait'].values())[0]['block_note']
# دوری قیمت از لحظه‌ی برخورد: RSI خنثی => منتظر؛ بعد از تایید، اگر قیمت > 0.5R دور شده باشد وارد نمی‌شود، با برگشت قیمت وارد می‌شود
fresh('minus1', rsi=50); g['_touch_register'](1, 'DR1', 'SELL', 'HVL=100.0 SCN=1', '5min', plan)
rec = list(S['touch_wait'].values())[0]; assert rec['status'] == 'opened' or not calls
fresh('all', rsi=50); g['_touch_register'](1, 'DR2', 'SELL', 'HVL=100.0 SCN=1', '5min', plan)
rec = list(S['touch_wait'].values())[0]; assert rec['status'] == 'waiting' and not calls
st['row']['rsi'] = 40; st['live'] = 100.5; rec['last_eval'] = 0; g['_touch_tick'](1)          # 0.5/0.8 = 0.625R > 0.5R
assert not calls and 'دور شده' in rec['block_note'] and rec['status'] == 'waiting', rec.get('block_note')
st['live'] = 100.2; rec['last_eval'] = 0; g['_touch_tick'](1)                                   # 0.25R
assert calls and rec['status'] == 'opened' and 'block_note' not in rec
st['live'] = 100.0
# --- بعد از تایید فیلترها: صف تایید حرکت و حالت دستیار مثل مسیر عادی ---
def fresh2():
    S['touch_wait'].clear(); S['touch_wait_seen'].clear(); calls.clear(); favc.clear(); astc.clear(); tgc.clear()
    S['touch_auto_mode'] = 'all'; st['row']['rsi'] = 40; st['live'] = 100.0
fresh2(); S['fav_confirm_enabled'] = True
res = g['_touch_register'](1, 'FQ1', 'SELL', 'HVL=100.0 SCN=1', '5min', plan)
rec = list(S['touch_wait'].values())[0]
assert res[0] == 'fav_wait' and rec['status'] == 'queued' and not calls and not astc, (res, rec['status'], calls)     # ورود مستقیم نمی‌شود
a_ = favc[-1]; assert a_[1:3] == ('FQ1', 'SELL') and a_[4] == 100.0 and (a_[5], a_[6]) == (100.8, 98.4) and a_[3]['score'] == 77 and a_[3]['structural_target'], a_
assert 'صف تایید حرکت' in g['_touch_card_text'](rec) and g['_touch_waiting_recs'](S) == []                            # از لیست انتظار خارج شد
S['assist_mode_enabled'] = True                                                                                        # صف تایید حرکت اولویت دارد (مثل مسیر عادی)
fresh2(); g['_touch_register'](1, 'FQ2', 'SELL', 'HVL=100.0 SCN=1', '5min')
assert list(S['touch_wait'].values())[0]['status'] == 'queued' and not astc
S['fav_confirm_enabled'] = False                                                                                       # حالت دستیار: کارت ✅/❌، بدون ورود خودکار
fresh2(); res = g['_touch_register'](1, 'AS1', 'SELL', 'HVL=100.0 SCN=1', '5min', plan)
rec = list(S['touch_wait'].values())[0]
assert res[0] == 'assist_card' and rec['status'] == 'card_sent' and not calls and astc and astc[-1][0][1:3] == ('AS1', 'SELL'), (res, calls)
assert 'حالت دستیار' in g['_touch_card_text'](rec)
S['assist_mode_enabled'] = False
fresh2(); assert g['_touch_register'](1, 'NO1', 'SELL', 'HVL=100.0 SCN=1', '5min')[0] == 'entry_opened' and calls and not favc[1:]   # هر دو خاموش => ورود مستقیم
# R:R لحظه‌ای پیش از رفتن به صف هم چک می‌شود
S['fav_confirm_enabled'] = True; fresh2(); g['_touch_register'](1, 'FQ3', 'SELL', 'HVL=100.0 SCN=1', '5min', {**plan, 'sl': 101.0, 'tp': 99.2})
assert not favc and list(S['touch_wait'].values())[0]['status'] == 'waiting'
S['fav_confirm_enabled'] = False
# چند مورد هم‌زمان: هر کارت مستقل است و دکمه‌هایش فقط به شناسه‌ی خودش اشاره می‌کنند
S['touch_wait'].clear(); S['touch_wait_seen'].clear(); calls.clear(); st['row']['rsi'] = 50; S['touch_auto_mode'] = 'all'
for sym_ in ('AAA', 'BBB', 'CCC'):
    g['_touch_register'](1, sym_, 'SELL', 'HVL=100.0 SCN=2', '5min'); time.sleep(0.01)
recs3 = g['_touch_waiting_recs'](S); assert [r['symbol'] for r in recs3] == ['CCC', 'BBB', 'AAA']                       # جدیدترین اول
ids = set()
for r in recs3:
    tx, mk3 = g['_touch_card_payload'](r)
    assert r['symbol'] in tx and all(x not in tx for x in ({'AAA', 'BBB', 'CCC'} - {r['symbol']}))
    assert all(r['id'] in b['callback_data'] for row in mk3['inline_keyboard'] for b in row if 'callback_data' in b)
    ids.add(r['id'])
assert len(ids) == 3
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

# --- V3.44.21: لیست انتظار فقط لیست است (نماد + تعداد رأی موافق)؛ کارت هر مورد با لمس نمادش می‌آید ---
import ast
tree = ast.parse(src)
_names = ('assist_pending_list', 'touch_open_card', '_message_protected', '_after_message_deleted', '_pending_vote_ok', 'pending_vote_filter_cycle')
fsrc = {n.name: ast.get_source_segment(src, n) for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in _names}
assert len(fsrc) == 6
S['touch_wait'].clear(); S['touch_wait_seen'].clear(); S['paper_positions'] = []; calls.clear(); tgc.clear(); st['row']['rsi'] = 50
for i in range(10):
    g['_touch_register'](1, f'S{i:02d}', 'SELL', f'HVL={100 + i}.0 SCN=2', '5min'); time.sleep(0.005)
tgc.clear()
hdr = []
g2 = dict(g, PENDING_HIGH_VOTE_PCT=0.70, _PENDING_VF_ORDER=('all', 'high', 'full'),
          _PENDING_VF_LABEL={'all': 'ALL', 'high': 'HIGH', 'full': 'FULL'}, TOUCH_CARDS_PER_LIST=25, _KB_ANCHOR={}, _KB_ANCHOR_LOCK=RLock(), USER_SESSIONS={1: S}, _assist_pending_recs=lambda s_: [],
          send_message=lambda c, tx, mk=None, message_id=None, **k: hdr.append((tx, mk)), save_session=lambda c: None)
for s_ in fsrc.values():
    exec(s_, g2)
g2['assist_pending_list'](1)
assert len(hdr) == 1 and '10 مورد' in hdr[0][0]
assert not [p for m, p in tgc if m == 'sendMessage'], 'لیست نباید کارت‌ها را خودکار بفرستد'
txt, mk = hdr[0]
for i in range(10):
    assert f'`S{i:02d}`' in txt
rows_ = [b for row in mk['inline_keyboard'] for b in row if b['callback_data'].startswith('/tw_open_')]
assert len(rows_) == 10
for rec_ in S['touch_wait'].values():
    b_ = next(b for b in rows_ if b['callback_data'] == f"/tw_open_{rec_['id']}")
    assert rec_['symbol'] in b_['text']
    if rec_.get('dir'):
        assert f"({rec_['agree']}/{rec_['total']})" in b_['text'] and f"{rec_['agree']} از {rec_['total']} رأی موافق" in txt
# لمس یک نماد => فقط کارت همان مورد (با دکمه‌های خودش) می‌آید
r5 = next(r for r in S['touch_wait'].values() if r['symbol'] == 'S05')
g2['touch_open_card'](1, r5['id'])
sends = [p for m, p in tgc if m == 'sendMessage']
assert len(sends) == 1 and '`S05`' in sends[0]['text'] and r5['msg_id']
assert any('/tw_qe_' in b.get('callback_data', '') for row in sends[0]['reply_markup']['inline_keyboard'] for b in row)
# لمس دوباره: کارت قبلی همان مورد حذف و کارت تازه فرستاده می‌شود (تکراری نمی‌ماند)
old_mid = r5['msg_id']; g2['touch_open_card'](1, r5['id'])
assert any(m == 'deleteMessage' and p['message_id'] == old_mid for m, p in tgc)
# مورد تمام‌شده
hdr.clear(); r9 = next(r for r in S['touch_wait'].values() if r['symbol'] == 'S09'); r9['status'] = 'expired'
g2['touch_open_card'](1, r9['id']); assert 'دیگر در لیست انتظار نیست' in hdr[-1][0]
assert g2['_message_protected'](1, r5['msg_id'])                                  # منتظر => حذف خودکار ۳ دقیقه‌ای رد می‌شود
r5['status'] = 'expired'; assert not g2['_message_protected'](1, r5['msg_id'])    # تمام شد => قابل پاک‌سازی
mid5 = r5['msg_id']; g2['_after_message_deleted'](1, mid5); assert r5['msg_id'] is None
print('assist list (symbols + votes, card on tap) OK')

# --- V3.44.23: ثبت معکوس‌شده از صف تایید حرکت (flip_from) از بررسی «قبلاً ثبت شده» عبور می‌کند و جهتِ الگو مخالف است ---
S['touch_wait'].clear(); S['touch_wait_seen'].clear(); S['paper_positions'] = []; S['manual_block_buy_entries'] = True
r1 = g['_touch_register'](1, 'FLP', 'BUY', 'HVL=100.0 SCN=2', '5min')
w = [r for r in S['touch_wait'].values() if r['symbol'] == 'FLP'][0]; w['status'] = 'expired'
assert g['_touch_register'](1, 'FLP', 'SELL', 'HVL=100.0 SCN=2', '5min')[0] == 'touch_skipped'
st_, _ = g['_touch_register'](1, 'FLP', 'SELL', '🔁 معکوس‌شده از صف تایید حرکت | HVL=100.0 SCN=2', '5min', flip_from='BUY')
assert st_ != 'touch_skipped'
fr = [r for r in S['touch_wait'].values() if r['symbol'] == 'FLP' and r['status'] == 'waiting'][0]
assert fr['flipped_from'] == 'BUY' and fr['touch_sig'] == 'SELL' and any(v['key'] == 'pattern' and v['vote'] == 'SELL' for v in fr['votes'])
assert '🔁' in g['_touch_card_text'](fr)
print('flip register OK')

# --- V3.44.24: دکمه‌ی فیلتر رأی در لیست انتظار (همه ← رأی بالا ≥۷۰٪ ← رأی کامل) ---
_t = time.time() + 600
def _mk(i, sym, d, ag, tot):
    return {'id': f'v{i}', 'symbol': sym, 'dir': d, 'agree': ag, 'total': tot, 'status': 'waiting', 'created_at': _t - i, 'expires_at': _t,
            'tf': '5min', 'votes': [], 'touch_sig': d or 'BUY'}
S['touch_wait'] = {f'v{i}': r for i, r in enumerate([_mk(0, 'FULL1', 'BUY', 7, 7), _mk(1, 'HIGH1', 'SELL', 5, 7), _mk(2, 'LOW1', 'BUY', 4, 7),
                                                       _mk(3, 'NODIR', None, 0, 7), _mk(4, 'NOF', 'BUY', 0, 0), _mk(5, 'EDGE', 'BUY', 7, 10)])}
S.pop('pending_vote_filter', None)
def _render():
    hdr.clear(); g2['assist_pending_list'](1)
    txt, mk = hdr[-1]
    return txt, mk, [b['text'] for row in mk['inline_keyboard'] for b in row if b['callback_data'].startswith('/tw_open_')]
txt, mk, btns = _render()
assert len(btns) == 6 and mk['inline_keyboard'][0][0]['callback_data'] == '/pending_vote_filter' and mk['inline_keyboard'][0][0]['text'] == 'ALL'
g2['pending_vote_filter_cycle'](1)                      # all -> high
assert S['pending_vote_filter'] == 'high'
txt, mk, btns = _render()
names = sorted(b.split()[1] for b in btns)
assert names == ['EDGE', 'FULL1', 'HIGH1'], names       # 7/10 = 70% هم رأی بالا حساب می‌شود؛ LOW1 (4/7) و بدون‌جهت/بدون‌فیلتر نه
assert 'فیلتر رأی' in txt and '3 از 6' in txt and mk['inline_keyboard'][0][0]['text'] == 'HIGH'
g2['pending_vote_filter_cycle'](1)                      # high -> full
assert S['pending_vote_filter'] == 'full'
txt, mk, btns = _render()
assert [b.split()[1] for b in btns] == ['FULL1'] and 'همه‌ی فیلترها موافق' in txt
g2['pending_vote_filter_cycle'](1)                      # full -> all
assert S['pending_vote_filter'] == 'all' and len(_render()[2]) == 6
# فیلتر همه‌ی موردها را پنهان کند: لیست و دکمه‌ی فیلتر می‌ماند (پیام «هیچ سیگنالی» نمی‌آید)
for r in S['touch_wait'].values(): r['agree'] = 1
S['pending_vote_filter'] = 'high'
txt, mk, btns = _render()
assert not btns and 'هیچ موردِ برخورد با سطح با این فیلتر جور نیست' in txt and mk['inline_keyboard'][0][0]['callback_data'] == '/pending_vote_filter'
print('pending vote filter OK')
