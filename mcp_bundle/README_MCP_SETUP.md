# Sci Tools MCP Bundle

Source: `tools_data.csv`  •  TOP_K=30

## Files
- requirements.txt       Pip packages (filtered + normalized)
- install_pip.bat/.sh    One-click installers for pip
- tools_manifest.json    MCP-like manifest (id/pip/import_test/score_Q)
- mcp_server_stub.py     Minimal stub to validate imports
- conda_env.yml          (Optional) Conda env with conda-preferred pkgs

## Usage
Windows (pip):
  .\install_pip.bat
  python mcp_server_stub.py

Conda (recommended for RDKit/deepmd/openmm on Windows):
  conda env create -f conda_env.yml
  conda activate sci-tools
  python mcp_server_stub.py

## Notes
- Some scientific packages are better installed via conda-forge on Windows (rdkit, deepmd-kit, openmm).
- If a package/import name differs, edit `overrides` in build script and re-run.
