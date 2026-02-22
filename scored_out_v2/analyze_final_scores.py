import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os
import argparse


def analyze_scores(csv_path, outdir, topn=30):
    os.makedirs(outdir, exist_ok=True)

    df = pd.read_csv(csv_path)
    print(f"[info] 加载 {len(df)} 条记录，字段：{list(df.columns)}")

    # --- 1️⃣ 基础统计 ---
    desc = df.describe(include='all')
    desc.to_csv(os.path.join(outdir, 'summary_stats.csv'))

    # --- 2️⃣ 前 TopN ---
    df_top = df.sort_values('final_score', ascending=False).head(topn)
    df_top.to_csv(os.path.join(outdir, f'top{topn}_tools.csv'), index=False)

    # --- 3️⃣ 得分分布 ---
    plt.figure(figsize=(8, 5))
    sns.histplot(df['final_score'], bins=20, kde=True)
    plt.title('Final Score Distribution')
    plt.xlabel('Final Score')
    plt.ylabel('Count')
    plt.tight_layout()
    plt.savefig(os.path.join(outdir, 'score_distribution.png'))
    plt.close()

    # --- 4️⃣ 领域平均得分 ---
    if 'category' in df.columns:
        plt.figure(figsize=(8, 5))
        df.groupby('category')['final_score'].mean().sort_values().plot(kind='bar', color='skyblue')
        plt.title('Average Score by Category')
        plt.ylabel('Mean Final Score')
        plt.tight_layout()
        plt.savefig(os.path.join(outdir, 'domain_breakdown.png'))
        plt.close()

    # --- 5️⃣ Star vs Score ---
    star_col = None
    for c in ['stars', 'repo_stars', 'gh_stars']:
        if c in df.columns:
            star_col = c
            break

    if star_col:
        plt.figure(figsize=(6, 5))
        sns.scatterplot(data=df, x=star_col, y='final_score', alpha=0.6)
        plt.xscale('log')
        plt.xlabel('Stars (log scale)')
        plt.ylabel('Final Score')
        plt.title('Stars vs Final Score')
        plt.tight_layout()
        plt.savefig(os.path.join(outdir, 'star_vs_score.png'))
        plt.close()

    # --- 6️⃣ bench_score vs composite_v2 ---
    if 'bench_score' in df.columns and 'composite_v2' in df.columns:
        plt.figure(figsize=(6, 5))
        sns.scatterplot(data=df, x='bench_score', y='composite_v2', alpha=0.6)
        plt.xlabel('Benchmark Score')
        plt.ylabel('Composite (Repo) Score')
        plt.title('Benchmark vs Composite Score')
        plt.tight_layout()
        plt.savefig(os.path.join(outdir, 'bench_vs_composite.png'))
        plt.close()

    # --- 7️⃣ 生成文字报告 ---
    md_path = os.path.join(outdir, 'final_analysis.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(f"# 最终打分分析报告\n\n")
        f.write(f"**输入文件：** {csv_path}\n\n")
        f.write(f"**总工具数：** {len(df)}\n\n")
        f.write(f"**前 {topn} 工具平均得分：** {df_top['final_score'].mean():.3f}\n\n")

        if 'category' in df.columns:
            f.write("## 各领域平均分\n")
            f.write(df.groupby('category')['final_score'].mean().to_string())
            f.write("\n\n")

        if star_col:
            corr = df[[star_col, 'final_score']].corr().iloc[0, 1]
            f.write(f"**Star 数与 Final Score 的相关系数：** {corr:.3f}\n\n")

        if 'bench_score' in df.columns and 'composite_v2' in df.columns:
            corr2 = df[['bench_score', 'composite_v2']].corr().iloc[0, 1]
            f.write(f"**Bench Score 与 Repo Score 的相关系数：** {corr2:.3f}\n\n")

        f.write(f"生成的图表包括：\n\n")
        f.write("- score_distribution.png\n- domain_breakdown.png (如有 category)\n")
        f.write("- star_vs_score.png (如有 star 数据)\n- bench_vs_composite.png (如有字段)\n")

    print(f"[done] 报告与图表已生成至 {outdir}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Analyze final_scored.csv and generate summary visuals.')
    parser.add_argument('--csv', required=True, help='Path to final_scored.csv')
    parser.add_argument('--outdir', default='final_analysis', help='Output directory')
    parser.add_argument('--topn', type=int, default=30)
    args = parser.parse_args()

    analyze_scores(args.csv, args.outdir, args.topn)
