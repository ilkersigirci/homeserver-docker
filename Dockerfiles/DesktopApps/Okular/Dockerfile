FROM ghcr.io/linuxserver/baseimage-kasmvnc:alpine317@sha256:e67ff31da12e6908fc6acbeaba499f9339794b1b622bcb2d945286a7257b755d

RUN apk add --no-cache okular

COPY /root /

ENV \
    CUSTOM_PORT="3000" \
    CUSTOM_HTTPS_PORT="3001" \
    TITLE="Okular" \
    FM_HOME="/books"

# add local files
COPY /root /

EXPOSE 3000
VOLUME ["/config","/books"]
