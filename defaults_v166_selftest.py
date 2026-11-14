# -*- coding: utf-8 -*-
"""V3.44.166 selftest: پیش‌فرض‌های جدید فیلترها (فهرست شماره‌دار کاربر) + مهاجرت یک‌باره."""
import sys, types, os, tempfile
for name in ('aiohttp', 'ccxt', 'ccxt.async_support'):
    try:
        __import__(name)
    except Exception:
        sys.modules[name] = types.ModuleType(name)
_tmp = tempfile.mkdtemp()
os.environ.update({'TELEGRAM_TOKEN': '123:abc', 'ADMIN_CHAT_IDS': '111', 'BOT_DB_PATH': os.path.join(_tmp, 'bot.sqlite3'),
                   'PRESETS_CUSTOM_PATH': os.path.join(_tmp, 'presets_custom.json'), 'FUNNEL_DIR': os.path.join(_tmp, 'funnel'),
                   'TELEGRAM_SKIP_BACKLOG': 'true'})
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
bot = importlib.import_module('bot')
import presets as P
import strategy as S
bot.init_db()

OFF = ['gate_touch_pattern_vote_enabled', 'sweep_require_reclaim', 'sweep_require_reversal_candle', 'sweep_enable_retest_continuation',
       'gate_4h_close_block_enabled', 'gate_fc_tf_enabled', 'gate_btc_front_level_enabled', 'gate_btc_chop_enabled', 'gate_pd_level_enabled',
       'gate_fc_ylevel_enabled', 'gate_fc_rsi_enabled', 'gate_fc_macd_enabled', 'gate_fc_vol_enabled', 'gate_fc_adx_enabled',
       'gate_min_score_enabled', 'gate_fee_ratio_enabled', 'use_edge_proxy_gate', 'gate_open_fee_ratio_enabled', 'gate_total_risk_cap_enabled']
WARN = ['trend_warn_enabled', 'ind_warn_enabled', 'symbol_tf_regime_warn_enabled', 'symbol_h4_regime_warn_enabled']
KEPT_ON = ['gate_touch_vote_enabled', 'gate_min_rr_enabled', 'gate_max_sl_atr_enabled', 'gate_cooldown_enabled', 'gate_risk_guard_enabled',
           'gate_traded_level_enabled', 'gate_fc_level_enabled']

# ۱) رجیستری گیت‌ها
for k in OFF:
    if k in bot.GATE_REGISTRY:
        assert bot.GATE_REGISTRY[k][1] is False, ('registry', k)
        assert bot.gate_on({'strategy_config': {}}, k) is False, ('gate_on', k)
assert bot.GATE_REGISTRY['gate_touch_dir_fixed_enabled'][1] is True
for k in KEPT_ON:
    assert bot.GATE_REGISTRY[k][1] is True, ('should stay on', k)

# ۲) پریست پایه و پیش‌فرض استراتژی
for k in OFF:
    assert P.BASE_CFG[k] is False, ('presets', k)
assert P.BASE_CFG['sweep_require_confirmation_candle'] is False and S.STRATEGY_DEFAULTS['sweep_require_confirmation_candle'] is False
assert P.BASE_CFG['gate_touch_dir_fixed_enabled'] is True
for k in KEPT_ON:
    if k in P.BASE_CFG:
        assert P.BASE_CFG[k] is True, ('preset should stay on', k)
for k in ('gate_fee_ratio_enabled', 'gate_min_score_enabled', 'sweep_require_reclaim', 'sweep_require_reversal_candle', 'sweep_enable_retest_continuation'):
    assert S.STRATEGY_DEFAULTS[k] is False, ('strategy default', k)
assert S.HALVING_DEFAULTS['gate_pd_level_enabled'] is False
assert bot.SWEEP_REQUIRE_CONFIRMATION_CANDLE_DEFAULT is False

# ۳) هشدارها در نشست جدید
d = bot.default_session()
for k in WARN:
    assert d[k] is False, ('warn default', k)
assert d['strategy_config']['sweep_require_confirmation_candle'] is False

# ۴) مهاجرت یک‌باره روی نشست قدیمی: مقدارهای روشنِ قدیمی خاموش می‌شوند، بعدش انتخاب دستی حفظ می‌شود
old = {'strategy_config': {**{k: True for k in OFF}, 'gate_touch_dir_fixed_enabled': False, 'gate_min_rr_enabled': True},
       **{k: True for k in WARN}}
s1 = bot.normalize_session(old)
for k in OFF:
    assert s1['strategy_config'][k] is False, ('migrated', k)
assert s1['strategy_config']['gate_touch_dir_fixed_enabled'] is True
assert s1['strategy_config']['gate_min_rr_enabled'] is True           # دست‌نخورده
for k in WARN:
    assert s1[k] is False, ('migrated warn', k)
assert s1['filter_defaults_v166'] is True
s1['strategy_config']['gate_fc_rsi_enabled'] = True                   # کاربر دستی روشن می‌کند
s1['trend_warn_enabled'] = True
s2 = bot.normalize_session(s1)                                        # بار دوم: دوباره اعمال نمی‌شود
assert s2['strategy_config']['gate_fc_rsi_enabled'] is True and s2['trend_warn_enabled'] is True

# ۵) پریست ۳ (حالت پیش‌فرض): رأی‌دهنده‌های مومنتوم همان تعریف خودش را نگه می‌دارد (RSI/MACD/ADX جزو تعریف حالت‌های ۳ تا ۵)
c3, _ = P._default_full('3')
assert c3['gate_fc_rsi_enabled'] and c3['gate_fc_macd_enabled'] and c3['gate_fc_adx_enabled']
assert c3['gate_fc_tf_enabled'] is False and c3['gate_fc_ylevel_enabled'] is False
print('defaults_v166_selftest OK')
