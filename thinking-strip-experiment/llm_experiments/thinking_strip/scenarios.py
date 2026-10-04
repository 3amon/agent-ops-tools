"""Multi-tool scenarios for the thinking-strip A/B v2.

v1 showed a +12s wall-time penalty and a 20% rate of dropped-step failures on
multi_tool_chain when stripping. These scenarios tighten that signal and extend to:
  - longer chains (3 tools across 2 skills)
  - conditional logic (model uses tool output to decide whether to call next tool)"""

SCENARIOS = [
    {
        "id": "multi_tool_chain",
        "prompt": "Remind me to pay rent on the 1st of each month, then tell me what's on my list this week.",
        "note": "Same as v1 run for continuity. skill-load + remember + list_reminders + reply (~4 rounds).",
        "expected_tools": {"load_skill", "remember", "list_reminders"},
    },
    {
        "id": "three_tool_mixed_skills",
        "prompt": "Save a reminder to pay rent on the 1st of each month, tell me what's on my list this week, and tell me the weather forecast.",
        "note": "Two skills (reminders + weather), three tool calls in one turn.",
        "expected_tools": {"load_skill", "remember", "list_reminders", "get_weather"},
    },
    {
        "id": "conditional_act_on_tool_output",
        "prompt": "Check the weather for this Saturday. If it's not going to rain, remind me to wash my car that day.",
        "note": (
            "Model must load weather, call get_weather, READ the result, decide (Saturday 4/25 is "
            "clear with 0% precip in the fake data → condition triggers), load reminders, and "
            "call remember. This is the plan-continuity test — strip breaks it if model forgets "
            "it was supposed to save a reminder conditional on the weather check."
        ),
        "expected_tools": {"load_skill", "get_weather", "remember"},
    },
]
