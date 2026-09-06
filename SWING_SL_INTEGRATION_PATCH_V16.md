# V16 — B5/S5 Swing Quality → Structural SL Integration

## What changed
- B5/S5 structural SL now consults the project's `detect_swings()` engine directly.
- Only swings with `status=confirmed` and a quality score at/above the configured `b5_min_swing_quality` are eligible.
- `significant` swings are preferred; `confirmed` swings are the controlled fallback.
- `weak` swings are never used as the B5/S5 structural SL.
- The swing must be inside the breakout→retest window and its `confirmed_at_index` must be no later than the B5/S5 resumption candle.
- This preserves the no-lookahead boundary: candles after resumption cannot influence the selected structural swing.
- If no eligible confirmed swing exists, B5/S5 does not manufacture an SL from a raw wick/segment extreme; the bridge falls back to its normal structural/ATR SL path.
- Audit evidence now records source, swing index, quality score/label, and `b5_sl_lookahead_safe`.
- Timeframe is passed explicitly into the swing detector, avoiding accidental 5m defaults on higher timeframes.

## Configuration
The optional nested `swing_structure_config` may contain:
- `b5_min_swing_quality` (default 45)
- all normal swing engine overrides, such as `fractal_k`, `atr_period`, `min_swing_atr_multiple`

The default policy is quality-aware without requiring every B5/S5 to have a `significant` swing: significant is preferred, confirmed is allowed, weak is rejected.

## Validation
`PYTHONPATH=. pytest -q` → **18 passed**.
