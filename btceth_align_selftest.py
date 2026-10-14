"""تست آفلاین کلید «فقط وقتی BTC و ETH هم‌جهت‌اند». اجرا: python btceth_align_selftest.py"""
import os
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()
a = src.index("def btc_eth_aligned(tf):"); b = src.index("def btc_eth_regime_text(")
rows = {}
g = dict(btc_eth_regime_rows=lambda tf: rows['v'])
exec(src[a:b], g)
f = g['btc_eth_aligned']
cases = [
    ([('BTC','BEARISH',21,37),('ETH','BEARISH',19,36)], True),
    ([('BTC','BULLISH',30,60),('ETH','BULLISH',25,58)], True),
    ([('BTC','RANGE',10,50),('ETH','RANGE',12,48)], False),
    ([('BTC','BULLISH',30,60),('ETH','BEARISH',25,40)], False),
    ([('BTC','BULLISH',30,60),('ETH','RANGE',12,50)], False),
    ([('BTC',None,None,None),('ETH','BULLISH',25,58)], False),
]
for r, exp in cases:
    rows['v'] = r; ok, txt = f('5min'); print(ok, txt); assert ok == exp
# registry/default/enforcement present
assert "'gate_btceth_aligned_enabled': (" in src and "'btceth_aligned'" in src
i = src.index("'gate_btceth_aligned_enabled': ("); assert "False, 'entry_filter'" in src[i:i+200]
print('ALL OK')
