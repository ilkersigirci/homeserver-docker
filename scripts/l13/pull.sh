#! /usr/bin/zsh

COMPOSE_ROOT=~/docker/compose

cd $COMPOSE_ROOT/base
docker compose --env-file ~/docker/configs/.env pull
docker compose --env-file ~/docker/configs/.env up -d
# cd $COMPOSE_ROOT/others
# docker compose --env-file ~/docker/configs/.env pull stable-diffusion
# docker compose --env-file ~/docker/configs/.env up -d stable-diffusion
cd $COMPOSE_ROOT/maintenance
# docker compose --env-file ~/docker/configs/.env build rustic
docker compose --env-file ~/docker/configs/.env pull dozzle wumps
docker compose --env-file ~/docker/configs/.env up -d dozzle wumps # rustic
cd $COMPOSE_ROOT/monitoring
docker compose --env-file ~/docker/configs/.env pull glances netdata
docker compose --env-file ~/docker/configs/.env up -d glances netdata
cd $COMPOSE_ROOT/notes
# docker pull ghcr.io/linuxserver/baseimage-kasmvnc:alpine318
# docker pull ghcr.io/linuxserver/baseimage-kasmvnc:debianbookworm
# docker compose --env-file ~/docker/configs/.env build obsidian
docker compose --env-file ~/docker/configs/.env pull couchdb flatnotes obsidian
docker compose --env-file ~/docker/configs/.env up -d flatnotes obsidian

# docker image prune --all --force
docker rmi `docker images -f "dangling=true" -q`