"""Btechnics IOT als app: PWA op gsm en tablet, desktop-app op Mac en Windows (v1.53.0).

v1.53.0: de pagina toont per toestel hoe je Btechnics IOT als app (PWA) installeert:
stappen voor iPhone en iPad, een installeerknop of stappen voor Android, en de
downloads voor Mac en Windows. Nooit de Home Assistant app.

v1.36.0: desktop-app downloaden vanuit de zijbalk.

Een item "IOT APP" onderaan de zijbalk, net boven Instellingen (voor alle
gebruikers), opent
een pagina met twee knoppen: "Download voor Mac" en "Download voor Windows".
De links zijn vaste waarden in de code, geen instelling: ze wijzen altijd naar
de laatste release van de desktop-app op GitHub.

De pagina wordt in HA getoond als iframe-paneel (frontend ha-panel-iframe). Een
iframe stuurt geen HA-sleutel mee, dus de pagina zelf vraagt geen aanmelding;
ze bevat enkel deze twee publieke links en geen gegevens van de klant.
"""
from __future__ import annotations

from aiohttp import web

from homeassistant.components import frontend
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant


def _version() -> str:
    # v1.51.0: logo staat 31 dagen in de cache; nieuwe versie, nieuw adres
    from . import _BT_VERSION
    return _BT_VERSION

# Vaste downloadlinks (altijd de laatste versie van de app)
MAC_URL = "https://github.com/bogaertm/btechnics-iot-app/releases/latest/download/Btechnics-IOT-Mac.dmg"
WINDOWS_URL = "https://github.com/bogaertm/btechnics-iot-app/releases/latest/download/Btechnics-IOT-Windows-Setup.exe"

PANEL_PATH = "btechnics-app"
PAGE_URL = "/btechnics_branding/app"
SIDEBAR_TITLE = "IOT APP"
SIDEBAR_ICON = "mdi:cellphone-arrow-down"

