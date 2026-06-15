# Change Request Template

```text
You are the Jarvis Marvel Rivals Discord Bot Codex agent.

Before editing, read AGENTS.md, all docs, all scripts, and inspect the relevant code and snapshot schema.

Task:
[Describe the requested change]

Acceptance criteria:
- [Expected behavior]
- [Expected snapshot regression output or image]
- [Database/season scope]
- [No breaking command change unless approved]

Testing:
- python -S -m py_compile main.py
- python scripts/inspect_jarvis_db.py
- python scripts/jarvis_offline_smoke.py
- python scripts/generate_db_sample_outputs.py

Constraints:
- Use copied offline fixtures only
- Do not access or modify the live Railway database
- Do not connect to live Discord
- Do not present snapshot output as current live statistics
- Do not commit secrets
- Open a PR; do not merge automatically
```
