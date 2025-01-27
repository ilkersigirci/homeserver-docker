#! /usr/bin/zsh

COMPOSE_ROOT=~/docker/compose

compose=("base" "notes" "others" "desktop_apps" "maintenance" "monitoring")

for stack in "${compose[@]}"
do
    cd "$COMPOSE_ROOT/$stack"
    docker compose --env-file ~/docker/configs/.env down --volumes --remove-orphans
done
