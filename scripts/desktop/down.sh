#! /usr/bin/zsh

STACKS_ROOT=~/docker/stacks

stacks=("base" "notes" "media" "others" "desktop_apps" "maintenance" "monitoring" "ml")

for stack in "${stacks[@]}"
do
    cd "$STACKS_ROOT/$stack"
    docker compose --env-file ~/docker/configs/.env down --volumes --remove-orphans
done

# Photo dir
cd "$STACKS_ROOT/photo"
docker compose down --volumes --remove-orphans