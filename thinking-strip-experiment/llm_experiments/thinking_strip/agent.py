"""Minimal agent loop for the thinking-strip A/B.

Two configs:
  - "keep":  thinking preserved on within-turn replies (round N's thinking visible in round N+1)
  - "strip": thinking stripped on within-turn replies (model must re-derive plan each round)

Historical cross-turn thinking is always stripped (we established separately that's a pure
context-bloat win). This experiment isolates the within-turn behavior.

No external deps — stdlib urllib for the Ollama call. Sync, no asyncio."""
import json
import time
import urllib.request
from datetime import datetime

from . import tools

OLLAMA_URL = "http://127.0.0.1:11434"
MODEL = "qwen3.6:35b-a3b-fast"
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


def _ollama_chat(messages: list[dict], schemas: list[dict]) -> dict:
    body = {"model": MODEL, "messages": messages, "stream": False, "tools": schemas}
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())["message"]


def run_turn(prompt: str, *, strip_within_turn: bool) -> dict:
    """Run one agent turn. Returns a full transcript + metadata."""
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

    for round_num in range(MAX_ROUNDS):
        rounds_used += 1
        schemas = tools.schemas_for(active_skills)
        payload_messages = [_strip_thinking(m) if strip_within_turn else m for m in working]
        t_round_start = time.monotonic()
        reply = _ollama_chat(payload_messages, schemas)
        t_round = time.monotonic() - t_round_start

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
    final = working[-1]
    final_text = final.get("content") or ""
    if not final_text and final.get("tool_calls"):
        final_text = "(model tried to call a tool but didn't produce a final reply)"

    return {
        "prompt": prompt,
        "config": "strip" if strip_within_turn else "keep",
        "rounds_used": rounds_used,
        "wall_s": round(wall_s, 2),
        "tool_call_sequence": tool_call_sequence,
        "thinking_chars_per_round": thinking_chars_per_round,
        "final_text": final_text,
        "transcript": transcript,
    }
