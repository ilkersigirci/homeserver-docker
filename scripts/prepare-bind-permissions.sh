#!/usr/bin/env bash
set -euo pipefail

TARGET_PROFILE="custom-user"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DEFAULT_ENV_FILE="${HOME}/docker/.env"
[[ -f "${DEFAULT_ENV_FILE}" ]] || DEFAULT_ENV_FILE="${REPO_ROOT}/.env"
DEFAULT_COMPOSE_FILE=""
if [[ -n "${MY_HOSTNAME:-}" ]]; then
  DEFAULT_COMPOSE_FILE="${REPO_ROOT}/compose/${MY_HOSTNAME}.yml"
fi
DEFAULT_PROFILES="${COMPOSE_PROFILES:-${TARGET_PROFILE}}"

COMPOSE_FILE="${DEFAULT_COMPOSE_FILE}"
ENV_FILE="${DEFAULT_ENV_FILE}"
PROFILES="${DEFAULT_PROFILES}"
REPO_PATH="${REPO_ROOT}"
DRY_RUN=false
CHECK_ONLY=false
RECURSIVE=false
STRICT=false
VERBOSE=false

TMP_JSON=""
rows_seen=0
skipped_non_numeric=0
skipped_outside_repo=0
skipped_owner_conflict=0
created_paths=0
chowned_paths=0
drift_missing=0
drift_owner=0

declare -A OWNER_BY_PATH=()
declare -A SERVICE_BY_PATH=()

cleanup() {
  [[ -n "${TMP_JSON:-}" && -f "${TMP_JSON}" ]] && rm -f "${TMP_JSON}"
}
trap cleanup EXIT

usage() {
  cat <<EOF_USAGE
Usage: $0 [options]

Create/chown writable bind mounts for services tagged with profile '${TARGET_PROFILE}'.
Only numeric users are applied (e.g. 999:999, 101:101).
Linux/GNU tools required ('realpath -m', 'stat -c').

Options:
  --compose-file PATH   Compose file to parse (default: compose/\$MY_HOSTNAME.yml)
  --env-file PATH       Env file for variable resolution (default: \$HOME/docker/.env)
  --profiles CSV        COMPOSE_PROFILES for compose resolution (default: ${DEFAULT_PROFILES})
  --repo-path PATH      Restrict changes to this repo path (default: detected repo root)
  --dry-run             Print actions without changing filesystem
  --check-only          Verify compliance only (no create/chown), exit non-zero on drift
  --recursive           Use chown -R for directories
  --strict              Exit non-zero if any entries are skipped or conflicted
  --verbose             Print additional skip details
  -h, --help            Show this help

Exit Codes:
  0 success / compliant
  1 usage error or strict-mode skip failure
  2 drift detected in --check-only mode
EOF_USAGE
}

die() {
  echo "$1" >&2
  exit 1
}

usage_err() {
  usage >&2
}

die_usage() {
  echo "$1" >&2
  usage_err
  exit 1
}

