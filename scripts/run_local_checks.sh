#!/usr/bin/env bash
set -euo pipefail
python -S -m py_compile main.py
python scripts/inspect_jarvis_db.py
python scripts/jarvis_offline_smoke.py
python scripts/generate_db_sample_outputs.py
if python -c "import aiohttp, discord, pandas, PIL" >/dev/null 2>&1; then
  python -m pip check
else
  echo "Dependency imports unavailable; run: python -m pip install -r requirements.txt"
fi
