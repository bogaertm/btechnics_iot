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

// ---------------------------------------------------------------- woordkeuze (v1.34.0)
// Nederlandstalige browser: "woning", "je huis" en "Welkom thuis" worden neutraal.
{
  const deepText = () => {
    const out = [];
    const walk = (r) => {
      const tw = document.createTreeWalker(r, NodeFilter.SHOW_TEXT);
      let n; while ((n = tw.nextNode())) { const t = n.parentNode && n.parentNode.nodeName; if (t !== "SCRIPT" && t !== "STYLE") out.push(n.textContent); }
      r.querySelectorAll("*").forEach((el) => { if (el.shadowRoot) walk(el.shadowRoot); });
    };
    walk(document);
    return out.join(" | ");
  };
  const nlLogin = await browser.newContext({ locale: "nl-BE" });
  const lp = await nlLogin.newPage();
  await lp.goto(BASE + "/auth/authorize?response_type=code&client_id=" + encodeURIComponent(CLIENT_ID) + "&redirect_uri=" + encodeURIComponent(CLIENT_ID));
  await sleep(6000);
  const lt = await lp.evaluate(deepText);
  ok("NL aanmeldscherm: Welkom! (niet thuis)", lt.includes("Welkom!") && !/Welkom thuis/.test(lt), (lt.match(/Welkom[^|]{0,20}/) || [""])[0]);
  await nlLogin.close();

  const nl = await browser.newContext({ locale: "nl-BE", viewport: { width: 1400, height: 900 } });
  await nl.addInitScript((t) => { localStorage.setItem("hassTokens", JSON.stringify(t)); localStorage.setItem("selectedLanguage", JSON.stringify("nl")); }, stored);
  const np = await nl.newPage();
  await np.goto(BASE + "/config/dashboard"); await sleep(8000);
  const dt = await np.evaluate(deepText);
  const loc = await np.evaluate(async () => {
    const u = performance.getEntriesByType("resource").map((e) => e.name).find((n) => /\/static\/translations\/config\/nl-[0-9a-f]+\.json/.test(n));
    if (!u) return ["geen config vertaling geladen"];
    const d = await (await fetch(u)).json();
    return [d["ui.panel.config.automation.description"], d["ui.panel.config.dashboard.people.secondary"], d["ui.panel.config.energy.battery.title"]];
  });
  ok("NL teksten: 'je locatie' i.p.v. 'je huis'", /je locatie/.test(loc[0]) && /je locatie/.test(loc[1] || "") && !/huis|woning/i.test(loc.join(" ")), JSON.stringify(loc));
  await np.goto(BASE + "/config/system"); await sleep(6000);
  const st = await np.evaluate(deepText);
  ok("NL Systeem: Algemeen i.p.v. Woninginformatie", st.includes("Algemeen") && !st.includes("Woninginformatie"), (st.match(/Algemeen|Woninginformatie/) || ["niets"])[0]);
  await np.screenshot({ path: (process.env.SHOT || "/tmp/bt.png").replace(/\.png$/, "_systeem.png") });
  await np.goto(BASE + "/config/general"); await sleep(6000);
  const ct = await np.evaluate(deepText);
  ok("NL Algemeen: Locatienaam i.p.v. Woningnaam", ct.includes("Locatienaam") && !ct.includes("Woningnaam"), (ct.match(/Locatienaam|Woningnaam/) || ["niets"])[0]);
  await np.screenshot({ path: (process.env.SHOT || "/tmp/bt.png").replace(/\.png$/, "_algemeen.png") });
  await nl.close();
  // Engelstalig blijft ongemoeid
  await page.goto(BASE + "/config/general"); await sleep(6000);
  const et = await page.evaluate(deepText);
  ok("EN ongemoeid", !et.includes("Locatienaam"), (et.match(/Home name|Location name|Name/) || ["?"])[0]);
}

