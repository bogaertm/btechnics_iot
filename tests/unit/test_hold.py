# Draaien: docker run --rm -v "$PWD:/w:ro" --entrypoint python3 ghcr.io/home-assistant/home-assistant:stable /w/tests/unit/test_hold.py
import asyncio, sys, types
from datetime import timedelta
sys.path.insert(0, "/w")
from unittest.mock import MagicMock
import custom_components.btechnics_branding.auto_update as au
from homeassistant.util import dt as dt_util

class FakeStore:
    def __init__(self,*a,**k): self.saved=None
    async def async_load(self): return None
    def async_delay_save(self, fn, d): self.saved=fn()
au.Store = FakeStore

class St:
    def __init__(s,eid,latest,inst="1.0",title=None):
        s.entity_id=eid; s.state="on"; s.attributes={"latest_version":latest,"installed_version":inst,"supported_features":1|8,"title":title or eid}
class Ent:
    def __init__(s,platform,uid): s.platform=platform; s.unique_id=uid; s.hidden_by=None
states=[St("update.os","18.4",title="HA OS"),St("update.mosq","7.2",title="Mosquitto"),St("update.core","2026.11.0",title="Core"),St("update.core2","2026.11.1",title="Core"),St("update.hacs_x","v2",title="X")]
reg_entries={"update.os":Ent("hassio","home_assistant_os_version"),"update.mosq":Ent("hassio","core_mosquitto_version"),"update.core":Ent("hassio","home_assistant_core_version"),"update.core2":Ent("hassio","home_assistant_core_version"),"update.hacs_x":Ent("hacs","123")}
hass=MagicMock(); hass.states.async_all=lambda d: states
reg=MagicMock(); reg.async_get=lambda eid: reg_entries.get(eid)
au.er.async_get=lambda h: reg
tr=au.Tracker(hass); hass.data={au._DATA_TRACKER: tr}
opts={"auto_update":True,"auto_update_categories":["system","addons","hacs"]}
ok=True
def check(name,cond,info=""):
    global ok; ok&=bool(cond); print(("OK  " if cond else "FOUT"),name,info)
todo,skipped=au.plan(hass,opts)
names=[u["entity_id"] for u in todo]
check("OS en app wachten 7 dagen", "update.os" not in names and "update.mosq" not in names, skipped)
check("melding met datum", any("wacht tot" in s and "HA OS" in s for s in skipped))
check("HACS niet uitgesteld", "update.hacs_x" in names)
check("Core .0 overgeslagen, .1 wel", "update.core" not in names and "update.core2" in names)
# 8 dagen later
old=(dt_util.utcnow()-timedelta(days=8)).isoformat()
for e in ("update.os","update.mosq"): tr.seen[e]["since"]=old
todo,skipped=au.plan(hass,opts); names=[u["entity_id"] for u in todo]
check("na 8 dagen wel", "update.os" in names or any("na de herstart" in s for s in skipped)) 
check("app na 8 dagen in plan", "update.mosq" in names)
# nieuwe versie reset de teller
states[1].attributes["latest_version"]="7.3"
todo,skipped=au.plan(hass,opts); names=[u["entity_id"] for u in todo]
check("nieuwere versie wacht opnieuw", "update.mosq" not in names)
check("opgeslagen in Store", "seen" in tr._store.saved and "update.mosq" in tr._store.saved["seen"])
print("RESULTAAT", "ALLES OK" if ok else "FOUTEN")
