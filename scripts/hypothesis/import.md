# Import Official Hypothesis Annotations

This runbook exports all annotations from your official `hypothes.is` account,
imports them into the self-hosted `hypothesis` service, and restores the
original annotation timestamps.

Run all host-side commands from the repository root:

```bash
cd $HOME/docker
```

## 1. Bootstrap The Local User

Set the local bootstrap user in `.env`:

```env
HYPOTHESIS_CLIENT_OAUTH_ID=<stable-uuid>
HYPOTHESIS_BOOTSTRAP_USERNAME=<username>
HYPOTHESIS_BOOTSTRAP_EMAIL=<email>
HYPOTHESIS_BOOTSTRAP_PASSWORD=<password>
HYPOTHESIS_BOOTSTRAP_ADMIN=true
HYPOTHESIS_BOOTSTRAP_OAUTH_CLIENT_NAME=Hypothesis client
HYPOTHESIS_BOOTSTRAP_OAUTH_REDIRECT_URI=https://hypothesis.$DOMAINNAME/app.html
```

Use any stable UUID for `HYPOTHESIS_CLIENT_OAUTH_ID`. To generate one:

```bash
uuidgen | tr '[:upper:]' '[:lower:]'
```

Run the one-shot init profile:

```bash
COMPOSE_PROFILES=reading,hypothesis,hypothesis-init docker compose \
  --env-file .env \
  -f compose/gpu.yml \
  run --rm hypothesis-init
```

This initializes the database/search index, creates the user if missing, and
grants admin when `HYPOTHESIS_BOOTSTRAP_ADMIN=true`. It also creates or updates
the OAuth client row for `HYPOTHESIS_CLIENT_OAUTH_ID`.

All listed bootstrap variables are required. If one is missing, compose or the
init script fails before database initialization. If the user already exists,
the init command updates its password from `HYPOTHESIS_BOOTSTRAP_PASSWORD`.

Recreate the app container:

```bash
COMPOSE_PROFILES=reading,hypothesis docker compose \
  --env-file .env \
  -f compose/gpu.yml \
  up -d --force-recreate hypothesis
```

## 2. Create API Tokens

Log in to the local service as `<username>`, then create a local API token:

```text
https://hypothesis.$DOMAINNAME/account/developer
```

Create an official API token:

```text
https://hypothes.is/account/developer
```

Export both tokens in the shell that will run the migration:

```bash
export HYPOTHESIS_TOKEN='<official-hypothes.is-token>'
export LOCAL_HYPOTHESIS_TOKEN='<self-hosted-token>'
export LOCAL_HYPOTHESIS_URL='https://hypothesis.$DOMAINNAME'
```

## 3. Back Up The Local Database

Take a backup before importing:

```bash
scripts/database/postgres-backup.sh \
  --service hypothesis-db \
  --profiles reading,hypothesis \
  --compose-file compose/gpu.yml
```

If the backup helper cannot resolve the compose service, use the direct
container fallback:

```bash
mkdir -p backups/postgres
docker exec hypothesis-db pg_dumpall -U hypothesis \
  | gzip -c > backups/postgres/hypothesis-db_pre_import.sql.gz
```

## 4. Export Official Annotations

```bash
mkdir -p backups/hypothesis

scripts/hypothesis/migrate-annotations.py export \
  --output backups/hypothesis/official-annotations.json
```

The script exports annotations for the official account attached to
`HYPOTHESIS_TOKEN`.

## 5. Dry-Run The Import

```bash
scripts/hypothesis/migrate-annotations.py import \
  --dest-url "$LOCAL_HYPOTHESIS_URL" \
  --input backups/hypothesis/official-annotations.json \
  --dry-run
```

The dry-run validates ordering, replies, and group policy without creating
annotations.

## 6. Import And Restore Timestamps

```bash
scripts/hypothesis/migrate-annotations.py import \
  --dest-url "$LOCAL_HYPOTHESIS_URL" \
  --input backups/hypothesis/official-annotations.json \
  --restore-timestamps
```

`--restore-timestamps` copies this script into the `hypothesis` container, fixes
the imported annotations' `created` and `updated` values from migration metadata,
and reindexes Elasticsearch so the sidebar/search UI shows the original dates.

Expected output ends with lines like:

```text
Imported 1555 annotations into https://hypothesis.$DOMAINNAME/api; skipped 0
matched=1555 changed=1555
reindexed=1555
```

## 7. Verify

Check that every migrated annotation has restored timestamps:

```bash
docker exec hypothesis-db psql -U hypothesis -d hypothesis -c "
select
  count(*) filter (
    where a.created = ((m.data #>> '{migrated_from_hypothesis,created}')::timestamptz at time zone 'UTC')
      and a.updated = ((m.data #>> '{migrated_from_hypothesis,updated}')::timestamptz at time zone 'UTC')
      and s.created = ((m.data #>> '{migrated_from_hypothesis,created}')::timestamptz at time zone 'UTC')
      and s.updated = ((m.data #>> '{migrated_from_hypothesis,updated}')::timestamptz at time zone 'UTC')
  ) as repaired,
  count(*) as total
from annotation a
join annotation_slim s on s.pubid = a.id
join annotation_metadata m on m.annotation_id = s.id
where m.data ? 'migrated_from_hypothesis';
"
```

Check the API returns old dates:

```bash
docker exec hypothesis wget -qO- \
  'http://127.0.0.1:5000/api/search?limit=3&sort=created&order=desc'
```

Refresh the browser sidebar after verification.

## Existing Import Without Timestamp Restore

If annotations were already imported without `--restore-timestamps`, repair them
without importing again:

```bash
docker cp scripts/hypothesis/migrate-annotations.py hypothesis:/tmp/migrate-annotations.py
docker exec hypothesis python /tmp/migrate-annotations.py restore-timestamps
```

## Notes

The public API cannot set `created`, `updated`, `id`, or `user` while creating
annotations. The migration script stores the official `id`, `user`, `created`,
and `updated` values in `metadata.migrated_from_hypothesis`, then the timestamp
restore step writes the dates into the local `annotation` and `annotation_slim`
tables and reindexes Elasticsearch.

By default:

- Public annotations stay public.
- Private annotations stay private.
- Shared annotations from unmapped official private groups become private.
- Replies are imported after their parent annotations.

To map an official private group to an existing local group, add one or more
group mappings to the import command:

```bash
--group-map OFFICIAL_GROUP_ID=LOCAL_GROUP_ID
```
