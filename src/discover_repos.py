# discover_repos.py
# -*- coding: utf-8 -*-
"""
Discover GitHub repositories by topics/keywords/languages with robust pagination,
rate limit handling, de-dup, and optional org harvesting. Outputs a CSV that
feeds into gh_enrich.py / score_tools_v2.py.

Usage examples (Windows PowerShell/CMD):
  # 1) 以主题与语言组合搜索，近180天更新，星标>=50
  python discover_repos.py --topics chem,bio,genomics --languages python --min-stars 50 --pushed-since 180 --out repos.csv

  # 2) 自定义查询关键词，拉更多语言，多页
  python discover_repos.py --queries "quantum chemistry","single-cell" --languages python,c++,rust --min-stars 10 --max-pages 10 --out repos.csv

  # 3) 直接把几个组织的仓库全抓进来（不经搜索）
  python discover_repos.py --orgs deepchem,scverse --out repos.csv

  # 4) 包含 archived，放开星标下限，抓更久以前
  python discover_repos.py --topics docking,materials --min-stars 0 --include-archived --created-since 1095 --out repos.csv

Environment:
  - Reads GITHUB_TOKEN from environment if not provided via --token
"""
from __future__ import annotations

import os
import re
import sys
import csv
import time
import math
import json
import argparse
import datetime as dt
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import requests

API = "https://api.github.com"
HEADERS = {"Accept": "application/vnd.github+json"}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# ---------- utils ----------

def parse_csv_list(s: Optional[str]) -> List[str]:
    if not s:
        return []
    # split by comma, strip spaces, dedup preserving order
    items = [x.strip() for x in s.split(",") if x.strip()]
    seen, out = set(), []
    for x in items:
        if x.lower() not in seen:
            seen.add(x.lower())
            out.append(x)
    return out

def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)

def iso_days_ago(days: int) -> str:
    t = now_utc() - dt.timedelta(days=int(days))
    return t.strftime("%Y-%m-%d")

def sleep_with_log(sec: float, why: str):
    sec = max(0.0, sec)
    print(f"[throttle] sleep {sec:.1f}s ({why})")
    time.sleep(sec)

def rate_limit_wait(r: requests.Response) -> bool:
    """
    If rate limited, compute wait time till reset and sleep.
    Return True if we slept, else False.
    """
    if r.status_code != 403:
        return False
    try:
        msg = r.json().get("message", "").lower()
    except Exception:
        msg = ""
    if "rate limit" not in msg:
        return False

    reset_epoch = r.headers.get("X-RateLimit-Reset")
    remaining = r.headers.get("X-RateLimit-Remaining")
    if reset_epoch:
        try:
            reset_ts = int(reset_epoch)
            wait = max(0, reset_ts - int(time.time())) + 5
            sleep_with_log(wait, f"rate limit reset (remaining={remaining})")
            return True
        except Exception:
            pass
    # fallback: sleep fixed time
    sleep_with_log(30, "rate limit fallback")
    return True

def backoff_sleep(i: int, reason: str):
    # exponential backoff: 1, 2, 4, 8, ... up to ~60
    sec = min(60, 2 ** max(0, i))
    sleep_with_log(sec, f"backoff {reason}")

def robust_get(url: str, params: Dict = None, token: Optional[str] = None, max_retry: int = 5) -> requests.Response:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for i in range(max_retry + 1):
        try:
            resp = SESSION.get(url, params=params, headers=headers, timeout=30)
        except requests.RequestException as e:
            if i == max_retry:
                raise
            backoff_sleep(i, f"network error {e}")
            continue

        if resp.status_code == 200:
            return resp

        if rate_limit_wait(resp):
            # after sleep, retry immediately
            continue

        # other errors: 4xx/5xx -> backoff + retry
        if i == max_retry:
            return resp
        backoff_sleep(i, f"HTTP {resp.status_code}")
    return resp

# ---------- Search helpers ----------

