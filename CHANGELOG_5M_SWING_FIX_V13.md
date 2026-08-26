# 5m Swing Detection & Structural SL Fix V13

Scope: **5-minute timeframe only.** 15m/1h/4h logic is byte-for-byte
unchanged; every new check is gated behind `is_5m` / `timeframe == "5min"`.

## Problem (reported from a live trade + trade report review)

1. `_detect_swing_break_entry` (Swing→Break→Retest→Confirmation, V9) always
   tested the *current* closed candle as "confirmation," with no bound on how
   long ago the qualifying break/retest happened. On the ~200-candle 5m
   window this let a break/retest from many hours earlier be "confirmed" by
   an unrelated, much later candle just because it closed in the right
   direction — anchoring SL to a stale, no-longer-relevant swing instead of
   the structure actually forming right now.
2. In `_execute_trade_unlocked` (bot.py), when the real fill price slipped
   away from the signal price (observed: ~0.5% slip in ~2s on a live ZEC
   trade), SL/TP were shifted by the *original fixed distance* from the new
   fill price. That preserves the R:R distance but silently breaks the "SL
   sits behind the swing" guarantee — after a slip, the SL may no longer
   actually be behind the real structural swing low/high.
3. `_detect_structure_flip` was gated behind `swing_setup` being truthy, even
   though the two signals are conceptually independent — a swing-break miss
   could suppress an otherwise-valid Structure Flip trade.

## Fixes

- `_detect_swing_break_entry`: added `5min_confirm_gap_bars` (default 3) and
  `5min_max_setup_age_bars` (default 48) — the confirmation candle must sit
  within a small number of bars of the retest, and the pivot itself may not
  be older than the age cap. 15m keeps the exact prior (unbounded) behavior.
- `_execute_trade_unlocked` / `execute_trade`: new optional
  `swing_level` / `swing_sl_buffer` params. When supplied (5m Swing→Break
  entries only), SL is re-anchored to `swing_level ± swing_sl_buffer` off the
  *actual fill price* instead of being shifted by the signal-time distance.
  If the slip is bad enough that price is already at/past that structural
  stop, the trade is skipped instead of opening with an invalid stop.
  `risk_distance` in the trade record now reflects the real `entry-sl`
  distance in this case (previously always equal to the signal-time gap).
- `_select_v2_setup`: Structure Flip candidate detection on 5m no longer
  requires `swing_setup` to be truthy first (15m keeps the original coupled
  behavior).

## Not changed in this pass

- `compute_swing_stop` (legacy rolling-window swing used by the
  `trend_pullback` / `breakout_retest` families and by
  `_check_swing_trailing_stop` trailing) — shared across timeframes, so left
  untouched per scope. These legacy 5m families are already unreachable
  while `structure_first`/`structure_mode` is on (current default), so this
  mainly matters if that gate is ever turned off.
- Numeric strictness (`min_score`, `min_rr`, `confirmation_body`, etc.) —
  intentionally not loosened yet. The staleness/recency bug above was likely
  suppressing legitimate near-miss setups more than the thresholds were;
  re-evaluate thresholds after collecting fresh trade data on this fix.

## Verified

- `_detect_swing_break_entry`: manual synthetic-data test confirms a stale
  break/retest (confirmed only by an unrelated candle ~70 bars later) is now
  rejected on `timeframe="5min"` and still accepted on `timeframe="15min"`
  (old behavior preserved) when given identical pivot/break/retest params.
- A "fresh" break→retest→confirm sequence (retest within
  `5min_confirm_gap_bars` of the confirmation candle) still produces a valid
  candidate and a valid `_build_swing_break_plan` output on 5m.
- `strategy.py` / `bot.py` compile cleanly (`python3 -m py_compile`).

## Recommended next step

Add granular audit logging inside `_detect_swing_break_entry` /
`_build_swing_break_plan` (why a candidate was skipped: no pivot / no break /
no retest / weak confirmation / RR too low) so the next filter review can be
based on real rejection-reason data instead of the single generic
"no Structure Flip" message currently logged for every miss.
