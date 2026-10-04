"""Fake tools for the thinking-strip A/B experiment.

These match the shape of the real assistant's tools (so the agent sees the same surface)
but return canned responses to keep the test fast and deterministic. The experiment
measures agent reasoning behavior, not tool correctness."""
import json
import secrets
from datetime import date


_reminders: dict[str, dict] = {}  # in-memory store, reset per run


LOAD_SKILL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "load_skill",
        "description": (
            "Load a skill to unlock its tools for this session. Call this FIRST when the user "
            "wants functionality not in your always-available tools. After loading, the skill's "
            "tools appear in your tool list and you call them normally.\n\n"
            "Available skills:\n"
            "  - weather: current conditions, forecast, alerts.\n"
            "  - news: recent news headlines (titles and links only).\n"
            "  - reminders: manage todos, ideas, recurring bills / appointments.\n\n"
            "Skills are loaded for the current turn only. Emit multiple load_skill calls "
            "if a single turn needs multiple skills (parallel in one round is fine)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill to load.",
                    "enum": ["weather", "news", "reminders"],
                },
            },
            "required": ["name"],
        },
    },
}

WEATHER_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": (
            "Get current weather and multi-day forecast. Returns current conditions, daily "
            "highs/lows, precipitation, and wind. Default location: Oakland, CA."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location": {"type": "string"},
                "days": {"type": "number"},
            },
        },
    },
}

HEADLINES_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_headlines",
        "description": "Fetch top news headlines (NPR). Titles + links only.",
        "parameters": {
            "type": "object",
            "properties": {"limit": {"type": "number"}},
        },
    },
}

REMEMBER_SCHEMA = {
    "type": "function",
    "function": {
        "name": "remember",
        "description": (
            "Save a reminder. Returns the created item including its id. "
            "Resolve natural-language dates to ISO YYYY-MM-DD before calling. "
            "CRITICAL: you MUST emit this call if you decide to save — don't just say "
            "'I'll save that' without actually calling it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "notes": {"type": "string"},
                "type": {"type": "string"},
                "urgency": {"type": "string", "enum": ["low", "medium", "high"]},
                "due_date": {"type": "string", "description": "ISO YYYY-MM-DD"},
                "recurrence": {
                    "type": "string",
                    "enum": ["none", "daily", "weekly", "monthly", "yearly"],
                },
                "recurrence_config": {"type": "object"},
            },
            "required": ["title"],
        },
    },
}

LIST_REMINDERS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_reminders",
        "description": (
            "List reminders. Filters: open, overdue, today, this_week, upcoming, archived, all."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "enum": ["all", "open", "overdue", "today", "this_week", "upcoming", "archived"],
                },
            },
        },
    },
}

SKILLS: dict[str, dict] = {
    "weather": {"description": "weather + forecast", "tool_names": ["get_weather"]},
    "news": {"description": "news headlines", "tool_names": ["get_headlines"]},
    "reminders": {
        "description": "manage todos / bills / appointments",
        "tool_names": ["remember", "list_reminders"],
    },
}

TOOL_SCHEMAS: dict[str, dict] = {
    "get_weather": WEATHER_SCHEMA,
    "get_headlines": HEADLINES_SCHEMA,
    "remember": REMEMBER_SCHEMA,
    "list_reminders": LIST_REMINDERS_SCHEMA,
}


def schemas_for(active_skills: set[str]) -> list[dict]:
    result = [LOAD_SKILL_SCHEMA]
    seen = {"load_skill"}
    for skill_name in active_skills:
        skill = SKILLS.get(skill_name)
        if not skill:
            continue
        for tool_name in skill["tool_names"]:
            if tool_name in seen:
                continue
            if tool_name in TOOL_SCHEMAS:
                result.append(TOOL_SCHEMAS[tool_name])
                seen.add(tool_name)
    return result


def reset_state() -> None:
    global _reminders
    _reminders = {}


