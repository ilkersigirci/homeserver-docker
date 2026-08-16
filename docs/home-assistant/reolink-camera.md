# Reolink E1 Pro in Home Assistant

This setup keeps Reolink device control in Home Assistant and uses
WebRTC/go2rtc only for two-way talk. Frigate is not required.

## Components

- Official Home Assistant Reolink integration: camera entity, PTZ, switches, and
  device controls.
- HACS `advanced-camera-card`: normal camera UI.
- HACS `WebRTC Camera` by AlexxIT: go2rtc-backed talk stream.
- Traefik: must allow browser microphone access for the Home Assistant host.

## Camera Settings

Enable these in the Reolink app or client:

- RTSP
- ONVIF

Use the camera local account, not Reolink cloud credentials.

## go2rtc

Create `configs/home-assistant/go2rtc.yaml`:

```yaml
streams:
  e1pro:
    - onvif://CAMERA_USER:CAMERA_PASSWORD@192.168.2.120:8000/
    - ffmpeg:rtsp://CAMERA_USER:CAMERA_PASSWORD@192.168.2.120:554/Preview_01_main#video=copy#audio=opus
```

URL-encode special characters in the password if needed.

After installing the HACS WebRTC Camera integration, add it once in Home
Assistant:

```text
Settings -> Devices & services -> Add integration -> WebRTC Camera
```

Leave the URL blank so the integration starts its managed go2rtc instance and
reads `/config/go2rtc.yaml`.

## Home Assistant Helper

Add this to `configs/home-assistant/configuration.yaml`:

```yaml
input_boolean:
  e1pro_talk:
    name: E1 Pro Talk
    icon: mdi:microphone
```

Restart Home Assistant after changing this file.

## Dashboard

The dashboard uses mutually exclusive cards:

- `input_boolean.e1pro_talk == off`: show Start Talk and Advanced Camera Card.
- `input_boolean.e1pro_talk == on`: show Stop Talk and the mic-enabled WebRTC
  card.

Dashboard YAML equivalent:

```yaml
type: grid
cards:
  - type: heading
    heading_style: title
    heading: Camera

  - type: vertical-stack
    cards:
      - type: conditional
        conditions:
          - entity: input_boolean.e1pro_talk
            state: "off"
        card:
          type: custom:advanced-camera-card
          cameras:
            - camera_entity: camera.livingroomcamera_fluent

      - type: conditional
        conditions:
          - entity: input_boolean.e1pro_talk
            state: "on"
        card:
          type: custom:webrtc-camera
          url: e1pro
          mode: webrtc
          media: video,audio,microphone
          ui: true
          muted: false

      - type: conditional
        conditions:
          - entity: input_boolean.e1pro_talk
            state: "off"
        card:
          type: button
          entity: input_boolean.e1pro_talk
          name: Start talk
          icon: mdi:microphone
          tap_action:
            action: toggle

      - type: conditional
        conditions:
          - entity: input_boolean.e1pro_talk
            state: "on"
        card:
          type: button
          entity: input_boolean.e1pro_talk
          name: Stop talk
          icon: mdi:microphone-off
          tap_action:
            action: toggle
```

This avoids showing two live streams during talk mode.

## Traefik

Browser microphone capture is blocked if the response header contains:

```text
Permissions-Policy: camera=(), microphone=()
```

The shared relaxed middleware still blocks camera and microphone. Home Assistant
uses a dedicated middleware instead.

In `configs/traefik3/rules/middlewares-secure-headers.yml`:

```yaml
middlewares-secure-headers-home-assistant:
  headers:
    <<: *headers-relaxed
    permissionsPolicy: "camera=(self), microphone=(self), geolocation=(), payment=(), usb=()"
```

In `configs/traefik3/rules/chain-no-auth.yml`:

```yaml
chain-no-auth-home-assistant:
  chain:
    middlewares:
      - middlewares-rate-limit-public-app
      - middlewares-secure-headers-home-assistant
```

If CrowdSec is enabled, keep the same CrowdSec middlewares used by the other
chains before the rate limit middleware.

In `configs/traefik3/rules.specific/rpi0.yml`, route Home Assistant through the
Home Assistant-specific chain:

```yaml
home-assistant-rtr:
  rule: "Host(`smarthome.{{env "DOMAINNAME"}}`)"
  entryPoints:
    - websecure
  middlewares:
    - chain-no-auth-home-assistant
  service: home-assistant-svc
```

Verify the live header:

```bash
curl -k -sS -I https://smarthome.home.ilkerflix.com/ | rg -i 'permissions-policy'
```

Expected:

```text
permissions-policy: camera=(self), microphone=(self), geolocation=(), payment=(), usb=()
```

## Client Notes

- Home Assistant must be opened over HTTPS.
- Android Companion app may need:
  - microphone permission enabled in Android app settings
  - Companion app frontend cache reset
  - app force-close and reopen
- If the HA app fails but Chrome works, the issue is usually Android WebView
  permission/cache state.

## Future Work: Frigate

If Frigate is deployed later, it can own the camera media pipeline and simplify
the dashboard:

- Advanced Camera Card can use its documented Frigate/go2rtc two-way-audio path.
- The separate `custom:webrtc-camera` talk card may no longer be needed.
- The `input_boolean.e1pro_talk` helper and conditional Start/Stop card swap may
  no longer be needed.
- go2rtc stream definitions can move from Home Assistant to
  `configs/frigate/config.yml`.
- go2rtc/ffmpeg media handling can move off the Raspberry Pi 4 Home Assistant
  host and onto the Frigate host.

Tradeoffs:

- Frigate adds service, MQTT, and camera configuration complexity.
- Recording should be explicitly disabled or tightly retained if disk wear is a
  concern.
- Keep the official Reolink integration unless Frigate fully replaces every
  needed device control. Frigate supports ONVIF PTZ controls, but Reolink-specific
  HA entities such as privacy mode and camera settings are still better through
  the official Reolink integration.

## Validation

After edits, run:

```bash
uvx prek run --files \
  configs/home-assistant/go2rtc.yaml \
  configs/home-assistant/configuration.yaml \
  configs/home-assistant/.storage/lovelace.dashboard_smart_devices \
  configs/traefik3/rules/middlewares-secure-headers.yml \
  configs/traefik3/rules/chain-no-auth.yml \
  configs/traefik3/rules.specific/rpi0.yml
```

Check Home Assistant config:

```bash
docker exec home-assistant python -m homeassistant --script check_config --config /config
```
