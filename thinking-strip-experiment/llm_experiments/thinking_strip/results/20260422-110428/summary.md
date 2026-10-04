# Thinking-strip A/B — 20260422-110428

Two configs of the within-turn thinking field on assistant messages:

- **keep**: thinking preserved between rounds of the same user turn
- **strip**: thinking removed when replaying own messages to Ollama

Cross-turn history thinking is always stripped in both configs (established prior).

## Per-cell stats

| cell | n | rounds (mean/min/max) | wall s (mean/min/max) | distinct tool sequences |
|---|---|---|---|---|
| conditional_act_on_tool_output/keep | 15 | 4.3 / 2 / 5 | 34.5 / 28.2 / 55.0 | 4 |
| conditional_act_on_tool_output/strip | 15 | 4.2 / 1 / 5 | 37.4 / 24.9 / 61.5 | 5 |
| multi_tool_chain/keep | 15 | 3.5 / 3 / 4 | 29.6 / 20.9 / 41.0 | 1 |
| multi_tool_chain/strip | 14 | 3.9 / 3 / 4 | 44.2 / 21.2 / 189.1 | 1 |
| three_tool_mixed_skills/keep | 12 | 3.0 / 3 / 3 | 48.3 / 34.2 / 106.7 | 1 |
| three_tool_mixed_skills/strip | 15 | 3.1 / 3 / 4 | 50.6 / 28.8 / 95.9 | 1 |

## Head-to-head (strip minus keep)

| scenario | Δrounds | Δwall_s | keep_seqs | strip_seqs |
|---|---|---|---|---|
| conditional_act_on_tool_output | -0.13 | +2.98 | 4 | 5 |
| multi_tool_chain | +0.46 | +14.55 | 1 | 1 |
| three_tool_mixed_skills | +0.13 | +2.31 | 1 | 1 |

Interpretation:
- Negative Δ = strip is faster/fewer-rounds
- Positive Δ = strip is slower (model floundered without its prior reasoning)
- Higher distinct_tool_seqs = more variance in chosen path (potentially lower consistency)
- For output quality, review transcripts/ directly and compare final_text fields.