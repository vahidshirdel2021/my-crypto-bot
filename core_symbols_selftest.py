"""تست کلید واچ‌لیست «فقط BTC / ETH / SOL»: python core_symbols_selftest.py"""
import sys, types
for _m in ('aiohttp', 'ccxt', 'dotenv', 'matplotlib', 'matplotlib.pyplot', 'matplotlib.dates', 'requests'):
    if _m not in sys.modules:
        try:
            __import__(_m)
        except ImportError:
            sys.modules[_m] = types.ModuleType(_m)
import bot, ui, access_policy

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, info)

off = {}
on = {'core_symbols_only': True}
check("خاموش: هیچ نمادی بلاک نمی‌شود", not bot._core_only_blocks(off, 'DOGE') and not bot._trade_set_blocks_entry(off, 'DOGE'))
for sym in ('BTC', 'ETH', 'SOL', 'BTCUSDT', 'ETHUSDT', 'SOLUSDT'):
    check(f"روشن: {sym} مجاز است", not bot._core_only_blocks(on, sym) and not bot._trade_set_blocks_entry(on, sym))
for sym in ('DOGE', 'XRP', 'ADA', 'SUI', 'DOGEUSDT'):
    check(f"روشن: {sym} بلاک می‌شود", bot._core_only_blocks(on, sym) and bot._trade_set_blocks_entry(on, sym))
check("ورود سریع دستی (priority_watch) مستثناست", not bot._core_only_blocks({**on, 'priority_watch': {'DOGE': {}}}, 'DOGE'))
check("CORE_SYMBOLS دقیقاً سه نماد", bot.CORE_SYMBOLS == ('BTC', 'ETH', 'SOL'))

kb_off = ui.get_watchlist_manage_keyboard(False)['inline_keyboard']
kb_on = ui.get_watchlist_manage_keyboard(True)['inline_keyboard']
b_off = [b for r in kb_off for b in r if b['callback_data'] == '/toggle_core_symbols']
b_on = [b for r in kb_on for b in r if b['callback_data'] == '/toggle_core_symbols']
check("دکمه در منوی واچ‌لیست هست", len(b_off) == 1 and len(b_on) == 1)
check("نشانگر 🔴/🟢 درست است", b_off[0]['text'].startswith('🔴') and b_on[0]['text'].startswith('🟢'))
check("بدون آرگومان هم کار می‌کند (سازگار با قبل)", ui.get_watchlist_manage_keyboard()['inline_keyboard'][0][0]['callback_data'] == '/toggle_core_symbols')
pats = list(access_policy._USER_PATTERNS)
check("کلید فقط برای ادمین است", '/toggle_core_symbols' not in access_policy.USER_EXACT and not any(p.match('/toggle_core_symbols') for p in pats))
print("\nALL PASS" if ok else "\nSOME FAILED")
raise SystemExit(0 if ok else 1)
