#!/bin/sh
set -eu

TEMPLATE_PATH="${1:-/app/data/config.template.json}"
OUTPUT_PATH="${2:-${APP_DIR:-/tmp/bifrost}/config.json}"

mkdir -p "$(dirname "$OUTPUT_PATH")"

TMP_OUTPUT_PATH="${OUTPUT_PATH}.tmp"

awk '
function normalize_base_url(url, normalized) {
    normalized = url
    sub(/\/+$/, "", normalized)
    sub(/\/v1$/, "", normalized)
    return normalized
}

{
    line = $0
    if (line ~ /"base_url"/) {
        marker_pos = index(line, "\"env.")
        if (marker_pos > 0) {
            prefix = substr(line, 1, marker_pos - 1)
            remainder = substr(line, marker_pos + 5)
            quote_pos = index(remainder, "\"")
            if (quote_pos <= 1) {
                printf "Failed to parse environment variable name for base_url from line: %s\n", line > "/dev/stderr"
                exit 1
            }

            env_var = substr(remainder, 1, quote_pos - 1)
            env_value = ENVIRON[env_var]
            if (env_value == "") {
                printf "Missing required environment variable for base_url: %s\n", env_var > "/dev/stderr"
                exit 1
            }

            env_value = normalize_base_url(env_value)
            gsub(/\\/, "\\\\", env_value)
            gsub(/"/, "\\\"", env_value)

            suffix = substr(remainder, quote_pos + 1)
            line = prefix "\"" env_value "\"" suffix
        }
    }
    print line
}
' "$TEMPLATE_PATH" > "$TMP_OUTPUT_PATH"

mv "$TMP_OUTPUT_PATH" "$OUTPUT_PATH"

echo "Rendered Bifrost config: $TEMPLATE_PATH -> $OUTPUT_PATH"

exec /app/docker-entrypoint.sh "$@"
