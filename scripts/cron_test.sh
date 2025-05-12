#!/bin/bash

# Add below to your crontab
# * * * * * ~/docker/scripts/cron_test.sh

echo "Cron job executed at $(date)" >> ~/docker/scripts/cron_log.txt