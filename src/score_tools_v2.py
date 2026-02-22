#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
score_tools_v2.py
科学工具质量评分系统（语义增强版）

基于 v1 的改进：
- 分析 README 文档质量
- 自动识别科学领域 (Bio/Chem/ML/Material)
- 检查项目结构中测试与CI/CD存在性
- 多层加权综合得分
"""

import os
import re
import requests
import json
import argparse
import numpy as np
import pandas as pd
from collections import Counter

# ---------- 工具函数 ----------

def safe_read(file_path):
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def normalize_series(s):
    s = pd.to_numeric(s, errors="coerce").fillna(0)
    lo, hi = s.min(), s.max()
    return (s - lo) / (hi - lo) if hi > lo else np.zeros(len(s))

def detect_domain(text):
    text = str(text).lower()
    if any(k in text for k in ["protein", "genome", "rna", "dna", "sequence", "bio"]):
        return "bio"
    elif any(k in text for k in ["molecule", "chem", "drug", "compound", "binding"]):
        return "chem"
    elif any(k in text for k in ["material", "crystal", "alloy", "polymer"]):
        return "material"
    elif any(k in text for k in ["deep", "model", "ai", "ml", "graph", "transformer"]):
        return "ml"
    return "other"

def readme_score(readme_text):
    text = readme_text.lower()
    length_score = min(len(text) / 5000, 1.0)
    section_score = len(re.findall(r"^#+", readme_text, re.M)) / 10
    install_score = 1.0 if re.search(r"pip install|conda install|requirements\.txt", text) else 0.3
    citation_score = 1.0 if "citation" in text or "doi" in text else 0.2
    total = 0.4 * length_score + 0.3 * section_score + 0.2 * install_score + 0.1 * citation_score
    return min(total, 1.0)

def ci_test_score(repo_path):
    if not os.path.isdir(repo_path):
        return 0.0
    files = []
    for root, _, fns in os.walk(repo_path):
        files += [os.path.join(root, f) for f in fns]
    ci_found = any((".github/workflows" in f or "ci.yml" in f or "actions" in f) for f in files)
    test_found = any("test" in os.path.basename(f).lower() for f in files)
    return 0.6 * test_found + 0.4 * ci_found

# --- GitHub metadata puller ---------------------------------------------------
def fetch_github_metrics(repo_full, token=None):
    """使用 GitHub REST API 拉取基础指标。"""
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://api.github.com/repos/{repo_full}"
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return {}
        data = r.json()
        return {
            "stars": data.get("stargazers_count", 0),
            "forks": data.get("forks_count", 0),
            "open_issues": data.get("open_issues_count", 0),
            "watchers": data.get("subscribers_count", 0),
            "updated_at": data.get("pushed_at", None),
        }
    except Exception:
        return {}


def compute_scores(df, github_token=None, readme_timeout=6):
    """
    进化版打分：
    - 自动识别 commits 窗口列(如 commits_last_180_days)，构造 commits_window
    - 缺失 issue_resolution_rate 时用 closed/(open+closed) 推导
    - 缺失 days_since_last_update 时由 pushed_at 推导
    - 在线抓取 README（raw.githubusercontent.com），计算 readme_score 与 domain
    - 保持 ci_test_score 为 0（无本地仓库时）
    """
    import re
    import datetime as dt
    import pandas as pd
    import numpy as np
    from urllib.request import urlopen, Request
    from urllib.error import URLError, HTTPError

    def _to_num(s, default=0):
        import pandas as pd
        if isinstance(s, (int, float)):  # 单值直接返回
            return s
        if s is None:
            return default
        try:
            return pd.to_numeric(s, errors="coerce").fillna(default)
        except Exception:
            return default

    def _minmax(x):
        x = pd.to_numeric(x, errors="coerce")
        lo, hi = x.min(skipna=True), x.max(skipna=True)
        if (not np.isfinite(lo)) or (not np.isfinite(hi)) or hi == lo:
            return np.zeros(len(x), dtype=float)
        return (x - lo) / (hi - lo)

    def _normalize_series(s):
        s = _to_num(s, 0)
        return _minmax(s)

    def _detect_commit_window_col(df_):
        # 识别 commits_last_{days}_days 的列（如同时存在多个，选天数最大的）
        cand = []
        for c in df_.columns:
            if c.startswith("commits_last_") and c.endswith("_days"):
                try:
                    d = int(c[len("commits_last_"):-len("_days")])
                    cand.append((d, c))
                except Exception:
                    pass
        if cand:
            cand.sort(reverse=True)
            return cand[0][1]
        return None

    def _infer_days_since_last_update(col_pushed_at):
        try:
            pushed = pd.to_datetime(col_pushed_at, errors="coerce", utc=True)
            now = pd.Timestamp.utcnow()
            return (now - pushed).dt.days
        except Exception:
            return pd.Series([np.nan] * len(col_pushed_at))

    def _fetch_readme_online(repo_fullname):
        """
        直接从 GitHub raw 拉 README（main -> master）。若提供 github_token，会加到 header。
        """
        headers = {"User-Agent": "SciToolHub-Readme-Fetcher"}
        if github_token:
            headers["Authorization"] = f"token {github_token}"
        for branch in ("main", "master"):
            url = f"https://raw.githubusercontent.com/{repo_fullname}/{branch}/README.md"
            try:
                req = Request(url, headers=headers)
                with urlopen(req, timeout=readme_timeout) as resp:
                    text = resp.read().decode("utf-8", errors="ignore")
                    if len(text) > 50:
                        return text
            except (HTTPError, URLError, TimeoutError, Exception):
                continue
        return ""

    def _readme_score(text):
        t = text.lower()
        length_score  = min(len(t) / 5000, 1.0)
        section_score = len(re.findall(r"^#+", text, flags=re.M)) / 10
        install_score = 1.0 if re.search(r"(pip|conda)\s+install|requirements\.txt", t) else 0.3
        citation_score= 1.0 if ("citation" in t or "doi" in t) else 0.2
        total = 0.4*length_score + 0.3*section_score + 0.2*install_score + 0.1*citation_score
        return float(min(max(total, 0.0), 1.0))

    def _detect_domain(text):
        tt = str(text).lower()
        if any(k in tt for k in ["protein", "genome", "rna", "dna", "sequence", "bio"]):
            return "bio"
        if any(k in tt for k in ["molecule", "chem", "drug", "compound", "binding"]):
            return "chem"
        if any(k in tt for k in ["material", "crystal", "alloy", "polymer"]):
            return "material"
        if any(k in tt for k in ["deep", "model", "ai", "ml", "graph", "transformer"]):
            return "ml"
        return "other"

    df = df.copy()

    # --- 统一关键字段 ---
    if "stars" not in df.columns:
        for c in ["stargazers_count"]:
            if c in df.columns:
                df["stars"] = _to_num(df[c], 0); break
    if "stars" not in df.columns:
        df["stars"] = 0

    if "contributors" not in df.columns and "contributors_count" in df.columns:
        df["contributors"] = _to_num(df["contributors_count"], 0)
    if "contributors" not in df.columns:
        df["contributors"] = 0

    if "open_issues" not in df.columns:
        df["open_issues"] = _to_num(df.get("open_issues_count", 0), 0)
    else:
        df["open_issues"] = _to_num(df["open_issues"], 0)

    if "closed_issues" not in df.columns:
        df["closed_issues"] = _to_num(df.get("closed_issues", 0), 0)
    else:
        df["closed_issues"] = _to_num(df["closed_issues"], 0)

    if "issue_resolution_rate" not in df.columns:
        total_iss = df["open_issues"] + df["closed_issues"]
        df["issue_resolution_rate"] = np.where(total_iss > 0, df["closed_issues"]/total_iss, np.nan)

    if "days_since_last_update" not in df.columns:
        if "pushed_at" in df.columns:
            df["days_since_last_update"] = _infer_days_since_last_update(df["pushed_at"])
        else:
            df["days_since_last_update"] = np.nan

    # commits_window 自动识别
    if "commits_window" not in df.columns:
        ccol = _detect_commit_window_col(df)
        if ccol and ccol in df.columns:
            df["commits_window"] = _to_num(df[ccol], 0)
        else:
            df["commits_window"] = 0

    # --- 基础归一化特征 ---
    df["stars_n"]        = _normalize_series(df["stars"])
    df["commits_n"]      = _normalize_series(df["commits_window"])
    df["contributors_n"] = _normalize_series(df["contributors"])

    irr = pd.to_numeric(df["issue_resolution_rate"], errors="coerce")
    med = irr.median(skipna=True)
    irr = irr.fillna(med if np.isfinite(med) else 0.5)
    df["issues_n"] = _minmax(irr)

    stale = pd.to_numeric(df["days_since_last_update"], errors="coerce")
    stale = stale.fillna(stale.median(skipna=True) if np.isfinite(stale.median(skipna=True)) else 180)
    df["staleness_n"] = 1.0 - _minmax(stale)

    # --- 在线抓 README + 语义领域 ---
    df["readme_score"] = 0.0
    df["ci_test_score"] = 0.0   # 无本地仓库时保持 0
    df["domain"] = "other"

    repo_col = "repo" if "repo" in df.columns else ("full_name" if "full_name" in df.columns else None)
    if repo_col is None:
        raise ValueError("CSV缺少 'repo' 或 'full_name' 列。")

    for i, row in df.iterrows():
        repo = str(row.get(repo_col, "")).strip()
        if not repo:
            continue
        readme_text = _fetch_readme_online(repo)
        df.loc[i, "readme_score"] = _readme_score(readme_text)
        desc = f"{str(row.get('description',''))} {readme_text[:500]}"
        df.loc[i, "domain"] = _detect_domain(desc)

    # 领域权重
    domain_weights = {"bio": 1.0, "chem": 0.95, "material": 0.9, "ml": 1.05, "other": 1.0}
    df["domain_weight"] = df["domain"].map(domain_weights).fillna(1.0)

    # 综合得分（v2）
    df["composite_v2"] = (
        0.20 * df["stars_n"] +
        0.15 * df["commits_n"] +
        0.15 * df["contributors_n"] +
        0.10 * df["issues_n"] +
        0.10 * df["staleness_n"] +
        0.15 * df["readme_score"] +
        0.15 * df["ci_test_score"]
    ) * df["domain_weight"]

    return df.sort_values("composite_v2", ascending=False).reset_index(drop=True)

# ---------- 主函数 ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="tools_data.csv 路径")
    ap.add_argument("--outdir", default="scored_out_v2", help="输出目录")
    args = ap.parse_args()

    df = pd.read_csv(args.input)
    scored = compute_scores(df, github_token=os.environ.get("GITHUB_TOKEN"))

    os.makedirs(args.outdir, exist_ok=True)
    ranked_csv = os.path.join(args.outdir, "ranked_tools_v2.csv")
    scored.to_csv(ranked_csv, index=False)

    topk = scored.head(20)  # 输出前 20 个
    topk_json = os.path.join(args.outdir, "top20_v2.json")
    topk[["repo", "composite_v2", "domain", "readme_score", "ci_test_score"]].to_json(
        topk_json, orient="records", indent=2
    )

    clusters = Counter(topk["domain"])
    with open(os.path.join(args.outdir, "semantic_clusters.json"), "w", encoding="utf-8") as f:
        json.dump(clusters, f, indent=2)

    print(f"[done] wrote: {ranked_csv}")
    print(f"[done] wrote: {topk_json}")
    print(f"[done] wrote semantic_clusters.json")
    print("\nTop-5 preview:")
    print(topk[["repo", "composite_v2", "domain", "readme_score", "ci_test_score"]].head())

if __name__ == "__main__":
    main()
