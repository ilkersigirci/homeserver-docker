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

## Setup

- Authelia
- ![Authelia Schema](https://camo.githubusercontent.com/9b4a111baec20c4f677b38d818b1142f5eae5a20e8d1d17c33fb1d9b339e0105/68747470733a2f2f7777772e61757468656c69612e636f6d2f696d616765732f61726368692e706e67)


- Create Secrets
```bash
tr -cd '[:alnum:]' </dev/urandom | fold -w "64" | head -n 1 | tr -d '\n' | sudo tee $HOME/docker/secrets/example_secret
```