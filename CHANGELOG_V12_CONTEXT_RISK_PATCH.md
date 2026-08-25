# V12 Context & Risk Patch

- HTF Liquidity Reversal now derives weekly/monthly liquidity from `market_data_dict['1d']` when available.
- `_select_v2_setup` accepts `defer_quality_gate` and applies hard floors of score 60 and RR 1.30 when the quality gate is active.
- V2 plan construction can receive the same `market_data_dict`, `filters`, and `regime` context used during signal discovery.
- Added pure `_capped_leverage` and `_leader_correlation_decision` helpers without changing existing decision thresholds.
- Added `_same_direction_guard_allows`: configurable soft cap and cooldown for same-direction positions, with exception at score >= 80 and RR >= 1.60.
- Added regression coverage for the HTF daily-context path.
