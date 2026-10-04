# Model Comparison — 20260423-075437

**A**: `qwen3.6:35b-a3b-fast` — MoE, 3B active / 35B total, fast quant (production)
**B**: `qwen3.6:27b` — dense 27B (newly released)

Scenarios, tools, and system prompt identical to thinking_strip experiment.
Thinking: always on. Within-turn thinking: kept. Cross-turn: stripped.

## Per-cell stats

| cell | n | rounds | wall s (mean/min/max) | tps | thinking chars | distinct tool seqs |
|---|---|---|---|---|---|---|
| conditional_act_on_tool_output/27b | 9 | 4.44 | 163.7 / 94.1 / 274.8 | 9.4 | 3167 | 4 |
| conditional_act_on_tool_output/35b-a3b-fast | 10 | 4.5 | 43.2 / 29.8 / 55.9 | 30.3 | 2517 | 4 |
| multi_tool_chain/27b | 8 | 3.25 | 131.2 / 72.5 / 208.1 | 9.4 | 2682 | 1 |
| multi_tool_chain/35b-a3b-fast | 10 | 4.2 | 56.5 / 26.6 / 257.2 | 30.2 | 3941 | 2 |
| three_tool_mixed_skills/27b | 9 | 3.0 | 162.6 / 122.5 / 209.6 | 9.3 | 2688 | 1 |
| three_tool_mixed_skills/35b-a3b-fast | 10 | 3.0 | 41.6 / 24.1 / 68.2 | 30.2 | 2146 | 1 |

## Head-to-head (B minus A)

Positive = B (`27b`) is slower / uses more resources

| scenario | Δwall_s | tps_A | tps_B | Δthinking | Δrounds | A_seqs | B_seqs |
|---|---|---|---|---|---|---|---|
| conditional_act_on_tool_output | +120.5s | 30.3 | 9.4 | +650 | -0.06 | 4 | 4 |
| multi_tool_chain | +74.7s | 30.2 | 9.4 | -1259 | -0.95 | 2 | 1 |
| three_tool_mixed_skills | +121.0s | 30.2 | 9.3 | +542 | +0.0 | 1 | 1 |

## Interpretation
- **tps**: output tokens/sec from Ollama eval_count/eval_duration — lower = slower
- **Δwall_s**: total wall time difference per scenario per trial
- **Δthinking**: more positive = B thinks more (longer chains)
- **distinct_tool_seqs**: variance in tool-call paths; lower = more consistent
- For quality, review transcripts/ and compare `final_text` fields directly