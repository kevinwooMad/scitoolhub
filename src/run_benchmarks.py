# run_benchmarks.py
# -*- coding: utf-8 -*-
import json
import time
import argparse
import requests
from pathlib import Path

DEFAULT_SERVER = "http://127.0.0.1:8008"

# 测试用例（全部 ASCII，避免控制台编码问题）
TEST_CASES = {
    "dash":         {"type": "version", "module": "dash"},
    "pycirclize":   {"type": "version", "module": "pycirclize"},
    "datamol":      {"type": "version", "module": "datamol"},
    "pennylane":    {"type": "version", "module": "pennylane"},
    "deepchem":     {"type": "version", "module": "deepchem"},
    "biopython":    {"type": "version", "module": "Bio"},
    "scanpy":       {"type": "version", "module": "scanpy"},
    "anndata":      {"type": "version", "module": "anndata"},
    "pydeseq2":     {"type": "version", "module": "pydeseq2"},
    "mdtraj":       {"type": "version", "module": "mdtraj"},
    "mdanalysis":   {"type": "version", "module": "MDAnalysis"},
    "scispacy":     {"type": "version", "module": "spacy", "label": "spacy version (for scispacy)"},
    "plantcv":      {"type": "module",  "module": "plantcv"},
    "dft":          {"type": "module",  "module": "dft"},
    "parmed":       {"type": "version", "module": "parmed"},
    "spacy":        {"type": "version", "module": "spacy"},
    # 重/难依赖：按需加入
    "scikit-bio":   {"type": "version", "module": "skbio"},
    "skbio":        {"type": "version", "module": "skbio"},
    # 明确跳过项
    "galaxy":       {"type": "skip", "reason": "skip: Galaxy requires external services"},
    "hail":         {"type": "skip", "reason": "skip: Hail requires JVM/Spark"},
    "atomate2":     {"type": "skip", "reason": "skip: Atomate2 requires full materials workflow stack"},
}

def payload_for_case(name: str, case: dict):
    ctype = case.get("type")
    module = case.get("module", "")
    if ctype == "version":
        return {
            "module": module,
            "function": "getattr(__import__('{}'), '__version__', 'unknown')".format(module),
            "args": [],
            "kwargs": {},
            "label": case.get("label", "version")
        }
    elif ctype == "module":
        return {
            "module": module,
            "function": "__import__",
            "args": [module],
            "kwargs": {},
            "label": case.get("label", "module import")
        }
    elif ctype == "skip":
        return {"type": "skip", "label": case.get("reason", "skip")}
    else:
        return {"type": "skip", "label": "no test case defined"}

def fetch_server_modules(server: str):
    try:
        r = requests.get(f"{server}/modules", timeout=2)
        if r.status_code == 200:
            out = r.json()
            if isinstance(out, dict) and "modules" in out and isinstance(out["modules"], list):
                return out["modules"]
            if isinstance(out, list):
                return out
    except Exception:
        pass
    return None

def load_top_candidates(server: str, json_path: str | None, topn: int):
    names = None
    mods = fetch_server_modules(server)
    if mods:
        names = [str(x) for x in mods][:topn]

    if names is None and json_path:
        try:
            data = json.loads(Path(json_path).read_text(encoding="utf-8"))
            if isinstance(data, dict) and "top" in data and isinstance(data["top"], list):
                raw = data["top"]
                names = []
                for x in raw:
                    if isinstance(x, str):
                        names.append(x)
                    elif isinstance(x, dict):
                        repo = x.get("repo") or x.get("name") or ""
                        if repo:
                            names.append(repo.split("/")[-1])
                names = names[:topn]
            elif isinstance(data, list):
                names = []
                for x in data:
                    if isinstance(x, str):
                        names.append(x)
                    elif isinstance(x, dict):
                        repo = x.get("repo") or x.get("name") or ""
                        if repo:
                            names.append(repo.split("/")[-1])
                names = names[:topn]
        except Exception:
            pass

    if names is None or len(names) == 0:
        print("[warn] use built-in fallback candidates")
        names = [
            "dash","pycirclize","datamol","pennylane","deepchem","biopython",
            "scispacy","scanpy","anndata","pydeseq2","scikit-bio","skbio",
            "mdtraj","mdanalysis","parmed","plantcv","dft","galaxy","hail","atomate2"
        ][:topn]
    return names

def bench_one(server: str, name: str):
    case = TEST_CASES.get(name)
    if case is None:
        return {"name": name, "label": "-", "passed": None, "skipped": True, "elapsed_s": 0.0, "detail": "no test case defined"}

    payload = payload_for_case(name, case)
    if payload.get("type") == "skip":
        return {"name": name, "label": "-", "passed": None, "skipped": True, "elapsed_s": 0.0, "detail": payload.get("label","skip")}

    label = payload.pop("label", "")
    t0 = time.time()
    try:
        r = requests.post(f"{server}/run", json=payload, timeout=10)
        el = round(time.time() - t0, 2)
        if r.status_code == 200:
            return {"name": name, "label": label, "passed": True,  "skipped": False, "elapsed_s": el, "detail": r.text}
        else:
            return {"name": name, "label": label, "passed": False, "skipped": False, "elapsed_s": el, "detail": f"HTTP {r.status_code} | {r.text[:200]}"}
    except Exception as e:
        el = round(time.time() - t0, 2)
        return {"name": name, "label": label, "passed": False, "skipped": False, "elapsed_s": el, "detail": repr(e)}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default=DEFAULT_SERVER)
    ap.add_argument("--json", default=None, help="path to top20 json")
    ap.add_argument("--topn", type=int, default=20)
    args = ap.parse_args()

    names = load_top_candidates(args.server, args.json, args.topn)
    print("Benchmarking {} top tools...".format(len(names)))

    results = []
    for name in names:
        rec = bench_one(args.server, name)
        results.append(rec)
        status = "SKIP" if rec["skipped"] else ("PASS" if rec["passed"] else "FAIL")
        print("{} {:<15} | {:>4.2f}s | {} | {}".format(
            status, name, rec["elapsed_s"], rec["label"] or "-", rec["detail"][:100].replace("\n"," ")
        ))

    tested = [r for r in results if not r["skipped"]]
    passed = sum(1 for r in tested if r["passed"])
    total  = len(tested)
    avg_t  = round(sum(r["elapsed_s"] for r in tested) / total, 2) if total else 0.0

    print("\n=== Summary ===")
    print("Pass rate: {}/{}".format(passed, total))
    print("Avg latency: {:.2f}s".format(avg_t))

    Path("benchmark_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Benchmark Results", "", "- Pass: {}/{}".format(passed, total), "- Avg latency: {:.2f}s".format(avg_t), ""]
    for r in results:
        badge = "SKIP" if r["skipped"] else ("PASS" if r["passed"] else "FAIL")
        lines.append("- **{}** [{}] — {} — {}s — {}".format(
            r["name"], badge, r["label"] or "-", r["elapsed_s"], r["detail"][:160].replace("\n"," ")
        ))
    Path("benchmark_results.md").write_text("\n".join(lines), encoding="utf-8")
    print("[done] wrote: benchmark_results.json / benchmark_results.md")

if __name__ == "__main__":
    main()
