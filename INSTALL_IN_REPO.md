# Installation Guide for the Codex Control Files

These files define the safe operating model for Codex-assisted Jarvis development. They do not replace the bot or Railway.

## Repository paths

Keep these paths in the Jarvis GitHub repository:

```text
AGENTS.md
docs/
scripts/
.github/workflows/jarvis-ci.yml
sample_outputs_from_uploaded_db.md
```

The workflow must be under `.github/workflows/`; a root-level `jarvis-ci.yml` is not discovered by GitHub Actions.

## Database meaning

`marvel_rivals_stats.db` in GitHub is a historical offline regression fixture. The Railway persistent volume database remains the source of truth for current live statistics.

## Do not copy

Do not commit `.tmp/`, generated test databases, Railway exports, real `.env` files, or production credentials.
