#! /usr/bin/zsh

# others,photo
COMPOSE_PROFILES=core,ml,maintenance,media,monitoring,reading docker compose --env-file ~/docker/.env up -d