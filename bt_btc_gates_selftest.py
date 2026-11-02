"""تست آفلاین گیت‌های BTC بک‌تست. اجرا: python3 bt_btc_gates_selftest.py"""
import sys, types, os, tempfile, time as _time
for name in ('aiohttp', 'ccxt', 'ccxt.async_support'):
    try: __import__(name)
    except Exception: sys.modules[name] = types.ModuleType(name)
if not hasattr(sys.modules['aiohttp'], 'ClientSession'):
    sys.modules['aiohttp'].ClientTimeout = lambda **k: None
    sys.modules['aiohttp'].TCPConnector = lambda **k: None
    sys.modules['aiohttp'].ClientSession = object
_tmp = tempfile.mkdtemp()
os.environ.update({'TELEGRAM_TOKEN': '123:abc', 'ADMIN_CHAT_IDS': '111', 'BOT_DB_PATH': os.path.join(_tmp, 'bot.sqlite3'),
                   'PRESETS_CUSTOM_PATH': os.path.join(_tmp, 'presets_custom.json'), 'TELEGRAM_SKIP_BACKLOG': 'true',
                   'HALVING_RANGE_OVERRIDE': '{"ETHUSDT":[4953.0,80.0],"BTCUSDT":[126199.5,2817.15]}'})
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib, numpy as np, pandas as pd
bot = importlib.import_module('bot'); bot.init_db()
import bt_btc_gates as G
ok_all = True
def check(name, cond, info=''):
    global ok_all; ok_all &= bool(cond); print(('PASS ' if cond else 'FAIL ') + name, '' if cond else info)

TF = 900_000; N = 1400; T0 = 1767225600000
TS = T0 + np.arange(N) * TF
def mk(close, rng=0.3):
    c = np.asarray(close, float); o = np.concatenate([[c[0]], c[:-1]])
    return pd.DataFrame({'timestamp': TS, 'open': o, 'high': np.maximum(o, c) + rng, 'low': np.minimum(o, c) - rng, 'close': c, 'volume': np.full(N, 100.0)})
up = mk(100 + np.arange(N) * 0.05)
down = mk(300 - np.arange(N) * 0.05)
K = 1000
TSK = int(TS[K])
H = lambda ql=None: {'calculate_indicators': bot.calculate_indicators, 'quick_levels': ql or bot._quick_opposing_levels,
     'with_halving_cfg': bot._with_halving_cfg, 'regime': bot.regime_from_ind_df, 'defaults': bot.STRATEGY_DEFAULTS,
     'front_min_atr': 1.0, 'chop': (3, 16, 3, 0.5), 'far_atr': 5.0, 'far_gap': 0.4, 'candle_min_body': 0.0}
def F(**k):
    d = {x: False for x in G.GATE_KEYS}; d.update(k); return d
cfg = {'halving_model_enabled': False}

# --- aligned
g = G.BtcGates(up, up, cfg, F(aligned=True), H())
check('aligned: هر دو صعودی -> BUY/SELL هر دو رد نمی‌شوند (جهت سنجیده نمی‌شود)', g.check(TSK, 'BUY')[0] and g.check(TSK, 'SELL')[0])
g = G.BtcGates(up, down, cfg, F(aligned=True), H())
check('aligned: ناهم‌جهت -> رد', g.check(TSK, 'BUY') == (False, 'aligned'))
g = G.BtcGates(up, None, cfg, F(aligned=True), H())
check('aligned: بدون داده‌ی ETH -> رد', g.check(TSK, 'BUY') == (False, 'aligned'))
# --- candle (بدنه‌ی آخرین کندل بسته‌شده)
g = G.BtcGates(up, None, cfg, F(candle=True), H())
check('candle: BTC صعودی: خرید آزاد، فروش بسته', g.check(TSK, 'BUY')[0] and g.check(TSK, 'SELL') == (False, 'candle'))
g = G.BtcGates(down, None, cfg, F(candle=True), H())
check('candle: BTC نزولی: فروش آزاد، خرید بسته', g.check(TSK, 'SELL')[0] and g.check(TSK, 'BUY') == (False, 'candle'))
# --- نبود داده
g = G.BtcGates(up, None, cfg, F(candle=True), H())
check('ts ناموجود -> nodata', g.check(TSK + 1, 'BUY') == (False, 'nodata'))
check('کندل آخرِ داده (بدون open بعدی) -> nodata', g.check(int(TS[-1]), 'BUY') == (False, 'nodata'))
# --- سطح جلویی با سطوح ساختگی
c0 = float(up['close'].iloc[K])
def ql_factory(levels):
    def ql(ind, entry, is_long, grid, cfg):
        return [(p, n) for p, n in levels if ((p > entry) if is_long else (p < entry))]
    return ql
