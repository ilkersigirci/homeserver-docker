#!/bin/bash

# Usage: docker exec -u abc ytdl-sub ./config/download_yt.sh <VIDEO_LINK>
# Usage with temp container: docker-compose --env-file ~/docker/.env run --rm -d ytdl-sub ./config/download_yt.sh <VIDEO_LINK>

# Default arg
# ARG2=${2:-'Video'}

# To test run with ytdl-sub --dry-run dl

# TODO: Run this without copying inside container


if [ -z "$1" ]
    then
        echo "No video url supplied"
        exit 1
fi

cd config

if [ -z "$2" ]
    then
        echo "No folder name supplied, downloading to default 'Video' folder"
        ytdl-sub dl --single-video-with-foldername --overrides.tv_show_name "Video" --youtube.video_url $1
    else
        # ytdl-sub dl --single-video "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        echo "Downloading to $2 folder"
        ytdl-sub dl --single-video-with-foldername --overrides.tv_show_name "$2" --youtube.video_url $1
fi
