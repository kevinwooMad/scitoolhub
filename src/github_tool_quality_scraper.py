#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# GitHub Tool Quality Scraper
# ===========================
# A runnable Python script to collect repository quality signals for scientific tooling from GitHub.
# It outputs a CSV with per-repo metrics you can later normalize/score for a Tool Quality Scoring System.
#
# Features
# - Reads a list of repositories (owner/name) from a CSV or CLI argument list.
# - Queries GitHub REST API v3 (repositories, issues, commits, contributors) with automatic pagination.
# - Computes quality signals: stars, forks, watchers, open_issues_count, closed_issues (queried),
#   issue_resolution_rate, days_since_last_update, commits_last_N_days, contributors_count.
# - Robustness: retry with exponential backoff; handles rate limits using headers.
# - Auth: uses GITHUB_TOKEN env var or --token flag.
#
# Usage:
#   1. Prepare a CSV file with a header "repo" and rows like:
#        repo
#        biopython/biopython
#        rdkit/rdkit
#        openmm/openmm
#   2. Run:
#        python github_tool_quality_scraper.py --input repos.csv --output tools_data.csv --days 180
#      or pass repos directly:
#        python github_tool_quality_scraper.py --repos biopython/biopython rdkit/rdkit
#
# Tip: export a personal access token (PAT) to increase rate limits:
#        export GITHUB_TOKEN=ghp_xxx

import os
import sys
import csv
import time
import argparse
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple

import requests
import pandas as pd

GITHUB_API = "https://api.github.com"


def _auth_headers(token: Optional[str]) -> Dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "tool-quality-scraper/1.0"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _parse_repo(full_name: str) -> Tuple[str, str]:
    if "/" not in full_name:
        raise ValueError(f"Repository '{full_name}' must be in the form 'owner/name'.")
    owner, name = full_name.strip().split("/", 1)
    return owner, name


def _sleep_until(reset_epoch: Optional[str], fallback_seconds: int = 60) -> None:
    if reset_epoch and reset_epoch.isdigit():
        reset_time = int(reset_epoch)
        now = int(time.time())
        wait_s = max(1, reset_time - now + 5)
    else:
        wait_s = fallback_seconds
    print(f"[rate-limit] Sleeping for {wait_s} seconds...", file=sys.stderr)
    time.sleep(wait_s)


def _request_with_retry(url: str, params: Dict[str, Any], headers: Dict[str, str],
                        session: requests.Session, max_retries: int = 5) -> requests.Response:
    backoff = 2.0
    for attempt in range(1, max_retries + 1):
        resp = session.get(url, params=params, headers=headers, timeout=30)
        # Handle rate limits
        if resp.status_code == 403 and ("rate limit" in resp.text.lower() or "secondary rate" in resp.text.lower()):
            remaining = resp.headers.get("X-RateLimit-Remaining")
            reset = resp.headers.get("X-RateLimit-Reset")
            print(f"[{attempt}] 403 rate-limited. Remaining={remaining}. Backing off.", file=sys.stderr)
            _sleep_until(reset, fallback_seconds=int(backoff))
            backoff = min(backoff * 2, 300)
            continue
        if resp.status_code in (500, 502, 503, 504):
            print(f"[{attempt}] Server error {resp.status_code}. Retrying in {int(backoff)}s", file=sys.stderr)
            time.sleep(backoff)
            backoff = min(backoff * 2, 300)
            continue
        if resp.status_code == 404:
            print(f"[warn] 404 Not Found: {url}", file=sys.stderr)
        return resp
    return resp  # last response


def _paginate(url: str, params: Dict[str, Any], headers: Dict[str, str],
              session: requests.Session, per_page: int = 100, max_pages: int = 100) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    page = 1
    while page <= max_pages:
        q = dict(params)
        q["per_page"] = per_page
        q["page"] = page
        resp = _request_with_retry(url, q, headers, session)
        if resp.status_code != 200:
            print(f"[error] GET {url} -> {resp.status_code} {resp.text[:200]}", file=sys.stderr)
            break
        chunk = resp.json()
        if not isinstance(chunk, list) or len(chunk) == 0:
            break
        results.extend(chunk)
        if len(chunk) < per_page:
            break
        page += 1
    return results


