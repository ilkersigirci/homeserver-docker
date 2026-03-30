# Database Scripts

## `postgres-backup.sh`

Creates a logical Postgres backup with `pg_dumpall` from a running Docker Compose service.

Example:

```bash
scripts/database/postgres-backup.sh \
  --service hatchet-db \
  --profiles programming,hatchet
```

## `postgres-upgrade-major.sh`

Performs a major-version upgrade using dump/restore:

1. backup (`pg_dumpall`)
2. stop writer services + DB
3. rotate data dir (keeps rollback path)
4. start DB on new image
5. restore
6. restart writer services

Example:

```bash
scripts/database/postgres-upgrade-major.sh \
  --service hatchet-db \
  --new-image postgres:18.3 \
  --stop-services hatchet \
  --profiles programming,hatchet
```

## Notes

- By default, compose file is auto-detected as `compose/$MY_HOSTNAME.yml`.
- By default, backups are written to `$REPO_PATH/backups/postgres`.
- If you pass `--new-image`, still update the image in the source compose app file so future deploys stay on the new version.