// ---------------------------------------------------------------- automatische updates
// Testentiteiten (tests/compat/fake_update): update.test_ok slaagt,
// update.test_faalt mislukt altijd, update.test_enkel_melding kan niet installeren.
{
  const entries = await (await fetch(BASE + "/api/config/config_entries/entry", { headers: H })).json();
  const entry = entries.find((e) => e.domain === "btechnics_branding");
  const setOpts = async (o) => {
    let f = await (await fetch(BASE + "/api/config/config_entries/options/flow", { method: "POST", headers: H, body: JSON.stringify({ handler: entry.entry_id }) })).json();
    const fields = (f.data_schema || []).map((x) => x.name);
    f = await (await fetch(BASE + "/api/config/config_entries/options/flow/" + f.flow_id, { method: "POST", headers: H, body: JSON.stringify(o) })).json();
    return { f, fields };
  };
  const ALLES = { auto_update: true, auto_update_time: "04:00:00", auto_update_categories: ["system", "addons", "hacs", "firmware"], auto_update_backup: true };
  const { f, fields } = await setOpts(ALLES);
  ok("Opties tonen automatische updates", ["auto_update", "auto_update_time", "auto_update_categories", "auto_update_backup"].every((n) => fields.includes(n)), fields.join(","));
  ok("Opties bewaren", f.type === "create_entry", f.type);
  await sleep(2000);

  const ws = (msg) => page.evaluate((m) => document.querySelector("home-assistant").hass.callWS(m), msg);
  const reg = async (eid) => (await ws({ type: "config/entity_registry/get", entity_id: eid }));
  const st = async (eid) => (await fetch(BASE + "/api/states/" + eid, { headers: H })).json();
  const issues = async () => (await ws({ type: "repairs/list_issues" })).issues.filter((i) => i.domain === "btechnics_branding").map((i) => i.issue_id);
  const badge = () => page.evaluate(() => {
    const sb = document.querySelector("home-assistant").shadowRoot.querySelector("home-assistant-main").shadowRoot.querySelector("ha-sidebar");
    return sb._updatesCount;
  });
  const call = async (dry) => (await (await fetch(BASE + "/api/services/btechnics_branding/run_updates?return_response", { method: "POST", headers: H, body: JSON.stringify({ dry_run: dry }) })).json()).service_response || {};

  ok("Verborgen: update die slaagt", (await reg("update.test_ok")).hidden_by === "integration");
  ok("Verborgen: update die faalt", (await reg("update.test_faalt")).hidden_by === "integration");
  ok("Niet verborgen: enkel melding (kan niet installeren)", (await reg("update.test_enkel_melding")).hidden_by === null);
  await page.goto(BASE + "/config/dashboard"); await sleep(8000);
  // HA telt enkel installeerbare updates; zonder verbergen zou dit 2 zijn (ok + faalt)
  ok("Zijbalk toont geen automatische updates", (await badge()) === 0, String(await badge()));

  const dry = await call(true);
  ok("Dry run toont plan", (dry.zou_installeren || []).length === 2, JSON.stringify(dry.zou_installeren));

  await call(false); await sleep(4000);
  ok("Run 1: test_ok geinstalleerd", (await st("update.test_ok")).state === "off");
  ok("Run 1: test_ok weer gewoon zichtbaar (niets meer open)", (await reg("update.test_ok")).hidden_by === null);
  ok("Run 1: test_faalt nog verborgen na 1 poging", (await reg("update.test_faalt")).hidden_by === "integration");
  ok("Run 1: nog geen melding", !(await issues()).some((i) => i.startsWith("update_failed_")));

  // v1.32.1: even unavailable (opstarten, herstart) mag de telling niet wissen
  await fetch(BASE + "/api/states/update.test_faalt", { method: "POST", headers: H, body: JSON.stringify({ state: "unavailable" }) });
  await sleep(1500);
  ok("Unavailable: blijft verborgen", (await reg("update.test_faalt")).hidden_by === "integration");
  await fetch(BASE + "/api/services/homeassistant/update_entity", { method: "POST", headers: H, body: JSON.stringify({ entity_id: "update.test_faalt" }) });
  await sleep(1500);
  ok("Unavailable: daarna terug aan en verborgen", (await st("update.test_faalt")).state === "on" && (await reg("update.test_faalt")).hidden_by === "integration");

  await call(false); await sleep(4000);
  ok("Run 2: test_faalt zichtbaar na 2 pogingen", (await reg("update.test_faalt")).hidden_by === null);
  ok("Run 2: melding onder Reparaties", (await issues()).includes("update_failed_update.test_faalt"), (await issues()).join(","));
  await page.goto(BASE + "/config/dashboard"); await sleep(8000);
  ok("Zijbalk toont de mislukte update", (await badge()) === 1, String(await badge()));

  // v1.32.1: icoon van een HACS update (brands.home-assistant.io kent Btechnics niet)
  const badgeBg = () => page.evaluate(() => {
    const out = [];
    const walk = (r) => r.querySelectorAll("*").forEach((el) => {
      if (el.tagName === "STATE-BADGE" && el.stateObj && el.stateObj.entity_id === "update.test_faalt") out.push(el.style.backgroundImage);
      if (el.shadowRoot) walk(el.shadowRoot);
    });
    walk(document);
    return out;
  });
  let bgs = await badgeBg();
  ok("Update icoon: Btechnics logo", bgs.length > 0 && bgs.every((b) => b.includes("/btechnics_branding/app-icon-192.png")), JSON.stringify(bgs));
  // De frontend tekent het icoon opnieuw bij elke wijziging van de update
  await fetch(BASE + "/api/states/update.test_faalt", { method: "POST", headers: H, body: JSON.stringify({ state: "on", attributes: { ...(await st("update.test_faalt")).attributes, release_summary: "hertekenen" } }) });
  await sleep(1000);
  const tussen = await badgeBg();
  await sleep(3000);
  bgs = await badgeBg();
  ok("Update icoon: blijft na hertekenen", bgs.length > 0 && bgs.every((b) => b.includes("/btechnics_branding/app-icon-192.png")), "tussen " + JSON.stringify(tussen) + " na " + JSON.stringify(bgs));
  await page.screenshot({ path: process.env.SHOT || "/tmp/bt-updates.png", clip: { x: 256, y: 0, width: 1144, height: 500 } });

  // v1.33.1: HACS draait in een iframe (zelfde domein) met eigen detailvenster.
  // Nagebootst: iframe in een shadow root met een img en een state-badge zoals HACS ze maakt.
  await page.evaluate(() => {
    const host = document.createElement("div");
    host.id = "bt-hacs-test";
    const sr = host.attachShadow({ mode: "open" });
    const f = document.createElement("iframe");
    f.srcdoc = '<img id="i" src="https://brands.home-assistant.io/_/btechnics_branding/dark_icon.png">' +
      '<state-badge id="b" style="display:block;width:40px;height:40px;background-image:url(https://brands.home-assistant.io/_/btechnics_branding/icon.png)"></state-badge>';
    sr.appendChild(f);
    document.body.appendChild(host);
  });
  await sleep(5000);
  const inFrame = await page.evaluate(() => {
    const d = document.getElementById("bt-hacs-test").shadowRoot.querySelector("iframe").contentDocument;
    return { img: d.getElementById("i").getAttribute("src"), badge: d.getElementById("b").style.backgroundImage };
  });
  ok("HACS iframe: logo in lijst", /\/btechnics_branding\/app-icon-192\.png/.test(inFrame.img), inFrame.img);
  ok("HACS iframe: logo in detailvenster", /\/btechnics_branding\/app-icon-192\.png/.test(inFrame.badge), inFrame.badge);
  await page.evaluate(() => document.getElementById("bt-hacs-test").remove());

  // v1.33.1: logo op de Info pagina (ha-logo-svg)
  await page.goto(BASE + "/config/info"); await sleep(6000);
  const info = await page.evaluate(() => {
    const out = [];
    const walk = (r) => r.querySelectorAll("*").forEach((el) => {
      if (el.tagName === "HA-LOGO-SVG") out.push(!!(el.shadowRoot && el.shadowRoot.querySelector(".bt-inline-logo")));
      if (el.shadowRoot) walk(el.shadowRoot);
    });
    walk(document);
    return out;
  });
  ok("Info pagina: Btechnics logo", info.length > 0 && info.every(Boolean), JSON.stringify(info));
  await page.goto(BASE + "/config/dashboard"); await sleep(6000);

  // v1.33.1: een gewone gebruiker (geen beheerder) mag geen updates starten
  const nu = await ws({ type: "config/auth/create", name: "Gewoon", group_ids: ["system-users"], local_only: false });
  await ws({ type: "config/auth_provider/homeassistant/create", user_id: nu.user.id, username: "gewoon", password: "gewoon12345" });
  let lf = await (await fetch(BASE + "/auth/login_flow", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ client_id: CLIENT_ID, handler: ["homeassistant", null], redirect_uri: CLIENT_ID }) })).json();
  lf = await (await fetch(BASE + "/auth/login_flow/" + lf.flow_id, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ client_id: CLIENT_ID, username: "gewoon", password: "gewoon12345" }) })).json();
  const ut = await (await fetch(BASE + "/auth/token", { method: "POST", body: new URLSearchParams({ grant_type: "authorization_code", code: lf.result, client_id: CLIENT_ID }) })).json();
  const UH = { authorization: "Bearer " + ut.access_token, "content-type": "application/json" };
  const r1 = await fetch(BASE + "/api/services/btechnics_branding/run_updates?return_response", { method: "POST", headers: UH, body: "{}" });
  const r2 = await fetch(BASE + "/api/services/btechnics_branding/send_status?return_response", { method: "POST", headers: UH, body: "{}" });
  ok("Gewone gebruiker: geen updates starten", !!ut.access_token && r1.status === 401, "run_updates " + r1.status);
  ok("Gewone gebruiker: geen status versturen", !!ut.access_token && r2.status === 401, "send_status " + r2.status);

  const dry3 = await call(true);
  ok("Run 3: faalt niet meer geprobeerd", (dry3.zou_installeren || []).length === 0 && (dry3.overgeslagen || []).some((x) => /2 keer mislukt/.test(x)), JSON.stringify(dry3));

  // Gebruiker verbergt zelf: blijft van hem
  await ws({ type: "config/entity_registry/update", entity_id: "update.test_enkel_melding", hidden_by: "user" });
  // Uitzetten: alles wat wij verborgen, komt terug; meldingen weg
  await setOpts({ ...ALLES, auto_update: false }); await sleep(2000);
  ok("Uit: melding weg", !(await issues()).some((i) => i.startsWith("update_failed_")));
  ok("Uit: verborgen door gebruiker blijft verborgen", (await reg("update.test_enkel_melding")).hidden_by === "user");

  // Weer aan: test_faalt blijft zichtbaar (zelfde versie, 2 pogingen onthouden)
  await setOpts(ALLES); await sleep(2000);
  ok("Aan: 2 mislukte pogingen onthouden", (await reg("update.test_faalt")).hidden_by === null);

  // v1.33.0: status naar Btechnics. Nep Work-app op de host (docker gateway).
  const http = await import("node:http");
  const ontvangen = [];
  const wachtrij = [], resultaten = [], opgehaald = [];
  const srv = http.createServer((req, res) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      res.writeHead(200, { "content-type": "application/json" });
      if (req.method === "GET" && req.url.startsWith("/commands")) {
        opgehaald.push(req.headers.authorization);
        const q = wachtrij.splice(0); return res.end(JSON.stringify({ commands: q }));
      }
      if (req.url.startsWith("/commands/result")) { try { resultaten.push(JSON.parse(body)); } catch (e) {} return res.end("{}"); }
      try { ontvangen.push({ auth: req.headers.authorization, body: JSON.parse(body) }); } catch (e) {}
      res.end("{}");
    });
  });
  await new Promise((r) => srv.listen(8999, "0.0.0.0", r));
  const GW = process.env.BT_GATEWAY || "172.17.0.1";
  const zonder = (await (await fetch(BASE + "/api/services/btechnics_branding/send_status?return_response", { method: "POST", headers: H, body: "{}" })).json()).service_response;
  ok("Status: zonder sleutel niets verstuurd", zonder && zonder.resultaat.ok === false && ontvangen.length === 0, JSON.stringify(zonder && zonder.resultaat));
  await setOpts({ ...ALLES, status_url: `http://${GW}:8999/status`, status_token: "testsleutel" }); await sleep(1000);
  const met = (await (await fetch(BASE + "/api/services/btechnics_branding/send_status?return_response", { method: "POST", headers: H, body: "{}" })).json()).service_response;
  const laatste = ontvangen[ontvangen.length - 1];
  ok("Status: verstuurd met sleutel", met && met.resultaat.ok === true && laatste && laatste.auth === "Bearer testsleutel", JSON.stringify(met && met.resultaat));
  const b = laatste ? laatste.body : {};
  // v1.33.1: https verplicht (behalve lokaal adres)
  const fout = await setOpts({ ...ALLES, status_url: "http://work.btechnics.be/api/iot/status", status_token: "testsleutel" });
  ok("Status: http naar buiten geweigerd", fout.f.type === "form" && fout.f.errors && fout.f.errors.status_url === "status_url_https", JSON.stringify(fout.f.errors));
  ok("Status: inhoud", !!b.instance_id && !!b.versions && b.versions.integration === "1.34.0" && Array.isArray(b.updates.failed) && b.updates.failed.some((u) => u.entity_id === "update.test_faalt") && b.auto_update.enabled === true, JSON.stringify({ id: b.instance_id, v: b.versions, failed: b.updates && b.updates.failed.map((u) => u.entity_id) }));
  ok("Status: geen sleutel in het bericht", !JSON.stringify(b).includes("testsleutel"));

  // v1.34.0: bediening op afstand. De installatie haalt elke minuut opdrachten op.
  wachtrij.push(
    { id: "c1", type: "set_auto_update", time: "05:30", categories: ["system", "addons", "hacs", "firmware"], backup: false },
    { id: "c2", type: "run_updates", dry_run: true },
    { id: "c3", type: "retry_failed", entity_id: "update.test_faalt" },
    { id: "c4", type: "skip_update", entity_id: "update.test_faalt" },
    { id: "c5", type: "clear_skipped", entity_id: "update.test_faalt" },
    { id: "c6", type: "install_update", entity_id: "update.test_faalt" },
    { id: "c7", type: "restart" },
    { id: "c8", type: "install_update", entity_id: "light.keuken" },
  );
  for (let i = 0; i < 30 && resultaten.length < 8; i++) await sleep(3000);
  const R = Object.fromEntries(resultaten.map((x) => [x.id, x]));
  ok("Op afstand: opdrachten opgehaald met sleutel", opgehaald.length > 0 && opgehaald.every((a) => a === "Bearer testsleutel"), String(opgehaald.length));
  ok("Op afstand: alle 8 resultaten terug", resultaten.length === 8, resultaten.map((x) => x.id + ":" + x.ok).join(","));
  ok("Op afstand: instellingen aangepast", R.c1 && R.c1.ok && R.c1.result.time === "05:30:00" && R.c1.result.backup === false, JSON.stringify(R.c1));
  ok("Op afstand: dry run", R.c2 && R.c2.ok && Array.isArray(R.c2.result.zou_installeren), JSON.stringify(R.c2 && R.c2.result));
  ok("Op afstand: overslaan en terugzetten", R.c4 && R.c4.ok && R.c5 && R.c5.ok && (await st("update.test_faalt")).state === "on", JSON.stringify([R.c4, R.c5]));
  ok("Op afstand: mislukte installatie gemeld", R.c6 && R.c6.ok === false && /testfout/.test(R.c6.error), JSON.stringify(R.c6));
  ok("Op afstand: onbekende opdracht geweigerd", R.c7 && R.c7.ok === false && /onbekende opdracht/.test(R.c7.error), JSON.stringify(R.c7));
  ok("Op afstand: enkel update entiteiten", R.c8 && R.c8.ok === false && /update\.\*/.test(R.c8.error), JSON.stringify(R.c8));
  ok("Op afstand: na retry_failed weer verborgen", R.c3 && R.c3.ok && (await reg("update.test_faalt")).hidden_by === "integration", String((await reg("update.test_faalt")).hidden_by));
  await sleep(12000);
  const naOpAfstand = ontvangen.filter((x) => /op_afstand/.test(x.body.reason || ""));
  ok("Op afstand: status meteen bijgewerkt", naOpAfstand.length > 0 && naOpAfstand[naOpAfstand.length - 1].body.auto_update.time === "05:30:00", JSON.stringify(naOpAfstand.map((x) => x.body.reason)));

  // Diagnose downloaden: zonder sleutel
  const diag = await (await fetch(BASE + "/api/diagnostics/config_entry/" + entry.entry_id, { headers: H })).json();
  ok("Diagnose: te downloaden", !!(diag && diag.data && diag.data.automatische_updates), Object.keys((diag && diag.data) || {}).join(","));
  ok("Diagnose: sleutel afgeschermd", !JSON.stringify(diag).includes("testsleutel"));

  // Stoppen bij een branding probleem (en meteen melden aan Btechnics)
  // De open pagina meldt zelf 20 s na het laden "alles ok"; die mag de test niet storen
  await page.goto("about:blank");
  const voor = ontvangen.length;
  const postAt = new Date().toISOString();
  await fetch(BASE + "/api/btechnics_branding/health", { method: "POST", headers: H, body: JSON.stringify({ problems: ["sidebar"] }) });
  const stopped = await call(true);
  ok("Stopt bij probleem met branding", stopped.branding_probleem === true);
  await sleep(14000);
  const melding = ontvangen.slice(voor).find((x) => x.body.branding && x.body.branding.ok === false);
  ok("Status: branding probleem meteen gemeld", !!melding && /branding/.test(melding.body.reason), JSON.stringify(ontvangen.slice(voor).map((x) => [x.body.sent_at, x.body.reason, x.body.branding])) + " post " + postAt);
  // v1.33.1: sleutel leegmaken (de interface stuurt een leeg veld niet mee)
  await setOpts({ ...ALLES, status_url: `http://${GW}:8999/status` }); await sleep(500);
  const leeg = (await (await fetch(BASE + "/api/services/btechnics_branding/send_status?return_response", { method: "POST", headers: H, body: "{}" })).json()).service_response;
  ok("Status: sleutel leegmaken stopt het versturen", leeg && leeg.resultaat.ok === false && /geen sleutel/.test(leeg.resultaat.error), JSON.stringify(leeg && leeg.resultaat));
  srv.close();
  await page.goto(BASE + "/config/dashboard"); await sleep(8000);
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

