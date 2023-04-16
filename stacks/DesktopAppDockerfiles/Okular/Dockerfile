FROM ghcr.io/linuxserver/baseimage-kasmvnc:alpine317

RUN apk add --no-cache okular

COPY /root /

ENV \
    CUSTOM_PORT="3000" \
    CUSTOM_HTTPS_PORT="3001" \
    TITLE="Obsidian v$OBSIDIAN_VERSION" \
    FM_HOME="/books"

# add local files
COPY /root /

EXPOSE 3000
VOLUME ["/config","/books"]