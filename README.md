# Jarvis Codex Agent Document Suite

This pack was generated from the latest uploaded `Jarvis.zip` GitHub export. It is intended to be copied into, or used alongside, the Jarvis GitHub repository before linking the repository to a Codex agent.

## Latest export audit summary

- Repository package folder: `Jarvis/`
- Main bot file: `main.py`
- Main bot file size: 827,206 bytes / 23,771 lines
- SQLite seed database: `marvel_rivals_stats.db` (21.4 MB)
- Detected Discord commands: 57
- Python compile: passed
- SQLite integrity check: `ok`
- Current bundled DB season: Season 7
- Season windows in bundled DB: 4 rows, no internal overlaps detected

## How to use this pack

1. Read `docs/CODEX_AGENT_ROLE.md` and paste the role section into the Codex agent setup prompt.
2. Copy `AGENTS.md` into the root of the Jarvis GitHub repository.
3. Copy the `docs/`, `scripts/`, and `.github/workflows/` folders into the repository.
4. Commit these documents on a documentation branch first.
5. Link the GitHub repository to Codex.
6. Ask Codex to inspect the repository and run `scripts/jarvis_offline_smoke.py` before making code changes.

## Core rule

Codex must never test against the live Railway SQLite volume. All tests must use a copied fixture database.
