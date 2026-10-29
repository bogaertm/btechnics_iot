# Draaien: docker run --rm -v "$PWD:/w:ro" --entrypoint python3 ghcr.io/home-assistant/home-assistant:stable /w/tests/unit/test_update_retry.py
# v1.48.2: Core 2026.10.4 mislukte op 26 en 27/10 (iot.bogaert.me) telkens 30 s na de start:
# "Error creating backup: Backup failed: ... Preparing backup of Home Assistant Core failed.
# Failed to inform HA Core: Unsuccessful websocket message". Daarnaast vertrok de melding
# "2 keer mislukt" al bij de start van poging 2.
import asyncio, sys
sys.path.insert(0, "/w")
from unittest.mock import MagicMock
import custom_components.btechnics_branding.auto_update as au


class FakeStore:
    def __init__(self, *a, **k): self.saved = None
    async def async_load(self): return None
    def async_delay_save(self, fn, d): self.saved = fn()
au.Store = FakeStore

BACKUP_ERR = ("Error creating backup: Backup failed: [{'type': 'HomeAssistantBackupError', 'message': "
              "\"Preparing backup of Home Assistant Core failed. Failed to inform HA Core: Unsuccessful "
              "websocket message - Could not lock database within 30 seconds.\"}]")
EID = "update.home_assistant_core_update"


class St:
    def __init__(s):
        s.entity_id = EID; s.state = "on"
        s.attributes = {"latest_version": "2026.10.4", "installed_version": "2026.10.2",
                        "supported_features": 1 | 8, "title": "Home Assistant Core"}


class Ent:
    platform = "hassio"; unique_id = "home_assistant_core_version"; hidden_by = None


class Issues:
    def __init__(s): s.created = []; s.items = {}
    def async_get_issue(s, domain, iid): return s.items.get(iid)


ok = True
def check(name, cond, info=""):
    global ok; ok &= bool(cond); print(("OK  " if cond else "FOUT"), name, info)


reg = MagicMock(); reg.async_get = lambda eid: Ent()
au.er.async_get = lambda h: reg
au._branding_broken = lambda h: False
async def no_refresh(h): return {"fouten": []}
au.async_refresh_hacs_custom = no_refresh
au.async_dispatcher_send = lambda *a, **k: None
au.BACKUP_RETRY_WAIT = 0.05
au.BACKUP_POLL = 0.01
OPTS = {"auto_update": True, "auto_update_categories": ["system", "addons", "hacs"], "auto_update_backup": True}


def make(install, attempts_before=0, backup=True):
    core = St()
    hass = MagicMock()
    hass.states.async_all = lambda d: [core]
    hass.states.get = lambda eid: core
    hass.services.has_service = lambda *a: False
    calls = []
    async def async_call(domain, service, data=None, blocking=False):
        if (domain, service) == ("update", "install"):
            calls.append(dict(data or {}))
            await install(hass, data, len(calls))
    hass.services.async_call = async_call
    tr = au.Tracker(hass)
    for _ in range(attempts_before):
        tr.add_attempt(EID, "2026.10.4")
    hass.data = {au._DATA_TRACKER: tr, au._DATA_GETOPTS: lambda: dict(OPTS, auto_update_backup=backup)}
    issues = Issues()
    au.ir.async_get = lambda h: issues
    def create(h, domain, iid, **kw):
        issues.created.append(iid); issues.items[iid] = object()
    au.ir.async_create_issue = create
    au.ir.async_delete_issue = lambda h, d, iid: issues.items.pop(iid, None)
    return hass, tr, calls, issues, core


def events(hass):
    return [e["message"] for e in hass.data.get(au._DATA_EVENTS, [])]