// ---------------------------------------------------------------- verwijderen: niets achterlaten
{
  const entries = await (await fetch(BASE + "/api/config/config_entries/entry", { headers: H })).json();
  const entry = entries.find((e) => e.domain === "btechnics_branding");
  const cfgDir = process.env.BT_CONFIG_DIR;
  const store = path.join(cfgDir, ".storage/btechnics_branding.auto_update");
  const logoDir = path.join(cfgDir, "btechnics_branding");
  const hadStore = fs.existsSync(store);
  fs.mkdirSync(logoDir, { recursive: true });
  fs.writeFileSync(path.join(logoDir, "customer_logo.png"), fs.readFileSync(path.join(COMP, "app-icon-192.png")));
  const del = await fetch(BASE + "/api/config/config_entries/entry/" + entry.entry_id, { method: "DELETE", headers: H });
  await sleep(6000);
  ok("Verwijderen: integratie weg", del.status === 200, String(del.status));
  ok("Verwijderen: tellingen opgeruimd", hadStore && !fs.existsSync(store), `voor ${hadStore} na ${fs.existsSync(store)}`);
  ok("Verwijderen: klantenlogo opgeruimd", !fs.existsSync(logoDir) || fs.readdirSync(logoDir).length === 0, fs.existsSync(logoDir) ? fs.readdirSync(logoDir).join(",") : "weg");
  const reg = await page.evaluate(() => document.querySelector("home-assistant").hass.callWS({ type: "config/entity_registry/get", entity_id: "update.test_faalt" }));
  ok("Verwijderen: niets meer verborgen", reg.hidden_by !== "integration", String(reg.hidden_by));
}

await browser.close();

// ---------------------------------------------------------------- resultaat
const fails = results.filter((x) => !x.pass);
console.log(`\n${results.length - fails.length}/${results.length} geslaagd`);
if (process.env.GITHUB_STEP_SUMMARY) {
  fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY,
    `### Btechnics IOT tegen HA ${process.env.HA_TAG || ""}\n\n| Test | Resultaat |\n|---|---|\n` +
    results.map((x) => `| ${x.name} | ${x.pass ? "OK" : "**FOUT** " + x.detail} |`).join("\n") + "\n");
}
process.exit(fails.length ? 1 : 0);
