#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
score_tools.py
读取 tools_data.csv，对科学工具仓库做质量评分与排序。
输出:
  - ranked_tools.csv: 含综合分的排序结果
  - rank_report.md:   关键统计的简短报告
  - top_k.txt/json:   (可选) Top-K 清单用于后续集成

使用示例:
  python score_tools.py --input tools_data.csv --topk 30 --outdir out
  python score_tools.py --input tools_data.csv --weights stars=0.25,commits=0.25,contributors=0.25,issues=0.15,staleness=0.10
"""
import os
import json
import math
import argparse
import datetime as dt
import numpy as np
import pandas as pd

# 尝试使用 sklearn 的 MinMaxScaler, 若无则用简易替代
try:
    from sklearn.preprocessing import MinMaxScaler
except Exception:
    MinMaxScaler = None

def _log1p_safe(x):
    try:
        return np.log1p(np.maximum(x, 0))
    except Exception:
        return np.zeros_like(x, dtype=float)

def _minmax_scale(arr):
    arr = np.asarray(arr, dtype=float)
    lo, hi = np.nanmin(arr), np.nanmax(arr)
    if not np.isfinite(lo) or not np.isfinite(hi) or hi == lo:
        return np.zeros_like(arr, dtype=float)
    return (arr - lo) / (hi - lo)

def _normalize_series(s, method="log1p_minmax"):
    s = pd.to_numeric(s, errors="coerce").fillna(0)
    if method == "log1p_minmax":
        v = _log1p_safe(s.values)
        return _minmax_scale(v)
    elif method == "minmax":
        return _minmax_scale(s.values)
    else:
        return _minmax_scale(s.values)

def parse_weights(arg):
    """
    将 "stars=0.25,commits=0.25,contributors=0.25,issues=0.15,staleness=0.10" 解析为 dict
    """
    default = {
        "stars": 0.25,
        "commits": 0.25,
        "contributors": 0.25,
        "issues": 0.15,      # issue 质量（解决率/速度）
        "staleness": 0.10    # 最近活跃度（越新越好）
    }
    if not arg:
        return default
    out = {}
    for kv in arg.split(","):
        if not kv.strip():
            continue
        if "=" not in kv:
            continue
        k, v = kv.split("=", 1)
        try:
            out[k.strip()] = float(v)
        except Exception:
            pass
    # 合并默认值
    for k, v in default.items():
        out.setdefault(k, v)
    # 归一化权重到和为1
    tot = sum(out.values()) or 1.0
    for k in out:
        out[k] = out[k] / tot
    return out

def infer_window_days(df):
    # 从列名推断 commits_last_{days}_days；否则返回 None
    for c in df.columns:
        if c.startswith("commits_last_") and c.endswith("_days"):
            try:
                return int(c[len("commits_last_"):-len("_days")])
            except Exception:
                pass
    return None

def compute_features(df):
    df = df.copy()

    # 关键字段名兼容
    # repo 名
    repo_col = "repo" if "repo" in df.columns else ("full_name" if "full_name" in df.columns else None)
    if repo_col is None:
        raise ValueError("CSV缺少 'repo' 或 'full_name' 列。")

    # stars/forks/watchers
    for c in ["stargazers_count", "stars"]:
        if c in df.columns:
            df["stars"] = pd.to_numeric(df[c], errors="coerce")
            break
    if "stars" not in df.columns:
        df["stars"] = 0

    if "forks" not in df.columns:
        for c in ["forks_count"]:
            if c in df.columns:
                df["forks"] = pd.to_numeric(df[c], errors="coerce")
                break
    if "forks" not in df.columns:
        df["forks"] = 0

    if "watchers" not in df.columns:
        for c in ["subscribers_count", "watchers_count"]:
            if c in df.columns:
                df["watchers"] = pd.to_numeric(df[c], errors="coerce")
                break
    if "watchers" not in df.columns:
        df["watchers"] = 0

    # issues：open/closed/解决率
    df["open_issues"] = pd.to_numeric(df.get("open_issues", 0), errors="coerce").fillna(0)
    df["closed_issues"] = pd.to_numeric(df.get("closed_issues", 0), errors="coerce").fillna(0)
    if "issue_resolution_rate" in df.columns:
        df["issue_resolution_rate"] = pd.to_numeric(df["issue_resolution_rate"], errors="coerce")
    else:
        total_issues = df["open_issues"] + df["closed_issues"]
        df["issue_resolution_rate"] = np.where(total_issues > 0, df["closed_issues"] / total_issues, np.nan)

    # 活跃度/陈旧度：days_since_last_update 越小越好
    if "days_since_last_update" not in df.columns:
        # 尝试从 pushed_at 解析
        if "pushed_at" in df.columns:
            try:
                pushed = pd.to_datetime(df["pushed_at"], errors="coerce", utc=True)
                now = pd.Timestamp.utcnow()
                df["days_since_last_update"] = (now - pushed).dt.days
            except Exception:
                df["days_since_last_update"] = np.nan
        else:
            df["days_since_last_update"] = np.nan

    # commits：自动识别窗口列
    win_days = infer_window_days(df)
    commits_col = None
    if win_days is not None:
        commits_col = f"commits_last_{win_days}_days"
    for c in [commits_col, "commits_last_180_days", "commits_last_90_days"]:
        if c and c in df.columns:
            df["commits_window"] = pd.to_numeric(df[c], errors="coerce").fillna(0)
            break
    if "commits_window" not in df.columns:
        # 回退：用 total commits 不一定有；没有就置0
        df["commits_window"] = 0

    # 贡献者数量
    if "contributors_count" in df.columns:
        df["contributors"] = pd.to_numeric(df["contributors_count"], errors="coerce").fillna(0)
    else:
        df["contributors"] = 0

    # 衍生指标：简单合成一个“受欢迎度”
    df["popularity_raw"] = (
        pd.to_numeric(df["stars"], errors="coerce").fillna(0) * 0.7 +
        pd.to_numeric(df["forks"], errors="coerce").fillna(0) * 0.2 +
        pd.to_numeric(df["watchers"], errors="coerce").fillna(0) * 0.1
    )

    return df, repo_col

def score_dataframe(df, weights):
    df = df.copy()

    # 归一化各项
    df["stars_n"]        = _normalize_series(df["stars"], method="log1p_minmax")
    df["commits_n"]      = _normalize_series(df["commits_window"], method="log1p_minmax")
    df["contributors_n"] = _normalize_series(df["contributors"], method="log1p_minmax")

    # issues: 以“解决率”为主，缺失置中值
    issues = pd.to_numeric(df["issue_resolution_rate"], errors="coerce")
    med = issues.median(skipna=True)
    issues = issues.fillna(med if np.isfinite(med) else 0.5)
    df["issues_n"] = _minmax_scale(issues.values)  # 高=好

    # staleness: days_since_last_update 越小越好 => 先 minmax，再取(1 - 值)
    stale = pd.to_numeric(df["days_since_last_update"], errors="coerce").fillna(stale := df["days_since_last_update"].median() if "days_since_last_update" in df.columns else 180)
    stale_n = _minmax_scale(stale.values)  # 值越大越“旧”
    df["staleness_n"] = 1.0 - stale_n      # 高=新

    # 综合分
    w = weights
    df["composite_score"] = (
        w["stars"]        * df["stars_n"] +
        w["commits"]      * df["commits_n"] +
        w["contributors"] * df["contributors_n"] +
        w["issues"]       * df["issues_n"] +
        w["staleness"]    * df["staleness_n"]
    )

    # 排序
    df_sorted = df.sort_values("composite_score", ascending=False).reset_index(drop=True)
    return df_sorted

def write_report(df_sorted, outdir, repo_col, topk):
    os.makedirs(outdir, exist_ok=True)
    path_md = os.path.join(outdir, "rank_report.md")
    lines = []
    lines.append(f"# Tool Quality Ranking Report\n")
    lines.append(f"- Generated at: {dt.datetime.utcnow().isoformat()}Z")
    lines.append(f"- Items: {len(df_sorted)}")
    lines.append(f"- Top-{topk} preview:\n")
    for i, row in df_sorted.head(topk).iterrows():
        nm = row[repo_col]
        sc = row["composite_score"]
        stars = int(row.get("stars", 0) or 0)
        commits = int(row.get("commits_window", 0) or 0)
        contrib = int(row.get("contributors", 0) or 0)
        irr = row.get("issue_resolution_rate")
        irr_txt = "NA" if pd.isna(irr) else f"{irr:.2f}"
        stale = row.get("days_since_last_update")
        stale_txt = "NA" if pd.isna(stale) else f"{int(stale)} days"
        lines.append(f"{i+1}. **{nm}** | score={sc:.3f} | ⭐{stars} | commits(win)={commits} | contrib={contrib} | issue_res={irr_txt} | staleness={stale_txt}")
    with open(path_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path_md

def main():
    ap = argparse.ArgumentParser(description="Score scientific tool repositories and rank them.")
    ap.add_argument("--input", required=True, help="Path to tools_data.csv")
    ap.add_argument("--outdir", default="scored_out", help="Output directory")
    ap.add_argument("--topk", type=int, default=30, help="Export Top-K list")
    ap.add_argument("--weights", default="", help="Weights like stars=0.25,commits=0.25,contributors=0.25,issues=0.15,staleness=0.10")
    args = ap.parse_args()

    assert os.path.exists(args.input), f"CSV not found: {args.input}"
    os.makedirs(args.outdir, exist_ok=True)

    weights = parse_weights(args.weights)
    print("[info] weights:", weights)

    df = pd.read_csv(args.input)
    print(f"[info] loaded rows: {len(df)}; cols: {list(df.columns)[:8]}...")

    df1, repo_col = compute_features(df)
    df2 = score_dataframe(df1, weights)

    # 输出 CSV
    out_csv = os.path.join(args.outdir, "ranked_tools.csv")
    df2.to_csv(out_csv, index=False)
    print(f"[done] wrote: {out_csv}")

    # Top-K 文本/JSON清单
    topk = max(1, min(args.topk, len(df2)))
    top_df = df2.head(topk).copy()
    top_txt = os.path.join(args.outdir, "top_k.txt")
    with open(top_txt, "w", encoding="utf-8") as f:
        for v in top_df[repo_col].tolist():
            f.write(str(v).strip() + "\n")
    print(f"[done] wrote: {top_txt}")

    top_json = os.path.join(args.outdir, "top_k.json")
    with open(top_json, "w", encoding="utf-8") as f:
        json.dump(top_df[[repo_col, "composite_score"]].to_dict(orient="records"), f, ensure_ascii=False, indent=2)
    print(f"[done] wrote: {top_json}")

    # 简短报告
    rep = write_report(df2, args.outdir, repo_col, topk)
    print(f"[done] wrote: {rep}")

    # 控制台预览前5
    print("\nTop-5 preview:")
    cols_show = [repo_col, "composite_score", "stars", "commits_window", "contributors", "issue_resolution_rate", "days_since_last_update"]
    print(df2.loc[:, [c for c in cols_show if c in df2.columns]].head(5).to_string(index=False))

if __name__ == "__main__":
    main()
