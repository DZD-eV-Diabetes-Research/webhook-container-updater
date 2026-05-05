# Full example: hello-world app with Traefik and auto-updates

This walkthrough sets up a complete stack on a single VPS:

- **Traefik** as the reverse proxy, handling HTTPS via Let's Encrypt
- **hello-world** — a simple nginx-based web app served at `https://hello.example.com`
- **webhook-container-updater** — receives DockerHub push webhooks and restarts `hello-world` automatically whenever a new image is pushed

By the end, pushing a new image to DockerHub will automatically redeploy `hello-world` on your server without any manual SSH.

---

## Prerequisites

- A VPS with Docker and Docker Compose v2 installed
- A domain name pointing at your VPS (`example.com` in this guide — replace with your own)
- A DockerHub account with a repository for your hello-world image

---

## Directory layout

```
/opt/hello-world/
├── docker-compose.yml
└── .env
```

Create the directory:

```bash
mkdir -p /opt/hello-world
cd /opt/hello-world
```

---

## 1. Create a shared Traefik network

Traefik and the app containers need to share a Docker network so Traefik can route to them.

```bash
docker network create traefik-public
```

---

## 2. Generate a webhook token

The token is the only thing preventing arbitrary users from triggering deploys. Use a random string:

```bash
openssl rand -hex 32
# e.g. a3f8c2e1d9b047f6a1234567890abcdef01234567890abcdef01234567890abc
```

---

## 3. The `.env` file

```bash
# /opt/hello-world/.env

# Must match the directory name or be set explicitly
COMPOSE_PROJECT_NAME=hello-world

# Paste the token generated above
WEBHOOK_TOKEN=a3f8c2e1d9b047f6a1234567890abcdef01234567890abcdef01234567890abc

# Your domain
DOMAIN=example.com

# Email for Let's Encrypt notifications
ACME_EMAIL=admin@example.com
```

Keep this file secret — it contains the webhook token.

---

## 4. The `docker-compose.yml`

```yaml
# /opt/hello-world/docker-compose.yml

networks:
  traefik-public:
    external: true

services:

  # ── Traefik ─────────────────────────────────────────────────────────────────
  traefik:
    image: traefik:v3.3
    restart: unless-stopped
    command:
      - --providers.docker=true
      - --providers.docker.exposedByDefault=false
      - --providers.docker.network=traefik-public
      - --entrypoints.web.address=:80
      - --entrypoints.web.http.redirections.entrypoint.to=websecure
      - --entrypoints.web.http.redirections.entrypoint.scheme=https
      - --entrypoints.websecure.address=:443
      - --certificatesresolvers.le.acme.tlschallenge=true
      - --certificatesresolvers.le.acme.email=${ACME_EMAIL}
      - --certificatesresolvers.le.acme.storage=/letsencrypt/acme.json
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - traefik-letsencrypt:/letsencrypt
    networks:
      - traefik-public

  # ── Hello World app ──────────────────────────────────────────────────────────
  hello-world:
    image: nginxdemos/hello:latest
    restart: unless-stopped
    networks:
      - traefik-public
    labels:
      - traefik.enable=true
      - traefik.http.routers.hello.rule=Host(`${DOMAIN}`)
      - traefik.http.routers.hello.entrypoints=websecure
      - traefik.http.routers.hello.tls.certresolver=le
      - traefik.http.services.hello.loadbalancer.server.port=80

  # ── Webhook updater ──────────────────────────────────────────────────────────
  webhook-updater:
    image: dzdde/webhook-container-updater:latest
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - .:/compose:ro
    environment:
      WEBHOOK_TOKEN: "${WEBHOOK_TOKEN}"
      WATCH_TAG: "latest"
      COMPOSE_PROJECT_NAME: "${COMPOSE_PROJECT_NAME}"
      COMPOSE_SERVICES: "hello-world"
    networks:
      - traefik-public
    labels:
      - traefik.enable=true
      # Expose only the /hooks/ path — never the whole container
      - traefik.http.routers.wh.rule=Host(`${DOMAIN}`) && PathPrefix(`/hooks/`)
      - traefik.http.routers.wh.entrypoints=websecure
      - traefik.http.routers.wh.tls.certresolver=le
      - traefik.http.services.wh.loadbalancer.server.port=9000

volumes:
  traefik-letsencrypt:
```

Key points:

- Traefik handles TLS termination. The webhook updater sits behind it and is only reachable at `/hooks/` — the secret token in the path provides the second layer of protection.
- `COMPOSE_SERVICES: "hello-world"` tells the updater to only pull and recreate the `hello-world` service, leaving Traefik and the updater itself untouched.
- `.:/compose:ro` mounts the project directory (the one containing `docker-compose.yml`) read-only inside the updater, so it can invoke compose on behalf of the host.

---

## 5. Start the stack

```bash
docker compose up -d
```

Check that everything came up:

```bash
docker compose ps
```

Visit `https://example.com` — you should see the nginx hello-world page.

---

## 6. Register the DockerHub webhook

1. Go to your DockerHub repository → **Webhooks** tab.
2. Click **Create Webhook**.
3. Set the URL to:

   ```
   https://example.com/hooks/update-<YOUR_WEBHOOK_TOKEN>
   ```

4. Save.

DockerHub will send a test ping immediately. You can confirm it was received in the updater logs:

```bash
docker compose logs webhook-updater
```

---

## 7. Test end-to-end

Push a new image to DockerHub:

```bash
docker pull nginxdemos/hello:latest        # or build your own image
docker tag nginxdemos/hello:latest your-dockerhub-user/hello-world:latest
docker push your-dockerhub-user/hello-world:latest
```

Within seconds the updater will log:

```
INFO Received push event: your-dockerhub-user/hello-world:latest
INFO Tag matched — starting update
INFO Running: docker compose -f /compose/docker-compose.yml pull hello-world
INFO Running: docker compose -f /compose/docker-compose.yml up -d --no-deps --force-recreate hello-world
INFO Update complete
```

And `hello-world` will be running the new image — no SSH needed.

---

## Troubleshooting

**Webhook not firing**
Check that port 443 is open on the VPS and that the DNS A record for your domain points to its IP. DockerHub requires a publicly reachable HTTPS endpoint.

**`open /compose/docker-compose.yml: no such file or directory`**
The `- .:/compose:ro` volume bind uses the directory where `docker compose` is invoked, which must be `/opt/hello-world`. If you start the stack from elsewhere, use an absolute path: `- /opt/hello-world:/compose:ro`.

**Wrong tag received — update not triggered**
Double-check that `WATCH_TAG` in `.env` matches the tag you pushed to DockerHub. The comparison is exact.

**Traefik returns 404 for `/hooks/`**
Confirm `traefik-public` network exists (`docker network ls`) and that the updater container joined it. Check `docker compose logs traefik` for routing errors.
