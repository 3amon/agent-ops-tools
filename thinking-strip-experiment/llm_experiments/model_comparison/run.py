"""Run the model comparison experiment.

Compares qwen3.6:35b-a3b-fast (MoE, 3B active / 35B total, production)
vs qwen3.6:27b (dense 27B, newly released) on identical multi-tool scenarios.

Each model runs all scenarios REPS times, interleaved to average out warmup drift.
"""
import json
import random
import sys
from datetime import datetime
from pathlib import Path

from .agent import run_turn
from ..thinking_strip.scenarios import SCENARIOS

REPS = 10
MODELS = [
    "qwen3.6:35b-a3b-fast",
    "qwen3.6:27b",
]
RESULTS_ROOT = Path(__file__).parent / "results"


def main():
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = RESULTS_ROOT / timestamp
    transcripts_dir = run_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    print(f"[run] writing to {run_dir}")

    trials = []
    for scenario in SCENARIOS:
        for rep in range(REPS):
            for model in MODELS:
                trials.append((scenario, rep, model))
    rng = random.Random(42)
    rng.shuffle(trials)

    total = len(trials)
    print(f"[run] total trials: {total}  "
          f"(scenarios={len(SCENARIOS)} x models={len(MODELS)} x reps={REPS})")

    results: list[dict] = []
    for i, (scenario, rep, model) in enumerate(trials, 1):
        t0 = datetime.now()
        label = model.split(":")[1]  # e.g. "35b-a3b-fast" or "27b"
        print(f"[{i}/{total}] {scenario['id']} rep={rep} model={label} ...", flush=True)
        try:
            result = run_turn(scenario["prompt"], model=model)
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}", flush=True)
            result = {"error": f"{type(e).__name__}: {e}", "model": model}
        elapsed = (datetime.now() - t0).total_seconds()
        tps = result.get("tokens_per_second")
        print(
            f"  done in {elapsed:.1f}s  rounds={result.get('rounds_used','?')}  "
            f"tps={tps}  tools={result.get('tool_call_sequence', [])}",
            flush=True,
        )

        meta = {
            "scenario_id": scenario["id"],
            "scenario_prompt": scenario["prompt"],
            "rep": rep,
            **result,
        }
        results.append(meta)
        safe_model = model.replace(":", "-").replace("/", "-")
        fname = f"{scenario['id']}__{safe_model}__rep{rep}.json"
        (transcripts_dir / fname).write_text(json.dumps(meta, indent=2, default=str))

    summary = _summarize(results)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    (run_dir / "summary.md").write_text(_format_summary_md(summary, timestamp))
    print(f"\n[run] DONE. Summary at {run_dir}/summary.md")


def _summarize(results: list[dict]) -> dict:
    by_scenario_model: dict = {}
    for r in results:
        if "error" in r and "rounds_used" not in r:
            continue
        key = (r["scenario_id"], r["model"])
        by_scenario_model.setdefault(key, []).append(r)

    cells: dict = {}
    for (sid, model), trials in by_scenario_model.items():
        rounds = [t["rounds_used"] for t in trials]
        walls = [t["wall_s"] for t in trials]
        tps_vals = [t["tokens_per_second"] for t in trials if t.get("tokens_per_second")]
        thinking = [t["total_thinking_chars"] for t in trials]
        tool_seqs = [tuple(t["tool_call_sequence"]) for t in trials]
        cells[f"{sid}/{model}"] = {
            "n": len(trials),
            "rounds_mean": round(sum(rounds) / len(rounds), 2),
            "wall_mean_s": round(sum(walls) / len(walls), 1),
            "wall_min_s": round(min(walls), 1),
            "wall_max_s": round(max(walls), 1),
            "tps_mean": round(sum(tps_vals) / len(tps_vals), 1) if tps_vals else None,
            "thinking_chars_mean": round(sum(thinking) / len(thinking)),
            "distinct_tool_seqs": len(set(tool_seqs)),
            "most_common_seq": list(max(set(tool_seqs), key=tool_seqs.count)) if tool_seqs else [],
        }

    # Head-to-head per scenario
    head_to_head: dict = {}
    for sid in {r["scenario_id"] for r in results if "rounds_used" in r}:
        a_key = f"{sid}/{MODELS[0]}"
        b_key = f"{sid}/{MODELS[1]}"
        a = cells.get(a_key)
        b = cells.get(b_key)
        if not (a and b):
            continue
        head_to_head[sid] = {
            "wall_delta_b_minus_a_s": round(b["wall_mean_s"] - a["wall_mean_s"], 1),
            "tps_a": a["tps_mean"],
            "tps_b": b["tps_mean"],
            "thinking_delta_b_minus_a": b["thinking_chars_mean"] - a["thinking_chars_mean"],
            "rounds_delta_b_minus_a": round(b["rounds_mean"] - a["rounds_mean"], 2),
            "a_distinct_seqs": a["distinct_tool_seqs"],
            "b_distinct_seqs": b["distinct_tool_seqs"],
        }

    return {"cells": cells, "head_to_head": head_to_head, "models": MODELS}


