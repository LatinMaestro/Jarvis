# Change Request Template

Use this when asking Codex to update Jarvis.

```text
You are the Jarvis Marvel Rivals Discord Bot Codex agent.

Before writing code, read AGENTS.md and the docs folder, then inspect main.py and the database schema.

Task:
[Describe the requested bot change]

Acceptance criteria:
- [Expected command or behaviour]
- [Expected sample output or image]
- [Season/database scope]
- [No breaking change to existing commands unless approved]

Testing required:
- Run python -S -m py_compile main.py
- Run scripts/jarvis_offline_smoke.py against a copied DB fixture
- Generate before/after sample output for affected command(s)
- Summarise test evidence in the PR

Constraints:
- Do not use live Railway DB for tests
- Do not commit secrets
- Keep changes small and reviewable
- Open a PR; do not merge automatically
```
