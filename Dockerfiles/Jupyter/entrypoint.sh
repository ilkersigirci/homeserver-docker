#!/bin/sh
set -eu

workspace=/workspace
uv_cache="${UV_CACHE_DIR:-/workspace/.cache/uv}"

export UV_CACHE_DIR="$uv_cache"

mkdir -p \
  "${HOME:-/tmp/jupyter-home}" \
  "${IPYTHONDIR:-/tmp/jupyter-home/.ipython}" \
  "${JUPYTER_CONFIG_DIR:-/tmp/jupyter-home/.jupyter}" \
  "${JUPYTER_DATA_DIR:-/tmp/jupyter-home/.local/share/jupyter}" \
  "${JUPYTERLAB_SETTINGS_DIR:-/tmp/jupyter-home/.jupyter/lab/user-settings}" \
  "${JUPYTERLAB_WORKSPACES_DIR:-/tmp/jupyter-home/.jupyter/lab/workspaces}" \
  "${JUPYTER_RUNTIME_DIR:-/tmp/jupyter-runtime}" \
  "${XDG_CACHE_HOME:-/tmp/jupyter-cache}" \
  "$uv_cache"

if ! touch "$workspace/.jupyter-write-test" 2>/dev/null; then
  echo "ERROR: $workspace is not writable by uid=$(id -u) gid=$(id -g)." >&2
  echo "Set PUID/PGID to match the owner of the bind-mounted workspace directory." >&2
  exit 1
fi
rm -f "$workspace/.jupyter-write-test"

[ -e "$workspace/default" ] || cp -R /opt/jupyter/projects/default "$workspace/default"
[ -e "$workspace/data_science" ] || cp -R /opt/jupyter/projects/data_science "$workspace/data_science"

jupyter-register-uv-kernels

exec "$@"
