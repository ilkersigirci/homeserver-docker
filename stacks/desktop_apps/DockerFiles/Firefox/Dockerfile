FROM ghcr.io/linuxserver/baseimage-kasmvnc:alpine318
RUN apk add --no-cache firefox
COPY /root /

ENV \
    TITLE="Firefox"

EXPOSE 3000
# VOLUME ["/downloads"]