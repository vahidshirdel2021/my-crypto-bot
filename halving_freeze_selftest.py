"""V3.44.154: با «k پویا» خاموش عمق سطوح قفل است و با لغزش ATR عوض نمی‌شود. اجرا: python3 halving_freeze_selftest.py"""
import os, sys, tempfile, json, importlib
TMP = tempfile.mkdtemp()
os.environ['HALVING_FROZEN_PATH'] = os.path.join(TMP, 'frozen.json')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import strategy as st

N = 300
def mk(atr, tf_ms=900000):
    c = np.full(N, 100.0)
    return pd.DataFrame({'timestamp': np.arange(N) * float(tf_ms), 'open': c, 'high': c + 1, 'low': c - 1, 'close': c,
                         'volume': np.ones(N), 'atr': np.full(N, atr)})

BASE = {'halving_model_enabled': True, 'halving_high': 200.0, 'halving_low': 50.0, 'halving_k_atr': 2.0,
        'halving_min_depth': 3, 'halving_max_depth': 10, 'halving_dynamic_k': False, 'halving_btc_dynamic_k': False}

def depth(atr, cfg, idx=None, tf_ms=900000):
    d = mk(atr, tf_ms)
    return st._halving_context(d, (N - 2) if idx is None else idx, st._halving_cfg(cfg))['depth']

def reset():
    st.halving_frozen_reset()

# ATR دو مقدار بسیار نزدیک که بدون قفل عمق را یک پله عوض می‌کنند (همان لغزش ریز)
reset()
nofreeze = {**BASE, 'halving_depth_freeze': False}
lo_atr = hi_atr = None
for a in np.arange(0.5, 3.0, 0.0005):
    if depth(a, nofreeze) != depth(a + 0.0005, nofreeze):
        lo_atr, hi_atr = a, a + 0.0005
        break
assert lo_atr is not None and depth(lo_atr, nofreeze) == depth(hi_atr, nofreeze) + 1

# ۱) کلید خاموش: عمق اولین سنجش می‌ماند، هرچه ATR بعدی شود
reset()
d0 = depth(lo_atr, BASE)
assert depth(hi_atr, BASE) == d0 and depth(hi_atr * 3, BASE) == d0 and depth(hi_atr / 3, BASE) == d0

# ۲) k پویا (تک‌نماد) روشن: قفل نیست و از ATR می‌آید
reset()
dyn = {**BASE, 'halving_dynamic_k': True}
a1, a2 = depth(lo_atr, dyn), depth(hi_atr * 3, dyn)
assert a1 != a2

# ۳) تغییر k (دستی یا از BTC) یا حداکثر عمق = کلید جدید = از ATR فعلی
reset()
d_k2 = depth(lo_atr, BASE)
d_k4 = depth(lo_atr, {**BASE, 'halving_k_atr': 4.0})
assert d_k4 == d_k2 - 1                                              # k دو برابر → یک پله درشت‌تر
assert depth(hi_atr, {**BASE, 'halving_k_atr': 4.0}) == d_k4          # و آن هم قفل شد
assert depth(hi_atr, BASE) == d_k2                                    # برگشت به k=2: همان قفل قبلی
assert depth(lo_atr, {**BASE, 'halving_max_depth': d_k2 - 1}) == d_k2 - 1

# ۴) تایم‌فریم دیگر = قفل جدا
reset()
assert depth(lo_atr, BASE, tf_ms=900000) == d0
assert depth(hi_atr, BASE, tf_ms=300000) == depth(hi_atr, nofreeze)   # ۵ دقیقه‌ای از ATR خودش قفل می‌شود
assert depth(lo_atr, BASE, tf_ms=900000) == d0                         # ۱۵ دقیقه‌ای دست‌نخورده

# ۵) سقف/کف تغییر کند (سقف جدید) = کلید جدید
reset()
depth(lo_atr, BASE)
assert depth(lo_atr, {**BASE, 'halving_high': 400.0}) == depth(lo_atr, {**nofreeze, 'halving_high': 400.0})

# ۶) بک‌تست (halving_depth_freeze=False) و کندل‌های تاریخی (idx قدیمی) قفل نمی‌شوند و چیزی ثبت نمی‌کنند
reset()
assert depth(lo_atr, nofreeze) != depth(hi_atr, nofreeze)
assert depth(lo_atr, BASE, idx=100) != depth(hi_atr, BASE, idx=100)
assert not st._HV_FROZEN

# ۷) سوئیچ محیطی
reset()
st.HALVING_FREEZE_ON = False
assert depth(lo_atr, BASE) != depth(hi_atr, BASE)
st.HALVING_FREEZE_ON = True

# ۸) ماندگاری: بعد از «ری‌استارت» همان عمق برمی‌گردد؛ ریست همه را پاک می‌کند
reset()
d0 = depth(lo_atr, BASE)
saved = json.load(open(os.environ['HALVING_FROZEN_PATH']))
assert len(saved) == 1 and list(saved.values()) == [d0]
st._HV_FROZEN.clear()
st._hv_frozen_load()
assert depth(hi_atr, BASE) == d0
assert st.halving_frozen_reset() == 1 and json.load(open(os.environ['HALVING_FROZEN_PATH'])) == {}

# ۹) بک‌تست‌های داخل ربات قفل را خاموش می‌کنند
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()
assert src.count("cfg['halving_depth_freeze'] = False") == 2
print('halving_freeze_selftest OK')
