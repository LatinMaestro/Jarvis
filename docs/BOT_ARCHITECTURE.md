# Bot Architecture

## Runtime model

Jarvis is a single-process Python Discord bot. Railway starts it using:

```bash
python main.py
```

The bot uses `discord.py`, `aiohttp`, `pandas`, `Pillow`, and SQLite.

## Main components observed in latest export

- Discord command registration and command handlers are currently contained in `main.py`.
- SQLite connection is created at startup using environment-configurable database paths.
- Railway persistent-storage behaviour is supported through `MR_DB_PATH` and `MR_DB_SEED_PATH`.
- Season-aware tables and views are created/migrated at startup.
- Marvel Rivals API import tables store match metadata, raw JSON, human-only JSON, player-match data, hero segments, badges, bans, hero time, roster and scan state.
- Image-output commands use Pillow fonts with fallback font paths.
- Session/team fairness state is held in memory and persisted to the `session_state` table.

## Deployment files

- `railway.toml` sets the Railway builder and start command.
- `requirements.txt` pins runtime Python packages.
- `runtime.txt` and `python-version.txt` select Python 3.11.
- `env.example` lists required Railway variables without secrets.

## Command surface

The latest export contains 57 detected `@bot.command` handlers. A full detected list is included in `sample_outputs_from_uploaded_db.md`.

## Architectural risk

`main.py` is currently very large (23,771 lines). Codex should avoid broad rewrites. The preferred approach is to add targeted helper functions, scripts, or tests first. Any modularisation should be incremental and supported by regression output.