atr = float(bot.calculate_indicators(up.iloc[:K + 2])['atr'].iloc[-2])
g = G.BtcGates(up, None, cfg, F(front=True), H(ql_factory([(c0 - 10 * atr, 'L')])))
check('front: BTC بالای سطح: خرید آزاد، فروش رد', g.check(TSK, 'BUY')[0] and g.check(TSK, 'SELL') == (False, 'front'))
g = G.BtcGates(up, None, cfg, F(front=True), H(ql_factory([(c0 + 0.3 * atr, 'L'), (c0 - 10 * atr, 'M')])))
check('front: سطح مقابل نزدیک (<1×ATR) -> خرید رد', g.check(TSK, 'BUY') == (False, 'front'))
g = G.BtcGates(up, None, cfg, F(front=True), H(ql_factory([(c0 + 3 * atr, 'U'), (c0 - 1.5 * atr, 'D')])))
check('front: BTC بالای نزدیک‌ترین سطح و سطح مقابل دور (۳×ATR) -> خرید آزاد', g.check(TSK, 'BUY')[0])
g = G.BtcGates(up, None, cfg, F(front=True), H(ql_factory([(c0 + 3 * atr, 'U'), (c0 - 10 * atr, 'D')])))
check('front: نزدیک‌ترین سطح بالای قیمت است -> خرید رد (سمت اشتباه سطح)', g.check(TSK, 'BUY') == (False, 'front'))
g = G.BtcGates(up, None, cfg, F(front=False, chop=False), H())
check('هیچ گیتی روشن نیست -> همیشه آزاد', g.check(TSK, 'BUY')[0])
# --- کلاف: کلوزها دور سطح رفت‌وبرگشت
osc = 100 + np.arange(N) * 0.0
osc = osc + np.where(np.arange(N) % 2 == 0, 0.4, -0.4)
osc_df = mk(osc, rng=0.1)
g = G.BtcGates(osc_df, None, cfg, F(chop=True), H(ql_factory([(100.0, 'L')])))
check('chop: رد و برگشت پیاپی -> رد', g.check(TSK, 'BUY') == (False, 'chop') and g.check(TSK, 'SELL') == (False, 'chop'))
g = G.BtcGates(up, None, cfg, F(chop=True), H(ql_factory([(c0 - 10 * atr, 'L')])))
check('chop: روند یک‌طرفه -> کلاف نیست', g.check(TSK, 'BUY')[0])
# --- بلاتکلیفی
g = G.BtcGates(up, None, cfg, F(undecided=True), H(ql_factory([(c0 + 40 * atr, 'U'), (c0 - 40 * atr, 'D')])))
check('undecided: وسط راهروی دو سطح دور -> هر دو جهت رد', g.check(TSK, 'BUY') == (False, 'undecided') and g.check(TSK, 'SELL') == (False, 'undecided'))
g = G.BtcGates(up, None, cfg, F(undecided=True), H(ql_factory([(c0 + 2 * atr, 'U'), (c0 - 40 * atr, 'D')])))
check('undecided: نزدیک یکی از سطوح -> آزاد', g.check(TSK, 'BUY')[0])
g = G.BtcGates(up, None, cfg, F(undecided=True), H(ql_factory([])))
check('undecided: بدون هیچ سطحی -> بسته', g.check(TSK, 'BUY') == (False, 'undecided'))
# --- بدون نشت آینده: تغییر داده‌ی بعد از کندل K+1 (و high/low/close خود K+1) نتیجه را عوض نمی‌کند
def verdicts(btc, eth):
    gg = G.BtcGates(btc, eth, cfg, F(aligned=True, candle=True, front=True, chop=True, undecided=True), H())
    return [gg.check(TSK, s) for s in ('BUY', 'SELL')]
base_v = verdicts(up, up)
fut = up.copy(); fut.loc[K + 1:, ['high', 'low', 'close']] = [999.0, 1.0, 500.0]
fut.loc[K + 2:, 'open'] = 777.0
check('بدون نشت آینده (BTC)', verdicts(fut, up) == base_v, (base_v, verdicts(fut, up)))
check('بدون نشت آینده (ETH)', verdicts(up, fut) == base_v)
# --- ادغام با simulate: رد شدن‌ها شمرده می‌شوند و ورودی نمی‌سازند
import inbot_backtest as ib, strategy as st
calls = []
def fake_sig(primary, md, mode, tf, strat, filters, cfg_, regime, live_price=None):
    return ('BUY', 'fake') if int(primary.iloc[-2]['timestamp']) % (TF * 50) == 0 else (None, 'no')
ib.get_signal_with_reason = fake_sig
ib.build_trade_plan = lambda primary, sig, cfg_, st_, strategy_timeframe=None, grid_levels=None, live_price=None, **k: ({'entry': live_price, 'sl': live_price - 1, 'tp': live_price + 1}, 'fake')
flat = mk(np.full(N, 100.0))
r0 = ib.simulate(flat, cfg, {}, '15min', start_ms=int(TS[760]), end_ms=int(TS[N - 5]), trail_enabled=False)
gate_closed = lambda ts, sig: (False, 'chop')
r1 = ib.simulate(flat, cfg, {}, '15min', start_ms=int(TS[760]), end_ms=int(TS[N - 5]), trail_enabled=False, entry_gate=gate_closed)
check('simulate: بدون گیت معامله دارد', r0['trades'] > 0, r0['trades'])
check('simulate: گیت بسته -> صفر معامله و شمارش رد', r1['trades'] == 0 and r1['stats']['signals'] > 0 and r1['stats']['gate_blocked'].get('chop') == r1['stats']['signals'], r1['stats'])
check('simulate: گیتی که خطا بدهد = رد با nodata', ib.simulate(flat, cfg, {}, '15min', start_ms=int(TS[760]), end_ms=int(TS[N - 5]), trail_enabled=False, entry_gate=lambda a, b: 1 / 0)['stats']['gate_blocked'].get('nodata', 0) > 0)
print('ALL OK' if ok_all else 'SOME FAILED'); sys.exit(0 if ok_all else 1)
