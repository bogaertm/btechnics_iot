/**
 * Btechnics IOT Branding v1.29.0
 *
 * v1.28.2: zoom van de hele interface instelbaar per desktop en mobiel
 *          (opties zoom_desktop, zoom_mobile, zoom_breakpoint; standaard
 *          80 / 85 / 870 px). Gebruikt CSS zoom op <html>.
 *
 * v1.26.1: MutationObserver op elke shadow root (dialogen, dropdowns) zodat
 *          tekst en links meteen gepatcht worden i.p.v. pas na 2 s. Elementen
 *          met href naar home-assistant.io die geen <a> zijn (ha-icon-button
 *          help knop) worden verborgen.
 *
 * v1.26.0: sidebar en header terug licht zoals origineel HA. Petrol enkel als
 *          primaire kleur (knoppen, links, actieve iconen, toggles, lichte
 *          achtergronden), oranje als accent.
 *
 * v1.25.2: brand map (icon.png, logo.png, dark_logo.png) toegevoegd zodat HA's
 *          brands API het Btechnics icoon serveert voor deze integratie; HACS
 *          update entiteit (CDN placeholder) krijgt het lokale icoon via JS.
 *
 * v1.25.1: actieve tabs in de petrol header/bottom bar in goud (waren petrol
 *          op petrol, onleesbaar op mobiel).
 *
 * v1.25.0: Btechnics kleuren: HA blauw vervangen door petrol (#00222b) als
 *          primaire kleur, oranje (#ed6928) als accent, sidebar en header
 *          petrol met gouden actieve items. Donkere modus krijgt lichtere
 *          petrol tinten voor links en knoppen. Tips balk (ha-tip) verborgen.
 *
 * v1.24.0: Open Home Foundation kaart en links naar home-assistant.io /
 *          openhomefoundation.org verborgen of omgeleid naar btechnics.be.
 *          Inline HA logo's (ha-logo-svg, ha-svg-icon met HA pad) en img's
 *          die naar het HA brand icoon wijzen worden vervangen door het
 *          Btechnics icoon. Brand icoon URLs zelf worden backend-side
 *          onderschept (zie __init__.py).
 */
const BRAND = "Btechnics IOT";

const BT = {
  logo: "/btechnics_branding/logo.svg",
  icon: "/btechnics_branding/app-icon-192.png",
  loginText: BRAND,
  loginSize: 24,
  sidebarText: BRAND,
  sidebarSize: 16,
  zoomDesktop: 80,
  zoomMobile: 85,
  zoomBreakpoint: 870,
  customerLogo: null,   // URL van het geuploade klantenlogo (of null)
  customerScale: 100,   // schaal in % t.o.v. het Btechnics logo
};

async function loadConfig() {
  try {
    const r = await fetch("/api/btechnics_branding/config");
    if (r.ok) {
      const d = await r.json();
      BT.loginText   = d.login_text        || BT.loginText;
      BT.loginSize   = d.login_text_size   || BT.loginSize;
      BT.sidebarText = d.sidebar_text      || BT.sidebarText;
      BT.sidebarSize = d.sidebar_text_size || BT.sidebarSize;
      if (d.zoom_desktop)    BT.zoomDesktop    = d.zoom_desktop;
      if (d.zoom_mobile)     BT.zoomMobile     = d.zoom_mobile;
      if (d.zoom_breakpoint) BT.zoomBreakpoint = d.zoom_breakpoint;
      BT.customerLogo = d.customer_logo || null;
      if (d.customer_logo_scale) BT.customerScale = d.customer_logo_scale;
    }
  } catch(e) {}
}

const style = document.createElement("style");
style.textContent = `
  #ha-launch-screen svg         { display: none !important; }
  #ha-launch-screen img.ha-logo { width: auto !important; height: 80px !important; }
  .ohf-logo                     { display: none !important; }
`;
document.head.appendChild(style);

