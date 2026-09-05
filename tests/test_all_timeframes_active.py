from pathlib import Path
from ui import get_timeframe_keyboard

BOT_SOURCE = Path(__file__).resolve().parents[1] / 'bot.py'


def test_all_four_trading_timeframes_are_supported_in_source():
    src = BOT_SOURCE.read_text()
    assert "('5min', '15min', '1hour', '4hour')" in src
    assert "WINNING_WATCHLISTS = {tf: LONG_WATCHLIST for tf in ('5min', '15min', '1hour', '4hour')}" in src


def test_timeframe_keyboard_exposes_all_four():
    buttons = [b for row in get_timeframe_keyboard()['inline_keyboard'] for b in row]
    callbacks = {b['callback_data'] for b in buttons}
    assert {'/set_tf_5m', '/set_tf_15m', '/set_tf_1h', '/set_tf_4h'} <= callbacks
