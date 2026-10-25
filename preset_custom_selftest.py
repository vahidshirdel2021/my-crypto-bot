"""تست ذخیره‌ی دلخواه هر کلید پریست: python preset_custom_selftest.py"""
import os, tempfile, json
import presets as P

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, info)

d = tempfile.mkdtemp()
P.set_custom_path(os.path.join(d, 'presets_custom.json'))

s = {'strategy_config': {}}
P.apply_preset(s, '3')
check("بدون ذخیره: پیش‌فرض کد", not P.has_custom('3') and s['touch_auto_mode'] == 'majority')

# تنظیم دستی و ذخیره فقط در کلید ۳
s['strategy_config']['halving_k_atr'] = 2.0
s['strategy_config']['halving_max_depth'] = 14
s['strategy_config']['gate_fc_macd_enabled'] = False
s['strategy_config']['halving_tf'] = {'15min': {'halving_k_atr': 2.0, 'halving_max_depth': 14}}
s['touch_auto_mode'] = 'minus1'
n = P.save_custom(s, '3')
check("ذخیره موفق و کلید ۳ فعال", n and s['active_preset'] == '3', n)
check("فقط کلید ۳ ذخیره شد", P.has_custom('3') and not any(P.has_custom(k) for k in '1245'))
check("بلافاصله بعد از ذخیره هیچ تفاوتی با پریست نیست", P.preset_diff(s, '3') == [], P.preset_diff(s, '3'))

# جلسه‌ی تازه با کلید ۳ همان را می‌گیرد
t = {'strategy_config': {}}
P.apply_preset(t, '3')
c = t['strategy_config']
check("اعمال کلید ۳ = نسخه‌ی ذخیره‌شده", c['halving_k_atr'] == 2.0 and c['halving_max_depth'] == 14 and c['gate_fc_macd_enabled'] is False and t['touch_auto_mode'] == 'minus1')
check("halving_tf ذخیره‌شده برگشت", c.get('halving_tf') == {'15min': {'halving_k_atr': 2.0, 'halving_max_depth': 14}})

# کلیدهای دیگر دست‌نخورده
u = {'strategy_config': {}}
P.apply_preset(u, '4')
check("کلید ۴ هنوز پیش‌فرض کد", u['touch_auto_mode'] == 'minus1' and u['strategy_config']['halving_k_atr'] == 4.0 and 'halving_tf' not in u['strategy_config'])
P.apply_preset(u, '5')
check("کلید ۵ هنوز پیش‌فرض کد", u['touch_auto_mode'] == 'all' and u['strategy_config']['gate_fc_macd_enabled'] is True)

# ذخیره‌ی مستقل کلید ۵ روی کلید ۳ اثر ندارد
v = {'strategy_config': {'gate_fc_vol_enabled': False}}
P.apply_preset(v, '5'); v['strategy_config']['gate_fc_vol_enabled'] = False; v['touch_auto_mode'] = 'majority'
P.save_custom(v, '5')
w = {'strategy_config': {}}; P.apply_preset(w, '3')
check("ذخیره‌ی کلید ۵ کلید ۳ را عوض نکرد", w['strategy_config']['halving_k_atr'] == 2.0 and w['touch_auto_mode'] == 'minus1')
w2 = {'strategy_config': {}}; P.apply_preset(w2, '5')
check("کلید ۵ نسخه‌ی خودش را دارد", w2['strategy_config']['gate_fc_vol_enabled'] is False and w2['touch_auto_mode'] == 'majority')

# تغییر دستی بعد از ذخیره در diff دیده می‌شود
w2['strategy_config']['gate_fc_rsi_enabled'] = False
check("تغییر دستی بعد از ذخیره = تفاوت", 'gate_fc_rsi_enabled' in P.preset_diff(w2, '5'))

# کلید جدیدی که بعداً به BASE_CFG اضافه شود پیش‌فرض می‌گیرد
P.BASE_CFG['__new_key__'] = 7
x = {'strategy_config': {}}; P.apply_preset(x, '3')
check("کلید جدید کد با فایل قدیمی هم پیش‌فرض می‌گیرد", x['strategy_config']['__new_key__'] == 7)
del P.BASE_CFG['__new_key__']

# بازگشت به پیش‌فرض
check("reset کلید ۳", P.reset_custom('3') is True and not P.has_custom('3') and P.has_custom('5'))
check("reset دوباره: چیزی نبود", P.reset_custom('3') is False)
y = {'strategy_config': {}}; P.apply_preset(y, '3')
check("بعد از reset پیش‌فرض کد", y['strategy_config']['halving_k_atr'] == 4.0 and y['strategy_config']['gate_fc_macd_enabled'] is True and 'halving_tf' not in y['strategy_config'])

# فایل خراب = پیش‌فرض، بدون کرش
open(P._custom_path(), 'w').write('{bad json')
z = {'strategy_config': {}}
check("فایل خراب: بدون کرش و پیش‌فرض", P.apply_preset(z, '5') and z['touch_auto_mode'] == 'all')

# بدون مسیر: ذخیره رد می‌شود
P.set_custom_path(None)
check("بدون مسیر ذخیره نمی‌شود", P.save_custom({'strategy_config': {}}, '3') is None)

# کیبورد: هر کلید دکمه‌ی ذخیره‌ی خودش را دارد
P.set_custom_path(os.path.join(d, 'k.json'))
P.save_custom({'strategy_config': {}}, '4')
cbs = [b['callback_data'] for r in P.keyboard({})['inline_keyboard'] for b in r]
check("دکمه‌ی ذخیره برای هر ۵ کلید", all(f'/preset_save_{n}' in cbs for n in '12345'))
check("دکمه‌ی پیش‌فرض فقط برای کلید ذخیره‌شده", '/preset_reset_4' in cbs and not any(f'/preset_reset_{n}' in cbs for n in '1235'))
check("متن منو بدون خطا", isinstance(P.menu_text({}), str) and '✏️' in P.menu_text({}))
print("\nALL PASS" if ok else "\nSOME FAILED")
raise SystemExit(0 if ok else 1)
