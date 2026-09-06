# V14 — Multi-Level Execution TP Ladder

- B5/S5 remains first-class KLSDE setup.
- Every key level can still independently trigger/evaluate a setup.
- On 5m/15m, P1H/P4H are not used as automatic execution targets.
- Execution targets are PDH/PDL → PWH/PWL → PMH/PML (directional and only if ahead of entry).
- When multiple valid execution targets exist, the farthest valid level becomes TP3, while nearer levels become TP1/TP2.
- RR validation is now calculated against the actual TP3/final structural target, preventing a nearby daily level from artificially collapsing the trade to ~1R.
- When only one valid target exists, TP1/TP2 are progressive fractions of the path to that target.
- The full target candidate list is preserved in the plan/audit as `target_level_candidates`.
- Existing B5/S5 retest-swing SL logic is unchanged.

Validation: `PYTHONPATH=. pytest -q` → 15 passed.
