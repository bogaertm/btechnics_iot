/**
 * Btechnics IOT Branding v1.24.0
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
    }
  } catch(e) {}
}

const style = document.createElement("style");
style.textContent = `
  #ha-launch-screen svg,
  #ha-launch-screen img.ha-logo { display: none !important; }
  .ohf-logo                     { display: none !important; }
`;
document.head.appendChild(style);

function deepQuery(root, selector) {
  const found = [];
  try {
    found.push(...root.querySelectorAll(selector));
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) found.push(...deepQuery(el.shadowRoot, selector));
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

function patchLaunchScreen() {
  const screen = document.getElementById("ha-launch-screen");
  if (!screen || screen.querySelector(".bt-logo")) return;
  const img = document.createElement("img");
  img.className = "bt-logo";
  img.src = BT.logo;
  img.style.cssText = "height:80px;width:auto;flex-shrink:0;";
  const old = screen.querySelector("svg, img.ha-logo");
  if (old) old.parentNode.insertBefore(img, old);
  else screen.prepend(img);
}

function patchLoginPage() {
  deepQuery(document, 'img[src*="favicon-192x192"], img[src*="favicon-512x512"], img[src*="favicon-384x384"]')
    .forEach(img => { if (!img.dataset.bt) { img.src = BT.icon; img.dataset.bt = "1"; } });

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

  if (!sr.querySelector(".bt-sidebar-logo")) {
    const logo = document.createElement("img");
    logo.className = "bt-sidebar-logo";
    logo.src = BT.logo;
    logo.style.cssText = "height:26px;width:auto;display:block;flex-shrink:0;margin:0 4px 0 8px;";
    title.insertBefore(logo, title.firstChild);
  }

  let span = sr.querySelector(".bt-sidebar-text");
  if (!span) {
    span = document.createElement("span");
    span.className = "bt-sidebar-text";
    title.appendChild(span);
  }
  span.textContent = BT.sidebarText;
  span.style.fontSize = BT.sidebarSize + "px";
}

// mdiHomeAssistant pad begint zo (src/resources/home-assistant-logo-svg.ts)
const HA_PATH_PREFIX = "m12.151 1.5882";
const HA_BRAND_RE = /(brands\.home-assistant\.io\/(_\/)?|\/api\/brands\/integration\/)(homeassistant|hassio|demo)\//;

function swapSvgForIcon(host) {
  const sr = host.shadowRoot;
  if (!sr || sr.querySelector(".bt-inline-logo")) return;
  const svg = sr.querySelector("svg");
  if (!svg) return;
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
    if (p.startsWith(HA_PATH_PREFIX)) swapSvgForIcon(el);
  });
  deepQuery(document, "img").forEach(img => {
    if (!img.dataset.bt && HA_BRAND_RE.test(img.getAttribute("src") || "")) {
      img.src = BT.icon;
      img.dataset.bt = "1";
    }
  });
}

// Externe HA / Open Home Foundation verwijzingen
const EXT_HIDE_RE  = /openhomefoundation\.org|community\.home-assistant\.io|release-notes|\/blog\//;
const EXT_HA_RE    = /home-assistant\.io|openhomefoundation\.org/;
const BT_SITE      = "https://btechnics.be";

function patchExternalLinks() {
  // Open Home Foundation kaart op de Info pagina
  deepQuery(document, "ha-card.ohf").forEach(c => { c.style.display = "none"; });
  deepQuery(document, "a[href]").forEach(a => {
    const href = a.getAttribute("href") || "";
    if (!EXT_HA_RE.test(href) || a.dataset.bt) return;
    a.dataset.bt = "1";
    if (EXT_HIDE_RE.test(href)) {
      // release notes, community, OHF: link volledig verbergen (rij erboven mee)
      const row = a.closest(".row") || a;
      row.style.display = "none";
    } else {
      // documentatie/logo links: naar btechnics.be
      a.setAttribute("href", BT_SITE);
    }
  });
}

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
  patchLaunchScreen();
  patchLoginPage();
  patchSidebar();
  patchInlineLogos();
  patchExternalLinks();
  patchTitle();
  deepReplaceText(document.body, "Home Assistant", BRAND);
  deepReplaceAttrs(document.body, "Home Assistant", BRAND);
}

(async () => {
  await loadConfig();
  patchLaunchScreen();
  patchTitle();
  patchFavicon();
  new MutationObserver(patchAll)
    .observe(document.documentElement, { childList: true, subtree: true });
  window.addEventListener("load", () => {
    patchAll();
    setInterval(patchAll, 2000);
  });
})();
