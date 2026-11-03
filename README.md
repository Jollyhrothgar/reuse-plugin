# reuse-plugin

A Claude Code plugin that checks whether someone has already built what you are
about to build. Before Claude writes a new skill, plugin, slash command or MCP
server, it searches public registries and returns a verdict: **adopt** an
existing one, **adapt** one, or **build** from scratch (informed by the near
misses).

## Install

```bash
claude plugin marketplace add Jollyhrothgar/reuse-plugin
claude plugin install reuse@reuse-plugin
```

## How it triggers

- **Hook.** A `UserPromptSubmit` hook matches prompts like "make a skill…",
  "create an MCP server…" and tells Claude to run `reuse:find` before
  `skill-creator`.
- **Session hook.** A `SessionStart` hook adds a standing instruction: before
  building any reusable capability during autonomous work, run `reuse:find`.
  The skill's description backs this up.
- **Manually.** Run `/reuse:find <what you need>`.

## Sources

Sources are declared in `skills/find/scripts/sources.json` and searched in
parallel. Duplicates are merged and results ranked by keyword match, usage
(installs or stars), and agreement across sources.

| Source | What it adds |
| --- | --- |
| installed | Skills already on this machine, checked first |
| [skills.sh](https://skills.sh) | Cross-agent skill directory with install counts |
| plugin marketplaces | Every locally registered marketplace, plus `anthropics/claude-plugins-official` |
| [goodailist.com](https://goodailist.com/repos) | Daily ranking of AI repos; star momentum |
| awesome-lists | Curated lists (ComposioHQ, travisvn, hesreallyhim) |
| [MCP registry](https://registry.modelcontextprotocol.io) | Official MCP server registry |
| GitHub code search | Any public `SKILL.md` matching the query |

List-type sources are cached for 24h in `~/.cache/reuse-find/`.

To add a source, add an entry to `sources.json`. To add a new *kind* of
source, write one adapter function in `search.py`. [CONTRIBUTING.md](CONTRIBUTING.md)
walks an agent through either one, including tests and what a PR needs.

```bash
python3 -I skills/find/scripts/search.py "extract tables pdf" --kind skill --limit 10
```

Needs Python 3.10+ and an authenticated `gh` CLI for the GitHub-backed sources.

## Safety

The plugin recommends; it never installs. Third-party skills run with your
permissions, so the skill reads each candidate's actual `SKILL.md`, checks its
license, and flags scripts, network calls and install instructions before
recommending.
