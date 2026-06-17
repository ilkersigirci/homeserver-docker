FROM alpine:latest@sha256:28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b

# Define build argument for Rustic version
ARG RUSTIC_VERSION=v0.5.4

# Install required packages
RUN apk add --update --no-cache curl rclone tzdata

WORKDIR /root

# Rustic: download, unpack, move into PATH
RUN curl -L -o rustic.tar.gz "https://github.com/rustic-rs/rustic/releases/download/${RUSTIC_VERSION}/rustic-${RUSTIC_VERSION}-x86_64-unknown-linux-musl.tar.gz" && \
  tar xzf ./rustic.tar.gz && \
  mv rustic /bin/ && \
  rm ./rustic.tar.gz

# Add crontab file
COPY crontab /etc/crontabs/root

# Run cron
ENTRYPOINT crond -f -d 8
