# Position Management V5

- Entry/strategy logic is unchanged.
- 5m V3 entry gate remains isolated to 5m.
- Upgraded profit-protection ladder for 5m/15m/1h/4h.
- Ladder is now based on the position's best MFE/peak favorable price, not only the latest price.
- Added MFE-based giveback protection for all supported timeframes.
- Added a small timeframe-specific pullback tolerance to avoid over-closing on normal noise.
- Safety check prevents moving a stop beyond the current tradable price.
- 5m early-loss protection remains active and unchanged in principle.
- No entry thresholds, setups, regimes, or signal selection rules were modified in V5.
