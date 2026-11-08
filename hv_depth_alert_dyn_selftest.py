"""V3.44.153: هشدار تغییر عمق فقط با کلیدهای k پویا. اجرا: python3 hv_depth_alert_dyn_selftest.py"""
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
os.environ['TELEGRAM_TOKEN'] = '123:abc'
os.environ['ADMIN_CHAT_IDS'] = '111'
os.environ['BOT_DB_PATH'] = os.path.join(tempfile.mkdtemp(), 'bot.sqlite3')
os.environ['TELEGRAM_SKIP_BACKLOG'] = 'true'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
import numpy as np
import pandas as pd
bot = importlib.import_module('bot')
bot.init_db()
bot.send_message = lambda *a, **k: None

N = 300
def mk(atr):
    c = np.full(N, 100.0)
    return pd.DataFrame({'timestamp': np.arange(N) * 900000.0, 'open': c, 'high': c + 1, 'low': c - 1, 'close': c, 'volume': np.ones(N), 'atr': np.full(N, atr)})

BASE = {'halving_model_enabled': True, 'halving_high': 200.0, 'halving_low': 50.0, 'halving_k_atr': 2.0,
        'halving_min_depth': 3, 'halving_max_depth': 10, 'halving_dynamic_k': False, 'halving_btc_dynamic_k': False}

def depth(atr, cfg):
    return bot._halving_context(mk(atr), N - 2, bot._halving_cfg({**cfg, 'halving_depth_freeze': False}))['depth']

# ATR دو مقدار نزدیک که عمق را یک پله عوض می‌کنند (همان لغزش ریز ATR)
lo_atr = hi_atr = None
for a in np.arange(0.5, 3.0, 0.0005):
    if depth(a, BASE) != depth(a + 0.0005, BASE):
        lo_atr, hi_atr = a, a + 0.0005
        break
assert lo_atr is not None and depth(lo_atr, BASE) == depth(hi_atr, BASE) + 1

def run(cfg, tag):
    bot._HV_DEPTH_TRACK.clear(); bot._HV_DEPTH_PENDING.clear(); bot._HV_DEPTH_STATE['first_pending'] = 0.0
    bot.HV_DEPTH_FLUSH_SECONDS = 10 ** 9      # ارسال نشود؛ فقط صف تاییدشده‌ها را می‌شماریم
    bot._hv_depth_track(tag, '15min', mk(lo_atr), cfg)
    for _ in range(bot.HV_DEPTH_CONFIRM + 1):
        bot._hv_depth_track(tag, '15min', mk(hi_atr), cfg)
    return len(bot._HV_DEPTH_PENDING)

assert bot.HV_DEPTH_ALERT_ONLY_DYNAMIC is True
# هر دو کلید خاموش → هشدار نیست و مبنا هم نگه‌داشته نمی‌شود
assert run(dict(BASE), 'AAA') == 0 and ('AAA', '15min') not in bot._HV_DEPTH_TRACK
# k پویا روشن → هشدار می‌آید
assert run({**BASE, 'halving_dynamic_k': True}, 'BBB') == 1
# k پویا از BTC روشن (مقدار BTC در دسترس نیست → k دستی): عمق از V3.44.154 قفل است، لغزش ATR هشدار نمی‌دهد
assert run({**BASE, 'halving_btc_dynamic_k': True}, 'CCC') == 0
# سوئیچ محیطی: رفتار قبلی (همیشه)
bot.HV_DEPTH_ALERT_ONLY_DYNAMIC = False
assert run({**BASE, 'halving_depth_freeze': False}, 'DDD') == 1
bot.HV_DEPTH_ALERT_ONLY_DYNAMIC = True
# HV_DEPTH_ALERT=0 کلاً خاموش
bot.HV_DEPTH_ALERT = False
assert run({**BASE, 'halving_dynamic_k': True}, 'EEE') == 0
print('hv_depth_alert_dyn_selftest OK')
