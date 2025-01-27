#! /usr/bin/zsh

COMPOSE_ROOT=~/docker/compose

compose=("base" "notes" "media" "others" "desktop_apps" "maintenance" "monitoring" "ml")

for stack in "${compose[@]}"
do
    cd "$COMPOSE_ROOT/$stack"
    docker compose --env-file ~/docker/configs/.env down --volumes --remove-orphans
done

# Photo dir
cd "$COMPOSE_ROOT/photo"
docker compose down --volumes --remove-orphans