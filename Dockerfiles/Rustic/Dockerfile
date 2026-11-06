FROM alpine:latest@sha256:3f4d6b32e26703c6082839234f43769d5046b3ac7c910033911d1e71d8cd630a

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
