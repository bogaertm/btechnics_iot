#!/usr/bin/env bash
# Start een echte HA container met Btechnics IOT en draait de compatibiliteitstest.
# Gebruik: tests/compat/run.sh [stable|beta|dev|2026.9.1]
set -euo pipefail
TAG="${1:-stable}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="$(mktemp -d)"
mkdir -p "$WORK/config/custom_components"
cp -r "$ROOT/custom_components/btechnics_branding" "$WORK/config/custom_components/"
cat > "$WORK/config/configuration.yaml" <<'YAML'
default_config:
logger:
  default: warning
YAML
docker rm -f bt-ha >/dev/null 2>&1 || true
docker run -d --name bt-ha -p 8123:8123 -v "$WORK/config:/config" \
  "ghcr.io/home-assistant/home-assistant:${TAG}" >/dev/null
echo "HA ${TAG} gestart, config in ${WORK}"
set +e
BT_CONFIG_DIR="$WORK/config" HA_URL="http://localhost:8123" node "$ROOT/tests/compat/check.mjs"
RESULT=$?
set -e
echo "---- HA log (btechnics en fouten) ----"
docker logs bt-ha 2>&1 | grep -iE "btechnics|BT[: ]|Traceback|ERROR" | tail -40 || true
docker rm -f bt-ha >/dev/null 2>&1 || true
exit $RESULT
