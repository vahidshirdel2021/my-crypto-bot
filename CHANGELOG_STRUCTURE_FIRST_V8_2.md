# V8.2 — Structure First Balanced/Flexible Modes

## Scope
Only 5m and 15m are affected. 1h and 4h remain unchanged.

## Default
`structure_mode = "balanced"`

Structure remains mandatory. Legacy entries are still blocked unless Structure First is disabled.

## Modes
- `strict`: previous V8.1-style sensitivity.
- `balanced`: wider retest tolerance, slightly smaller break requirement, longer lookback, and moderately softer candle-body confirmation. **Default.**
- `flexible`: further widens retest/break conditions and softens confirmation while keeping Structure as a hard gate.
- `off`: disables Structure First and restores the previous V7 selector for 5m/15m.

## Risk
The V8.1 structural SL remains unchanged: SL is placed behind the confirmed retest swing with ATR buffer.

## Important
This change does not remove Structure. It only reduces unnecessary signal starvation around the same Break → Retest → Swing → Confirmation concept.
