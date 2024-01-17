#!/bin/bash
set -e

# NOTE: Make sure to copy this file to llama.cpp/.devops/start_server.sh && and set permission as chmod 777 start_server.sh 

# Read the first argument into a variable
arg1="$1"

# Shift the arguments to remove the first one
shift

if [[ "$arg1" == "--only_llma_server" ]]; then
    echo "Starting only llama server"
    ./server --host 0.0.0.0 --port 8080 "$@"
elif [[ "$arg1" == "--only_openapi_server" ]]; then
    echo "Starting llama && openapi server"
    ./server --host 127.0.0.1 --port 5000 "$@" &
    python3  /api_like_OAI.py --llama-api http://127.0.0.1:5000 --host 0.0.0.0 --port 8080
else
    echo "Unknown argument: $arg1"
    exit 1
fi