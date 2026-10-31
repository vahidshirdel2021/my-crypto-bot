"""V3.44.87: منوی «قوانین معامله (فیلترها)» بر اساس موضوع دسته‌بندی شده؛ هر فیلتر فقط در دسته‌ی خودش است."""
import ast, os, re
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()
tree = ast.parse(src)
fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'trade_filter_management_keyboard')
a = src.index("GATE_REGISTRY = {"); b = src.index("\n}\n", a)
REG = {m.group(1): (m.group(2), m.group(3) == 'True', m.group(4), '') for m in
       re.finditer(r"^\s*'((?:gate_|sweep_|use_)[a-z0-9_]+)':\s*\('([^']*)',\s*(True|False),\s*'([a-z_]+)'", src[a:b + 3], re.M)}
S = {'strategy_config': {}, 'touch_auto_mode': 'all', 'fav_confirm_enabled': False}
g = dict(get_session=lambda c: S, GATE_REGISTRY=REG, gate_on=lambda s, k: REG[k][1], _fav_cfg=lambda s: (0.3, 1.0, 900),
         _fav_max_label=lambda s: '1R', _fav_max_mode=lambda s: 'r', regime_advanced_on=lambda: False,
         _filter_info=lambda k, s=None: (k, ''), TOUCH_AUTO_LABELS={'all': 'همه'}, _be_cfg=lambda s: (1.0, 0.5),
         TRAIL_PROFILES={'balanced': ('متعادل',)}, _trail_profile_key=lambda s: 'balanced',
         _profit_thr=lambda s, k: 5.0, is_restricted_user=lambda c: False)
exec(ast.get_source_segment(src, fn), g)
kb = g['trade_filter_management_keyboard']


def cbs(sec):
    return [b['callback_data'] for row in kb(1, sec)['inline_keyboard'] for b in row if 'callback_data' in b]


# منوی اصلی: همه‌ی دسته‌ها مستقیم باز می‌شوند
main = cbs(None)
for c in ('/preset_menu', '/trade_filter_level', '/trade_filter_structure', '/trade_filter_momentum', '/trade_filter_btceth',
          '/trade_filter_regime', '/trade_filter_entry_rules', '/trade_filter_timing', '/trade_filter_quality',
          '/trade_filter_entry_warn', '/trade_filter_experimental', '/trade_filter_exit', '/trade_filter_limits', '/trade_filter_tools', '/menu'):
    assert c in main, c
assert '/trade_filter_entry' not in main and '/trade_filter_entry_filter' not in main, main

EXPECT = {
    'level': ['gate_fc_level_enabled', 'gate_fc_ylevel_enabled', 'gate_pd_level_enabled', 'gate_traded_level_enabled'],
    'structure': ['gate_touch_pattern_vote_enabled', 'gate_touch_dir_fixed_enabled', 'sweep_require_reclaim', 'sweep_require_reversal_candle', 'sweep_enable_retest_continuation'],
    'momentum': ['gate_fc_rsi_enabled', 'gate_fc_macd_enabled', 'gate_fc_adx_enabled', 'gate_fc_vol_enabled'],
    'btceth': ['gate_fc_btceth_enabled', 'gate_fc_btcpat_enabled', 'gate_fc_btcside_enabled', 'gate_btceth_aligned_enabled', 'gate_btc_candle_enabled', 'gate_btc_front_level_enabled', 'gate_btc_chop_enabled'],
    'regime': ['gate_symbol_structure_block_enabled', 'gate_fc_symreg_enabled', 'gate_fc_tf_enabled', 'gate_fc_h4_enabled', 'gate_final_regime_enabled', 'gate_h4_tier_enabled'],
    'timing': ['gate_4h_close_block_enabled', 'gate_cooldown_enabled', 'gate_risk_guard_enabled'],
    'quality': ['gate_min_score_enabled', 'gate_min_rr_enabled', 'gate_max_sl_atr_enabled', 'gate_fee_ratio_enabled', 'use_edge_proxy_gate', 'gate_open_fee_ratio_enabled', 'gate_total_risk_cap_enabled'],
    'experimental': ['gate_inverse_trading_enabled', 'gate_reversal_contra_enabled'],
}
seen = []
for sec, keys in EXPECT.items():
    got = [c[len('/toggle_gate_'):] for c in cbs(sec) if c.startswith('/toggle_gate_')]
    assert sorted(got) == sorted(keys), (sec, set(got) ^ set(keys))
    assert all(REG[k][2] == sec for k in keys), sec
    assert '/trade_filter_management' in cbs(sec) and '/menu' in cbs(sec), sec
    seen += got
# صفحه‌ی رژیم کلید «رژیم دقیق‌تر» را هم دارد
assert '/toggle_regime_adv' in cbs('regime')

# صفحه‌ی «رأی‌گیری و ورود»: فقط کلید رأی‌گیری + ورود خودکار + تایید حرکت (بدون کلیدهای دسته‌های دیگر)
rul = cbs('entry_rules')
need = {'/toggle_gate_gate_touch_vote_enabled', '/touch_auto_next', '/toggle_sweep_confirm', '/toggle_fav_confirm', '/toggle_fav_close5m', '/toggle_fav_close15m', '/fav_min_r_next',
        '/fav_max_r_next', '/fav_wait_next', '/fav_max_mode_toggle', '/fav_queue', '/fav_stats', '/trade_filter_management', '/menu'}
assert set(rul) == need, set(rul) ^ need
assert rul.index('/toggle_gate_gate_touch_vote_enabled') < rul.index('/touch_auto_next') < rul.index('/toggle_fav_confirm')
seen += ['gate_touch_vote_enabled']

# هر کلید رجیستری دقیقاً در یک دسته است؛ چیزی گم یا تکراری نمی‌شود
assert sorted(seen) == sorted(REG), set(seen) ^ set(REG)
assert len(seen) == len(set(seen))
# هشدارها
assert '/toggle_trend_warn' in cbs('entry_warn') and '/trade_filter_management' in cbs('entry_warn')
# مسیریاب و متن صفحه‌ها
handler = src.split("# V3.43.31: هندلر صفحه‌های زیرمنوی")[1][:1200]
for sec in ('level', 'momentum', 'btceth', 'regime', 'timing', 'experimental', 'entry_rules', 'entry_warn', 'structure', 'quality'):
    assert f"'/trade_filter_{sec}'" in handler, sec
    assert f"'{sec}'" in src.split('_FILTER_SECTION_TITLES = {')[1].split('\n}\n')[0], sec
    assert f"'{sec}'" in src.split('has_toggles = section in (')[1][:240], sec
# تنظیم‌های تایید حرکت/رأی‌گیری به همین صفحه برمی‌گردند
assert src.count("trade_filter_management_keyboard(chat_id, 'entry_rules'))") == 7
print('entry_menu_selftest OK', len(seen))

# V3.44.28: منوی «خروج و حفظ سود» دو کلید بستن سر به سر (هشدار / خودکار) و دو دکمه‌ی آستانه دارد
ex = cbs('exit')
assert all(c in ex for c in ('/toggle_be_alert', '/toggle_be_auto', '/be_profit_next', '/be_loss_next', '/toggle_trail', '/trail_profile_next')), ex
print('exit menu breakeven buttons OK')
