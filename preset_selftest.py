"""تست مستقل پریست من: python preset_selftest.py"""
import presets as P

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, info)

check("پنج پریست: کلید ۱ (قدیمی) و ۴ پریست مقایسه", list(P.PRESETS) == ['1', '2', '3', '4', '5'])

# سشنی که عمداً با پریست فرق دارد
s = {'strategy_config': {'halving_k_atr': 2.0, 'halving_max_depth': 14, 'gate_fc_rsi_enabled': True,
                         'gate_btceth_aligned_enabled': True, 'scenario_7_enabled': True,
                         'halving_tf': {'15min': {'halving_k_atr': 2.0, 'halving_max_depth': 14}}},
     'trend_warn_enabled': True, 'touch_auto_mode': 'all', 'fav_confirm_enabled': False,
     'trail_enabled': False, 'be_close_auto_enabled': False}
check("اعمال کلید ۱", P.apply_preset(s, '1') and s['active_preset'] == '1')
check("نام نامعتبر رد می‌شود", P.apply_preset(s, '9') is False and s['active_preset'] == '1')
c = s['strategy_config']
check("k=4 و عمق ۱۰ و انتخاب دستی هر تایم پاک شد", c['halving_k_atr'] == 4.0 and c['halving_max_depth'] == 10 and 'halving_tf' not in c)
check("RSI/MACD/ADX/حجم/BTCETH/۴ساعته در رأی‌گیری خاموش", not any(c[k] for k in ('gate_fc_rsi_enabled', 'gate_fc_macd_enabled', 'gate_fc_adx_enabled', 'gate_fc_vol_enabled', 'gate_fc_btceth_enabled', 'gate_fc_h4_enabled')))
check("رأی‌دهنده‌های روشن: رژیم ۵/۱۵، کلوز سطح، سقف/کف دیروز، الگو، رأی‌گیری", all(c[k] for k in ('gate_fc_tf_enabled', 'gate_fc_level_enabled', 'gate_fc_ylevel_enabled', 'gate_touch_pattern_vote_enabled', 'gate_touch_vote_enabled')))
check("دروازه‌های BTC و بلاک ۴ ساعته روشن", all(c[k] for k in ('gate_btc_candle_enabled', 'gate_btc_front_level_enabled', 'gate_4h_close_block_enabled')))
check("BTC/ETH aligned، رژیم مرحله‌ی آخر، معکوس، رتبه‌ی ۴ساعته خاموش", not any(c[k] for k in ('gate_btceth_aligned_enabled', 'gate_final_regime_enabled', 'gate_inverse_trading_enabled', 'gate_h4_tier_enabled')))
check("حالت‌های ۱ تا ۶ روشن و ۷ خاموش", all(c[f'scenario_{n}_enabled'] for n in range(1, 7)) and c['scenario_7_enabled'] is False)
check("ورود خودکار اکثریت ساده", s['touch_auto_mode'] == 'majority')
check("صبر برای تایید: روشن با 0.15R / ۲۰٪ مسیر / ۳۰ دقیقه", s['fav_confirm_enabled'] is True and s['fav_confirm_min_r'] == 0.15 and s['fav_confirm_max_mode'] == 'tp' and s['fav_confirm_max_tp_pct'] == 0.20 and s['fav_confirm_wait_sec'] == 1800)
check("سربه‌سر خودکار و تریلینگ روشن", s['be_close_auto_enabled'] is True and s['trail_enabled'] is True)
check("هشدارها خاموش", s['trend_warn_enabled'] is False and s['symbol_h4_regime_warn_enabled'] is False)
check("بدون تغییر دستی: diff خالی", P.preset_diff(s) == [])
check("تگ معامله", P.trade_tag(s) == {'preset': '1', 'preset_modified': False, 'preset_diff': []})

# تغییر دستی بعد از اعمال
s['strategy_config']['gate_min_rr_enabled'] = False
t = P.trade_tag(s)
check("تغییر دستی شناسایی می‌شود", t['preset_modified'] and t['preset_diff'] == ['gate_min_rr_enabled'], t)
s['strategy_config']['halving_k_atr'] = 4.0000000001
s['strategy_config']['gate_min_rr_enabled'] = True
check("خطای اعشاری تغییر حساب نمی‌شود", P.preset_diff(s) == [])

