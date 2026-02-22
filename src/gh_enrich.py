# gh_enrich.py
import os, sys, time, csv, math, json
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta

API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
HEADERS = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}

def get(url, params=None):
    for _ in range(3):
        r = requests.get(url, headers=HEADERS, params=params, timeout=20)
        if r.status_code == 403 and "rate limit" in r.text.lower():
            time.sleep(3)
            continue
        if r.status_code in (200, 404):
            return r
        time.sleep(1)
    return r

def repo_stats(full):
    owner, name = full.split("/", 1)
    base = f"{API}/repos/{owner}/{name}"
    r = get(base)
    if r.status_code != 200:
        return {"repo": full, "ok": False, "error": f"{r.status_code}"}

    data = r.json()
    pushed_at = data.get("pushed_at")
    days_since_update = None
    if pushed_at:
        dt = datetime.fromisoformat(pushed_at.replace("Z","+00:00"))
        days_since_update = (datetime.now(timezone.utc) - dt).days

    # commits 近90天
    commits_90 = 0
    since = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    rr = get(f"{base}/commits", params={"since": since})
    if rr.status_code == 200:
        commits_90 = len(rr.json())

    # contributors
    contrib = 0
    rc = get(f"{base}/contributors", params={"per_page": 100})
    if rc.status_code == 200:
        contrib = len(rc.json())

    # issue 关闭率（粗略）
    ri_open = get(f"{API}/search/issues", params={"q": f"repo:{owner}/{name} type:issue state:open"})
    ri_closed = get(f"{API}/search/issues", params={"q": f"repo:{owner}/{name} type:issue state:closed"})
    open_cnt = ri_open.json().get("total_count", 0) if ri_open.status_code==200 else 0
    closed_cnt = ri_closed.json().get("total_count", 0) if ri_closed.status_code==200 else 0
    issue_resolution_rate = closed_cnt / (open_cnt + closed_cnt) if (open_cnt+closed_cnt)>0 else 0.0

    return {
        "repo": full,
        "description": data.get("description") or "",
        "language": data.get("language") or "",
        "license": (data.get("license") or {}).get("spdx_id") or "",
        "stars": data.get("stargazers_count", 0),
        "forks": data.get("forks_count", 0),
        "watchers": data.get("subscribers_count", 0),
        "open_issues": data.get("open_issues_count", 0),
        "commits_window": commits_90,
        "contributors": contrib,
        "issue_resolution_rate": round(issue_resolution_rate, 4),
        "days_since_last_update": days_since_update if days_since_update is not None else 9999,
    }

def main():
    if len(sys.argv) < 3:
        print("Usage: python gh_enrich.py repos.csv enriched_tools.csv")
        sys.exit(1)
    inp, outp = sys.argv[1], sys.argv[2]
    df = pd.read_csv(inp)
    repos = [str(x) for x in df["repo"].dropna().unique()]
    rows = []
    for i, r in enumerate(repos, 1):
        s = repo_stats(r)
        rows.append(s)
        print(f"[{i}/{len(repos)}] {r} -> {'ok' if s.get('stars') is not None else 'fail'}")
        time.sleep(0.5)  # 温和速率
    pd.DataFrame(rows).to_csv(outp, index=False)
    print(f"[done] wrote: {outp}")

if __name__ == "__main__":
    if not TOKEN:
        print("ERROR: missing GITHUB_TOKEN env; set it first.")
        sys.exit(2)
    main()
