#!/bin/sh
set -e

# Keep upstream behavior: frontend proxies to backend service DNS unless overridden.
BACKEND_URL="${BACKEND_URL:-excalidash-db:8000}"
echo "Configuring nginx with BACKEND_URL: ${BACKEND_URL}"

ESCAPED_BACKEND_URL="$(printf '%s\n' "${BACKEND_URL}" | sed 's/[\/&]/\\&/g')"
sed "s/__BACKEND_URL__/${ESCAPED_BACKEND_URL}/g" /etc/nginx/nginx.conf.template > /tmp/nginx.conf

echo "Validating nginx configuration..."
nginx -t -c /tmp/nginx.conf

exec nginx -g 'daemon off;' -c /tmp/nginx.conf
