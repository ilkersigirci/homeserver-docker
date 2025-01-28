# Homeserver Docker

- Essential commands

```bash
# Start selected components
bash scripts/docker-manage.sh up

# Stop selected components
bash scripts/docker-manage.sh down

# Pull latest images
bash scripts/docker-manage.sh pull
```

- Start containers at machine start-up

```bash
nano $HOME/.config/autostart/start.sh.desktop

[Desktop Entry]
Type=Application
Exec=$HOME/docker/scripts/docker-manage.sh up
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Name[en_US]=Start Docker Apps
Name=Start Docker Apps
Comment[en_US]=
Comment=
```