# PR Review Checklist

## Required review

- [ ] The PR summary clearly explains the change.
- [ ] No secrets, `.env` files, production exports, or generated test databases are included.
- [ ] Railway settings and live Discord were not touched unless separately approved.
- [ ] The live Railway production database was not accessed or modified.
- [ ] Snapshot outputs are labeled as offline regression evidence, not current live statistics.
- [ ] Database migrations, if any, were tested only against disposable copied fixtures.
- [ ] Rollback and owner-operated post-deployment checks are documented where relevant.

## PRs modifying `main.py`

- [ ] `python -S -m py_compile main.py` passed.
- [ ] `python scripts/inspect_jarvis_db.py` passed.
- [ ] `python scripts/jarvis_offline_smoke.py` passed.
- [ ] `python scripts/generate_db_sample_outputs.py` passed.
- [ ] Relevant before/after snapshot regression output is included.
- [ ] Image changes include non-empty, readable image evidence.

Current live Railway DB access is not required for a normal code PR.

## After deployment

Any live Discord smoke testing is performed by the owner or an explicitly authorized operator, not by automated Codex tests.