require_value() {
  local flag="$1" value="${2:-}"
  if [[ -z "${value}" || "${value}" == --* ]]; then
    die_usage "Missing value for ${flag}"
  fi
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --compose-file) require_value "$1" "${2:-}"; COMPOSE_FILE="$2"; shift 2 ;;
      --env-file) require_value "$1" "${2:-}"; ENV_FILE="$2"; shift 2 ;;
      --profiles) require_value "$1" "${2:-}"; PROFILES="$2"; shift 2 ;;
      --repo-path) require_value "$1" "${2:-}"; REPO_PATH="$2"; shift 2 ;;
      --dry-run) DRY_RUN=true; shift ;;
      --check-only) CHECK_ONLY=true; shift ;;
      --recursive) RECURSIVE=true; shift ;;
      --strict) STRICT=true; shift ;;
      --verbose) VERBOSE=true; shift ;;
      -h|--help) usage; exit 0 ;;
      --) shift; break ;;
      *) die_usage "Unknown argument: $1" ;;
    esac
  done
  [[ $# -eq 0 ]] || die_usage "Unknown positional arguments: $*"
}

skip_total() {
  echo $((skipped_non_numeric + skipped_outside_repo + skipped_owner_conflict))
}

validate_config() {
  [[ "${DRY_RUN}" == true && "${CHECK_ONLY}" == true ]] && die "Use either --dry-run or --check-only, not both."
  [[ -n "${COMPOSE_FILE}" && -f "${COMPOSE_FILE}" ]] || die "Compose file not found: ${COMPOSE_FILE}"
  [[ -f "${ENV_FILE}" ]] || die "Env file not found: ${ENV_FILE}"
  if [[ "${EUID}" -ne 0 && "${DRY_RUN}" != true && "${CHECK_ONLY}" != true ]]; then
    die "Run as root (sudo) to apply chown changes, or use --dry-run/--check-only first."
  fi
  local cmd
  for cmd in docker jq realpath stat; do
    command -v "${cmd}" >/dev/null 2>&1 || die "${cmd} not found in PATH"
  done
  REPO_PATH="$(realpath -m "${REPO_PATH}")"
  if [[ "${VERBOSE}" == true ]]; then
    echo "compose_file=${COMPOSE_FILE}"
    echo "env_file=${ENV_FILE}"
    echo "profiles=${PROFILES}"
    echo "repo_path=${REPO_PATH}"
  fi
}

collect_targets() {
  local service user source uid gid owner source_path
  TMP_JSON="$(mktemp)"
  COMPOSE_PROFILES="${PROFILES}" docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" config --format json > "${TMP_JSON}"
  while IFS=$'\t' read -r service user source; do
    ((rows_seen+=1))
    if [[ "${user}" =~ ^([0-9]+)(:([0-9]+))?$ ]]; then
      uid="${BASH_REMATCH[1]}"
      gid="${BASH_REMATCH[3]:-${BASH_REMATCH[1]}}"
      owner="${uid}:${gid}"
    else
      ((skipped_non_numeric+=1))
      [[ "${VERBOSE}" == true ]] && echo "SKIP non-numeric user: service=${service} user=${user}"
      continue
    fi
    source_path="$(realpath -m "${source}")"
    if [[ "${source_path}" != "${REPO_PATH}" && "${source_path}" != "${REPO_PATH}/"* ]]; then
      ((skipped_outside_repo+=1))
      [[ "${VERBOSE}" == true ]] && echo "SKIP outside REPO_PATH: service=${service} source=${source_path}"
      continue
    fi
    if [[ -n "${OWNER_BY_PATH[${source_path}]:-}" && "${OWNER_BY_PATH[${source_path}]}" != "${owner}" ]]; then
      ((skipped_owner_conflict+=1))
      echo "SKIP owner conflict: path=${source_path} owners=${OWNER_BY_PATH[${source_path}]} vs ${owner}" >&2
      continue
    fi
    OWNER_BY_PATH["${source_path}"]="${owner}"
    SERVICE_BY_PATH["${source_path}"]="${service}"
  done < <(
    jq -r --arg target_profile "${TARGET_PROFILE}" '
      .services
      | to_entries[]
      | .key as $service
      | .value as $cfg
      | select(($cfg.profiles // []) | index($target_profile))
      | ($cfg.user // "") as $user
      | ($cfg.volumes // [])[]?
      | select(.type == "bind")
      | select((.read_only // false) == false)
      | [$service, $user, .source] | @tsv
    ' "${TMP_JSON}"
  )
}

process_targets() {
  local path owner service actual_owner
  while IFS= read -r path; do
    owner="${OWNER_BY_PATH[${path}]}"
    service="${SERVICE_BY_PATH[${path}]}"
    if [[ "${CHECK_ONLY}" == true ]]; then
      if [[ ! -e "${path}" ]]; then
        echo "MISSING path=${path} expected_owner=${owner} service=${service}"
        ((drift_missing+=1))
        continue
      fi
      actual_owner="$(stat -c '%u:%g' "${path}")"
      if [[ "${actual_owner}" != "${owner}" ]]; then
        echo "OWNER_MISMATCH path=${path} expected=${owner} actual=${actual_owner} service=${service}"
        ((drift_owner+=1))
      fi
      continue
    fi
    if [[ ! -e "${path}" ]]; then
      if [[ "${DRY_RUN}" == true ]]; then
        echo "DRY-RUN create dir: ${path} (service=${service})"
      else
        mkdir -p "${path}"
      fi
      ((created_paths+=1))
    fi
    if [[ "${DRY_RUN}" == true ]]; then
      if [[ "${RECURSIVE}" == true && -d "${path}" ]]; then
        echo "DRY-RUN chown -R ${owner} ${path}"
      else
        echo "DRY-RUN chown ${owner} ${path}"
      fi
    else
      if [[ "${RECURSIVE}" == true && -d "${path}" ]]; then
        chown -R "${owner}" "${path}"
      else
        chown "${owner}" "${path}"
      fi
    fi
    ((chowned_paths+=1))
  done < <(printf '%s\n' "${!OWNER_BY_PATH[@]}" | sort)
}

report_no_targets_and_exit() {
  local skipped_total
  skipped_total="$(skip_total)"
  echo "No writable bind mounts found for ${TARGET_PROFILE} services."
  echo "rows_seen=${rows_seen} skipped_non_numeric=${skipped_non_numeric} skipped_outside_repo=${skipped_outside_repo} skipped_owner_conflict=${skipped_owner_conflict}"
  [[ "${STRICT}" == true && "${skipped_total}" -gt 0 ]] && exit 1
  exit 0
}

report_and_exit() {
  local skipped_total drift_total
  skipped_total="$(skip_total)"
  if [[ "${CHECK_ONLY}" == true ]]; then
    drift_total=$((drift_missing + drift_owner))
    echo "Check complete."
    echo "rows_seen=${rows_seen} unique_paths=${#OWNER_BY_PATH[@]} drift_missing=${drift_missing} drift_owner=${drift_owner}"
    echo "skipped_non_numeric=${skipped_non_numeric} skipped_outside_repo=${skipped_outside_repo} skipped_owner_conflict=${skipped_owner_conflict}"
    [[ "${drift_total}" -gt 0 ]] && exit 2
    [[ "${STRICT}" == true && "${skipped_total}" -gt 0 ]] && exit 1
    exit 0
  fi
  echo "Done."
  echo "rows_seen=${rows_seen} unique_paths=${#OWNER_BY_PATH[@]} created_paths=${created_paths} chowned_paths=${chowned_paths}"
  echo "skipped_non_numeric=${skipped_non_numeric} skipped_outside_repo=${skipped_outside_repo} skipped_owner_conflict=${skipped_owner_conflict}"
  [[ "${STRICT}" == true && "${skipped_total}" -gt 0 ]] && exit 1
  exit 0
}

main() {
  parse_args "$@"
  validate_config
  collect_targets
  if [[ ${#OWNER_BY_PATH[@]} -eq 0 ]]; then
    report_no_targets_and_exit
  fi
  process_targets
  report_and_exit
}

main "$@"
