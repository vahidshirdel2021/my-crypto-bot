"""تست آفلاین V3.44.95: کلید «خروج سریع‌تر از صف (کلوز ۵ دقیقه)». اجرا: python3 fav_close5m_selftest.py"""
import os, time, logging, hashlib, pandas as pd
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()
a = src.index("FAV_CONFIRM_MIN_RR = float"); b = src.index("def _auto_trend_gate(")
block = src[a:b]
sent = []; calls = []; asked = []
S = {'paper_positions': [], 'timeframe': '15min', 'trading_mode': 'PAPER', 'fav_confirm_enabled': True}
state = {'live': 100.2, 'df15': None, 'df5': None}
def gk(sym, tf, n):
    asked.append(tf); return state['df5'] if tf == '5min' else state['df15']
g = dict(os=os, time=time, hashlib=hashlib, logger=logging.getLogger('t'), pd=pd, ASSIST_SEEN_TTL_SECONDS=21600,
         _TF_SECONDS={'5min': 300, '15min': 900}, _LAST_BLOCK_REASON={}, get_session=lambda c: S, save_session=lambda c: None,
         fmt=lambda v: str(v), extract_setup_level=lambda r: ('t', 'L', '1.0'), send_message=lambda c, t, *a, **k: sent.append(t),
         latest_price=lambda sym: state['live'], exchange_latest_price=lambda c, sym: state['live'], get_klines=gk,
         _auto_trend_gate=lambda *a, **k: False, execute_trade=lambda *a, **k: (calls.append(k) or True),
         gate_on=lambda s, k: False, _btc_front_flags=lambda s: (False, False), USER_SESSIONS={},
         ASSIST_SHADOW_HORIZON_SECONDS=86400, _assist_queue_signal=lambda *a, **k: 'assist_sent')
exec(block, g)
E = g['_fav_eval_tf']
# --- انتخاب تایم‌فریم ارزیابی ---
assert E({}, '15min') == '15min' and E({'fav_close_5m_enabled': False}, '15min') == '15min'      # خاموش = رفتار قبلی
assert E({'fav_close_5m_enabled': True}, '15min') == '5min'
assert E({'fav_close_5m_enabled': True}, '5min') == '5min' and E({'fav_close_5m_enabled': True}, '1min') == '1min'   # تایم‌فریم ≤ ۵ دقیقه دست نمی‌خورد
# --- جریان واقعی: سیگنال ۱۵ دقیقه‌ای؛ کلوز ۵ دقیقه‌ای اول تایید می‌دهد ولی هنوز کندل ۱۵ دقیقه‌ای بسته نشده ---
now = time.time()
def mk5(closes, t0):
    return pd.DataFrame([{'timestamp': t0 + i * 300, 'close': c, 'open': c, 'high': c, 'low': c} for i, c in enumerate(closes)])
def queue():
    S['fav_wait'] = {}; S.pop('fav_wait_seen', None)
    assert g['_fav_confirm_hold'](1, 'ABC', 'BUY', {'rr': 2.0}, 100, 99, 102, 'r') is True
    rec = list(S['fav_wait'].values())[0]; rec['created_at'] = now - 400; return rec
state['df15'] = pd.DataFrame([{'timestamp': now - 3000, 'close': 100.0, 'open': 100, 'high': 100, 'low': 100},
                              {'timestamp': now + 600, 'close': 100.2, 'open': 100, 'high': 100, 'low': 100}])      # فقط کندل در حال تشکیل بعد از سیگنال
state['df5'] = mk5([100.0, 100.2, 100.2], now - 330)       # کندل ۵ دقیقه‌ای بعد از سیگنال بسته شده (کلوز ۱۰۰٫۲ = +0.2R)، آخری در حال تشکیل
# خاموش: ۱۵ دقیقه‌ای هنوز بسته نشده → صبر
S['fav_close_5m_enabled'] = False; asked.clear(); rec = queue()
g['_fav_process_one'](1, S, rec); assert rec['status'] == 'waiting' and not calls and set(asked) == {'15min'}, (rec['status'], asked)
# روشن: کلوز ۵ دقیقه‌ای همان لحظه تایید می‌دهد → ورود
S['fav_close_5m_enabled'] = True; asked.clear(); rec = queue()
g['_fav_process_one'](1, S, rec); assert rec['status'] == 'opened' and len(calls) == 1 and set(asked) == {'5min'} and rec['eval_tf'] == '5min', (rec['status'], asked)
# روشن + کندل ۵ دقیقه‌ای بدون حرکت کافی: صبر؛ و دوباره‌سنجی (برگشت last_eval_ts) فقط ۵ دقیقه عقب می‌رود نه ۱۵ دقیقه
calls.clear(); rec = queue(); state['df5'] = mk5([100.0, 100.05, 100.05], now - 330)
g['_fav_process_one'](1, S, rec); assert rec['status'] == 'waiting' and rec['eval_n'] == 2 and rec['last_eval_ts'] == now - 30
# --- کارت: متن ۵ دقیقه‌ای ---
assert "r.get('eval_tf') == '5min' and tf != '5min'" in src and 'کلوز کندل بسته‌شده‌ی ۵ دقیقه‌ای' in src
# --- منو و کنترل‌کننده در کد ---
assert "'/toggle_fav_close5m'" in src and "'fav_close_5m_enabled': False" in src and "'fav_close_5m_enabled'," in src
print('fav_close5m_selftest ALL OK')
