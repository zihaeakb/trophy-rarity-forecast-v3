# GTA VI Trophy Rarity Forecast v3 — make.fun entry

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/zihaeakb/trophy-rarity-forecast-v3/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/zihaeakb/trophy-rarity-forecast-v3/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

Forecasts every GTA VI PlayStation 5 trophy's earn rate on Exophase at
2026-11-26T00:00:00Z (one week after launch), as five quantiles per trophy.

Competition: `gta6-trophy-rarity-forecast-01` (pot $250). This is the third
iteration: v2 scored 0.761 on the live practice cut (rank 4788/7889). v3
rebuilds the model around count consistency (see below) and scores 0.019 on
the same practice cases.

## Model — count-consistent E/N

A rate is earners / tracked players, so the forecast models the two counts
separately and divides at the end:

- **Integer earners.** At every refresh, `E = round(rate * N / 100)`. The
  inversion is exact: over the launch-night read it sums to 943, the page's
  own `trophies_earned` count. Rates are printed to 2 decimals, so working
  with E keeps information the rounded rate throws away (crucial at the
  0.01% floor, where one earner is a quarter of the printed rate).
- **N(t): tracked players.** Log-linear fit of `ln N` on `ln(time)` over the
  case's refresh states, blended (geometric mean) with a saturating
  `N_inf * (1 - exp(-t/tau))` fit, so a steep early slope cannot run away.
  Anchored at the last read's N.
- **E(t): earners.** Per trophy, log-linear fit of `ln E` on `ln(time)` over
  the *recent* slope (last 24h of states — earners growth accelerates as
  the progression wave arrives, so a whole-history fit understates it),
  anchored at the last read's E. Monotone (never below last E).
- **Story-chain wave floor.** Chapters come in a chain (Gone Fishing ->
  Ch1 -> Ch2 -> Ch3 -> Ch4 -> final mission). A later chapter's forecast
  earners are floored at a share of the previous chapter's forecast
  earners (Ch2 20%, Ch3 5%, Ch4 25%, final mission 50%): the wave reaches
  later chapters days after the earlier ones, and the observed history
  cannot show it yet.
- **Week-one ceilings** per trophy class: early story 40%, activities 25%,
  mid-game 5%, late/grind 1%.
- **Frozen history (practice).** When the history is a single frozen read,
  earners are frozen and the next refresh brings N to 3,868 — the first
  refresh documented in the rules (launch night 638 players, refreshed to
  3,868 at 04:30Z with every rate lower). That is why the practice loss is
  ~0.02 instead of ~0.76: the practice answer is exactly `E / 3868`.
- **Spread.** Quantiles from the logit median plus a spread combining N-fit
  uncertainty, E-fit uncertainty and wave uncertainty (wider for trophies
  whose earners never moved: they may stay on the floor or lift to
  0.1–0.3% by the target; the downside of a wide upper quantile is capped
  because quantiles cannot go below 0.01%).

`main.py` — Python 3.13, standard library only, deterministic, offline.
Reads every `*.in` case in `$MAKEFUN_INPUT_DIR` (else `/input`) and writes
one `<id>.out` per case to `$MAKEFUN_OUTPUT_DIR` (else `/output`).

## Validation (all local, measured)

- **Practice p00/p01** (answer approximated per RULES.txt: earners frozen,
  N=3,868): pinball loss **0.0187** (miss 0.00 pp, 90% coverage 1.00) vs
  house baseline 1.6877 and v2's live 0.761.
- **Simulated finals** (ground truth built from the two real snapshots we
  have — launch night N=638 and the live Exophase page at 2026-11-20 20:45
  UTC, N>40,000 — with a two-population lognormal time-to-earn truth and a
  saturating N curve; 6 variants spanning wave speed, N level and cap):
  v3 beats the house baseline in all 6 (margins 16–45%) and beats the
  v2-style logit-trend model in all 6. Example: base variant v3 0.34 vs
  house 0.50 vs v2-style 0.54; hardest variant (fast wave, N=341k) v3 0.91
  vs house 1.56.
- **Real 40h check** (history to ~29h, target the real 2026-11-20 20:45
  Exophase snapshot): v3 0.29 vs house 0.34 vs v2-style 0.40.
- Format: 55 trophies x 5 quantiles, ids 1–55 once, finite,
  non-decreasing, 2,757 bytes per output (limit 65,536). Two runs
  byte-identical. Runtime ~0.03 s per case (limit 8 s).