def _format_summary_md(summary: dict, ts: str) -> str:
    a, b = summary["models"]
    a_label = a.split(":")[1]
    b_label = b.split(":")[1]

    lines = [f"# Model Comparison — {ts}", ""]
    lines.append(f"**A**: `{a}` — MoE, 3B active / 35B total, fast quant (production)")
    lines.append(f"**B**: `{b}` — dense 27B (newly released)")
    lines.append("")
    lines.append("Scenarios, tools, and system prompt identical to thinking_strip experiment.")
    lines.append("Thinking: always on. Within-turn thinking: kept. Cross-turn: stripped.")
    lines.append("")

    lines.append("## Per-cell stats")
    lines.append("")
    lines.append("| cell | n | rounds | wall s (mean/min/max) | tps | thinking chars | distinct tool seqs |")
    lines.append("|---|---|---|---|---|---|---|")
    for key in sorted(summary["cells"]):
        c = summary["cells"][key]
        tps = f"{c['tps_mean']}" if c["tps_mean"] else "—"
        lines.append(
            f"| {key.replace(a, a_label).replace(b, b_label)} | {c['n']} | {c['rounds_mean']} | "
            f"{c['wall_mean_s']} / {c['wall_min_s']} / {c['wall_max_s']} | {tps} | "
            f"{c['thinking_chars_mean']} | {c['distinct_tool_seqs']} |"
        )
    lines.append("")

    lines.append("## Head-to-head (B minus A)")
    lines.append("")
    lines.append(f"Positive = B (`{b_label}`) is slower / uses more resources")
    lines.append("")
    lines.append("| scenario | Δwall_s | tps_A | tps_B | Δthinking | Δrounds | A_seqs | B_seqs |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for sid, d in sorted(summary["head_to_head"].items()):
        sign = "+" if d["wall_delta_b_minus_a_s"] >= 0 else ""
        lines.append(
            f"| {sid} | {sign}{d['wall_delta_b_minus_a_s']}s | {d['tps_a']} | {d['tps_b']} | "
            f"{d['thinking_delta_b_minus_a']:+} | {d['rounds_delta_b_minus_a']:+} | "
            f"{d['a_distinct_seqs']} | {d['b_distinct_seqs']} |"
        )
    lines.append("")

    lines.append("## Interpretation")
    lines.append("- **tps**: output tokens/sec from Ollama eval_count/eval_duration — lower = slower")
    lines.append("- **Δwall_s**: total wall time difference per scenario per trial")
    lines.append("- **Δthinking**: more positive = B thinks more (longer chains)")
    lines.append("- **distinct_tool_seqs**: variance in tool-call paths; lower = more consistent")
    lines.append("- For quality, review transcripts/ and compare `final_text` fields directly")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
