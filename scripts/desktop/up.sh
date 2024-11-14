#! /usr/bin/zsh

# NOTE: Only for essential stacks

STACKS_ROOT=~/docker/stacks

############################### MINIMUM RESOURCE ##################################


# cd $STACKS_ROOT/base
# docker compose --env-file ~/docker/configs/.env up -d
# # cd $STACKS_ROOT/media
# # docker compose --env-file ~/docker/configs/.env up -d transmission jellyfin # ytdl-sub deemix beets
# # cd $STACKS_ROOT/others
# # docker compose --env-file ~/docker/configs/.env up -d stable-diffusion
# cd $STACKS_ROOT/maintenance
# docker compose --env-file ~/docker/configs/.env up -d sshwifty # code-server czkawka
# cd $STACKS_ROOT/monitoring
# docker compose --env-file ~/docker/configs/.env up -d glances
# # cd $STACKS_ROOT/photo
# # docker compose up -d
# cd $STACKS_ROOT/notes
# docker compose --env-file ~/docker/configs/.env up -d couchdb flatnotes obsidian


############################### NORMAL ##################################

cd $STACKS_ROOT/base
# docker compose --env-file ~/docker/configs/.env up -d traefik docker-socket-proxy authelia filebrowser
docker compose --env-file ~/docker/configs/.env up -d
cd $STACKS_ROOT/media
docker compose --env-file ~/docker/configs/.env up -d transmission jellyfin feishin # ytdl-sub deemix beets
cd $STACKS_ROOT/maintenance
docker compose --env-file ~/docker/configs/.env up -d dozzle code-server stirlingpdf it-tools convertx # rustic czkawka sshwifty watchtower
cd $STACKS_ROOT/monitoring
docker compose --env-file ~/docker/configs/.env up -d beszel watchyourlan #glances netdata
cd $STACKS_ROOT/photo
docker compose up -d
cd $STACKS_ROOT/ml
docker compose --env-file ~/docker/configs/.env up -d open-webui open-webui-betus
cd $STACKS_ROOT/notes
docker compose --env-file ~/docker/configs/.env up -d flatnotes obsidian
# cd $STACKS_ROOT/others
# docker compose --env-file ~/docker/configs/.env up -d stable-diffusion
