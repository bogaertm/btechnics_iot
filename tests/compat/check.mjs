// Compatibiliteitstest Btechnics IOT tegen een echte HA container.
// Doet de onboarding via de API, installeert de integratie, en controleert dan
// de server (HTTP) en de interface (Playwright, ingelogd). Exit 1 bij een fout.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const BASE = process.env.HA_URL || "http://localhost:8123";
const CLIENT_ID = BASE + "/";
const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../..");
const COMP = path.join(ROOT, "custom_components/btechnics_branding");

const results = [];
const ok = (name, pass, detail = "") => {
  results.push({ name, pass, detail });
  console.log(`${pass ? "OK  " : "FOUT"}  ${name}${detail ? "  (" + detail + ")" : ""}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitFor(url, maxS = 600) {
  for (let i = 0; i < maxS / 5; i++) {
    try { const r = await fetch(url, { signal: AbortSignal.timeout(5000) }); if (r.status < 500) return true; } catch {}
    await sleep(5000);
  }
  return false;
}

// ---------------------------------------------------------------- opstart
if (!(await waitFor(BASE + "/api/onboarding"))) {
  ok("HA start op", false, "geen antwoord na 10 minuten");
  process.exit(1);
}
ok("HA start op", true);

// ---------------------------------------------------------------- onboarding
let r = await fetch(BASE + "/api/onboarding/users", {
  method: "POST", headers: { "content-type": "application/json" },
  body: JSON.stringify({ client_id: CLIENT_ID, name: "Test", username: "test", password: "test12345", language: "nl" }),
});
const { auth_code } = await r.json();
r = await fetch(BASE + "/auth/token", {
  method: "POST",
  body: new URLSearchParams({ grant_type: "authorization_code", code: auth_code, client_id: CLIENT_ID }),
});
const tokens = await r.json();
const H = { authorization: "Bearer " + tokens.access_token, "content-type": "application/json" };
await fetch(BASE + "/api/onboarding/core_config", { method: "POST", headers: H, body: "{}" });
await fetch(BASE + "/api/onboarding/analytics", { method: "POST", headers: H, body: "{}" });
await fetch(BASE + "/api/onboarding/integration", {
  method: "POST", headers: H, body: JSON.stringify({ client_id: CLIENT_ID, redirect_uri: BASE + "/?auth_callback=1" }),
});
ok("Onboarding via API", !!tokens.access_token);

// ---------------------------------------------------------------- integratie
r = await fetch(BASE + "/api/config/config_entries/flow", { method: "POST", headers: H, body: JSON.stringify({ handler: "btechnics_branding" }) });
let flow = await r.json();
if (flow.type === "form") {
  r = await fetch(BASE + "/api/config/config_entries/flow/" + flow.flow_id, { method: "POST", headers: H, body: "{}" });
  flow = await r.json();
}
ok("Integratie installeert", flow.type === "create_entry", flow.type + " " + (flow.reason || ""));
await sleep(8000);

// ---------------------------------------------------------------- HTTP
const text = async (u, h = {}) => (await fetch(BASE + u, { headers: h })).text();
const bytes = async (u) => Buffer.from(await (await fetch(BASE + u)).arrayBuffer());

const man = JSON.parse(await text("/manifest.json"));
ok("Manifest: naam", man.name === "Btechnics IOT", man.name);
ok("Manifest: iconen", (man.icons || []).every((i) => i.src.startsWith("/btechnics_branding/")));

const index = await text("/");
ok("Index: onze CSS", index.includes("bt-hide"));
ok("Index: titel", index.includes("<title>Btechnics IOT</title>"));
ok("Index: opstartlogo", index.includes("/btechnics_branding/logo.svg") && !index.includes("home-assistant-logo-loading.svg"));
ok("Index: naam beginscherm", !index.includes('content="Home Assistant"'));
ok("Index: Btechnics script geladen", index.includes("/btechnics_branding/btechnics-branding.js"));

const auth = await text("/auth/authorize?response_type=code&client_id=" + encodeURIComponent(CLIENT_ID) + "&redirect_uri=" + encodeURIComponent(CLIENT_ID));
ok("Aanmeldscherm: script en titel", auth.includes("btechnics-branding.js") && auth.includes("Btechnics IOT"));

const icon = fs.readFileSync(path.join(COMP, "app-icon-192.png"));
ok("Static favicon vervangen", (await bytes("/static/icons/favicon-192x192.png")).equals(icon));
ok("Static maskable icoon vervangen", (await bytes("/static/icons/maskable_icon-192x192.png")).equals(icon));
const logo = fs.readFileSync(path.join(COMP, "logo.svg"));
ok("Static HA logo vervangen", (await bytes("/static/images/home-assistant-logo-loading.svg")).equals(logo));

const cfg = await (await fetch(BASE + "/api/btechnics_branding/config")).json().catch(() => null);
ok("Config API", !!cfg && "zoom_desktop" in cfg);

// ---------------------------------------------------------------- frontend bundel
// Tekenreeksen waar de branding op steunt. Verdwijnt er een, dan heeft HA iets
// hernoemd en werkt die aanpassing stil niet meer.
const where = spawnSync("docker", ["exec", "bt-ha", "python3", "-c", "import hass_frontend;print(hass_frontend.where())"], { encoding: "utf8" }).stdout.trim();
if (where) {
  const grep = (needle, sub) => spawnSync("docker", ["exec", "bt-ha", "grep", "-rlF", needle, where + "/" + sub], { encoding: "utf8" }).stdout.trim().length > 0;
  const needles = [
    ["index.html", "home-assistant-logo-loading.svg", "opstartlogo in index.html"],
    ["index.html", 'name="apple-mobile-web-app-title"', "naam beginscherm"],
    ["index.html", "ha-launch-screen", "opstartscherm"],
    ["frontend_latest", "home-assistant-main", "hoofdelement"],
    ["frontend_latest", "ha-sidebar", "zijbalk"],
    ["frontend_latest", "m12.151 1.5882", "vorm HA logo"],
    ["frontend_latest", "frontend/set_system_data", "enquete opslag"],
    ["frontend_latest", "cloud-discover", "cloud promo"],
    ["frontend_latest", "ha-tip", "tip balk"],
    ["frontend_latest", "/api/brands/integration/", "brands API"],
  ];
  for (const [sub, n, label] of needles) ok("Frontend bevat: " + label, grep(n, sub), n);
} else {
  ok("Frontend map gevonden", false);
}

// ---------------------------------------------------------------- interface
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
const stored = {
  ...tokens, hassUrl: BASE, clientId: CLIENT_ID,
  expires: Date.now() + tokens.expires_in * 1000,
};
await ctx.addInitScript((t) => { localStorage.setItem("hassTokens", JSON.stringify(t)); }, stored);
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => { if (/btechnics/i.test(e.stack || "")) errors.push(e.message); });

const AUDIT = () => {
  const out = { text: [], icons: 0, cloud: 0 };
  const EDIT = ".cm-editor, [contenteditable], textarea, input, pre, code";
  const vis = (e) => { const b = e.getBoundingClientRect(); return b.width > 0 && b.height > 0; };
  const walk = (root) => {
    const tw = document.createTreeWalker(root, NodeFilter.SHOW_TEXT); let n;
    while ((n = tw.nextNode())) {
      const p = n.parentElement;
      if (/Home Assistant/.test(n.textContent) && p && !p.closest(EDIT) && vis(p)) out.text.push(n.textContent.trim().slice(0, 80));
    }
    for (const e of root.querySelectorAll("*")) {
      if (e.tagName === "HA-SVG-ICON" && String(e.path || "").startsWith("m12.151 1.5882") && !e.shadowRoot?.querySelector(".bt-inline-logo") && vis(e)) out.icons++;
      if (e.tagName === "A" && e.getAttribute("href") === "/config/cloud" && vis(e)) out.cloud++;
      if (e.shadowRoot) walk(e.shadowRoot);
    }
  };
  walk(document);
  return out;
};

await page.goto(BASE + "/config/dashboard");
await sleep(25000); // zelfcontrole meldt na 20 s
const ui = await page.evaluate(async () => {
  const ha = document.querySelector("home-assistant");
  const hass = ha.hass;
  const sb = ha.shadowRoot.querySelector("home-assistant-main")?.shadowRoot?.querySelector("ha-sidebar")?.shadowRoot;
  const issues = await hass.callWS({ type: "repairs/list_issues" }).catch(() => ({ issues: [] }));
  return {
    title: document.title,
    sidebarLogo: !!sb?.querySelector(".bt-sidebar-logo"),
    sidebarText: sb?.querySelector(".bt-sidebar-text")?.textContent || "",
    primary: getComputedStyle(document.documentElement).getPropertyValue("--primary-color").trim(),
    survey: !!hass.systemData?.surveys?.onboarding,
    btIssues: (issues.issues || []).filter((i) => i.domain === "btechnics_branding").map((i) => i.translation_placeholders?.problems || i.issue_id),
  };
});
ok("UI: titel", ui.title.includes("Btechnics IOT"), ui.title);
ok("UI: logo in zijbalk", ui.sidebarLogo);
ok("UI: tekst in zijbalk", ui.sidebarText === "Btechnics IOT", ui.sidebarText);
ok("UI: petrol als primaire kleur", ui.primary.toLowerCase() === "#00222b", ui.primary);
ok("UI: enquete uit", ui.survey);
ok("UI: zelfcontrole zonder melding", ui.btIssues.length === 0, ui.btIssues.join("; "));

for (const p of ["/config/dashboard", "/config/info", "/config/integrations/dashboard", "/config/voice-assistants/assistants", "/logbook"]) {
  await page.goto(BASE + p);
  await sleep(6000);
  const a = await page.evaluate(AUDIT);
  ok(`UI ${p}: geen "Home Assistant"`, a.text.length === 0, a.text.slice(0, 3).join(" | "));
  ok(`UI ${p}: geen HA logo`, a.icons === 0, String(a.icons));
  if (p === "/config/dashboard") ok("UI: cloud verborgen", a.cloud === 0);
}
ok("UI: geen JS fouten van Btechnics", errors.length === 0, errors.slice(0, 2).join(" | "));

// Zelfcontrole zelf testen: een probleem melden moet een reparatie geven, en
// "alles goed" moet ze weer weghalen.
const listBt = () => page.evaluate(async () => {
  const r = await document.querySelector("home-assistant").hass.callWS({ type: "repairs/list_issues" });
  return r.issues.filter((i) => i.domain === "btechnics_branding").length;
});
await fetch(BASE + "/api/btechnics_branding/health", { method: "POST", headers: H, body: JSON.stringify({ problems: ["sidebar"] }) });
await sleep(1000);
const na1 = await listBt();
await fetch(BASE + "/api/btechnics_branding/health", { method: "POST", headers: H, body: JSON.stringify({ problems: [] }) });
await sleep(1000);
const na2 = await listBt();
ok("Zelfcontrole maakt en wist melding", na1 === 1 && na2 === 0, `${na1} -> ${na2}`);
const anon = await fetch(BASE + "/api/btechnics_branding/health", { method: "POST", body: "{}" });
ok("Zelfcontrole vraagt aanmelding", anon.status === 401, String(anon.status));
await browser.close();

// ---------------------------------------------------------------- automatische updates
{
  const entries = await (await fetch(BASE + "/api/config/config_entries/entry", { headers: H })).json();
  const entry = entries.find((e) => e.domain === "btechnics_branding");
  let f = await (await fetch(BASE + "/api/config/config_entries/options/flow", { method: "POST", headers: H, body: JSON.stringify({ handler: entry.entry_id }) })).json();
  const fields = (f.data_schema || []).map((x) => x.name);
  ok("Opties tonen automatische updates", ["auto_update", "auto_update_time", "auto_update_categories", "auto_update_backup"].every((n) => fields.includes(n)), fields.join(","));
  f = await (await fetch(BASE + "/api/config/config_entries/options/flow/" + f.flow_id, { method: "POST", headers: H,
    body: JSON.stringify({ auto_update: true, auto_update_time: "04:00:00", auto_update_categories: ["system", "addons", "hacs", "firmware"], auto_update_backup: true }) })).json();
  ok("Opties bewaren", f.type === "create_entry", f.type + " " + JSON.stringify(f.errors || ""));

  const states = await (await fetch(BASE + "/api/states", { headers: H })).json();
  const avail = states.filter((s) => s.entity_id.startsWith("update.") && s.state === "on" && (s.attributes.supported_features & 1)).map((s) => s.entity_id);
  const call = async (dry) => (await fetch(BASE + "/api/services/btechnics_branding/run_updates?return_response", { method: "POST", headers: H, body: JSON.stringify({ dry_run: dry }) })).json();
  const dry = await call(true);
  const plan = dry.service_response || {};
  ok("Dry run toont plan", Array.isArray(plan.zou_installeren) && plan.zou_installeren.length === avail.length, `${(plan.zou_installeren || []).length} van ${avail.length} beschikbaar`);
  const still1 = (await (await fetch(BASE + "/api/states", { headers: H })).json()).filter((s) => s.entity_id.startsWith("update.") && s.state === "on" && (s.attributes.supported_features & 1)).length;
  ok("Dry run installeert niets", still1 === avail.length, String(still1));

  const real = (await call(false)).service_response || {};
  ok("Run start op de achtergrond", Array.isArray(real.gestart) && real.gestart.length === plan.zou_installeren.length, String((real.gestart || []).length));
  // Een update na de andere; de demo met 1000 stappen doet er zelf minuten over.
  // Geslaagd als alles geinstalleerd is of nog bezig is (in_progress).
  let open = avail.length, busy = 0;
  for (let i = 0; i < 36; i++) {
    await sleep(5000);
    const st = (await (await fetch(BASE + "/api/states", { headers: H })).json()).filter((s) => avail.includes(s.entity_id) && s.state === "on");
    busy = st.filter((s) => s.attributes.in_progress).length;
    open = st.length - busy;
    if (open === 0) break;
  }
  ok("Echte run installeert alles wat kan", open === 0, `niet gestart: ${open}, bezig: ${busy}`);
  // Stoppen bij een branding probleem
  await fetch(BASE + "/api/btechnics_branding/health", { method: "POST", headers: H, body: JSON.stringify({ problems: ["sidebar"] }) });
  const stopped = (await call(true)).service_response || {};
  ok("Stopt bij probleem met branding", stopped.branding_probleem === true, JSON.stringify(stopped).slice(0, 80));
  await fetch(BASE + "/api/btechnics_branding/health", { method: "POST", headers: H, body: JSON.stringify({ problems: [] }) });
}

// ---------------------------------------------------------------- planning op het uur
{
  const cfg = await (await fetch(BASE + "/api/config", { headers: H })).json();
  const nu = new Date(Date.now() + 70 * 1000);
  const hhmm = new Intl.DateTimeFormat("nl-BE", { timeZone: cfg.time_zone, hour: "2-digit", minute: "2-digit", hour12: false }).format(nu);
  const entries = await (await fetch(BASE + "/api/config/config_entries/entry", { headers: H })).json();
  const entry = entries.find((e) => e.domain === "btechnics_branding");
  let f = await (await fetch(BASE + "/api/config/config_entries/options/flow", { method: "POST", headers: H, body: JSON.stringify({ handler: entry.entry_id }) })).json();
  f = await (await fetch(BASE + "/api/config/config_entries/options/flow/" + f.flow_id, { method: "POST", headers: H,
    body: JSON.stringify({ auto_update: true, auto_update_time: hhmm + ":00", auto_update_categories: ["system", "addons", "hacs", "firmware"], auto_update_backup: true }) })).json();
  let last = null;
  for (let i = 0; i < 30; i++) {
    await sleep(5000);
    last = (await (await fetch(BASE + "/api/btechnics_branding/health", { headers: H })).json()).auto_update_last;
    if (last && last.trigger === "schema") break;
  }
  ok("Start zelf op het ingestelde uur", !!last && last.trigger === "schema", `${hhmm} ${cfg.time_zone} -> ${last ? last.trigger + " " + last.started : "niets"}`);
}

// ---------------------------------------------------------------- resultaat
const fails = results.filter((x) => !x.pass);
console.log(`\n${results.length - fails.length}/${results.length} geslaagd`);
if (process.env.GITHUB_STEP_SUMMARY) {
  fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY,
    `### Btechnics IOT tegen HA ${process.env.HA_TAG || ""}\n\n| Test | Resultaat |\n|---|---|\n` +
    results.map((x) => `| ${x.name} | ${x.pass ? "OK" : "**FOUT** " + x.detail} |`).join("\n") + "\n");
}
process.exit(fails.length ? 1 : 0);
