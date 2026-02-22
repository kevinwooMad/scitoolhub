# pipeline.py
# -*- coding: utf-8 -*-
"""
一键执行完整 pipeline：
1) 运行基准脚本 run_benchmarks.py
2) 读取 benchmark_results.json
3) 调用 analyze_results.py 生成分析制品（可选）
4) 生成 Markdown + HTML 汇总报告
"""

import subprocess
import json
import argparse
import datetime
from pathlib import Path
import os

def _print_ascii(s: str):
    # 避免 Windows GBK 控制台编码问题：过滤非 ASCII、替换不可显示字符
    try:
        print(s.encode("ascii", "ignore").decode("ascii", "ignore"))
    except Exception:
        # 兜底：静默
        pass

def run_subprocess(cmd, desc, cwd=None):
    # 强制 UTF-8，并容忍不可解码字节
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")

    _print_ascii("")
    _print_ascii("[RUN] {}: {}".format(desc, " ".join(cmd)))

    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",      # 关键：强制按 utf-8 读取
            errors="replace",      # 关键：替换无法解码的字节
            check=False,
            cwd=cwd,
            shell=False,
            env=env,
        )
        if res.stdout:
            _print_ascii(res.stdout)
        if res.stderr:
            _print_ascii("stderr: " + res.stderr)
        return res.returncode == 0
    except Exception as e:
        _print_ascii("[ERROR] {} failed: {}".format(desc, e))
        return False

def safe_load_json(path: str):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None

def write_markdown_report(benchmark, output_path="final_report.md"):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# Benchmark 综合报告",
        "",
        "- 生成时间：{}".format(now),
        "- 记录条数：{}".format(len(benchmark)),
        "",
        "---",
        ""
    ]
    for r in benchmark:
        status = "通过" if r.get("passed") else ("跳过" if r.get("skipped") else "失败")
        lines += [
            "### {}".format(r.get("name","-")),
            "- 状态：{}".format(status),
            "- 标签：{}".format(r.get("label","-")),
            "- 耗时：{}s".format(r.get("elapsed_s",0)),
            "- 详情：{}".format(str(r.get("detail",""))[:200].replace("\n"," ")),
            ""
        ]
    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
    _print_ascii("[OK] Markdown 报告已生成：{}".format(output_path))

def write_html_report(benchmark, output_path="final_report.html"):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    def row(r):
        passed = r.get("passed")
        skipped = r.get("skipped")
        color = "#c8e6c9" if passed else ("#eeeeee" if skipped else "#ffcdd2")
        badge = "PASS" if passed else ("SKIP" if skipped else "FAIL")
        detail = str(r.get("detail",""))[:200].replace("<","&lt;").replace(">","&gt;")
        return (
            "<tr style='background:{}'>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}s</td>"
            "<td>{}</td>"
            "</tr>"
        ).format(
            color, badge, r.get("name","-"), r.get("label","-"),
            r.get("elapsed_s",0), detail
        )
    rows = "\n".join(row(r) for r in benchmark)
    html = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>Benchmark 综合报告</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 2em; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ccc; padding: 6px 10px; text-align: left; }}
th {{ background-color: #f2f2f2; }}
</style>
</head>
<body>
<h1>Benchmark 综合报告</h1>
<p>生成时间：{}</p>
<table>
<tr><th>状态</th><th>模块</th><th>标签</th><th>耗时</th><th>详情</th></tr>
{}
</table>
</body>
</html>
""".format(now, rows)
    Path(output_path).write_text(html, encoding="utf-8")
    _print_ascii("[OK] HTML 报告已生成：{}".format(output_path))

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:8008")
    ap.add_argument("--json", default="scored_out_v2/top20_v2.json")
    ap.add_argument("--topn", type=int, default=20)
    ap.add_argument("--analyze", action="store_true", help="是否在基准后调用 analyze_results.py")
    args = ap.parse_args()

    _print_ascii("\n=== Step 1: 运行基准测试 ===")
    ok_bench = run_subprocess(
        ["python", "run_benchmarks.py", "--server", args.server, "--json", args.json, "--topn", str(args.topn)],
        "运行基准测试"
    )

    if not Path("benchmark_results.json").exists():
        _print_ascii("[FAIL] benchmark_results.json 未找到（run_benchmarks 可能失败）。已停止。")
        return

    benchmark = safe_load_json("benchmark_results.json") or []
    _print_ascii("[INFO] 已加载 {} 条基准记录。".format(len(benchmark)))

    if args.analyze and Path("analyze_results.py").exists():
        _print_ascii("\n=== Step 2: 调用分析脚本 ===")
        ok_ana = run_subprocess(
            ["python", "analyze_results.py", "--input", "benchmark_results.json", "--outdir", "analysis_out", "--topn", str(args.topn)],
            "分析结果"
        )
        if not ok_ana:
            _print_ascii("[WARN] analyze_results.py 运行未成功，继续生成基础报告。")

    _print_ascii("\n=== Step 3: 生成报告 ===")
    write_markdown_report(benchmark, "final_report.md")
    write_html_report(benchmark, "final_report.html")
    _print_ascii("\nDONE. 报告已生成：final_report.md / final_report.html")

if __name__ == "__main__":
    main()
