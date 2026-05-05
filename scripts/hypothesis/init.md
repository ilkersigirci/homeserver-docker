# Initialize Self-Hosted Hypothesis

This runbook covers local service bootstrap for the self-hosted `hypothesis`
stack: database/search initialization, local user creation, password/admin
sync, and OAuth client setup.

Run all commands from the repository root:

```bash
cd $HOME/docker
```

## Required `.env` Values

Set these before running `hypothesis-init`:

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

All listed bootstrap variables are required. If one is missing, compose or the
init script fails before database initialization.

## When To Run `hypothesis-init`

Run `hypothesis-init`:

- On first install with an empty Hypothesis database.
- After changing any required bootstrap `.env` value.
- After changing `HYPOTHESIS_CLIENT_OAUTH_ID`.
- After upgrading the `hypothesis/hypothesis` image.
- After recreating or restoring `data/hypothesis/postgres`.
- After recreating or restoring `data/hypothesis/elasticsearch`.

Normal day-to-day restarts do not need `hypothesis-init`.

## Run Init

```bash
COMPOSE_PROFILES=reading,hypothesis,hypothesis-init docker compose \
  --env-file .env \
  -f compose/gpu.yml \
  run --rm hypothesis-init
```

The init command:

- Initializes database tables and Alembic stamp when needed.
- Initializes Elasticsearch settings.
- Creates the local user if missing.
- Updates the local user's password from `HYPOTHESIS_BOOTSTRAP_PASSWORD`.
- Applies admin state from `HYPOTHESIS_BOOTSTRAP_ADMIN`.
- Creates or updates the OAuth client row for `HYPOTHESIS_CLIENT_OAUTH_ID`.

After init, recreate the app container:

```bash
COMPOSE_PROFILES=reading,hypothesis docker compose \
  --env-file .env \
  -f compose/gpu.yml \
  up -d --force-recreate hypothesis
```

## Fresh Setup Order

```bash
COMPOSE_PROFILES=reading,hypothesis docker compose \
  --env-file .env \
  -f compose/gpu.yml \
  up -d

COMPOSE_PROFILES=reading,hypothesis,hypothesis-init docker compose \
  --env-file .env \
  -f compose/gpu.yml \
  run --rm hypothesis-init

COMPOSE_PROFILES=reading,hypothesis docker compose \
  --env-file .env \
  -f compose/gpu.yml \
  up -d --force-recreate hypothesis
```

## Notes

`MODEL_CREATE_ALL` is not used. Database/search initialization is explicit and
owned by the `hypothesis-init` profile.
