# Draaien: docker run --rm -v "$PWD:/w:ro" --entrypoint python3 ghcr.io/home-assistant/home-assistant:stable /w/tests/unit/test_backup_busy.py
# v1.48.1: Core update mislukte op 25/10 met "Backup manager busy: create_backup".
import asyncio, sys
sys.path.insert(0, "/w")
from unittest.mock import MagicMock
import custom_components.btechnics_branding.auto_update as au


class FakeStore:
    def __init__(self, *a, **k): self.saved = None
    async def async_load(self): return None
    def async_delay_save(self, fn, d): self.saved = fn()
au.Store = FakeStore


class Mgr:
    def __init__(self, state): self.state = state


class St:
    def __init__(s, eid, latest, inst):
        s.entity_id = eid; s.state = "on"
        s.attributes = {"latest_version": latest, "installed_version": inst,
                        "supported_features": 1 | 8, "title": "Home Assistant Core"}


class Ent:
    platform = "hassio"; unique_id = "home_assistant_core_version"; hidden_by = None


ok = True
def check(name, cond, info=""):
    global ok; ok &= bool(cond); print(("OK  " if cond else "FOUT"), name, info)


def make_hass(manager_state, install):
    core = St("update.home_assistant_core_update", "2026.10.3", "2026.10.2")
    hass = MagicMock()
    hass.states.async_all = lambda d: [core]
    hass.states.get = lambda eid: core
    hass.services.has_service = lambda *a: False
    calls = []
    async def async_call(domain, service, data=None, blocking=False):
        calls.append((domain, service, dict(data or {})))
        if (domain, service) == ("update", "install"):
            await install(hass, data)
    hass.services.async_call = async_call
    tr = au.Tracker(hass)
    hass.data = {au._DATA_TRACKER: tr}
    if manager_state is not None:
        hass.data["backup"] = Mgr(manager_state)
    return hass, tr, calls


reg = MagicMock(); reg.async_get = lambda eid: Ent()
au.er.async_get = lambda h: reg
au._branding_broken = lambda h: False
async def no_refresh(h): return {"fouten": []}
au.async_refresh_hacs_custom = no_refresh
au.async_sync_visibility = lambda *a, **k: None
au.async_dispatcher_send = lambda *a, **k: None
au.BACKUP_RETRY_WAIT = 0.05  # v1.48.2: busy wordt eerst opnieuw geprobeerd
OPTS = {"auto_update": True, "auto_update_categories": ["system", "addons", "hacs"], "auto_update_backup": True}
EID = "update.home_assistant_core_update"


async def main():
    # 1. status lezen
    h, _, _ = make_hass(None, None)
    check("geen back-upintegratie: None", au.backup_state(h) is None)
    h, _, _ = make_hass("create_backup", None)
    check("status create_backup gelezen", au.backup_state(h) == "create_backup")
    check("busy-fout herkend", au.backup_busy_error(Exception("Error creating backup: Backup manager busy: create_backup")))
    check("andere fout niet", not au.backup_busy_error(Exception("timeout")))

    # 2. wachten tot vrij: na 0,3 s wordt de manager idle, daarna gewoon installeren
    async def install_ok(hass, data):
        hass.states.get(EID).attributes["installed_version"] = "2026.10.3"
    h, tr, calls = make_hass("create_backup", install_ok)
    au.BACKUP_POLL = 0.05
    async def free_later():
        await asyncio.sleep(0.3); h.data["backup"].state = "idle"
    asyncio.get_running_loop().create_task(free_later())
    res = await au._async_run_locked(h, OPTS, "test")
    inst = [c for c in calls if c[:2] == ("update", "install")]
    check("wacht en installeert daarna", len(inst) == 1 and inst[0][2].get("backup") is True and res["installed"], res)
    check("geen mislukte poging", not res["failed"] and tr.count(EID, "2026.10.3") == 0, tr.attempts)

    # 3. blijft bezig na de wachttijd: niet installeren, niet als poging tellen
    h, tr, calls = make_hass("create_backup", install_ok)
    au.BACKUP_WAIT = 0.2
    res = await au._async_run_locked(h, OPTS, "test")
    check("niet geinstalleerd bij blijvend bezig", not [c for c in calls if c[:2] == ("update", "install")])
    check("overgeslagen met reden", any("back-up van HA nog bezig" in s for s in res["skipped"]), res["skipped"])
    check("telt niet als poging", not res["failed"] and tr.count(EID, "2026.10.3") == 0, tr.attempts)
    au.BACKUP_WAIT = 30 * 60

    # 4. net tegelijk gestart: busy-fout uit install telt niet als poging
    async def install_busy(hass, data):
        raise Exception("Error creating backup: Backup manager busy: create_backup")
    h, tr, calls = make_hass("idle", install_busy)
    res = await au._async_run_locked(h, OPTS, "test")
    check("busy-fout niet bij mislukt", not res["failed"], res)
    check("busy-fout teller terug op 0", tr.count(EID, "2026.10.3") == 0, tr.attempts)
    check("busy-fout overgeslagen", any("back-up van HA bezig" in s for s in res["skipped"]), res["skipped"])

    # 5. een echte fout telt nog altijd
    async def install_err(hass, data):
        raise Exception("Supervisor fout")
    h, tr, calls = make_hass("idle", install_err)
    res = await au._async_run_locked(h, OPTS, "test")
    check("echte fout telt als poging", res["failed"] and tr.count(EID, "2026.10.3") == 1, (res["failed"], tr.attempts))

    # 6. undo_attempt laat eerdere pogingen staan
    tr.add_attempt(EID, "2026.10.3"); tr.undo_attempt(EID, "2026.10.3")
    check("undo_attempt: 2 wordt 1", tr.count(EID, "2026.10.3") == 1)

    # 7. zonder back-up gevraagd: niet wachten
    h, tr, calls = make_hass("create_backup", install_ok)
    res = await au._async_run_locked(h, dict(OPTS, auto_update_backup=False), "test")
    inst = [c for c in calls if c[:2] == ("update", "install")]
    check("zonder back-up meteen installeren", len(inst) == 1 and "backup" not in inst[0][2], inst)

asyncio.run(main())
print("RESULTAAT", "ALLES OK" if ok else "FOUTEN")
sys.exit(0 if ok else 1)
