import pandas as pd
from signal_engine.bridge import _b5_retest_swing_stop
from signal_engine.confluence.selector import TradeSignal

def test_b5_retest_swing_sl_uses_confirmed_quality_swing():
    d = pd.DataFrame({
        "open":[100,104,102,104,105,106,105,104,106,108,109,110,111,112,113],
        "high":[101,106,104,107,108,110,106,105,109,111,112,113,114,115,116],
        "low":[99,103,100,103,104,105,102,101,105,107,108,109,110,111,112],
        "close":[100,105,101,106,107,109,103,102,108,110,111,112,113,114,115],
        "volume":[100,100,100,100,100,180,100,100,160,100,100,100,100,100,100],
    })
    sig = TradeSignal("s","X","bullish",.9,4,10,"active","KLSDE","B5",
        reference_levels={"klsde_setup_evidence":{
            "b5_variant":True,"breakout_confirm_index":1,
            "retest_swing_index":7,"resumption_index":10,
            "swing_structure_config":{"fractal_k":3,"atr_period":3,"min_swing_atr_multiple":0.2,"b5_min_swing_quality":45}}})
    sl, swing = _b5_retest_swing_stop(sig,d,108,True,1.0,timeframe="5m")
    assert swing is not None
    assert sl < swing < 108
    ev = sig.reference_levels["klsde_setup_evidence"]
    assert ev["b5_sl_lookahead_safe"] is True
    assert ev["b5_sl_swing_quality_score"] is not None
    assert ev["b5_sl_swing_quality_label"] in {"confirmed", "significant"}



def test_non_b5_does_not_use_retest_swing():
    d = pd.DataFrame({'open':[1]*5,'high':[2]*5,'low':[0]*5,'close':[1]*5})
    sig = TradeSignal('s','T','bullish',.9,4,10,'active','KLSDE','BPB',reference_levels={})
    assert _b5_retest_swing_stop(sig,d,1.5,True,1.0) == (None,None)
