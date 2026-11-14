"""تست پریست «معمولی» (تنها پریست): python preset_selftest.py"""
import presets as P

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, info)

check("فقط یک پریست: معمولی", list(P.PRESETS) == ['3'] and P.PRESETS['3']['label'] == 'معمولی' and P.DEFAULT_MODE == '3')
check("انتخاب حالت معامله حذف شده", not any(hasattr(P, n) for n in ('TRADE_MODES', 'mode_keyboard', 'mode_menu_text', 'wizard_mode_keyboard', 'wizard_mode_text', 'panel_line')))

s = {'strategy_config': {'halving_k_atr': 2.0, 'halving_max_depth': 14, 'gate_fc_rsi_enabled': False,
                         'gate_btceth_aligned_enabled': True, 'scenario_7_enabled': True,
                         'halving_tf': {'15min': {'halving_k_atr': 2.0, 'halving_max_depth': 14}}},
     'trend_warn_enabled': True, 'touch_auto_mode': 'all', 'fav_confirm_enabled': False,
     'trail_enabled': False, 'be_close_auto_enabled': False}
check("اعمال معمولی", P.apply_preset(s, '3') and s['active_preset'] == '3')
for old in ('1', '2', '4', '5', '9'):
    check(f"کلید حذف‌شده {old} رد می‌شود و پریست فعال عوض نمی‌شود", P.apply_preset(s, old) is False and s['active_preset'] == '3')
c = s['strategy_config']
check("k=4 و عمق ۱۰ و انتخاب دستی هر تایم پاک شد", c['halving_k_atr'] == 4.0 and c['halving_max_depth'] == 10 and 'halving_tf' not in c)
check("رأی‌دهنده‌ها: رژیم ۵/۱۵ (کلوز + سقف/کف دیروز) + مومنتوم؛ الگوی BTC/حجم/۴ساعته/BTC-ETH خاموش",
      all(c[k] for k in ('gate_fc_level_enabled', 'gate_fc_rsi_enabled', 'gate_fc_macd_enabled', 'gate_fc_adx_enabled'))
      and not any(c[k] for k in ('gate_fc_btcpat_enabled', 'gate_fc_vol_enabled', 'gate_fc_h4_enabled', 'gate_fc_btceth_enabled')))
check("جهت ثابت از الگو روشن و رأی الگو خاموش", c['gate_touch_dir_fixed_enabled'] is True and c['gate_touch_pattern_vote_enabled'] is False)
check("BTC/ETH aligned، رژیم مرحله‌ی آخر، معکوس، رتبه‌ی ۴ساعته خاموش", not any(c[k] for k in ('gate_btceth_aligned_enabled', 'gate_final_regime_enabled', 'gate_inverse_trading_enabled', 'gate_h4_tier_enabled')))
check("حالت‌های ۱ تا ۶ روشن و ۷ خاموش", all(c[f'scenario_{n}_enabled'] for n in range(1, 7)) and c['scenario_7_enabled'] is False)
check("ورود خودکار اکثریت ساده", s['touch_auto_mode'] == 'majority')
check("صبر برای تایید: روشن با 0.15R / ۲۰٪ مسیر / ۳۰ دقیقه", s['fav_confirm_enabled'] is True and s['fav_confirm_min_r'] == 0.15 and s['fav_confirm_max_mode'] == 'tp' and s['fav_confirm_max_tp_pct'] == 0.20 and s['fav_confirm_wait_sec'] == 1800)
check("سربه‌سر خودکار و تریلینگ روشن", s['be_close_auto_enabled'] is True and s['trail_enabled'] is True)
check("هشدارها خاموش", s['trend_warn_enabled'] is False and s['symbol_h4_regime_warn_enabled'] is False)
check("بدون تغییر دستی: diff خالی", P.preset_diff(s) == [])
check("تگ معامله", P.trade_tag(s) == {'preset': '3', 'preset_modified': False, 'preset_diff': []})

s['strategy_config']['gate_min_rr_enabled'] = False
t = P.trade_tag(s)
check("تغییر دستی شناسایی می‌شود", t['preset_modified'] and t['preset_diff'] == ['gate_min_rr_enabled'], t)
s['strategy_config']['halving_k_atr'] = 4.0000000001
s['strategy_config']['gate_min_rr_enabled'] = True
check("خطای اعشاری تغییر حساب نمی‌شود", P.preset_diff(s) == [])
check("پریست ناشناخته: تگ خالی", P.trade_tag({'active_preset': '5'}) == {'preset': None, 'preset_modified': False, 'preset_diff': []})

trades = [
 {'preset': '3', 'preset_modified': False, 'pnl_usdt': 2.0, 'realized_r': 1.0, 'mfe_r': 1.5},
 {'preset': '3', 'preset_modified': False, 'pnl_usdt': -1.0, 'realized_r': -1.0, 'mfe_r': 0.2},
 {'preset': '3', 'preset_modified': True, 'pnl_usdt': -2.0, 'realized_r': -1.0},
 {'pnl_usdt': 1.0},
 {'preset': '3', 'pnl_usdt': None},
]
st = P.summarize(trades)
check("گروه‌بندی", set(st) == {'کلید ۳', 'کلید ۳ (دستی تغییر کرده)', 'بدون برچسب'}, sorted(st))
a = st['کلید ۳']
check("آمار", a['n'] == 2 and a['wins'] == 1 and abs(a['pnl'] - 1.0) < 1e-9 and abs(a['profit_factor'] - 2.0) < 1e-9)
check("متن آمار و هشدار نمونه‌ی کم", 'نمونه کم' in P.format_stats(st) and len(P.format_stats(st)) < 4000)
txt = P.menu_text(s)
check("منو: فقط معمولی و بدون «کلید ۱ تا ۵»", len(txt) < 4000 and 'معمولی' in txt and 'کلید ۴' not in txt and 'سخت‌گیر' not in txt and 'محافظه‌کار' not in txt)
cbs = [b['callback_data'] for r in P.keyboard(s)['inline_keyboard'] for b in r]
check("کیبورد: فقط اعمال/نمایش/ذخیره‌ی همین پریست", '/preset_apply_3' in cbs and '/preset_show_3' in cbs and '/preset_save_3' in cbs
      and not any(f'/preset_apply_{n}' in cbs for n in '1245'))
print("ALL OK" if ok else "SOME FAILED")
raise SystemExit(0 if ok else 1)
