#!/usr/bin/env python3
"""SessionStart hook: standing instruction for autonomous work. Lives in the
plugin rather than ~/.claude/CLAUDE.md so it travels with the plugin and needs
no dotfile (chezmoi ignores ~/.claude on the personal profile)."""
import json

print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": (
        "Before building any reusable capability (a skill, plugin, slash command, "
        "subagent, MCP server, or a general-purpose script/workflow someone else has "
        "plausibly written), run the reuse:find skill to check for an existing one. "
        "Skip it for one-off code specific to the current project."
    ),
}}))