def fetch_repo_core(owner: str, repo: str, headers: Dict[str, str], session: requests.Session) -> Dict[str, Any]:
    url = f"{GITHUB_API}/repos/{owner}/{repo}"
    resp = _request_with_retry(url, {}, headers, session)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to fetch repo {owner}/{repo}: {resp.status_code}")
    j = resp.json()
    return {
        "full_name": j.get("full_name"),
        "description": j.get("description"),
        "created_at": j.get("created_at"),
        "updated_at": j.get("updated_at"),
        "pushed_at": j.get("pushed_at"),
        "stargazers_count": j.get("stargazers_count", 0),
        "forks_count": j.get("forks_count", 0),
        "subscribers_count": j.get("subscribers_count", 0),  # watchers
        "open_issues_count": j.get("open_issues_count", 0),
        "license": (j.get("license") or {}).get("spdx_id"),
        "language": j.get("language"),
        "archived": j.get("archived"),
    }


# 替换原有的 fetch_closed_issues(...) 函数
def fetch_closed_issues_count(owner: str, repo: str, headers: Dict[str, str],
                              session: requests.Session, since_date_iso: Optional[str] = None) -> int:
    """
    使用 Search API 获取关闭 issue 的计数(total_count)。
    可选 since_date_iso（如 '2025-04-01T00:00:00Z'）用于统计“最近窗口”内关闭的数量。
    注意：Search API 有速率限制，建议带 token。
    """
    # Search 语法：repo:OWNER/REPO is:issue state:closed [closed:>=YYYY-MM-DD]
    q = f"repo:{owner}/{repo} is:issue state:closed"
    if since_date_iso:
        q += f" closed:>={since_date_iso.split('T')[0]}"  # 只要日期部分

    url = f"{GITHUB_API}/search/issues"
    # per_page 无关紧要，我们只要 total_count
    resp = _request_with_retry(url, {"q": q, "per_page": 1}, headers, session)
    if resp.status_code != 200:
        print(f"[error] search/issues -> {resp.status_code} {resp.text[:200]}", file=sys.stderr)
        return 0
    j = resp.json()
    # total_count 可能很大（>1000），Search 返回的列表限制不影响 total_count 的准确性
    return int(j.get("total_count", 0))



def fetch_contributors_count(owner: str, repo: str, headers: Dict[str, str], session: requests.Session) -> int:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/contributors"
    items = _paginate(url, {"anon": "true"}, headers, session)
    return len(items)


def fetch_commits_since(owner: str, repo: str, since_iso: str, headers: Dict[str, str], session: requests.Session) -> int:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/commits"
    items = _paginate(url, {"since": since_iso}, headers, session, per_page=100, max_pages=1000)
    return len(items)


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def days_since(iso_time: Optional[str]) -> Optional[int]:
    if not iso_time:
        return None
    try:
        dt = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days
    except Exception:
        return None


