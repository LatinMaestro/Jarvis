-- Template only. Codex may test this only against a disposable copied fixture.
-- Any production season operation is owner-controlled and must not be run by Codex.
-- Brisbane local dates are represented as UTC boundaries.
-- Review with docs/SEASON_MANAGEMENT_GUIDE.md before use.

BEGIN TRANSACTION;

-- Example Season 8 full window placeholder based on user-provided planning dates.
-- Start 2026-05-16 00:00 Brisbane = 2026-05-15T14:00:00Z.
-- End 2026-07-17 23:59:59 Brisbane = 2026-07-17T13:59:59Z.
-- Uncomment only after approval.

-- INSERT INTO mr_season_windows(season_id, start_utc, end_utc, note)
-- VALUES(8, '2026-05-15T14:00:00+00:00', '2026-07-17T13:59:59+00:00', 'Season 8 / 8.5')
-- ON CONFLICT(season_id) DO UPDATE SET
--   start_utc=excluded.start_utc,
--   end_utc=excluded.end_utc,
--   note=excluded.note;

-- UPDATE bot_settings SET value='8' WHERE key='current_season';

COMMIT;
