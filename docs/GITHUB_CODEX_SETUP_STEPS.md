# GitHub + Codex Setup Steps

## Step 1 — Prepare repository docs

1. Create a branch such as `docs/codex-agent-setup`.
2. Copy `AGENTS.md`, the `docs/` folder, the `scripts/` folder, and `.github/workflows/jarvis-ci.yml` into the Jarvis repo.
3. Commit and push the documentation branch.
4. Open a PR and merge once reviewed.

## Step 2 — Link GitHub repository to Codex

In ChatGPT/Codex, connect the Jarvis GitHub repository and allow Codex to inspect repository files. Use the role text from `docs/CODEX_AGENT_ROLE.md`.

## Step 3 — First Codex task

Use this first prompt:

```text
Inspect the Jarvis repository and read AGENTS.md and docs/*. Do not write code. Confirm the repository structure, current Railway deployment model, current DB status, command list, and first safe test commands.
```

## Step 4 — First safe test task

```text
Run the offline smoke checks against a copied DB fixture. Do not use the live Railway DB. Report the exact commands run and results.
```

## Step 5 — Normal development

For each bot update:

1. Create a branch.
2. Make the smallest safe code change.
3. Run smoke checks and command-specific sample outputs.
4. Open a PR with evidence.
5. Owner reviews sample outputs.
6. Merge to trigger Railway deploy.
7. Owner runs manual Discord smoke commands.
