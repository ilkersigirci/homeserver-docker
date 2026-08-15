# Running The Stack

This is the operator quick reference for humans and coding agents.

## Prerequisites

- Docker installed
- Docker Compose 5.3.0 or later
- Repo `.env` exists at `$HOME/docker/.env`
- `MY_HOSTNAME` is set and matches a file in `compose/` (examples: `gpu`, `remoteserver`, `remoteserver2`, `rpi3`)

## Preferred Commands (Repository Script)

```bash
# Start selected profiles
bash scripts/docker-manage.sh up

# Stop stack
bash scripts/docker-manage.sh down

# Pull, recreate, and prune dangling images
bash scripts/docker-manage.sh update

# Pull latest images without restarting
bash scripts/docker-manage.sh pull

# Remove dangling images
bash scripts/docker-manage.sh prune

# Restart
bash scripts/docker-manage.sh restart
```

## Direct Docker Compose Commands

Use these when you need to bypass `scripts/docker-manage.sh` and stay behavior-compatible.

```bash
PROFILES="core,desktop_apps,maintenance,media,monitoring,programming,reading,others"
COMPOSE_FILE="$HOME/docker/compose/$MY_HOSTNAME.yml"
ENV_FILE="$HOME/docker/.env"

COMPOSE_PROFILES="$PROFILES" docker compose --env-file "$ENV_FILE" --file "$COMPOSE_FILE" up -d
COMPOSE_PROFILES="$PROFILES" docker compose --env-file "$ENV_FILE" --file "$COMPOSE_FILE" down --remove-orphans
COMPOSE_PROFILES="$PROFILES" docker compose --env-file "$ENV_FILE" --file "$COMPOSE_FILE" pull
COMPOSE_PROFILES="$PROFILES" docker compose --env-file "$ENV_FILE" --file "$COMPOSE_FILE" up -d
```

## Service Log Rotation

`apps/logrotate.yml` rotates bind-mounted service logs under `logs/*/*.log`.
Use it for file logs; Docker daemon rotation only covers container stdout/stderr.

## Image Digest Pinning

When updating image versions in `apps/*.yml`, always pin to immutable digests (`image:tag@sha256:...`).
Use `scripts/get-image-sha.sh` to resolve the digest for a tag:

```bash
scripts/get-image-sha.sh --pinned-only ghcr.io/traefik/traefik:3.7.0-rc.2
```

## Custom Images

Custom images are defined under `Dockerfiles/<Name>/Dockerfile` and published by
per-image workflows named `.github/workflows/custom-images-<name>.yml` to
`ghcr.io/ilkersigirci/homeserver-<name>`.

Each per-image workflow filters on its own `Dockerfiles/<Name>/**` path and
calls the shared `.github/workflows/custom-images-build.yml` workflow.
GitHub requires workflow files directly under `.github/workflows`; workflow
subdirectories are not supported.

Pull requests validate image and workflow changes. Pushes to `main` publish only
when the matching `Dockerfiles/<Name>/**` context changes, so shared workflow
maintenance does not republish unchanged image tags.
PR validation uses read-only repository permissions; only publish jobs get
`packages: write`.

Images publish the version read from `ARG IMAGE_VERSION` by default. If
`Dockerfiles/<Name>/version_tagging.sh` exists and is executable, the workflow
uses its stdout as the image tag instead.

To add an image:

1. Add its Dockerfile with `ARG IMAGE_VERSION=<tag>` and use
    `${IMAGE_VERSION}` in the upstream `FROM` instruction.
2. Pin every `FROM` image to an immutable digest.
3. Copy an existing per-image workflow and update only its trigger path plus
    `name`, `context`, and `repository` inputs.
4. For dependency-derived tags, add an executable `version_tagging.sh` and keep
    it out of the build context with `.dockerignore`.
5. Reference the published image from Compose as `tag@sha256:digest`.

Keep Docker build steps in `custom-images-build.yml`; per-image workflows should
only declare triggers and inputs.
Coding agents adding custom images should follow
`docs/skills/create-custom-image/SKILL.md`.

### Renovate Update Flow

Renovate handles an upstream release in two runs:

1. Renovate updates `IMAGE_VERSION`, or a dependency and lockfile used by
    `version_tagging.sh`.
2. After that PR is merged, the workflow publishes the new custom image tag.
3. A later Renovate run updates the custom image tag and digest in the Compose file.

The Compose update cannot be created before the workflow publishes the new custom
image tag.

Custom image Compose updates are grouped by Renovate under `homeserver custom
images`. Package-derived images map each published image to its release-driving
upstream so the Compose PR shows that project's release notes instead of this
repository's. Thin wrappers can use Dockerfile dependency types to ignore helper
stages while tracking the final base image.

Package-derived custom images use one explicit release-driver rule per image in
`renovate.json`. Renovate disables every other dependency and base-image update
in those image contexts. For a thin wrapper driven by its final `FROM` image,
disable the `stage` and `syntax` dependency types in that Dockerfile. A single
package rule can then match both the upstream and published custom-image names,
set their release URLs, and disable digest-only updates with `digest.enabled`.

### Renovate Package Rule Placement

Keep `packageRules` in the root `renovate.json` ordered as follows:

1. Shared homeserver custom-image group and package-derived context deny rule.
2. Per-image release rules, alphabetically by image name.
3. Shared package-derived lock-file maintenance rule.
4. Remaining custom-image Compose rules, alphabetically by image name.
5. All other app rules, alphabetically by app name.

For a package-derived custom image, update the shared context and lock-file
denylists, add one exact release-driver rule, and add its Compose upstream rule.
For a final-stage-driven wrapper, add one non-final dependency rule and one rule
for its upstream and published package names. Do not combine unrelated files and
packages in one release-driver rule: list matchers form an allow set, not
one-to-one pairs. Preserve broad disable rules before their narrow allow rules
because later matching rules override earlier values.

### Public Package Bootstrap

GitHub creates each new GHCR package as private, and package visibility cannot be
changed through the supported Packages REST API.

1. Merge the Dockerfile and image workflow while services still use their existing
    pinned image.
2. Let the workflow publish the first image, then set the new package visibility to
    Public in GitHub.
3. Resolve the public image digest and switch the service to
    `ghcr.io/ilkersigirci/homeserver-<name>:<tag>@sha256:<digest>`.

## Renovate Local Checks

```bash
make renovate-validate

# lookup-only; it does not create branches or PRs.
make renovate-local
```

## Destructive Operations

- `down --volumes` and `rm -svf` are intentionally excluded from normal workflows.
- Use them only for explicit cleanup tasks, after confirming data-loss impact on bound volumes and named volumes.
