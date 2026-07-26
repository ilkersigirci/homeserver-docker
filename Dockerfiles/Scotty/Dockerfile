# Multi-stage build for minimal final image
FROM golang:1.26-alpine@sha256:0178a641fbb4858c5f1b48e34bdaabe0350a330a1b1149aabd498d0699ff5fb2 AS builder

# Install git (required for go install)
RUN apk add --no-cache git ca-certificates

# Create non-root user for build
RUN adduser -D -s /bin/sh appuser

# Set working directory
WORKDIR /build

# Install Scotty from source
RUN go install go.uploadedlobster.com/scotty@latest

# Final minimal image
FROM alpine:latest@sha256:28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b

# Install ca-certificates and shadow (for usermod/groupmod)
RUN apk --no-cache add ca-certificates shadow su-exec

# Create default group and user
RUN addgroup -g 1000 -S appgroup && \
    adduser -u 1000 -G appgroup -S -s /bin/sh appuser

# Copy the binary from builder stage
COPY --from=builder /go/bin/scotty /usr/local/bin/scotty

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh

# Make entrypoint executable
RUN chmod +x /entrypoint.sh

# Set environment variables with defaults
ENV PUID=1000
ENV PGID=1000

# Set the entrypoint
ENTRYPOINT ["/entrypoint.sh"]

# Default command (show help)
CMD ["scotty", "--help"]

# Set the entrypoint
ENTRYPOINT ["scotty"]

# Default command (show help)
CMD ["--help"]
