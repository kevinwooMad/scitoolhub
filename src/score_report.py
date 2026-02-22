# score_report.py
# -*- coding: utf-8 -*-
import argparse, pandas as pd
from pathlib import Path

TEMPLATE = """# 最终分数报告

**数据源**
- 基础分（composite_v2）：来自 `tools_data_enriched.csv` 计算（README 完整度、CI/测试信号、stars/forks、活跃度等）。
- 运行分（bench_score）：来自 `benchmark_results.json`（是否通过 + 时延归一）。
- 最终分：`final_score = {alpha_repo} * composite_v2 + {beta_bench} * bench_score`。

**Top {topn}（按 final_score 排序）**
{top_table}

---

## 打分口径（摘要）
- 基础分 composite_v2：多指标归一+加权，偏重生态质量、文档、近期活跃度。
- bench_score：70% 取决于是否通过；30% 取决于相对时延（越快越高）。
- 跳过项（无法在本机合理运行的重型依赖）不计入 bench_score，但保留基础分。

"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="scored_out_v2/final_scored.csv")
    ap.add_argument("--outmd", default="final_score_report.md")
    ap.add_argument("--outhtml", default="final_score_report.html")
    ap.add_argument("--topn", type=int, default=20)
    ap.add_argument("--alpha_repo", type=float, default=0.7)
    ap.add_argument("--beta_bench", type=float, default=0.3)
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    cols = ["repo","domain","composite_v2","bench_score","final_score"]
    cols = [c for c in cols if c in df.columns]
    head = df[cols].head(args.topn).copy()

    def fmt(x):
        try: return f"{float(x):.4f}"
        except: return str(x)

    head = head.rename(columns={
        "repo":"Repo", "domain":"Domain",
        "composite_v2":"基础分", "bench_score":"运行分", "final_score":"最终分"
    })
    for c in ["基础分","运行分","最终分"]:
        if c in head.columns: head[c] = head[c].map(fmt)

    top_table = head.to_markdown(index=False)

    md = TEMPLATE.format(
        alpha_repo=args.alpha_repo, beta_bench=args.beta_bench,
        topn=args.topn, top_table=top_table
    )
    Path(args.outmd).write_text(md, encoding="utf-8")

    # 简易 HTML
    html = "<meta charset='utf-8'>\n" + md.replace("\n", "<br>\n")
    Path(args.outhtml).write_text(html, encoding="utf-8")

    print(f"[done] report: {args.outmd} / {args.outhtml}")

if __name__ == "__main__":
    main()
