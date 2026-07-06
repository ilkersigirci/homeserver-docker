---
name: create-custom-image
description: Create or update repository custom Docker images under Dockerfiles with matching per-image GitHub Actions workflows, GHCR naming, Renovate flow, version tagging, and validation. Use when adding a new custom image, changing an existing custom image build context, wiring custom image publishing, or updating custom image workflow conventions in this repository.
---

# Create Custom Image

## Required Context

- Read `docs/RUNNING.md` Custom Images section.
- Read `.github/workflows/custom-images-build.yml`.
- Read one existing wrapper, such as `.github/workflows/custom-images-gatus.yml`.
- Work from the repository root (`$HOME/docker`).

## Workflow

### 1) Image Context

- Use top-level `Dockerfiles/<Name>/Dockerfile`.
- Define `ARG IMAGE_VERSION=<tag>` when the published tag comes from an upstream image tag.
- Use `${IMAGE_VERSION}` in the upstream `FROM` line.
- Pin every `FROM` image to an immutable digest.
- Do not use `latest` for `IMAGE_VERSION`.

If the published tag should come from a dependency, add executable
`Dockerfiles/<Name>/version_tagging.sh` that prints one Docker tag and keep it
out of the build context with `.dockerignore`.

### 2) Per-Image Workflow

Create `.github/workflows/custom-images-<slug>.yml` by copying an existing
wrapper. Update only:

- workflow display name
- `Dockerfiles/<Name>/**` trigger path
- `name: <Name>`
- `context: Dockerfiles/<Name>`
- `repository: homeserver-<slug>`

Preserve these rules:

- No `workflow_dispatch`; custom image publishing is automatic only.
- `push.paths` includes only the matching image context.
- `pull_request.paths` includes the image context, shared build workflow, and wrapper.
- PR validation job uses only `contents: read`.
- Push publish job uses `contents: read` and `packages: write`.
- Shared Docker build steps stay in `custom-images-build.yml`.

### 3) Compose And Renovate

Reference custom images from Compose only after GHCR has published the image:

```yaml
image: ghcr.io/ilkersigirci/homeserver-<slug>:<tag>@sha256:<digest>
```

Keep this Renovate flow:

1. Renovate updates `Dockerfiles/**` or dependencies used by `version_tagging.sh`.
2. The matching image workflow publishes after merge to `main`.
3. A later Renovate run updates Compose references for `ghcr.io/ilkersigirci/homeserver-*`.

Keep custom image Compose updates grouped under `homeserver custom images`.

## Validation

- Run `uvx prek run --files <changed-files>`.
- Run `uvx --from actionlint-py actionlint <changed-workflow-files>` when workflows changed.
- Run `make renovate-validate` when `renovate.json` changed.
- Run `version_tagging.sh` when added or changed and confirm stdout is one valid Docker tag.

## Done Criteria

- `Dockerfiles/<Name>/Dockerfile` exists and pins every `FROM` image.
- `ARG IMAGE_VERSION` or executable `version_tagging.sh` provides the published tag.
- `.github/workflows/custom-images-<slug>.yml` follows the copied wrapper pattern.
- Compose uses `tag@sha256:digest` only after the image exists in GHCR.
