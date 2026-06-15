# Web Delivery Plan

## Phase 0: Planning and inventory

Status: documentation only.

Goals:

- document product vision and safety boundaries;
- inventory bot features that should map to web pages;
- define architecture options;
- define testing and PR expectations.

Exit criteria:

- planning docs reviewed by the owner;
- no production systems touched;
- no website deployed.

## Phase 1: Offline read-only prototype

Goals:

- create a private local web prototype;
- use a temporary copied GitHub snapshot database only;
- build read-only pages for dashboard, players, seasons, matches, and leaderboards;
- include a visible data-source banner.

Testing expectations:

- compile existing `main.py`;
- run existing offline database inspection and smoke scripts;
- run future web lint, unit, and build checks;
- generate screenshots from snapshot data;
- verify no production secrets or data are required.

Exit criteria:

- owner can browse snapshot-backed pages locally;
- website clearly says snapshot outputs are offline regression data;
- no live Railway or Discord access.

## Phase 2: Shared read-only query layer

Goals:

- factor common read queries into a tested layer if duplication becomes risky;
- keep the Discord bot's command behavior unchanged;
- support the web app through read-only functions or API routes;
- preserve existing bot output semantics.

Testing expectations:

- bot offline checks still pass;
- web tests cover query outputs;
- sample data from the snapshot matches expected regression output;
- read-only boundaries are documented.

Exit criteria:

- bot and web pages share consistent calculations where practical;
- no write-enabled API exists without explicit approval.

## Phase 3: Private access and staging validation

Goals:

- add private authentication and access controls;
- validate with an owner-approved copied Railway DB export or staging Railway service if current-stat validation is required;
- continue to keep live production data protected.

Testing expectations:

- no direct live production DB access;
- sensitive copied exports excluded from Git;
- staging credentials stored only in approved secret stores;
- clear rollback and removal steps for staging data.

Exit criteria:

- owner-approved users can access private staging;
- current-stat validation path is documented and isolated.

## Phase 4: Production web deployment decision

Goals:

- decide whether and where to deploy the private web platform;
- document runtime, auth, data access, backup, and rollback plans;
- decide whether the web app remains read-only or needs approved write workflows.

Required owner decisions:

- hosting provider;
- authentication provider;
- current-stat data access path;
- allowed admin/write features;
- retention and privacy policy;
- monitoring and incident response expectations.

Exit criteria:

- production deployment is approved separately;
- bot runtime remains stable;
- live database protection plan is in place.

## Phase 5: Database evolution review

Goals:

- evaluate whether SQLite is still enough;
- consider Postgres only if product needs justify it;
- rehearse migrations against copied data.

Triggers for Postgres evaluation:

- multiple live writers;
- need for reporting replicas;
- richer admin dashboards;
- large match history growth;
- frequent concurrent web traffic;
- operational backup requirements beyond the current Railway volume model.

Exit criteria:

- owner approves or rejects migration with documented tradeoffs;
- no live migration is performed by Codex directly.

## General PR expectations

Future web PRs should include:

- files changed;
- data source used for testing;
- confirmation that Railway, Discord, secrets, production data, and the live database were not touched;
- screenshots or text sample output for user-facing pages;
- bot regression checks when shared code is affected;
- web-specific lint, unit, build, and accessibility checks when available;
- explicit note if outputs are based on the GitHub snapshot.

