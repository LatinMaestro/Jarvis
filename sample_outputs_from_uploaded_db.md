# Jarvis snapshot regression outputs

Generated offline from the GitHub-bundled `marvel_rivals_stats.db` snapshot. These outputs are regression evidence only and are not proof of current live Railway statistics.

Snapshot source: `marvel_rivals_stats.db`

Integrity check: `ok`

Snapshot current season: `7`

## Tables

| Table | Rows |
| --- | --- |
| bot_settings | 1 |
| game_stats | 3356 |
| hero_bans | 2743 |
| hero_cache | 51 |
| hero_time_stats | 6683 |
| hero_time_stats_all | 13444 |
| match_imports | 480 |
| mr_auto_import_scan_state | 19 |
| mr_ban_picks | 2764 |
| mr_bot_settings | 6 |
| mr_hero_segments | 13444 |
| mr_match_json_humans | 480 |
| mr_match_json_raw | 480 |
| mr_match_meta | 480 |
| mr_player_badges | 5180 |
| mr_player_match | 5760 |
| mr_players | 1749 |
| mr_roster | 16 |
| mr_season_windows | 4 |
| mr_skipped_matches | 8 |
| seasons | 3 |
| session_state | 2 |
| streaks | 37 |

## Season windows

| Season | Start Brisbane | End Brisbane | Note |
| --- | --- | --- | --- |
| 4 | 13 Sep 2025 00:00:00 AEST | 14 Nov 2025 23:59:59 AEST |  |
| 5 | 15 Nov 2025 00:00:00 AEST | 16 Jan 2026 23:59:59 AEST |  |
| 6 | 17 Jan 2026 00:00:00 AEST | 20 Mar 2026 23:59:59 AEST |  |
| 7 | 21 Mar 2026 00:00:00 AEST | 22 May 2026 23:59:59 AEST |  |

## Leaderboard sample

| Player | Games | Wins | Losses | WR % | Kills | Deaths | Assists | K/D |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Rhyscomes69 | 86 | 54 | 32 | 62.8 | 2384 | 669 | 919 | 3.56 |
| Nev Pounder | 77 | 53 | 24 | 68.8 | 2328 | 487 | 888 | 4.78 |
| Nev_blade7 | 92 | 45 | 47 | 48.9 | 2684 | 758 | 1437 | 3.54 |
| NevSONIC | 88 | 37 | 51 | 42.0 | 2023 | 802 | 1146 | 2.52 |
| xX_Harold_Xx | 71 | 34 | 37 | 47.9 | 2054 | 591 | 869 | 3.48 |
| Texonidas | 54 | 28 | 26 | 51.9 | 1574 | 422 | 324 | 3.73 |
| LatinMaestro | 55 | 26 | 29 | 47.3 | 1595 | 481 | 662 | 3.32 |
| Fandangleberry | 38 | 20 | 18 | 52.6 | 1232 | 279 | 581 | 4.42 |
| barber_sturgeo | 66 | 19 | 47 | 28.8 | 1750 | 555 | 842 | 3.15 |
| Quake_ | 26 | 18 | 8 | 69.2 | 690 | 172 | 365 | 4.01 |
| Nev Masher | 6 | 2 | 4 | 33.3 | 182 | 44 | 54 | 4.14 |

## Roster sample

| UID | Player | Enabled |
| --- | --- | --- |
| 1025623593 | barber_sturgeo | 1 |
| 2092848953 | Fandangleberry | 1 |
| 1064511620 | LatinMaestro | 1 |
| 96894221 | Nev Pounder | 1 |
| 120747082 | Nev_blade7 | 1 |
| 1673102382 | NevSONIC | 1 |
| 640498765 | Quake_. | 1 |
| 1188003396 | Rhyscomes69 | 1 |
| 1497128877 | Texonidas | 1 |
| 903452137 | xX_Harold_Xx | 1 |
| 1843671901 | AncientChunk | 0 |
| 2025958864 | Andrecinho10 | 0 |
| 1410682561 | bLindDisc | 0 |
| 1819906712 | Hayd4n | 0 |
| 1104357900 | Nuffman | 0 |
| 1189601753 | Nuffmans | 0 |

## Hero role summary

| Role | Heroes |
| --- | --- |
| Duelist | 26 |
| Strategist | 12 |
| Vanguard | 13 |

## Commands detected in `main.py`

| Command | Aliases | Function |
| --- | --- | --- |
| !backfill_hero_dht | !mr_backfill_hero_dht | backfill_hero_dht_cmd |
| !season |  | season |
| !set_season |  | set_season |
| !list_seasons |  | list_seasons |
| !reset_season |  | reset_season |
| !browse_games |  | browse_games |
| !refresh_heroes | !refresh_heros, !refresh_hero_cache, !refreshheroes | refresh_heroes_cmd |
| !hero_roles_check |  | hero_roles_check |
| !hero_role_set |  | hero_role_set |
| !auto_import_status |  | auto_import_status |
| !skipped_draws | !skipped_draw_games, !draw_skips, !skipped_games_draws, !skippinggames_draws | skipped_draws_cmd |
| !auto_import_on |  | auto_import_on |
| !auto_import_off |  | auto_import_off |
| !auto_import_cutoff |  | auto_import_cutoff_cmd |
| !season_window_set |  | season_window_set_cmd |
| !season_windows |  | season_windows_cmd |
| !roster_add |  | roster_add |
| !roster_remove |  | roster_remove |
| !roster_list |  | roster_list |
| !roster_update_all |  | roster_update_all |
| !auto_import_run |  | auto_import_run |
| !auto_import_debug |  | auto_import_debug |
| !match_history_probe |  | match_history_probe |
| !submit_match |  | submit_match |
| !hero_time |  | hero_time |
| !player_heros | !player_heroes | player_heros |
| !hero_bans |  | hero_bans |
| !player_bans |  | player_bans |
| !top3_stack | !elite_stack, !two_plus_top3 | top3_stack |
| !hero_tierlist |  | hero_tierlist |
| !hero_synergy |  | hero_synergy |
| !edit_game |  | edit_game |
| !undo_last_game |  | undo_last_game |
| !delete_game |  | delete_game |
| !undelete_match |  | undelete_match |
| !mr_cleanup_orphans |  | mr_cleanup_orphans |
| !session_overview |  | session_overview |
| !season_overviews |  | season_overviews |
| !leaderboard_image |  | leaderboard_image |
| !teammate_matrix_fair |  | teammate_matrix_fair |
| !teammate_matrix_lowteam_fair | !teammate_matrix_low_team_fair | teammate_matrix_lowteam_fair |
| !win_matrix |  | win_matrix |
| !2v2_records |  | two_v_two_records |
| !profile |  | profile |
| !role_winrates | !role_wr, !player_role_wr | role_winrates |
| !h2h | !head2head, !head_to_head | head_to_head_cmd |
| !low_team |  | low_team |
| !season_story |  | season_story |
| !role_distribution |  | role_distribution |
| !season_movie_pack |  | season_movie_pack |
| !run_all_stats |  | run_all_stats |
| !pregame |  | pregame |
| !session_start |  | session_start_cmd |
| !session_players |  | session_players |
| !next_teams |  | next_teams |
| !fairness_debug |  | fairness_debug |
| !helpme | !helper, !commands, !help_cmds | helpme |

