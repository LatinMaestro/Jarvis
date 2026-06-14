# Testing Protocol

## Mandatory checks before opening a PR

Run these from the repository root:

```bash
python -S -m py_compile main.py
python scripts/jarvis_offline_smoke.py --repo-root . --db marvel_rivals_stats.db
python scripts/generate_db_sample_outputs.py --db marvel_rivals_stats.db --out .tmp/sample_outputs.md
```

If the change affects command output, also run a targeted before/after sample against a copied DB fixture.

## Standard safe test setup

```bash
mkdir -p .tmp
cp marvel_rivals_stats.db .tmp/test-marvel_rivals_stats.db
export MR_DB_PATH=.tmp/test-marvel_rivals_stats.db
export MR_DB_SEED_PATH=marvel_rivals_stats.db
export DISCORD_BOT_TOKEN=dummy_not_used_for_offline_tests
export MR_API_KEY=dummy_not_used_for_offline_tests
python -S -m py_compile main.py
python scripts/jarvis_offline_smoke.py --repo-root . --db .tmp/test-marvel_rivals_stats.db
```

## What must be tested by change type

### Database/stat command changes

- SQLite integrity check.
- Row counts before and after, where relevant.
- Sample output for affected command.
- Check current season filtering.
- Check that disabled roster players are not accidentally included where active roster only is intended.

### API import changes

- Do not hit the API in CI unless explicitly configured.
- Use stored `mr_match_json_raw` rows for offline import/regression tests when possible.
- Confirm import dedupe via `match_imports`.
- Confirm draw/skipped-match handling.
- Confirm no surprise hero-cache refresh calls from normal stat commands.

### Image-output command changes

- Confirm the command generates a non-empty file.
- Confirm the output file can be opened by Pillow.
- Confirm table columns remain legible.
- Include a generated example or screenshot in the PR where possible.

### Railway/deployment changes

- Confirm `railway.toml` start command remains valid.
- Confirm `requirements.txt` has only needed dependencies.
- Confirm env vars are documented in `env.example` and `README_RAILWAY_SETUP.md`.
- Explain rollback steps.

## PR evidence required

Every PR should include:

- Summary of change.
- Files changed.
- Tests run.
- Sample outputs generated.
- Any database migration impact.
- Railway deployment impact.
- Manual Discord commands the owner should test after deployment.
