"""تست‌های حلقه‌ی مدیریت پوزیشن، قفل سود و فیلتر جهت بازار.

بدون شبکه و بدون صرافی اجرا می‌شود. اگر aiohttp/ccxt نصب نباشند (مثلاً در CI سبک) با stub
جایگزین می‌شوند؛ در محیط واقعی از خود پکیج‌ها استفاده می‌شود.
اجرا:  pytest test_position_manager.py   (یا:  python test_position_manager.py)
"""
import asyncio
import importlib
import os
import sys
import tempfile
import threading
import time
from unittest.mock import MagicMock

os.environ.setdefault('TELEGRAM_TOKEN', '')
os.environ.setdefault('BOT_DB_PATH', os.path.join(tempfile.mkdtemp(), 'test_bot.sqlite3'))
os.environ.pop('DATABASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _name in ('aiohttp', 'ccxt'):
    try:
        importlib.import_module(_name)
    except ImportError:
        sys.modules[_name] = MagicMock()

import bot  # noqa: E402


# ----------------------------------------------------------------------------- helpers
class _Restore:
    """monkeypatch ساده (بدون وابستگی به pytest)."""
    def __init__(self):
        self._undo = []

    def setattr(self, obj, name, value):
        self._undo.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, old in reversed(self._undo):
            setattr(obj, name, old)
        self._undo.clear()


def _pos(side='BUY', sl=98.0, real=False):
    return {'symbol': 'X', 'side': side, 'entry_price': 100.0, 'margin': 50.0,
            'leverage': 5, 'sl': sl, 'is_real': real}


# ----------------------------------------------------------------------------- position manager
def test_scan_loop_no_longer_manages_positions():
    import inspect
    src = inspect.getsource(bot.scan_loop)
    assert 'update_positions(' not in src
    assert 'reconcile_real(' not in src


def test_manager_runs_each_user_and_survives_errors():
    m = _Restore()
    try:
        calls = []
        m.setattr(bot, 'USER_SESSIONS', {1: {'trading_mode': 'PAPER'}, 2: {'trading_mode': 'PAPER'}, 3: {'trading_mode': 'PAPER'}})

        def fake_update(cid):
            calls.append(cid)
            if cid == 2:
                raise RuntimeError('boom')
        m.setattr(bot, 'update_positions', fake_update)
        bot._position_manager_once()
        assert calls == [1, 2, 3]  # خطای کاربر ۲ کاربر ۳ را متوقف نکرد
    finally:
        m.undo()


def test_manager_real_reconciles_only_when_active_and_holds_entry_lock():
    m = _Restore()
    try:
        events = []
        m.setattr(bot, 'USER_SESSIONS', {
            10: {'trading_mode': 'REAL', 'is_bot_active': True},
            11: {'trading_mode': 'REAL', 'is_bot_active': False},
        })
        m.setattr(bot, 'reconcile_real', lambda cid: events.append(('reconcile', cid, bot.get_entry_lock(cid)._is_owned())))
        m.setattr(bot, 'update_positions', lambda cid: events.append(('update', cid, bot.get_entry_lock(cid)._is_owned())))
        bot._position_manager_once()
        # کاربر فعال: reconcile سپس update، هر دو زیر قفل ورود
        assert ('reconcile', 10, True) in events and ('update', 10, True) in events
        assert events.index(('reconcile', 10, True)) < events.index(('update', 10, True))
        # کاربر غیرفعال: فقط update
        assert ('reconcile', 11, True) not in events and ('reconcile', 11, False) not in events
        assert ('update', 11, True) in events
    finally:
        m.undo()


def test_manager_real_waits_for_in_flight_entry():
    """حالت خطرناک قبلی: reconcile نباید وسط execute_trade (پوزیشن فیل‌شده ولی هنوز ثبت‌نشده) اجرا شود."""
    m = _Restore()
    try:
        m.setattr(bot, 'USER_SESSIONS', {20: {'trading_mode': 'REAL', 'is_bot_active': True}})
        order = []
        m.setattr(bot, 'reconcile_real', lambda cid: order.append('reconcile'))
        m.setattr(bot, 'update_positions', lambda cid: order.append('update'))
        entry_lock = bot.get_entry_lock(20)
        started = threading.Event()

        def entry():
            with entry_lock:
                started.set()
                time.sleep(0.3)
                order.append('entry_done')

        t = threading.Thread(target=entry)
        t.start()
        started.wait(2)
        bot._position_manager_once()
        t.join()
        assert order[0] == 'entry_done', order  # manager تا پایان ورود صبر کرد
        assert order[1:] == ['reconcile', 'update']
    finally:
        m.undo()


def test_manager_skips_overlapping_run_for_same_user():
    m = _Restore()
    try:
        m.setattr(bot, 'USER_SESSIONS', {30: {'trading_mode': 'PAPER'}})
        calls = []
        gate = threading.Event()

        def slow_update(cid):
            calls.append(cid)
            gate.wait(2)
        m.setattr(bot, 'update_positions', slow_update)
        t = threading.Thread(target=bot._position_manager_once)
        t.start()
        time.sleep(0.1)
        bot._position_manager_once()  # اجرای هم‌پوشان: باید رد شود، نه منتظر بماند
        gate.set()
        t.join()
        assert calls == [30]
    finally:
        m.undo()


# ----------------------------------------------------------------------------- profit lock
def _lock_env(m, net_of_fees=False, move_ok=True):
    m.setattr(bot, 'PROFIT_LOCK_ENABLED', True)
    m.setattr(bot, 'PROFIT_LOCK_USDT', 5.0)
    m.setattr(bot, 'PROFIT_LOCK_NET_OF_FEES', net_of_fees)
    m.setattr(bot, 'normalize_price', lambda c, sym, pr: round(pr, 4))
    m.setattr(bot, 'send_message', lambda *a, **k: None)
    moves = []
    m.setattr(bot, 'move_stop_loss', lambda c, sym, sl: (moves.append(sl) or (move_ok, 'OK' if move_ok else 'boom')))
    return moves


def test_profit_lock_first_step_long_and_short():
    m = _Restore()
    try:
        _lock_env(m)
        p = _pos('BUY', 98.0)
        assert bot._apply_profit_lock(1, {}, p, 101.9) is False and p['sl'] == 98.0  # هنوز ۵ دلار نشده
        assert bot._apply_profit_lock(1, {}, p, 102.1) is True
        assert abs(p['sl'] - 102.0) < 1e-6 and p['profit_lock_usdt'] == 5.0 and p['sl_moved_ts'] > 0
        q = _pos('SELL', 102.0)
        assert bot._apply_profit_lock(1, {}, q, 97.9) is True and abs(q['sl'] - 98.0) < 1e-6
    finally:
        m.undo()


def test_profit_lock_ladder_steps_up_5_10_15():
    m = _Restore()
    try:
        moves = _lock_env(m, move_ok=True)
        p = _pos('BUY', 98.0, real=True)
        # مارجین ۵۰ × لوریج ۵ = ۲۵۰ => هر ۵ دلار = ۲٪ حرکت قیمت
        assert bot._apply_profit_lock(1, {}, p, 102.1) and abs(p['sl'] - 102.0) < 1e-6 and p['profit_lock_usdt'] == 5.0
        assert bot._apply_profit_lock(1, {}, p, 103.9) is False           # هنوز به ۱۰ نرسیده
        assert bot._apply_profit_lock(1, {}, p, 104.1) and abs(p['sl'] - 104.0) < 1e-6 and p['profit_lock_usdt'] == 10.0
        assert bot._apply_profit_lock(1, {}, p, 104.9) is False           # هنوز همان پله‌ی ۱۰
        assert bot._apply_profit_lock(1, {}, p, 106.2) and abs(p['sl'] - 106.0) < 1e-6 and p['profit_lock_usdt'] == 15.0
        assert len(moves) == 3                                            # هر پله فقط یک‌بار روی صرافی
        # پرش مستقیم چند پله‌ای: بالاترین پله‌ی رسیده‌شده قفل می‌شود (۲۶ دلار => پله‌ی ۲۵)
        assert bot._apply_profit_lock(1, {}, p, 110.5) and abs(p['sl'] - 110.0) < 1e-6 and p['profit_lock_usdt'] == 25.0
    finally:
        m.undo()


def test_profit_lock_ladder_short():
    m = _Restore()
    try:
        _lock_env(m)
        q = _pos('SELL', 102.0)
        assert bot._apply_profit_lock(1, {}, q, 97.9) and abs(q['sl'] - 98.0) < 1e-6
        assert bot._apply_profit_lock(1, {}, q, 95.9) and abs(q['sl'] - 96.0) < 1e-6 and q['profit_lock_usdt'] == 10.0
    finally:
        m.undo()


def test_profit_lock_retrace_keeps_last_level():
    """سناریوی واقعی: سود تا ۱۱ دلار می‌رود و برمی‌گردد؛ پله‌ی ۱۰ باید قفل مانده باشد."""
    m = _Restore()
    try:
        _lock_env(m)
        p = _pos('BUY', 98.0)
        for price in (102.1, 104.4):                 # ۵ و بعد ~۱۱ دلار
            bot._apply_profit_lock(1, {}, p, price)
        assert p['profit_lock_usdt'] == 10.0 and abs(p['sl'] - 104.0) < 1e-6
        bot._apply_profit_lock(1, {}, p, 102.4)      # برگشت به ~۶ دلار: SL نباید عقب برود
        assert abs(p['sl'] - 104.0) < 1e-6
    finally:
        m.undo()


def test_profit_lock_backward_compatible_with_single_step_positions():
    m = _Restore()
    try:
        _lock_env(m)
        p = _pos('BUY', 102.0)
        p['profit_lock_active'] = True               # پوزیشن قفل‌شده با نسخه‌ی قبلی (بدون profit_lock_usdt)
        assert bot._apply_profit_lock(1, {}, p, 102.5) is False   # پله‌ی ۵ دوباره اعمال نمی‌شود
        assert bot._apply_profit_lock(1, {}, p, 104.1) is True and p['profit_lock_usdt'] == 10.0
    finally:
        m.undo()


def test_profit_lock_never_loosens_existing_stop():
    m = _Restore()
    try:
        _lock_env(m)
        p = _pos('BUY', 102.4)  # مکانیزم دیگری قبلاً سود بیشتری قفل کرده
        assert bot._apply_profit_lock(1, {}, p, 102.5) is False
        assert p['sl'] == 102.4 and p['profit_lock_active'] is True and p['profit_lock_usdt'] == 5.0
    finally:
        m.undo()


def test_profit_lock_net_of_fees_needs_more_profit():
    m = _Restore()
    try:
        _lock_env(m, net_of_fees=True)
        p = _pos('BUY', 98.0)
        assert bot._apply_profit_lock(1, {}, p, 102.1) is False  # کارمزد ~0.25 هم باید پوشش داده شود
        assert bot._apply_profit_lock(1, {}, p, 102.6) is True
        assert p['sl'] > 102.0
    finally:
        m.undo()


def test_profit_lock_real_move_failure_retries_next_cycle():
    m = _Restore()
    try:
        moves = _lock_env(m, move_ok=False)
        p = _pos('BUY', 98.0, real=True)
        assert bot._apply_profit_lock(1, {}, p, 102.5) is False
        assert p['sl'] == 98.0 and not p.get('profit_lock_active')
        m.setattr(bot, 'move_stop_loss', lambda c, sym, sl: (moves.append(sl) or (True, 'OK')))
        assert bot._apply_profit_lock(1, {}, p, 102.5) is True and p['profit_lock_active']
    finally:
        m.undo()


# ----------------------------------------------------------------------------- market direction gate
def _direction(scores, tf):
    it = iter(scores)

    async def snap(http, sym, _tf):
        return next(it)
    m = _Restore()
    try:
        m.setattr(bot, '_market_snapshot_async', snap)
        bot.MARKET_DIRECTION_CACHE.pop(tf, None)
        return asyncio.run(bot.refresh_market_direction(None, tf))
    finally:
        m.undo()


def test_direction_seven_of_ten():
    assert _direction([1] * 7 + [0] * 3, 'a')['state'] == 'BULLISH'
    assert _direction([-1] * 7 + [1] * 3, 'b')['state'] == 'BEARISH'
    assert _direction([1] * 6 + [-1] * 4, 'c')['state'] == 'RANGE'
    assert _direction([1] * 6 + [None] * 4, 'd')['state'] == 'RANGE'
    assert 'd' not in bot.MARKET_DIRECTION_CACHE  # خطای داده کش نمی‌شود


def test_direction_single_fetch_under_concurrency():
    calls = []

    async def snap(http, sym, _tf):
        calls.append(sym)
        await asyncio.sleep(0.01)
        return 1
    m = _Restore()
    try:
        m.setattr(bot, '_market_snapshot_async', snap)
        bot.MARKET_DIRECTION_CACHE.pop('z', None)

        async def run():
            await asyncio.gather(*[bot.refresh_market_direction(None, 'z') for _ in range(20)])
        asyncio.run(run())
        assert len(calls) == len(bot.MARKET_REPORT_SYMBOLS)
    finally:
        m.undo()


if __name__ == '__main__':
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print('PASS', name)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                import traceback
                print('FAIL', name, repr(exc))
                traceback.print_exc()
    sys.exit(1 if failed else 0)
