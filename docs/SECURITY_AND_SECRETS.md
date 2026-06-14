# Security and Secrets

## Secret handling

Never commit:

- Discord bot token;
- Marvel Rivals API key;
- Railway project/service tokens;
- `.env` or `.env.*` files containing real values;
- live production DB backups copied from Railway unless the owner explicitly approves and sensitive data handling is agreed.

## GitHub repository hygiene

The repository should include `env.example`, not `.env`.

The current deployment pack includes `gitignore.txt`; when installing into a repo, convert/copy it as `.gitignore` if required.

## Database data

The SQLite DB contains player names, match history, Discord-related session state and API metadata. Treat it as private project data.

Codex may inspect the bundled seed DB for testing, but must not upload it elsewhere or use it outside the repository workflow.

## API safety

Normal command tests must not call Marvel Rivals API unless explicitly required. Prefer stored match JSON and local DB fixtures.

Hero-cache/API refreshes should remain opt-in by default.