# آمار
trades = [
 {'preset': '1', 'preset_modified': False, 'pnl_usdt': 2.0, 'realized_r': 1.0, 'mfe_r': 1.5},
 {'preset': '1', 'preset_modified': False, 'pnl_usdt': -1.0, 'realized_r': -1.0, 'mfe_r': 0.2},
 {'preset': '1', 'preset_modified': True, 'pnl_usdt': -2.0, 'realized_r': -1.0},
 {'pnl_usdt': 1.0},
 {'preset': '1', 'pnl_usdt': None},
]
st = P.summarize(trades)
check("گروه‌بندی", set(st) == {'کلید ۱', 'کلید ۱ (دستی تغییر کرده)', 'بدون برچسب'}, sorted(st))
a = st['کلید ۱']
check("آمار کلید ۱", a['n'] == 2 and a['wins'] == 1 and abs(a['pnl'] - 1.0) < 1e-9 and abs(a['profit_factor'] - 2.0) < 1e-9)
txt = P.format_stats(st)
check("متن آمار و هشدار نمونه‌ی کم", 'نمونه کم' in txt and len(txt) < 4000)
check("منو و کیبورد", len(P.menu_text(s)) < 4000 and len(P.keyboard(s)['inline_keyboard']) == 4 + len(P.PRESETS))

# V3.44.47: چهار پریست مقایسه
def _apply(n):
    ss = {'strategy_config': {}, 'trend_warn_enabled': True}
    assert P.apply_preset(ss, n)
    return ss, ss['strategy_config']
base_same = ('halving_k_atr', 'halving_max_depth', 'gate_btc_candle_enabled', 'gate_btc_front_level_enabled', 'gate_touch_vote_enabled',
             'gate_fc_tf_enabled', 'gate_fc_level_enabled', 'gate_fc_ylevel_enabled')
s1, c1 = _apply('1')
check("کلید ۱: رفتار قبلی (جهت ثابت خاموش، رأی الگو روشن، الگوی BTC خاموش)",
      c1['gate_touch_dir_fixed_enabled'] is False and c1['gate_touch_pattern_vote_enabled'] is True and c1['gate_fc_btcpat_enabled'] is False)
for n in ('2', '3', '4', '5'):
    sn, cn = _apply(n)
    check(f"کلید {n}: جهت ثابت روشن، رأی الگو خاموش، اکثریت، ۱۵ دقیقه‌ی ATR ۴ و عمق ۱۰ و دروازه‌های BTC مثل هم",
          cn['gate_touch_dir_fixed_enabled'] is True and cn['gate_touch_pattern_vote_enabled'] is False
          and sn['touch_auto_mode'] == 'majority' and all(cn[k] == c1[k] for k in base_same))
    check(f"کلید {n}: diff خالی", P.preset_diff(sn) == [])
mom = ('gate_fc_rsi_enabled', 'gate_fc_macd_enabled', 'gate_fc_adx_enabled')
_, c2 = _apply('2'); _, c3 = _apply('3'); _, c4 = _apply('4'); _, c5 = _apply('5')
check("کلید ۲: بدون مومنتوم و بدون BTC", not any(c2[k] for k in mom) and not c2['gate_fc_btcpat_enabled'])
check("کلید ۳: فقط مومنتوم اضافه", all(c3[k] for k in mom) and not c3['gate_fc_btcpat_enabled'] and not c3['gate_fc_vol_enabled'])
check("کلید ۴: فقط الگوی BTC اضافه", c4['gate_fc_btcpat_enabled'] and not any(c4[k] for k in mom))
check("کلید ۵: همه روشن", all(c5[k] for k in mom + ('gate_fc_btcpat_enabled', 'gate_fc_btceth_enabled', 'gate_fc_h4_enabled', 'gate_fc_vol_enabled')))
# اعمال کلید ۲ روی سشنی که قبلاً کلید ۵ بود، همه‌چیز را کامل برمی‌گرداند (چیزی از قبلی نمی‌ماند)
s5, _ = _apply('5')
P.apply_preset(s5, '2')
check("کلید ۲ بعد از ۵ چیزی از ۵ باقی نمی‌گذارد", P.preset_diff(s5) == [] and not s5['strategy_config']['gate_fc_btcpat_enabled'] and not s5['strategy_config']['gate_fc_rsi_enabled'])
print("ALL OK" if ok else "SOME FAILED")
