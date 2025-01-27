#! /usr/bin/zsh

COMPOSE_ROOT=~/docker/compose

cd $COMPOSE_ROOT/base
# docker compose --env-file ~/docker/configs/.env pull traefik docker-socket-proxy authelia filebrowser homepage
docker compose --env-file ~/docker/configs/.env pull
docker compose --env-file ~/docker/configs/.env up -d
cd $COMPOSE_ROOT/media
docker compose --env-file ~/docker/configs/.env pull transmission jellyfin jellysearch jellyseerr feishin # ytdl-sub deemix beets
docker compose --env-file ~/docker/configs/.env up -d transmission jellyfin jellysearch jellyseerr feishin # ytdl-sub deemix beets
# cd $COMPOSE_ROOT/others
# docker compose --env-file ~/docker/configs/.env pull stable-diffusion
# docker compose --env-file ~/docker/configs/.env up -d stable-diffusion
cd $COMPOSE_ROOT/maintenance
# docker compose --env-file ~/docker/configs/.env build rustic
docker compose --env-file ~/docker/configs/.env pull dozzle code-server stirlingpdf it-tools convertx
docker compose --env-file ~/docker/configs/.env up -d dozzle code-server stirlingpdf it-tools convertx
cd $COMPOSE_ROOT/monitoring
docker compose --env-file ~/docker/configs/.env pull beszel watchyourlan
docker compose --env-file ~/docker/configs/.env up -d beszel watchyourlan
cd $COMPOSE_ROOT/photo
docker compose pull
docker compose up -d
cd $COMPOSE_ROOT/ml
docker compose --env-file ~/docker/configs/.env pull  open-webui
docker compose --env-file ~/docker/configs/.env up -d open-webui open-webui-betus
cd $COMPOSE_ROOT/notes
# docker pull ghcr.io/linuxserver/baseimage-kasmvnc:alpine318
# docker pull ghcr.io/linuxserver/baseimage-kasmvnc:debianbookworm
# docker compose --env-file ~/docker/configs/.env build obsidian
docker compose --env-file ~/docker/configs/.env pull couchdb flatnotes obsidian linkwarden
docker compose --env-file ~/docker/configs/.env up -d flatnotes obsidian linkwarden

# docker image prune --all --force
docker rmi `docker images -f "dangling=true" -q`
