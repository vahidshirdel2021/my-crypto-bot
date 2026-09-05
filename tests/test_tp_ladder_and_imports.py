def test_core_imports():
    import strategy
    import backtest
    from signal_engine.confluence.layer import generate_trade_signals
    assert callable(strategy.get_signal_with_reason)
    assert callable(backtest.run_backtest)
    assert callable(generate_trade_signals)
