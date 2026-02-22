# SciToolHub  
### Discovering and Evaluating Scientific Software on GitHub

SciToolHub is a Python pipeline that automatically **discovers, benchmarks, and ranks scientific software repositories on GitHub** using a combination of metadata analysis, environment testing, and performance benchmarking.

## 🚀 Project Motivation
Thousands of scientific software repositories exist on GitHub, but it is often unclear:
- Which tools are actually usable?
- Which repositories are actively maintained?
- Which tools can run successfully in real environments?

## 🧠 What This Project Does
1. Repository discovery using GitHub metadata  
2. Environment generation and dependency installation  
3. Automated benchmarking and testing  
4. Composite quality scoring and ranking  

## 🏗️ Project Structure
scitoolhub/
├── src/  
├── data/  
├── analysis_out/  
├── scored_out_v2/  
├── mcp_bundle/  
└── final_report.md  

## 🛠️ Tech Stack
Python, Pandas, NumPy, GitHub API, automation scripting

## ▶️ How to Run
pip install -r mcp_bundle/requirements.txt  
python src/pipeline.py

## 👤 Author
Chengjun Wu – University of Wisconsin–Madison
