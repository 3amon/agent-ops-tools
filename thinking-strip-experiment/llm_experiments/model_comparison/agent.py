"""Agent loop for model comparison experiment.

Parameterized on `model` name. Thinking is always on (settled from prior experiment).
Cross-turn thinking is stripped, within-turn thinking is kept (also settled).

Unlike thinking_strip/agent.py, we read the full Ollama response body to capture
eval_count and eval_duration so we can compute actual token throughput."""
import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

# Import shared tools from the sibling experiment package
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from llm_experiments.thinking_strip import tools

OLLAMA_URL = "http://127.0.0.1:11434"
MAX_ROUNDS = 6

SYSTEM_PROMPT = (
    "You are a local AI agent. Respond concisely. Use tools when they help; don't narrate calls. "
    "Keep replies short. Use bullets when listing. If you don't know something and no tool can "
    "get it, say so plainly instead of guessing."
)


def _strip_thinking(msg: dict) -> dict:
    if "thinking" not in msg:
        return msg
    return {k: v for k, v in msg.items() if k != "thinking"}


def _ollama_chat(messages: list[dict], schemas: list[dict], model: str) -> tuple[dict, dict]:
    """Returns (message, raw_response_body)."""
    body = {"model": model, "messages": messages, "stream": False, "tools": schemas}
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        raw = json.loads(r.read())
    return raw["message"], raw


def run_turn(prompt: str, *, model: str) -> dict:
    """Run one agent turn with the given model. Returns transcript + metadata."""
    now = datetime.now().astimezone()
    time_line = (
        f"\n\nCurrent time: {now.strftime('%A, %B %d, %Y at %I:%M %p %Z')} "
        f"(ISO: {now.isoformat(timespec='seconds')})."
    )
    system_content = SYSTEM_PROMPT + time_line

    working: list[dict] = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": prompt},
    ]
    transcript: list[dict] = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": prompt},
    ]
    active_skills: set[str] = set()
    tools.reset_state()

    t_start = time.monotonic()
    rounds_used = 0
    tool_call_sequence: list[str] = []
    thinking_chars_per_round: list[int] = []
    # Ollama token metrics summed across all rounds
    total_eval_count = 0
    total_eval_duration_ns = 0
    total_prompt_eval_count = 0

    for round_num in range(MAX_ROUNDS):
        rounds_used += 1
        schemas = tools.schemas_for(active_skills)
        # Cross-turn: strip thinking on history (keep current turn's replies)
        payload_messages = []
        for i, m in enumerate(working):
            # All messages except the final assistant reply can be safely stripped
            # (the final round's reply hasn't been added yet — this is the next request)
            payload_messages.append(_strip_thinking(m))

        t_round_start = time.monotonic()
        reply, raw = _ollama_chat(payload_messages, schemas, model)
        t_round = time.monotonic() - t_round_start

        # Accumulate token metrics
        total_eval_count += raw.get("eval_count", 0)
        total_eval_duration_ns += raw.get("eval_duration", 0)
        total_prompt_eval_count += raw.get("prompt_eval_count", 0)

        thinking = reply.get("thinking") or ""
        thinking_chars_per_round.append(len(thinking))
        working.append(reply)
        transcript.append({
            **reply,
            "_round": round_num,
            "_round_wall_s": round(t_round, 2),
        })

        tool_calls = reply.get("tool_calls") or []
        if not tool_calls:
            break
        for tc in tool_calls:
            fn = tc.get("function", {}) or {}
            name = fn.get("name", "")
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            tool_call_sequence.append(name)
            result = tools.dispatch(name, args, active_skills)
            tool_msg = {"role": "tool", "content": result, "name": name}
            working.append(tool_msg)
            transcript.append({**tool_msg, "_round": round_num})

    wall_s = time.monotonic() - t_start

    # Tokens per second (generation only, not prompt eval)
    tps = (
        (total_eval_count / (total_eval_duration_ns / 1e9))
        if total_eval_duration_ns > 0
        else None
    )

    final = working[-1]
    final_text = final.get("content") or ""
    if not final_text and final.get("tool_calls"):
        final_text = "(model produced a tool call but no text reply)"

    return {
        "model": model,
        "prompt": prompt,
        "rounds_used": rounds_used,
        "wall_s": round(wall_s, 2),
        "tool_call_sequence": tool_call_sequence,
        "thinking_chars_per_round": thinking_chars_per_round,
        "total_thinking_chars": sum(thinking_chars_per_round),
        "eval_tokens": total_eval_count,
        "prompt_tokens": total_prompt_eval_count,
        "tokens_per_second": round(tps, 1) if tps is not None else None,
        "final_text": final_text,
        "transcript": transcript,
    }