// Mutaties binnen shadow roots zijn onzichtbaar voor een observer op document;
// daarom observeren we elke shadow root die we tegenkomen (eenmalig).
const observedRoots = new WeakSet();
let patching = false;
let patchTimer = null;
function schedulePatch() {
  if (patching || patchTimer) return;
  patchTimer = setTimeout(() => { patchTimer = null; patchAll(); }, 60);
}
function observeRoot(root) {
  if (observedRoots.has(root)) return;
  observedRoots.add(root);
  try {
    new MutationObserver(schedulePatch)
      .observe(root, { childList: true, subtree: true, characterData: true });
  } catch(e) {}
}

function deepQuery(root, selector) {
  const found = [];
  try {
    found.push(...root.querySelectorAll(selector));
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) { observeRoot(el.shadowRoot); found.push(...deepQuery(el.shadowRoot, selector)); }
    }
  } catch(e) {}
  return found;
}

function deepReplaceText(root, from, to) {
  try {
    const escaped = from.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const re = new RegExp(escaped, 'g');
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (node.textContent.includes(from)) {
        node.textContent = node.textContent.replace(re, to);
      }
    }
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) deepReplaceText(el.shadowRoot, from, to);
    }
  } catch(e) {}
}

// Klantenlogo naast het Btechnics logo (zijbalk, aanmeldscherm, opstartscherm).
// baseHeight = hoogte van het Btechnics logo op die plaats, in px.
function ensureCustomerLogo(container, afterEl, cls, baseHeight, gap) {
  if (!BT.customerLogo || !container) return;
  let img = container.querySelector("." + cls);
  if (!img) {
    img = document.createElement("img");
    img.className = cls;
    img.alt = "";
    if (afterEl && afterEl.parentNode === container) afterEl.after(img);
    else container.appendChild(img);
  }
  const h = Math.round(baseHeight * BT.customerScale / 100);
  img.style.cssText = "height:" + h + "px;width:auto;max-width:" + Math.round(h * 3) +
    "px;display:block;flex-shrink:1;min-width:0;object-fit:contain;margin-left:" + gap + "px;";
  if (img.getAttribute("src") !== BT.customerLogo) img.src = BT.customerLogo;
}

function patchLaunchScreen() {
  const screen = document.getElementById("ha-launch-screen");
  if (!screen) return;
  // v1.29.0: de server zet het Btechnics logo al in <img class="ha-logo">. Komt de
  // HTML nog uit een oude cache van de service worker, dan zetten we het hier.
  let img = screen.querySelector("img.ha-logo") || screen.querySelector(".bt-logo");
  if (!img) {
    img = document.createElement("img");
    img.className = "bt-logo";
    screen.prepend(img);
  }
  if (img.getAttribute("src") !== BT.logo) img.src = BT.logo;
  img.alt = "";
  img.style.cssText = "height:80px;width:auto;flex-shrink:0;display:block;";
  ensureCustomerLogo(img.parentNode, img, "bt-launch-customer-logo", 80, 24);
}

function patchLoginPage() {
  deepQuery(document, 'img[src*="favicon-192x192"], img[src*="favicon-512x512"], img[src*="favicon-384x384"]')
    .forEach(img => { if (!img.dataset.bt) { img.src = BT.icon; img.dataset.bt = "1"; } });

  // Aanmeldscherm: <div class="header"><img></div> (authorize.html.template)
  const loginHeader = document.querySelector(".content > .header");
  if (loginHeader) {
    const icon = loginHeader.querySelector("img:not(.bt-login-customer-logo)");
    ensureCustomerLogo(loginHeader, icon, "bt-login-customer-logo", 56, 20);
  }

  const haAuthEls = deepQuery(document, 'ha-authorize, ha-auth-flow, ha-auth');
  haAuthEls.forEach(haAuth => {
    if (haAuth.shadowRoot) {
      haAuth.shadowRoot.querySelectorAll('img').forEach(img => {
        if (!img.dataset.bt) {
          img.src = BT.icon;
          img.style.height = "64px";
          img.style.width = "auto";
          img.dataset.bt = "1";
        }
      });
    }
  });

  deepReplaceText(document.body, "Welkom thuis!", BT.loginText);
  deepReplaceText(document.body, "Welkom thuis", BT.loginText);
  deepReplaceText(document.body, "Welcome home!", BT.loginText);
  deepReplaceText(document.body, "Welcome home", BT.loginText);
}

