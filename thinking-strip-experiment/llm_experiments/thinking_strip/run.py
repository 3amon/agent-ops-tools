"""Run the thinking-strip A/B experiment.

Interleaves trials (shuffled with a fixed seed) to average out any Ollama warmup
or time-of-day drift. Saves full transcripts + a summary to results/<timestamp>/."""
import json
import random
from datetime import datetime
from pathlib import Path

from .agent import run_turn
from .scenarios import SCENARIOS

REPS = 15
CONFIGS = ["keep", "strip"]
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
            for config in CONFIGS:
                trials.append((scenario, rep, config))
    rng = random.Random(42)
    rng.shuffle(trials)

    total = len(trials)
    print(f"[run] total trials: {total}  (scenarios={len(SCENARIOS)} x configs={len(CONFIGS)} x reps={REPS})")

    results: list[dict] = []
    for i, (scenario, rep, config) in enumerate(trials, 1):
        strip = (config == "strip")
        t0 = datetime.now()
        print(f"[{i}/{total}] {scenario['id']} rep={rep} config={config} ...", flush=True)
        try:
            result = run_turn(scenario["prompt"], strip_within_turn=strip)
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}", flush=True)
            result = {"error": f"{type(e).__name__}: {e}", "config": config}
        elapsed = (datetime.now() - t0).total_seconds()
        print(f"  done in {elapsed:.1f}s  rounds={result.get('rounds_used','?')}  "
              f"tools={result.get('tool_call_sequence', [])}", flush=True)

        meta = {
            "scenario_id": scenario["id"],
            "scenario_prompt": scenario["prompt"],
            "rep": rep,
            "config": config,
            **result,
        }
        results.append(meta)
        fname = f"{scenario['id']}__{config}__rep{rep}.json"
        (transcripts_dir / fname).write_text(json.dumps(meta, indent=2, default=str))

    summary = _summarize(results)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    (run_dir / "summary.md").write_text(_format_summary_md(summary, timestamp))
    print(f"\n[run] DONE. Summary at {run_dir}/summary.md")


def _summarize(results: list[dict]) -> dict:
    by_scenario_config: dict = {}
    for r in results:
        if "error" in r and "rounds_used" not in r:
            continue
        key = (r["scenario_id"], r["config"])
        by_scenario_config.setdefault(key, []).append(r)

    summary: dict = {"cells": {}, "scenarios": {}}
    for (sid, cfg), trials in by_scenario_config.items():
        rounds = [t["rounds_used"] for t in trials]
        walls = [t["wall_s"] for t in trials]
        tool_seqs = [tuple(t["tool_call_sequence"]) for t in trials]
        summary["cells"][f"{sid}/{cfg}"] = {
            "n": len(trials),
            "rounds_mean": sum(rounds) / len(rounds),
            "rounds_min": min(rounds),
            "rounds_max": max(rounds),
            "wall_mean_s": sum(walls) / len(walls),
            "wall_min_s": min(walls),
            "wall_max_s": max(walls),
            "distinct_tool_seqs": len(set(tool_seqs)),
            "most_common_seq": list(max(set(tool_seqs), key=tool_seqs.count)),
        }

    for sid in {r["scenario_id"] for r in results if "rounds_used" in r}:
        keep = summary["cells"].get(f"{sid}/keep")
        strip = summary["cells"].get(f"{sid}/strip")
        if not (keep and strip):
            continue
        summary["scenarios"][sid] = {
            "rounds_delta_mean": round(strip["rounds_mean"] - keep["rounds_mean"], 2),
            "wall_delta_mean_s": round(strip["wall_mean_s"] - keep["wall_mean_s"], 2),
            "strip_distinct_seqs": strip["distinct_tool_seqs"],
            "keep_distinct_seqs": keep["distinct_tool_seqs"],
        }
    return summary


def _format_summary_md(summary: dict, ts: str) -> str:
    lines = [f"# Thinking-strip A/B — {ts}", ""]
    lines.append("Two configs of the within-turn thinking field on assistant messages:")
    lines.append("")
    lines.append("- **keep**: thinking preserved between rounds of the same user turn")
    lines.append("- **strip**: thinking removed when replaying own messages to Ollama")
    lines.append("")
    lines.append("Cross-turn history thinking is always stripped in both configs (established prior).")
    lines.append("")
    lines.append("## Per-cell stats")
    lines.append("")
    lines.append("| cell | n | rounds (mean/min/max) | wall s (mean/min/max) | distinct tool sequences |")
    lines.append("|---|---|---|---|---|")
    for key in sorted(summary["cells"]):
        c = summary["cells"][key]
        lines.append(
            f"| {key} | {c['n']} | {c['rounds_mean']:.1f} / {c['rounds_min']} / {c['rounds_max']} | "
            f"{c['wall_mean_s']:.1f} / {c['wall_min_s']:.1f} / {c['wall_max_s']:.1f} | "
            f"{c['distinct_tool_seqs']} |"
        )
    lines.append("")
    lines.append("## Head-to-head (strip minus keep)")
    lines.append("")
    lines.append("| scenario | Δrounds | Δwall_s | keep_seqs | strip_seqs |")
    lines.append("|---|---|---|---|---|")
    for sid, d in sorted(summary["scenarios"].items()):
        lines.append(
            f"| {sid} | {d['rounds_delta_mean']:+} | {d['wall_delta_mean_s']:+} | "
            f"{d['keep_distinct_seqs']} | {d['strip_distinct_seqs']} |"
        )
    lines.append("")
    lines.append("Interpretation:")
    lines.append("- Negative Δ = strip is faster/fewer-rounds")
    lines.append("- Positive Δ = strip is slower (model floundered without its prior reasoning)")
    lines.append("- Higher distinct_tool_seqs = more variance in chosen path (potentially lower consistency)")
    lines.append("- For output quality, review transcripts/ directly and compare final_text fields.")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
