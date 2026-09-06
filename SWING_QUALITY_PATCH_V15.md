# V15 — Swing Confirmation + Quality Layer

## What changed
- Kept the existing fractal confirmation/no-lookahead boundary intact.
- Added `SwingPoint.quality_score` and `quality_label`:
  - `weak` < 45
  - `confirmed` 45–69.9
  - `significant` >= 70 (defaults; configurable)
- Quality is calculated **only through `confirmed_at_index`**.
- Added quality evidence:
  - `prominence_atr`
  - `reversal_excursion_atr`
  - `volume_percentile`
  - `prior_leg_atr`
  - `quality_calculated_through_index`
  - `quality_lookahead_safe`
- Added `select_significant_swings()` for consumers that require meaningful swings.
- BOS/CHoCH evidence now carries the broken swing's quality score/label and confidence gets a small quality-aware adjustment.
- Restored the existing `swings_as_arrays()` compatibility helper.

## Important behavior
`confirmed` does NOT mean every swing is important. The engine now explicitly separates:
1. confirmed fractal;
2. confirmed-but-weak swing;
3. significant swing.

The live strategy is not globally forced to discard all `confirmed` swings yet, because that would be a behavior-changing gate. B5 can be upgraded to require `significant` swings in a later controlled patch after backtesting.

## Validation
`PYTHONPATH=. pytest -q` → **18 passed**.
