/**
 * Btechnics IOT Branding v1.7.0
 */
const BRAND = "Btechnics IOT";

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
  const svg = screen.querySelector("svg");
  if (svg) svg.parentNode.insertBefore(img, svg);
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
  patchTitle();
  deepReplaceText(document.body, "Home Assistant", BRAND);
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
