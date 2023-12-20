#! /usr/bin/zsh

STACKS_ROOT=~/docker/stacks

cd $STACKS_ROOT/base
docker compose --env-file ~/docker/configs/.env pull
docker compose --env-file ~/docker/configs/.env up -d
# cd $STACKS_ROOT/others
# docker compose --env-file ~/docker/configs/.env pull stable-diffusion
# docker compose --env-file ~/docker/configs/.env up -d stable-diffusion
cd $STACKS_ROOT/maintenance
docker compose --env-file ~/docker/configs/.env build rustic
docker compose --env-file ~/docker/configs/.env up -d rustic
cd $STACKS_ROOT/monitoring
docker compose --env-file ~/docker/configs/.env pull glances netdata
docker compose --env-file ~/docker/configs/.env up -d glances netdata
cd $STACKS_ROOT/notes
docker pull ghcr.io/linuxserver/baseimage-kasmvnc:alpine318
docker pull ghcr.io/linuxserver/baseimage-kasmvnc:debianbookworm
docker compose --env-file ~/docker/configs/.env build obsidian
docker compose --env-file ~/docker/configs/.env pull flatnotes
docker compose --env-file ~/docker/configs/.env up -d couchdb flatnotes obsidian

docker image prune --all --force
