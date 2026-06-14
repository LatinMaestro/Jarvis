#!/usr/bin/env bash
set -euo pipefail
mkdir -p .tmp
cp marvel_rivals_stats.db .tmp/test-marvel_rivals_stats.db
python -S -m py_compile main.py
python scripts/jarvis_offline_smoke.py --repo-root . --db .tmp/test-marvel_rivals_stats.db
python scripts/generate_db_sample_outputs.py --db .tmp/test-marvel_rivals_stats.db --out .tmp/sample_outputs.md
