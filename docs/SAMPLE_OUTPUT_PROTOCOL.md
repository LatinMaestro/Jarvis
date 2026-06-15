# Sample Output Protocol

## Purpose

User-facing command changes should include before/after regression output so the owner can review formatting and behavior before deployment.

## Data meaning

Default generated outputs come from a temporary copy of the GitHub-bundled database snapshot. They are:

- offline regression evidence;
- useful for stable query and formatting comparisons;
- not current live Discord output;
- not proof of current Railway statistics.

## Standard command

```bash
python scripts/generate_db_sample_outputs.py
```

The script copies the snapshot to `.tmp` and writes `.tmp/sample_outputs.md`.

For image-layout work, also run:

```bash
python scripts/generate_image_readability_samples.py
```

This writes representative PNGs under `.tmp/` and verifies them with Pillow.
They are readability regressions, not current-stat reports.

## Required evidence

For each changed command, provide:

1. Command name and example invocation.
2. Snapshot or fixture used.
3. Output text or image generated.
4. Known differences from Discord rendering.
5. For images, file path, size, and successful Pillow-open validation.

## Baseline

`sample_outputs_from_uploaded_db.md` is the committed snapshot regression baseline. Regenerate it after relevant query, parser, schema-fixture, or output changes:

```bash
python scripts/generate_db_sample_outputs.py --out sample_outputs_from_uploaded_db.md
```

## Current-stat validation

If current statistics must be validated, use an owner-approved copied Railway export or staging service. Never run the generator against the live production database.

Commands that rely on `ctx.send` should use a fake context. Automated tests must not connect to live Discord.
