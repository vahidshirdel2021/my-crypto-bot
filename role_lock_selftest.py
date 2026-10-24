"""V3.44.59: قفل نقش‌ها (کاربر عادی / ادمین). اجرا: python3 role_lock_selftest.py"""
import os, re
import access_policy as ap
import ui

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, 'bot.py'), encoding='utf-8').read()

# 1) دستورهای مجاز کاربر عادی
ALLOW = ['/start', '/menu', '/cancel', '/start_scan', '/stop_scan', '/reload_and_start', '/open_positions', '/positions',
         '/close_all_prompt', '/confirm_close_all', '/emergency_close_all', '/performance', '/performance_week', '/daily_pnl',
         '/today_trades', '/menu_settings', '/check_wizard', '/mode_paper', '/mode_real', '/set_bal_1000', '/set_margin_50',
         '/set_lev_5', '/set_max_3', '/set_max_0', '/set_tf_15m', '/real_pick_binance', '/real_use_bitunix', '/real_new_binance',
         '/manage_BTCUSDT', '/close_prompt_BTCUSDT', '/confirm_close_BTCUSDT', '/pclose_50_BTC', '/edit_sl_BTC', '/edit_tp_BTC',
         '/show_chart_BTC', '/assist_ok_ab12', '/assist_no_ab12', '/assist_rev_ab12', '/autotg_ok_r1', '/autotg_no_r1',
         '/qt_buy_BTC', '/qt_sell_ETH', '/qtm_buy_BTC', '/tw_qe_buy_t1', '/fq_qe_buy_f1', '/fq_rej_f1', '/cfm_abc', '/cfmno_abc',
         '/back:/menu', '/back:/menu_settings', '🔴 توقف اسکن', '🟢 شروع اسکن', '🏠 منوی اصلی', '/assist_pending',
         '/fee_menu', '/my_fee_report', '/check_entry_BTC', '/cancel_watch_BTC', '/start ref123']
for c in ALLOW:
    assert ap.user_command_allowed(c), ('should be allowed', c)

# 2) هر چیز مربوط به استراتژی/ادمین باید بسته باشد
DENY = ['/admin_panel', '/admin_access', '/admin_tests', '/admin_users_list', '/users', '/allow 123', '/audit', '/set_fee 5',
        '/setup_management', '/trade_filter_management', '/trade_filter_entry', '/trade_filter_limits', '/scenario_management',
        '/strategy_families_menu', '/signal_channel_settings', '/preset_menu', '/preset_export', '/preset_stats', '/preset_apply_x',
        '/market_report', '/btc_eth_regime', '/entry_diag', '/entry_diag_log', '/trade_audit', '/quality_report', '/export_trade_data',
        '/export_trade_pipeline', '/trade_tracking_menu', '/trade_pipeline', '/fav_queue', '/fav_stats', '/fav_star', '/review_list',
        '/menu_reports', '/menu_trading', '/manual_trade', '/pending_order_start', '/backtest_start', '/scan_signal_start',
        '/manage_watchlist', '/add_long_symbol', '/remove_short_symbol', '/watchlist_list', '/assist_ind_ab12', '/assist_menu',
        '/assist_stats', '/assist_expiry_cycle', '/toggle_halving_model', '/toggle_gate_x', '/toggle_scenario_x', '/toggle_setup_daily',
        '/toggle_signal_all3', '/toggle_regime_adv', '/toggle_btc_guard', '/halving_depth_cycle', '/halving_k_cycle', '/sl_up', '/tp_down',
        '/adx_up', '/set_max_same_2', '/set_dir_cooldown_60', '/profile_advanced', '/profile_balanced', '/apply_my_profile', '/save_my_profile',
        '/learn_menu', '/reset_stats_prompt', '/reset_stats_confirm', '/full_reset_prompt', '/full_reset_confirm', '/same_dir_menu',
        '/chreg', '/chlist', '/chind_5', '/fq_flt_r1', '/rvclear', '/touch_auto_next', '/hours_profile_next', '/trail_profile_next',
        '/back:/admin_panel', '/back:/trade_filter_management', '/set_tf_30m', '/set_lev_abc', '/manage_watchlist', '/unknown_new_command', '', None,
        'BTC', 'تحلیل', '/ADMIN_PANEL']
for c in DENY:
    assert not ap.user_command_allowed(c), ('should be denied', c)

# 3) هر دستوری که در process_command هست و به لیست مجاز نرسیده، پیش‌فرض بسته است (بررسی نمونه‌ای از کل کد)
a = src.index('def process_command(')
pc = src[a:a + 220000]
lits = set(re.findall(r"'(/[a-z0-9_]+)'", pc))
admin_like = [c for c in lits if re.match(r'^/(admin_|toggle_|trade_filter|halving_|fav_|preset_|setup_|scenario_|learn_|export_|entry_diag)', c)]
assert len(admin_like) > 30, len(admin_like)
for c in admin_like:
    assert not ap.user_command_allowed(c + 'x' if c.endswith('_') else c), c

# 4) کیبوردهای واقعی ربات: فیلتر برای کاربر عادی
def callbacks(mk):
    return [b.get('callback_data') for r in mk.get('inline_keyboard', []) for b in r if b.get('callback_data')]

