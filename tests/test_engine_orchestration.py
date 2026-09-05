import numpy as np
import pandas as pd
import signal_engine.confluence.layer as layer


def _df(n=120):
    idx = pd.date_range('2026-01-01', periods=n, freq='5min', tz='UTC')
    x = np.arange(n, dtype=float)
    c = 100 + np.sin(x / 5)
    return pd.DataFrame({
        'timestamp': idx.view('int64') // 10**6,
        'open': c, 'high': c + 1, 'low': c - 1,
        'close': c, 'volume': 1000,
    })


def test_all_five_engines_are_invoked(monkeypatch):
    called = []
    monkeypatch.setattr(layer, 'pre_detect_all', lambda *a, **k: called.append('PRE') or [])
    monkeypatch.setattr(layer, 'detect_swings', lambda *a, **k: called.append('SDE_SWINGS') or [])
    monkeypatch.setattr(layer, 'detect_structure_events', lambda *a, **k: called.append('SDE_STRUCTURE') or [])
    monkeypatch.setattr(layer, 'classify_macro_cycle', lambda *a, **k: called.append('MCDE_MACRO') or [])
    monkeypatch.setattr(layer, 'classify_micro_cycle', lambda *a, **k: called.append('MCDE_MICRO') or [])
    monkeypatch.setattr(layer, 'cpde_detect_all', lambda *a, **k: called.append('CPDE') or [])
    monkeypatch.setattr(layer, 'compute_key_levels', lambda *a, **k: called.append('KLSDE_LEVELS') or type('LS', (), {'levels': {}})())
    monkeypatch.setattr(layer, 'detect_interactions', lambda *a, **k: called.append('KLSDE_INTERACTIONS') or [])
    monkeypatch.setattr(layer, 'klsde_classify_all', lambda *a, **k: called.append('KLSDE_SETUP') or [])
    monkeypatch.setattr(layer, 'build_confluence_contexts', lambda *a, **k: [])
    monkeypatch.setattr(layer, 'score_all', lambda *a, **k: [])
    monkeypatch.setattr(layer, 'select_signals', lambda *a, **k: [])

    layer.generate_trade_signals(_df(), '5min', 'TEST', config={'min_confluence_score_to_emit': 0.0})

    assert called == [
        'PRE', 'SDE_SWINGS', 'SDE_STRUCTURE',
        'MCDE_MACRO', 'MCDE_MICRO', 'CPDE',
        'KLSDE_LEVELS', 'KLSDE_INTERACTIONS', 'KLSDE_SETUP',
    ]
