# Database Scripts

## `postgres-backup.sh`

Creates a logical Postgres backup with `pg_dumpall` from a running Docker Compose service.

Example:

```bash
scripts/database/postgres-backup.sh \
  --service hatchet-db \
  --profiles programming,hatchet
```

## Notes

- By default, compose file is auto-detected as `compose/$MY_HOSTNAME.yml`.
- By default, backups are written to `$REPO_PATH/backups/postgres`.
