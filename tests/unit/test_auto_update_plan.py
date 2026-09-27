"""Unit test voor de volgorde en regels van de automatische updates.

Draai in de HA image:
docker run --rm -v "$PWD:/w" -w /w --entrypoint python3 ghcr.io/home-assistant/home-assistant:stable tests/unit/test_auto_update_plan.py
"""
import sys
import types
from unittest.mock import patch

sys.path.insert(0, "custom_components/btechnics_branding")
import importlib.util
spec = importlib.util.spec_from_file_location("auto_update", "custom_components/btechnics_branding/auto_update.py")
au = importlib.util.module_from_spec(spec)
spec.loader.exec_module(au)


class State:
    def __init__(self, eid, latest, installed="1", feat=1 | 8, on=True, title=None):
        self.entity_id = eid
        self.state = "on" if on else "off"
        self.attributes = {"latest_version": latest, "installed_version": installed,
                           "supported_features": feat, "title": title or eid}


class Entry:
    def __init__(self, platform, uid):
        self.platform, self.unique_id = platform, uid


STATES = [
    State("update.home_assistant_core_update", "2026.10.1", "2026.9.3", title="Core"),
    State("update.home_assistant_operating_system_update", "17.1", "17.0", title="OS"),
    State("update.home_assistant_supervisor_update", "2026.10.0", title="Supervisor", feat=1),
    State("update.mosquitto_update", "6.5.0", title="Mosquitto"),
    State("update.btechnics_iot_features_update", "1.32.0", title="Btechnics IOT Features", feat=1),
    State("update.shelly_firmware", "1.5", title="Shelly", feat=1),
    State("update.no_install", "2", title="Enkel melding", feat=0),
    State("update.skipped", "3", title="Overgeslagen", on=False),
]
ENTRIES = {
    "update.home_assistant_core_update": Entry("hassio", "home_assistant_core_version_latest"),
    "update.home_assistant_operating_system_update": Entry("hassio", "home_assistant_os_version_latest"),
    "update.home_assistant_supervisor_update": Entry("hassio", "home_assistant_supervisor_version_latest"),
    "update.mosquitto_update": Entry("hassio", "core_mosquitto_version_latest"),
    "update.btechnics_iot_features_update": Entry("hacs", "12345"),
    "update.shelly_firmware": Entry("shelly", "abc"),
    "update.no_install": Entry("demo", "x"),
}


class Reg:
    def async_get(self, eid):
        return ENTRIES.get(eid)


def run(states, options):
    hass = types.SimpleNamespace(states=types.SimpleNamespace(async_all=lambda d: states))
    with patch.object(au.er, "async_get", lambda h: Reg()):
        return au.plan(hass, options)


fails = 0
def check(name, cond, detail=""):
    global fails
    print(("OK  " if cond else "FOUT"), name, detail)
    fails += 0 if cond else 1

todo, skipped = run(STATES, {"auto_update_categories": ["system", "addons", "hacs"]})
names = [u["name"] for u in todo]
check("volgorde supervisor, app, hacs, core", names == ["Supervisor", "Mosquitto", "Btechnics IOT Features", "Core"], str(names))
check("OS wacht tot volgende nacht", any("OS" in s for s in skipped), str(skipped))
check("firmware niet zonder vinkje", "Shelly" not in names)
check("zonder install-functie nooit", "Enkel melding" not in names)
check("overgeslagen door gebruiker nooit", "Overgeslagen" not in names)
check("back-up enkel waar ondersteund", [u["backup"] for u in todo] == [False, True, False, True], str([u["backup"] for u in todo]))

s2 = list(STATES)
s2[0] = State("update.home_assistant_core_update", "2026.10.0", "2026.9.3", title="Core")
todo, skipped = run(s2, {"auto_update_categories": ["system"]})
names = [u["name"] for u in todo]
check("Core x.0 overgeslagen, OS komt dan wel", "Core" not in names and "OS" in names, str(names) + " " + str(skipped))

s3 = list(STATES)
s3[0] = State("update.home_assistant_core_update", "2026.10.1b2", "2026.9.3", title="Core")
todo, _ = run(s3, {"auto_update_categories": ["system"]})
check("Core beta nooit", "Core" not in [u["name"] for u in todo])

todo, _ = run(STATES, {"auto_update_categories": ["firmware"]})
check("enkel firmware", [u["name"] for u in todo] == ["Shelly"], str([u["name"] for u in todo]))

sys.exit(1 if fails else 0)
