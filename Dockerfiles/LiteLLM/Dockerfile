ARG IMAGE_VERSION=1.92.0-libre.1
FROM ghcr.io/nathanael-h/litellm-libre:${IMAGE_VERSION}@sha256:ed3a32a346fa670db402ee5b8be5f5364c8a5e730974d3b85811a810468a9e95

COPY base-sources.sha256 litellm-auth.patch verify_auth.py /tmp/litellm-auth/
COPY oidc_delegated_auth.py /app/litellm-config/oidc_delegated_auth.py

RUN set -eux; \
    site_packages="$(python3 -c 'import site; print(site.getsitepackages()[0])')"; \
    cd "${site_packages}"; \
    sha256sum -c /tmp/litellm-auth/base-sources.sha256; \
    test ! -e /app/enterprise; \
    test ! -e "${site_packages}/litellm/proxy/enterprise"; \
    python3 -c 'import importlib.util; assert importlib.util.find_spec("litellm_enterprise") is None'; \
    apk add --no-cache --virtual .litellm-patch-deps patch; \
    patch --batch --forward --fuzz=0 --strip=1 < /tmp/litellm-auth/litellm-auth.patch; \
    apk del .litellm-patch-deps; \
    python3 -m py_compile \
      litellm/proxy/auth/user_api_key_auth.py \
      litellm/proxy/response_api_endpoints/endpoints.py \
      /app/litellm-config/oidc_delegated_auth.py; \
    python3 /tmp/litellm-auth/verify_auth.py; \
    rm -rf /tmp/litellm-auth
