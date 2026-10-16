# Video consultations: setup and external-network requirements

CivicBridge uses a self-hosted **LiveKit** SFU (`livekit/livekit-server:v1.13.8`). The CivicBridge API owns authorization and lifecycle; LiveKit carries media. Configuration: `infra/livekit/livekit.yaml`, compose service `livekit`.

## What works out of the box

The default configuration is for **one computer**: browsers on the Docker host at `http://localhost:8084`.

| Path | Port | Exposure |
|---|---|---|
| Signalling (websocket) | `ws://localhost:8084/rtc` → nginx → `livekit:7880` | same origin as the app |
| Media over UDP | `127.0.0.1:50100-50160/udp` | host loopback only |
| Media over TCP fallback | `127.0.0.1:7891/tcp` | host loopback only |
| Server API and webhook | `livekit:7880` ↔ `backend:8000` | Docker network only |

LiveKit runs with `--node-ip ${LIVEKIT_NODE_IP:-127.0.0.1}` and `use_external_ip: false`, so it does not contact public STUN servers. Rooms are created only by the backend (`auto_create: false`). Recording is disabled by a locked policy.

**Verified level:** automated three-browser calls on one host with Chromium fake camera/microphone devices (`frontend/e2e/video.spec.ts`): admission, media frames decoded by a remote participant, per-viewer document access, removal of a connected participant, server-side room check, meeting end. Not verified: real cameras and microphones, other devices on a LAN, the internet, TURN, or browsers other than Chromium.

## Using video from other devices (LAN)

Browsers allow camera and microphone only on `https://` origins or `localhost`. For other devices you need TLS.

1. Choose the host's LAN address, e.g. `192.168.1.20`, and a hostname that resolves to it, e.g. `civicbridge.lan`.
2. Put a TLS-terminating reverse proxy in front of port 8084 (for example Caddy or nginx with a certificate trusted by the devices). Proxy `/` and the `/rtc` websocket to `127.0.0.1:8084`.
3. Create `.env` next to `docker-compose.yml`:
   ```
   CB_PUBLIC_ORIGIN=https://civicbridge.lan
   CB_ALLOWED_ORIGINS=https://civicbridge.lan
   CB_LIVEKIT_PUBLIC_URL=wss://civicbridge.lan
   CB_CSP_CONNECT_EXTRA=wss://civicbridge.lan
   CB_COOKIE_SECURE=true
   LIVEKIT_NODE_IP=192.168.1.20
   LIVEKIT_BIND_IP=0.0.0.0
   ```
   Keep `WEB_BIND_IP=127.0.0.1` if your TLS proxy runs on the same host.
4. Allow inbound UDP 50100-50160 and TCP 7891 to the host in the host firewall.
5. `docker compose up -d` to apply. Check with two devices.

## Internet participants

In addition to the LAN steps:

- A public DNS name and a publicly trusted certificate.
- `LIVEKIT_NODE_IP` set to the public IP (or `use_external_ip: true` in `livekit.yaml` to discover it via STUN).
- The UDP range and TCP 7891 forwarded from the router or cloud firewall.
- A **TURN** server for participants behind symmetric NAT or networks that block UDP. LiveKit has a built-in TURN server (`turn:` section in `livekit.yaml`, needs its own TLS certificate and ports 443/TCP or 3478/UDP); configure it per the LiveKit documentation. CivicBridge does not ship a TURN configuration.
- Review rate limits, logging and retention for a public deployment; this installation is a local demo.

## How authorization is enforced

1. Invitees must hold an eligible role on the case (citizen owner, participating authority or institution staff, delegated professional with `attend_meetings`, or an interpreter).
2. The host opens the meeting; others ask to join and wait. Tokens are issued only to admitted participants (`POST /api/meetings/{id}/token`), scoped to that room, valid for 10 minutes.
3. Removal calls LiveKit's `RemoveParticipant`. A signed webhook (`participant_joined`) kicks any identity not currently admitted, and the worker reconciles every 10 seconds.
4. Documents shared in a meeting are authorized per viewer on each preview.

## Troubleshooting

| Symptom | Check |
|---|---|
| "Could not connect to the media server" | `docker compose ps livekit`; `curl -i http://localhost:8084/rtc/validate` should return 401 (reached LiveKit). |
| Connected but no video | UDP 50100-50160 blocked or `LIVEKIT_NODE_IP` not reachable from the browser; TCP 7891 is the fallback. |
| Camera/microphone not offered | Page not on `https://` or `localhost`; browser site permissions. |
| CSP error for `ws://…` in the console | Add the websocket origin to `CB_CSP_CONNECT_EXTRA` and recreate the `frontend` container. |
| Removed participant still visible briefly | Expected up to the 10-second reconciliation interval if the immediate kick failed; check `GET /api/meetings/{id}/room-check` as host. |
