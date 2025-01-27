#! /usr/bin/zsh

# NOTE: Only for essential compose

COMPOSE_ROOT=~/docker/compose

############################### MINIMUM RESOURCE ##################################


# cd $COMPOSE_ROOT/base
# docker compose --env-file ~/docker/configs/.env up -d
# # cd $COMPOSE_ROOT/media
# # docker compose --env-file ~/docker/configs/.env up -d transmission jellyfin # ytdl-sub deemix beets
# # cd $COMPOSE_ROOT/others
# # docker compose --env-file ~/docker/configs/.env up -d stable-diffusion
# cd $COMPOSE_ROOT/maintenance
# docker compose --env-file ~/docker/configs/.env up -d sshwifty # code-server czkawka
# cd $COMPOSE_ROOT/monitoring
# docker compose --env-file ~/docker/configs/.env up -d glances
# # cd $COMPOSE_ROOT/photo
# # docker compose up -d
# cd $COMPOSE_ROOT/notes
# docker compose --env-file ~/docker/configs/.env up -d couchdb flatnotes obsidian


############################### NORMAL ##################################

cd $COMPOSE_ROOT/base
# docker compose --env-file ~/docker/configs/.env up -d traefik docker-socket-proxy authelia filebrowser
docker compose --env-file ~/docker/configs/.env up -d
cd $COMPOSE_ROOT/media
docker compose --env-file ~/docker/configs/.env up -d transmission jellyfin jellysearch jellyseerr feishin # ytdl-sub deemix beets
cd $COMPOSE_ROOT/maintenance
docker compose --env-file ~/docker/configs/.env up -d dozzle code-server stirlingpdf it-tools convertx # rustic czkawka sshwifty watchtower
cd $COMPOSE_ROOT/monitoring
docker compose --env-file ~/docker/configs/.env up -d beszel watchyourlan #glances netdata
cd $COMPOSE_ROOT/photo
docker compose up -d
cd $COMPOSE_ROOT/ml
docker compose --env-file ~/docker/configs/.env up -d open-webui open-webui-betus
cd $COMPOSE_ROOT/notes
docker compose --env-file ~/docker/configs/.env up -d flatnotes obsidian linkwarden
# cd $COMPOSE_ROOT/others
# docker compose --env-file ~/docker/configs/.env up -d stable-diffusion