def collect_metrics_for_repo(full_name: str, days: int, headers: Dict[str, str], session: requests.Session) -> Dict[str, Any]:
    owner, repo = _parse_repo(full_name)
    core = fetch_repo_core(owner, repo, headers, session)
    contributors = fetch_contributors_count(owner, repo, headers, session)

    # 时间窗口（用于 commits / 近期关闭 issue / 近期新建且未解决 issue）
    since_iso = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    since_date = since_iso.split("T")[0]  # Search API 的日期部分

    # ---- 使用 Search API 统计关闭 issue 的总数与窗口期数量（避免大仓库 422）----
    # 总关闭数
    url_search = f"{GITHUB_API}/search/issues"

    def _search_total(q: str) -> int:
        resp = _request_with_retry(url_search, {"q": q, "per_page": 1}, headers, session)
        if resp.status_code != 200:
            print(f"[error] search/issues -> {resp.status_code} {resp.text[:200]}", file=sys.stderr)
            return 0
        return int(resp.json().get("total_count", 0))

    closed_issues_total = _search_total(f"repo:{owner}/{repo} is:issue state:closed")
    closed_issues_window = _search_total(f"repo:{owner}/{repo} is:issue state:closed closed:>={since_date}")

    # （可选）窗口期内新创建且仍为 open 的 issue 数，用于“近期解决率”分母更合理
    open_created_last_window = _search_total(f"repo:{owner}/{repo} is:issue state:open created:>={since_date}")

    # 其余指标
    commits_N = fetch_commits_since(owner, repo, since_iso, headers, session)
    open_issues = int(core.get("open_issues_count") or 0)

    # 历史总体“解决率”（与原字段语义保持一致）
    total_issues = open_issues + closed_issues_total
    issue_resolution_rate = (closed_issues_total / total_issues) if total_issues > 0 else None

    # 近期窗口期“解决率”（新增，更能反映当下维护健康度）
    den_window = closed_issues_window + open_created_last_window
    issue_resolution_rate_window = (closed_issues_window / den_window) if den_window > 0 else None

    metrics = {
        "repo": core.get("full_name") or f"{owner}/{repo}",
        "description": core.get("description"),
        "language": core.get("language"),
        "license": core.get("license"),
        "stars": int(core.get("stargazers_count") or 0),
        "forks": int(core.get("forks_count") or 0),
        "watchers": int(core.get("subscribers_count") or 0),

        "open_issues": open_issues,
        # 向下兼容：保留原字段名，但值改为 Search API 统计的总关闭数
        "closed_issues": int(closed_issues_total),
        "issue_resolution_rate": issue_resolution_rate,

        # 新增：窗口期指标（便于做“近期健康度”分析）
        "closed_issues_last_window": int(closed_issues_window),
        "open_created_last_window": int(open_created_last_window),
        "issue_resolution_rate_last_window": issue_resolution_rate_window,

        "created_at": core.get("created_at"),
        "updated_at": core.get("updated_at"),
        "pushed_at": core.get("pushed_at"),
        "days_since_last_update": days_since(core.get("pushed_at")),
        f"commits_last_{days}_days": int(commits_N),
        "contributors_count": int(contributors),
        "archived": bool(core.get("archived")),
        "scraped_at": iso_now(),
    }
    return metrics



def read_repos_from_csv(path: str) -> List[str]:
    repos: List[str] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = (row.get("repo") or "").strip()
            if name:
                repos.append(name)
    if not repos:
        raise ValueError("No repos found in CSV. Ensure a header 'repo' and rows like 'owner/name'.")
    return repos


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="GitHub Tool Quality Scraper")
    parser.add_argument("--input", "-i", type=str, help="CSV file with a header 'repo' listing owner/name entries")
    parser.add_argument("--repos", nargs="*", help="Repositories as 'owner/name' entries (alternative to --input)")
    parser.add_argument("--output", "-o", type=str, default="tools_data.csv", help="Output CSV path")
    parser.add_argument("--days", type=int, default=180, help="Lookback window for commit counts")
    parser.add_argument("--token", type=str, default=os.environ.get("GITHUB_TOKEN"), help="GitHub token (env GITHUB_TOKEN if omitted)")
    parser.add_argument("--max", type=int, default=None, help="Optional cap on number of repos to process")
    args = parser.parse_args(argv)

    if not args.input and not args.repos:
        parser.error("Provide --input CSV or --repos owner/name ...")

    repos: List[str] = []
    if args.input:
        repos = read_repos_from_csv(args.input)
    if args.repos:
        repos.extend(args.repos)
    # De-duplicate while preserving order
    seen = set()
    repos = [r for r in repos if not (r in seen or seen.add(r))]

    if args.max is not None:
        repos = repos[: args.max]

    token = args.token
    headers = _auth_headers(token)
    session = requests.Session()

    print(f"[info] Processing {len(repos)} repositories; days={args.days}", file=sys.stderr)
    rows: List[Dict[str, Any]] = []
    for idx, full_name in enumerate(repos, 1):
        try:
            print(f"[{idx}/{len(repos)}] {full_name}", file=sys.stderr)
            row = collect_metrics_for_repo(full_name, args.days, headers, session)
            rows.append(row)
        except Exception as e:
            print(f"[error] {full_name}: {e}", file=sys.stderr)

    if not rows:
        print("[warn] No rows collected; nothing to write.", file=sys.stderr)
        return 1

    df = pd.DataFrame(rows)
    sort_cols = ["stars", f"commits_last_{args.days}_days", "issue_resolution_rate", "contributors_count"]
    existing = [c for c in sort_cols if c in df.columns]
    df = df.sort_values(existing, ascending=[False] * len(existing), na_position="last")
    df.to_csv(args.output, index=False, encoding="utf-8")
    print(f"[done] Wrote {args.output} with {len(df)} rows.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
