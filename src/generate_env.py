#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
generate_env.py
从 scored_out_v2/top20_v2.json 生成：
  - requirements_top20_raw.txt  （直接由 repo 推断的“候选包名”）
  - requirements_top20_windows.txt（为 Windows 过滤&映射后的可安装清单）
  - env_report.md               （包含被跳过/原因、映射详情）
可选：简单连通性检查（pip index versions）用于标记PyPI可用性（不会中断）
"""

import os
import json
import subprocess

TOP_JSON = os.path.join("scored_out_v2", "top20_v2.json")

# 1) repo -> pip包名 的常见映射/拆包
#    注意：Galaxy、DeepVariant 等非纯Python/强依赖Linux的工具会被标红并跳过（Windows不友好）
REPO_TO_PKGS = {
    # 前几名示例（你这次的Top里有）
    "plotly/dash": ["dash"],                           # OK (pip)
    "deepchem/deepchem": ["deepchem"],                 # OK (pip)
    "PennyLaneAI/pennylane": ["pennylane"],           # OK (pip)
    "biopython/biopython": ["biopython"],              # OK (pip/conda-forge)
    "biotite-dev/biotite": ["biotite"],                # OK (pip/conda-forge)
    "MDAnalysis/mdanalysis": ["MDAnalysis"],           # OK (conda-forge更稳)
    "scikit-bio/scikit-bio": ["scikit-bio"],          # OK (conda-forge更稳)
    "scanpy/scanpy": ["scanpy"],                       # OK (conda-forge更稳)

    # 这些一般在 Windows 上不友好/非纯Python，默认跳过
    "google/deepvariant": [],     # 二进制+Linux优先，Windows基本不可用
    "galaxyproject/galaxy": [],   # Web/服务端平台，部署重，Windows不建议
    "deepmodeling/deepmd-kit": [],# 需编译/硬件加速，Win不友好
    "deepgraphlearning/graphormer": [],  # 研究代码，非pip标准库
    "hail-is/hail": [],           # 依赖JVM/Spark，Win不友好
    "allenai/scispacy": ["scispacy"],  # 本体可安装，但语言模型需另下载；保留
    "sib-swiss/training-collection": [], # 教学资源集合，不是Python包
}

# 2) 明确在Windows上可安装（绿色）与应跳过（红色）的规则
ALWAYS_SKIP = set([
    "google/deepvariant",
    "galaxyproject/galaxy",
    "deepmodeling/deepmd-kit",
    "deepgraphlearning/graphormer",
    "hail-is/hail",
    "sib-swiss/training-collection",
])

# 3) 如果Top20出现以下repo但映射里没有，将按 repo 名的最后一段作包名尝试
def default_guess(repo_fullname: str) -> str:
    return repo_fullname.strip().split("/")[-1].lower()

def pip_exists(package: str) -> bool:
    """轻量可用性标记：查询 PyPI 是否有该包名（失败不抛错，只用于报告）"""
    try:
        p = subprocess.run(
            ["python", "-m", "pip", "index", "versions", package],
            capture_output=True, check=False, text=True
        )
        return (p.returncode == 0) and ("Available versions" in (p.stdout or ""))
    except Exception:
        return False

def main():
    assert os.path.exists(TOP_JSON), f"Missing {TOP_JSON}. 请先运行 score_tools_v2.py 生成 top20_v2.json"
    with open(TOP_JSON, "r", encoding="utf-8") as f:
        items = json.load(f)

    os.makedirs("scored_out_v2", exist_ok=True)
    raw_txt = os.path.join("scored_out_v2", "requirements_top20_raw.txt")
    win_txt = os.path.join("scored_out_v2", "requirements_top20_windows.txt")
    rep_md  = os.path.join("scored_out_v2", "env_report.md")

    selected_raw = []      # 由repo直接映射/猜测的候选包
    selected_win = []      # 过滤后Windows可安装清单
    skipped = []           # 跳过列表（含原因）
    mapping_rows = []      # 报告映射明细

    for it in items:
        repo = it.get("repo", "")
        if not repo:
            continue

        # 1) 跳过不友好 repo
        if repo in ALWAYS_SKIP:
            skipped.append((repo, "Skipped (Windows-unfriendly / non-Python tool)"))
            mapping_rows.append((repo, "—", "SKIPPED"))
            continue

        # 2) 映射到 pip 包名（优先 REPO_TO_PKGS）
        pkgs = REPO_TO_PKGS.get(repo)
        if pkgs is None:
            # 不在映射表里：尝试用默认猜测（repo名最后一段）
            guess = default_guess(repo)
            pkgs = [guess]

        # 3) 写入 raw 列表
        for p in pkgs:
            if p:
                selected_raw.append(p)

        # 4) 过滤为 Windows 可安装清单：目前简单策略=保留映射出的纯 Python 常见库
        for p in pkgs:
            if not p:
                continue
            # 用 pip index 试探可用性（不强制，不中断）
            ok = pip_exists(p)
            tag = "OK" if ok else "UNKNOWN"
            mapping_rows.append((repo, p, tag))
            # 即使 UNKNOWN，也先放入清单（你可手动再删）
            selected_win.append(p)

    # 去重
    def dedup_keep_order(seq):
        seen, out = set(), []
        for x in seq:
            if x not in seen:
                seen.add(x); out.append(x)
        return out

    selected_raw = dedup_keep_order(selected_raw)
    selected_win = dedup_keep_order(selected_win)

    # 写文件
    with open(raw_txt, "w", encoding="utf-8") as f:
        for p in selected_raw:
            f.write(p + "\n")
    with open(win_txt, "w", encoding="utf-8") as f:
        for p in selected_win:
            f.write(p + "\n")

    # 报告
    lines = []
    lines.append("# Environment Report (Top20)\n")
    lines.append("## Mapping\n")
    for repo, pkg, tag in mapping_rows:
        lines.append(f"- {repo} -> `{pkg}` [{tag}]")
    lines.append("\n## Skipped (with reasons)\n")
    if not skipped:
        lines.append("- (none)")
    else:
        for repo, reason in skipped:
            lines.append(f"- {repo}: {reason}")
    with open(rep_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"[done] wrote: {raw_txt}")
    print(f"[done] wrote: {win_txt}")
    print(f"[done] wrote: {rep_md}")

if __name__ == "__main__":
    main()
