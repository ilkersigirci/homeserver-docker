# Hatchet

This image builds a pinned official Hatchet release and applies the generic OIDC
support from [hatchet-dev/hatchet#4176](https://github.com/hatchet-dev/hatchet/pull/4176)
as a local patch. It is used by [`apps/hatchet.yml`](../../apps/hatchet.yml) with
Pocket ID until the change is available in an upstream release.

`IMAGE_VERSION` selects the official source tag and published image tag.
`UPSTREAM_COMMIT` pins that tag to an exact commit. During the build,
`base-sources.sha256` verifies every upstream file changed by `oidc.patch`, the
patch is applied with zero fuzz, and the OIDC unit tests run before the binaries
are built. The image includes matching `hatchet-lite`, `hatchet-admin`,
`hatchet-migrate`, and frontend artifacts.

## Updating

1. Resolve the new official tag to its peeled commit and update `IMAGE_VERSION`
    and `UPSTREAM_COMMIT` in `Dockerfile`.
2. Check out that tag in a clean upstream clone and apply `oidc.patch` with
    three-way merge support.
3. Resolve conflicts against the new source. If the API contract changed,
    regenerate `api/v1/server/oas/gen/openapi.gen.go` with
    `hack/oas/generate-server.sh`; run `go mod tidy` after dependency changes.
4. Regenerate `oidc.patch` as the binary diff from the clean tag and refresh
    `base-sources.sha256` from the unpatched tag.
5. Build the image and exercise the OIDC unit tests and runtime login redirect.

Remove the patch, source hashes, and OIDC-specific build test once an official
Hatchet release contains equivalent generic OIDC support. Keep a runtime smoke
test for the configured provider after removing the patch.
