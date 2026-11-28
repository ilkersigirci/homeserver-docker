ARG IMAGE_VERSION=v5.38.0
FROM ghcr.io/tarampampam/microcheck:1.4.0@sha256:c9f79cd408626de7c10f2d487d67339f49adf0ba61dde96ede65343269db1f85 AS microcheck
FROM ghcr.io/twin/gatus:${IMAGE_VERSION}@sha256:085ed63da963728965d00a3c78aa6167e3bf135218485b893201758e079e8415

COPY --from=microcheck /bin/httpcheck /bin/httpcheck

HEALTHCHECK --interval=2m --timeout=5s --start-period=30s --retries=3 \
  CMD ["/bin/httpcheck", "--timeout", "3", "http://127.0.0.1:8080/health"]
