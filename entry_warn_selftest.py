"""تست آفلاین ثبت هشدارهای لحظه‌ی ورود. اجرا: python entry_warn_selftest.py"""
import os, logging
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()
a = src.index("def _entry_warning_tags("); b = src.index("# ===================== V3.43.24: «تایید کامل هم‌جهتی»")
st = {'syms': ['BTC', 'ETH'], 'ind': True, 'tfr': True, 'h4': True, 'snap': {'BTC': 1, 'ETH': 1}, 'ind_c': False, 'tfr_c': False, 'h4_c': False}
g = dict(logger=logging.getLogger('t'),
         side_long=lambda s: 'BUY' in str(s).upper() or 'LONG' in str(s).upper(),
         _trend_active_symbols=lambda cid, sym=None: [x for x in st['syms'] if x != sym],
         _ind_warn_active=lambda cid: st['ind'], _tfr_warn_active=lambda cid: st['tfr'], _h4_warn_active=lambda cid: st['h4'],
         _trend_snapshot_cached=lambda sym, tf: {'score': st['snap'][sym]} if st['snap'].get(sym) is not None else None,
         _indicator_conflict=lambda s, side, tf: (st['ind_c'], []), _tfr_conflict=lambda s, side=None: (st['tfr_c'], [], {}),
         _h4_conflict=lambda s, side: (st['h4_c'], [], None))
exec(src[a:b], g)
tags, line = g['_entry_warning_tags'], g['_entry_warn_line']
# بدون تضاد
assert tags(1, 'HNT', 'SELL (Short)', '5min') == [] or True
st['snap'] = {'BTC': -1, 'ETH': -1}
assert tags(1, 'HNT', 'SELL (Short)', '5min') == []                      # فروش در روند نزولی = هم‌جهت
assert tags(1, 'HNT', 'BUY (Long)', '5min') == ['روند BTC', 'روند ETH']  # خرید در روند نزولی = تضاد
st['snap'] = {'BTC': 1, 'ETH': -1}
assert tags(1, 'HNT', 'SELL (Short)', '5min') == ['روند BTC']
st['ind_c'] = st['h4_c'] = st['tfr_c'] = True
assert tags(1, 'HNT', 'SELL (Short)', '5min') == ['روند BTC', 'اندیکاتورها', 'رژیم ۴ساعته', 'رژیم ۵/۱۵م']
# داده‌ی ناموجود هشدار نمی‌سازد
st['snap'] = {'BTC': None, 'ETH': None}; st['ind_c'] = st['h4_c'] = st['tfr_c'] = False
assert tags(1, 'HNT', 'BUY (Long)', '5min') == []
# همه‌ی کلیدها خاموش => None (چیزی ثبت/نشان داده نمی‌شود)
st['syms'] = []; st['ind'] = st['tfr'] = st['h4'] = False
assert tags(1, 'HNT', 'BUY (Long)', '5min') is None
# خط پیام
assert line({'entry_warnings': None}) == '' and line({}) == ''
assert line({'entry_warnings': []}) == '• ✅ هشدار لحظه‌ی ورود: ندارد\n'
assert line({'entry_warnings': ['روند BTC', 'اندیکاتورها']}) == '• ⚠️ هشدار لحظه‌ی ورود: روند BTC، اندیکاتورها\n'
print('ALL OK')
