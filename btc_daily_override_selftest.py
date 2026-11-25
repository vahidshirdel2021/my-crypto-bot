"""تست آفلاین «باز شدن موقت جهت در حرکت قطعی ۱۵م BTC خلاف رژیم روزانه» (V3.44.186). اجرا: python3 btc_daily_override_selftest.py"""
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
_tmp = tempfile.mkdtemp()
os.environ['TELEGRAM_TOKEN'] = '123:abc'
os.environ['ADMIN_CHAT_IDS'] = '111'
os.environ['BOT_DB_PATH'] = os.path.join(_tmp, 'bot.sqlite3')
os.environ['PRESETS_CUSTOM_PATH'] = os.path.join(_tmp, 'presets_custom.json')
os.environ['TELEGRAM_SKIP_BACKLOG'] = 'true'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
import numpy as np
import pandas as pd
bot = importlib.import_module('bot')
import presets
bot.init_db()
ok_all = True


def check(name, cond, info=''):
    global ok_all
    ok_all &= bool(cond)
    print(('PASS ' if cond else 'FAIL ') + name, info)


def mk(kind, step, n=200, seed=7):
    now = int(time.time() // step * step)
    ts = [(now - (n - 1 - i) * step) * 1000 for i in range(n)]
    rng = np.random.RandomState(seed)
    i = np.arange(n)
    if kind == 'down':
        c = 400 - 1.5 * i + rng.randn(n) * 0.8
    elif kind == 'up':
        c = 100 + 1.5 * i + rng.randn(n) * 0.8
    elif kind == 'weakup':                      # صعودی ولی ضعیف/پرنوسان => ADX پایین
        c = 100 + 0.05 * i + rng.randn(n) * 2.0
    elif kind == 'late_up':                     # نزولی طولانی و بعد صعود تند در ۳۰ کندل آخر
        c = np.where(i < n - 30, 400 - 1.0 * i, 400 - 1.0 * (n - 30) + 3.0 * (i - (n - 30)))
        c = c + rng.randn(n) * 0.5
    elif kind == 'late_down':
        c = np.where(i < n - 30, 100 + 1.0 * i, 100 + 1.0 * (n - 30) - 3.0 * (i - (n - 30)))
        c = c + rng.randn(n) * 0.5
    else:
        c = 100 + rng.randn(n) * 1.0
    o = np.concatenate([[c[0]], c[:-1]])
    h = np.maximum(o, c) + 0.5
    l = np.minimum(o, c) - 0.5
    return pd.DataFrame({'timestamp': ts, 'open': o, 'high': h, 'low': l, 'close': c, 'volume': np.full(n, 1000.0)})


MODE = {'1day': 'down', '15min': 'late_up', '1hour': 'late_up', 'none': False}
STEP = {'1day': 86400, '15min': 900, '1hour': 3600}


def fake_klines(symbol, tf='5min', limit=200):
    if MODE['none'] or tf not in STEP:
        return pd.DataFrame()
    return mk(MODE[tf], STEP[tf])


bot.get_klines = fake_klines


def reset(**modes):
    MODE.update({'1day': 'down', '15min': 'late_up', '1hour': 'late_up', 'none': False})
    MODE.update(modes)
    bot._BTC_DAILY_CACHE.clear()
    bot._BTC_OVR_CACHE.clear()


def v(sig, on=True):
    return bot.btc_daily_verdict(sig, override_on=on)


# ---- سنجش پایه‌ی مدل ساختگی: روزانه نزولی => خرید بدون override بلاک
reset()
check('daily bearish blocks BUY (override off)', v('BUY', False)[0] is False)
check('daily bearish allows SELL', v('SELL', False)[0] is True)

# ---- نزولی روزانه + ۱۵م و ۱س صعودیِ قطعی => خرید موقتاً باز
reset(**{'15min': 'up', '1hour': 'up'})
ok, txt, info = v('BUY')
check('bearish daily + strong 15m/1h up => BUY allowed', ok is True and (info or {}).get('override') == 'BULLISH', info)
check('SELL still allowed in that state', v('SELL')[0] is True)
check('override off => BUY still blocked', v('BUY', False)[0] is False)

# ---- ۱۵م صعودی ولی ۱س نزولی => باز نشود
reset(**{'15min': 'up', '1hour': 'down'})
check('15m up but 1h down => BUY blocked', v('BUY')[0] is False)

# ---- صعود ضعیف ۱۵م => باز نشود
reset(**{'15min': 'weakup', '1hour': 'up'})
check('weak 15m up (low ADX) => BUY blocked', v('BUY')[0] is False)

# ---- رنج ۱۵م => باز نشود
reset(**{'15min': 'range', '1hour': 'up'})
check('range 15m => BUY blocked', v('BUY')[0] is False)

# ---- نبود داده => fail-closed
reset(**{'15min': 'up', '1hour': 'up'})
MODE['1day'] = 'down'
orig = bot.get_klines
bot.get_klines = lambda s, tf='5min', limit=200: (fake_klines(s, tf, limit) if tf == '1day' else pd.DataFrame())
bot._BTC_OVR_CACHE.clear()
check('no 15m data => BUY blocked (fail-closed)', v('BUY')[0] is False)
bot.get_klines = orig

# ---- رژیم روزانه صعودی + ریزش قطعی => فروش موقتاً باز
reset(**{'1day': 'up', '15min': 'down', '1hour': 'down'})
ok, txt, info = v('SELL')
check('bullish daily + strong 15m/1h down => SELL allowed', ok is True and (info or {}).get('override') == 'BEARISH', info)
check('BUY allowed in bullish daily', v('BUY')[0] is True)

# ---- رنج روزانه => هیچ‌چیز بلاک نیست و override لازم نیست
reset(**{'1day': 'range', '15min': 'up', '1hour': 'up'})
check('range daily: both allowed, no override', v('BUY')[0] is True and v('SELL')[0] is True and not (v('BUY')[2] or {}).get('override'))

# ---- ارزیاب خالص: شرط‌های سخت‌گیرانه
ind_up = bot.calculate_indicators(mk('up', 900))
ind_w = bot.calculate_indicators(mk('weakup', 900))
check('eval strong up (enter)', bot._btc_ovr_eval(ind_up, 'BULLISH', False) is True)
check('eval strong up vs wrong direction', bot._btc_ovr_eval(ind_up, 'BEARISH', False) is False)
check('eval weak up fails', bot._btc_ovr_eval(ind_w, 'BULLISH', False) is False)
check('eval None safe', bot._btc_ovr_eval(None, 'BULLISH', False) is False)

# ---- هیسترزیس: وقتی باز است شرط خروج نرم‌تر از ورود است
old_enter = bot.BTC_OVR_ADX_ENTER
bot.BTC_OVR_ADX_ENTER = 1000.0
check('hysteresis: stays open (stay rule) when enter rule would fail', bot._btc_ovr_eval(ind_up, 'BULLISH', True) is True)
check('hysteresis: enter rule fails with huge ADX threshold', bot._btc_ovr_eval(ind_up, 'BULLISH', False) is False)
bot.BTC_OVR_ADX_ENTER = old_enter

# ---- گیت کامل با سشن + معاملات معکوس
reset(**{'15min': 'up', '1hour': 'up'})
s = bot.get_session(222)
s.setdefault('strategy_config', {})['gate_btc_daily_regime_enabled'] = True
s['strategy_config']['gate_btc_daily_override_enabled'] = True
bot._block_simple_register = lambda *a, **k: None
check('gate: BUY allowed via override', bot._btc_daily_gate(222, s, 'ETH', 'BUY')[0] is True)
s['strategy_config']['gate_btc_daily_override_enabled'] = False
check('gate: override key off => BUY blocked', bot._btc_daily_gate(222, s, 'ETH', 'BUY')[0] is False)
s['strategy_config']['gate_btc_daily_override_enabled'] = True
s['strategy_config']['gate_inverse_trading_enabled'] = True
check('gate: inverse mode evaluates final direction (SELL signal => BUY trade allowed)', bot._btc_daily_gate(222, s, 'ETH', 'SELL')[0] is True)
check('gate: inverse mode BUY signal => SELL trade allowed (bearish daily)', bot._btc_daily_gate(222, s, 'ETH', 'BUY')[0] is True)

# ---- پیش‌فرض و پریست
check('registry default on', bot._gate_default('gate_btc_daily_override_enabled') is True)
check('key is a preset gate', 'gate_btc_daily_override_enabled' in presets._GATES_ON)

print('ALL PASS' if ok_all else 'SOME FAILED')
sys.exit(0 if ok_all else 1)
