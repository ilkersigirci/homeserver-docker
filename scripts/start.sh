#! /usr/bin/zsh

STACKS_ROOT=~/docker/stacks

cd $STACKS_ROOT/base
docker compose --env-file ~/docker/configs/.env up -d
cd $STACKS_ROOT/media
docker compose --env-file ~/docker/configs/.env up -d transmission jellyfin ytdl-sub deemix beets
# cd $STACKS_ROOT/others
# docker compose --env-file ~/docker/configs/.env up -d stable-diffusion
cd $STACKS_ROOT/maintanence
docker compose --env-file ~/docker/configs/.env up -d sshwifty code-server czkawka
cd $STACKS_ROOT/monitoring
docker compose --env-file ~/docker/configs/.env up -d glances
cd $STACKS_ROOT/photo
docker compose up -d
cd $STACKS_ROOT/photo-dev
docker compose up -d
cd $STACKS_ROOT/notes
docker compose --env-file ~/docker/configs/.env up -d flatnotes obsidian okular couchdb