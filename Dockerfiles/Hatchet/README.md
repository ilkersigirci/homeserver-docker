# Hatchet

This image builds Hatchet Lite from
[hatchet-dev/hatchet#4176](https://github.com/hatchet-dev/hatchet/pull/4176),
which adds generic OIDC authentication to self-hosted OSS Hatchet. It is used by
[`apps/hatchet.yml`](../../apps/hatchet.yml) with Pocket ID until the change is
available in an upstream release.

`IMAGE_VERSION` defines the published image tag, while `HATCHET_REVISION` pins
the exact PR commit. The image includes the matching `hatchet-lite`,
`hatchet-admin`, `hatchet-migrate`, and frontend artifacts.
