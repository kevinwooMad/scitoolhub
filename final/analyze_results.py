import os
import json
import argparse
import pandas as pd
import matplotlib.pyplot as plt

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def load_benchmark(path):
    """支持 dict 形式的 JSON 文件"""
    with open(path, 'r', encoding='utf-8-sig') as f:
        data = json.load(f)

    items = []
    # 如果是字典 {tool_name: {...}}
    if isinstance(data, dict):
        for name, info in data.items():
            items.append({
                "name": name,
                "status": info.get("status", ""),
                "elapsed_s": float(info.get("time", 0.0)),
                "msg": info.get("msg", "")
            })
    # 如果是列表 [ {...}, {...} ]
    elif isinstance(data, list):
        for d in data:
            if isinstance(d, dict):
                items.append({
                    "name": d.get("name", "unknown"),
                    "status": d.get("status", ""),
                    "elapsed_s": float(d.get("elapsed", d.get("time", 0.0))),
                    "msg": d.get("msg", d.get("result", ""))
                })
    else:
        raise ValueError("Unsupported JSON structure")

    return pd.DataFrame(items)


def summarize(df, topn=20):
    df["passed"] = df["status"].str.lower().eq("ok")
    df["skipped"] = df["status"].str.lower().eq("skipped")

    total = len(df)
    passed = int(df["passed"].sum())
    failed = int((~df["passed"] & ~df["skipped"]).sum())
    skipped = int(df["skipped"].sum())

    summary = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "pass_rate": round(passed / total, 3) if total else 0,
        "avg_latency_s": round(df["elapsed_s"].mean(), 4)
    }

    df_sorted = df.sort_values(["passed", "elapsed_s"], ascending=[False, True])
    return df_sorted.head(topn), summary


def plot_latency(df, out_png):
    plt.figure(figsize=(10, 4))
    plt.bar(df["name"], df["elapsed_s"])
    plt.xticks(rotation=60, ha="right")
    plt.ylabel("Latency (s)")
    plt.title("Top tools by latency")
    plt.tight_layout()
    plt.savefig(out_png, dpi=160)
    plt.close()


def plot_pass_fail(df, out_png):
    sizes = [
        int(df["passed"].sum()),
        int((~df["passed"] & ~df["skipped"]).sum()),
        int(df["skipped"].sum())
    ]
    labels = ["Passed", "Failed", "Skipped"]
    plt.figure(figsize=(4, 4))
    plt.pie(sizes, labels=labels, autopct="%1.0f%%")
    plt.title("Pass/Fail/Skip Distribution")
    plt.tight_layout()
    plt.savefig(out_png, dpi=160)
    plt.close()


def write_markdown(df, summary, out_md):
    lines = [
        "# Benchmark Summary",
        f"- Total: **{summary['total']}**",
        f"- Passed: **{summary['passed']}**",
        f"- Failed: **{summary['failed']}**",
        f"- Skipped: **{summary['skipped']}**",
        f"- Pass rate: **{summary['pass_rate']*100:.1f}%**",
        f"- Avg latency: **{summary['avg_latency_s']}s**",
        "\n## Top Tools\n",
        df.to_markdown(index=False)
    ]
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--outdir", default="analysis_out")
    ap.add_argument("--topn", type=int, default=20)
    args = ap.parse_args()

    ensure_dir(args.outdir)
    df = load_benchmark(args.input)
    head, summary = summarize(df, args.topn)

    csv_path = os.path.join(args.outdir, "benchmark_analysis.csv")
    md_path = os.path.join(args.outdir, "analysis_results.md")
    png_latency = os.path.join(args.outdir, "latency_bar.png")
    png_pie = os.path.join(args.outdir, "pass_fail_pie.png")

    df.to_csv(csv_path, index=False)
    write_markdown(head, summary, md_path)
    plot_latency(head, png_latency)
    plot_pass_fail(df, png_pie)

    print("[done] Results written to:")
    print(" -", csv_path)
    print(" -", md_path)
    print(" -", png_latency)
    print(" -", png_pie)


if __name__ == "__main__":
    main()
