# Jarvis Codex Agent Document Suite

This repository includes the operating guidance and offline test harness for Codex-assisted development of the Jarvis Marvel Rivals Discord bot.

## Operating model

- GitHub is the source of truth for code and review history.
- Railway runs the live bot.
- Railway's persistent volume database owns current live statistics.
- The database committed to GitHub is a historical snapshot for offline regression checks only.
- Codex does not access live Discord or directly access or modify the Railway production database.

## Normal development

Use the GitHub snapshot database for compile checks, schema and query checks, offline smoke tests, and sample-output regression evidence. The scripts copy the snapshot into `.tmp` before opening it.

Run:

```bash
python -S -m py_compile main.py
python scripts/inspect_jarvis_db.py
python scripts/jarvis_offline_smoke.py
python scripts/generate_db_sample_outputs.py
```

Generated outputs describe the bundled snapshot, not current live stats.

## Current-stat validation

When current production-state validation is genuinely required, use an owner-approved copied Railway database export or a staging Railway service. Never test against or modify the live production database.
