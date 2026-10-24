"""V3.44.62: «📋 سیگنال‌های در انتظار» برای کاربر عادی فقط نام نماد + دکمه‌ی TradingView؛ ادمین لیست کامل. اجرا: python3 pending_list_plain_selftest.py"""
import sys, types, os, tempfile, time, json
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
sent = []
bot.send_message = lambda chat_id, text, markup=None, message_id=None, **k: sent.append((chat_id, text, markup)) or True
bot.latest_price = lambda sym: 1.0
now = time.time()
for cid in (222, 111):
    s = bot.get_session(cid)
    s['assist_log'] = [{'id': 'a1', 'status': 'pending', 'symbol': 'INJ', 'sig': 'SELL', 'tf': '15min', 'entry': 7.56, 'sl': 7.74, 'tp': 7.2,
                        'expires_at': now + 1500, 'created_at': now - 10, 'saved': False}]
    s['touch_wait'] = {'t1': {'id': 't1', 'status': 'waiting', 'symbol': 'CRV', 'dir': 'BUY', 'tf': '5min', 'agree': 6, 'total': 8,
                              'expires_at': now + 1700, 'created_at': now - 20},
                       't2': {'id': 't2', 'status': 'waiting', 'symbol': 'INJ', 'dir': None, 'tf': '5min', 'agree': 0, 'total': 3,
                              'expires_at': now + 1700, 'created_at': now - 30}}
    sent.clear(); bot.assist_pending_list(cid)
    c, text, markup = sent[0]
    print(f'--- chat {cid} ---\n{text}\nBUTTONS: {json.dumps(markup, ensure_ascii=False)}\n')
    if cid == 222:
        for bad in ('رأی', 'خرید', 'فروش', 'فشار', 'فیلتر', 'دقیقه', 'ورود', 'R)', '🟢', '🔴', '🎯', '🤖'):
            assert bad not in text, ('leak in text', bad)
        btns = [b for row in markup['inline_keyboard'] for b in row]
        assert any('url' in b and 'tradingview.com' in b['url'] for b in btns)
        for b in btns:
            assert 'رأی' not in b['text'] and '/pending_vote_filter' != b.get('callback_data') and '/fav_queue' != b.get('callback_data'), b
        assert text.count('`INJ`') == 1 and '`CRV`' in text, 'dedupe/symbols'
    else:
        assert 'رأی' in text and 'فشار' in text, 'admin lost detail'
print('PENDING LIST PLAIN OK')
