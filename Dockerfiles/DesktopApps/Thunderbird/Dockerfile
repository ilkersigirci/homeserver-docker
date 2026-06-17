FROM ghcr.io/linuxserver/baseimage-kasmvnc:debianbookworm@sha256:c6129530811450448ab760064b27e111fb3351fc3222af652f605a48eb518ed7

RUN apt-get update && \
    apt-get install -y --no-install-recommends thunderbird && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY /root /

ENV \
    CUSTOM_PORT="3000" \
    CUSTOM_HTTPS_PORT="3001" \
    TITLE="Thunderbird" \
    FM_HOME="/config"

# add local files
COPY /root /

EXPOSE 3000
VOLUME ["/config"]
