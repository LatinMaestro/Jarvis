# PR Review Checklist

## Owner review

Before merging a Jarvis PR, confirm:

- [ ] The PR summary clearly explains the change.
- [ ] No secrets or `.env` files are included.
- [ ] `main.py` compiles.
- [ ] Offline smoke tests passed against a copied DB fixture.
- [ ] Sample output was generated for every changed command.
- [ ] Database migrations are safe and idempotent.
- [ ] Railway deployment settings are unchanged or clearly explained.
- [ ] Rollback path is clear.
- [ ] Manual Discord commands to test are listed.

## Manual Discord smoke after deployment

Run:

```text
!season
!season_windows
!auto_import_status
!roster_list
!hero_roles_check
!helpme
```

For stat/image changes, run the changed command with the exact sample arguments used in PR testing.
