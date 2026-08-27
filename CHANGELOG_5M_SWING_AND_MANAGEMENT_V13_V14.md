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

---

# V14: 5m Position-Management Rebalance (early-exit too aggressive)

Scope: **5-minute timeframe only**, `_weakness_exit_check` and
`POSITION_MANAGEMENT_TIMEFRAME_MAP` in bot.py. Nothing here touches entry
logic, other timeframes' position management, or the V13 fix above.

## Problem (found by comparing trades before/after the V13 update, using the
same trade report)

Splitting the 65 5m trades at the V13 cutover (~ts 1787693155) showed the
*current* position-management code performs measurably worse than what ran
before it, not better:

| | before V13 (48 trades) | after V13 / current (17 trades) |
|---|---|---|
| avg realized R | -0.05 | **-0.52** |
| win rate | 38% | 24% |
| TP hit rate | 5/48 (10%) | **0/17 (0%)** |
| weakness-exit bucket avg R | -0.09 | -0.54 |

Two causes:
1. `POSITION_MANAGEMENT_TIMEFRAME_MAP['5min']` was `'1min'` — weakness
   (ADX/DI/RSI/EMA20) was judged on a timeframe 5x faster/noisier than the
   entry timeframe, so normal 5m-healthy trends looked "weak" constantly.
2. The V13 graduated ATR-pressure branch could fire on `current_r < 0` (i.e.
   a single tick of red) combined with `wscore >= 25` — a bar so low it's
   satisfied by almost any two of the five weakness sub-scores. Two real
   trades in the report (ATOM, DOT) got closed at +0.61R/+0.4R after
   reaching +1.48R/+1.15R MFE — profitable trades cut well short of target.
3. Separately (not a V13 regression, pre-existing): 5m weakness is
   deliberately checked *before* the hard SL/TP check, to react faster than a
   fast candle. But the exit price used was the raw live price, uncapped —
   so on a real gap past SL, the weakness path could realize a loss *worse*
   than the stated stop (observed: a DOT trade closed at -1.43R, worse than a
   full -1R stop).

## Fixes

- `POSITION_MANAGEMENT_TIMEFRAME_MAP['5min']`: `'1min'` → `'5min'` (own
  timeframe). 15min/1h/4h unchanged.
- Removed the "extreme" ATR-pressure branch (`current_r<0` + `wscore>=25`)
  entirely. The remaining ATR-pressure branch now requires `current_r<=-0.40`
  *and* `wscore>=50` *and* `atr_pressure>=0.85` together (was an easier
  alternate path before; now a stricter combined confirmation).
  The plain-R branches were raised too: -0.50R now needs `wscore>=45` (was
  35), and the base gate is -0.30R/`wscore>=55` (was -0.20R/45).
- Exit price on the 5m weakness path is now clamped to `[sl, tp]` before
  closing, so a gap-driven weakness exit can never realize a loss worse than
  the stated stop.

## Not changed

- `_mfe_protection_exit_check` / `PROFIT_LADDERS_R` — only 2/65 trades used
  this path and its logic (breakeven-then-graduated profit lock) looked
  reasonable on inspection; left alone pending more data.
- Non-5m weakness exit ordering/thresholds — untouched.

## Caveat

17 "after" trades is a small sample — directionally clear (0% TP rate is
stark) but treat the exact R figures as indicative, not final. Worth
re-running this same before/after comparison after a few days on V14 to
confirm the rebalance actually restores the TP rate rather than just
shifting where the loss happens.

