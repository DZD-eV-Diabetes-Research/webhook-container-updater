#!/usr/bin/env bash
# Local smoke test for webhook-container-updater.
# Builds the image, starts a container, exercises all request paths, then cleans up.
set -euo pipefail

IMAGE="webhook-container-updater:test"
CONTAINER="wcu-smoke-test"
PORT=19000
TOKEN="testtoken123"
HOOK="/hooks/update-${TOKEN}"
BASE="http://localhost:${PORT}"

pass() { echo "  PASS: $*"; }
fail() { echo "  FAIL: $*"; exit 1; }

cleanup() {
  docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> Building image ${IMAGE}"
docker build -q -t "${IMAGE}" .

echo "==> Starting container"
docker run -d --name "${CONTAINER}" \
  -p "${PORT}:9000" \
  -e WEBHOOK_TOKEN="${TOKEN}" \
  -e WATCH_TAG="dev" \
  -e COMPOSE_PROJECT_NAME="myproject" \
  -e COMPOSE_SERVICES="myapp" \
  "${IMAGE}" >/dev/null

# Wait for server to be ready
for i in $(seq 1 10); do
  if curl -sf "${BASE}/healthz" >/dev/null 2>&1; then break; fi
  sleep 0.3
done

echo "==> Test: GET /healthz"
body=$(curl -sf "${BASE}/healthz")
[ "${body}" = "ok" ] && pass "/healthz returned 'ok'" || fail "/healthz returned '${body}'"

echo "==> Test: POST to unknown path → 404"
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/hooks/update-wrongtoken")
[ "${code}" = "404" ] && pass "unknown path returned 404" || fail "expected 404, got ${code}"

echo "==> Test: POST with non-matching tag → 200 'ignored'"
body=$(curl -s -X POST "${BASE}${HOOK}" \
  -H "Content-Type: application/json" \
  -d '{"push_data":{"tag":"latest"},"repository":{"repo_name":"myorg/myapp"}}')
[ "${body}" = "ignored" ] && pass "non-matching tag returned 'ignored'" || fail "expected 'ignored', got '${body}'"

echo "==> Test: POST with matching tag → 202 Accepted (update runs in background)"
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}${HOOK}" \
  -H "Content-Type: application/json" \
  -d '{"push_data":{"tag":"dev"},"repository":{"repo_name":"myorg/myapp"}}')
[ "${code}" = "202" ] && pass "matching tag returned HTTP 202" || fail "expected 202, got ${code}"

echo "==> Test: POST with invalid JSON → 400"
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}${HOOK}" \
  -H "Content-Type: application/json" \
  -d 'not-json')
[ "${code}" = "400" ] && pass "invalid JSON returned 400" || fail "expected 400, got ${code}"

echo ""
echo "==> Container logs:"
docker logs "${CONTAINER}"

echo ""
echo "==> All tests passed."
