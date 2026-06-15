# Web Architecture Options

## Recommended direction

Build the website as a separate private web frontend while keeping the Discord bot on Railway. Add a read-only web API only when the frontend needs shared query behavior or current-stat access through an owner-approved staging/export path.

Do not point development tools or Codex directly at the live Railway production database.

## Option 1: Separate private web frontend

In this model, the Discord bot remains unchanged and the website is a separate app.

Recommended early use:

- static or server-rendered private pages;
- local development against copied snapshot fixtures;
- no write access to league data;
- no dependency on live Discord or Railway production secrets.

Benefits:

- lowest risk to the existing bot;
- easiest to review in small PRs;
- allows UI iteration using historical data;
- keeps live stats protected.

Tradeoffs:

- snapshot data cannot prove current live statistics;
- duplicated query logic may appear until a shared read layer exists.

## Option 2: Add a read-only web API

In this model, a small API exposes league views for the web frontend. The API should be read-only at first.

Allowed data sources for development:

- copied GitHub snapshot fixtures;
- copied Railway DB export supplied by the owner and handled as sensitive data;
- staging Railway service, if explicitly approved.

Disallowed data sources for Codex work:

- `/data/marvel_rivals_stats.db`;
- live Railway production volume;
- direct live production database connections;
- live Discord.

Benefits:

- centralizes SQL and derived stats;
- helps preserve bot and website consistency;
- creates a clean boundary for future auth, caching, and testing.

Tradeoffs:

- introduces another service surface;
- requires strict access controls before any current-stat path is used;
- still must avoid direct writes to the production database.

## Option 3: Later migration from SQLite to Postgres

SQLite can remain appropriate while the live bot is the only writer and the website is read-only or fixture-based. A later Postgres migration may be useful if the platform needs:

- concurrent web and bot writes;
- richer admin tooling;
- multiple runtime instances;
- stronger backup and restore workflows;
- reporting replicas;
- managed credentials and network access controls.

Migration requirements:

- explicit owner approval;
- documented rollback plan;
- schema migration plan;
- staged rehearsal against copied data;
- no Codex direct modification of the live production database.

## Protecting the Railway database

The live Railway persistent volume database is the source of truth for current live stats. Future web architecture must keep that database protected by default:

- no local development against the live volume;
- no automated tests against the live volume;
- no direct Codex reads, writes, migrations, resets, or overwrites;
- no production secrets in GitHub;
- no write-enabled web API until separately approved and reviewed.

If current-stat validation is required, use a copied Railway DB export or staging Railway service. Treat exports as sensitive data and keep them out of Git.

## Suggested near-term architecture

Phase 1 should use:

- existing bot unchanged on Railway;
- future web code in GitHub behind PR review;
- local/offline fixture database copied from the GitHub snapshot;
- generated sample data and screenshots from snapshot fixtures;
- no live production connections.

Phase 2 can introduce a read-only API layer if it reduces duplication or improves testability.

Phase 3 can evaluate Postgres only if product requirements justify the operational cost.

