# Web Codex Agent Guide

## Role

For future web-platform work, Codex acts as a documentation-first, safety-first implementation agent. The goal is to evolve Jarvis carefully while protecting the existing Discord bot and production data.

## Required reading before web changes

Before editing future web code, read:

- `AGENTS.md`
- `README.md`
- `README_RAILWAY_SETUP.md`
- `docs/BOT_ARCHITECTURE.md`
- `docs/DATABASE_GUIDE.md`
- `docs/TESTING_PROTOCOL.md`
- `docs/SAMPLE_OUTPUT_PROTOCOL.md`
- `docs/SECURITY_AND_SECRETS.md`
- `docs/PR_REVIEW_CHECKLIST.md`
- this web documentation set
- relevant scripts and source files

## Non-negotiable boundaries

Do not:

- access Railway;
- connect to live Discord;
- read or modify the live production database;
- test against `/data/marvel_rivals_stats.db`;
- commit secrets or real `.env` files;
- commit Railway exports;
- describe the GitHub snapshot database as current production data;
- change bot command behavior unless the task explicitly approves it;
- change season windows unless the owner explicitly approves it.

## Normal development data model

Use Option A for normal work:

- compile `main.py`;
- inspect the copied GitHub snapshot database;
- run offline smoke checks;
- generate snapshot-based sample outputs;
- use temporary copied fixture databases wherever practical.

If current-stat validation is required, ask the owner for a copied Railway DB export or a staging Railway service. Codex must still not access or modify the live production database directly.

## Web PR expectations

Every future web PR should state:

- files changed;
- whether `main.py` changed;
- whether `marvel_rivals_stats.db` changed;
- whether `railway.toml` or `.env.example` changed;
- data source used for tests;
- Railway, Discord, secret, production data, and live database impact;
- test commands run and results;
- screenshots or sample outputs for user-facing UI work;
- remaining risks and owner decisions.

## Required checks

For any PR that touches shared bot code, run:

```bash
python -S -m py_compile main.py
python scripts/inspect_jarvis_db.py
python scripts/jarvis_offline_smoke.py
python scripts/generate_db_sample_outputs.py
```

For future web code, also run the web project's own checks once they exist, such as:

```bash
npm run lint
npm test
npm run build
```

Use only the checks that are available in the repository at the time.

## Implementation guidance

- Start read-only.
- Prefer small PRs.
- Keep the Discord bot stable.
- Preserve existing command semantics.
- Add shared query helpers only when they reduce real duplication.
- Keep fixture handling explicit and temporary.
- Label snapshot-backed outputs clearly.
- Include screenshots or text mockups for UI changes.
- Do not deploy without explicit owner approval.

