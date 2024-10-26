#! /usr/bin/zsh

STACKS_ROOT=~/docker/stacks

cd $STACKS_ROOT/base
# docker compose --env-file ~/docker/configs/.env pull traefik docker-socket-proxy authelia filebrowser homepage
docker compose --env-file ~/docker/configs/.env pull
docker compose --env-file ~/docker/configs/.env up -d
cd $STACKS_ROOT/media
docker compose --env-file ~/docker/configs/.env pull transmission jellyfin feishin # ytdl-sub deemix beets
docker compose --env-file ~/docker/configs/.env up -d transmission jellyfin feishin # ytdl-sub deemix beets
# cd $STACKS_ROOT/others
# docker compose --env-file ~/docker/configs/.env pull stable-diffusion
# docker compose --env-file ~/docker/configs/.env up -d stable-diffusion
cd $STACKS_ROOT/maintenance
# docker compose --env-file ~/docker/configs/.env build rustic
docker compose --env-file ~/docker/configs/.env pull dozzle code-server  # watchtower sshwifty czkawka
docker compose --env-file ~/docker/configs/.env up -d dozzle code-server  # watchtower sshwifty czkawka
cd $STACKS_ROOT/monitoring
docker compose --env-file ~/docker/configs/.env pull glances netdata
docker compose --env-file ~/docker/configs/.env up -d glances netdata
cd $STACKS_ROOT/photo
docker compose pull
docker compose up -d
cd $STACKS_ROOT/ml
docker compose --env-file ~/docker/configs/.env pull  open-webui
docker compose --env-file ~/docker/configs/.env up -d open-webui open-webui-betus
cd $STACKS_ROOT/notes
# docker pull ghcr.io/linuxserver/baseimage-kasmvnc:alpine318
# docker pull ghcr.io/linuxserver/baseimage-kasmvnc:debianbookworm
# docker compose --env-file ~/docker/configs/.env build obsidian
docker compose --env-file ~/docker/configs/.env pull couchdb flatnotes obsidian
docker compose --env-file ~/docker/configs/.env up -d flatnotes obsidian

# docker image prune --all --force
docker rmi `docker images -f "dangling=true" -q`
