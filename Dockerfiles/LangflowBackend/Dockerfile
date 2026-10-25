ARG IMAGE_VERSION=1.13.0
FROM langflowai/langflow-backend:${IMAGE_VERSION}@sha256:387e2a89fae7f722e506623d605b51d058cf0bfd219ed433ccf7e0a8a53cfde9

USER 0

COPY patches/openai-responses.patch /tmp/openai-responses.patch
# Temporary upstream backport; see README.md for the removal condition.
COPY patches/s3-chat-attachments.patch /tmp/s3-chat-attachments.patch

RUN set -eux; \
    microdnf install -y patch; \
    site_packages="$(python -c 'import site; print(site.getsitepackages()[0])')"; \
    cd "${site_packages}"; \
    patch --batch --forward --fuzz=0 --strip=4 < /tmp/openai-responses.patch; \
    patch --batch --forward --fuzz=0 --strip=4 < /tmp/s3-chat-attachments.patch; \
    uv pip install --python /app/.venv/bin/python --no-deps \
      'lfx-openai==0.1.4' 'lfx-openai-compatible==0.1.0' 'langchain-openai==1.4.1'; \
    microdnf remove -y patch; \
    microdnf clean all; \
    rm -f /tmp/openai-responses.patch /tmp/s3-chat-attachments.patch

USER user

ENV LANGFLOW_COMPONENTS_PATH=/app/custom_components
COPY --chown=1000:0 components /app/custom_components

COPY --chown=1000:0 tests /tmp/langflow-backend-tests

RUN set -eux; \
    export LANGFLOW_CONFIG_DIR=/tmp/langflow-build-check; \
    python -m unittest discover -s /tmp/langflow-backend-tests -v; \
    python -c 'from langflow.main import create_app; from langflow.plugin_routes import _get_route_keys; assert ("/api/v1/responses", "POST") in _get_route_keys(create_app())'; \
    rm -rf /tmp/langflow-backend-tests /tmp/langflow-build-check
