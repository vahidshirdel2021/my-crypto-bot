import os, re, time
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()
a = src.index("def _touch_block_lines("); b = src.index("def _touch_buttons(")
g = dict(time=time, TF_DISPLAY={'15min': '15م'}, _assist_describe_source=lambda *a: ('HVL=1', '6'),
         _TOUCH_ST_TXT={'ok': '✅ تایید', 'wait': '⏳ منتظر تایید', 'against': '❌ مخالف', 'buy': '🟢 رأی خرید', 'sell': '🔴 رأی فروش'}, _TOUCH_GROUP_FA={})
exec(src[a:b], g)
mk = lambda k, s: {'key': k, 'label': k, 'status': s, 'detail': ''}
votes = [mk('a', 'wait'), mk('b', 'ok'), mk('c', 'against'), mk('d', 'ok'), mk('e', 'wait')]
r = {'symbol': 'THETA', 'tf': '15min', 'status': 'waiting', 'expires_at': time.time() + 900, 'votes': votes, 'dir': 'SELL', 'agree': 3, 'total': 5}
L = [l.strip() for l in g['_touch_block_lines'](r, None, time.time())]
i = [k for k, l in enumerate(L) if l.startswith('1.')][0]
seq = L[i:i + 7]
assert [re.sub(r'^\d+\. ', '', x).split(':')[0] if not x.startswith('┄') else '-' for x in seq] == ['b', 'd', '-', 'a', 'e', '-', 'c'], seq
assert [x.split('.')[0] for x in seq if not x.startswith('┄')] == ['1', '2', '3', '4', '5']
# فقط یک گروه => خط جداکننده نمی‌آید
r['votes'] = [mk('a', 'ok'), mk('b', 'ok')]; L = g['_touch_block_lines'](r, None, time.time()); assert not any('┄' in x for x in L)
print('touch card order OK')