function patchSidebar() {
  const ha     = document.querySelector("home-assistant");
  const main   = ha?.shadowRoot?.querySelector("home-assistant-main");
  const mainSR = main?.shadowRoot;
  if (!mainSR) return;
  const sidebar = mainSR.querySelector("ha-drawer")?.querySelector("ha-sidebar");
  const sr      = sidebar?.shadowRoot;
  if (!sr) return;

  const title = sr.querySelector(".title");
  if (!title) return;

  for (const node of [...title.childNodes])
    if (node.nodeType === Node.TEXT_NODE) node.remove();

  // v1.28.2: de zijbalkkop is twee rijen. Rij 1 is een vaste logoregel (LOGO_H px hoog) met het
  // Btechnics logo en, als het er is, het klantenlogo ernaast. Beide worden op die hoogte
  // geschaald, breedte automatisch, met een maximale breedte zodat een breed klantenlogo de
  // regel nooit breekt. Rij 2 is de tekst, op een regel met afkapping. Zo kan geen enkel logo
  // de tekst uit de kop duwen, wat er sinds v1.28.2 gebeurde (.title is geen flex container).
  const LOGO_H = 28;
  title.style.cssText = "display:flex;flex-direction:column;justify-content:center;gap:3px;" +
    "overflow:hidden;line-height:1.2;padding-left:8px;box-sizing:border-box;";

  let rij = sr.querySelector(".bt-logos");
  if (!rij) {
    rij = document.createElement("div");
    rij.className = "bt-logos";
    title.insertBefore(rij, title.firstChild);
  }
  rij.style.cssText = "display:flex;align-items:center;gap:10px;height:" + LOGO_H + "px;" +
    "max-width:100%;overflow:hidden;flex-shrink:0;";

  let logo = sr.querySelector(".bt-sidebar-logo");
  if (!logo) {
    logo = document.createElement("img");
    logo.className = "bt-sidebar-logo";
    logo.src = BT.logo;
    logo.alt = "";
  }
  logo.style.cssText = "height:" + LOGO_H + "px;width:auto;max-width:60%;object-fit:contain;" +
    "object-position:left center;display:block;flex-shrink:1;min-width:0;";
  if (logo.parentNode !== rij) rij.appendChild(logo);

  let klant = sr.querySelector(".bt-sidebar-customer-logo");
  if (BT.customerLogo) {
    if (!klant) {
      klant = document.createElement("img");
      klant.className = "bt-sidebar-customer-logo";
      klant.alt = "";
    }
    // Schaal enkel naar beneden in de zijbalk: hoger dan de logoregel kan nooit.
    const h = Math.round(LOGO_H * Math.min(BT.customerScale, 100) / 100);
    klant.style.cssText = "height:" + h + "px;width:auto;max-width:40%;object-fit:contain;" +
      "object-position:left center;display:block;flex-shrink:1;min-width:0;";
    if (klant.getAttribute("src") !== BT.customerLogo) klant.src = BT.customerLogo;
    if (klant.parentNode !== rij) rij.appendChild(klant);
  } else if (klant) {
    klant.remove();
  }

  let span = sr.querySelector(".bt-sidebar-text");
  if (!span) {
    span = document.createElement("span");
    span.className = "bt-sidebar-text";
  }
  span.textContent = BT.sidebarText;
  span.style.cssText = "display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" +
    "font-size:" + BT.sidebarSize + "px;";
  if (span.parentNode !== title) title.appendChild(span);
}

