"""Btechnics IOT desktop-app downloaden vanuit de zijbalk (v1.36.0).

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

# Vaste downloadlinks (altijd de laatste versie van de app)
MAC_URL = "https://github.com/bogaertm/btechnics-iot-app/releases/latest/download/Btechnics-IOT-Mac.dmg"
WINDOWS_URL = "https://github.com/bogaertm/btechnics-iot-app/releases/latest/download/Btechnics-IOT-Windows-Setup.exe"

PANEL_PATH = "btechnics-app"
PAGE_URL = "/btechnics_branding/app"
SIDEBAR_TITLE = "IOT APP"
SIDEBAR_ICON = "mdi:monitor-arrow-down"

_PAGE = """<!doctype html>
<html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IOT APP</title>
<style>
:root{--bg:#fafafa;--card:#fff;--text:#1d1a18;--muted:#6b6560;--line:#e8e3df;--orange:#ED6928;--gold:#F59E32}
@media (prefers-color-scheme:dark){:root{--bg:#111;--card:#1c1c1c;--text:#eee;--muted:#a8a29e;--line:#2e2b29}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:Raleway,Roboto,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:560px;margin:0 auto;padding:40px 16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:28px}
.logo{display:block;height:36px;margin:0 0 20px}
h1{font-size:22px;margin:0 0 8px}
p{color:var(--muted);line-height:1.5;margin:0 0 24px}
.buttons{display:flex;flex-direction:column;gap:12px}
a.btn{display:flex;align-items:center;justify-content:center;gap:10px;padding:14px 18px;border-radius:12px;
  font-weight:600;font-size:16px;text-decoration:none;border:2px solid var(--orange);color:var(--orange);background:transparent}
a.btn.main{background:var(--orange);color:#fff}
a.btn:hover{filter:brightness(1.05)}
a.btn svg{width:20px;height:20px;fill:currentColor}
small{display:block;color:var(--muted);margin-top:18px;font-size:13px;line-height:1.5}
</style></head>
<body><main><div class="card">
<img class="logo" src="/btechnics_branding/logo.svg" alt="Btechnics">
<h1>Btechnics IOT op je computer</h1>
<p>Met de desktop-app heb je je installatie altijd bij de hand op je Mac of Windows-pc. Je krijgt telkens de laatste versie.</p>
<div class="buttons">
<a class="btn" id="mac" href="__MAC__" target="_blank" rel="noopener">
<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M16.4 12.6c0-2.5 2-3.7 2.1-3.8-1.2-1.7-3-1.9-3.6-2-1.5-.2-3 .9-3.8.9-.8 0-2-.9-3.3-.9-1.7 0-3.3 1-4.1 2.5-1.8 3.1-.5 7.6 1.3 10.1.8 1.2 1.8 2.6 3.1 2.5 1.2 0 1.7-.8 3.2-.8s1.9.8 3.2.8c1.3 0 2.2-1.2 3-2.4.9-1.4 1.3-2.7 1.3-2.8 0 0-2.4-.9-2.4-3.8zM14 5.2c.7-.8 1.1-1.9 1-3-1 0-2.2.6-2.9 1.4-.6.7-1.2 1.9-1 2.9 1.1.1 2.2-.5 2.9-1.3z"/></svg>
Download voor Mac</a>
<a class="btn" id="win" href="__WIN__" target="_blank" rel="noopener">
<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 5.5l7.4-1v7.1H3V5.5zm0 13l7.4 1v-7H3v6zm8.3 1.1L21 21v-8.4h-9.7v7zm0-15.2v7.2H21V3l-9.7 1.4z"/></svg>
Download voor Windows</a>
</div>
<small>Na het installeren meld je je aan met de gegevens die je van Btechnics kreeg. Vragen? Neem contact op met Btechnics.</small>
</div></main>
<script>
(function(){var u=navigator.userAgent||"",p=(navigator.userAgentData&&navigator.userAgentData.platform)||navigator.platform||"";
var id=/Win/i.test(p+u)?"win":(/Mac/i.test(p+u)&&!/iPhone|iPad/i.test(u)?"mac":null);
if(id){var el=document.getElementById(id);el.classList.add("main");el.parentNode.insertBefore(el,el.parentNode.firstChild);}})();
</script>
</body></html>
"""


class AppDownloadView(HomeAssistantView):
    """De downloadpagina. Geen aanmelding nodig: enkel twee publieke links."""

    url = PAGE_URL
    name = "btechnics_branding:app"
    requires_auth = False

    async def get(self, request):
        html = _PAGE.replace("__MAC__", MAC_URL).replace("__WIN__", WINDOWS_URL)
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