def dispatch(name: str, args: dict, active_skills: set[str]) -> str:
    """Fake dispatch. Same signature as the real one, but canned responses."""
    if name == "load_skill":
        skill_name = (args or {}).get("name", "")
        if skill_name not in SKILLS:
            return json.dumps({"error": f"unknown skill {skill_name!r}"})
        active_skills.add(skill_name)
        return json.dumps({
            "loaded": skill_name,
            "description": SKILLS[skill_name]["description"],
            "tools_now_available": SKILLS[skill_name]["tool_names"],
        })

    if name == "get_weather":
        # Fake but deterministic weather. Saturday 2026-04-25 is unambiguously "nice"
        # (Clear, 0% precip) so the conditional_act scenario has a clear correct path.
        return json.dumps({
            "location": "Oakland, CA",
            "current": {"temp_f": 59, "condition": "Overcast", "wind_mph": 7},
            "daily": [
                {"date": "2026-04-22", "condition": "Overcast", "high_f": 62, "low_f": 50, "precip_chance_pct": 20},
                {"date": "2026-04-23", "condition": "Rain", "high_f": 58, "low_f": 48, "precip_chance_pct": 80},
                {"date": "2026-04-24", "condition": "Partly cloudy", "high_f": 64, "low_f": 49, "precip_chance_pct": 10},
                {"date": "2026-04-25", "condition": "Clear", "high_f": 70, "low_f": 51, "precip_chance_pct": 0},
                {"date": "2026-04-26", "condition": "Clear", "high_f": 72, "low_f": 52, "precip_chance_pct": 0},
                {"date": "2026-04-27", "condition": "Partly cloudy", "high_f": 68, "low_f": 51, "precip_chance_pct": 15},
                {"date": "2026-04-28", "condition": "Clear", "high_f": 71, "low_f": 52, "precip_chance_pct": 5},
            ],
            "alerts": ["Heavy rain: 2026-04-23 — 0.8in expected"],
            "changes": [],
        })

    if name == "get_headlines":
        return json.dumps({
            "source": "NPR Top Stories",
            "count": 4,
            "headlines": [
                {"title": "Fed holds rates steady, signals one more cut this year", "link": "https://npr.example/1"},
                {"title": "European leaders convene emergency climate summit", "link": "https://npr.example/2"},
                {"title": "Supreme Court hears arguments on social media liability", "link": "https://npr.example/3"},
                {"title": "New study links screen time to sleep disruption in teens", "link": "https://npr.example/4"},
            ],
        })

    if name == "remember":
        a = args or {}
        title = (a.get("title") or "").strip()
        if not title:
            return json.dumps({"error": "title is required"})
        due = a.get("due_date")
        if due:
            try:
                date.fromisoformat(due)
            except (ValueError, TypeError):
                return json.dumps({
                    "error": f"Invalid due_date {due!r}. Expected ISO YYYY-MM-DD. "
                    "Resolve natural-language dates before calling."
                })
        rid = "r_" + secrets.token_hex(3)
        item = {
            "id": rid,
            "title": title,
            "type": a.get("type"),
            "urgency": a.get("urgency", "medium"),
            "due_date": due,
            "recurrence": a.get("recurrence", "none"),
            "recurrence_config": a.get("recurrence_config"),
            "completions": [],
            "status": "open",
        }
        _reminders[rid] = item
        return json.dumps({"created": item})

    if name == "list_reminders":
        items = list(_reminders.values())
        today = date.today().isoformat()
        filt = (args or {}).get("filter", "open")
        out = []
        for r in items:
            if r["status"] == "archived" and filt != "archived":
                continue
            due = r.get("due_date")
            if filt == "all" or filt == "open":
                out.append(r)
            elif filt == "this_week" and due:
                try:
                    d = date.fromisoformat(due)
                    t = date.fromisoformat(today)
                    if 0 <= (d - t).days <= 7:
                        out.append(r)
                except ValueError:
                    pass
            elif filt == "today" and due == today:
                out.append(r)
            elif filt == "upcoming" and due and due >= today:
                out.append(r)
        return json.dumps({"count": len(out), "items": out, "today": today})

    return json.dumps({"error": f"unknown tool {name!r}"})
