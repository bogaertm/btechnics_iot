/**
 * Btechnics IOT Branding v1.6.0
 */
const BRAND = "Btechnics IOT"; // Vaste merknaam - vervangt "Home Assistant" overal

const BT = {
  logo: "https://btechnics.be/logo_btechnics/btechnics.svg",
  icon: "https://btechnics.be/logo_btechnics/btechnics-icon.png",
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
  #ha-launch-screen svg { display: none !important; }
  .ohf-logo             { display: none !important; }
`;
document.head.appendChild(style);

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

function patchLoginLogo() {
  document.querySelectorAll('img[src*="favicon-192x192"], img[src*="favicon-512x512"]')
    .forEach(img => { if (!img.dataset.bt) { img.src = BT.icon; img.dataset.bt = "1"; } });
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

  // Verwijder alle tekst nodes
  for (const node of [...title.childNodes])
    if (node.nodeType === Node.TEXT_NODE) node.remove();

  // Logo (eenmalig)
  if (!sr.querySelector(".bt-sidebar-logo")) {
    const logo = document.createElement("img");
    logo.className = "bt-sidebar-logo";
    logo.src = BT.logo;
    logo.style.cssText = "height:26px;width:auto;display:block;flex-shrink:0;margin:0 4px 0 8px;";
    title.insertBefore(logo, title.firstChild);
  }

  // Tekst-span met instelbare tekst en grootte
  let span = sr.querySelector(".bt-sidebar-text");
  if (!span) {
    span = document.createElement("span");
    span.className = "bt-sidebar-text";
    title.appendChild(span);
  }
  span.textContent = BT.sidebarText;
  span.style.fontSize = BT.sidebarSize + "px";
}

function patchLoginText() {
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    if (node.textContent.includes("Welkom thuis") || node.textContent.includes("Welkom Thuis")) {
      node.textContent = node.textContent.replace(/Welkom [Tt]huis!?/g, BT.loginText);
      if (node.parentElement) node.parentElement.style.fontSize = BT.loginSize + "px";
    }
  }
}

function replaceText(root) {
  // "Home Assistant" wordt altijd vervangen door de vaste merknaam BRAND
  if (!root) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    if (node.nodeType === Node.TEXT_NODE && node.textContent.includes("Home Assistant")) {
      node.textContent = node.textContent.replace(/Home Assistant/g, BRAND);
    }
  }
  for (const el of root.querySelectorAll?.("*") ?? [])
    if (el.shadowRoot) replaceText(el.shadowRoot);
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
  patchLoginLogo();
  patchLoginText();
  patchSidebar();
  patchTitle();
  replaceText(document.body);
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
    setInterval(patchAll, 3000);
  });
})();
