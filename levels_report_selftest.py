"""تست آفلاین «سطوح نماد»: گزارش سقف/کف تاریخی + سطوح نصف‌کردن + سطوح دوره‌ای با داده‌ی ساختگی.
اجرا:  python levels_report_selftest.py"""
import os, re, logging
import numpy as np, pandas as pd
import strategy as st

here = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(here, 'bot.py'), encoding='utf-8').read()

def grab(start, end):
    a = src.index(start); b = src.index(end, a); return src[a:b]

block = grab("def _levels_symbol(raw):", "# ===================== V3.44.57: انتخاب صرافی")
block = grab("def _halving_tf_params(cfg, tf):", "def _halving_tf_apply(") + "\n" + block
HALVING_TF_DEFAULTS = getattr(st, 'HALVING_TF_DEFAULTS', {})

def make_df(n=650, base=100.0, step_ms=5 * 60 * 1000):
    rng = np.random.default_rng(1)
    close = base + np.cumsum(rng.normal(0, 0.4, n))
    close = np.clip(close, 20, None)
    ts = 1_760_000_000_000 + np.arange(n) * step_ms
    o = np.r_[close[0], close[:-1]]
    h = np.maximum(o, close) + 0.3; l = np.minimum(o, close) - 0.3
    return pd.DataFrame({'timestamp': ts, 'open': o, 'high': h, 'low': l, 'close': close, 'volume': 10.0})

session = {'timeframe': '5min', 'strategy_config': {}}
calls = {'range': 0}
state = {'rng': (400.0, 5.0), 'live': 100.0, 'df': make_df()}
g = dict(np=np, pd=pd, re=re, logger=logging.getLogger('t'),
         get_session=lambda cid: session,
         get_halving_range_sync=lambda sym: state['rng'],
         get_klines=lambda sym, tf, lim: state['df'],
         latest_price=lambda sym: state['live'],
         fmt=lambda v: f'{float(v):,.4f}'.rstrip('0').rstrip('.'),
         TF_DISPLAY={'5min': '5m'},
         tradingview_chart_url=lambda sym, tf: 'https://example.com/chart',
         calculate_indicators=st.calculate_indicators, get_timeframe_preset=st.get_timeframe_preset,
         _compute_prev_day_levels=st._compute_prev_day_levels, _pdh_pdl_at=st._pdh_pdl_at,
         _compute_prev_htf_levels=st._compute_prev_htf_levels,
         _halving_context=st._halving_context, _halving_cfg=st._halving_cfg,
         HALVING_TF_DEFAULTS=HALVING_TF_DEFAULTS, _HIST_RANGE_SRC={})
exec(block, g)
rep = g['symbol_levels_report']

# ۱) نام نماد
for raw, want in (('btc', 'BTCUSDT'), ('ETH/USDT', 'ETHUSDT'), (' sol ', 'SOLUSDT'), ('1000pepe', '1000PEPEUSDT')):
    assert g['_levels_symbol'](raw) == want, (raw, g['_levels_symbol'](raw))
assert g['_levels_symbol']('') is None and g['_levels_symbol']('a b$') is None
print('1 symbol parsing ok')

# ۲) گزارش کامل با منبع Binance
g['_HIST_RANGE_SRC']['BTCUSDT'] = ('Binance', (400.0, 5.0))
text, kb = rep(1, 'btc')
print(text)
assert 'سطوح مهم BTCUSDT' in text and 'سقف تاریخی: `400`' in text and 'کف تاریخی: `5`' in text
assert 'منبع: Binance' in text and 'جایگاه قیمت در بازه' in text
assert '🔺' in text and '🔻' in text, 'سطوح نصف‌کردن بالا و پایین قیمت باید نمایش داده شوند'
assert 'دیروز' in text, 'سقف/کف دیروز'
cb = [b.get('callback_data') for row in kb['inline_keyboard'] for b in row]
assert '/lv_BTCUSDT' in cb and '/an_BTCUSDT' in cb and '/menu' in cb
print('2 full report ok')

# ۳) منبع جایگزین (Binance نبوده) درست نمایش داده شود
g['_HIST_RANGE_SRC'].clear()
text, _ = rep(1, 'BTC'); assert 'چون Binance در دسترس نبود' in text
print('3 fallback source label ok')

# ۴) سقف/کف در دسترس نیست
state['rng'] = None
text, _ = rep(1, 'BTC'); assert 'سقف/کف تاریخی این نماد در دسترس نیست' in text
state['rng'] = (400.0, 5.0)
print('4 no range ok')

# ۵) بدون داده
state['df'] = pd.DataFrame()
text, kb = rep(1, 'XYZ'); assert text.startswith('❌') and kb is None
state['df'] = make_df()
print('5 no data ok')

# ۶) نماد نامعتبر
text, kb = rep(1, '$$'); assert text.startswith('⚠️') and kb is None
print('6 invalid symbol ok')
print('ALL OK')
