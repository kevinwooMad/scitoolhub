import pandas as pd, json

def main():
    df = pd.read_csv("scored_out_v2/ranked_tools_v2.csv")
    with open("benchmark_summary.json", "r", encoding="utf-8") as f:
        bench = pd.DataFrame(json.load(f))

    bench["run_score"] = bench["passed"].astype(float) * (1.0 - bench["elapsed"].fillna(1)/2.0)
    merged = df.merge(bench[["tool", "run_score"]], left_on="name", right_on="tool", how="left")
    merged["run_score"].fillna(0, inplace=True)
    merged["final_score"] = 0.8 * merged["composite_v2"] + 0.2 * merged["run_score"]

    merged.sort_values("final_score", ascending=False).to_csv("final_rank.csv", index=False)
    print("[done] final_rank.csv written")

if __name__ == "__main__":
    main()
