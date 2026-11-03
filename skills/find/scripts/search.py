#!/usr/bin/env python3
"""Search every registered source for existing skills, plugins and MCP servers.

Usage:
  search.py "<what you need>" [--kind skill|plugin|mcp|any] [--limit N]
                               [--sources a,b] [--refresh] [--json]

Sources are declared in sources.json next to this file. Each `type` there maps
to an adapter below. Adapters return candidates in one normalized shape; this
script merges duplicates across sources, scores by query match and usage
signal, and prints a ranked list. A failing source is reported and skipped.

Standard library plus the `gh` CLI (for GitHub sources). No installs.
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures as cf
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "reuse-find"
UA = "reuse-find/0.1 (claude-code plugin)"
TIMEOUT = 20

STOP = {"a", "an", "the", "for", "from", "to", "of", "into", "by", "and", "or", "with", "in", "on",
        "my", "me", "i", "that", "this", "skill", "skills", "claude", "agent",
        "make", "create", "build", "want", "need", "tool", "using", "use"}


# ---------------------------------------------------------------- helpers

def http_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def gh_json(path: str):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=TIMEOUT)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:200])
    return json.loads(out.stdout)


def gh_file(repo: str, path: str) -> str:
    d = gh_json(f"repos/{repo}/contents/{urllib.parse.quote(path)}")
    return base64.b64decode(d["content"]).decode("utf-8", "replace")


def cached(name: str, ttl_hours: float, refresh: bool, fetch):
    """Return fetch() through a per-source JSON cache."""
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', name)}.json"
    if not refresh and f.exists() and time.time() - f.stat().st_mtime < ttl_hours * 3600:
        return json.loads(f.read_text())
    data = fetch()
    f.write_text(json.dumps(data))
    return data


def terms(q: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9][a-z0-9+#.-]*", q.lower()) if t not in STOP]


def match(text: str, ts: list[str]) -> float:
    """Fraction of query terms present in text (prefix match on word starts)."""
    if not ts:
        return 0.0
    words = set(re.findall(r"[a-z0-9][a-z0-9+#.-]*", text.lower()))
    hit = sum(1 for t in ts if t in words or any(w.startswith(t) for w in words if len(t) >= 4))
    return hit / len(ts)


def cand(**kw) -> dict:
    base = {"kind": "skill", "name": "", "repo": "", "url": "", "description": "",
            "installs": None, "stars": None, "star_7d": None, "updated": None,
            "sources": []}
    base.update(kw)
    if base["repo"] and not base["url"]:
        base["url"] = f"https://github.com/{base['repo']}"
    return base


def frontmatter(text: str) -> dict:
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    out = {}
    if m:
        for line in m.group(1).splitlines():
            k, _, v = line.partition(":")
            if v and not line.startswith(" "):
                out[k.strip()] = v.strip().strip("\"'")
    return out


# ---------------------------------------------------------------- adapters
# Each adapter: (src: dict, query: str, ts: list[str], refresh: bool) -> list[cand]

def a_installed(src, query, ts, refresh):
    roots = [Path.home() / ".claude/skills", Path.home() / ".claude/plugins/cache",
             Path.cwd() / ".claude/skills"]
    seen, out = set(), []
    for root in roots:
        if not root.exists():
            continue
        for f in root.rglob("SKILL.md"):
            fm = frontmatter(f.read_text(errors="replace")[:4000])
            name = fm.get("name") or f.parent.name
            if name in seen:
                continue
            seen.add(name)
            out.append(cand(kind="installed", name=name, url=str(f.parent),
                            description=fm.get("description", "")))
    return out


def a_skills_sh(src, query, ts, refresh):
    q = " ".join(ts) or query
    d = http_json("https://skills.sh/api/search?q=" + urllib.parse.quote(q))
    return [cand(kind="skill", name=s["name"], repo=s["source"],
                 url=f"https://skills.sh/{s['id']}", installs=s.get("installs"),
                 description=f"skill `{s['skillId']}` in {s['source']}")
            for s in d.get("skills", [])[:25]]


def a_goodailist(src, query, ts, refresh):
    def fetch():
        rows = {}
        for kw in src.get("keywords", ["Skills"]):
            d = http_json("https://goodailist.com/api/repos?limit=500&keyword=" + urllib.parse.quote(kw))
            for r in d["repos"]:
                if not r.get("archived"):
                    rows[r["repo"]] = {k: r.get(k) for k in
                                       ("repo", "description", "stars", "star_7d", "keywords", "subcat", "updated_at")}
        return list(rows.values())
    rows = cached(src["name"], src.get("ttl_hours", 24), refresh, fetch)
    return [cand(kind="skill" if "Skills" in (r.get("keywords") or "") else "repo",
                 name=r["repo"].split("/")[-1], repo=r["repo"], description=r.get("description") or "",
                 stars=r.get("stars"), star_7d=r.get("star_7d"), updated=(r.get("updated_at") or "")[:10])
            for r in rows]


def a_marketplace(src, query, ts, refresh):
    def plugins_of(mkt: dict, mkt_repo: str):
        out = []
        for p in mkt.get("plugins", []):
            s = p.get("source")
            repo = mkt_repo
            if isinstance(s, dict) and s.get("repo"):
                repo = s["repo"]
            elif isinstance(s, dict) and s.get("url"):
                m = re.search(r"github\.com[/:]([^/]+/[^/.]+)", s["url"])
                repo = m.group(1) if m else mkt_repo
            out.append({"name": p["name"], "repo": repo, "description": p.get("description", ""),
                        "marketplace": mkt.get("name", mkt_repo)})
        return out

    def fetch():
        rows = []
        for repo in src.get("repos", []):
            try:
                rows += plugins_of(json.loads(gh_file(repo, ".claude-plugin/marketplace.json")), repo)
            except Exception as e:  # a repo without a marketplace file is not fatal
                print(f"  [marketplace] {repo}: {e}", file=sys.stderr)
        return rows
    rows = cached(src["name"], src.get("ttl_hours", 24), refresh, fetch)
    if src.get("local_known"):
        for f in (Path.home() / ".claude/plugins/marketplaces").glob("*/.claude-plugin/marketplace.json"):
            try:
                rows += plugins_of(json.loads(f.read_text()), f.parent.parent.name)
            except Exception:
                pass
    return [cand(kind="plugin", name=r["name"], repo=r["repo"], description=r["description"],
                 url=f"plugin {r['name']}@{r['marketplace']}") for r in rows]


LINK = re.compile(r"\[([^\]]+)\]\((https://github\.com/([^/\s)]+/[^/\s)#]+)[^)]*)\)\s*[-–—:]?\s*(.*)")


def a_awesome_list(src, query, ts, refresh):
    def fetch():
        rows = []
        for repo in src.get("repos", []):
            try:
                md = base64.b64decode(gh_json(f"repos/{repo}/readme")["content"]).decode("utf-8", "replace")
            except Exception as e:
                print(f"  [awesome] {repo}: {e}", file=sys.stderr)
                continue
            for line in md.splitlines():
                m = LINK.search(line)
                if m and m.group(3).lower() != repo.lower():
                    rows.append({"name": m.group(1).strip("* "), "repo": m.group(3).removesuffix(".git"),
                                 "url": m.group(2), "description": re.sub(r"[*_`]", "", m.group(4))[:200],
                                 "list": repo})
        return rows
    rows = cached(src["name"], src.get("ttl_hours", 24), refresh, fetch)
    return [cand(kind="skill", name=r["name"], repo=r["repo"], url=r["url"],
                 description=f"{r['description']} (listed in {r['list']})") for r in rows]


def a_mcp_registry(src, query, ts, refresh):
    out = []
    # Registry search is substring on name; query the most specific terms.
    for t in sorted(ts, key=len, reverse=True)[:2]:
        d = http_json("https://registry.modelcontextprotocol.io/v0/servers?limit=20&search=" + urllib.parse.quote(t))
        for s in d.get("servers", []):
            srv = s.get("server", s)
            repo_url = (srv.get("repository") or {}).get("url", "")
            m = re.search(r"github\.com/([^/]+/[^/.]+)", repo_url)
            out.append(cand(kind="mcp", name=srv.get("name", ""), repo=m.group(1) if m else "",
                            url=repo_url or srv.get("websiteUrl", ""), description=srv.get("description", "")))
    return out


def a_github_code(src, query, ts, refresh):
    q = " ".join(ts[:4]) + " filename:SKILL.md"
    d = gh_json("search/code?per_page=30&q=" + urllib.parse.quote(q))
    by_repo = {}
    for it in d.get("items", []):
        by_repo.setdefault(it["repository"]["full_name"], it["path"])
    repos = list(by_repo)[: src.get("max_results", 15)]

    def info(r):
        try:
            j = gh_json(f"repos/{r}")
            return r, j.get("stargazers_count"), j.get("pushed_at", "")[:10], j.get("description") or "", j.get("archived")
        except Exception:
            return r, None, None, "", False
    with cf.ThreadPoolExecutor(8) as ex:
        rows = list(ex.map(info, repos))
    return [cand(kind="skill", name=by_repo[r].rsplit("/", 2)[-2] if "/" in by_repo[r] else r.split("/")[1],
                 repo=r, url=f"https://github.com/{r}/blob/HEAD/{by_repo[r]}", description=desc,
                 stars=stars, updated=pushed)
            for r, stars, pushed, desc, archived in rows if not archived]


ADAPTERS = {
    "installed": a_installed, "skills_sh": a_skills_sh, "goodailist": a_goodailist,
    "marketplace": a_marketplace, "awesome_list": a_awesome_list,
    "mcp_registry": a_mcp_registry, "github_code": a_github_code,
}
# Sources that already filter by the query server-side; others are matched locally.
SERVER_FILTERED = {"skills_sh", "mcp_registry", "github_code"}


# ---------------------------------------------------------------- merge + rank

def popularity(c) -> float:
    vals = [v for v in (c["installs"], c["stars"]) if v]
    p = math.log10(1 + max(vals)) if vals else 0.0
    if c["star_7d"]:
        p += 0.5 * math.log10(1 + c["star_7d"])
    return p


def run(query, kind, limit, only, refresh):
    cfg = json.loads((HERE / "sources.json").read_text())
    srcs = [s for s in cfg["sources"] if s.get("enabled", True) and (not only or s["name"] in only)]
    ts = terms(query)
    results, errors = [], {}

    def go(s):
        return s, ADAPTERS[s["type"]](s, query, ts, refresh)
    with cf.ThreadPoolExecutor(len(srcs) or 1) as ex:
        futs = [ex.submit(go, s) for s in srcs]
        for f in cf.as_completed(futs):
            try:
                s, cs = f.result()
            except Exception as e:  # noqa: BLE001 - one bad source must not sink the search
                errors[str(e)[:40]] = str(e)
                continue
            for c in cs:
                text = f"{c['name']} {c['repo']} {c['description']}"
                c["match"] = match(text, ts)
                if s["type"] in SERVER_FILTERED:
                    # The server matched on content we cannot see; trust it, but below a visible match.
                    c["match"] = max(c["match"], 0.5)
                if c["match"] >= 0.5:
                    c["sources"] = [s["name"]]
                    results.append(c)

    # Merge duplicates (same repo + same name, or same repo for repo-level entries).
    merged: dict[tuple, dict] = {}
    for c in results:
        key = (c["kind"] == "installed", (c["repo"] or c["url"]).lower(), c["name"].lower()
               if c["kind"] in ("plugin", "mcp", "installed") else "")
        if key in merged:
            m = merged[key]
            m["sources"] = sorted(set(m["sources"] + c["sources"]))
            for k in ("installs", "stars", "star_7d", "updated"):
                m[k] = m[k] or c[k]
            if len(c["description"]) > len(m["description"]):
                m["description"] = c["description"]
            m["match"] = max(m["match"], c["match"])
        else:
            merged[key] = dict(c)
    out = list(merged.values())
    if kind != "any":
        out = [c for c in out if c["kind"] in (kind, "installed")]
    for c in out:
        # Match dominates; popularity and cross-source agreement break ties.
        c["score"] = round(c["match"] * 10 + popularity(c) + 0.75 * (len(c["sources"]) - 1), 2)
    installed = sorted((c for c in out if c["kind"] == "installed"), key=lambda c: -c["score"])[:5]
    rest = sorted((c for c in out if c["kind"] != "installed"), key=lambda c: -c["score"])[:limit]
    return installed, rest, errors


def fmt_n(v):
    if v is None:
        return "-"
    return f"{v/1000:.1f}k" if v >= 1000 else str(v)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query")
    ap.add_argument("--kind", default="any", choices=["any", "skill", "plugin", "mcp", "repo"])
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--sources", default="", help="comma list of source names to restrict to")
    ap.add_argument("--refresh", action="store_true", help="ignore caches")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    installed, rest, errors = run(a.query, a.kind, a.limit,
                                  set(filter(None, a.sources.split(","))), a.refresh)
    if a.json:
        json.dump({"query": a.query, "terms": terms(a.query), "installed": installed,
                   "candidates": rest, "errors": list(errors.values())}, sys.stdout, indent=1)
        return
    print(f"query terms: {terms(a.query)}")
    if installed:
        print("\nALREADY INSTALLED (check these first):")
        for c in installed:
            print(f"  - {c['name']}: {c['description'][:110]}")
    print(f"\nCANDIDATES ({len(rest)}):")
    for i, c in enumerate(rest, 1):
        sig = f"installs={fmt_n(c['installs'])} stars={fmt_n(c['stars'])} 7d=+{fmt_n(c['star_7d'])}"
        print(f"{i:>2}. [{c['kind']}] {c['name']}  ({c['repo'] or '-'})  score={c['score']}")
        print(f"    {sig}  updated={c['updated'] or '-'}  via={','.join(c['sources'])}")
        print(f"    {c['description'][:140]}")
        print(f"    {c['url']}")
    for e in errors.values():
        print(f"\n! source error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
