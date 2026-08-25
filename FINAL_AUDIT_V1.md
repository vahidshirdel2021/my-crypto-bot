# Final strategy audit — V1

## Scope
Audited and patched `strategy.py`, `bot.py`, and `v3_backtest.py` for the V2 dynamic path, paper/live position management, and V3 backtesting consistency.

## Changes applied
1. HTF context is now actually fetched for dynamic 5m/15m/1h/4h scans.
2. V2 regime now separates trend state from volatility state; high volatility no longer automatically routes a strong trend into mean reversion.
3. V2 risk planning uses the signal timeframe instead of a hard-coded 1h planner.
4. Active setup risk uses the latest closed candle ATR while preserving the original setup candle as the liquidity anchor/extreme.
5. `edge_proxy` remains logged/diagnostic but is no longer a hard entry gate unless `use_edge_proxy_gate=true` is explicitly configured.
6. Regime confidence is now an explicit entry gate using `regime_confidence_min`.
7. Indicator-based weakness exits require at least 1R profit and use the execution timeframe itself.
8. Early loss-cut based on weakness is disabled by default to avoid competing with the hard SL; it can be explicitly enabled.
9. V3 backtester management timeframe and weakness-exit rules were aligned with bot.py.

## Validation
- `py_compile` passed for `strategy.py`, `bot.py`, `backtest.py`, `v3_backtest.py`.
- Synthetic regression test confirmed HIGH volatility + strong bullish trend returns `TREND_BULL` with `volatility_state=HIGH`.
- Synthetic active-setup regression confirmed ATR source is the latest closed candle while `setup_index` remains the original setup candle.
- V3 CSV smoke test completed successfully with no runtime error.

## Paper-test defaults
- `use_edge_proxy_gate=false`
- `weakness_exit_min_r=1.0`
- `weakness_exit_score=55`
- `early_loss_weakness_exit_enabled=false`

These defaults favor stable observation during the one-month paper test over aggressive discretionary exits.
