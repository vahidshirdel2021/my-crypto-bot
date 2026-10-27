"""تشخیص سطوح نصف‌کردن: python levels_diag.py LINKUSDT 15m [k_atr=4] [max_depth=10]
سقف/کف تاریخی (با ۵ کمترین/بیشترین هفتگی و تاریخشان)، ATR هموار، عمق و سطوح نزدیک قیمت را از Binance Spot چاپ می‌کند
تا با چارت TradingView (اندیکاتور HalvLvl) مقایسه شود."""
import sys, time, datetime as dt
import requests, pandas as pd
import strategy as st
from halving_levels import choose_depth, spacing_at, levels_near

sym = (sys.argv[1] if len(sys.argv) > 1 else 'BTCUSDT').upper()
tf = sys.argv[2] if len(sys.argv) > 2 else '15m'
k = float(sys.argv[3]) if len(sys.argv) > 3 else 4.0
maxd = int(sys.argv[4]) if len(sys.argv) > 4 else 10
B = 'https://api.binance.com/api/v3/klines'

def klines(interval, limit=1000, end=None):
    p = {'symbol': sym, 'interval': interval, 'limit': limit}
    if end: p['endTime'] = end
    r = requests.get(B, params=p, timeout=15); r.raise_for_status()
    return r.json()

def df_of(rows):
    d = pd.DataFrame(rows).iloc[:, :6]; d.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    for c in d.columns: d[c] = pd.to_numeric(d[c])
    return d

# ---- سقف/کف تاریخی (کندل هفتگی، کل تاریخچه)
rows = []; end = None
while True:
    part = klines('1w', 1000, end)
    if not part: break
    rows = part + rows
    if len(part) < 1000: break
    end = part[0][0] - 1
w = df_of(rows); w['date'] = pd.to_datetime(w['timestamp'], unit='ms').dt.date
hi, lo = float(w['high'].max()), float(w['low'].min())
print(f'== {sym}: {len(w)} هفته | سقف تاریخی {hi} | کف تاریخی {lo}')
print('۵ کمترین کفِ هفتگی:'); print(w.nsmallest(5, 'low')[['date', 'low', 'high', 'close']].to_string(index=False))
print('۵ بیشترین سقفِ هفتگی:'); print(w.nlargest(5, 'high')[['date', 'high', 'low', 'close']].to_string(index=False))

# ---- ATR هموار و عمق
d = st.calculate_indicators(df_of(klines(tf, 1000)))
atr = st._halving_atr(d, len(d) - 1, {'halving_atr_smooth_candles': 200})
price = float(d['close'].iloc[-1])
print(f'\nتایم‌فریم {tf} | قیمت {price} | ATR هموار (میانه‌ی ۲۰۰ کندل از ATR14) = {atr:.6g}')
for kk in sorted({3.0, 4.0, k}):
    dep = choose_depth(hi, lo, atr, kk, 3, maxd)
    print(f'  k={kk:g}: R/(k*ATR)={((hi-lo)/(kk*atr)):.1f} → عمق {dep} | فاصله {spacing_at(hi, lo, dep):.6g}')
dep = choose_depth(hi, lo, atr, k, 3, maxd); step = spacing_at(hi, lo, dep)
print(f'\nسطوح عمق {dep} (k={k:g}) اطراف قیمت:')
for lv in levels_near(hi, lo, dep, price - 3 * step, price + 3 * step): print(f"  {lv['price']:.6g}  (عمق سطح {lv['depth']})")
