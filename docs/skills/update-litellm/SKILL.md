---
name: update-litellm
description: Upgrade the self-contained LiteLLM image and rebase its enterprise-removal, SSO, and delegated-auth patches in Dockerfiles/LiteLLM.
---

# Update LiteLLM

Work in `Dockerfiles/LiteLLM`; read its `README.md` and `ARCHITECTURE.md`.
Use official `BerriAI/litellm` source. No fork image, vendored checkout, or
separate release workflow is needed.

1. Clone the requested `v<version>` tag into a fresh temporary directory.
    Set `IMAGE_VERSION` and its resolved `UPSTREAM_COMMIT` in the Dockerfile.
    Compare upstream's Dockerfile, Python/workspace metadata, UI build, and
    Prisma entrypoint with our stages; update base pins when required.
2. Run `strip_enterprise.py <checkout>`. It removes the proprietary trees,
    dependency/workspace entries from both TOML files, and enterprise UI override.
    Preserve unrelated dependency pins. Adapt it if upstream changes layout.
3. Apply `litellm-oss.patch` then `litellm-auth.patch` with
    `patch --batch --forward --fuzz=0 -p1` inside the checkout. Resolve drift by
    editing upstream code and regenerating the affected diff, keeping the two
    patches separate. Do not turn on `premium_user` globally: retain authorization,
    model access, budgets, rate limits, SCIM deactivation, and admin-only UI access.
4. Refresh `base-sources.sha256` for every patched file from pristine upstream
    source, before either patch. Run `verify_oss.py <patched-checkout>`.
5. Build from the repository root:

    ```sh
    docker build --progress=plain -t homeserver-litellm:check Dockerfiles/LiteLLM
    ```

    This rebuilds the OSS dashboard and checks the installed proxy, absence of
    enterprise modules, unlimited UI SSO, and both delegated token profiles.
    Fix failed checks; do not skip them or accept patch fuzz. Verify startup with
    an isolated configuration if entrypoint or migration behavior changed.
6. Run `uvx prek run --files <changed-files>`. The existing custom-image workflow
    publishes the version after merge; Compose's tag/digest update follows once
    that image exists. Never invent a published digest or restart the live stack
    as part of a patch rebase.

Renovate proposes upstream version changes and points here. Complete the source
pin refresh, patch repair, and build checks without routine confirmation; a
version-only change intentionally fails the commit check until prepared.