def build_search_queries(
    topics: List[str],
    queries: List[str],
    languages: List[str],
    min_stars: int,
    pushed_since_days: Optional[int],
    created_since_days: Optional[int],
    include_archived: bool,
) -> List[str]:
    """
    Produce a list of GitHub Search qualifiers strings.
    We build them combinatorially but keep them simple to avoid hitting 1000 cap too early.
    """
    # base filters
    base = []
    if min_stars > 0:
        base.append(f"stars:>={min_stars}")
    if not include_archived:
        base.append("archived:false")
    if pushed_since_days:
        base.append(f"pushed:>={iso_days_ago(pushed_since_days)}")
    if created_since_days:
        base.append(f"created:>={iso_days_ago(created_since_days)}")

    base_q = " ".join(base).strip()

    lang_parts = languages or [""]
    # build topic queries
    topic_terms = [f"topic:{t}" for t in topics] if topics else []
    term_list = topic_terms + queries
    if not term_list:
        # if user gave nothing, fallback to a broad science umbrella
        term_list = ["chemistry", "bioinformatics", "genomics", "materials", "single-cell", "molecular"]

    # produce all combinations of (term x language)
    out = []
    for term in term_list:
        term_q = term.strip()
        for lang in lang_parts:
            parts = []
            if term_q:
                parts.append(term_q)
            if lang:
                parts.append(f"language:{lang}")
            if base_q:
                parts.append(base_q)
            q = " ".join(parts).strip()
            out.append(q)
    return out

def search_repos_one_query(q: str, per_page: int, max_pages: int, sort: str, order: str, token: Optional[str]) -> Iterable[dict]:
    """
    Iterate through paginated search results for query q.
    """
    max_pages = max(1, min(max_pages, 10))  # GitHub search caps at 1000 items (10 pages * 100)
    for page in range(1, max_pages + 1):
        params = {
            "q": q,
            "per_page": max(1, min(per_page, 100)),
            "page": page,
            "sort": sort,
            "order": order,
        }
        r = robust_get(f"{API}/search/repositories", params=params, token=token)
        if r.status_code != 200:
            print(f"[warn] search HTTP {r.status_code}, q='{q}', page={page}, body={r.text[:200]}")
            break
        data = r.json()
        items = data.get("items") or []
        if not items:
            break
        for it in items:
            yield it
        # heuristic: if fewer than per_page returned, next page likely empty
        if len(items) < params["per_page"]:
            break

def harvest_org_repos(org: str, per_page: int, max_pages: int, token: Optional[str]) -> Iterable[dict]:
    """
    Iterate through all public repos of an organization.
    """
    for page in range(1, max_pages + 1):
        params = {"per_page": max(1, min(per_page, 100)), "page": page, "type": "public", "sort": "updated"}
        r = robust_get(f"{API}/orgs/{org}/repos", params=params, token=token)
        if r.status_code != 200:
            print(f"[warn] org {org} HTTP {r.status_code}: {r.text[:200]}")
            break
        arr = r.json()
        if not isinstance(arr, list) or not arr:
            break
        for it in arr:
            yield it
        if len(arr) < params["per_page"]:
            break

# ---------- CSV IO ----------

CSV_FIELDS = [
    "full_name",
    "html_url",
    "description",
    "language",
    "stargazers_count",
    "forks_count",
    "open_issues_count",
    "archived",
    "topics",
    "license",
    "pushed_at",
    "created_at",
    "updated_at",
    "default_branch",
]

def normalize_item(it: dict) -> dict:
    license_name = ""
    lic = it.get("license")
    if isinstance(lic, dict):
        license_name = lic.get("spdx_id") or lic.get("key") or lic.get("name") or ""
    topics = it.get("topics") or []
    if not isinstance(topics, list):
        topics = []
    return {
        "full_name": it.get("full_name", ""),
        "html_url": it.get("html_url", ""),
        "description": (it.get("description") or "")[:5000],
        "language": it.get("language") or "",
        "stargazers_count": it.get("stargazers_count") or 0,
        "forks_count": it.get("forks_count") or 0,
        "open_issues_count": it.get("open_issues_count") or 0,
        "archived": bool(it.get("archived")),
        "topics": ";".join(topics),
        "license": license_name,
        "pushed_at": it.get("pushed_at") or "",
        "created_at": it.get("created_at") or "",
        "updated_at": it.get("updated_at") or "",
        "default_branch": it.get("default_branch") or "",
    }

def load_existing(out_path: Path) -> set:
    if not out_path.exists():
        return set()
    try:
        with out_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if "full_name" not in reader.fieldnames:
                return set()
            return {row["full_name"] for row in reader if row.get("full_name")}
    except Exception:
        return set()