// mdiHomeAssistant pad begint zo (src/resources/home-assistant-logo-svg.ts)
const HA_PATH_PREFIX = "m12.151 1.5882";
const OWN_BRAND_RE = /brands\.home-assistant\.io\/(_\/)?btechnics_branding\//;
const HA_BRAND_RE = /(brands\.home-assistant\.io\/(_\/)?|\/api\/brands\/integration\/)(homeassistant|hassio|demo|homeassistant_hardware|compensation|emulated_hue|emulated_kasa|emulated_roku|lacrosse|picotts|rss_feed_template|seven_segments|simulated|syslog|tcp|telnet|trace|version|update|homeassistant_green|homeassistant_yellow|homeassistant_sky_connect|homeassistant_connect_zbt1|homeassistant_connect_zbt2)\//;

// v1.29.0: ha-svg-icon elementen worden door de frontend hergebruikt (lijsten,
// logboek). Krijgt een vervangen icoon later een ander pad, dan zetten we het
// origineel terug; anders bleef ons logo op de verkeerde plaats staan.
function swapSvgForIcon(host, on = true) {
  const sr = host.shadowRoot;
  if (!sr) return;
  const svg = sr.querySelector("svg");
  const mine = sr.querySelector(".bt-inline-logo");
  if (!on) {
    if (mine) mine.remove();
    if (svg) svg.style.display = "";
    return;
  }
  if (mine || !svg) return;
  svg.style.display = "none";
  const img = document.createElement("img");
  img.className = "bt-inline-logo";
  img.src = BT.icon;
  img.style.cssText = "width:100%;height:100%;object-fit:contain;display:block;";
  sr.appendChild(img);
}

const TEXT_ATTRS = ["alt", "title", "aria-label", "placeholder"];
function deepReplaceAttrs(root, from, to) {
  try {
    for (const el of root.querySelectorAll("*")) {
      for (const a of TEXT_ATTRS) {
        const v = el.getAttribute(a);
        if (v && v.includes(from)) el.setAttribute(a, v.split(from).join(to));
      }
      if (el.shadowRoot) deepReplaceAttrs(el.shadowRoot, from, to);
    }
  } catch(e) {}
}

function patchInlineLogos() {
  deepQuery(document, "ha-logo-svg").forEach(swapSvgForIcon);
  deepQuery(document, "ha-svg-icon").forEach(el => {
    const p = el.path || el.getAttribute("path") || "";
    swapSvgForIcon(el, p.startsWith(HA_PATH_PREFIX));
  });
  deepQuery(document, "img").forEach(img => {
    if (!img.dataset.bt && HA_BRAND_RE.test(img.getAttribute("src") || "")) {
      img.src = BT.icon;
      img.dataset.bt = "1";
    }
  });
  // HACS update entiteit wijst naar brands.home-assistant.io/_/btechnics_branding
  // (bestaat niet op de CDN -> "icon not available"); state-badge gebruikt
  // een background-image, dus hier vervangen door het lokale icoon
  deepQuery(document, "state-badge").forEach(el => {
    const bg = el.style.backgroundImage || "";
    if (!el.dataset.bt && OWN_BRAND_RE.test(bg)) {
      el.style.backgroundImage = "url(" + BT.icon + ")";
      el.dataset.bt = "1";
    }
  });
}

// Externe HA / Open Home Foundation verwijzingen
const EXT_HIDE_RE  = /ohf\.to|openhomefoundation\.org|community\.home-assistant\.io|release-notes|\/blog\//;
const EXT_HA_RE    = /home-assistant\.io|openhomefoundation\.org|ohf\.to/;
const BT_SITE      = "https://btechnics.be";

function patchExternalLinks() {
  // Open Home Foundation kaart op de Info pagina
  deepQuery(document, "ha-card.ohf").forEach(c => { c.style.display = "none"; });
  // "Tip!" balk onderaan Instellingen (forums, socials, blog, nieuwsbrief, sneltoetsen)
  deepQuery(document, "ha-tip").forEach(c => { c.style.display = "none"; });
  // ook ha-icon-button / ha-button met href (bv. het ? help icoon in dialogen)
  deepQuery(document, "[href]").forEach(a => {
    const href = a.getAttribute("href") || "";
    if (!EXT_HA_RE.test(href) || a.dataset.bt) return;
    a.dataset.bt = "1";
    if (EXT_HIDE_RE.test(href) || a.tagName !== "A") {
      // release notes, community, OHF: link volledig verbergen (rij erboven mee)
      const row = a.closest(".row") || a;
      row.style.display = "none";
    } else {
      // documentatie/logo links: naar btechnics.be
      a.setAttribute("href", BT_SITE);
    }
  });
}

