# Codex Task Prompts

## 1. First repository audit

```text
Inspect the Jarvis repository without making changes. Read AGENTS.md, README_RAILWAY_SETUP.md, MANIFEST.txt, CHECKLIST.md, requirements.txt, railway.toml, env.example, main.py, and all docs. Then provide:
1. repository structure summary;
2. detected command list;
3. database schema summary;
4. Railway deployment summary;
5. recommended first tests;
6. risks or decisions needing owner approval.
Do not write code yet.
```

## 2. Implement a command update

```text
Implement the requested update to [command name]. Use the current SQLite seed DB as a fixture only. Preserve existing command aliases. Add or update tests/scripts if useful. Generate sample output before and after the change. Run the mandatory smoke checks. Open a PR with evidence.
```

## 3. Add a new stat image

```text
Add a new Jarvis stat image for [description]. Reuse existing visual style where practical. Query current-season data unless otherwise specified. Generate an offline sample image from the copied DB fixture and confirm it opens successfully. Do not change unrelated commands.
```

## 4. Season setup/update

```text
Review current season settings and mr_season_windows. Confirm whether the repo seed DB and live Railway DB differ. Prepare a safe season-window update plan with SQL and Discord command alternatives. Do not apply destructive changes without approval.
```

## 5. Railway deployment review

```text
Review this PR for Railway safety. Check start command, requirements, env var changes, SQLite volume assumptions, background task behaviour, and rollback path. Provide a concise deployment approval checklist.
```
