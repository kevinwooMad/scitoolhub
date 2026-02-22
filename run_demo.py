import os
import subprocess

print("Running demo pipeline...")

# Example steps (adjust filenames if needed)
scripts = [
    "discover_repos.py",
    "gh_enrich.py",
    "merge_scores.py",
    "analyze_results.py"
]

for script in scripts:
    if os.path.exists(script):
        print(f"Running {script}")
        subprocess.run(["python", script])
    else:
        print(f"Skipping {script} (not found)")

print("Demo finished.")