# Multi-stage build for minimal final image
FROM golang:1.27-alpine@sha256:738d1cf061836894ff6bb8c33881080ac66de8cf0586615012a0c8f592649cfa AS builder

# Install git (required for go install)
RUN apk add --no-cache git ca-certificates

# Create non-root user for build
RUN adduser -D -s /bin/sh appuser

# Set working directory
WORKDIR /build

# Install Scotty from source
RUN go install go.uploadedlobster.com/scotty@latest

# Final minimal image
FROM alpine:latest@sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6

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
