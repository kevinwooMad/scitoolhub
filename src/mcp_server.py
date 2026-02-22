# -*- coding: utf-8 -*-
"""
mcp_server.py
扩展版：支持 /run 调用任意白名单科学包函数。
兼容 run_benchmarks.py 的请求格式。
"""

import os
import importlib
import traceback
from typing import Dict, Any
from flask import Flask, jsonify, request

APP = Flask(__name__)

TOOLS_TXT = os.path.join("scored_out_v2", "requirements_top20_windows.txt")

LOADED: Dict[str, Any] = {}

# ---- 白名单映射 ----
ALIAS_MAP = {
    "biopython": "Bio",
    "bio": "Bio",
    "deepchem": "deepchem",
    "pennylane": "pennylane",
    "dash": "dash",
    "datamol": "datamol",
    "parmed": "parmed",
    "pycirclize": "pycirclize",
    "pydeseq2": "pydeseq2",
    "scispacy": "spacy",
    "plantcv": "plantcv",
    "dft": "dft",
    "spacy": "spacy",
    "scikit-bio": "skbio",
    "skbio": "skbio",
}

ALLOWLIST = set(ALIAS_MAP.values())

def _resolve_module_name(name: str) -> str:
    if not name:
        return ""
    key = name.strip().lower()
    return ALIAS_MAP.get(key, name)

# 在文件顶部合适位置加入：
SAFE_BUILTINS = {
    "__import__": __import__,
    "getattr": getattr,
    "setattr": setattr,   # 可选，如不需要可去掉
    "hasattr": hasattr,
    "len": len,
    "str": str,
    "int": int,
    "float": float,
    "dict": dict,
    "list": list,
    "tuple": tuple,
    "bool": bool,
}

def _build_eval_env(loaded_modules: dict) -> dict:
    # 用“最小安全内建”替换空 builtins
    env = {"__builtins__": SAFE_BUILTINS}
    # 暴露已加载模块
    for k, v in loaded_modules.items():
        if v:
            env[k] = v
    # 兼容别名 -> 实名映射
    for alias, real in ALIAS_MAP.items():
        if real in loaded_modules and loaded_modules[real]:
            env[real] = loaded_modules[real]
    return env

@APP.get("/modules")
def list_modules():
    # 返回你的 allowlist 或已加载成功的模块名（两种都可以）
    # 1) 若想返回允许调用的名字（含别名）
    return jsonify(sorted(set(ALIAS_MAP.keys())))

    # 2) 或者返回已成功 import 的真实模块名
    # return jsonify(sorted([k for k, v in LOADED.items() if v is not None]))


def _load_tools():
    skip_list = {"pyscf", "doped", "molecularnodes"}
    if not os.path.exists(TOOLS_TXT):
        print(f"[warn] Missing {TOOLS_TXT}, using default top20 list.")
        pkgs = list(ALIAS_MAP.keys())
    else:
        with open(TOOLS_TXT, "r", encoding="utf-8") as f:
            pkgs = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    for name in pkgs:
        if name in skip_list:
            print(f"[skip] {name} (暂时不导入)")
            LOADED[name] = None
            continue
        try:
            mod = importlib.import_module(name)
            LOADED[name] = mod
        except Exception as e:
            print(f"[fail] {name}: {e.__class__.__name__} - {e}")
            LOADED[name] = None

@APP.route("/tools", methods=["GET"])
def list_tools():
    data = []
    for name, mod in LOADED.items():
        data.append({
            "package": name,
            "imported": mod is not None
        })
    return jsonify({"ok": True, "tools": data})

@APP.post("/run")
def run():
    """
    通用执行接口：
    { "module": "biopython", "function": "Bio.Seq.Seq", "args": ["ATCG"], "kwargs": {} }
    """
    data = request.get_json(silent=True) or {}
    func_expr = data.get("function")
    args = data.get("args", [])
    kwargs = data.get("kwargs", {})
    module_req = data.get("module", "")

    # --- 参数检查 ---
    if not func_expr or not isinstance(func_expr, str):
        return jsonify({"ok": False, "error": "missing 'function' string"}), 400
    if not isinstance(args, list) or not isinstance(kwargs, dict):
        return jsonify({"ok": False, "error": "'args' must be list and 'kwargs' must be dict"}), 400

    # --- 动态导入模块（若请求指定）---
    if module_req:
        real_name = _resolve_module_name(module_req)
        if real_name not in ALIAS_MAP.values() and real_name not in LOADED:
            return jsonify({"ok": False, "error": f"module '{module_req}' not allowed"}), 400
        if real_name not in LOADED or LOADED.get(real_name) is None:
            try:
                LOADED[real_name] = importlib.import_module(real_name)
            except Exception as e:
                return jsonify({"ok": False, "error": f"cannot import module '{real_name}': {type(e).__name__}: {e}"}), 400

    safe_env = _build_eval_env(LOADED)

    # --- 执行表达式 ---
    try:
        obj = eval(func_expr, safe_env, {})
    except Exception as e:
        return jsonify({"ok": False, "error": f"eval failed: {type(e).__name__}: {e}"}), 400

    # --- 如果是函数则调用，否则直接返回值 ---
    if callable(obj):
        try:
            result = obj(*args, **kwargs)
        except Exception as e:
            return jsonify({
                "ok": False,
                "error": f"call failed: {type(e).__name__}: {e}",
                "trace": traceback.format_exc()
            }), 500
    else:
        result = obj  # 直接返回表达式结果

    # --- 尝试序列化返回 ---
    try:
        return jsonify({"ok": True, "result": result}), 200
    except Exception:
        return jsonify({"ok": True, "result": str(result)}), 200


def main():
    _load_tools()
    print(f"[server] loaded {sum(1 for m in LOADED.values() if m)} tools; "
          f"{sum(1 for m in LOADED.values() if m is None)} failed or skipped.")
    APP.run(host="0.0.0.0", port=8008, debug=False)

if __name__ == "__main__":
    main()
