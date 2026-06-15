# Web Feature Map

## Principle

The website should preserve the meaning of existing Jarvis bot outputs while presenting them in browsable pages. A web feature may reorganize information for readability, but it should not silently change league calculations, season windows, command names, or data definitions.

## Existing bot functions to preserve

| Bot capability | Future web feature | Notes |
| --- | --- | --- |
| Stats dashboards | League dashboard and season dashboard | Show all-time and selected-season summaries. |
| Season history | Seasons index and season detail pages | Preserve season names, windows, and historical context. |
| Player profiles | Player profile pages | Include wins, losses, win rate, heroes, roles, teammates, and recent history. |
| Hero stats | Hero explorer and hero detail pages | Include hero usage, win rates, roles, and player breakdowns. |
| Bans | Ban dashboard | Support hero bans, player bans, trends, and season filters. |
| Head-to-head | Head-to-head comparison page | Compare two players across seasons and match history. |
| Leaderboard | Leaderboard page | Keep current leaderboard semantics and filters. |
| Team generation | Team generator page | Present generated teams, fairness notes, and constraints clearly. |
| Session/fairness tools | Session dashboard | Show session players, generated teams, fairness debug, and low-team balancing views. |
| Pregame output | Pregame page | Render matchup, player context, and role/hero notes for the next game. |
| Role distribution | Role distribution page | Show player role tendencies and team role balance. |
| Match history | Match history and match detail pages | Browse matches with filters, teams, heroes, maps, and outcomes. |

## Suggested navigation

Primary navigation:

- Dashboard
- Seasons
- Players
- Heroes
- Matches
- Leaderboards
- Teams
- Sessions
- Pregame
- Admin

The Admin area should be owner-only if it is ever built. Early website work should focus on read-only league browsing.

## Page inventory

### Dashboard

Purpose: quick league overview.

Initial content:

- selected season summary;
- recent matches;
- top players;
- top heroes;
- role balance highlights;
- links to active session or pregame tools.

### Seasons

Purpose: browse league history by season.

Initial content:

- season list;
- season date windows;
- match counts;
- player participation;
- season leaderboard links;
- season story or highlights where available.

### Players

Purpose: browse individual player records.

Initial content:

- player search;
- player profile cards;
- season filter;
- win/loss record;
- hero pool;
- role tendencies;
- teammate and opponent context.

### Heroes

Purpose: browse hero performance and usage.

Initial content:

- hero list by role;
- win rate and usage;
- most played players;
- ban frequency;
- synergy links where supported.

### Matches

Purpose: inspect match history.

Initial content:

- filter by season, player, hero, map, result, and date;
- match detail page;
- soft-deleted or admin-only recovery data only if approved later.

### Leaderboards

Purpose: preserve current leaderboard output in a web-friendly table.

Initial content:

- all-time and season filters;
- sort controls;
- record, win rate, streaks, and games played;
- snapshot disclaimer in offline/dev builds.

### Teams

Purpose: support team generation workflows.

Initial content:

- player selector;
- generated team cards;
- role distribution;
- fairness explanation;
- low-team balancing mode if available.

### Sessions

Purpose: support live league night preparation without live Discord automation.

Initial content:

- session player list;
- overview cards;
- fairness debug output;
- generated team history;
- clear separation between preview and any future write action.

### Pregame

Purpose: make pregame output easier to read and review.

Initial content:

- selected players;
- likely role distribution;
- head-to-head notes;
- hero and ban context;
- generated preview that mirrors Discord meaning.

## Data accuracy rule

Every web page should state whether it is using:

- the GitHub snapshot database for offline regression; or
- an owner-approved copied export or staging source for current-stat validation.

The website must not imply that snapshot-backed outputs are current live stats.

