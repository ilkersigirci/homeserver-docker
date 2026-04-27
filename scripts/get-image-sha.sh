#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/get-image-sha.sh [--digest-only|--pinned-only] <image[:tag]>

Description:
  Resolves a container image tag to its immutable sha256 digest using:
    docker buildx imagetools inspect

Options:
  --digest-only   Print only the digest (sha256:...)
  --pinned-only   Print only the pinned image (image:tag@sha256:...)
  -h, --help      Show this help

Examples:
  scripts/get-image-sha.sh langfuse/langfuse:3.171.0
  scripts/get-image-sha.sh --digest-only redis:8
  scripts/get-image-sha.sh --pinned-only postgres:18.3
EOF
}

err() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

mode="default"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --digest-only)
      mode="digest-only"
      shift
      ;;
    --pinned-only)
      mode="pinned-only"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      err "Unknown option: $1"
      ;;
    *)
      break
      ;;
  esac
done

[[ $# -eq 1 ]] || err "Exactly one image reference is required. Run with --help for usage."

image_ref="$1"

command -v docker >/dev/null 2>&1 || err "docker is not installed or not in PATH"

inspect_output="$(
  docker buildx imagetools inspect "$image_ref" 2>&1
)" || err "Could not inspect image '$image_ref'. Details: $inspect_output"

digest="$(
  printf '%s\n' "$inspect_output" | awk '$1=="Digest:" { print $2; exit }'
)"

[[ -n "$digest" ]] || err "Failed to parse digest for image '$image_ref'"

unpinned_ref="${image_ref%@sha256:*}"
pinned_ref="${unpinned_ref}@${digest}"

case "$mode" in
  digest-only)
    printf '%s\n' "$digest"
    ;;
  pinned-only)
    printf '%s\n' "$pinned_ref"
    ;;
  *)
    printf 'Image:  %s\n' "$image_ref"
    printf 'Digest: %s\n' "$digest"
    printf 'Pinned: %s\n' "$pinned_ref"
    ;;
esac
