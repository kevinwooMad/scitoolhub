# build_mcp_bundle_v2.py
# Robust MCP bundle builder with skip/overrides and optional Conda env export

import os, json, argparse, sys
from pathlib import Path
import pandas as pd

def guess_pkg_from_repo(full: str) -> str:
    # owner/repo -> repo (lowercase)
    return full.split("/")[-1].strip().lower()

def main():
    ap = argparse.ArgumentParser(description="Build an MCP-ready tool bundle from ranked CSV.")
    ap.add_argument("--ranked", default="tools_ranked.csv",
                    help="CSV from scoring notebook (must contain columns: repo, Q).")
    ap.add_argument("--fallback", default="tools_data.csv",
                    help="Fallback CSV if ranked is missing (must contain repo).")
    ap.add_argument("--topk", type=int, default=30, help="Top-K tools to include.")
    ap.add_argument("--minq", type=float, default=0.0, help="Min Q threshold (applies when ranked is present).")
    ap.add_argument("--out", default="mcp_bundle", help="Output folder.")
    ap.add_argument("--include-langs", nargs="*", default=[],
                    help='Filter by languages (e.g. --include-langs Python "C++"). Empty means no filter.')
    ap.add_argument("--emit-conda", action="store_true",
                    help="Also emit a conda_env.yml (packages better via conda go there; others in pip section).")
    args = ap.parse_args()

    # ---------- Load input ----------
    if os.path.exists(args.ranked):
        df = pd.read_csv(args.ranked)
        if "Q" not in df.columns:
            raise ValueError("tools_ranked.csv found but missing column Q. Please re-run scoring to produce Q.")
        print(f"[info] Loaded {len(df)} rows from {args.ranked}")
        if args.include_langs and "language" in df.columns:
            df = df[df["language"].isin(args.include_langs)]
        df = df.sort_values("Q", ascending=False)
        if args.minq > 0:
            df = df[df["Q"] >= args.minq]
        source = args.ranked
    else:
        assert os.path.exists(args.fallback), f"Neither {args.ranked} nor {args.fallback} exists."
        df = pd.read_csv(args.fallback)
        print(f"[warn] Using fallback {args.fallback} (no Q). Selecting by stars/commits/contributors heuristics.")
        if args.include_langs and "language" in df.columns:
            df = df[df["language"].isin(args.include_langs)]
        # Fallback scoring
        for c in ["stars","commits_last_180_days","contributors_count"]:
            if c not in df.columns:
                df[c] = 0
        df["__Q_fallback__"] = (
            df["stars"].fillna(0)*0.5 +
            df["commits_last_180_days"].fillna(0)*0.3 +
            df["contributors_count"].fillna(0)*0.2
        )
        df = df.sort_values("__Q_fallback__", ascending=False).drop(columns=["__Q_fallback__"])
        source = args.fallback

    assert "repo" in df.columns, "CSV must contain column `repo`."
    top = df.head(args.topk).copy()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # ---------- Mapping rules ----------
    # Known non-PyPI or tricky repos (skip or prefer conda)
    skip_repos_or_pkgs = {
        # Non-pip or typically source-only
        "an-introduction-to-applied-bioinformatics",
        "MolecularAI/REINVENT4",
        "gcorso/DiffDock",
        "maxhodak/keras-molecules",
        "wengong-jin/icml18-jtnn",
        "biobert",          # not a pip package; usually a model name
        "deepvariant",      # better via conda or custom install
        # Add more as you encounter
    }

    # Prefer conda for these packages on Windows / scientific stacks
    conda_preferred = {
        "rdkit", "deepmd-kit", "openmm", "pyg", "torch-geometric", "pytorch",
        # extend as needed
    }

    # Manual overrides: repo -> proper PyPI and import name
    overrides = {
        "biopython/biopython": {"pypi": "biopython", "import": "Bio"},
        "MDAnalysis/mdanalysis": {"pypi": "MDAnalysis", "import": "MDAnalysis"},
        "mdtraj/mdtraj": {"pypi": "mdtraj", "import": "mdtraj"},
        "biotite-dev/biotite": {"pypi": "biotite", "import": "biotite"},
        "BioPandas/biopandas": {"pypi": "biopandas", "import": "biopandas"},
        "ParmEd/ParmEd": {"pypi": "parmed", "import": "parmed"},
        "datamol-io/datamol": {"pypi": "datamol", "import": "datamol"},
        "mordred-descriptor/mordred": {"pypi": "mordred", "import": "mordred"},
        "openmm/openmm": {"pypi": "openmm", "import": "openmm"},
        # Examples you might see in lists
        "deepchem/deepchem": {"pypi": "deepchem", "import": "deepchem"},
        "plotly/dash": {"pypi": "dash", "import": "dash"},
        "microsoft/DeepGNN": {"pypi": "deepgnn", "import": "deepgnn"},
        # Add more as needed...
    }

    # ---------- Build package table ----------
    rows = []
    for _, r in top.iterrows():
        repo = r["repo"]
        pkg = guess_pkg_from_repo(repo)
        imp = pkg.replace("-", "_")
        if repo in overrides:
            pkg = overrides[repo].get("pypi", pkg)
            imp = overrides[repo].get("import", imp)
        rows.append({
            "repo": repo,
            "Q": float(r["Q"]) if "Q" in r else None,
            "language": r.get("language", ""),
            "pypi_package": pkg,
            "import_name": imp,
        })
    df_pkgs = pd.DataFrame(rows)

    # ---------- Split into pip vs conda (and skip) ----------
    pip_pkgs = []
    conda_pkgs = []
    for _, row in df_pkgs.iterrows():
        repo_full = row["repo"]
        pkg = row["pypi_package"]
        if repo_full in skip_repos_or_pkgs or pkg in skip_repos_or_pkgs:
            continue
        # route to conda if preferred, otherwise pip
        if pkg in conda_preferred:
            conda_pkgs.append(pkg)
        else:
            pip_pkgs.append(pkg)

    pip_pkgs = sorted(set(pip_pkgs))
    conda_pkgs = sorted(set(conda_pkgs))

    # ---------- Write requirements.txt ----------
    (out / "requirements.txt").write_text("\n".join(pip_pkgs), encoding="utf-8")

    # ---------- Write installers ----------
    (out / "install_pip.bat").write_text(
        "@echo off\r\n"
        "python -m pip install -U pip\r\n"
        "python -m pip install -r requirements.txt\r\n"
        "echo Done.\r\n",
        encoding="utf-8"
    )
    (out / "install_pip.sh").write_text(
        "#!/usr/bin/env bash\nset -e\npython -m pip install -U pip\npython -m pip install -r requirements.txt\necho Done.\n",
        encoding="utf-8"
    )

    # ---------- Optional: emit a conda env yaml ----------
    if args.emit_conda:
        # Basic pinned Python (3.11 更稳)，conda-forge 优先
        conda_env = {
            "name": "sci-tools",
            "channels": ["conda-forge", "defaults"],
            "dependencies": [
                "python>=3.11,<3.12",
                # scientific base stack is often helpful
                "numpy",
                "pandas",
                "matplotlib",
            ]
        }
        # Add conda-preferred pkgs if any
        conda_env["dependencies"].extend(sorted(set(conda_pkgs)))
        # Put remaining pip pkgs into pip section
        if pip_pkgs:
            conda_env["dependencies"].append({
                "pip": pip_pkgs
            })
        import yaml  # requires pyyaml; if missing, just write JSON-ish
        (out / "conda_env.yml").write_text(
            yaml.safe_dump(conda_env, sort_keys=False, allow_unicode=True),
            encoding="utf-8"
        )

    # ---------- Manifest ----------
    manifest = {
        "name": "sci-tools",
        "version": "0.2.0",
        "description": "Curated scientific toolset generated from GitHub metrics.",
        "source_csv": Path(args.ranked).name if os.path.exists(args.ranked) else Path(args.fallback).name,
        "tools": [
            {
                "id": row["pypi_package"],
                "repo": row["repo"],
                "language": row.get("language", ""),
                "pip": row["pypi_package"],
                "import_test": row["import_name"],
                "score_Q": row.get("Q"),
                "install_via": "conda" if row["pypi_package"] in conda_pkgs else "pip"
            }
            for _, row in df_pkgs.iterrows()
            if (row["repo"] not in skip_repos_or_pkgs and row["pypi_package"] not in skip_repos_or_pkgs)
        ]
    }
    (out / "tools_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- Minimal MCP server stub ----------
    stub = r'''"""
Minimal MCP server stub.
Customize: import the packages from tools_manifest.json and expose them to your agent runtime.
"""
import json, importlib
from pathlib import Path

MANIFEST_PATH = Path(__file__).parent / "tools_manifest.json"

def load_tools():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    tools = []
    for t in manifest.get("tools", []):
        name = t.get("import_test") or t.get("pip")
        try:
            importlib.import_module(name)
            tools.append({"id": t["id"], "module": name, "ok": True, "install_via": t.get("install_via")})
        except Exception as e:
            tools.append({"id": t["id"], "module": name, "ok": False, "error": str(e), "install_via": t.get("install_via")})
    return tools

def main():
    tools = load_tools()
    ok = [t for t in tools if t.get("ok")]
    bad = [t for t in tools if not t.get("ok")]
    print(f"Loaded {len(ok)} tools; {len(bad)} failed.")
    if bad:
        print("Failures (first 10):")
        for t in bad[:10]:
            print(" -", t["id"], "(via", t.get("install_via"), ")->", t.get("error"))

if __name__ == "__main__":
    main()
'''
    (out / "mcp_server_stub.py").write_text(stub, encoding="utf-8")

    # ---------- README ----------
    readme = f"""# Sci Tools MCP Bundle

Source: `{Path(source).name}`  •  TOP_K={len(top)}

## Files
- requirements.txt       Pip packages (filtered + normalized)
- install_pip.bat/.sh    One-click installers for pip
- tools_manifest.json    MCP-like manifest (id/pip/import_test/score_Q)
- mcp_server_stub.py     Minimal stub to validate imports
- conda_env.yml          (Optional) Conda env with conda-preferred pkgs

## Usage
Windows (pip):
  .\\install_pip.bat
  python mcp_server_stub.py

Conda (recommended for RDKit/deepmd/openmm on Windows):
  conda env create -f conda_env.yml
  conda activate sci-tools
  python mcp_server_stub.py

## Notes
- Some scientific packages are better installed via conda-forge on Windows (rdkit, deepmd-kit, openmm).
- If a package/import name differs, edit `overrides` in build script and re-run.
"""
    (out / "README_MCP_SETUP.md").write_text(readme, encoding="utf-8")

    # ---------- Done ----------
    print(f"[done] Wrote bundle to: {out.resolve()}")
    print("pip requirements (first 10):", pip_pkgs[:10])
    if args.emit_conda:
        print("conda packages (first 10):", conda_pkgs[:10])

if __name__ == "__main__":
    # Optional: friendly check for PyYAML when --emit-conda is used
    # We only warn if missing; pip section still works.
    try:
        import yaml  # type: ignore
    except Exception:
        if "--emit-conda" in sys.argv:
            print("[warn] PyYAML not installed; install via `pip install pyyaml` to emit conda_env.yml.", file=sys.stderr)
    main()
