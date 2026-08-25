# V6 — Daily 5-Level Structure Map

- Entry logic is unchanged.
- Adds a deterministic daily structure map from PDH/PDL:
  - PDH
  - EQ = (PDH + PDL) / 2
  - PDL
  - PDH+Range = PDH + (PDH - EQ)
  - PDL-Range = PDL - (EQ - PDL)
- These outer levels are structural/reaction references only in V6; no new entry trigger is enabled.
- Chart output labels all five levels for 5m/15m.
- Trade plans expose `daily_structure_levels` for future replay/management work.
