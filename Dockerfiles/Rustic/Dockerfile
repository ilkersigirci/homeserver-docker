FROM alpine:latest@sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6

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
