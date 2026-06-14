# Installation Guide for This Document Suite

This document suite is not a replacement for the Jarvis bot. It is a setup/control layer for Codex-assisted development.

## Copy into repository

Copy these paths into the root of the Jarvis GitHub repository:

```text
AGENTS.md
docs/
scripts/
.github/workflows/jarvis-ci.yml
```

Keep `sample_outputs_from_uploaded_db.md` as evidence or place it under `docs/evidence/` if preferred.

## Recommended first commit message

```text
docs: add Codex agent operating guide and offline test protocol
```

## Do not copy

Do not copy any local `.tmp` folders, generated test databases, or real `.env` files.
