#!/bin/sh
set -eu

ALLOWED_DOMAIN_URL="${ALLOWED_DOMAIN_URL:-${AIGATEWAY_BASE_URL/models}}"
ALLOWED_HTTPS_IP_URL="${ALLOWED_HTTPS_IP_URL:-${ALLOWED_IP_URL:-}}"
ALLOWED_HTTP_IP_URL="${ALLOWED_HTTP_IP_URL:-}"
DENIED_DOMAIN_URL="${DENIED_DOMAIN_URL:-https://example.com/}"
DENIED_HTTPS_IP_URL="${DENIED_HTTPS_IP_URL:-${DENIED_IP_URL:-https://1.0.0.1/}}"
DENIED_HTTP_IP_URL="${DENIED_HTTP_IP_URL:-http://1.0.0.1/}"

curl_base() {
  curl \
    --silent \
    --show-error \
    --connect-timeout 10 \
    --max-time 30 \
    --output /dev/null \
    --write-out "\n%{http_code} %{proxy_used} %{url_effective}" \
    "$@"
}

pass() {
  printf 'PASS: %s\n' "$1"
}

skip() {
  printf 'SKIP: %s\n' "$1"
}

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

status_line() {
  printf '%s\n' "$1" | tail -n 1
}

assert_proxy_used() {
  name="$1"
  output="$2"
  line="$(status_line "$output")"
  set -- $line

  if [ "${2:-}" != "1" ]; then
    fail "$name did not use proxy: $output"
  fi

  printf '%s\n' "$line"
}

expect_proxy_allowed() {
  name="$1"
  shift

  if output="$(curl_base "$@" 2>&1)"; then
    line="$(assert_proxy_used "$name" "$output")"
    case "$line" in
      403\ *) fail "$name was denied by proxy: $output" ;;
    esac

    pass "$name: $line"
    return
  fi

  assert_proxy_used "$name" "$output" >/dev/null
  fail "$name was blocked: $output"
}

expect_proxy_blocked() {
  name="$1"
  shift

  if output="$(curl_base --fail "$@" 2>&1)"; then
    line="$(assert_proxy_used "$name" "$output")"
    fail "$name was allowed: $line"
  fi

  line="$(assert_proxy_used "$name" "$output")"
  pass "$name blocked: $line"
}

expect_direct_blocked() {
  name="$1"
  shift

  if output="$(curl_base --noproxy "*" "$@" 2>&1)"; then
    fail "$name was allowed: $output"
  fi

  pass "$name blocked"
}

expect_proxy_allowed "allowed domain" --location "$ALLOWED_DOMAIN_URL"
if [ -n "$ALLOWED_HTTPS_IP_URL" ]; then
  expect_proxy_allowed "allowed HTTPS IP" --insecure "$ALLOWED_HTTPS_IP_URL"
else
  skip "allowed HTTPS IP not configured"
fi

if [ -n "$ALLOWED_HTTP_IP_URL" ]; then
  expect_proxy_allowed "allowed HTTP IP" "$ALLOWED_HTTP_IP_URL"
else
  skip "allowed HTTP IP not configured"
fi

expect_direct_blocked "direct no-proxy domain" "$ALLOWED_DOMAIN_URL"
expect_proxy_blocked "denied domain" "$DENIED_DOMAIN_URL"
expect_proxy_blocked "denied HTTPS IP" --insecure "$DENIED_HTTPS_IP_URL"
expect_proxy_blocked "denied HTTP IP" "$DENIED_HTTP_IP_URL"
