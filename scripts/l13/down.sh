#! /usr/bin/zsh

STACKS_ROOT=~/docker/stacks

stacks=("base" "notes" "others" "desktop_apps" "maintenance" "monitoring")

for stack in "${stacks[@]}"
do
    cd "$STACKS_ROOT/$stack"
    docker compose --env-file ~/docker/configs/.env down --volumes --remove-orphans
done
