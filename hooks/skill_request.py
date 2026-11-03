#!/usr/bin/env python3
"""UserPromptSubmit hook: when a prompt asks to build a skill/plugin/MCP server,
inject a reminder to run reuse:find first. Model judgment alone misses this
too often because skill-creator competes for the same trigger."""
import json
import re
import sys

PATTERN = re.compile(
    r"\b(make|create|write|build|scaffold|draft|author|generate|new|add)\b"
    r"[^.?!\n]{0,40}?\b(skills?|plugins?|slash[- ]commands?|subagents?|mcp(?: server)?s?)\b",
    re.I,
)

try:
    prompt = json.load(sys.stdin).get("prompt", "")
except Exception:
    sys.exit(0)

if PATTERN.search(prompt) and "/reuse:find" not in prompt:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": (
            "This request looks like building a skill/plugin/MCP server. Before creating "
            "anything (and before skill-creator), invoke the reuse:find skill to check "
            "whether an existing one should be adopted or adapted. Skip only if the user "
            "already said they want it built from scratch."
        ),
    }}))
