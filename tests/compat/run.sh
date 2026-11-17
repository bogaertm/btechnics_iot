#!/usr/bin/env bash
# Start een echte HA container met Btechnics IOT en draait de compatibiliteitstest.
# Gebruik: tests/compat/run.sh [stable|beta|dev|2026.9.1]
set -euo pipefail
TAG="${1:-stable}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="$(mktemp -d)"
mkdir -p "$WORK/config/custom_components"
cp -r "$ROOT/custom_components/btechnics_branding" "$WORK/config/custom_components/"
# v1.55.0: vanaf HA 2026.11 neemt de ingebouwde Marktplaats HACS over (de loader
# geeft het domein hacs door aan marketplace). Dan testen we met een nep-Marktplaats.
docker pull -q "ghcr.io/home-assistant/home-assistant:${TAG}" >/dev/null 2>&1 || true
HAV="$(docker run --rm --entrypoint python3 "ghcr.io/home-assistant/home-assistant:${TAG}" -c 'import homeassistant.const as c;print(c.__version__)')"
STORE=hacs
if python3 -c "import sys;v=[int(x) for x in sys.argv[1].split('.')[:2]];sys.exit(0 if v>=[2026,11] else 1)" "$HAV"; then STORE=marketplace; fi
echo "HA ${HAV}: test met ${STORE}"
cp -r "$ROOT/tests/compat/fake_update/bt_fake" "$ROOT/tests/compat/fake_update/$STORE" "$ROOT/tests/compat/fake_update/btechnics_toegang" "$WORK/config/custom_components/"
cat > "$WORK/config/configuration.yaml" <<YAML
default_config:
update:
  - platform: bt_fake
  - platform: ${STORE}
btechnics_toegang:
logger:
  default: warning
YAML
docker rm -f bt-ha >/dev/null 2>&1 || true
docker run -d --name bt-ha -p 8123:8123 -v "$WORK/config:/config" \
  "ghcr.io/home-assistant/home-assistant:${TAG}" >/dev/null
echo "HA ${TAG} gestart, config in ${WORK}"
set +e
BT_STORE="$STORE" BT_CONFIG_DIR="$WORK/config" HA_URL="http://localhost:8123" node "$ROOT/tests/compat/check.mjs"
RESULT=$?
set -e
echo "---- HA log (btechnics en fouten) ----"
docker logs bt-ha 2>&1 | grep -iE "btechnics|BT[: ]|Traceback|ERROR" | tail -40 || true
[ "${KEEP:-0}" = 1 ] || docker rm -f bt-ha >/dev/null 2>&1 || true
exit $RESULT
