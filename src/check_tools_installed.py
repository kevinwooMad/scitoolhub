# -*- coding: utf-8 -*-
"""
check_tools_installed.py
逐个尝试导入 requirements_top20_windows.txt 中的包，报告安装/导入状态。
"""

import os, sys, importlib, json
from typing import Dict

REQ_PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join("scored_out_v2", "requirements_top20_windows.txt")

# repo名与import名可能不同，这里做一个常见映射（可按需增补）
IMPORT_NAME_MAP: Dict[str, str] = {
    "biopython": "Bio",
    "rdkit": "rdkit",
    "pennylane": "pennylane",
    "deepchem": "deepchem",
    "dash": "dash",
    "scispacy": "scispacy",
    "plantcv": "plantcv",
    "doped": "doped",
    "parmed": "parmed",
    "pycirclize": "pycirclize",
    "jcvi": "jcvi",
    "pyscf": "pyscf",
    "molecularnodes": "molecularnodes",
    "pydeseq2": "pydeseq2",
    "datamol": "datamol",
    "dft": "dft",
}

def read_requirements(path: str):
    if not os.path.exists(path):
        print(f"[error] requirements file not found: {path}")
        sys.exit(1)
    pkgs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            # 去掉版本说明，如 pkg==1.2.3
            name = s.split("==")[0].strip()
            pkgs.append(name)
    return pkgs

def try_import(pkg: str):
    modname = IMPORT_NAME_MAP.get(pkg, pkg)
    try:
        mod = importlib.import_module(modname)
        ver = getattr(mod, "__version__", "unknown")
        return {"package": pkg, "import_name": modname, "imported": True, "version": ver, "error": None}
    except Exception as e:
        return {"package": pkg, "import_name": modname, "imported": False, "version": None, "error": str(e)}

def main():
    pkgs = read_requirements(REQ_PATH)
    results = [try_import(p) for p in pkgs]

    ok = [r for r in results if r["imported"]]
    bad = [r for r in results if not r["imported"]]

    print("\n=== ✅ 可导入（已安装） ===")
    for r in ok:
        print(f"- {r['package']:15s}  as {r['import_name']:20s}  version={r['version']}")

    print("\n=== ❌ 导入失败（未安装/未满足依赖） ===")
    for r in bad:
        print(f"- {r['package']:15s}  as {r['import_name']:20s}  error={r['error']}")

    # 同时写一份 JSON 结果，便于留档
    out_json = "check_tools_installed.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n[done] 详细结果已写入: {out_json}")

if __name__ == "__main__":
    main()
