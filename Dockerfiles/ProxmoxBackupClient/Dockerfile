# syntax=docker/dockerfile:1.26@sha256:ecfaec9ed6d810b56388c508f4121597bfbba70d41a6dfeee4d8cad5f295fc32
# renovate: datasource=deb depName=proxmox-backup-client
ARG IMAGE_VERSION=4.2.4-1

FROM debian:13.6-slim@sha256:3a39a0592364683e6bab97937b72cad5a8fa6dcbbee90edb3bb48c7f8e94f258

ARG IMAGE_VERSION

ADD --checksum=sha256:136673be77aba35dcce385b28737689ad64fd785a797e57897589aed08db6e45 \
    https://enterprise.proxmox.com/debian/proxmox-archive-keyring-trixie.gpg \
    /usr/share/keyrings/proxmox-archive-keyring.gpg
COPY pbs-client.sources /etc/apt/sources.list.d/pbs-client.sources

RUN chmod 0644 /usr/share/keyrings/proxmox-archive-keyring.gpg \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends \
        ca-certificates \
        "proxmox-backup-client=${IMAGE_VERSION}" \
    && rm -rf /var/lib/apt/lists/* \
    && useradd \
        --create-home \
        --home-dir /home/pbs \
        --no-log-init \
        --shell /usr/sbin/nologin \
        --uid 1000 \
        --user-group \
        pbs \
    && install --directory --owner=pbs --group=pbs --mode=0700 /home/pbs/.config/proxmox-backup \
    && install --directory --owner=pbs --group=pbs --mode=0755 /backups

LABEL org.opencontainers.image.description="Rootless multi-architecture container for the official Proxmox Backup Client" \
      org.opencontainers.image.documentation="https://pbs.proxmox.com/docs/backup-client.html" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.source="https://git.proxmox.com/?p=proxmox-backup.git" \
      org.opencontainers.image.title="Proxmox Backup Client" \
      org.opencontainers.image.version="${IMAGE_VERSION}"

ENV HOME=/home/pbs \
    XDG_CACHE_HOME=/tmp/.cache

USER pbs:pbs
RUN proxmox-backup-client version
WORKDIR /backups

ENTRYPOINT ["proxmox-backup-client"]
CMD ["version"]