def append_rows(out_path: Path, rows: List[dict]):
    file_exists = out_path.exists()
    with out_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        for r in rows:
            writer.writerow(r)

# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topics", default="", help="Comma-separated topics. e.g. chem,bio,genomics")
    ap.add_argument("--queries", default="", help="Comma-separated free-text queries. e.g. 'quantum chemistry','single-cell'")
    ap.add_argument("--languages", default="python", help="Comma-separated languages. e.g. python,c++,rust")
    ap.add_argument("--min-stars", type=int, default=50, help="Minimum stars")
    ap.add_argument("--pushed-since", type=int, default=1095, help="Days since last push (updated). 0 to disable")
    ap.add_argument("--created-since", type=int, default=0, help="Days since creation. 0 to disable")
    ap.add_argument("--include-archived", action="store_true", help="Include archived repos (default: exclude)")
    ap.add_argument("--per-page", type=int, default=100)
    ap.add_argument("--max-pages", type=int, default=10, help="Up to 10 for search (GitHub cap ~1000 results per query)")
    ap.add_argument("--sort", default="stars", choices=["stars", "updated", "best-match"])
    ap.add_argument("--order", default="desc", choices=["desc", "asc"])
    ap.add_argument("--orgs", default="", help="Comma-separated orgs to harvest in addition to search. e.g. deepchem,scverse")
    ap.add_argument("--out", default="repos.csv", help="Output CSV path")
    ap.add_argument("--token", default=None, help="GitHub token (else read from env GITHUB_TOKEN)")
    args = ap.parse_args()

    token = args.token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("[warn] No GITHUB_TOKEN provided. You may hit rate limits quickly.")

    topics = parse_csv_list(args.topics)
    queries = parse_csv_list(args.queries)
    languages = parse_csv_list(args.languages) or [""]
    orgs = parse_csv_list(args.orgs)

    out_path = Path(args.out)
    seen = load_existing(out_path)
    print(f"[info] Output: {out_path} (seen={len(seen)})")

    # 1) Harvest orgs (optional)
    total_new = 0
    for org in orgs:
        print(f"[org] Harvesting org: {org}")
        batch = []
        for it in harvest_org_repos(org, per_page=args.per_page, max_pages=args.max_pages, token=token):
            fn = it.get("full_name")
            if not fn or fn in seen:
                continue
            row = normalize_item(it)
            batch.append(row)
            seen.add(fn)
            if len(batch) >= 200:
                append_rows(out_path, batch)
                total_new += len(batch)
                print(f"[org:{org}] +{len(batch)} (cum={total_new})")
                batch = []
        if batch:
            append_rows(out_path, batch)
            total_new += len(batch)
            print(f"[org:{org}] +{len(batch)} (cum={total_new})")

    # 2) Search combos
    queries_built = build_search_queries(
        topics=topics,
        queries=queries,
        languages=languages,
        min_stars=args.min_stars,
        pushed_since_days=(args.pushed_since if args.pushed_since > 0 else None),
        created_since_days=(args.created_since if args.created_since > 0 else None),
        include_archived=args.include_archived,
    )
    # 去重避免重复搜索
    queries_built = list(dict.fromkeys(queries_built))
    print(f"[info] Built {len(queries_built)} search queries")

    for idx, q in enumerate(queries_built, 1):
        print(f"[search {idx}/{len(queries_built)}] q=\"{q}\"")
        batch = []
        for it in search_repos_one_query(q, per_page=args.per_page, max_pages=args.max_pages,
                                         sort=args.sort, order=args.order, token=token):
            fn = it.get("full_name")
            if not fn or fn in seen:
                continue
            row = normalize_item(it)
            batch.append(row)
            seen.add(fn)
            if len(batch) >= 200:
                append_rows(out_path, batch)
                total_new += len(batch)
                print(f"[search] +{len(batch)} (cum={total_new})")
                batch = []
        if batch:
            append_rows(out_path, batch)
            total_new += len(batch)
            print(f"[search] +{len(batch)} (cum={total_new})")

    print(f"[done] Total new rows: {total_new}  |  Output: {out_path.resolve()}")
    if total_new == 0:
        print("[hint] Try relaxing filters: lower --min-stars, add more --topics/--queries, extend --pushed-since/--created-since, or add --include-archived.")

if __name__ == "__main__":
    main()
