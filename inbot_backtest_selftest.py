"""تست آفلاین موتور بک‌تست داخل ربات. اجرا: python3 inbot_backtest_selftest.py"""
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
os.environ['HALVING_RANGE_OVERRIDE'] = '{"BTCUSDT":[126199.5,2817.15]}'   # آفلاین: سقف/کف BTC (در سرور واقعی از تاریخچه‌ی Binance می‌آید)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
import numpy as np, pandas as pd
bot = importlib.import_module('bot')
import inbot_backtest as ib
bot.init_db()
ok_all = True
def check(name, cond, info=''):
    global ok_all
    ok_all &= bool(cond)
    print(('PASS ' if cond else 'FAIL ') + name, info)

N = 900
BASE = 100.0
def make_df(paths):
    """paths: {index: (high, low, close)} برای کندل‌های خاص؛ بقیه تخت 100."""
    o = np.full(N, BASE); h = np.full(N, BASE + 0.05); l = np.full(N, BASE - 0.05); c = np.full(N, BASE)
    for k, (hh, ll, cc) in paths.items():
        h[k] = hh; l[k] = ll; c[k] = cc
        if k + 1 < N: o[k + 1] = cc
    ts = 1767225600000 + np.arange(N) * 900000
    return pd.DataFrame({'timestamp': ts, 'open': o, 'high': h, 'low': l, 'close': c, 'volume': np.full(N, 100.0)})

SIG_AT = 720   # کلوز این کندل سیگنال می‌دهد؛ ورود روی open کندل 721
seen = {'last_closed_ts': [], 'forming_flat': True, 'forming_ts_ok': True}
def fake_signal_factory(side='BUY'):
    def fake(primary, md, mode, tf, strat, filters, cfg, regime, live_price=None):
        # آخرین ردیف «در حال تشکیل» باید تخت باشد (open=high=low=close) و live_price = open همان ردیف
        f = primary.iloc[-1]
        flat = (f['open'] == f['high'] == f['low'] == f['close'] == live_price)
        seen['forming_flat'] &= bool(flat)
        closed_ts = int(primary.iloc[-2]['timestamp'])
        seen['last_closed_ts'].append(closed_ts)
        seen['forming_ts_ok'] &= (int(f['timestamp']) == closed_ts + 900000)
        return (side, 'fake') if closed_ts == int(df_ref['timestamp'].iloc[SIG_AT]) else (None, 'no')
    return fake
def fake_plan_factory(entry, sl, tp):
    return lambda primary, sig, cfg, st, strategy_timeframe=None, grid_levels=None, live_price=None, **k: (
        {'entry': entry, 'sl': sl, 'tp': tp}, 'fake-plan')

def run(paths, side='BUY', sl=99.0, tp=102.0, trail=False, profile='balanced'):
    global df_ref
    df_ref = make_df(paths)
    ib.get_signal_with_reason = fake_signal_factory(side)
    ib.build_trade_plan = fake_plan_factory(BASE, sl, tp)
    seen.update({'last_closed_ts': [], 'forming_flat': True, 'forming_ts_ok': True})
    return ib.simulate(df_ref, {'halving_model_enabled': True}, {}, '15min', start_ms=int(df_ref['timestamp'].iloc[SIG_AT]) - 1,
                       end_ms=int(df_ref['timestamp'].iloc[SIG_AT + 30]), margin=50.0, leverage=5.0, fee_pct=0.05,
                       start_balance=1000.0, trail_enabled=trail, trail_profile=profile, trail_fn=bot._trail_step)

# 1) TP: کندل 723 به 102 می‌رسد
r = run({723: (102.1, 99.9, 102.0)})
t = r['trade_list'][0] if r['trades'] else {}
check('TP exit', r['trades'] == 1 and t.get('why') == 'TP' and abs(t['exit'] - 102.0) < 1e-9, t.get('why'))
fee = 50 * 5 * 0.0005 * 2
check('pnl = gross - roundtrip fee', abs(t['pnl'] - ((102 - 100) * (250 / 100) - fee)) < 1e-9, t.get('pnl'))
check('no look-ahead: forming row flat + 1 candle ahead', seen['forming_flat'] and seen['forming_ts_ok'])
# 2) SL
r = run({723: (100.2, 98.9, 99.0)})
t = r['trade_list'][0]
check('SL exit', t['why'] == 'SL' and abs(t['exit'] - 99.0) < 1e-9 and t['pnl'] < 0, t['why'])
# 3) SL و TP در یک کندل => SL (محافظه‌کارانه)
r = run({723: (102.5, 98.5, 100.0)})
check('same candle SL+TP => SL', r['trade_list'][0]['why'] == 'SL', r['trade_list'][0]['why'])
# 4) SELL TP
r = run({723: (100.1, 97.9, 98.0)}, side='SELL', sl=101.0, tp=98.0)
check('SELL TP', r['trade_list'][0]['why'] == 'TP' and r['trade_list'][0]['pnl'] > 0)
# 5) ترلینگ: قیمت تا +1.5R بالا می‌رود (101.5 با R=1)، بعد برمی‌گردد؛ بدون ترلینگ SL کامل، با ترلینگ خروج سودده/سر‌به‌سر
paths = {723: (101.5, 99.95, 101.4), 724: (101.4, 100.4, 100.5), 725: (100.5, 98.9, 99.0)}
r0 = run(paths, trail=False); r1 = run(paths, trail=True)
check('no-trail => full SL', r0['trade_list'][0]['why'] == 'SL' and r0['trade_list'][0]['r'] < -0.9, r0['trade_list'][0])
check('trail => TRAIL exit better than SL', r1['trade_list'][0]['why'] == 'TRAIL' and r1['trade_list'][0]['pnl'] > r0['trade_list'][0]['pnl'], r1['trade_list'][0])
# 6) هیچ سیگنالی => صفر معامله و خلاصه سالم
global_ok = True
df_ref = make_df({})
ib.get_signal_with_reason = lambda *a, **k: (None, 'no')
r = ib.simulate(df_ref, {'halving_model_enabled': True}, {}, '15min', start_ms=int(df_ref['timestamp'].iloc[SIG_AT]), end_ms=int(df_ref['timestamp'].iloc[SIG_AT + 20]))
line = ib.one_line(r, 'BTCUSDT', '15m', '01-01', '06-30', 1000.0)
check('empty result line', r['trades'] == 0 and '0 معامله' in line, line)
# 7) داده کم => خطای واضح
try:
    ib.simulate(df_ref.iloc[:300], {}, {}, '15min'); check('short data raises', False)
