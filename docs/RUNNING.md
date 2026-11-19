# Running The Stack

This is the operator quick reference for humans and coding agents.

## Deploy from coding

Run deployment playbooks from the Docker checkout on `coding`. The launcher
uses the inventory, SSH configuration, shared `check_rbw` role and pinned uv
environment in `~/Repos/Mine/ansible-automations`. Set `ANSIBLE_AUTOMATIONS_DIR`
if the infrastructure checkout is elsewhere.

Provision Docker and the Compose plugin on the targets first.
From the Docker repository root, install the deployment collection once:

```bash
uv run --frozen --project "${ANSIBLE_AUTOMATIONS_DIR:-$HOME/Repos/Mine/ansible-automations}" \
  ansible-galaxy collection install -r ansible/collections/requirements.yml
```

After pushing a stack or mapping change to `main`, deploy to a host:

```bash
rbw unlock
./ansible/run deploy.yml --limit gpu
```

The playbook updates the selected host's checkout of `main`, writes its `.env`
with mode `0600`, and runs Compose `up` with the configured image pull policy.
Use an SSH agent with access to the Git remote. On `coding`, `~/docker` is the
controller's own working checkout. Update it yourself (for example with
`git pull --ff-only` on `main`) before deploying. Its host vars skip the Git
task even when the deployment includes the entire `homeserver` group.

Store literal secret values in Bitwarden. The controller reads each mapped vault
item once per host and selects custom fields by full name, ignoring case. Use
canonical names such as `username` or `password` for built-in fields, which
`rbw` resolves separately. Only the selected values go into the Compose template.
A missing, ambiguous, or empty field stops the sync before it writes `.env`.
Add shared variable-to-field mappings in
`ansible/roles/homeserver_rbw_env/defaults/main.yml` and host overrides in
`ansible/host_vars/<inventory_hostname>.yml`. Keep SSH users, addresses, and host
membership in the infrastructure inventory. Each mapping needs an `item`. Add
`field` only when the vault field differs from the environment variable name:

```yaml
env_vars_mapping:
  GRAFANA_CLIENT_ID:
    item: pocketid.ilker
  ADGUARD_PASSWORD:
    item: adguardhome.rpi1
    field: password
```

Run the full deployment once per host to install `compose/profiles.env`. For
later value changes in Bitwarden, sync and apply the environment on that host:

```bash
./ansible/run deploy.yml --limit gpu --tags env,compose
```

Use `--tags checkout`, `--tags env`, or `--tags compose` for an individual phase.
Use `--list-hosts` to preview the target selection. Omitting `--limit` selects
the whole homeserver group. A full `--check` requires an existing target
checkout and environment because Compose validates files on disk.

For a standalone lifecycle action on an existing deployment:

```bash
./ansible/run docker_compose.yml --limit gpu -e task=restart
```

| Action | Fleet playbook behavior |
| --- | --- |
| `up` | Apply configuration and recreate changed services. |
| `update` | Pull images and reconcile the stack. |
| `pull` | Pull images only. |
| `restart` | Take the selected stack down and bring it back up. |
| `down` | Take the stack down and remove orphans. |
| `prune` | Remove dangling images on the selected host. |

The legacy script wrapper is available as `./ansible/run docker_manage.yml
--limit gpu -e homeserver_docker_manage_action=update`. Its `update` also prunes
dangling images.

## Local operations on one host

- Docker installed
- Docker Compose 5.4.0 or later for automatic pulling of `pre_start` images
- Repo `.env` exists at `$HOME/docker/.env`
- `MY_HOSTNAME` is set and matches a file in `compose/` (examples: `gpu`, `remoteserver`, `remoteserver2`, `rpi3`)

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

## Missing `pre_start` Images After Pruning

If startup fails with `No such image` for a `pre_start` hook, check
`docker compose version` on the affected host. Compose 5.3.x does not pull hook
images automatically; `docker system prune -a` can remove these images when no
container references them. Upgrade to Compose 5.4.0 or later, which includes the
[hook image pull fix](https://github.com/docker/compose/releases/tag/v5.4.0).
For immediate recovery on an older version, run `docker pull` with the exact
image reference from the error, including its digest, then retry
`bash scripts/docker-manage.sh up`.

## Direct Docker Compose Commands

Use these when you need to bypass `scripts/docker-manage.sh` and stay behavior-compatible.

```bash
cd ~/docker
docker compose -f "compose/$MY_HOSTNAME.yml" --env-file .env --env-file compose/profiles.env up -d
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
`packages: write` and `id-token: write` (for signing).

The shared workflow reads the image version and calls the SHA-pinned
[Docker GitHub Builder](https://github.com/docker/github-builder). Docker manages
native `linux/amd64` and `linux/arm64` runners, per-image/per-platform caches,
SBOM/provenance attestations, signing, and final manifest publication. Wrappers
can restrict `platforms` to `linux/amd64` when required. A wrapper can publish
several images from one context with a matrix of Dockerfile `target` stages and
`repository` names, as the Hatchet and LiteLLM wrappers do. No QEMU is used.
Only successful publish builds update the version tag; no `latest` tag is created.
PR builds do not push images or publish a manifest. GHCR authentication uses the
automatic GitHub token; no additional stored secrets are required.

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

Keep version resolution and Docker workflow inputs in `custom-images-build.yml`;
per-image workflows only declare triggers, permissions, and inputs.
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

## Renovate PR Updates

The workflow uses a personal access token with platform commits disabled and a
dedicated Git author. Keep that author stable so Renovate recognizes its commits.

## Renovate Local Checks

```bash
make renovate-validate

# lookup-only; it does not create branches or PRs.
make renovate-local
```

## Destructive Operations

- `down --volumes` and `rm -svf` are intentionally excluded from normal workflows.
- Use them only for explicit cleanup tasks, after confirming data-loss impact on bound volumes and named volumes.
