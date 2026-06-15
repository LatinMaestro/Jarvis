# Web Security and Access

## Baseline rule

The future website must be private by default. League data should not become public just because it is easier to browse on the web.

## Protected systems

Codex and ordinary development workflows must not access:

- live Railway production database files;
- `/data/marvel_rivals_stats.db`;
- live Discord;
- production secrets;
- Railway credentials;
- Discord tokens;
- Marvel Rivals API keys;
- owner-provided sensitive exports unless explicitly scoped and excluded from Git.

## Data source labels

Every future web environment should clearly label its data source:

- `Offline snapshot`: GitHub-bundled database copied to a temporary fixture.
- `Copied export`: owner-provided Railway export, handled as sensitive data.
- `Staging`: owner-approved staging service.
- `Production`: owner-approved private production web runtime.

Snapshot-backed pages must not claim to represent current live stats.

## Access model

Recommended future access tiers:

- Viewer: can browse stats, profiles, matches, leaderboards, seasons, and hero pages.
- Session host: can use team generation, pregame, and session preview tools.
- Owner/admin: can manage approved settings if admin features are ever built.

Early phases should implement read-only viewer behavior first.

## Authentication

Authentication provider selection is an open decision. Any future implementation should:

- require private sign-in;
- avoid hardcoded credentials;
- store secrets only in approved secret stores;
- prevent public indexing;
- log access-relevant events without exposing secrets;
- include a local development mode that does not require production credentials.

## API safety

The first API should be read-only if one is needed.

API requirements:

- no production write endpoints by default;
- explicit allowlist of read operations;
- parameter validation for filters and IDs;
- rate limiting if exposed beyond localhost;
- no SQL string construction from untrusted input without safe binding;
- clear separation between fixture, staging, and production data sources.

## Database protection

The live Railway persistent volume database remains protected:

- no Codex direct reads;
- no Codex direct writes;
- no automated tests against it;
- no local migrations against it;
- no overwrite, reset, or import operations against it.

If current-stat validation is needed, the owner must provide a copied export or staging Railway service. Copied exports are sensitive and must not be committed.

## Secrets and local files

Never commit:

- `.env`;
- Railway exports;
- temporary copied databases;
- credentials;
- tokens;
- screenshots containing secrets;
- production logs with private tokens or connection strings.

Use `.env.example` only for example variable names if a future PR explicitly needs them.

## Open security decisions

- Which authentication provider should be used?
- Should any web feature ever write to league data?
- Should admin features exist on the website or remain Discord/owner-operated?
- How should staging data be refreshed and expired?
- What audit logging is required for private league access?

