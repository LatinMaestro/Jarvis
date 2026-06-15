# GitHub and Codex Setup Steps

## Repository setup

1. Keep `AGENTS.md`, `docs/`, `scripts/`, and the snapshot baseline in GitHub.
2. Keep CI at `.github/workflows/jarvis-ci.yml`.
3. Use branches and pull requests for reviewable changes.

## Ownership model

- GitHub is the source of truth for code.
- Railway is the live runtime.
- The Railway volume database is the source of truth for current live statistics.
- The GitHub database is a historical offline regression snapshot.

## First Codex task

Ask Codex to read all repository guidance and inspect the offline harness before editing.

## First safe checks

```bash
python -S -m py_compile main.py
python scripts/inspect_jarvis_db.py
python scripts/jarvis_offline_smoke.py
python scripts/generate_db_sample_outputs.py
```

These commands use copied snapshot fixtures. They do not require Railway, production secrets, or live Discord.

## Normal development

1. Create a branch.
2. Make the smallest safe change.
3. Run offline checks and command-specific regression outputs.
4. Open a PR with evidence.
5. The owner reviews and merges.
6. The owner or an authorized operator performs any live post-deployment checks.

Codex must not directly access or modify the live Railway database or connect automated tests to live Discord.
