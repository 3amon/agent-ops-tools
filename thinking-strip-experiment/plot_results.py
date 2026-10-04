#!/usr/bin/env python3
"""Draw results.png: every trial of the 15-repetition run, one dot per trial.

    uv run --with matplotlib python3 plot_results.py [out.png]

One panel per scenario, shared log-scale y axis (one 189 s trial would flatten a
linear axis). The short bar is the median of the completed trials. Trials that
hit the 300 s request timeout have no wall time and are counted in a note.
"""
from __future__ import annotations

import glob
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

HERE = Path(__file__).resolve().parent
RUN = HERE / "llm_experiments/thinking_strip/results/20260422-110428"
SCENARIOS = [("multi_tool_chain", "Two tools in sequence"),
             ("three_tool_mixed_skills", "Three tools, two skills"),
             ("conditional_act_on_tool_output", "Act on a tool result")]
SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
COLOR = {"keep": "#2a78d6", "strip": "#eb6834"}
TICKS = [20, 30, 50, 100, 200]


def main(out: str) -> None:
    wall, failed = defaultdict(list), defaultdict(int)
    for f in sorted(glob.glob(str(RUN / "transcripts" / "*.json"))):
        d = json.load(open(f))
        key = (d["scenario_id"], d["config"])
        if "wall_s" in d:
            wall[key].append(d["wall_s"])
        else:
            failed[key] += 1

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    fig, axes = plt.subplots(1, 3, figsize=(10.4, 4.6), sharey=True, facecolor=SURFACE)
    for ax, (sid, title) in zip(axes, SCENARIOS):
        ax.set_facecolor(SURFACE)
        ax.set_yscale("log")
        ax.set_ylim(17, 360)
        ax.set_yticks(TICKS)
        ax.set_yticklabels([str(t) for t in TICKS], color=MUTED)
        ax.minorticks_off()
        ax.grid(axis="y", color=GRID, linewidth=1)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color("#c3c2b7")
        ax.tick_params(axis="both", length=0)
        ax.set_xlim(-0.6, 1.6)
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["thinking kept", "thinking stripped"], color=INK2)
        ax.set_title(title, loc="left", color=INK, fontsize=11, fontweight="bold", pad=8)
        for i, cond in enumerate(("keep", "strip")):
            ys = sorted(wall[(sid, cond)])
            # deterministic spread so equal-ish values do not hide each other
            xs = [i + ((j % 5) - 2) * 0.07 for j in range(len(ys))]
            ax.scatter(xs, ys, s=62, color=COLOR[cond], edgecolors=SURFACE, linewidths=1.6, zorder=3)
            med = st.median(ys)
            ax.plot([i - 0.27, i + 0.27], [med, med], color=INK, linewidth=2, solid_capstyle="round", zorder=4)
            note = f"median {med:.0f} s\nn = {len(ys)}"
            if failed[(sid, cond)]:
                note += f", {failed[(sid, cond)]} timed out"
            ax.annotate(note, (i, 290), va="center", ha="center", fontsize=8.5, color=INK2, linespacing=1.5)
    axes[0].set_ylabel("Wall time per trial, seconds (log scale)", color=INK2)
    fig.suptitle("Keeping or stripping the model's thinking between tool rounds: every trial",
                 x=0.012, y=0.985, ha="left", color=INK, fontsize=12.5, fontweight="bold")
    fig.text(0.012, 0.905, "qwen3.6:35b-a3b-fast on Ollama, 15 repetitions per cell, run 2026-04-22. "
             "Trials over the 300 s timeout are not plotted.", color=INK2, fontsize=9)
    handles = [Line2D([], [], marker="o", linestyle="", markersize=8, markerfacecolor=COLOR[c],
                      markeredgecolor=SURFACE, label=lab)
               for c, lab in (("keep", "thinking kept"), ("strip", "thinking stripped"))]
    handles.append(Line2D([], [], color=INK, linewidth=2, label="median"))
    fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.008, 0.0), ncol=3, frameon=False,
               labelcolor=INK2, fontsize=9, handletextpad=0.5, columnspacing=1.8)
    fig.subplots_adjust(left=0.075, right=0.985, top=0.80, bottom=0.17, wspace=0.08)
    fig.savefig(out, dpi=160, facecolor=SURFACE)
    print(out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(HERE / "results.png"))
