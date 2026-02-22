# gh_enrich.py
# -*- coding: utf-8 -*-
import os
import re
import csv
import time
import json
import argparse
import requests
import pandas as pd
from pathlib import Path

GITHUB_API = "https://api.github.com"
HEADERS = {"Accept": "application/vnd.github+json"}

def norm_full_name(x: str) -> str:
    """将各种形式归一到 owner/repo。支持 URL、空白、大小写等。"""
    if not isinstance(x, str):
        return ""
    x = x.strip()
    if not x:
        return ""
    m = re.search(r"github\.com/([^/\s]+/[^/\s#?]+)", x, re.IGNORECASE)
    if m:
        return m.group(1)
    # 逗号分隔 owner,repo
    m2 = re.match(r"^\s*([A-Za-z0-9_.-]+)\s*[,/]\s*([A-Za-z0-9_.-]+)\s*$", x)
    if m2:
        return f"{m2.group(1)}/{m2.group(2)}"
    return x

def looks_like_full_name(x: str) -> bool:
    return bool(re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", x or ""))

def pick_repo_column(df: pd.DataFrame, prefer: str | None) -> str | None:
    """优先用 --col，其次尝试常见列名。最后尝试单列/第一列。"""
    if prefer and prefer in df.columns:
        return prefer
    candidates = ["repo", "full_name", "name", "html_url", "url"]
    for c in candidates:
        if c in df.columns:
            return c
    if df.shape[1] == 1:
        return df.columns[0]
    return df.columns[0]  # 退而求其次

def read_repos_csv(path: str, col: str | None, sep: str | None, max_n: int | None) -> list[str]:
    """尽可能鲁棒地读取 repo 列；自动抽取 owner/repo。"""
    df = pd.read_csv(
        path,
        engine="python",
        sep=sep,             # sep=None 时让 pandas 尝试自动识别
        on_bad_lines="skip", # 遇到坏行跳过
        dtype=str,
        keep_default_na=False
    )
    colname = pick_repo_column(df, col)
    s = df[colname].astype(str).map(norm_full_name).str.strip()
    # 若是 URL 或其它形式，转为 owner/repo
    s = s.apply(norm_full_name)
    # 过滤不是 owner/repo 的
    s = s[s.map(looks_like_full_name)]
    repos = s.drop_duplicates().tolist()
    if max_n:
        repos = repos[:max_n]
    return repos

def github_get(path: str, token: str | None, params: dict | None = None) -> dict | None:
    headers = dict(HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for _ in range(2):
        r = requests.get(f"{GITHUB_API}{path}", headers=headers, params=params, timeout=20)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (403, 429):
            time.sleep(5)
            continue
        return None
    return None

def enrich_one(full_name: str, token: str | None) -> dict | None:
    """抓取仓库基本信息。可以按需扩展更多字段。"""
    repo = github_get(f"/repos/{full_name}", token)
    if not repo:
        return None
    topics = repo.get("topics", [])
    out = {
        "repo": full_name,
        "stars": repo.get("stargazers_count", 0),
        "forks": repo.get("forks_count", 0),
        "watchers": repo.get("subscribers_count", 0),
        "open_issues": repo.get("open_issues_count", 0),
        "language": repo.get("language"),
        "license": (repo.get("license") or {}).get("spdx_id"),
        "archived": repo.get("archived", False),
        "disabled": repo.get("disabled", False),
        "created_at": repo.get("created_at"),
        "updated_at": repo.get("updated_at"),
        "pushed_at": repo.get("pushed_at"),
        "size_kb": repo.get("size", 0),
        "has_wiki": repo.get("has_wiki", False),
        "has_pages": repo.get("has_pages", False),
        "default_branch": repo.get("default_branch"),
        "topics": ";".join(topics) if isinstance(topics, list) else "",
        "homepage": repo.get("homepage") or "",
        "description": (repo.get("description") or "").replace("\n", " ").strip(),
        "html_url": repo.get("html_url") or "",
    }
    return out

def load_done(output_csv: str) -> set[str]:
    """断点续跑：已抓过的 repo 集合。"""
    p = Path(output_csv)
    if not p.exists():
        return set()
    try:
        df = pd.read_csv(p, dtype=str, keep_default_na=False)
        if "repo" in df.columns:
            return set(df["repo"].astype(str).tolist())
    except Exception:
        pass
    return set()

def append_rows(output_csv: str, rows: list[dict]):
    p = Path(output_csv)
    if not p.exists():
        pd.DataFrame(rows).to_csv(output_csv, index=False, encoding="utf-8", quoting=csv.QUOTE_MINIMAL)
    else:
        pd.DataFrame(rows).to_csv(output_csv, mode="a", index=False, header=False, encoding="utf-8", quoting=csv.QUOTE_MINIMAL)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_csv", help="包含 repo 列（owner/repo 或 GitHub URL）的 CSV")
    ap.add_argument("output_csv", help="输出的 enriched CSV")
    ap.add_argument("--col", default=None, help="显式指定包含仓库的列名（如 repo / full_name / html_url）")
    ap.add_argument("--sep", default=None, help="CSV 分隔符，默认自动识别")
    ap.add_argument("--max", type=int, default=None, help="最多处理多少条（调试用）")
    ap.add_argument("--resume", action="store_true", help="开启断点续跑（跳过 output_csv 里已有的 repo）")
    ap.add_argument("--sleep", type=float, default=0.6, help="每次请求后的 sleep 秒数，默认 0.6")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("[warn] 未设置 GITHUB_TOKEN，可能很快触发限流。建议先：set GITHUB_TOKEN=你的token")

    repos = read_repos_csv(args.input_csv, args.col, args.sep, args.max)
    print(f"[info] 候选仓库数量：{len(repos)}")

    done = load_done(args.output_csv) if args.resume else set()
    print(f"[info] 已存在于输出（将跳过）：{len(done)}")

    buffered = []
    cnt_ok, cnt_fail = 0, 0

    for i, full_name in enumerate(repos, 1):
        if args.resume and full_name in done:
            continue
        info = enrich_one(full_name, token)
        if info:
            buffered.append(info)
            cnt_ok += 1
        else:
            cnt_fail += 1

        if len(buffered) >= 50:
            append_rows(args.output_csv, buffered)
            print(f"[flush] 写入 50 条，进度 {i}/{len(repos)}")
            buffered.clear()

        time.sleep(args.sleep)

    if buffered:
        append_rows(args.output_csv, buffered)

    print(f"[done] 成功 {cnt_ok}，失败 {cnt_fail}，输出：{args.output_csv}")

if __name__ == "__main__":
    main()