// Btechnics kleuren: petrol (app icoon) als primaire kleur, oranje als accent
const BT_COLORS = {
  petrol: "#00222b", orange: "#ed6928", gold: "#f59e32",
  scale: { // petrol tinten, 05 donker -> 95 licht
    "05": "#000c10", "10": "#001820", "20": "#00222b", "30": "#003a4a",
    "40": "#00222b", "50": "#0f6b85", "60": "#3f98b3", "70": "#7fbfd2",
    "80": "#b7dbe6", "90": "#dde9ee", "95": "#eef4f6",
  },
};

function isDarkMode() {
  try {
    const bg = getComputedStyle(document.documentElement)
      .getPropertyValue("--primary-background-color").trim();
    const m = bg.match(/^#([0-9a-f]{6})$/i);
    if (!m) return window.matchMedia("(prefers-color-scheme: dark)").matches;
    const v = parseInt(m[1], 16);
    const lum = ((v >> 16) & 255) * 0.299 + ((v >> 8) & 255) * 0.587 + (v & 255) * 0.114;
    return lum < 128;
  } catch(e) { return false; }
}

function patchColors() {
  const root = document.documentElement;
  const dark = isDarkMode();
  const primary = dark ? BT_COLORS.scale["70"] : BT_COLORS.petrol;
  const vars = {
    "--primary-color": primary,
    "--dark-primary-color": dark ? BT_COLORS.scale["60"] : BT_COLORS.scale["10"],
    "--darker-primary-color": dark ? BT_COLORS.scale["50"] : BT_COLORS.scale["05"],
    "--light-primary-color": dark ? BT_COLORS.scale["30"] : BT_COLORS.scale["80"],
    "--rgb-primary-color": dark ? "127, 191, 210" : "0, 34, 43",
    "--accent-color": BT_COLORS.orange,
    "--rgb-accent-color": "237, 105, 40",
    "--ha-color-text-link": primary,
  };
  for (const k in BT_COLORS.scale) vars["--ha-color-primary-" + k] = BT_COLORS.scale[k];
  for (const k in vars) {
    if (root.style.getPropertyValue(k) !== vars[k]) root.style.setProperty(k, vars[k]);
  }
}

// Zoom van de hele interface, apart voor mobiel en desktop (instelbaar in opties)
// v1.28.2: GEEN zoom in de companion app (iOS en Android). De app draait de frontend in een
// webview en zet zelf de schaal; CSS zoom op <html> daarbovenop brak de app. De app is te
// herkennen aan zijn user agent ("Home Assistant/..." , zie mobile-apps docs) en aan de bruggen
// die hij in window zet: externalApp (Android) en webkit.messageHandlers.externalBus (iOS).
function isCompanionApp() {
  try {
    if (/Home ?Assistant\//i.test(navigator.userAgent || "")) return true;
    if (window.externalApp) return true;
    if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.externalBus) return true;
  } catch(e) {}
  return false;
}

function applyZoom() {
  try {
    if (isCompanionApp()) {
      if (document.documentElement.style.zoom) document.documentElement.style.zoom = "";
      return;
    }
    const pct = window.innerWidth < BT.zoomBreakpoint ? BT.zoomMobile : BT.zoomDesktop;
    const z = pct === 100 ? "" : String(pct / 100);
    if (document.documentElement.style.zoom !== z) document.documentElement.style.zoom = z;
  } catch(e) {}
}
window.addEventListener("resize", applyZoom);

function patchTitle() {
  if (document.title.includes("Home Assistant"))
    document.title = document.title.replace(/Home Assistant/g, BRAND);
}

function patchFavicon() {
  document.querySelectorAll('link[rel*="icon"]').forEach(l => l.remove());
  const link = document.createElement("link");
  link.rel = "icon"; link.type = "image/png"; link.href = BT.icon;
  document.head.appendChild(link);
}

function patchAll() {
  patching = true;
  try { patchAllInner(); } finally { patching = false; }
}

function patchAllInner() {
  disableSurvey();
  patchLaunchScreen();
  patchLoginPage();
  patchSidebar();
  patchInlineLogos();
  patchExternalLinks();
  patchColors();
  patchTitle();
  deepReplaceText(document.body, "Home Assistant", BRAND);
  deepReplaceAttrs(document.body, "Home Assistant", BRAND);
}

// v1.29.0: DE SERVICE WORKER VAN HA HIELD OUDE HA LOGO'S VAST.
// Hij precachet favicon-192x192.png en favicon.ico, cachet alles onder /static/
// "cache first" en brand iconen "stale while revalidate" (frontend
// src/entrypoints/service-worker.ts, build-scripts/gulp/service-worker.js).
// Wat voor onze vervanging in die cache belandde, bleef het HA huisje tonen,
// ook al geeft de server nu het Btechnics logo. Eenmaal per versie halen we die
// items uit alle caches; de service worker haalt ze dan opnieuw bij de server.
const BT_VERSION = "1.29.0";
const HA_CACHED_RE = new RegExp(
  "/static/(icons/(favicon|mask-icon|apple-touch-icon|maskable_icon|tile-win|logo_ohf|ohf)" +
  "|images/(home-assistant-logo|notification-badge|ohf-badge|open-home-foundation))" +
  "|/api/brands/integration/(" + HA_BRAND_RE.source.split("(homeassistant|")[1].split(")")[0].replace(/^/, "homeassistant|") + ")/"
);
async function purgeHaCaches() {
  try {
    if (!("caches" in window)) return;
    let klaar = null;
    try { klaar = localStorage.getItem("bt-cache-purge"); } catch(e) {}
    if (klaar === BT_VERSION) return;
    let weg = 0;
    for (const naam of await caches.keys()) {
      const cache = await caches.open(naam);
      for (const req of await cache.keys()) {
        const url = new URL(req.url);
        let del = HA_CACHED_RE.test(url.pathname);
        // Oude HTML van de hoofdpagina zonder onze aanpassingen
        if (!del && url.origin === location.origin && (url.pathname === "/" || url.pathname === "")) {
          try {
            const res = await cache.match(req);
            const txt = res ? await res.clone().text() : "";
            del = !!txt && !txt.includes("bt-hide");
          } catch(e) {}
        }
        if (del && await cache.delete(req)) weg++;
      }
    }
    try { localStorage.setItem("bt-cache-purge", BT_VERSION); } catch(e) {}
    if (weg) console.info("[Btechnics] " + weg + " oude HA afbeeldingen uit de cache gehaald");
  } catch(e) {}
}

// Vangnet voor de HA enquete: de backend zet dit al bij elke start, maar mocht
// dat mislukken, dan doet de eerste eigenaar die de app opent het hier.
let surveyChecked = false;
async function disableSurvey() {
  if (surveyChecked) return;
  try {
    const hass = document.querySelector("home-assistant")?.hass;
    if (!hass?.user || !hass.systemData) return;
    surveyChecked = true;
    if (!hass.user.is_admin || hass.systemData.surveys?.onboarding) return;
    await hass.callWS({
      type: "frontend/set_system_data",
      key: "core",
      value: {
        ...hass.systemData,
        surveys: { ...(hass.systemData.surveys || {}),
          onboarding: { date: new Date().toISOString(), action: "dismissed" } },
      },
    });
  } catch(e) {}
}

(async () => {
  purgeHaCaches();
  await loadConfig();
  applyZoom();
  patchColors();
  patchLaunchScreen();
  patchTitle();
  patchFavicon();
  new MutationObserver(schedulePatch)
    .observe(document.documentElement, { childList: true, subtree: true, characterData: true });
  window.addEventListener("load", () => {
    patchAll();
    setInterval(patchAll, 2000);
  });
})();
