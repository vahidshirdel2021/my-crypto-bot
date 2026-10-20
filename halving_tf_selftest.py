"""V3.44.40: پیش‌فرض k و عمق درخت برای هر تایم‌فریم جدا. اجرا: python3 halving_tf_selftest.py"""
import os
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()
a = src.index("HALVING_TF_DEFAULTS = {"); b = src.index("def _p4_sync_tags(")
g = {}
exec(src[a:b].replace("\n\n\ndef _p4_keep_flags", "\n\n\ndef _p4_keep_flags"), g)
P, A, S = g['_halving_tf_params'], g['_halving_tf_apply'], g['_halving_tf_store']
assert P({}, '5min') == {'halving_k_atr': 3.0, 'halving_max_depth': 12}
assert P({}, '15min') == {'halving_k_atr': 4.0, 'halving_max_depth': 10}
assert P({}, '1hour') == {}
# نشست قدیمی با مقدار سراسری 4/10 → روی ۵ دقیقه 3/12 می‌شود
cfg = {'halving_k_atr': 4.0, 'halving_max_depth': 10}
A(cfg, '5min'); assert (cfg['halving_k_atr'], cfg['halving_max_depth']) == (3.0, 12)
A(cfg, '15min'); assert (cfg['halving_k_atr'], cfg['halving_max_depth']) == (4.0, 10)
# تایم‌فریم بدون پیش‌فرض: مقدار فعلی دست‌نخورده
A(cfg, '1hour'); assert (cfg['halving_k_atr'], cfg['halving_max_depth']) == (4.0, 10)
# تغییر دستی روی ۵ دقیقه فقط برای ۵ دقیقه می‌ماند
A(cfg, '5min'); cfg['halving_k_atr'] = 5.0; S(cfg, '5min')
A(cfg, '15min'); assert (cfg['halving_k_atr'], cfg['halving_max_depth']) == (4.0, 10)
A(cfg, '5min'); assert (cfg['halving_k_atr'], cfg['halving_max_depth']) == (5.0, 12)
# مسیر کانال
assert P(cfg, '15min')['halving_k_atr'] == 4.0 and P(cfg, '5min')['halving_k_atr'] == 5.0
print('halving tf selftest OK')
