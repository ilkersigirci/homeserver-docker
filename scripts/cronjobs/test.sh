#!/bin/bash

# Add below to your crontab
# * * * * * ~/docker/scripts/cronjobs/test.sh

echo "Cron job executed at $(date)" >> ~/docker/logs/test_cron_log.txt
