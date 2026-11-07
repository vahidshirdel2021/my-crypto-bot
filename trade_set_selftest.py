"""V3.44.152: مجموعهٔ معامله (نمادهای هم‌بسته با BTC) + رأی همه‌ی نمادها. اجرا: python3 trade_set_selftest.py"""
import sys, types, os, tempfile, inspect
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
os.environ['TRADE_SET_REPORT_PATH'] = os.path.join(tempfile.mkdtemp(), 'ts.json')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
import numpy as np
import pandas as pd
bot = importlib.import_module('bot')
bot.init_db()

N = 220
rng = np.random.default_rng(7)
btc_r = rng.normal(0, 0.01, N)
ts = (np.arange(N) * 3_600_000 + 1_700_000_000_000).astype(float)


def mk_df(rets):
    close = 100 * np.exp(np.cumsum(rets))
    return pd.DataFrame({'timestamp': ts, 'open': close, 'high': close * 1.001, 'low': close * 0.999,
                         'close': close, 'volume': np.ones(N)})


# هم‌بستگی: A≈BTC، B نیمه، C نویز خالص
data = {'BTC': mk_df(btc_r),
        'ETH': mk_df(btc_r * 0.9 + rng.normal(0, 0.002, N)),
        'A': mk_df(btc_r * 1.0 + rng.normal(0, 0.001, N)),
        'B': mk_df(btc_r * 0.5 + rng.normal(0, 0.01, N)),
        'C': mk_df(rng.normal(0, 0.01, N)),
        'D': mk_df(btc_r * 0.95 + rng.normal(0, 0.003, N)),
        'E': mk_df(btc_r * 0.7 + rng.normal(0, 0.006, N)),
        'F': mk_df(rng.normal(0, 0.01, N)),
        'G': mk_df(btc_r * 0.2 + rng.normal(0, 0.01, N)),
        'H': mk_df(-btc_r + rng.normal(0, 0.002, N))}      # هم‌بستگی منفی


def fetch(sym):
    if sym == 'BAD':
        raise RuntimeError('boom')
    return data.get(sym, pd.DataFrame())


# ۱) انتخاب: BTC و ETH همیشه، بعد بالاترین هم‌بستگی؛ منفی و نویز بیرون
bot.TRADE_SET_SIZE = 5
bot.TRADE_SET_MIN_CORR = 0.0
chosen, corr, n_ok = bot.compute_trade_set(list(data), fetch)
assert chosen[:2] == ['BTC', 'ETH'], chosen
assert chosen[2:] == ['A', 'D', 'E'], chosen
assert corr['A'] > corr['D'] > corr['E'] > corr['B'] > 0.2 and corr['H'] < -0.9
assert n_ok == len(data) - 1

# ۲) کف هم‌بستگی: فقط واجدین شرایط (حتی اگر جا باشد)
bot.TRADE_SET_SIZE = 9
bot.TRADE_SET_MIN_CORR = 0.6
chosen, corr, _ = bot.compute_trade_set(list(data), fetch)
assert set(chosen) == {'BTC', 'ETH', 'A', 'D', 'E'}, chosen
bot.TRADE_SET_MIN_CORR = 0.0

# ۳) داده‌ی BTC نیامد یا اکثر نمادها خراب → None (فهرست قبلی عوض نمی‌شود)
assert bot.compute_trade_set(list(data), lambda s: pd.DataFrame()) is None
assert bot.compute_trade_set(['BTC', 'ETH', 'A', 'BAD', 'X1', 'X2', 'X3', 'X4', 'X5', 'X6'], fetch) is None

# ۴) نمونه‌ی کوتاه (کمتر از حداقل کندل) = بدون همبستگی
short = data['A'].tail(40).reset_index(drop=True)
assert bot._trade_set_corr(short, data['BTC']) is None

# ۵) refresh: حالت را می‌نویسد؛ شکست حالت قبلی را نگه می‌دارد
bot.TRADE_SET_SIZE = 5
assert bot.trade_set_symbols() == bot._trade_set_fallback()          # قبل از محاسبه: فهرست ثابت
assert bot.refresh_trade_set(list(data), fetch) is True
assert bot.trade_set_symbols() == ['BTC', 'ETH', 'A', 'D', 'E']
assert bot.refresh_trade_set(list(data), lambda s: pd.DataFrame()) is False
assert bot.trade_set_symbols() == ['BTC', 'ETH', 'A', 'D', 'E']
assert os.path.exists(bot.TRADE_SET_REPORT_PATH)

# ۶) دروازه
s = {'priority_watch': {}}
bot.TRADE_SET_ON = True
assert bot.trade_set_allows('A') and bot.trade_set_allows('ETHUSDT') and not bot.trade_set_allows('C')
assert bot._trade_set_blocks_entry(s, 'C') is True and bot._trade_set_blocks_entry(s, 'A') is False
assert bot._trade_set_blocks_entry({'priority_watch': {'C': {'added_at': 1}}}, 'C') is False   # ورود سریع دستی مستثناست
bot.TRADE_SET_ON = False
assert bot._trade_set_blocks_entry(s, 'C') is False                                           # خاموش = مثل قبل
bot.TRADE_SET_ON = True

# ۷) در scan_symbol: بعد از ثبت رأی در تابلو و قبل از ثبت برخورد/ورود
src = inspect.getsource(bot.scan_symbol)
i_vote = src.index('_dir_board_note(')
i_nosig = src.index("'no_signal'", i_vote)      # اولین «بدون سیگنال» بعد از ثبت رأی
i_gate, i_touch = src.index('_trade_set_blocks_entry('), src.index('_touch_register')
assert i_vote < i_nosig < i_gate < i_touch

# ۸) مرحله‌ی نمایشی و متن واچ‌لیست
st = bot._entry_diag_stage({'status': 'vote_only', 'reason': 'x'})
assert st[1] == 'فقط رأی جهت'
txt = bot.trade_set_text()
assert 'BTC' in txt and 'D 0.9' in txt and 'فقط در جهت غالب' in txt

# ۹) رأی نمادهای غیرمعامله‌ای در جهت غالب شمرده می‌شود (فقط از تابلو، بدون برخورد)
CID = 111
sess = bot.get_session(CID)
sess['touch_wait'] = {}
sess['dir_board'] = {}
sess['timeframe'] = '15min'
bot.save_session = lambda *a, **k: None
for sym, d in (('C', 'SELL'), ('F', 'SELL'), ('G', 'SELL'), ('H', 'SELL'), ('A', 'BUY')):
    bot._dir_board_note(CID, sym, '15min', d, 'x')
blocked, b, sl = bot._touch_bias_verdict(sess)
assert (b, sl) == (1, 4) and blocked == 'BUY'                      # ۴ از ۵ فروش (۸۰٪) → خرید بلاک؛ هیچ‌کدام وارد لیست برخورد نشدند
assert not sess['touch_wait']
print('trade_set_selftest OK')
