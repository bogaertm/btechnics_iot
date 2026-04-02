/**
 * Btechnics IOT Branding v1.1.0
 * Teksten instelbaar via Instellingen → Integraties → Btechnics IOT → Tandwiel
 */

const BT = {
  logo: "https://btechnics.be/logo_btechnics/btechnics.svg",
  icon: "https://btechnics.be/logo_btechnics/btechnics-icon.png",
  loginText: "Btechnics IOT",
  sidebarText: "Btechnics IOT",
};

/* Haal de instellingen op van de HA API */
async function loadConfig() {
  try {
    const r = await fetch("/api/btechnics_branding/config");
    if (r.ok) {
      const data = await r.json();
      BT.loginText   = data.login_text   || BT.loginText;
      BT.sidebarText = data.sidebar_text || BT.sidebarText;
    }
  } catch (e) {}
}

/* 1. Globale CSS */
const style = document.createElement("style");
style.textContent = `
  #ha-launch-screen svg { display: none !important; }
  .ohf-logo             { display: none !important; }
`;
document.head.appendChild(style);

/* 2. Laadscherm logo */
function patchLaunchScreen() {
  const screen = document.getElementById("ha-launch-screen");
  if (!screen || screen.querySelector(".bt-logo")) return;
  const img = document.createElement("img");
  img.className = "bt-logo";
  img.src = BT.logo;
  img.style.cssText = "height:80px;width:auto;flex-shrink:0;";
  const svg = screen.querySelector("svg");
  if (svg) svg.parentNode.insertBefore(img, svg);
  else screen.prepend(img);
}

/* 3. Login logo + tekst */
function patchLoginLogo() {
  // Vervang HA favicon door Btechnics icoon
  document.querySelectorAll('img[src*="favicon-192x192"], img[src*="favicon-512x512"]')
    .forEach(img => { if (!img.dataset.bt) { img.src = BT.icon; img.dataset.bt = "1"; } });

  // Vervang "Welkom thuis!" door de ingestelde login tekst
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    if (node.textContent.includes("Welkom thuis") || node.textContent.includes("Welkom Thuis")) {
      node.textContent = node.textContent.replace(/Welkom [Tt]huis!?/g, BT.loginText);
    }
  }
}

/* 4. Sidebar */
function patchSidebar() {
  const ha     = document.querySelector("home-assistant");
  const main   = ha?.shadowRoot?.querySelector("home-assistant-main");
  const mainSR = main?.shadowRoot;
  if (!mainSR) return;
  const sidebar = mainSR.querySelector("ha-drawer")?.querySelector("ha-sidebar");
  const sr      = sidebar?.shadowRoot;
  if (!sr) return;

  // Logo toevoegen (eenmalig)
  if (!sr.querySelector(".bt-sidebar-logo")) {
    const logo = document.createElement("img");
    logo.className = "bt-sidebar-logo";
    logo.src = BT.logo;
    logo.style.cssText = "height:26px;width:auto;display:block;flex-shrink:0;margin:0 4px 0 8px;";
    const menu = sr.querySelector(".menu");
    if (!menu) return;
    const title = sr.querySelector(".title");
    if (title) {
      for (const node of [...title.childNodes])
        if (node.nodeType === Node.TEXT_NODE) node.textContent = "";
      const span = title.querySelector("span");
      if (span) span.textContent = BT.sidebarText;
      else title.insertAdjacentText("beforeend", BT.sidebarText);
      title.insertBefore(logo, title.firstChild);
    }
  } else {
    // Tekst updaten als instellingen gewijzigd zijn
    const title = sr.querySelector(".title");
    if (title) {
      const span = title.querySelector("span");
      if (span && span.textContent !== BT.sidebarText) span.textContent = BT.sidebarText;
    }
  }
}

/* 5. Tekst in alle shadow DOMs */
function replaceText(root) {
  if (!root) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    if (node.textContent.includes("Home Assistant")) {
      node.textContent = node.textContent.replace(/Home Assistant/g, BT.sidebarText);
    }
  }
  for (const el of root.querySelectorAll?.("*") ?? [])
    if (el.shadowRoot) replaceText(el.shadowRoot);
}

/* 6. Titel en favicon */
function patchTitle() {
  if (document.title.includes("Home Assistant"))
    document.title = document.title.replace(/Home Assistant/g, BT.sidebarText);
}
function patchFavicon() {
  document.querySelectorAll('link[rel*="icon"]').forEach(l => l.remove());
  const link = document.createElement("link");
  link.rel = "icon"; link.type = "image/png"; link.href = BT.icon;
  document.head.appendChild(link);
}

/* 7. Alles samen */
function patchAll() {
  patchLaunchScreen();
  patchLoginLogo();
  patchSidebar();
  patchTitle();
  replaceText(document.body);
}

/* 8. Start: eerst config laden, dan patchen */
(async () => {
  await loadConfig();
  patchLaunchScreen();
  patchTitle();
  patchFavicon();

  new MutationObserver(patchAll)
    .observe(document.documentElement, { childList: true, subtree: true });

  window.addEventListener("load", () => {
    patchAll();
    setInterval(patchAll, 3000);
  });
})();
