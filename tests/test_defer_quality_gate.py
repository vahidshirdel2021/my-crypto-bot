import pandas as pd
import pytest

from strategy import get_signal_with_reason, build_trade_plan


def _df(n=120):
    ts = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC").view("int64") // 10**6
    close = pd.Series(range(n), dtype=float) + 100
    return pd.DataFrame({"timestamp": ts, "ts": ts, "open": close, "high": close+1, "low": close-1, "close": close, "volume": 100.0})

# This test targets the explicit gate mechanics through a patched engine result.
def test_deferred_gate_allows_low_score(monkeypatch):
    import strategy
    best = {"code":"KLSDE:BOF","direction":"BUY","entry":101.0,"sl":100.0,"tp":103.0,"total_score":40,"base_score":40,"bonus":0,"penalty":0,"reasons":["test"],"level_label":"PDH","tp_partial":None}
    monkeypatch.setattr(strategy, "_run_engine_multi_source", lambda *a, **k: (best, "KLSDE"))
    sig, _ = strategy.get_signal_with_reason(_df(), strategy_config={"min_trade_score":65, "global_market_regime":"BULLISH"}, defer_quality_gate=False)
    assert sig is None
    sig, _ = strategy.get_signal_with_reason(_df(), strategy_config={"min_trade_score":65, "global_market_regime":"BULLISH"}, defer_quality_gate=True)
    assert sig == "BUY"


def test_deferred_gate_does_not_bypass_invalid_price(monkeypatch):
    import strategy
    best = {"code":"KLSDE:BOF","direction":"BUY","entry":0.0,"sl":-1.0,"tp":2.0,"total_score":40,"base_score":40,"bonus":0,"penalty":0,"reasons":["test"],"level_label":"PDH","tp_partial":None}
    monkeypatch.setattr(strategy, "_run_engine_multi_source", lambda *a, **k: (best, "KLSDE"))
    plan, reason = strategy.build_trade_plan(_df(), "BUY", strategy_config={"min_trade_score":65, "global_market_regime":"BULLISH"}, defer_quality_gate=True)
    assert plan is None
    assert "نامعتبر" in reason
