import numpy as np
import pandas as pd

from signal_engine.key_level_setup.interactions import InteractionWindow
from signal_engine.key_level_setup.setups import SetupEvent
import signal_engine.confluence.layer as layer


def _df(n=40):
    idx = pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC")
    c = np.linspace(100, 120, n)
    return pd.DataFrame({
        "timestamp": idx.view("int64") // 10**6,
        "open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1000,
    })


def test_klsde_old_resolved_setup_is_not_emitted(monkeypatch):
    d = _df()

    class LS:
        levels = {}

    old = SetupEvent("s-old", "TST", "PWH", 110, "TEST", "4hour", "bullish", 5, 10, 0.8)
    fresh = SetupEvent("s-new", "TST", "PWH", 110, "TEST", "4hour", "bullish", 35, 37, 0.8)

    monkeypatch.setattr(layer, "pre_detect_all", lambda *a, **k: [])
    monkeypatch.setattr(layer, "detect_swings", lambda *a, **k: [])
    monkeypatch.setattr(layer, "detect_structure_events", lambda *a, **k: [])
    monkeypatch.setattr(layer, "classify_macro_cycle", lambda *a, **k: [])
    monkeypatch.setattr(layer, "classify_micro_cycle", lambda *a, **k: [])
    monkeypatch.setattr(layer, "cpde_detect_all", lambda *a, **k: [])
    monkeypatch.setattr(layer, "compute_key_levels", lambda *a, **k: LS())
    monkeypatch.setattr(layer, "detect_interactions", lambda *a, **k: [])
    monkeypatch.setattr(layer, "klsde_classify_all", lambda *a, **k: [old, fresh])
    monkeypatch.setattr(layer, "build_confluence_contexts", lambda envs, **k: [])
    monkeypatch.setattr(layer, "score_all", lambda *a, **k: [])
    monkeypatch.setattr(layer, "select_signals", lambda *a, **k: [])

    captured = []
    monkeypatch.setattr(layer, "adapt_klsde_events", lambda events, *a, **k: captured.extend(events) or [])
    layer.generate_trade_signals(d, "4hour", "TEST", config={"min_confluence_score_to_emit": 0.0})
    assert [e.id for e in captured] == ["s-new"]