_PAGE = """<!doctype html>
<html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IOT APP</title>
<style>
:root{--bg:#fafafa;--card:#fff;--text:#1d1a18;--muted:#5f5a55;--line:#e8e3df;--petrol:#04212B;--orange:#ED6928}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:Raleway,Roboto,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:560px;margin:0 auto;padding:32px 16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:28px}
.logo{display:block;height:64px;max-width:100%;margin:0 auto 24px}
h1{font-size:22px;margin:0 0 8px}
h2{font-size:17px;margin:28px 0 10px}
p{color:var(--muted);line-height:1.5;margin:0 0 18px}
.buttons{display:flex;flex-direction:column;gap:12px}
.btn{display:flex;align-items:center;justify-content:center;gap:10px;padding:14px 18px;border-radius:12px;cursor:pointer;
  font-weight:600;font-size:16px;font-family:inherit;text-decoration:none;border:2px solid var(--petrol);color:var(--petrol);background:transparent}
.btn.main{background:var(--petrol);color:#fff}
.btn:hover{filter:brightness(1.08)}
.btn svg{width:20px;height:20px;fill:currentColor}
ol{margin:0 0 6px;padding-left:22px;line-height:1.7}
ol li{padding-left:4px}
.ok{background:#04212B0d;border-left:4px solid var(--orange);border-radius:8px;padding:12px 14px;color:var(--text);margin:0 0 18px}
.hide{display:none}
small{display:block;color:var(--muted);margin-top:22px;font-size:13px;line-height:1.5}
</style></head>
<body><main><div class="card">
<img class="logo" src="/btechnics_branding/logo.svg?v=__V__" alt="Btechnics.be">
<h1>Btechnics IOT als app</h1>
<p>Zet Btechnics IOT als app op je gsm, tablet of computer. Je opent je installatie dan met een tik op het icoon, zonder browser errond.</p>

<div id="klaar" class="ok hide">Btechnics IOT staat al als app op dit toestel.</div>

<div id="sec-install" class="hide">
<div class="buttons"><button class="btn main" id="installeer" type="button">Installeer de app</button></div>
</div>

<div id="sec-ios" class="hide">
<h2>iPhone en iPad</h2>
<ol>
<li>Open deze pagina in <b>Safari</b>.</li>
<li>Tik onderaan op <b>Deel</b> (vierkant met pijl omhoog).</li>
<li>Kies <b>Zet op beginscherm</b>.</li>
<li>Tik op <b>Voeg toe</b>. Btechnics IOT staat nu op je beginscherm.</li>
</ol>
</div>

<div id="sec-android" class="hide">
<h2>Android</h2>
<ol>
<li>Open deze pagina in <b>Chrome</b>.</li>
<li>Tik rechtsboven op het menu <b>&#8942;</b>.</li>
<li>Kies <b>App installeren</b> of <b>Toevoegen aan startscherm</b>.</li>
<li>Bevestig met <b>Installeren</b>. Btechnics IOT staat nu bij je apps.</li>
</ol>
</div>

<div id="sec-desktop" class="hide">
<h2>Mac en Windows</h2>
<p>Met de desktop-app heb je je installatie altijd bij de hand. Je krijgt telkens de laatste versie.</p>
<div class="buttons">
<a class="btn" id="mac" href="__MAC__" target="_blank" rel="noopener">
<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M16.4 12.6c0-2.5 2-3.7 2.1-3.8-1.2-1.7-3-1.9-3.6-2-1.5-.2-3 .9-3.8.9-.8 0-2-.9-3.3-.9-1.7 0-3.3 1-4.1 2.5-1.8 3.1-.5 7.6 1.3 10.1.8 1.2 1.8 2.6 3.1 2.5 1.2 0 1.7-.8 3.2-.8s1.9.8 3.2.8c1.3 0 2.2-1.2 3-2.4.9-1.4 1.3-2.7 1.3-2.8 0 0-2.4-.9-2.4-3.8zM14 5.2c.7-.8 1.1-1.9 1-3-1 0-2.2.6-2.9 1.4-.6.7-1.2 1.9-1 2.9 1.1.1 2.2-.5 2.9-1.3z"/></svg>
Download voor Mac</a>
<a class="btn" id="win" href="__WIN__" target="_blank" rel="noopener">
<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 5.5l7.4-1v7.1H3V5.5zm0 13l7.4 1v-7H3v6zm8.3 1.1L21 21v-8.4h-9.7v7zm0-15.2v7.2H21V3l-9.7 1.4z"/></svg>
Download voor Windows</a>
</div>
</div>

<small>Je meldt je aan met de gegevens die je van Btechnics kreeg. Vragen? Neem contact op met Btechnics.</small>
</div></main>
<script>
(function(){
var u=navigator.userAgent||"",p=(navigator.userAgentData&&navigator.userAgentData.platform)||navigator.platform||"";
var top=window;try{if(window.parent&&window.parent.btInstall)top=window.parent;}catch(e){}
function toon(id){document.getElementById(id).classList.remove("hide");}
var ios=/iPhone|iPad|iPod/i.test(u)||(/Mac/i.test(p)&&navigator.maxTouchPoints>1);
var android=/Android/i.test(u);
var standalone=false;try{standalone=top.btIsStandalone?top.btIsStandalone():false;}catch(e){}
if(standalone){toon("klaar");return;}
function knop(){var ok=false;try{ok=!!top.btInstallPrompt;}catch(e){}
  if(ok)toon("sec-install");}
document.getElementById("installeer").onclick=function(){
  top.btInstall().then(function(r){if(r==="accepted"){document.getElementById("sec-install").classList.add("hide");toon("klaar");}});};
if(ios){toon("sec-ios");}
else if(android){knop();toon("sec-android");}
else{knop();toon("sec-desktop");
  var id=/Win/i.test(p+u)?"win":(/Mac/i.test(p+u)?"mac":null);
  if(id){var el=document.getElementById(id);el.classList.add("main");el.parentNode.insertBefore(el,el.parentNode.firstChild);}}
setTimeout(knop,1500);
})();
</script>
</body></html>
"""


class AppDownloadView(HomeAssistantView):
    """De downloadpagina. Geen aanmelding nodig: enkel twee publieke links."""

    url = PAGE_URL
    name = "btechnics_branding:app"
    requires_auth = False

    async def get(self, request):
        html = _PAGE.replace("__MAC__", MAC_URL).replace("__WIN__", WINDOWS_URL).replace("__V__", _version())
        return web.Response(
            text=html,
            content_type="text/html",
            headers={
                "Cache-Control": "no-cache",
                "X-Content-Type-Options": "nosniff",
                # Enkel binnen HA zelf te tonen; geen externe scripts of bronnen
                "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'",
                "Referrer-Policy": "no-referrer",
            },
        )


def async_setup(hass: HomeAssistant) -> None:
    """Zijbalk-item registreren (een keer)."""
    if PANEL_PATH in hass.data.get("frontend_panels", {}):
        return
    frontend.async_register_built_in_panel(
        hass,
        component_name="iframe",
        sidebar_title=SIDEBAR_TITLE,
        sidebar_icon=SIDEBAR_ICON,
        frontend_url_path=PANEL_PATH,
        config={"url": PAGE_URL},
        require_admin=False,
    )


def async_unload(hass: HomeAssistant) -> None:
    frontend.async_remove_panel(hass, PANEL_PATH, warn_if_unknown=False)
