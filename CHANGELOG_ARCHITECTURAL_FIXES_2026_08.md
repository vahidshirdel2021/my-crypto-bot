# Architectural Fixes — PDH/EQ/PDL, TP Ladder, Structural Trailing

- PDH/PDL/PWH/PWL are anchored to completed UTC calendar sessions; live forming candles are excluded from the reference lookup.
- A hard dead-zone gate blocks entry generation when price is inside the middle of the reference range without a current-session boundary touch/sweep/retest/break event.
- B6/S6 discount/premium mid-range entries were removed.
- Smart MFE/weakness/day-end premature exits were removed from the automated position-management loop. Positions are closed by hard SL, the TP ladder, or manual intervention.
- TP ladder added: 50% at EQ, 30% at the opposite boundary, 20% at range extension. After TP1, remaining SL is moved to entry (break-even).
- REAL positions now install only the protective SL at entry; TP ladder execution is managed by the bot so the exchange cannot close 100% of the position at TP1.
- Swing detection now requires a meaningful wick and configurable volume ratio. Structural trailing follows the latest confirmed validated swing and applies an ATR buffer.
- Historical-touch fakeout penalty is adaptive with diminishing returns instead of a fixed -15 hit, reducing over-penalization of otherwise strong core setups.
