"""V3.44.108: اولین مرحله‌ی ویزارد کاغذی = انتخاب صرافی (Binance / Bitunix)؛ داده‌ی همان صرافی استفاده می‌شود.
اجرا: python3 paper_exchange_selftest.py"""
import sys, types, os, tempfile
for name in ('aiohttp', 'ccxt', 'ccxt.async_support'):
    try: __import__(name)
    except Exception: sys.modules[name] = types.ModuleType(name)
if not hasattr(sys.modules['aiohttp'], 'ClientSession'):
    sys.modules['aiohttp'].ClientTimeout = lambda **k: None
    sys.modules['aiohttp'].TCPConnector = lambda **k: None
    sys.modules['aiohttp'].ClientSession = object
os.environ['TELEGRAM_TOKEN'] = '123:abc'; os.environ['ADMIN_CHAT_IDS'] = '111'
os.environ['BOT_DB_PATH'] = os.path.join(tempfile.mkdtemp(), 'bot.sqlite3'); os.environ['TELEGRAM_SKIP_BACKLOG'] = 'true'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
bot = importlib.import_module('bot'); bot.init_db()
out = []
bot.send_message = lambda chat_id, text, markup=None, message_id=None, **k: out.append((text, markup)) or True
bot.edit_page = lambda chat_id, text, markup=None, message_id=None, **k: out.append((text, markup)) or True
def cbs(m): return [b.get('callback_data') for r in (m or {}).get('inline_keyboard', []) for b in r]

for cid in (222, 111):
    s = bot.get_session(cid); s['paper_positions'] = {}
    assert s.get('paper_exchange') == 'binance'                       # پیش‌فرض
    out.clear(); bot.process_command('/mode_paper', cid)
    t, m = out[-1]
    assert '/paper_pick_binance' in cbs(m) and '/paper_pick_bitunix' in cbs(m) and '/set_bal_1000' not in cbs(m), cbs(m)
    out.clear(); bot.process_command('/paper_pick_bitunix', cid)
    t, m = out[-1]
    assert s['paper_exchange'] == 'bitunix' and s['trading_mode'] == 'PAPER' and '/set_bal_1000' in cbs(m), (s['paper_exchange'], cbs(m))
    assert bot.data_venue_for(cid) == 'bitunix'
    assert bot.tradingview_symbol('BTCUSDT', cid).startswith('BITUNIX:') and bot.tradingview_symbol('BTCUSDT', cid).endswith('.P')
    out.clear(); bot.process_command('/set_bal_500', cid)
    assert '/paper_bal' in cbs(out[-1][1])                              # «بازگشت» از مبلغ → صفحه‌ی موجودی (نه انتخاب صرافی)
    out.clear(); bot.process_command('/paper_pick_binance', cid)
    assert s['paper_exchange'] == 'binance' and bot.data_venue_for(cid) == 'binance'
    assert bot.tradingview_symbol('BTCUSDT', cid).startswith('BINANCE:')
    # با پوزیشن باز نمی‌شود صرافی را عوض کرد
    s['paper_positions'] = {'X': {}}
    out.clear(); bot.process_command('/paper_pick_bitunix', cid)
    assert s['paper_exchange'] == 'binance'
    s['paper_positions'] = {}
    out.clear(); bot.process_command('/paper_pick_okx', cid); assert s['paper_exchange'] == 'binance'
print('paper_exchange_selftest: ALL OK')
