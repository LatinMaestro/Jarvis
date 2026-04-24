# Railway Setup Checklist

1. Create a new GitHub repository.
2. Upload the contents of this deployment pack to the root of the repo.
3. Create a new Railway project from the GitHub repo.
4. Add the Railway variables from `.env.example` using the service Variables tab.
5. Attach a volume to the service and mount it at `/data`.
6. Confirm the start command is `python main.py` (already set in `railway.toml`).
7. Deploy or redeploy the service.
8. Watch the deploy logs for `Logged in as ...` or equivalent Discord startup output.
9. In Discord, run `!auto_import_status`, `!roster_list`, `!hero_roles_check`, and `!helpme`.
10. After a gaming session, run `!auto_import_run`.
