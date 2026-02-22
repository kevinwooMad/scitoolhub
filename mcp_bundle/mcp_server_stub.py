"""
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
