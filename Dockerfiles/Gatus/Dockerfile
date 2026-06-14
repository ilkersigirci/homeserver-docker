ARG IMAGE_VERSION=v5.36.0
FROM ghcr.io/tarampampam/microcheck:1.3.0@sha256:79c187c05bfa67518078bf4db117771942fa8fe107dc79a905861c75ddf28dfa AS microcheck
FROM ghcr.io/twin/gatus:${IMAGE_VERSION}@sha256:c5f210d095fa78e6efaa20ffeb14803f2ba4f10615e16a6d12087697149617f0

COPY --from=microcheck /bin/httpcheck /bin/httpcheck

HEALTHCHECK --interval=2m --timeout=5s --start-period=30s --retries=3 \
  CMD ["/bin/httpcheck", "--timeout", "3", "http://127.0.0.1:8080/health"]
