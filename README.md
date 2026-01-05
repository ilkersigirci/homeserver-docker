# Homeserver Docker

![Services](./resources/services.png)


Essential commands

```bash
# Start selected components
bash scripts/docker-manage.sh up

# Stop selected components
bash scripts/docker-manage.sh down

# Pull latest images
bash scripts/docker-manage.sh pull
```

Useful aliases

```bash
alias dup="docker compose --file $HOME/docker/compose/$MY_HOSTNAME.yml up"
alias ddown="docker compose --file $HOME/docker/compose/$MY_HOSTNAME.yml down --volumes --remove-orphans"
alias drm="docker compose --file $HOME/docker/compose/$MY_HOSTNAME.yml rm -svf"
alias dpull="docker compose --file $HOME/docker/compose/$MY_HOSTNAME.yml pull"
alias dbuild="docker compose --file $HOME/docker/compose/$MY_HOSTNAME.yml build"
```

Start containers at machine start-up

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