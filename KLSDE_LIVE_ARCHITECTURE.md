# KLSDE V2 Live Architecture

## Live entry rule
Only **KLSDE V2** can create the trade anchor that reaches the live entry planner.

### Key levels
- MONTH: PMH / PML / PMEQ
- WEEK: PWH / PWL / PWEQ
- DAY: PDH / PDL / PDEQ
- 4H: Previous 4H High / Low / EQ
- 1H: Previous 1H High / Low / EQ

The price first interacts with one or more of these levels. KLSDE opens an
interaction window and classifies the resolved price action as one of:

- BOF
- TST
- BPB
- BP
- CPB

## Confirmation engines
SDE, PRE, CPDE and MCDE are still evaluated, but **cannot create an entry by
themselves**. They can only support a KLSDE anchor through the Confluence layer.

## Disabled live engines
- B1..B7 / S1..S7 legacy scenario engine
- Extra ORB / Judas Swing / MSS engine

Their source files remain in the repository for research/backtesting, but the
Live path cannot call them.

## Final flow

`Watchlist -> Key Levels -> KLSDE interaction -> BOF/TST/BPB/BP/CPB ->
Confluence confirmations -> Score -> HTF/RR/Risk -> Entry`

TP prefers the nearest valid structural Key Level ahead of the entry; ATR is
only a fallback when no valid structural target exists.
