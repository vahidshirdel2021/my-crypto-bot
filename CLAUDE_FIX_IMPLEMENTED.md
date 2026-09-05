# Claude Fix Plan — Implementation Report

Base: `my-crypto-bot-KLSDE-V2-CLEAN-final.zip`

Implemented in the requested order while preserving the current KLSDE/Confluence architecture.

## 1. HTF closed-candle / look-ahead fix
- Added `signal_engine/common/htf.py`.
- HTF candles are confirmed only when `open_time + timeframe_duration <= decision_time`.
- Backtest now slices 1h/4h/1d/1w data using actual candle close boundaries.
- Live bot trims fetched HTF data with the same helper before strategy decisions.
- Added exact-boundary regression tests.

## 2. `defer_quality_gate`
- Propagated the flag through `strategy.py` → bridge → Confluence selector.
- Deferred mode can construct a low-score Near-Miss candidate.
- Deferred mode does not bypass invalid price, SL direction, RR, ATR/SL, or other safety checks in the trade-plan layer.
- Added regression tests.

## 3. Signal → Plan context consistency
- `live_price`, `filters`, `regime`, and `defer_quality_gate` are now explicitly carried through the signal and plan paths.
- Signal and plan both use the same live price snapshot supplied by the caller.
- The same market-data dictionary is passed into both paths.

## 4. Deterministic tests
Added `tests/` with regression coverage for:
- HTF forming/closed candles and exact boundaries.
- Deferred quality gate behavior.
- Safety checks remaining active in deferred mode.
- Core imports / pipeline availability.

## 5. Context/API cleanup
- Existing parameters were retained rather than removed.
- Context values are explicitly preserved in the strategy configuration for auditing and alternate execution paths.

## 6. Backtest/live parity
- The same closed-HTF candle helper is used by both backtest and live paths.
- The primary decision candle convention remains the project's existing `df.iloc[-2]` closed-candle contract.

## Validation
- `pytest`: 6 passed.
- `python -m compileall`: passed.

No strategy thresholds were changed by this fix pass.
