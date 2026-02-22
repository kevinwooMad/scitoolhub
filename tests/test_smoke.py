import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_src_syntax_compiles():
    """Ensure src/ has no syntax errors."""
    src_dir = ROOT / "src"
    assert src_dir.exists(), "Missing src/ directory"

    r = subprocess.run(
        [sys.executable, "-m", "compileall", str(src_dir)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, (r.stdout + "\n" + r.stderr)

def test_run_demo_exists():
    """Basic repo sanity check."""
    assert (ROOT / "run_demo.py").exists(), "Missing run_demo.py"