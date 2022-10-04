#!/bin/bash

# Usage: docker exec -u abc ytdl-sub ./config/download_yt.sh <VIDEO_LINK>
# Usage with temp container: docker-compose --env-file ~/docker/.env run --rm -d ytdl-sub ./config/download_yt.sh <VIDEO_LINK>
# Alias: alias ytdl='docker-compose --file ~/docker/stacks/media/docker-compose.yml --env-file ~/docker/.env run --rm -d ytdl-sub ./config/download_yt.sh'

# Default arg
# ARG2=${2:-'Video'}

# NOTE: To test it, run with ytdl-sub --dry-run dl 

# TODO: Run this without copying inside container


# Download part of a youtube video ->> Command line version
# yt-dlp https://www.youtube.com/watch?v=xMOHrl_is4Y --downloader ffmpeg --downloader-args "ffmpeg_i:-ss 00:00:01.00 -to 00:00:02.00"


if [ -z "$1" ]
    then
        echo "No video url supplied"
        exit 1
fi

cd config

if [ -z "$2" ]
then
    echo "No folder name supplied, downloading to default 'Video' folder"
    ytdl-sub dl --single-video $1
elif [ $2 = "Metadata" ]
then
    echo "Downloading just metadata to Metadata folder"
    ytdl-sub dl --single-video-metadata $1
    # TODO: Remove .cache and .mp4 video file
else
    # ytdl-sub dl --single-video "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    echo "Downloading to $2 folder"
    ytdl-sub --dry-run dl --single-video-with-foldername $1 --overrides.tv_show_name "$2"
fi
