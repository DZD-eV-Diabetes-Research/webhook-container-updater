# webhook-container-updater

A self-hosted, event-driven replacement for Watchtower. Receives DockerHub push webhooks and runs `docker compose pull` + `docker compose up --force-recreate` for the configured services. No polling, no scheduled jobs — only acts when DockerHub tells it to.

See **[EXAMPLE.md](EXAMPLE.md)** for a full walkthrough with Traefik, Let's Encrypt, and a hello-world web app.

## How it works

1. You register a webhook in DockerHub pointing at this container's `/hooks/update-<WEBHOOK_TOKEN>` path.
2. When DockerHub pushes a new image it POSTs a JSON payload to that URL.
3. The server checks `push_data.tag` against `WATCH_TAG`.
4. If the tag matches it runs:
   ```
   docker compose -f /compose/docker-compose.yml pull <COMPOSE_SERVICES>
   docker compose -f /compose/docker-compose.yml up -d --no-deps --force-recreate <COMPOSE_SERVICES>
   ```
5. Non-matching tags are silently acknowledged (HTTP 200 `ignored`).

## Configuration

All configuration is via environment variables.

| Variable               | Required | Description                                               |
|------------------------|----------|-----------------------------------------------------------|
| `WEBHOOK_TOKEN`        | yes      | Secret token that forms part of the webhook URL           |
| `WATCH_TAG`            | yes      | Only trigger on this DockerHub tag (e.g. `latest`, `dev`) |
| `COMPOSE_PROJECT_NAME` | yes      | Must match the host Compose project name                  |
| `COMPOSE_SERVICES`     | yes      | Space-separated list of services to update                |

## Compose integration

```yaml
services:
  webhook-updater:
    image: dzdde/webhook-container-updater:latest
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - .:/compose:ro
    environment:
      WEBHOOK_TOKEN: "${WEBHOOK_TOKEN}"
      WATCH_TAG: "dev"
      COMPOSE_PROJECT_NAME: "${COMPOSE_PROJECT_NAME}"
      COMPOSE_SERVICES: "myapp myapp-worker"
    ports:
      - "9000:9000"
```

Mount your `docker-compose.yml` (and any `.env` it needs) read-only at `/compose`. The container uses the host Docker socket to run compose commands as if it were on the host.

## DockerHub webhook setup

In your DockerHub repository → **Webhooks**, add a webhook URL:

```
https://<your-domain>/hooks/update-<WEBHOOK_TOKEN>
```

DockerHub sends a POST with a JSON body on every push. Only pushes whose `push_data.tag` equals `WATCH_TAG` trigger an update.

## Health check

`GET /healthz` returns `200 ok` and can be used as a liveness probe.

## Endpoints

| Method | Path                         | Description                      |
|--------|------------------------------|----------------------------------|
| POST   | `/hooks/update-<TOKEN>`      | DockerHub webhook receiver       |
| GET    | `/healthz`                   | Liveness probe                   |

## Logging

Every request and its outcome is logged to stdout:

```
2025-01-15 12:00:00,123 INFO Starting webhook-container-updater on port 9000 ...
2025-01-15 12:00:05,456 INFO Received push event: myorg/myapp:dev
2025-01-15 12:00:05,457 INFO Tag matched — starting update
2025-01-15 12:00:05,458 INFO Running: docker compose -f /compose/docker-compose.yml pull myapp
2025-01-15 12:00:12,789 INFO Update complete
```
