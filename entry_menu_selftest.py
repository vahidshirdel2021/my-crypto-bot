"""V3.44.19: منوی «شرایط ورود به معامله» به دو زیرمنوی «🧱 فیلترها» و «🎯 شرایط ورود» تقسیم شده است."""
import ast, os, re
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()
tree = ast.parse(src)
fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'trade_filter_management_keyboard')
a = src.index("GATE_REGISTRY = {"); b = src.index("\n}\n", a)
REG = {m.group(1): (m.group(2), m.group(3) == 'True', m.group(4), '') for m in
       re.finditer(r"^\s*'(gate_[a-z0-9_]+)':\s*\('([^']*)',\s*(True|False),\s*'([a-z_]+)'", src[a:b + 3], re.M)}
S = {'strategy_config': {}, 'touch_auto_mode': 'all', 'fav_confirm_enabled': False}
g = dict(get_session=lambda c: S, GATE_REGISTRY=REG, gate_on=lambda s, k: REG[k][1], _fav_cfg=lambda s: (0.3, 1.0, 900),
         _fav_max_label=lambda s: '1R', _fav_max_mode=lambda s: 'r', regime_advanced_on=lambda: False,
         _filter_info=lambda k: (k, ''), TOUCH_AUTO_LABELS={'all': 'همه'}, _be_cfg=lambda s: (1.0, 0.5),
         TRAIL_PROFILES={'balanced': ('متعادل',)}, _trail_profile_key=lambda s: 'balanced')
exec(ast.get_source_segment(src, fn), g)
kb = g['trade_filter_management_keyboard']


def cbs(sec):
    return [b['callback_data'] for row in kb(1, sec)['inline_keyboard'] for b in row if 'callback_data' in b]


ent = cbs('entry')
assert '/trade_filter_entry_filter' in ent and '/trade_filter_entry_rules' in ent and '/trade_filter_entry_warn' in ent, ent
flt, rul = cbs('entry_filter'), cbs('entry_rules')
fc = {f'/toggle_gate_{k}' for k in REG if k.startswith('gate_fc_')} | {'/toggle_gate_gate_btceth_aligned_enabled'}
assert set(flt) == fc | {'/trade_filter_entry', '/menu'}, set(flt) ^ (fc | {'/trade_filter_entry', '/menu'})
need = {'/toggle_gate_gate_touch_vote_enabled', '/toggle_gate_gate_touch_pattern_vote_enabled', '/touch_auto_next', '/toggle_sweep_confirm',
        '/toggle_fav_confirm', '/fav_min_r_next', '/fav_max_r_next', '/fav_wait_next', '/fav_max_mode_toggle', '/fav_queue', '/fav_stats',
        '/toggle_gate_gate_4h_close_block_enabled', '/toggle_gate_gate_inverse_trading_enabled', '/toggle_gate_gate_final_regime_enabled', '/trade_filter_entry', '/menu'}
assert set(rul) == need, set(rul) ^ need
assert rul.index('/toggle_gate_gate_touch_vote_enabled') < rul.index('/touch_auto_next') < rul.index('/toggle_fav_confirm')   # رأی‌گیری بالاتر از تایید حرکت
# هر کلید رجیستری دقیقاً در یکی از دو صفحه‌ی «ورود» است و چیزی گم یا تکراری نمی‌شود
ent_gates = {k for k, v in REG.items() if v[2] in ('entry_filter', 'entry_rules')}
assert ent_gates == {c[len('/toggle_gate_'):] for c in flt + rul if c.startswith('/toggle_gate_')} and len(flt + rul) == len(set(flt + rul)) + 2
# مسیریاب و متن صفحه‌ها
assert "'/trade_filter_entry_rules'" in src.split("# V3.43.31: هندلر صفحه‌های زیرمنوی")[1][:400]
for sec in ('entry_filter', 'entry_rules'):
    assert sec in src.split('_FILTER_SECTION_TITLES = {')[1].split('}')[0] and f"'{sec}'" in src.split('has_toggles = section in (')[1][:140]
# بازگشت دکمه‌های تنظیم تایید حرکت/رأی‌گیری به همین صفحه‌ی «شرایط ورود»
assert src.count("trade_filter_management_keyboard(chat_id, 'entry_rules'))") == 5
for k in ('gate_touch_vote_enabled', 'gate_touch_pattern_vote_enabled', 'gate_4h_close_block_enabled', 'gate_inverse_trading_enabled', 'gate_final_regime_enabled'):
    assert REG[k][2] == 'entry_rules', k
print('entry_menu_selftest OK', len(flt), len(rul))

# V3.44.28: منوی «خروج و حفظ سود» دو کلید بستن سر به سر (هشدار / خودکار) و دو دکمه‌ی آستانه دارد
ex = cbs('exit')
assert all(c in ex for c in ('/toggle_be_alert', '/toggle_be_auto', '/be_profit_next', '/be_loss_next', '/toggle_trail', '/trail_profile_next')), ex
print('exit menu breakeven buttons OK')
