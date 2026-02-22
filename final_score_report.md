# 最终分数报告

**数据源**
- 基础分（composite_v2）：来自 `tools_data_enriched.csv` 计算（README 完整度、CI/测试信号、stars/forks、活跃度等）。
- 运行分（bench_score）：来自 `benchmark_results.json`（是否通过 + 时延归一）。
- 最终分：`final_score = 0.7 * composite_v2 + 0.3 * bench_score`。

**Top 20（按 final_score 排序）**
| Repo                       | Domain   |   基础分 |   运行分 |   最终分 |
|:---------------------------|:---------|---------:|---------:|---------:|
| plotly/dash                | other    |   0.3899 |   0.9996 |   0.5728 |
| deepchem/deepchem          | bio      |   0.3015 |   0.9996 |   0.5109 |
| allenai/scispacy           | bio      |   0.2626 |   0.9996 |   0.4837 |
| owkin/PyDESeq2             | bio      |   0.2552 |   0.9992 |   0.4784 |
| moshi4/pyCirclize          | other    |   0.2553 |   0.9796 |   0.4726 |
| ParmEd/ParmEd              | ml       |   0.2597 |   0.9648 |   0.4712 |
| ialbert/bio                | bio      |   0.2355 |   1      |   0.4648 |
| danforthcenter/plantcv     | ml       |   0.2275 |   0.9992 |   0.459  |
| datamol-io/datamol         | other    |   0.2063 |   0.998  |   0.4438 |
| PennyLaneAI/pennylane      | chem     |   0.2596 |   0.7    |   0.3917 |
| kivymd/KivyMD              | bio      |   0.2693 |   0      |   0.1885 |
| insitro/redun              | ml       |   0.2664 |   0      |   0.1865 |
| google/deepvariant         | bio      |   0.2661 |   0      |   0.1863 |
| histolab/histolab          | ml       |   0.2656 |   0      |   0.1859 |
| OmicsML/dance              | ml       |   0.2645 |   0      |   0.1852 |
| BayraktarLab/cell2location | ml       |   0.2639 |   0      |   0.1848 |
| MDIL-SNU/SevenNet          | ml       |   0.2637 |   0      |   0.1846 |
| snakemake/snakefmt         | ml       |   0.2636 |   0      |   0.1845 |
| gyorilab/indra             | ml       |   0.2632 |   0      |   0.1842 |
| zktuong/dandelion          | ml       |   0.263  |   0      |   0.1841 |

---

## 打分口径（摘要）
- 基础分 composite_v2：多指标归一+加权，偏重生态质量、文档、近期活跃度。
- bench_score：70% 取决于是否通过；30% 取决于相对时延（越快越高）。
- 跳过项（无法在本机合理运行的重型依赖）不计入 bench_score，但保留基础分。

