# Testing Protocol

## Normal development model: Option A

Normal Codex development uses the GitHub-bundled database snapshot for offline regression testing. The snapshot is suitable for compile checks, schema and query checks, smoke tests, and sample-output generation.

It is not current production data. The Railway persistent volume remains the source of truth for current live statistics.

## Mandatory checks

Run from the repository root:

```bash
python -S -m py_compile main.py
python scripts/inspect_jarvis_db.py
python scripts/jarvis_offline_smoke.py
python scripts/generate_db_sample_outputs.py
python scripts/generate_image_readability_samples.py
```

The database scripts copy their input into `.tmp` and open the copy read-only.

When dependencies can be installed, also run:

```bash
python -m pip install -r requirements.txt
python -m pip check
```

## Prohibited test targets

- `/data/marvel_rivals_stats.db`
- the live Railway service or volume
- live Discord
- production secrets
- live Marvel Rivals API calls unless a separately approved test explicitly requires them

## Current-stat validation

Current-stat validation is not required for normal pull requests. When it is specifically required, use:

- an owner-approved copied Railway database export; or
- a staging Railway service.

Never use the live production database. Treat exports as sensitive, keep them out of Git, and run tests against another disposable copy.

## Change-specific evidence

### Database and statistics changes

- integrity, quick, and foreign-key checks;
- relevant row-count invariants;
- current-snapshot-season filtering;
- active/inactive roster filtering;
- before/after snapshot regression output.

### API import changes

- stored `mr_match_json_raw` fixtures where possible;
- import deduplication;
- draw and skipped-match handling;
- no surprise cache refreshes or network calls.

### Image changes

- non-empty generated files;
- successful Pillow-open validation;
- readable columns and labels;
- sample image evidence.

The image readability generator uses representative data with the real image
renderers, writes only under `.tmp/`, and opens every generated PNG with Pillow.

## PR evidence

Every `main.py` PR should list files changed, commands run, results, snapshot limitations, migration impact, Railway impact, and owner-operated post-deployment checks.
