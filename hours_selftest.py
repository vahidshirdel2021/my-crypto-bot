"""تست آفلاین کلید «فقط در بهترین ساعات معامله اسکن کن». اجرا: python hours_selftest.py"""
import ast, os, time, calendar
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()
a = src.index("TRADE_HOURS_PROFILES = {"); b = src.index("# ===================== V3.44.33")
g = dict(time=time); exec(src[a:b], g)
ok = g['_in_trade_hours']
def at(h, m=0): return calendar.timegm((2026, 10, 19, h, m, 0))      # دوشنبه، UTC
S = {'hours_filter_enabled': True, 'hours_profile': 'both'}
# خاموش = همیشه مجاز
assert all(ok({'hours_filter_enabled': False}, at(h))[0] for h in range(24))
# لندن + نیویورک
for h, m, exp in [(6, 59, False), (7, 0, True), (9, 59, True), (10, 0, False), (12, 29, False), (12, 30, True), (16, 59, True), (17, 0, False), (23, 0, False), (3, 0, False)]:
    assert ok(S, at(h, m))[0] is exp, (h, m)
S['hours_profile'] = 'london'; assert ok(S, at(8))[0] and not ok(S, at(14))[0]
S['hours_profile'] = 'ny'; assert ok(S, at(14))[0] and not ok(S, at(8))[0]
S['hours_profile'] = 'نامعتبر'; assert ok(S, at(8))[0] and ok(S, at(14))[0] and not ok(S, at(3))[0]    # پروفایل خراب = پیش‌فرض 'both'
txt = ok({'hours_filter_enabled': True, 'hours_profile': 'both'}, at(3))[1]
assert '07:00–10:00 UTC (10:30–13:30 تهران)' in txt and '12:30–17:00 UTC (16:00–20:30 تهران)' in txt, txt
# ورود سریع/صف اولویت‌دار: در حلقه‌ی اسکن فقط واچ‌لیست عادی خالی می‌شود
seg = src[src.index("_hrs_ok, _hrs_why = _in_trade_hours(s)"):][:700]
assert 'watchlist = []' in seg and "pw = s.get('priority_watch')" in src[src.index("_hrs_ok, _hrs_why"):][:2500]
# منو
fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == 'trade_filter_management_keyboard')
G = dict(get_session=lambda c: {'strategy_config': {}}, GATE_REGISTRY={}, gate_on=lambda s, k: False, _fav_cfg=lambda s: (0.3, 1.0, 900),
         _fav_max_label=lambda s: '', _fav_max_mode=lambda s: 'r', regime_advanced_on=lambda: False, _filter_info=lambda k: (k, ''),
         TOUCH_AUTO_LABELS={'all': ''}, _be_cfg=lambda s: (1.0, 0.5), TRAIL_PROFILES={'balanced': ('م',)}, _trail_profile_key=lambda s: 'balanced',
         TRADE_HOURS_PROFILES=g['TRADE_HOURS_PROFILES'], _hours_profile_key=g['_hours_profile_key'])
exec(ast.get_source_segment(src, fn), G)
cb = [x['callback_data'] for row in G['trade_filter_management_keyboard'](1, 'limits')['inline_keyboard'] for x in row if 'callback_data' in x]
assert '/toggle_hours' in cb and '/hours_profile_next' in cb and cb.index('/toggle_hours') < cb.index('/toggle_block_buy'), cb
for needle in ["'hours_filter_enabled': False", "'limits': ['hours',", "if cl == '/toggle_hours':", "if cl == '/hours_profile_next':"]:
    assert needle in src, needle
print('ALL OK')
