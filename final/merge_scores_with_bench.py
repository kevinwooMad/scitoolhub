# merge_scores_with_bench.py
# -*- coding: utf-8 -*-
import json, argparse
import pandas as pd
from pathlib import Path

def load_bench(path):
    items = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = []
    for it in items:
        name = it.get("name","").strip()
        passed = bool(it.get("passed")) if it.get("skipped") is False else None
        skipped = bool(it.get("skipped"))
        lat = it.get("elapsed_s", None)
        rows.append({"name": name, "passed": passed, "skipped": skipped, "elapsed_s": lat})
    return pd.DataFrame(rows)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ranked_csv", required=True, help="scored_out_v2/ranked_tools_v2.csv")
    ap.add_argument("--bench_json", required=True, help="benchmark_results.json")
    ap.add_argument("--out", default="final_scored.csv")
    ap.add_argument("--alpha_repo", type=float, default=0.7, help="基础数据分权重")
    ap.add_argument("--beta_bench", type=float, default=0.3, help="运行信号权重")
    args = ap.parse_args()

    df = pd.read_csv(args.ranked_csv)
    b = load_bench(args.bench_json)

    # 统一名字：根据常见映射补齐（可按需扩展）
    alias = {
        "biopython":"Bio","mdanalysis":"MDAnalysis","scikit-bio":"skbio"
    }
    b["key"] = b["name"].map(lambda x: alias.get(x, x).lower())

    # 基线：repo名的最后一段作为 key
    def repo_to_key(repo):
        if isinstance(repo, str) and "/" in repo:
            return repo.split("/")[-1].lower()
        return str(repo).lower()

    df["key"] = df["repo"].apply(repo_to_key)

    # 只用非 skip 的条目作为 bench 信号
    bx = b[b["skipped"]==False].copy()

    # 运行通过：passed -> 1，否则 0（失败才计 0；缺失/跳过不影响）
    bx["pass_score"] = bx["passed"].map(lambda v: 1.0 if v else 0.0)

    # 时延：越快越好，做一个相对分（反向归一）
    lat = bx["elapsed_s"].fillna(bx["elapsed_s"].max())
    if len(lat) and lat.max() > 0:
        lat_score = 1.0 - (lat - lat.min())/(lat.max()-lat.min() if lat.max()>lat.min() else 1.0)
    else:
        lat_score = 0.0
    bx["latency_score"] = lat_score

    # bench 综合：70% 通过，30% 时延
    bx["bench_score"] = 0.7*bx["pass_score"] + 0.3*bx["latency_score"]

    # 合并到主数据
    out = df.merge(bx[["key","bench_score","pass_score","latency_score"]], on="key", how="left")

    # 对于没有 bench 的项，bench_score 为空，记为 0（只靠 repo 基础分）
    out["bench_score"] = out["bench_score"].fillna(0.0)

    # 最终分：repo 基础分（composite_v2）与 bench_score 融合
    # 记住 composite_v2 已经是 0~1（或接近）范围，如不是，可先线性缩放
    out["final_score"] = args.alpha_repo*out["composite_v2"] + args.beta_bench*out["bench_score"]

    # 排名
    out = out.sort_values("final_score", ascending=False)
    Path(args.out).write_text(out.to_csv(index=False), encoding="utf-8")
    print(f"[done] wrote final merged: {args.out}")

if __name__ == "__main__":
    main()