async def main():
    check("fout herkend als tijdelijk", au.backup_retryable(Exception(BACKUP_ERR)))
    check("andere fout niet", not au.backup_retryable(Exception("Downloading Home Assistant version 2026.10.4 failed")))

    # 1. eerste poging back-upfout, tweede lukt
    async def flaky(hass, data, n):
        if n == 1:
            raise Exception(BACKUP_ERR)
        hass.states.get(EID).attributes["installed_version"] = "2026.10.4"
    h, tr, calls, iss, _ = make(flaky)
    res = await au._async_run_locked(h, dict(OPTS), "test")
    check("1: opnieuw geprobeerd en gelukt", len(calls) == 2 and res["installed"] and not res["failed"], res)
    check("1: teller terug op 0", tr.count(EID, "2026.10.4") == 0, tr.attempts)
    check("1: logregel nieuwe poging", any("nieuwe poging over" in m for m in events(h)), events(h))

    # 2. blijft mislukken: 3 pogingen, telt als 1 mislukte poging
    async def always(hass, data, n): raise Exception(BACKUP_ERR)
    h, tr, calls, iss, _ = make(always)
    res = await au._async_run_locked(h, dict(OPTS), "test")
    check("2: 1 + 2 herhalingen", len(calls) == 1 + au.BACKUP_RETRIES, len(calls))
    check("2: mislukt met volledige oorzaak", res["failed"] and "Could not lock database" in res["failed"][0], res["failed"])
    check("2: telt als 1 poging", tr.count(EID, "2026.10.4") == 1, tr.attempts)

    # 3. downloadfout die blijft: herhaald, daarna mislukt
    async def dl(hass, data, n): raise Exception("Error updating Home Assistant Core: Downloading Home Assistant version 2026.10.4 failed")
    h, tr, calls, iss, _ = make(dl)
    res = await au._async_run_locked(h, dict(OPTS), "test")
    check("3: blijvende downloadfout: 3 pogingen, dan mislukt", len(calls) == 1 + au.BACKUP_RETRIES and res["failed"], len(calls))
    async def other(hass, data, n): raise Exception("Supervisor fout: niet genoeg schijfruimte")
    h, tr, calls, iss, _ = make(other)
    res = await au._async_run_locked(h, dict(OPTS), "test")
    check("3b: andere fout niet herhaald", len(calls) == 1 and res["failed"], len(calls))

    # 4. zonder back-up: niet herhalen
    h, tr, calls, iss, _ = make(always, backup=False)
    res = await au._async_run_locked(h, dict(OPTS, auto_update_backup=False), "test")
    check("4: zonder back-up niet herhaald", len(calls) == 1, len(calls))

    # 5. poging 2: geen melding tijdens de installatie, wel na het resultaat
    seen_during = []
    async def fail_and_sync(hass, data, n):
        au.async_sync_visibility(hass, dict(OPTS))  # zoals de state listener doet
        seen_during.append(list(iss5.created))
        raise Exception("Supervisor fout")
    h, tr, calls, iss5, _ = make(fail_and_sync, attempts_before=1)
    res = await au._async_run_locked(h, dict(OPTS), "test")
    check("5: geen melding tijdens poging 2", seen_during == [[]], seen_during)
    check("5: wel melding na mislukte poging 2", ("update_failed_" + EID) in iss5.created, iss5.created)
    check("5: markering opgeruimd", not au.is_installing(h, EID))

    # 6. poging 2 lukt: nooit een melding
    async def ok_and_sync(hass, data, n):
        au.async_sync_visibility(hass, dict(OPTS))
        hass.states.get(EID).attributes["installed_version"] = "2026.10.4"
        hass.states.get(EID).state = "off"
    h, tr, calls, iss6, _ = make(ok_and_sync, attempts_before=1)
    res = await au._async_run_locked(h, dict(OPTS), "test")
    check("6: poging 2 gelukt, geen melding", not iss6.created and res["installed"], (iss6.created, res))

    # 7. downloadfout: opnieuw geprobeerd, ook zonder back-up
    async def dl_once(hass, data, n):
        if n == 1:
            raise Exception("Error updating Home Assistant Core: Downloading Home Assistant version 2026.10.4 failed")
        hass.states.get(EID).attributes["installed_version"] = "2026.10.4"
    h, tr, calls, iss, _ = make(dl_once, backup=False)
    res = await au._async_run_locked(h, dict(OPTS, auto_update_backup=False), "test")
    check("7: downloadfout opnieuw geprobeerd en gelukt", len(calls) == 2 and res["installed"], (len(calls), res))
    check("7: logregel download", any(m.startswith("download voor") for m in events(h)), events(h))

    # 8. controle na herstart
    from datetime import timedelta
    from homeassistant.util import dt as dt_util
    au._MODULE_START = dt_util.utcnow()
    def with_attempt(installed, state, done=False):
        h, tr, calls, iss, core = make(always)
        tr.add_attempt(EID, "2026.10.4")
        tr.attempts[EID]["last"] = (au._MODULE_START - timedelta(minutes=20)).isoformat()
        if done:
            tr.mark_done(EID)
        core.attributes["installed_version"] = installed
        core.state = state
        au.async_sync_visibility(h, dict(OPTS))
        return h, tr
    h, tr = with_attempt("2026.10.2", "on")
    check("8: niet actief na herstart gemeld", any("na de herstart niet actief" in m for m in events(h)), events(h))
    au.async_sync_visibility(h, dict(OPTS))
    check("8: maar 1 keer gemeld", sum("na de herstart niet actief" in m for m in events(h)) == 1, events(h))
    h, tr = with_attempt("2026.10.4", "off")
    check("8: actief na herstart gemeld", any("actief na de herstart" in m for m in events(h)), events(h))
    h, tr = with_attempt("2026.10.2", "on", done=True)
    check("8: gekende fout: geen melding na herstart", not any("herstart" in m for m in events(h)), events(h))

    # 9. Core mislukt na HACS-update: toch herstart voor HACS
    class HSt(St):
        def __init__(s):
            super().__init__(); s.entity_id = "update.x_update"
            s.attributes = {"latest_version": "v2", "installed_version": "v1", "supported_features": 1, "title": "X"}
    restarts = []
    h, tr, calls, iss, core = make(always)
    hacs = HSt()
    h.states.async_all = lambda d: [hacs, core]
    h.states.get = lambda eid: hacs if eid == hacs.entity_id else core
    class HEnt: platform = "hacs"; unique_id = "1"; hidden_by = None
    reg.async_get = lambda eid: HEnt() if eid == hacs.entity_id else Ent()
    orig = h.services.async_call
    async def call(domain, service, data=None, blocking=False):
        if (domain, service) == ("homeassistant", "restart"):
            restarts.append(1); return
        if (domain, service) == ("update", "install") and data["entity_id"] == hacs.entity_id:
            hacs.attributes["installed_version"] = "v2"; hacs.state = "off"; return
        await orig(domain, service, data, blocking)
    h.services.async_call = call
    au.is_night = lambda now=None: True
    res = await au._async_run_locked(h, dict(OPTS), "schema")
    check("9: Core mislukt, toch herstart voor HACS", res["failed"] and restarts == [1], (res["failed"], restarts))
    reg.async_get = lambda eid: Ent()

    # ---- v1.48.3 (triple check) ----
    check("v1.48.3: blijvende back-upfout niet tijdelijk", not au.backup_retryable(Exception("Error creating backup: Backup failed: No space left on device")))
    check("v1.48.3: busy niet als tijdelijk", not au.backup_retryable(Exception("Error creating backup: Backup manager busy: create_backup")))

    # A. downloadfout: herhaling zonder nieuwe back-up
    async def dl_then_ok(hass, data, n):
        if n == 1:
            raise Exception("Error updating Home Assistant Core: Downloading Home Assistant version 2026.10.4 failed")
        hass.states.get(EID).attributes["installed_version"] = "2026.10.4"
    h, tr, calls, iss, _ = make(dl_then_ok)
    res = await au._async_run_locked(h, dict(OPTS), "test")
    check("A: 1e poging met back-up, herhaling zonder", len(calls) == 2 and calls[0].get("backup") is True and "backup" not in calls[1], calls)

    # B. busy uit de installatie: niet herhalen, niet tellen
    async def busy(hass, data, n): raise Exception("Error creating backup: Backup manager busy: create_backup")
    h, tr, calls, iss, _ = make(busy)
    res = await au._async_run_locked(h, dict(OPTS), "test")
    check("B: busy niet herhaald, niet geteld", len(calls) == 1 and not res["failed"] and tr.count(EID, "2026.10.4") == 0, (len(calls), res, tr.attempts))

    # C. timeout tijdens Core: niet mislukt, geen HACS-herstart, controle na herstart blijft mogelijk
    oud = au._INSTALL_TIMEOUT
    au._INSTALL_TIMEOUT = 0.2
    async def slow(hass, data, n): await asyncio.sleep(2)
    h, tr, calls, iss, core = make(slow)
    res = await au._async_run_locked(h, dict(OPTS), "test")
    au._INSTALL_TIMEOUT = oud
    check("C: timeout Core niet als mislukt", not res["failed"] and any("resultaat volgt na de herstart" in x for x in res["skipped"]), res)
    check("C: poging niet afgesloten (controle na herstart)", not tr.attempts[EID].get("nagekeken"), tr.attempts)

    # D. undo_attempt: geen valse melding na herstart
    h, tr, calls, iss, core = make(always)
    tr.add_attempt(EID, "2026.10.4"); tr.add_attempt(EID, "2026.10.4")
    tr.undo_attempt(EID, "2026.10.4")
    tr.attempts[EID]["last"] = (au._MODULE_START - timedelta(minutes=10)).isoformat()
    au.async_sync_visibility(h, dict(OPTS))
    check("D: na overgeslagen poging geen melding na herstart", not any("herstart" in m for m in events(h)), events(h))

    # E. overgeslagen versie (off, andere versie): geen "actief"
    h, tr = with_attempt("2026.10.2", "off")
    check("E: overgeslagen versie: geen valse 'actief'", not any("actief" in m for m in events(h)), events(h))

    # F. HACS-herstart wacht op de back-up van HA
    au.BACKUP_WAIT = 0.2
    restarts = []
    h, tr, calls, iss, core = make(always)
    hacs = HSt()
    h.states.async_all = lambda d: [hacs]
    h.states.get = lambda eid: hacs
    reg.async_get = lambda eid: HEnt()
    h.data["backup"] = type("M", (), {"state": "create_backup"})()
    async def call2(domain, service, data=None, blocking=False):
        if (domain, service) == ("homeassistant", "restart"):
            restarts.append(1); return
        hacs.attributes["installed_version"] = "v2"; hacs.state = "off"
    h.services.async_call = call2
    res = await au._async_run_locked(h, dict(OPTS), "schema")
    check("F: geen herstart zolang HA een back-up maakt, wel uitgesteld", restarts == [] and res.get("herstart_gepland") and any("herstart uitgesteld" in m for m in events(h)), (restarts, res, events(h)))
    au.async_cancel_deferred(h)
    h.data["backup"].state = "idle"
    hacs.state = "on"; hacs.attributes["installed_version"] = "v1"
    res = await au._async_run_locked(h, dict(OPTS), "schema")
    check("F: wel herstart als de back-up klaar is", restarts == [1], restarts)
    reg.async_get = lambda eid: Ent()

    # G. timeout bij poging 2: geen valse "2 keer mislukt"
    au._INSTALL_TIMEOUT = 0.2
    h, tr, calls, iss, core = make(slow, attempts_before=1)
    res = await au._async_run_locked(h, dict(OPTS), "test")
    au._INSTALL_TIMEOUT = oud
    check("G: timeout poging 2: geen reparatie", not iss.created and au.is_installing(h, EID), (iss.created, res))

    # H. back-upfout met 'download' in de tekst: geen herhaling zonder back-up
    async def weird(hass, data, n): raise Exception("Error creating backup: Backup failed: failed to download agent list")
    h, tr, calls, iss, _ = make(weird)
    res = await au._async_run_locked(h, dict(OPTS), "test")
    check("H: geen installatie zonder back-up na back-upfout", len(calls) == 1 and calls[0].get("backup") is True, calls)

asyncio.run(main())
print("RESULTAAT", "ALLES OK" if ok else "FOUTEN")
sys.exit(0 if ok else 1)
