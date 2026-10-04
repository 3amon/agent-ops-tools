#!/usr/bin/env python3
"""Re-derive the numbers in the README from the saved transcripts.

    python3 analyze.py                 # all three saved runs
    python3 analyze.py <run dir> ...   # specific runs

Standard library only. For each cell (scenario x condition) it prints the
number of completed and failed trials, wall-time mean / median / max, mean
rounds, and how many trials called every tool the scenario needs. For each
scenario it prints the difference between the two conditions with a bootstrap
95% interval and a two-sided permutation p-value (20,000 resamples, fixed seed).

This script was written after the experiment, for the write-up. The harness's
own summary (summary.md in each run directory) reports means only.
"""
from __future__ import annotations

import glob
import json
import random
import statistics as st
import sys
from collections import defaultdict
from math import comb
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_RUNS = [
    "llm_experiments/thinking_strip/results/20260422-104214",
    "llm_experiments/thinking_strip/results/20260422-110428",
    "llm_experiments/model_comparison/results/20260423-075437",
]
# tools a trial must call to have done what the prompt asked (from scenarios.py)
EXPECTED = {
    "multi_tool_chain": {"load_skill", "remember", "list_reminders"},
    "three_tool_mixed_skills": {"load_skill", "remember", "list_reminders", "get_weather"},
    "conditional_act_on_tool_output": {"load_skill", "get_weather", "remember"},
}
RESAMPLES = 20_000


def boot_ci(a, b, seed=1):
    r = random.Random(seed)
    diffs = sorted(st.mean(r.choices(b, k=len(b))) - st.mean(r.choices(a, k=len(a))) for _ in range(RESAMPLES))
    return diffs[int(0.025 * RESAMPLES)], diffs[int(0.975 * RESAMPLES)]


def perm_p(a, b, seed=1):
    r = random.Random(seed)
    observed = abs(st.mean(b) - st.mean(a))
    pool, hits = a + b, 0
    for _ in range(RESAMPLES):
        r.shuffle(pool)
        if abs(st.mean(pool[len(a):]) - st.mean(pool[:len(a)])) >= observed - 1e-12:
            hits += 1
    return hits / RESAMPLES


def fmt_p(p):
    return "< 0.001" if p < 0.001 else f"= {p:.3f}"


def fisher_two_sided(a_yes, a_no, b_yes, b_no):
    n, row, col = a_yes + a_no + b_yes + b_no, a_yes + a_no, a_yes + b_yes
    prob = lambda x: comb(row, x) * comb(n - row, col - x) / comb(n, col)  # noqa: E731
    p0 = prob(a_yes)
    return sum(prob(x) for x in range(max(0, col - (n - row)), min(row, col) + 1) if prob(x) <= p0 + 1e-12)


def analyze(run: Path) -> None:
    cells, errors = defaultdict(list), defaultdict(int)
    for f in sorted(glob.glob(str(run / "transcripts" / "*.json"))):
        d = json.load(open(f))
        cond = d.get("config") or d.get("model")
        key = (d["scenario_id"], cond)
        if "rounds_used" in d:
            cells[key].append(d)
        else:
            errors[key] += 1
    print(f"\n=== {run.relative_to(HERE) if run.is_relative_to(HERE) else run}")
    print(f"{'cell':<58} {'n':>3} {'fail':>4} {'wall mean':>9} {'median':>7} {'max':>7} {'rounds':>6} {'all tools':>9} {'tok/s':>6}")
    for key in sorted(set(cells) | set(errors)):
        ts = cells.get(key, [])
        if not ts:
            print(f"{'/'.join(key):<58} {0:>3} {errors[key]:>4}")
            continue
        wall = [t["wall_s"] for t in ts]
        need = EXPECTED.get(key[0])
        done = f"{sum(1 for t in ts if need <= set(t['tool_call_sequence']))}/{len(ts)}" if need else "-"
        tps = [t["tokens_per_second"] for t in ts if t.get("tokens_per_second")]
        print(f"{'/'.join(key):<58} {len(ts):>3} {errors[key]:>4} {st.mean(wall):>9.1f} {st.median(wall):>7.1f} "
              f"{max(wall):>7.1f} {st.mean(t['rounds_used'] for t in ts):>6.2f} {done:>9} "
              f"{(f'{st.mean(tps):.1f}' if tps else '-'):>6}")
    for sid in sorted({k[0] for k in cells}):
        conds = sorted(k[1] for k in cells if k[0] == sid)
        if len(conds) != 2:
            continue
        a, b = (cells[(sid, c)] for c in conds)
        print(f"\n{sid}: {conds[1]} minus {conds[0]}")
        for label, field in (("wall s", "wall_s"), ("rounds", "rounds_used")):
            xa, xb = [t[field] for t in a], [t[field] for t in b]
            lo, hi = boot_ci(xa, xb)
            print(f"  {label:<7} mean diff {st.mean(xb) - st.mean(xa):+7.2f}   median diff {st.median(xb) - st.median(xa):+7.2f}"
                  f"   bootstrap 95% [{lo:+.2f}, {hi:+.2f}]   permutation p {fmt_p(perm_p(xa, xb))}")
        need = EXPECTED.get(sid)
        if need:
            ya = sum(1 for t in a if need <= set(t["tool_call_sequence"]))
            yb = sum(1 for t in b if need <= set(t["tool_call_sequence"]))
            print(f"  called every needed tool: {conds[0]} {ya}/{len(a)}, {conds[1]} {yb}/{len(b)}"
                  f"   Fisher exact p = {fisher_two_sided(ya, len(a) - ya, yb, len(b) - yb):.3f}")


if __name__ == "__main__":
    for arg in sys.argv[1:] or DEFAULT_RUNS:
        analyze((HERE / arg) if not Path(arg).is_absolute() else Path(arg))