main = ap.filter_markup(ui.get_main_menu_keyboard(True, True, False))
cbs = callbacks(main)
assert '/start_scan' in cbs or '/stop_scan' in cbs
assert '/open_positions' in cbs and '/performance' in cbs and '/menu_settings' in cbs
for hidden in ('/menu_reports', '/menu_trading', '/manual_trade', '/review_list', '/btc_eth_regime', '/admin_panel'):
    assert hidden not in cbs, hidden

settings = callbacks(ap.filter_markup(ui.get_settings_menu_keyboard()))
assert settings == ['/check_wizard', '/trade_mode_menu', '/menu'], settings      # V3.44.62: «🎯 حالت معامله» اضافه شد

perf = callbacks(ap.filter_markup(ui.get_performance_keyboard()))
assert set(perf) == {'/performance_today', '/performance_week', '/performance_month', '/performance', '/today_trades', '/menu'}, perf

# ویزارد اولیه نباید بشکند: همه‌ی دکمه‌ها (به‌جز ردیف‌های نمایشی) باید سالم بمانند
for kb in (ui.get_start_keyboard(), ui.get_balance_keyboard(), ui.get_margin_keyboard(), ui.get_leverage_keyboard(),
           ui.get_max_positions_keyboard()):
    assert callbacks(ap.filter_markup(kb)) == callbacks(kb)
tf_all = [c for c in callbacks(ui.get_timeframe_keyboard()) if c != '/dummy']
tf_user = callbacks(ap.filter_markup(ui.get_timeframe_keyboard()))
assert tf_user == tf_all and '/dummy' not in tf_user and any(c.startswith('/set_tf_') for c in tf_user), tf_user
for r in ap.filter_markup(ui.get_timeframe_keyboard())['inline_keyboard']:
    for b in r:
        assert 'دسته' not in b['text'] and 'نقدینگی' not in b['text'], b

# لیست پوزیشن‌ها / کارت پوزیشن
pos = callbacks(ap.filter_markup(ui.get_positions_keyboard([{'symbol': 'BTC', 'side': 'BUY'}])))
assert '/manage_BTC' in pos and '/close_longs_prompt' in pos and '/menu' in pos, pos
card_src = src[src.index('def trade_action_keyboard('):src.index('def close_confirm_keyboard(')]
assert "'/edit_sl_" in card_src and "'/close_prompt_" in card_src

# کیبورد ثابت پایین
bottom = ap.filter_markup(ui.get_bottom_menu_keyboard(True))
texts = [b['text'] for r in bottom['keyboard'] for b in r]
assert '🔄 پوزیشن‌ها' in texts and '💰 سود و زیان امروز' in texts and '🏠 منوی اصلی' in texts
assert '🧭 رژیم BTC/ETH' not in texts and '⏳ سیگنال‌های در حال تایید' not in texts
assert 'تحلیل' not in bottom['input_field_placeholder']
# ورودی تغییر نکرده
assert '🧭 رژیم BTC/ETH' in [b['text'] for r in ui.get_bottom_menu_keyboard(True)['keyboard'] for b in r]

# دکمه‌های url / web_app حفظ می‌شوند
mk = {'inline_keyboard': [[{'text': 'x', 'web_app': {'url': 'https://e.x'}}, {'text': 'y', 'url': 'https://t.v'}, {'text': 'bad', 'callback_data': '/admin_panel'}]]}
out = ap.filter_markup(mk)
assert [b['text'] for b in out['inline_keyboard'][0]] == ['x', 'y'] and len(mk['inline_keyboard'][0]) == 3

# 5) تشخیص نقش
assert not ap.is_restricted(111, {111}) and ap.is_restricted(222, {111})
assert not ap.is_restricted(222, set()), 'ADMIN خالی => قفل خاموش (مالک بیرون نماند)'
assert not ap.is_restricted(-1001234, {111}), 'کانال/گروه فیلتر نمی‌شود'
assert not ap.is_restricted(222, {111}, enabled=False)
assert not ap.is_restricted('abc', {111})

# 6) سیم‌کشی در bot.py
for needle in ("def is_restricted_user(", "def _deny_restricted(", "not _ap.user_command_allowed(cmd)",
               "_ap.filter_markup(payload['reply_markup'])", "if is_restricted_user(chat_id): markup = _ap.filter_markup(markup)",
               "current_state not in ('WAIT_REAL_API_KEY', 'WAIT_REAL_API_SECRET')", "startswith(('/chind_', '/assist_ind_', '/fq_flt_'))",
               "if is_restricted_user(chat_id):\n        # V3.44.59: کاربر عادی فقط خطوط ورود"):
    assert needle in src, needle
assert src.count("if is_restricted_user(chat_id): markup = _ap.filter_markup(markup)") == 2
# گیت دستورها باید قبل از هر منطق دیگرِ process_command باشد
i_gate = src.index('not _ap.user_command_allowed(cmd)')
i_back = src.index("if str(cmd).startswith('/back:'):", i_gate)
assert 0 < i_back - i_gate < 400

print('role_lock_selftest OK')
