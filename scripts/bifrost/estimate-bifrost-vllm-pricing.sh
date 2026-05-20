#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage Example:

scripts/estimate-bifrost-vllm-pricing.sh \
  --hourly-usd 0.89 \
  --input-tokens-per-hour 1358516 \
  --output-tokens-per-hour 317147 \
  --output-multiplier 2
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -lt 3 || $# -gt 4 ]]; then
  usage >&2
  exit 2
fi

hourly_usd="$1"
input_tokens_per_hour="$2"
output_tokens_per_hour="$3"
output_multiplier="${4:-2}"

awk \
  -v hourly_usd="$hourly_usd" \
  -v input_tokens_per_hour="$input_tokens_per_hour" \
  -v output_tokens_per_hour="$output_tokens_per_hour" \
  -v output_multiplier="$output_multiplier" '
    BEGIN {
      if (hourly_usd <= 0 || input_tokens_per_hour < 0 || output_tokens_per_hour < 0 || output_multiplier <= 0) {
        print "Invalid input: hourly_usd and output_multiplier must be > 0; token rates must be >= 0" > "/dev/stderr"
        exit 2
      }

      weighted_tokens_per_hour = input_tokens_per_hour + (output_multiplier * output_tokens_per_hour)
      if (weighted_tokens_per_hour <= 0) {
        print "Invalid input: at least one token rate must be > 0" > "/dev/stderr"
        exit 2
      }

      input_cost_per_token = hourly_usd / weighted_tokens_per_hour
      output_cost_per_token = input_cost_per_token * output_multiplier

      printf "input_cost_per_token=%.12f\n", input_cost_per_token
      printf "output_cost_per_token=%.12f\n", output_cost_per_token
      printf "input_cost_per_1m_tokens=%.6f\n", input_cost_per_token * 1000000
      printf "output_cost_per_1m_tokens=%.6f\n", output_cost_per_token * 1000000
    }
  '
