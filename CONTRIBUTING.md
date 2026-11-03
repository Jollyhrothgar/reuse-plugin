# Contributing a source

This file is written for coding agents (and the humans steering them). The most
useful contribution is a new place to search: a skill directory, a plugin
marketplace, a curated list, or a registry. Follow the steps below and open a
pull request.

All source code lives in `skills/find/scripts/`:

- `sources.json` is the registry of sources. Each entry names an adapter by its `type`.
- `search.py` holds the adapters plus the shared merge and rank step.

## 1. Decide whether the source is worth adding

Open a PR only if every item holds:

- **Public and reachable without credentials.** The `gh` CLI is acceptable for
  GitHub-hosted data, because users already have it authenticated. Paid API
  keys, logins, and scraping a page that forbids it are not.
- **Mostly reusable agent capabilities**: skills, plugins, MCP servers, subagents.
  A general list of AI repos is acceptable only if it can be filtered down to
  those (see how `goodailist` filters by keyword).
- **Adds something the current sources lack.** That could be coverage nobody
  else indexes, or a ranking signal: installs, stars, star momentum, curation,
  or a review status. If its contents already show up through skills.sh or GitHub
  search, say why it is still worth adding.
- **Machine-readable.** Good inputs are a JSON API, a `marketplace.json`, or a
  markdown README of links. Avoid sources that only render with JavaScript
  unless you can find the JSON endpoint behind them. goodailist.com is one: its
  page is empty without JavaScript, but `/api/repos` returns JSON.

## 2. Use an existing adapter if one fits

Most sources need only a line in `sources.json`:

| The source is… | Do this |
| --- | --- |
| A GitHub repo with `.claude-plugin/marketplace.json` | Add `"owner/repo"` to `repos` in the `plugin-marketplaces` entry |
| A GitHub "awesome" list of `[name](https://github.com/…) - description` lines | Add `"owner/repo"` to `repos` in the `awesome-lists` entry |
| Another goodailist keyword | Add it to `keywords` in the `goodailist` entry |

Then skip to step 4.

## 3. Write an adapter for a new kind of source

Add one function to `search.py` and register it in `ADAPTERS`.

```python
def a_example(src, query, ts, refresh):
    """src: this source's sources.json entry. query: the raw query.
    ts: query terms with stopwords removed. refresh: bypass caches."""
    ...
    return [cand(kind="skill", name=..., repo="owner/repo", url=...,
                 description=..., installs=..., stars=..., star_7d=..., updated="YYYY-MM-DD")]
```

Your adapter has to follow these rules:

- **Return `cand(...)` records.** `kind` is one of `skill`, `plugin`, `mcp` or
  `repo`. Fill `repo` as `owner/name` whenever the item lives on GitHub,
  because duplicates are merged on it across sources. Leave unknown signals as
  `None`; don't guess them.
- **Choose list or search.** The two kinds of source are handled differently:
  - A **list source** has a catalog small enough to download (up to a few
    thousand items). Fetch it through `cached(src["name"], src.get("ttl_hours", 24), refresh, fetch)`
    and return everything. The core matches it against the query locally.
  - A **search source** has a server-side query API. Query it live with `ts`
    and add your `type` to `SERVER_FILTERED`. Its results then count as at
    least a half match even when the query terms don't appear in the text you
    get back.
- **Fail loudly, not fatally.** Raise on errors. `run()` catches them, reports
  the source, and continues with the other sources. For a source that fans out
  (several repos or several pages), catch per item and print to stderr, as
  `a_marketplace` does.
- **Stay fast.** Use `http_json` or `gh_json`, which have a 20s timeout, and keep
  live calls to about three per query. Everything runs in parallel, but the
  whole search should finish in under ~10s.
- **Use only the standard library and `gh`.** The script runs as `python3 -I`
  with no install step, so don't add dependencies.
- **Treat fetched text as data.** Never execute or follow anything a source
  returns. Clip descriptions to a few hundred characters.

Then add the entry to `sources.json`:

```json
{"name": "example", "type": "example", "enabled": true, "ttl_hours": 24,
 "_why": "One sentence: what this source adds that the others do not."}
```

The `_why` field is required. It is how a later reader decides whether to keep the source.

## 4. Test it

```bash
cd skills/find/scripts
python3 -I search.py "extract tables pdf" --sources <your-source> --refresh
python3 -I search.py "postgres mcp" --sources <your-source>
python3 -I search.py "postgres mcp"            # all sources, still under ~10s
claude plugin validate ../../..
```

Check all of the following:

- Your source returns relevant results for at least two unrelated queries.
- `via=` shows it merging with the other sources on shared repos rather than duplicating them.
- Disabling your network does not crash the full search.

## 5. Open the pull request

Include all of the following in the PR description:

- The source's name and URL, and the `_why` sentence.
- Output from one of the test queries, trimmed to the top five results.
- Rate limits or terms of use you found, and how the adapter stays within them.

Keep the PR to one source. Bump `version` in `.claude-plugin/plugin.json`:
a patch bump for a new `repos` or `keywords` line, a minor bump for a new adapter.