except RuntimeError:
    check('short data raises', True)

# ======================= اتصال به ربات (دکمه/دستور) =======================
import threading, time as _time
sent = []
bot.send_message = lambda chat_id, text, markup=None, *a, **k: (sent.append((chat_id, text, k.get('parse_mode', 'Markdown'))) or True)
ADMIN, USER = 111, 222
rng2 = np.random.default_rng(11)
nn = 1500
cl_ = 80000 * np.exp(np.cumsum(rng2.normal(0, 0.0016, nn)))
op_ = np.concatenate([[80000], cl_[:-1]])
hist = pd.DataFrame({'timestamp': 1767225600000 - 10 * 86400000 + np.arange(nn) * 900000, 'open': op_,
                     'high': np.maximum(op_, cl_) * 1.0007, 'low': np.minimum(op_, cl_) * 0.9993, 'close': cl_, 'volume': 300.0})
bot._backtest_fetch_history = lambda symbol, tf, a, b: hist
import importlib as _il
_il.reload(ib) if False else None
# سیگنال/پلن واقعی استراتژی دوباره لازم است (تست‌های قبلی monkeypatch کرده‌اند)
import strategy as _st
ib.get_signal_with_reason = _st.get_signal_with_reason
ib.build_trade_plan = _st.build_trade_plan
a = bot.get_session(ADMIN)
check('پیش‌فرض: مدل نصف‌کردن روشن است', a['strategy_config'].get('halving_model_enabled'))
line = bot.run_inbot_backtest(ADMIN, '/backtest_btc 2026-01-01 2026-01-14')
check('خروجی دقیقاً یک سطر', isinstance(line, str) and '\n' not in line and line.startswith('🧪 BTC 15m'), line)
check('تاریخ بازه در سطر', '01-01→01-14' in line, line)
a2, b2 = bot._backtest_parse_args('/backtest_btc')
check('پیش‌فرض بازه: ۱ ژانویه تا ۱ ژوئیه همین سال', (a2.month, a2.day, b2.month, b2.day) == (1, 1, 7, 1) or b2 < __import__('datetime').datetime.now(__import__('datetime').timezone.utc), (a2, b2))
for bad in ('/backtest_btc 2026-05-01 2026-01-01', '/backtest_btc 2020-01-01 2026-01-01'):
    try:
        bot._backtest_parse_args(bad); check('بازه‌ی نامعتبر رد می‌شود ' + bad, False)
    except RuntimeError:
        check('بازه‌ی نامعتبر رد می‌شود ' + bad, True)
sent.clear()
bot.process_command('/backtest_btc', USER, 1)
check('کاربر عادی: بسته است و بک‌تست اجرا نمی‌شود', len(sent) == 1 and sent[0][0] == USER and not any(t.startswith(('🧪', '⏳')) for _, t, _ in sent) and '/backtest_btc' not in bot._BACKTEST_RUNNING and USER not in bot._BACKTEST_RUNNING, sent)
sent.clear()
bot.process_command('/backtest_btc 2026-01-01 2026-01-10', ADMIN, 1)
for _ in range(600):
    if any(t.startswith('🧪') or t.startswith('❌') for _, t, _ in sent): break
    _time.sleep(0.2)
final = [t for _, t, _ in sent if t.startswith('🧪') or t.startswith('❌')]
check('ادمین: پیام شروع + یک سطر نتیجه', len(sent) == 2 and sent[0][1].startswith('⏳') and len(final) == 1 and final[0].startswith('🧪'), sent)
check('بدون Markdown (علامت‌های | و _ خراب نمی‌کنند)', sent[-1][2] is None)
check('دکمه در صفحه‌ی کلیدها', any(b.get('callback_data') == '/backtest_btc' for r in __import__('presets').keyboard(a)['inline_keyboard'] for b in r))
check('قفل اجرای همزمان آزاد شد', ADMIN not in bot._BACKTEST_RUNNING)
print('ALL OK (bot glue)' if ok_all else 'SOME FAILED (bot glue)')
sys.exit(0 if ok_all else 1)
