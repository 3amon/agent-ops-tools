# Thinking-strip A/B — 20260422-104214

Two configs of the within-turn thinking field on assistant messages:

- **keep**: thinking preserved between rounds of the same user turn
- **strip**: thinking removed when replaying own messages to Ollama

Cross-turn history thinking is always stripped in both configs (established prior).

## Per-cell stats

| cell | n | rounds (mean/min/max) | wall s (mean/min/max) | distinct tool sequences |
|---|---|---|---|---|
| date_math/keep | 5 | 3.0 / 3 / 3 | 21.6 / 17.0 / 33.9 | 1 |
| date_math/strip | 5 | 2.8 / 2 / 3 | 21.7 / 16.9 / 25.7 | 2 |
| multi_skill/keep | 5 | 3.0 / 3 / 3 | 27.8 / 19.1 / 32.5 | 1 |
| multi_skill/strip | 5 | 3.0 / 3 / 3 | 21.7 / 16.9 / 28.9 | 1 |
| multi_tool_chain/keep | 5 | 3.4 / 3 / 4 | 24.8 / 17.3 / 31.7 | 1 |
| multi_tool_chain/strip | 5 | 3.6 / 3 / 4 | 36.9 / 15.3 / 70.5 | 2 |
| single_tool_save/keep | 5 | 2.8 / 2 / 3 | 18.3 / 12.2 / 28.4 | 2 |
| single_tool_save/strip | 5 | 3.0 / 3 / 3 | 17.0 / 14.7 / 18.8 | 1 |

## Head-to-head (strip minus keep)

| scenario | Δrounds | Δwall_s | keep_seqs | strip_seqs |
|---|---|---|---|---|
| date_math | -0.2 | +0.1 | 1 | 2 |
| multi_skill | +0.0 | -6.15 | 1 | 1 |
| multi_tool_chain | +0.2 | +12.15 | 1 | 2 |
| single_tool_save | +0.2 | -1.28 | 2 | 1 |

Interpretation:
- Negative Δ = strip is faster/fewer-rounds
- Positive Δ = strip is slower (model floundered without its prior reasoning)
- Higher distinct_tool_seqs = more variance in chosen path (potentially lower consistency)
- For output quality, review transcripts/ directly and compare final_text fields.