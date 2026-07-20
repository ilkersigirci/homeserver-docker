#!/bin/sh
set -eu

workspace=/workspace
projects=/workspace/projects
config_source="${MARIMO_CONFIG_FILE:-/etc/marimo/marimo.toml}"
secrets_file="${MARIMO_SECRETS_FILE:-/run/secrets/marimo_ai}"
tmp_dir="${TMPDIR:-/workspace/.cache/marimo/tmp}"
uv_cache="${UV_CACHE_DIR:-/workspace/.cache/uv}"
xdg_cache="${XDG_CACHE_HOME:-/workspace/.cache}"
xdg_config="${XDG_CONFIG_HOME:-/tmp/marimo-home/.config}"
xdg_data="${XDG_DATA_HOME:-/workspace/.local/share}"

if ! touch "$workspace/.marimo-write-test" 2>/dev/null; then
  echo "ERROR: $workspace is not writable by uid=$(id -u) gid=$(id -g)." >&2
  echo "Set PUID/PGID to match the owner of the bind-mounted workspace directory." >&2
  exit 1
fi
rm -f "$workspace/.marimo-write-test"

umask 077
mkdir -p \
  "${HOME:-/tmp/marimo-home}" \
  "$projects" \
  "$tmp_dir" \
  "$uv_cache" \
  "$xdg_cache" \
  "$xdg_config" \
  "$xdg_data" \
  "${UV_PYTHON_BIN_DIR:-/workspace/.local/bin}" \
  "${UV_PYTHON_INSTALL_DIR:-/workspace/.local/share/uv/python}"

# Sandbox environments are temporary. Remove leftovers from an interrupted
# container before Marimo starts creating new environments in this directory.
find "$tmp_dir" \
  -mindepth 1 \
  -maxdepth 1 \
  -type d \
  -name 'marimo-sandbox-*' \
  -exec rm -rf -- {} +

python /opt/marimo/render_config.py \
  --config "$config_source" \
  --secrets "$secrets_file" \
  --output "$xdg_config/marimo/marimo.toml"

if [ "$#" -ge 2 ] && [ "$1" = "marimo" ] && [ "$2" = "edit" ]; then
  if [ -n "${TOKEN:-}" ]; then
    set -- "$@" --token --token-password "$TOKEN"
  else
    set -- "$@" --no-token
  fi
fi

exec "$@"
