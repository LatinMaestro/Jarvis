# Web UI Mockups

These mockups are text-only planning sketches for a future private website. They are not an implementation contract and do not authorize a production web app.

## Global layout

```text
+--------------------------------------------------------------+
| Jarvis League                                                |
| Dashboard | Seasons | Players | Heroes | Matches | Teams     |
| Sessions  | Pregame | Admin                                    |
+--------------------------------------------------------------+
| Data source: Offline GitHub snapshot regression fixture       |
+--------------------------------------------------------------+
| Page content                                                  |
+--------------------------------------------------------------+
```

The data source banner should be visible in local and staging builds so reviewers know whether they are looking at snapshot data or owner-approved current-stat validation.

## Dashboard

```text
+--------------------------------------------------------------+
| Dashboard                                      Season: S3 v   |
+--------------------------------------------------------------+
| League Summary                                               |
| Games: 128    Players: 14    Heroes used: 31    Maps: 9      |
+--------------------------+-----------------------------------+
| Top Players              | Recent Matches                    |
| 1. Player A   62% WR     | 2026-06-01  Team 1 def Team 2     |
| 2. Player B   58% WR     | 2026-06-01  Team 2 def Team 1     |
| 3. Player C   55% WR     | 2026-05-30  Team 1 def Team 2     |
+--------------------------+-----------------------------------+
| Hero Highlights          | Role Balance                      |
| Most picked: Hero X      | Vanguard: balanced               |
| Most banned: Hero Y      | Duelist: high variance           |
| Best WR: Hero Z          | Strategist: needs review         |
+--------------------------------------------------------------+
```

## Player profile

```text
+--------------------------------------------------------------+
| Player: Player A                             Season: All v    |
+--------------------------------------------------------------+
| Record: 42-26    Win Rate: 61.8%    Streak: W3               |
+--------------------------+-----------------------------------+
| Favorite Heroes          | Role Distribution                 |
| Hero X  18 games  67%    | Vanguard   ########  40%         |
| Hero Y  14 games  57%    | Duelist    #####     25%         |
| Hero Z  11 games  64%    | Strategist #######   35%         |
+--------------------------+-----------------------------------+
| Recent Matches                                                |
| Date        Result   Map        Team Notes                    |
| 2026-06-01  Win      Map A      with Player B, Player C       |
| 2026-05-30  Loss     Map B      vs Player D                   |
+--------------------------------------------------------------+
```

## Season detail

```text
+--------------------------------------------------------------+
| Season: Season 3                                             |
| Window: 2026-05-01 through 2026-06-30                         |
+--------------------------------------------------------------+
| Summary Cards                                                |
| Games | Active Players | Top Hero | Most Banned | Close Games |
+--------------------------------------------------------------+
| Leaderboard Preview                                          |
| Rank | Player | Games | W-L | WR | Primary Role               |
+--------------------------------------------------------------+
| Story Notes                                                  |
| - Biggest climber                                            |
| - Most common matchup                                        |
| - Notable hero trends                                        |
+--------------------------------------------------------------+
```

## Match history

```text
+--------------------------------------------------------------+
| Matches                                                      |
| Filters: Season [All] Player [Any] Hero [Any] Result [Any]   |
+--------------------------------------------------------------+
| Date       Season  Map    Winner    Players                  |
| 2026-06-01 S3      Map A  Team 1    A, B, C vs D, E, F       |
| 2026-05-30 S3      Map B  Team 2    A, D, E vs B, C, F       |
+--------------------------------------------------------------+
```

## Team generator

```text
+--------------------------------------------------------------+
| Team Generator                                               |
| Players: A, B, C, D, E, F                                    |
| Mode: Balanced    Season: Current selected data source        |
+--------------------------+-----------------------------------+
| Team 1                   | Team 2                            |
| Player A  Vanguard       | Player D  Vanguard                |
| Player B  Duelist        | Player E  Duelist                 |
| Player C  Strategist     | Player F  Strategist              |
+--------------------------+-----------------------------------+
| Fairness Notes                                                |
| Estimated gap: 2.3 points                                    |
| Role distribution: balanced                                  |
| Rematch risk: low                                            |
+--------------------------------------------------------------+
```

## Pregame

```text
+--------------------------------------------------------------+
| Pregame Preview                                              |
| Match: Team 1 vs Team 2                                      |
+--------------------------+-----------------------------------+
| Key Head-to-Head          | Hero/Ban Context                  |
| A vs D: 6-4               | Hero X frequently banned          |
| B vs E: 3-5               | Hero Y high win rate              |
+--------------------------+-----------------------------------+
| Role Distribution                                             |
| Team 1: 1 Vanguard, 1 Duelist, 1 Strategist                  |
| Team 2: 1 Vanguard, 1 Duelist, 1 Strategist                  |
+--------------------------------------------------------------+
```

## First-version design notes

- Prefer readable tables over dense single-image outputs.
- Keep dark-theme styling aligned with current Jarvis visual identity.
- Use clear source labels for snapshot, export, staging, and future production views.
- Start with read-only pages.
- Treat team generation and session tools as previews until write workflows are explicitly approved.

