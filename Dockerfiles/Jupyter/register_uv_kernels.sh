#!/usr/bin/env bash
set -euo pipefail

workspace="${JUPYTER_UV_WORKSPACE:-/workspace}"
max_depth="${JUPYTER_UV_PROJECT_MAX_DEPTH:-2}"
uv_cache="${UV_CACHE_DIR:-/workspace/.cache/uv}"

if ! [[ "$max_depth" =~ ^[0-9]+$ ]]; then
  echo "ERROR: JUPYTER_UV_PROJECT_MAX_DEPTH must be a non-negative integer." >&2
  exit 1
fi

kernel_id() {
  local label="$1"
  if [[ "$label" == "default" ]]; then
    printf 'python3\n'
    return
  fi

  local slug
  slug="$(printf '%s' "$label" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9._-]+/-/g; s/^[-._]+//; s/[-._]+$//')"
  printf 'uv-%s\n' "${slug:-workspace}"
}

display_name() {
  local label="$1"
  if [[ "$label" == "default" ]]; then
    printf 'Python 3 (default uv)\n'
    return
  fi

  printf 'Python 3 (uv: %s)\n' "$label"
}

sync_args() {
  local project="$1"
  if [[ -f "$project/uv.lock" ]]; then
    printf '%s\n' --locked
  fi
}

register_project() {
  local project="$1"
  local label="$2"
  local venv="$project/.venv"
  local id
  local name
  id="$(kernel_id "$label")"
  name="$(display_name "$label")"

  local args=()
  while IFS= read -r arg; do
    args+=("$arg")
  done < <(sync_args "$project")

  UV_PROJECT_ENVIRONMENT="$venv" uv sync "${args[@]}" --project "$project"

  if ! "$venv/bin/python" -c 'import ipykernel' >/dev/null 2>&1; then
    echo "ERROR: $project is missing ipykernel." >&2
    echo "Run: cd $project && uv add --dev ipykernel" >&2
    exit 1
  fi

  uv run "${args[@]}" --project "$project" \
    ipython kernel install \
    --user \
    --name "$id" \
    --display-name "$name" \
    --env VIRTUAL_ENV "$venv" \
    --env PATH "$venv/bin:${PATH:-}" \
    --env UV_PROJECT "$project" \
    --env UV_PROJECT_ENVIRONMENT "$venv" \
    --env UV_CACHE_DIR "$uv_cache"

  registered+=("$id")
}

mapfile -t projects < <(
  find "$workspace" \
    -mindepth 1 \
    -maxdepth "$((max_depth + 1))" \
    -type d \( \
      -name .cache \
      -o -name .git \
      -o -name .hg \
      -o -name .ipynb_checkpoints \
      -o -name .mypy_cache \
      -o -name .pytest_cache \
      -o -name .ruff_cache \
      -o -name .tox \
      -o -name .venv \
      -o -name __pycache__ \
      -o -name node_modules \
    \) -prune \
    -o -name pyproject.toml -type f -print \
  | sed 's#/pyproject[.]toml$##' \
  | sort
)

if [[ "${#projects[@]}" -eq 0 ]]; then
  echo "ERROR: no uv projects found in $workspace." >&2
  exit 1
fi

registered=()
for project in "${projects[@]}"; do
  if [[ "$project" == "$workspace" ]]; then
    label="workspace"
  else
    label="${project#"$workspace"/}"
  fi
  register_project "$project" "$label"
done

printf -v registered_list '%s, ' "${registered[@]}"
echo "Registered ${#registered[@]} uv kernel(s): ${registered_list%, }"
