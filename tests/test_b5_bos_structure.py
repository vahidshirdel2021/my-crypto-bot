import pandas as pd
from signal_engine.key_level_setup import setups
from signal_engine.swing_structure.swings import SwingPoint
from signal_engine.swing_structure.structure import StructureEvent


def test_b5_structure_evidence_detects_bos_and_higher_low(monkeypatch):
    df = pd.DataFrame({"open":[100]*8,"high":[101]*8,"low":[90,91,92,94,93,95,96,97],"close":[100]*8})
    swings = [
        SwingPoint("h0","5min","X","swing_high",100,1,2,1,1,"confirmed"),
        SwingPoint("l0","5min","X","swing_low",90,2,3,1,1,"confirmed"),
        SwingPoint("l1","5min","X","swing_low",94,4,5,1,1,"confirmed"),
    ]
    event = StructureEvent("e","5min","X","BOS","bullish",106,3,"h0","uptrend","uptrend",0.7,{"broken_price":100})
    monkeypatch.setattr(setups, "detect_swings", lambda *a, **k: swings)
    monkeypatch.setattr(setups, "detect_structure_events", lambda *a, **k: [event])
    out = setups._b5_structure_evidence(df, "5min", "X", "bullish", 3, 4, 6)
    assert out["bos_confirmed"] is True
    assert out["bos_index"] == 3
    assert out["structure_hl_lh_confirmed"] is True
    assert out["structure_swing_price"] == 94.0


def test_b5_structure_evidence_detects_lower_high(monkeypatch):
    df = pd.DataFrame({"open":[100]*8,"high":[110,109,108,106,107,105,104,103],"low":[100]*8,"close":[100]*8})
    swings = [
        SwingPoint("l0","5min","X","swing_low",90,1,2,1,1,"confirmed"),
        SwingPoint("h0","5min","X","swing_high",110,2,3,1,1,"confirmed"),
        SwingPoint("h1","5min","X","swing_high",106,4,5,1,1,"confirmed"),
    ]
    event = StructureEvent("e","5min","X","BOS","bearish",84,3,"l0","downtrend","downtrend",0.7,{"broken_price":90})
    monkeypatch.setattr(setups, "detect_swings", lambda *a, **k: swings)
    monkeypatch.setattr(setups, "detect_structure_events", lambda *a, **k: [event])
    out = setups._b5_structure_evidence(df, "5min", "X", "bearish", 3, 4, 6)
    assert out["bos_confirmed"] is True
    assert out["structure_hl_lh_confirmed"] is True
    assert out["structure_swing_price"] == 106.0
