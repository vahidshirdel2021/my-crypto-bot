# Structure Flip Entry V7

- Added a dedicated `structure_flip` entry family for 5m and 15m.
- Daily structure map uses five levels: `PDL-Range`, `PDL`, `EQ`, `PDH`, `PDH+Range`.
- Outer levels mirror the half-range: `PDL-(EQ-PDL)` and `PDH+(PDH-EQ)`.
- Entry requires a completed break through a level, a subsequent swing/retest from the new side, and a confirmation candle.
- The flipped level becomes the structural support/resistance anchor; the next adjacent daily level is the default target.
- 5m V3 legacy gate remains unchanged for existing setup families. `structure_flip` is an independent family with its own score/RR gate.
- 15m/1h/4h existing entry families are otherwise unchanged; 1h/4h dedicated HTF selection remains intact.
- No future candles are used in the flip detector.
