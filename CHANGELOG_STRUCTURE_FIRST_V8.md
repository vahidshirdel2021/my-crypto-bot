# V8 — Structure First (5m / 15m only)

## Purpose
Make the daily five-level structure map a **hard prerequisite** for entries on 5m and 15m.

Levels:
- PDL-Range
- PDL
- EQ
- PDH
- PDH+Range

A valid entry requires a completed-candle sequence:

**Break/Reaction → Retest → Swing → Confirmation → Entry**

The resulting flipped level supplies the structural SL and next structural target.

## Important behavior
- 5m and 15m only.
- 1h and 4h are unchanged.
- Legacy entry families are not evaluated when `structure_first_enabled=True`.
- HTF, regime, volume, EdgeProxy and related signals are **confirmation/scoring layers**, not alternative entry triggers.
- If there is no valid Structure Flip, there is **NO TRADE**, even if every other signal is favorable.
- Only the structural minimum score and structural R:R remain hard gates.

## Rollback / disable
Set:

```python
"structure_first_enabled": False
```

This restores the previous V7 selector behavior for 5m/15m without changing the legacy entry rules.

Optional tuning:
- `structure_first_timeframes`
- `structure_first_min_score`
- `structure_first_use_htf_as_score`
- `structure_first_use_regime_as_score`

## Scope
No changes to the 1h/4h entry logic and no changes to position-management logic.
