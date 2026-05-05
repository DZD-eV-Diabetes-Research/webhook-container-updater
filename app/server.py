#!/usr/bin/env python3
"""Webhook receiver that triggers docker compose pull + up when DockerHub pushes a matching tag."""

import json
import logging
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, cast

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

WEBHOOK_TOKEN = os.environ["WEBHOOK_TOKEN"]
WATCH_TAG = os.environ["WATCH_TAG"]
COMPOSE_PROJECT_NAME = os.environ["COMPOSE_PROJECT_NAME"]
COMPOSE_SERVICES = os.environ.get("COMPOSE_SERVICES", "")

HOOK_PATH = f"/hooks/update-{WEBHOOK_TOKEN}"
COMPOSE_FILE = "/compose/docker-compose.yml"


def run_update() -> str:
    services: list[str] = COMPOSE_SERVICES.split() if COMPOSE_SERVICES.strip() else []
    base: list[str] = ["docker", "compose", "-f", COMPOSE_FILE, "-p", COMPOSE_PROJECT_NAME]
    env: dict[str, str] = {**os.environ, "COMPOSE_PROJECT_NAME": COMPOSE_PROJECT_NAME}

    pull_cmd = base + ["pull"] + services
    up_cmd = base + ["up", "-d", "--no-deps", "--force-recreate"] + services

    output_parts: list[str] = []
    for cmd in (pull_cmd, up_cmd):
        log.info("Running: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        combined = (result.stdout + result.stderr).strip()
        output_parts.append(combined)
        if combined:
            log.info(combined)
        if result.returncode != 0:
            log.error("Command failed (exit %d): %s", result.returncode, " ".join(cmd))
            break

    return "\n".join(output_parts)


def _extract_str(data: dict[str, Any], key: str, default: str = "") -> str:
    value = data.get(key)
    return str(value) if value is not None else default


class WebhookHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        log.info("HTTP %s - %s", self.address_string(), format % args)

    def _send(self, code: int, body: str) -> None:
        encoded = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self) -> None:
        if self.path != HOOK_PATH:
            log.warning("Unknown path: %s", self.path)
            self._send(404, "not found")
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""

        try:
            parsed: Any = json.loads(raw) if raw else {}
            payload: dict[str, Any] = cast(dict[str, Any], parsed) if isinstance(parsed, dict) else {}
        except json.JSONDecodeError as exc:
            log.warning("Invalid JSON: %s", exc)
            self._send(400, "invalid json")
            return

        push_data_raw = payload.get("push_data")
        repository_raw = payload.get("repository")
        push_data: dict[str, Any] = cast(dict[str, Any], push_data_raw) if isinstance(push_data_raw, dict) else {}
        repository: dict[str, Any] = cast(dict[str, Any], repository_raw) if isinstance(repository_raw, dict) else {}
        tag = _extract_str(push_data, "tag")
        repo = _extract_str(repository, "repo_name", "<unknown>")
        log.info("Received push event: %s:%s", repo, tag)

        if tag != WATCH_TAG:
            log.info("Tag %r does not match WATCH_TAG %r — ignoring", tag, WATCH_TAG)
            self._send(200, "ignored")
            return

        log.info("Tag matched — starting update")
        output = run_update()
        log.info("Update complete")
        self._send(200, output or "done")

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send(200, "ok")
        else:
            self._send(404, "not found")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 9000))
    log.info(
        "Starting webhook-container-updater on port %d "
        "(hook path: /hooks/update-****, watch_tag: %s, project: %s, services: %r)",
        port, WATCH_TAG, COMPOSE_PROJECT_NAME, COMPOSE_SERVICES,
    )
    server = HTTPServer(("", port), WebhookHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down")
