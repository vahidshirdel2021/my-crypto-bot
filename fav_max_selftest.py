"""تست آفلاین «سقف ورود بر اساس فاصله تا هدف». اجرا: python fav_max_selftest.py"""
import os
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()
a = src.index("def _fav_cfg(s):"); b = src.index("def _fav_move_r(")
g = dict(FAV_HARD_MAX_R=1.5)
exec(src[a:b], g)
eff = g['_fav_effective_max_r']
base = {'fav_confirm_min_r': 0.15, 'fav_confirm_max_r': 0.30, 'fav_confirm_max_tp_pct': 0.20}
# هدف ۵R دور: سقف = 1.0R ؛ هدف ۱.۵R: 0.30R
assert abs(eff(base, 100, 99, 105) - 1.0) < 1e-9
assert abs(eff(base, 100, 99, 101.5) - 0.30) < 1e-9
# سقف سخت ۱.۵R
assert abs(eff(base, 100, 99, 120) - 1.5) < 1e-9
# کف: همیشه از min_r بیشتر
assert eff(dict(base, fav_confirm_max_tp_pct=0.10), 100, 99, 101.3) >= 0.15 + 0.05 - 1e-9
# حالت ثابت
assert eff(dict(base, fav_confirm_max_mode='r'), 100, 99, 105) == 0.30
# فروش (قیمت‌های وارونه) و داده‌ی نامعتبر
assert abs(eff(base, 100, 101, 95) - 1.0) < 1e-9
assert eff(base, 100, 100, 95) == 0.30
print('ALL OK')
