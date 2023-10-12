#! /usr/bin/zsh

STACKS_ROOT=~/docker/stacks

cd $STACKS_ROOT/base
docker compose --env-file ~/docker/configs/.env pull
docker compose --env-file ~/docker/configs/.env up -d
cd $STACKS_ROOT/media
docker compose --env-file ~/docker/configs/.env pull transmission jellyfin # ytdl-sub deemix beets
docker compose --env-file ~/docker/configs/.env up -d transmission jellyfin # ytdl-sub deemix beets
# cd $STACKS_ROOT/others
# docker compose --env-file ~/docker/configs/.env pull stable-diffusion
# docker compose --env-file ~/docker/configs/.env up -d stable-diffusion
cd $STACKS_ROOT/maintenance
docker compose --env-file ~/docker/configs/.env pull watchtower sshwifty code-server  # czkawka
docker compose --env-file ~/docker/configs/.env up -d watchtower sshwifty code-server  # czkawka
cd $STACKS_ROOT/monitoring
docker compose --env-file ~/docker/configs/.env pull glances
docker compose --env-file ~/docker/configs/.env up -d glances
# cd $STACKS_ROOT/photo
# docker compose pull
# docker compose up -d
cd $STACKS_ROOT/photo-dev
docker compose pull
docker compose up -d
cd $STACKS_ROOT/notes
docker pull ghcr.io/linuxserver/baseimage-kasmvnc:alpine318
docker pull ghcr.io/linuxserver/baseimage-kasmvnc:debianbookworm
docker compose --env-file ~/docker/configs/.env build obsidian
docker compose --env-file ~/docker/configs/.env pull flatnotes
docker compose --env-file ~/docker/configs/.env up -d couchdb flatnotes obsidian

docker image prune --all --force
