"""V3.44.52: کارت ورود و پیام «پوزیشن بسته شد» برای معامله‌های بسته‌شده‌ی امروز تا پایان روز حذف نشوند، فردا حذف شوند."""
import os, time, logging
from datetime import datetime, timezone, timedelta
from threading import RLock
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()
a = src.index("KEEP_CLOSED_CARDS_TODAY = ")
b = src.index("def _message_protected(")
b2 = src.index("\n\n\n", b)
now = datetime.now(timezone.utc)
g = {'os': os, 'datetime': datetime, 'timezone': timezone, 'RLock': RLock, 'logger': logging.getLogger('t'),
     '_crypto_now': lambda: datetime.now(timezone.utc), '_KB_ANCHOR_LOCK': RLock(), '_KB_ANCHOR': {}, 'USER_SESSIONS': {}}
exec(src[a:b2], g)
P = g['_message_protected']
CID = 5
def sess(**kw):
    g['USER_SESSIONS'][CID] = {'closed_positions': [], 'paper_positions': [], **kw}
today_ts = time.time()
yday_ts = (now - timedelta(days=1, hours=1)).timestamp()
sess(closed_positions=[
    {'symbol': 'A', 'close_timestamp': yday_ts, 'entry_card_mid': 11, 'close_msg_mid': 12},      # دیروز (سود/ضرر فرقی ندارد)
    {'symbol': 'B', 'close_timestamp': today_ts, 'entry_card_mid': 21, 'close_msg_mid': 22, 'pnl_usdt': -3.0},   # امروز، ضرر
    {'symbol': 'C', 'close_timestamp': today_ts, 'entry_card_mid': 31, 'pnl_usdt': 5.0},          # امروز، سود، بدون پیام بستن
])
assert P(CID, 21) and P(CID, 22), 'کارت و پیام بسته‌شده‌ی امروز (ضرر) باید بماند'
assert P(CID, 31), 'کارت ورود معامله‌ی سودده‌ی امروز باید بماند'
assert not P(CID, 11) and not P(CID, 12), 'مال دیروز باید پاک شود'
assert not P(CID, 999), 'پیام نامرتبط محافظت نمی‌شود'
# پوزیشن باز مثل قبل محافظت می‌شود
sess(paper_positions=[{'symbol': 'X', 'entry_card_mid': 77}])
assert P(CID, 77)
# کلید خاموش: رفتار قبلی
g['KEEP_CLOSED_CARDS_TODAY'] = False
sess(closed_positions=[{'symbol': 'B', 'close_timestamp': today_ts, 'entry_card_mid': 21}])
assert not P(CID, 21)
# رکورد بدون زمان بسته‌شدن یا خراب: محافظت نمی‌شود و خطا نمی‌دهد
g['KEEP_CLOSED_CARDS_TODAY'] = True
sess(closed_positions=[{'symbol': 'D', 'entry_card_mid': 41}, {'symbol': 'E', 'close_timestamp': 'x', 'entry_card_mid': 42}])
assert not P(CID, 41) and not P(CID, 42)
print('keep_closed_cards_selftest OK')
