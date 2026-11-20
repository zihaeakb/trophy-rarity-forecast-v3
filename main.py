#!/usr/bin/env python3
"""GTA VI trophy rarity forecast (make.fun gta6-trophy-rarity-forecast-01).

Count-consistent E/N model: a rate is earners / tracked players.  Instead of
extrapolating logit(rate) trends, recover integer earners E = round(rate*N/100)
at every refresh, model E(t) and N(t) separately (both log-linear in time
since the first read), then forecast rate = E(target)/N(target).

Key facts used (all from the public RULES.txt / the public Exophase page):
- Exophase refreshes in steps; between refreshes the page is frozen.
- Launch night: 638 players tracked, frozen; first refresh 2026-11-19 04:30Z
  brought 3,868 players with every rate lower (earn-ers unchanged).
- Integer inversion is exact: sum over trophies of round(rate*638/100) == 943,
  the page's trophies_earned count, so E is recovered without error.
- The tracked-player count grows roughly like a power law in time since
  launch (638 -> 3,868 in 4.7h -> 40k+ by ~45h); the fit is redone from the
  case's own refresh history whenever it has any.
- Story trophies come in a chain (Gone Fishing -> Ch1 -> Ch2 -> Ch3 -> Ch4 ->
  final mission): the wave of players reaches later chapters days after the
  earlier ones, so a later chapter's earners are floored at a share of the
  previous chapter's forecast earners (structural prior; the observed
  history cannot show the wave yet because it has not arrived).
- Week-one class ceilings (rate cannot exceed these by the target):
  early story 40%, activities 25%, mid-game 5%, late/grind 1%.

Python 3.13, standard library only, deterministic, offline.
Reads every *.in in $MAKEFUN_INPUT_DIR (else /input), writes one <id>.out
per case to $MAKEFUN_OUTPUT_DIR (else /output).
"""

import json
import math
import os
import sys
from datetime import datetime, timezone

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.6448536269514722, -0.6744897501960817, 0.0, 0.6744897501960817,
     1.6448536269514722]
# Documented first refresh (RULES.txt): 3,868 players tracked, earners frozen.
FIRST_REFRESH_N = 3868.0
FIRST_REFRESH_HOURS = 4.7
# Power-law prior for N(t) when the history is frozen (calibrated on the
# documented launch refresh and the public page snapshot ~45h after launch).
N_PRIOR_DELTA = 1.36
N_PRIOR_A = 1.21
N_PRIOR_N0 = 638.0


def parse_time(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def logit_pct(x):
    p = min(max(x, 0.01), 99.99) / 100.0
    return math.log(p / (1.0 - p))


def inv_logit_pct(l):
    return 100.0 / (1.0 + math.exp(-l))


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def lsq(xs, ys):
    """Least squares y = a + b*x. Returns (a, b, resid_std)."""
    n = len(xs)
    if n == 0:
        return 0.0, 0.0, 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 1e-12:
        return my, 0.0, 0.0
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx
    a = my - b * mx
    if n > 2:
        resid = math.sqrt(sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys)) / (n - 2))
    else:
        resid = 0.0
    return a, b, resid


def classify(troph):
    s = (troph["name"] + " " + troph["description"]).lower()
    if troph.get("tier") == "platinum":
        return "platinum"
    if "gone fishing" in s or "chapter 1" in s or "breakfast run" in s:
        return "early"
    if "fishing challenge" in s:
        return "early"
    if "chapter 2" in s or "arcade" in s or "bowling" in s or "100 vehicles" in s:
        return "earlymid"
    if "chapter 3" in s or "chapter 4" in s or "final mission" in s:
        return "mid"
    if "chapter" in s:
        return "mid"
    return "late"


CEIL = {"platinum": 2.0, "early": 40.0, "earlymid": 25.0, "mid": 5.0,
        "late": 1.0}
# Structural wave floor: a story chapter's forecast earners are at least this
# share of the previous chapter's forecast earners (the progression wave
# reaches later chapters days after the earlier ones).
CHAIN = ["gone fishing", "chapter 1", "chapter 2", "chapter 3", "chapter 4",
         "final mission"]
CHAIN_FLOOR = {"chapter 2": 0.20, "chapter 3": 0.05, "chapter 4": 0.25,
               "final mission": 0.50}


def chain_key(troph):
    s = (troph["name"] + " " + troph["description"]).lower()
    for k in CHAIN:
        if k in s:
            return k
    return None


def quantiles_from_logit(lmed, sig):
    qs = []
    for z in Z:
        q = inv_logit_pct(lmed + z * sig)
        qs.append(clamp(q, 0.01, 99.99))
    # enforce non-decreasing (rounding can only break ties by epsilon)
    for i in range(1, 5):
        if qs[i] < qs[i - 1]:
            qs[i] = qs[i - 1]
    return [round(q, 4) for q in qs]


