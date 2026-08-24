# V2 Adaptive Opportunity Engine

## Added
- Quality and Confidence are now separate metrics.
- Opportunity Pool stores recent valid candidates across symbols.
- Near-Miss registry stores WAIT_PULLBACK and WAIT_CONFIRMATION opportunities.
- Cross-symbol comparable opportunity rank.
- Smart Timing states: TRADE_NOW, WAIT_PULLBACK, WAIT_CONFIRMATION.

## Preserved from V1
- Candidate generation families.
- V1 final score/RR gates.
- HTF context, regime checks and risk guards.
- Same-direction exposure guard.
- Leader correlation guard.
- Existing position management.

## Execution rule
V2 is additive: it never promotes an invalid V1 candidate to TRADE.
It may delay a valid candidate for timing evidence.
