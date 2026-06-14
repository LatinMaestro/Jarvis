# Sample Output Protocol

## Purpose

Every user-facing command change should produce sample output before merge so the owner can check behaviour before Railway deployment.

## Standard command-output evidence

Use the database sample script:

```bash
mkdir -p .tmp
cp marvel_rivals_stats.db .tmp/test-marvel_rivals_stats.db
python scripts/generate_db_sample_outputs.py --db .tmp/test-marvel_rivals_stats.db --out .tmp/sample_outputs.md
```

Attach or paste the relevant section in the PR.

## Requirements for output samples

For every changed command, provide:

1. Command name and example invocation.
2. Database/season used.
3. Output text or image file generated.
4. Any known difference from live Discord formatting.
5. If image output is generated, confirm file path and file size.

## Baseline sample file

This pack includes `sample_outputs_from_uploaded_db.md`, generated from the latest uploaded DB. Codex should regenerate it after any DB or command-output change.

## Discord-context testing

Commands that rely on `ctx.send` should be tested with a fake context that captures sent text, file attachments, embeds, and errors/exceptions.

Do not connect to the live Discord bot for automated testing.