def forecast_case(case):
    trophies = case["trophies"]
    hist = case["history"]
    at = parse_time(case["at"])
    target = parse_time(case["target"])
    horizon_h = max((target - at).total_seconds() / 3600.0, 0.0)

    # ---- collapse history into distinct refresh states ----
    states = []  # (t_hours_from_first, N, rates)
    t0 = None
    for r in hist:
        rt = parse_time(r["at"])
        if t0 is None:
            t0 = rt
        th = (rt - t0).total_seconds() / 3600.0
        n = float(r["players_tracked"])
        rates = r["rates"]
        if states and states[-1][1] == n and states[-1][2] == rates:
            continue
        states.append((th, n, list(rates)))
    if not states:
        states = [(0.0, 638.0, [0.01] * len(trophies))]
    n_states = len(states)
    t_last, n_last, rates_last = states[-1]
    u_last = t_last + 1.0
    u_target = u_last + horizon_h

    # ---- per-trophy integer earners at each state ----
    n_tr = len(trophies)
    E = [[0] * n_states for _ in range(n_tr)]
    for k, (_th, n, rates) in enumerate(states):
        for i in range(n_tr):
            r = rates[i]
            if r is None:
                r = rates_last[i]
            if r >= 99.99:
                E[i][k] = int(round(n))
            elif r <= 0.0:
                E[i][k] = 0
            else:
                E[i][k] = int(round(r * n / 100.0))

    out = {}
    if n_states == 1:
        # ---- frozen history (practice): earners frozen, one documented
        # refresh to 3,868 players before a short-horizon target. ----
        if horizon_h <= 6.0:
            n_t = FIRST_REFRESH_N
        else:
            # long frozen horizon: power-law prior through the documented
            # launch refresh (calibrated on the public ~45h snapshot).
            n_t = N_PRIOR_N0 * ((u_target + N_PRIOR_DELTA) /
                                (1.0 + N_PRIOR_DELTA)) ** N_PRIOR_A
            n_t = max(n_t, n_last)
        for i, t in enumerate(trophies):
            e = E[i][0]
            if rates_last[i] >= 99.99:
                out[t["id"]] = [99.99, 99.99, 100.0, 100.0, 100.0]
                continue
            rate = 100.0 * e / n_t if n_t > 0 else rates_last[i]
            rate = clamp(rate, 0.01, 99.99)
            if horizon_h <= 6.0:
                sig = 0.08
            else:
                sig = 1.2
            out[t["id"]] = quantiles_from_logit(logit_pct(rate), sig)
        return out

    # ---- N(t): log-linear fit on refresh states ----
    xs = [math.log(th + 1.0) for th, _n, _r in states]
    ys = [math.log(max(n, 1.0)) for _th, n, _r in states]
    _a_n, b_n, resid_n = lsq(xs, ys)
    # recent slope (last 24h of states) if enough states
    recent = [(x, y) for (th, _n, _r), x, y in zip(states, xs, ys)
              if th >= t_last - 24.0]
    if len(recent) >= 3:
        _a_r, b_r, _rr = lsq([p[0] for p in recent], [p[1] for p in recent])
        b_use = 0.5 * b_n + 0.5 * b_r
    else:
        b_use = b_n
    b_use = clamp(b_use, 0.0, 1.5)
    n_power = n_last * (u_target / u_last) ** b_use
    # Saturating alternative N(u) = N_inf*(1-exp(-u/tau)): adoption must bend.
    # Fit tau on a grid, N_inf by least squares; blend (geometric mean) with
    # the power law so a steep early slope cannot run away unchecked.
    best = None
    for tau in (12.0, 24.0, 48.0, 96.0, 192.0, 384.0, 768.0, 1536.0):
        w = [1.0 - math.exp(-(th + 1.0) / tau) for th, _n, _r in states]
        num = sum(n * wi for (_th, n, _r), wi in zip(states, w))
        den = sum(wi * wi for wi in w)
        if den <= 1e-12:
            continue
        n_inf = num / den
        sse = sum((math.log(max(n, 1.0)) -
                   math.log(max(n_inf * wi, 1.0))) ** 2
                  for (_th, n, _r), wi in zip(states, w))
        if best is None or sse < best[0]:
            best = (sse, tau, n_inf)
    if best is not None:
        _sse, tau_sat, n_inf = best
        n_sat = n_inf * (1.0 - math.exp(-u_target / tau_sat))
        n_sat = max(n_sat, n_last)
        n_t = math.exp(0.5 * math.log(max(n_power, 1.0)) +
                       0.5 * math.log(max(n_sat, 1.0)))
        model_gap = abs(math.log(max(n_power, 1.0)) - math.log(max(n_sat, 1.0)))
    else:
        n_t = n_power
        model_gap = 0.0
    n_t = max(n_t, n_last)
    sig_ln_n = clamp(0.18 + resid_n + 0.5 * model_gap, 0.18, 0.8)

    # ---- E(t) per trophy: RECENT-slope log-linear fit, anchored at E_last.
    # Earners growth accelerates (the progression wave), so a global fit
    # over the whole history understates the late slope; the recent slope
    # (last 24h of states) is what extrapolates. ----
    e_target = [0.0] * n_tr
    sig_e = [0.5] * n_tr
    ln_horizon = math.log(u_target / u_last) if u_last > 0 else 0.0
    for i in range(n_tr):
        if rates_last[i] >= 99.99:
            e_target[i] = n_t
            sig_e[i] = 0.05
            continue
        all_pts = [(math.log(states[k][0] + 1.0), math.log(max(E[i][k], 0.5)))
                   for k in range(n_states) if E[i][k] > 0]
        rec_pts = [(math.log(states[k][0] + 1.0), math.log(max(E[i][k], 0.5)))
                   for k in range(n_states)
                   if E[i][k] > 0 and states[k][0] >= t_last - 24.0]
        use = None
        if len(rec_pts) >= 2 and len(set(p[1] for p in rec_pts)) >= 2:
            use = rec_pts
        elif len(all_pts) >= 2 and len(set(p[1] for p in all_pts)) >= 2:
            use = all_pts
        if use is not None:
            _a_e, p_e, resid_e = lsq([p[0] for p in use], [p[1] for p in use])
            p_e = clamp(p_e, -0.5, 3.0)
            e_t = float(E[i][-1]) * (u_target / u_last) ** p_e
            sig_e[i] = clamp(0.4 + 0.3 * ln_horizon + resid_e, 0.4, 1.4)
        else:
            e_t = float(E[i][-1])
            sig_e[i] = 0.5
        e_t = max(e_t, float(E[i][-1]))
        e_target[i] = e_t

    # ---- structural wave floor along the story chain ----
    # order chain trophies by their chain key; a later chapter's earners are
    # at least floor_ratio * previous chapter's forecast earners.
    chain_members = {}
    for i, t in enumerate(trophies):
        k = chain_key(t)
        if k is not None and k != "gone fishing":
            chain_members.setdefault(k, []).append(i)
    prev_e = None
    for k in CHAIN[1:]:
        if k not in chain_members:
            continue
        for i in chain_members[k]:
            if prev_e is not None and k in CHAIN_FLOOR:
                floor_e = prev_e * CHAIN_FLOOR[k]
                if e_target[i] < floor_e:
                    e_target[i] = floor_e
        # previous chapter's earners for the next link: the largest in this key
        prev_e = max(e_target[i] for i in chain_members[k])

    # ---- assemble rates + spreads ----
    for i, t in enumerate(trophies):
        if rates_last[i] >= 99.99:
            out[t["id"]] = [99.99, 99.99, 100.0, 100.0, 100.0]
            continue
        cls = classify(t)
        e_t = min(e_target[i], n_t)
        rate = 100.0 * e_t / n_t if n_t > 0 else rates_last[i]
        rate = min(rate, CEIL[cls])
        rate = clamp(rate, 0.01, 99.99)
        # floor trophies whose earners never moved: keep them near the floor
        # but allow the spread to cover a small lift.
        sig = math.sqrt(sig_ln_n ** 2 + sig_e[i] ** 2)
        if cls in ("mid", "late") and E[i][-1] <= max(E[i][0], 1) * 1.5:
            # Earners never moved: the trophy may stay on the floor, or the
            # progression wave may lift it to 0.1-0.3% by the target. The
            # median stays at the floor but the upper quantiles must reach
            # far: the downside is capped because quantiles cannot go below
            # 0.01%, while the upside of missing a lift is ~3 logit.
            sig += 1.0
        if t.get("tier") == "platinum":
            sig = max(sig, 1.2)
        sig = clamp(sig, 0.7, 2.5)
        out[t["id"]] = quantiles_from_logit(logit_pct(rate), sig)
    return out


def main():
    in_dir = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    names = sorted(fn for fn in os.listdir(in_dir) if fn.endswith(".in"))
    for fn in names:
        with open(os.path.join(in_dir, fn), "r", encoding="utf-8") as f:
            case = json.load(f)
        res = forecast_case(case)
        rows = [{"id": int(tid), "q": res[int(tid)]}
                for tid in sorted(res, key=lambda x: int(x))]
        with open(os.path.join(out_dir, fn[:-3] + ".out"), "w",
                  encoding="utf-8") as f:
            json.dump({"trophies": rows}, f, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
