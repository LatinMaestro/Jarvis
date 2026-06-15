# Codex Task Prompts

## Repository audit

```text
Inspect Jarvis without making changes. Read all guidance and scripts. Report code structure, offline snapshot schema, Railway deployment model, test readiness, and risks. Clearly distinguish snapshot facts from current live statistics.
```

## Command update

```text
Implement the requested command update using copied GitHub snapshot fixtures for offline regression only. Preserve aliases, run all mandatory checks, generate clearly labeled before/after evidence, and open a PR. Do not access Railway or live Discord.
```

## Image update

```text
Implement the requested image output. Use a copied snapshot fixture, confirm the image is non-empty and opens with Pillow, and include regression evidence. Do not claim it represents current live statistics.
```

## Season review

```text
Review snapshot season data only as historical regression information. Do not infer current production state. Current-stat validation requires an owner-approved copied Railway export or staging service. Do not access or modify the live Railway database.
```

## Railway safety review

```text
Review the PR for start-command, environment-variable, SQLite single-instance, secret-handling, and rollback risks. Do not access Railway or production data.
```
