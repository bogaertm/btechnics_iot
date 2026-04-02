/**
 * Btechnics IOT Branding v1.6.0
 * Geladen via configuration.yaml extra_module_url
 */
const BT = {
  name: "Btechnics IOT",
  logo: "https://btechnics.be/logo_btechnics/btechnics.svg",
  icon: "https://btechnics.be/logo_btechnics/btechnics-icon.png",
};

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

/* 3. Login logo - vervangt favicon-192x192.png */
function patchLoginLogo() {
  document.querySelectorAll('img[src*="favicon-192x192"], img[src*="favicon-512x512"]')
    .forEach(img => { if (!img.dataset.bt) { img.src = BT.icon; img.dataset.bt = "1"; } });
}

/* 4. Sidebar */
function patchSidebar() {
  const ha     = document.querySelector("home-assistant");
  const main   = ha?.shadowRoot?.querySelector("home-assistant-main");
  const mainSR = main?.shadowRoot;
  if (!mainSR) return;
  const sidebar = mainSR.querySelector("ha-drawer")?.querySelector("ha-sidebar");
  const sr      = sidebar?.shadowRoot;
  if (!sr || sr.querySelector(".bt-sidebar-logo")) return;

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
    if (span) span.textContent = BT.name;
    else title.insertAdjacentText("beforeend", BT.name);
    title.insertBefore(logo, title.firstChild);
  }
}

/* 5. Tekst in alle shadow DOMs */
function replaceText(root) {
  if (!root) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    if (node.textContent.includes("Home Assistant") || node.textContent.includes("Welkom thuis")) {
      node.textContent = node.textContent
        .replace(/Home Assistant/g, BT.name)
        .replace(/Welkom thuis!/gi, BT.name)
        .replace(/Welkom Thuis!/gi, BT.name);
    }
  }
  for (const el of root.querySelectorAll?.("*") ?? [])
    if (el.shadowRoot) replaceText(el.shadowRoot);
}

/* 6. Titel en favicon */
function patchTitle() {
  if (document.title.includes("Home Assistant") || document.title.includes("Welkom thuis"))
    document.title = document.title.replace(/Home Assistant|Welkom thuis/gi, BT.name);
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

patchLaunchScreen();
patchTitle();
patchFavicon();

new MutationObserver(patchAll)
  .observe(document.documentElement, { childList: true, subtree: true });

window.addEventListener("load", () => {
  patchAll();
  setInterval(patchAll, 3000);
});
