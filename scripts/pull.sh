#! /usr/bin/zsh

# TODO: Remove old containers

STACKS_ROOT=~/docker/stacks

cd $STACKS_ROOT/base
docker compose --env-file ~/docker/configs/.env pull
docker compose --env-file ~/docker/configs/.env up -d
cd $STACKS_ROOT/media
docker compose --env-file ~/docker/configs/.env pull transmission jellyfin jellyseerr ytdl-sub
docker compose --env-file ~/docker/configs/.env up -d transmission jellyfin jellyseerr ytdl-sub
cd $STACKS_ROOT/others
docker compose --env-file ~/docker/configs/.env pull couchdb
docker compose --env-file ~/docker/configs/.env up -d couchdb
cd $STACKS_ROOT/monitoring
docker compose --env-file ~/docker/configs/.env pull glances
docker compose --env-file ~/docker/configs/.env up -d glances
cd $STACKS_ROOT/photo
docker compose pull
docker compose up -d

docker image prune --all --force
