#! /usr/bin/zsh

STACKS_ROOT=~/docker/stacks

cd $STACKS_ROOT/base
docker compose --env-file ~/docker/configs/.env down --volumes --remove-orphans
cd $STACKS_ROOT/media
docker compose --env-file ~/docker/configs/.env down --volumes --remove-orphans
cd $STACKS_ROOT/others
docker compose --env-file ~/docker/configs/.env down --volumes --remove-orphans
cd $STACKS_ROOT/monitoring
docker compose --env-file ~/docker/configs/.env down --volumes --remove-orphans
cd $STACKS_ROOT/photo
docker compose down --volumes --remove-orphans