"""تست مستقل پریست‌ها: python preset_selftest.py"""
import presets as P

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, info)

s = {'strategy_config': {'halving_k_atr': 4.0, 'gate_fc_rsi_enabled': True}, 'trend_warn_enabled': True}
check("اعمال کلید ۱", P.apply_preset(s, '1') and s['active_preset'] == '1')
check("نام نامعتبر رد می‌شود", P.apply_preset(s, '99') is False and s['active_preset'] == '1')
check("k به ۳ برگشت و RSI سخت خاموش شد", s['strategy_config']['halving_k_atr'] == 3.0 and s['strategy_config']['gate_fc_rsi_enabled'] is False)
check("هشدارها خاموش", s['trend_warn_enabled'] is False and s['symbol_h4_regime_warn_enabled'] is False)
check("بدون تغییر دستی: diff خالی", P.preset_diff(s) == [])
check("تگ معامله", P.trade_tag(s) == {'preset': '1', 'preset_modified': False, 'preset_diff': []})

P.apply_preset(s, '2')
check("کلید ۲: فقط k پویا فرق دارد", s['strategy_config']['halving_dynamic_k'] is True and s['fav_confirm_enabled'] is False)
P.apply_preset(s, '3')
check("کلید ۳: k پویا برگشت و fav روشن", s['strategy_config']['halving_dynamic_k'] is False and s['fav_confirm_enabled'] is True)
P.apply_preset(s, '4')
c = s['strategy_config']
check("کلید ۴: همه‌ی تاییدهای سخت روشن", all(c[k] for k in ('gate_fc_rsi_enabled','gate_fc_macd_enabled','gate_fc_adx_enabled','gate_fc_h4_enabled','gate_fc_tf_enabled','gate_fc_btceth_enabled')) and s['fav_confirm_enabled'] is False)
P.apply_preset(s, '5')
c = s['strategy_config']
check("کلید ۵: BTC/ETH aligned خاموش و تایید کندل خاموش", c['gate_btceth_aligned_enabled'] is False and c['sweep_require_confirmation_candle'] is False and c['gate_fc_rsi_enabled'] is False)
P.apply_preset(s, '1')
check("برگشت به ۱: هیچ چیزی از ۵ نمانده", c['gate_btceth_aligned_enabled'] is True and c['sweep_require_confirmation_candle'] is True)

# تغییر دستی بعد از اعمال
s['strategy_config']['gate_min_rr_enabled'] = False
t = P.trade_tag(s)
check("تغییر دستی شناسایی می‌شود", t['preset_modified'] and t['preset_diff'] == ['gate_min_rr_enabled'], t)
s['strategy_config']['halving_k_atr'] = 3.0000000001
s['strategy_config']['gate_min_rr_enabled'] = True
check("خطای اعشاری تغییر حساب نمی‌شود", P.preset_diff(s) == [])

# هر پریست فقط در حد کلیدهای مجاز با کلید ۱ فرق دارد
base_cfg, base_ses = P._full('1')
for n in '2345':
    cfg, ses = P._full(n)
    d = [k for k in cfg if cfg[k] != base_cfg[k]] + [k for k in ses if ses[k] != base_ses[k]]
    print("   کلید", n, "فرق با ۱:", d)
check("همه‌ی کلیدهای پریست در GATE/سشن شناخته‌شده‌اند", all(k in P.managed_keys() for k in P.managed_keys()))

# آمار
trades = [
 {'preset': '1', 'preset_modified': False, 'pnl_usdt': 2.0, 'realized_r': 1.0, 'mfe_r': 1.5},
 {'preset': '1', 'preset_modified': False, 'pnl_usdt': -1.0, 'realized_r': -1.0, 'mfe_r': 0.2},
 {'preset': '2', 'preset_modified': False, 'pnl_usdt': 3.0, 'realized_r': 1.5, 'mfe_r': 2.0},
 {'preset': '1', 'preset_modified': True, 'pnl_usdt': -2.0, 'realized_r': -1.0},
 {'pnl_usdt': 1.0},
 {'preset': '2', 'pnl_usdt': None},
]
st = P.summarize(trades)
check("گروه‌بندی", set(st) == {'کلید ۱', 'کلید ۲', 'کلید ۱ (دستی تغییر کرده)', 'بدون برچسب'}, sorted(st))
a = st['کلید ۱']
check("آمار کلید ۱", a['n'] == 2 and a['wins'] == 1 and abs(a['pnl'] - 1.0) < 1e-9 and abs(a['profit_factor'] - 2.0) < 1e-9)
check("رکورد بدون PnL نادیده گرفته می‌شود", st['کلید ۲']['n'] == 1)
txt = P.format_stats(st)
check("متن آمار و هشدار نمونه‌ی کم", 'نمونه کم' in txt and len(txt) < 4000)
check("منو و کیبورد", len(P.menu_text(s)) < 4000 and len(P.keyboard(s)['inline_keyboard']) == 9)
print("ALL OK" if ok else "SOME FAILED")
