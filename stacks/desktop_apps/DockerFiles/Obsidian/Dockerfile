FROM ghcr.io/linuxserver/baseimage-kasmvnc:debianbookworm

# SHELL ["/bin/bash", "-c"]

RUN \
    echo "**** install packages ****" && \
        # Update and install extra packages.
        apt-get update && \
        apt-get install -y --no-install-recommends \
            # Packages needed to download and extract obsidian.
            curl \
            jq \
            wget \
            libgtk-3-0 \
            libnotify4 \
            libatspi2.0-0 \
            libsecret-1-0 \
            libnss3 && \
    echo "**** cleanup ****" && \
        apt-get autoclean && \
        rm -rf \
        /var/lib/apt/lists/* \
        /var/tmp/* \
        /tmp/*

# Get the specific version of Obsidian
# ARG OBSIDIAN_VERSION=1.5.12
# RUN dl_url="https://github.com/obsidianmd/obsidian-releases/releases/download/v${OBSIDIAN_VERSION}/obsidian_${OBSIDIAN_VERSION}_amd64.deb" && \
#     curl --location --output obsidian.deb "$dl_url" && \
#     dpkg -i obsidian.deb

# Get the latest version of Obsidian
# RUN curl -ks https://api.github.com/repos/obsidianmd/obsidian-releases/releases/latest | grep "browser_download_url.*deb" | cut -d : -f 2,3 | tr -d \" | wget --no-check-certificate -i - \
RUN curl -ks https://api.github.com/repos/obsidianmd/obsidian-releases/releases/latest | jq -r '.assets[] | select(.name | endswith(".deb")).browser_download_url' | wget --no-check-certificate -i - \
    && dpkg -i *.deb

ENV \
    CUSTOM_PORT="3000" \
    CUSTOM_HTTPS_PORT="3001" \
    TITLE="Obsidian" \
    # TITLE="Obsidian v$OBSIDIAN_VERSION" \
    FM_HOME="/vaults"
    # FM_HOME="/config"

# add local files
COPY /root /

EXPOSE 3000
VOLUME ["/config","/vaults"]
