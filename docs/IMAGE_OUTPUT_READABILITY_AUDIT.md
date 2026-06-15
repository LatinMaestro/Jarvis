# Jarvis Image Output Readability Audit

This audit covers image-producing commands in `main.py`. All checks use copied
offline fixtures. The bundled GitHub database remains a historical regression
snapshot and is not evidence of current live statistics.

## Direct Image Commands

| Command | Readability risk found | Improvement |
| --- | --- | --- |
| `!player_heros` / `!player_heroes` | 18 rows at 32 px spacing and a dense footer | Larger canvas and type, 44 px rows, 16-row page limit |
| `!player_bans` | Two tables compressed into a 980 px canvas | Taller canvas, 42 px rows and more section spacing |
| `!top3_stack` / `!elite_stack` / `!two_plus_top3` | 13 columns with 32 px rows caused strong Discord downscaling | Larger canvas, 42 px rows and more summary room |
| `!hero_tierlist` | 18 tightly packed rows per page | 15 rows per page, larger canvas and 44 px rows |
| `!hero_synergy` | Long pair labels and 32 px rows | 15 rows per page, larger canvas and 44 px rows |
| `!session_overview` | Eleven-column records table was the highest-risk layout | 27 px body text, 56 px rows, wider measured columns, larger headers and spacing |
| `!season_overviews` | Inherits session overview density | Uses the improved session renderers |
| `!leaderboard_image` | 45 px rows and 60 px headers were marginal for long tables | 54 px rows, 68 px headers and larger section bands |
| `!teammate_matrix_fair` | Small cells in a potentially wide matrix | 52 px rows, wider labels/cells and larger padding |
| `!teammate_matrix_lowteam_fair` | Small cells plus longer explanatory values | 52 px rows, wider labels/cells and larger padding |
| `!win_matrix` | Two text lines inside 58 px cells | 68 px cells, larger fonts and wider labels |
| `!2v2_records` | Compact 44 px rows and narrow padding | 54 px rows, 64 px headers and wider measured columns |
| `!profile` | 22 px body text and crowded hero performance columns | 2240x1540 canvas, 26 px body text, larger panels and corrected columns |
| `!role_winrates` / `!role_wr` / `!player_role_wr` | 34 px rows left little vertical separation | 44 px rows and larger global typography |
| `!h2h` / `!head2head` / `!head_to_head` | Narrow canvas and small footer text | 1420 px canvas, 28 px body text, 56 px rows and wider labels |
| `!low_team` | Compact table geometry | 54 px rows, 64 px headers and wider columns |
| `!season_story` | Dense two-column text and overlapping role labels | 2140x1640 canvas, 27 px body text, 35 px lines; large rosters plot all dots but label top-time players |
| `!role_distribution` | Fonts dropped to 12 px for large rosters | Larger canvas and a 16 px minimum label size |
| `!pregame` | Matrix, leaderboard, triangle and determinations inherited compact layouts | Increased table geometry, 1200x920 triangle and larger determination card |

## Image-Producing Wrappers

- `!run_all_stats` invokes existing image commands and has no unique renderer.
- `!auto_import_run` can invoke the stats workflow and has no unique renderer.

## Non-Image Commands Checked

- `!hero_bans` returns text, not an image.
- `!season_movie_pack` sends a Markdown file, not an image.

## Regression Evidence

The evidence uses representative labels rendered through the real `main.py`
functions while `MR_DB_PATH` points to a temporary copy of the bundled snapshot.

- Session overview: `1860x1142` before, `2226x1466` after.
- Profile dashboard: `2000x1300` before, `2240x1540` after.
- Head to head: `1200x1026` before, `1420x1176` after.
- Role distribution: `1850x900` before, `2100x1060` after.
- Season story: `1850x1380` before, `2140x1640` after.

Run `python scripts/generate_image_readability_samples.py` to generate and
Pillow-validate the current representative set under `.tmp/`.

## Remaining Risk

Very large rosters can still create extremely wide matrix images. The current
change improves cell readability without changing matrix meaning or splitting
the output. A future pass could add deterministic matrix pagination if roster
growth makes Discord downscaling excessive.
