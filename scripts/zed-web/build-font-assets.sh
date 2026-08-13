#!/usr/bin/env bash
set -euo pipefail

container="${ZED_WEB_CONTAINER:-zed-web}"
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
output_dir="${ZED_WEB_ASSET_DIR:-${repo_dir}/configs/zed-web/assets}"

if (( $# == 0 )); then
  echo "Usage: $0 FONT.ttf [FONT.ttf ...]" >&2
  exit 2
fi

for font in "$@"; do
  if [[ ! -f "${font}" || "${font}" != *.ttf ]]; then
    echo "Expected an existing .ttf file: ${font}" >&2
    exit 2
  fi
done

if ! docker container inspect "${container}" >/dev/null 2>&1; then
  echo "Zed Web container not found: ${container}" >&2
  exit 1
fi

work_dir="$(mktemp -d)"
asset_container=""
cleanup() {
  if [[ -n "${asset_container}" ]]; then
    docker container rm --force --volumes "${asset_container}" >/dev/null 2>&1 || true
  fi
  find "${work_dir}" -depth -delete
}
trap cleanup EXIT

archive="${work_dir}/zed-assets.tar"
font_dir="${work_dir}/fonts/fira-code"
mkdir -p "${font_dir}"

image_id="$(docker container inspect --format '{{.Image}}' "${container}")"
asset_container="$(docker container create "${image_id}")"
docker cp \
  "${asset_container}:/opt/zed-web/static/zed-assets.tar" \
  "${archive}"
docker container rm --volumes "${asset_container}" >/dev/null
asset_container=""

for font in "$@"; do
  install -m 0644 "${font}" "${font_dir}/$(basename -- "${font}")"
done

tar --append --file "${archive}" --directory "${work_dir}" fonts/fira-code
gzip --best --stdout "${archive}" >"${archive}.gz"

if command -v brotli >/dev/null 2>&1; then
  brotli --quality 11 --output "${archive}.br" "${archive}"
elif command -v uv >/dev/null 2>&1; then
  uv run --isolated --quiet --with brotli python -c \
    'import brotli, pathlib, sys; source, target = map(pathlib.Path, sys.argv[1:]); target.write_bytes(brotli.compress(source.read_bytes(), quality=11))' \
    "${archive}" "${archive}.br"
else
  echo "Install brotli or uv to generate the Brotli asset variant." >&2
  exit 1
fi

mkdir -p "${output_dir}"
install -m 0644 "${archive}" "${output_dir}/zed-assets.tar"
install -m 0644 "${archive}.gz" "${output_dir}/zed-assets.tar.gz"
install -m 0644 "${archive}.br" "${output_dir}/zed-assets.tar.br"

printf 'Generated Zed Web assets in %s with:\n' "${output_dir}"
printf '  %s\n' "$@"
