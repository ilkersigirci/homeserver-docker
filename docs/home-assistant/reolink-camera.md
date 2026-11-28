# Reolink E1 Pro in Home Assistant

Open **Devices → Camera** for live video and PTZ. **Open two-way talk** opens
the microphone-enabled view in the current browser. Use the back arrow to leave
it. Each browser controls its own talk session.

The official Reolink integration supplies the camera entity to Advanced Camera
Card. The WebRTC Camera integration runs go2rtc for two-way audio. On a new
installation, enable RTSP and ONVIF on the E1 Pro, add the Reolink integration
with a local camera account, install the dashboard resources, and add **WebRTC
Camera** under **Settings → Devices & services**. Leave its server URL blank
to start the managed go2rtc instance.

## Credentials and networking

Ansible writes the `reolink.camera` login to rpi0's `.env` as `REOLINK_USER`
and `REOLINK_PASSWORD`. Compose passes both to Home Assistant. go2rtc inserts
them directly into the stream URLs, so use URL-safe camera credentials (letters,
digits, `-`, `.`, `_` or `~`). After changing the login, update the vault and
the Reolink integration, then run `just ansible-deploy --limit rpi0 --tags env,compose`.
[Stream configuration](../../configs/home-assistant/go2rtc.yaml)

The go2rtc HTTP API (1984) and RTSP server (8554) bind to loopback. Home
Assistant handles signaling. WebRTC uses port 8555 for media. For microphone
capture, open Home Assistant over HTTPS and grant microphone access to the site
or Companion app. The rpi0 Traefik router uses `chain-no-auth-media-devices`,
which allows same-origin microphone access. [Traefik router](../../configs/traefik3/rules.specific/rpi0.yml)

To check the media path from rpi0, inspect the listeners and probe the video
codec of the named stream:

```bash
ss -lntu | rg ':(1984|8554|8555)\b'
docker exec home-assistant ffprobe -v error -rtsp_transport tcp \
  -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 \
  rtsp://127.0.0.1:8554/e1pro
```
