#! /usr/bin/zsh

STACKS_ROOT=~/docker/stacks

cd $STACKS_ROOT/base
docker compose --env-file ~/docker/configs/.env pull
docker compose --env-file ~/docker/configs/.env up -d
cd $STACKS_ROOT/notes
docker compose --env-file ~/docker/configs/.env pull flatnotes obsidian
docker compose --env-file ~/docker/configs/.env up -d flatnotes obsidian
cd $STACKS_ROOT/media
docker compose --env-file ~/docker/configs/.env pull transmission jellyfin jellyseerr ytdl-sub
docker compose --env-file ~/docker/configs/.env up -d transmission jellyfin jellyseerr ytdl-sub
# cd $STACKS_ROOT/others
# docker compose --env-file ~/docker/configs/.env pull stable-diffusion
# docker compose --env-file ~/docker/configs/.env up -d stable-diffusion
cd $STACKS_ROOT/maintanence
docker compose --env-file ~/docker/configs/.env pull code-server
docker compose --env-file ~/docker/configs/.env up -d code-server
cd $STACKS_ROOT/monitoring
docker compose --env-file ~/docker/configs/.env pull glances
docker compose --env-file ~/docker/configs/.env up -d glances
cd $STACKS_ROOT/photo
docker compose pull
docker compose up -d

docker image prune --all --force
