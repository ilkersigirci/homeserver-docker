ARG IMAGE_VERSION=1.11.4
FROM langflowai/langflow-backend:${IMAGE_VERSION}@sha256:f90962a3abfa693d8ddd9b479e12aec6c9e4cbfd6e8050729f21ee92c11ce8a4

USER 0

COPY patches/openai-responses.patch /tmp/openai-responses.patch

RUN set -eux; \
    microdnf install -y patch; \
    site_packages="$(python -c 'import site; print(site.getsitepackages()[0])')"; \
    cd "${site_packages}"; \
    patch --batch --forward --fuzz=0 --strip=4 < /tmp/openai-responses.patch; \
    microdnf remove -y patch; \
    microdnf clean all; \
    rm -f /tmp/openai-responses.patch

USER user

COPY --chown=1000:0 tests /tmp/langflow-openai-responses-tests

RUN set -eux; \
    python -m unittest discover -s /tmp/langflow-openai-responses-tests -v; \
    python -c 'from langflow.main import create_app; from langflow.plugin_routes import _get_route_keys; assert ("/api/v1/responses", "POST") in _get_route_keys(create_app())'; \
    rm -rf /tmp/langflow-openai-responses-tests
