"""تست «حالت ساده ۶ سناریو»: python simple_mode_selftest.py"""
import sys, types
for _m in ('aiohttp', 'ccxt', 'dotenv', 'matplotlib', 'matplotlib.pyplot', 'matplotlib.dates', 'requests'):
    if _m not in sys.modules:
        try: __import__(_m)
        except ImportError: sys.modules[_m] = types.ModuleType(_m)
import bot, ui, strategy, access_policy
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

off = {'strategy_config': {'gate_touch_vote_enabled': True, 'gate_fc_rsi_enabled': True}}
on = {'strategy_config': {'simple_scenario_mode': True, 'gate_touch_vote_enabled': True, 'gate_fc_rsi_enabled': True,
                          'gate_min_rr_enabled': True, 'gate_risk_guard_enabled': True, 'gate_cooldown_enabled': True,
                          'gate_inverse_trading_enabled': True, 'scenario_1_enabled': False, 'scenario_7_enabled': True}}
check("خاموش: رأی‌گیری و RSI سر جایشان", bot.gate_on(off, 'gate_touch_vote_enabled') and bot.gate_on(off, 'gate_fc_rsi_enabled'))
for k in [k for k in bot.GATE_REGISTRY if k.startswith("gate_")]:
    if k in strategy.SIMPLE_MODE_KEEP_GATES:
        check(f"روشن: {k} می‌ماند", bot.gate_on(on, k) == bool(on['strategy_config'].get(k, bot._gate_default(k))))
    else:
        check(f"روشن: {k} خاموش", not bot.gate_on(on, k))
cfg = on['strategy_config']
check("strategy._gate_on خاموش", not strategy._gate_on(cfg, 'gate_min_rr_enabled') and strategy._gate_on(cfg, 'gate_risk_guard_enabled'))
for kind, sig in (('simple','SELL'),('simple','BUY'),('continuation','BUY'),('continuation','SELL'),('fakeout','SELL'),('fakeout','BUY')):
    check(f"سناریو {kind}/{sig} همیشه روشن (حتی با کلید خاموش)", strategy._scenario_enabled(kind, sig, cfg))
check("سناریو ۷ ممنوع", strategy.simple_touch_signal.__code__ is not None and strategy.simple_touch_signal(None, cfg, None)[0] is None)
for sym in ('BTCUSDT', 'ETHUSDT', 'SOLUSDT'):
    check(f"{sym} مجاز", not bot._trade_set_blocks_entry(on, sym))
for sym in ('DOGEUSDT', 'XRPUSDT', 'ADAUSDT'):
    check(f"{sym} بلاک", bot._trade_set_blocks_entry(on, sym))
check("خاموش: DOGE بلاک نمی‌شود", not bot._trade_set_blocks_entry(off, 'DOGEUSDT'))
check("ساعات معامله آزاد", bot._in_trade_hours({**on, 'hours_filter_enabled': True})[0])
check("دکمه در منو", any(b['callback_data'] == '/toggle_simple_mode' for r in ui.get_scenario_management_keyboard(on)['inline_keyboard'] for b in r))
check("فقط ادمین", not access_policy.__dict__.get('USER_EXACT', set()).__contains__('/toggle_simple_mode'))
sys.exit(0 if ok else 1)
