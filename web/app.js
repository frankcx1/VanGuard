/* VanGuard dashboard. Vanilla JS, zero dependencies, fully offline. */
"use strict";

const REFRESH_LATEST_MS = 5_000;
const REFRESH_INSIGHT_MS = 10_000;
const REFRESH_HISTORY_MS = 60_000;
const HISTORY_WINDOW_S = 24 * 3600;

const SPARKS = {
  soc: { source: "shunt", metric: "soc_pct", color: "var(--c-soc)", fmt: v => `${v.toFixed(0)}%` },
  net: { source: "shunt", metric: "power_w", color: "var(--c-net)", fmt: v => `${v.toFixed(0)} W` },
};

const $ = id => document.getElementById(id);
const tooltip = $("tooltip");
const cToF = c => c * 9 / 5 + 32;
const fToC = f => (f - 32) * 5 / 9;

function fmtAge(s) {
  if (s == null) return "–";
  if (s < 90) return `${Math.round(s)}s`;
  if (s < 5400) return `${Math.round(s / 60)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}
function fmtHours(h) {
  if (h == null) return null;
  if (h < 48) return `${h.toFixed(1)} h`;
  return `${(h / 24).toFixed(1)} d`;
}
function get(readings, source, metric) {
  const m = readings?.[source]?.[metric];
  return m ? m.value : null;
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* The model sprinkles Markdown despite instructions; render the safe subset
   (input is already HTML-escaped, so this can't inject anything). */
function mdLite(escaped) {
  return escaped
    .replace(/^#{1,4}\s+(.+)$/gm, "<b>$1</b>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/\*([^*\n]+)\*/g, "<i>$1</i>")
    .replace(/`([^`\n]+)`/g, "<code>$1</code>");
}
async function postJson(url, body) {
  const r = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error((await r.json()).detail ?? r.status);
  return r.json();
}

/* ---- latest readings → tiles ---------------------------------------------- */

let lastReadings = null;
let PRESENTATION = false;   // filming mode: SIM labels hidden (config-flagged)

async function refreshLatest() {
  const data = await (await fetch("/api/telemetry/latest")).json();
  const rd = data.readings, dv = data.derived;
  lastReadings = rd;
  PRESENTATION = data.presentation === true;
  document.body.classList.toggle("presentation", PRESENTATION);

  // Disclosure as a strength: presentation mode swaps the warning badge for
  // the honest flex instead of hiding simulation entirely.
  const simBadge = $("sim-badge");
  if (data.simulated && PRESENTATION) {
    simBadge.textContent = "SIMULATED VAN · REAL LOCAL AI";
    simBadge.className = "badge rail";
    simBadge.classList.remove("hidden");
  } else if (data.simulated) {
    simBadge.textContent = "⚠ SIM DATA";
    simBadge.className = "badge sim";
  } else {
    simBadge.classList.add("hidden");
  }
  $("flow-live").textContent = "LIVE · " + new Date(data.server_ts * 1000)
    .toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) + " ·";
  if (PRESENTATION && $("hvac-note").textContent.includes("phase 2")) {
    $("hvac-note").textContent = "smart climate control";
  }
  $("src-line").textContent = PRESENTATION
    ? "VanGuard · all processing on device"
    : `source: ${data.source_kind}` + (data.simulated ? " · SIMULATED DATA — no van hardware connected" : " · live van data");

  const soc = get(rd, "shunt", "soc_pct");
  $("soc").textContent = soc == null ? "–" : soc.toFixed(0);
  setSocStatus(soc);
  const v = get(rd, "shunt", "voltage_v");
  $("volts").textContent = v == null ? "–" : `${v.toFixed(2)} V`;
  const i = get(rd, "shunt", "current_a");
  $("amps").textContent = i == null ? "–" : `${i > 0 ? "+" : ""}${i.toFixed(1)} A`;
  const bt = get(rd, "shunt", "temp_c");
  $("batt-temp").textContent = bt == null ? "–" : `${cToF(bt).toFixed(0)} °F`;
  const tte = fmtHours(dv?.time_to_empty_h);
  const ttf = fmtHours(dv?.time_to_full_h);
  $("tte-ttf").textContent =
    tte ? `≈ ${tte} to empty at current draw`
    : ttf ? `≈ ${ttf} to full at current charge`
    : "holding steady";

  setFlowPanel(rd, dv);
  setClimateTile(rd);
  setInverterTile(rd);
  setNetworkTile(rd);
  setChassisBlock(rd);
  fillTable(rd, data.server_ts);
  updateDiagSummary(rd, data.server_ts);
}

function setChassisBlock(rd) {
  const ch = rd?.chassis;
  if (!ch) {
    $("chassis-line1").textContent = "no chassis adapter · not monitored";
    $("chassis-line2").textContent = "";
    return;
  }
  const eng = ch.engine_running?.value === 1;
  const spd = ch.speed_mph?.value ?? 0;
  $("chassis-line1").textContent =
    `${eng ? (spd > 2 ? `driving · ${spd.toFixed(0)} mph` : "engine running · parked")
           : "parked · ignition off"} · ${(ch.chassis_v?.value ?? 0).toFixed(2)} V chassis`;
  $("chassis-line2").textContent =
    `fuel ${(ch.fuel_pct?.value ?? 0).toFixed(0)}% · DEF ${(ch.def_pct?.value ?? 0).toFixed(0)}% · ` +
    `coolant ${cToF(ch.coolant_c?.value ?? 0).toFixed(0)}°F · ` +
    `DTC ${(ch.dtc_count?.value ?? 0).toFixed(0)}`;
  if (eng) {
    const gph = ch.fuel_rate_gph?.value ?? 0;
    const mpg = spd > 2 && gph > 0.1 ? spd / gph : null;
    $("chassis-line3").textContent =
      `${(ch.rpm?.value ?? 0).toFixed(0)} rpm · ${(ch.engine_load_pct?.value ?? 0).toFixed(0)}% load · ` +
      `${(ch.boost_psi?.value ?? 0).toFixed(1)} psi boost` +
      (mpg ? ` · ${mpg.toFixed(1)} mpg` : ` · ${gph.toFixed(1)} gph idle`) +
      ` · range ${(ch.range_mi?.value ?? 0).toFixed(0)} mi`;
  } else {
    $("chassis-line3").textContent =
      `range ${(ch.range_mi?.value ?? 0).toFixed(0)} mi at fill-up pace`;
  }
}

/* ---- network -------------------------------------------------------------- */

const NET_MODES = { 0: "off", 1: "cell", 2: "wifi", 3: "starlink" };
const NET_LABELS = { 0: "offline", 1: "5G cellular", 2: "Wi-Fi · local hotspot", 3: "Starlink Mini" };

function setNetworkTile(rd) {
  const net = rd?.network;
  if (!net) return;
  const mode = net.mode?.value ?? 0;
  const modeName = NET_MODES[mode];
  const sig = net.signal_pct?.value ?? 0;
  const sl = rd?.starlink;
  const booting = mode === 3 && sl?.state?.value === 0;

  document.querySelectorAll(".net-tile .seg button").forEach(b => {
    if (b.dataset.pendingUntil && Date.now() < Number(b.dataset.pendingUntil)) return;
    b.classList.toggle("active", b.dataset.net === modeName);
  });

  const bars = Math.min(4, Math.max(0, Math.ceil(sig / 25)));
  $("net-bars").innerHTML = ["▂", "▄", "▆", "█"].map((ch, i) =>
    `<span class="${i < bars ? "lit" : ""}">${ch}</span>`).join("");

  if (mode === 0) {
    $("net-state").textContent = "offline";
    $("net-state").className = "status plain";
    $("net-stats").textContent = "no uplink";
  } else if (booting) {
    $("net-state").textContent = "Starlink · booting…";
    $("net-state").className = "status warn";
    $("net-stats").textContent = "dish acquiring satellites";
  } else {
    $("net-state").textContent = NET_LABELS[mode];
    $("net-state").className = "status good";
    $("net-stats").textContent =
      `${(net.latency_ms?.value ?? 0).toFixed(0)} ms · ` +
      `${(net.down_mbps?.value ?? 0).toFixed(0)}↓ ${(net.up_mbps?.value ?? 0).toFixed(0)}↑ Mbps`;
  }

  if (mode === 3 && sl) {
    const st = { 0: "booting", 1: "online", 2: "⚠ OBSTRUCTED" }[sl.state?.value] ?? "–";
    $("net-dish").textContent =
      `dish ${(sl.power_w?.value ?? 0).toFixed(0)} W off the battery · ` +
      `obstruction ${(sl.obstruction_pct?.value ?? 0).toFixed(0)}% · ${st}`;
  } else {
    $("net-dish").textContent = "uplink is internet only · AI & telemetry stay on device";
  }

  // Rail badge: connectivity truth at a glance.
  const badge = $("net-badge");
  if (mode === 0) {
    badge.textContent = "⛔ OFFLINE";
    badge.className = "badge rail";
  } else if (booting) {
    badge.textContent = "📡 STARLINK · booting";
    badge.className = "badge rail warn";
  } else {
    badge.textContent = { 1: "📶 5G", 2: "🛜 WI-FI", 3: "📡 STARLINK" }[mode] +
      ` · ${(net.down_mbps?.value ?? 0).toFixed(0)} Mbps`;
    badge.className = "badge rail good";
  }
}

document.querySelectorAll(".net-tile .seg button").forEach(btn =>
  btn.addEventListener("click", async () => {
    document.querySelectorAll(".net-tile .seg button").forEach(b => {
      b.classList.toggle("active", b === btn);
      b.dataset.pendingUntil = String(Date.now() + 5000);
    });
    try {
      await postJson("/api/network", { mode: btn.dataset.net });
      refreshAudit();
    } catch (e) { showFlowNote(String(e.message)); }
  }));

function setSocStatus(soc) {
  const el = $("soc-status");
  if (soc == null) { el.textContent = ""; return; }
  if (soc >= 50)      { el.textContent = "✓ OK";        el.className = "status good"; }
  else if (soc >= 30) { el.textContent = "⚠ LOW";       el.className = "status warn"; }
  else if (soc >= 15) { el.textContent = "⚠ VERY LOW";  el.className = "status serious"; }
  else                { el.textContent = "✖ CRITICAL";  el.className = "status critical"; }
}

/* ---- power flow panel ------------------------------------------------------- */

function setFlowPanel(rd, dv) {
  const cs = dv?.charge_source ?? { solar_w: 0, alternator_w: 0, sources: [] };
  const ctl = rd?.charge_ctl;
  const states = {
    solar: ctl?.solar_on?.value === 1,
    alternator: ctl?.alternator_on?.value === 1,
    shore: ctl?.shore_on?.value === 1,
  };
  $("f-solar").textContent = `${cs.solar_w} W`;
  $("f-alt").textContent = `${cs.alternator_w} W`;
  $("f-shore").textContent = states.shore ? "on · inferred" : "off";
  document.querySelectorAll(".flow-node.src[data-src]").forEach(b => {
    b.classList.toggle("on", states[b.dataset.src]);
    b.dataset.on = states[b.dataset.src] ? "1" : "0";
    b.setAttribute("aria-pressed", states[b.dataset.src] ? "true" : "false");
  });

  const net = dv?.net_power_w;
  const fb = $("f-net");
  fb.textContent = net == null ? "–" : `${net > 0 ? "+" : ""}${net.toFixed(0)} W`;
  fb.classList.toggle("charging", (net ?? 0) > 5);
  $("f-net-label").textContent =
    net == null ? "battery" : net > 5 ? "▲ into battery" : net < -5 ? "▼ from battery" : "battery · idle";

  const invDc = get(rd, "inverter", "dc_in_w") ?? 0;
  const invAc = get(rd, "inverter", "ac_out_w") ?? 0;
  const invState = get(rd, "inverter", "state");
  const load = dv?.load_w;
  const house = load == null ? null : Math.max(0, load - invDc);
  $("f-house").textContent = load == null ? "n/a on shore" : `${house.toFixed(0)} W`;
  $("f-ac").textContent = `${invAc.toFixed(0)} W`;
  $("f-inv-state").textContent =
    ({ 0: "off", 1: "idle", 2: "inverting", 3: "BYPASS" })[invState] ?? "–";
  setToggle($("inverter-btn"), invState !== 0);

  const inW = cs.solar_w + cs.alternator_w;
  $("arrow-in").classList.toggle("active", inW > 10 || states.shore);
  $("arrow-out").classList.toggle("active", (load ?? 0) > 5);
  if (!flowNote && load != null && net != null) {
    $("flow-recon").textContent =
      `${inW} W in − ${load.toFixed(0)} W out ≈ ${net > 0 ? "+" : ""}${net.toFixed(0)} W battery`;
  } else if (!flowNote) {
    $("flow-recon").textContent = states.shore ? "shore charging · load underivable" : "";
  }

  const sw = rd?.switches;
  const cook = invAc > 1200;
  $("f-cook").textContent = cook ? "1500 W" : "off";
  setToggle($("cooktop-btn"), cook);
  if (sw) {
    const fOn = sw.fridge_on?.value === 1, zOn = sw.freezer_on?.value === 1;
    $("f-fridge").textContent = fOn ? `${(sw.fridge_w?.value ?? 0).toFixed(0)} W` : "off";
    $("f-freezer").textContent = zOn ? `${(sw.freezer_w?.value ?? 0).toFixed(0)} W` : "off";
    setToggle($("fridge-btn"), fOn);
    setToggle($("freezer-btn"), zOn);
  }
  const acOn = rd?.hvac?.mode?.value === 2;
  $("f-acu").textContent = acOn
    ? `${(rd.hvac.hvac_power_w?.value ?? 0).toFixed(0)} W` : "off";
  setToggle($("acu-btn"), acOn);

  // Battery-only runtime readout: reacts live as loads are toggled.
  const soc = get(rd, "shunt", "soc_pct");
  const tte = dv?.time_to_empty_h, ttf = dv?.time_to_full_h;
  const rt = $("f-runtime");
  if (net != null && net < -25 && tte != null && soc != null) {
    const toReserve = soc > 20 ? tte * (soc - 20) / soc : 0;
    rt.textContent = `≈ ${toReserve.toFixed(1)}h to reserve · ${tte.toFixed(1)}h to empty`;
  } else if (net != null && net > 5 && ttf != null) {
    rt.textContent = `≈ ${ttf.toFixed(1)}h to full`;
  } else {
    rt.textContent = "";
  }
}

function setToggle(btn, on) {
  if (btn.dataset.pendingUntil && Date.now() < Number(btn.dataset.pendingUntil)) {
    return;   // optimistic state holds until the next poll confirms it
  }
  btn.classList.toggle("on", on);
  btn.dataset.on = on ? "1" : "0";
  btn.setAttribute("aria-pressed", on ? "true" : "false");
}

/* Optimistic toggling: flip the button now, let telemetry confirm within a
   couple of polls. */
let flowNote = null;

function optimistic(btn, on) {
  btn.classList.toggle("on", on);
  btn.dataset.on = on ? "1" : "0";
  btn.setAttribute("aria-pressed", on ? "true" : "false");
  btn.dataset.pendingUntil = String(Date.now() + 5000);
  setTimeout(refreshLatest, 2500);
  setTimeout(refreshLatest, 5200);
}

function showFlowNote(text, ms = 6000) {
  flowNote = text;
  $("flow-recon").textContent = text;
  setTimeout(() => { flowNote = null; }, ms);
}

document.querySelectorAll(".flow-node.src[data-src]").forEach(btn =>
  btn.addEventListener("click", async () => {
    const enabled = btn.dataset.on !== "1";
    optimistic(btn, enabled);
    try {
      await postJson("/api/charge_source", { source: btn.dataset.src, enabled });
      refreshAudit();
    } catch (e) { showFlowNote(String(e.message)); }
  }));

$("cooktop-btn").addEventListener("click", async () => {
  const on = $("cooktop-btn").dataset.on !== "1";
  optimistic($("cooktop-btn"), on);
  if (on && $("inverter-btn").dataset.on !== "1") {
    // 12V-only van until the inverter runs — the sim switches it on for us.
    optimistic($("inverter-btn"), true);
    showFlowNote("inverter was off — switching it on so the cooktop has 110V");
  }
  try {
    await postJson("/api/appliance", { name: "cooktop", on });
    refreshAudit();
  } catch (e) { showFlowNote(String(e.message)); }
});

$("inverter-btn").addEventListener("click", async () => {
  const on = $("inverter-btn").dataset.on !== "1";
  optimistic($("inverter-btn"), on);
  if (!on && $("cooktop-btn").dataset.on === "1") {
    optimistic($("cooktop-btn"), false);
    showFlowNote("inverter off — the cooktop lost 110V");
  }
  try {
    await postJson("/api/inverter", { on });
    refreshAudit();
  } catch (e) { showFlowNote(String(e.message)); }
});

$("acu-btn").addEventListener("click", async () => {
  const on = $("acu-btn").dataset.on !== "1";
  optimistic($("acu-btn"), on);
  try {
    await postJson("/api/hvac", { mode: on ? "cool" : "off" });
    refreshAudit();
  } catch (e) { showFlowNote(String(e.message)); }
});

for (const name of ["fridge", "freezer"]) {
  $(`${name}-btn`).addEventListener("click", async () => {
    const btn = $(`${name}-btn`);
    const on = btn.dataset.on !== "1";
    optimistic(btn, on);
    try {
      await postJson("/api/load_switch", { name, on });
      refreshAudit();
    } catch (e) { showFlowNote(String(e.message)); }
  });
}

/* ---- climate ---------------------------------------------------------------- */

function setClimateTile(rd) {
  const hv = rd?.hvac;
  if (!hv) return;
  $("cabin-temp").textContent =
    hv.cabin_temp_c ? cToF(hv.cabin_temp_c.value).toFixed(1) : "–";
  const mode = { 0: "off", 1: "heat", 2: "cool" }[hv.mode?.value] ?? "off";
  const running = (hv.hvac_power_w?.value ?? 0) > 1;
  $("hvac-state").textContent = mode === "off" ? "" :
    `${mode} → ${cToF(hv.setpoint_c?.value).toFixed(0)}°F${running ? " · running" : " · idle"}`;
  document.querySelectorAll(".seg button").forEach(b =>
    b.classList.toggle("active", b.dataset.mode === mode));
}

document.querySelectorAll(".seg button").forEach(btn =>
  btn.addEventListener("click", () => sendHvac({ mode: btn.dataset.mode })));
$("setpoint").addEventListener("change", () =>
  sendHvac({ setpoint_c: Math.round(fToC(parseFloat($("setpoint").value)) * 2) / 2 }));

async function sendHvac(cmd) {
  try {
    await postJson("/api/hvac", cmd);
    $("hvac-note").textContent = PRESENTATION
      ? "command sent" : "command queued · applies within one poll · SIMULATED";
    refreshAudit();
  } catch (e) { $("hvac-note").textContent = String(e.message); }
}

/* ---- inverter ----------------------------------------------------------------- */

const INV_STATES = {
  0: ["off", "status plain"],
  1: ["idle", "status plain"],
  2: ["⚡ inverting", "status good"],
  3: ["🔌 BYPASS · shore power", "status warn"],
};

function setInverterTile(rd) {
  // The standalone inverter tile was folded into Power Flow (P8); keep this
  // guard so nothing breaks if the elements are absent.
  if (!$("inv-ac")) return;
}

/* ---- insight + outlook ---------------------------------------------------------- */

let currentInsight = null;
let dismissedSummary = null;

async function refreshInsight() {
  const data = await (await fetch("/api/insight")).json();
  const ins = data.insight, ol = data.outlook;
  currentInsight = ins;

  if (dismissedSummary !== ins.summary) {
    $("insight-summary").textContent = ins.summary;
    const reco = $("insight-reco");
    reco.classList.toggle("hidden", !ins.recommendation);
    reco.textContent = ins.recommendation ?? "";
    $("insight-quality").innerHTML = (ins.data_quality ?? [])
      .map(q => `◆ ${escapeHtml(q)}`).join("<br>");
    const act = $("ins-action");
    if (ins.proposed_action) {
      act.textContent = PRESENTATION
        ? ins.proposed_action.label.replace(/^Simulate\s+/i, "")
            .replace(/^./, c => c.toUpperCase())
        : ins.proposed_action.label;
      act.classList.remove("hidden");
    } else {
      act.classList.add("hidden");
    }
  }

  const list = $("outlook-list");
  if (!ol.available) {
    list.innerHTML = `<dt>forecast</dt><dd>${escapeHtml(ol.reason ?? "unavailable")}</dd>`;
    $("ol-conf").textContent = "";
    return;
  }
  const rows = [];
  const row = (k, v, cls = "") => rows.push(`<dt>${k}</dt><dd class="${cls}">${v}</dd>`);
  if (ol.runtime_to_reserve_h != null)
    row("to reserve at current draw", `${ol.runtime_to_reserve_h} h`);
  row("SOC at sunrise", `${ol.soc_at_sunrise_pct}%`,
      ol.reserve_ok_overnight ? "good" : "bad");
  row("hours to sunrise", `${ol.hours_to_sunrise} h`);
  row("solar left today (est.)", `${ol.remaining_solar_wh} Wh`);
  row("discretionary energy", `${ol.discretionary_wh} Wh`);
  if (ol.solar_surplus_w != null)
    row("solar surplus now", `${ol.solar_surplus_w} W`, ol.solar_surplus_w >= 0 ? "good" : "");
  list.innerHTML = rows.join("");
  const conf = $("ol-conf");
  conf.textContent = `${ol.confidence} confidence` + (PRESENTATION ? "" : " · simulated");
  conf.className = "status " + ({ high: "good", medium: "plain", low: "serious" }[ol.confidence] ?? "plain");
  const a = ol.assumptions;
  $("ol-assumptions").textContent =
    `capacity ${a.capacity_wh} Wh · reserve ${a.reserve_pct}% · ` +
    `load basis ${a.load_basis_w} W · ${a.note} · ${a.solar_model}`;
}

$("ins-dismiss").addEventListener("click", () => {
  dismissedSummary = currentInsight?.summary;
  $("insight-summary").textContent = "Dismissed until conditions change.";
  $("insight-reco").classList.add("hidden");
  $("insight-quality").innerHTML = "";
  $("ins-action").classList.add("hidden");
});
$("ins-explain").addEventListener("click", () => {
  if (currentInsight) sendChat("Explain this and your recommendation: " + currentInsight.summary);
});
$("ins-changed").addEventListener("click", () => sendChat("What changed in the last hour?"));
$("ins-speak").addEventListener("click", () => {
  if (!currentInsight) return;
  const text = currentInsight.summary +
    (currentInsight.recommendation ? " " + currentInsight.recommendation : "");
  if ("speechSynthesis" in window) {
    speechSynthesis.cancel();
    speechSynthesis.speak(new SpeechSynthesisUtterance(text));
  }
});
$("ins-action").addEventListener("click", async () => {
  const act = currentInsight?.proposed_action;
  if (!act) return;
  const promptText = PRESENTATION
    ? `${act.label.replace(/^Simulate\s+/i, "")}?`
    : `${act.label}? (SIMULATED - no real hardware is touched)`;
  if (!window.confirm(promptText)) return;
  const cmd = act.command;
  try {
    if (cmd.target === "hvac") await postJson("/api/hvac",
      { mode: cmd.mode, setpoint_c: cmd.setpoint_c });
    refreshAudit();
  } catch (e) { $("insight-quality").textContent = String(e.message); }
});

/* ---- status rail ----------------------------------------------------------------- */

async function refreshStatus() {
  const s = await (await fetch("/api/status")).json();
  const chip = $("stale-chip");
  chip.classList.toggle("hidden", !s.stale);
  if (s.stale) chip.textContent = `⚠ STALE ${fmtAge(s.staleness_s)}`;
  $("clock").textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (s.mode && $("mode-sel").value !== s.mode) $("mode-sel").value = s.mode;
}

async function refreshRuntime() {
  const r = await (await fetch("/api/runtime")).json();
  const badge = $("ai-badge");
  if (r.loaded) {
    badge.textContent = `LOCAL AI: ${r.device_confirmed} · ${r.model_short}`;
    badge.className = "badge rail good";
    // The single most differentiated architectural point, said plainly:
    $("insight-prov").textContent =
      `verdict: deterministic rules · explanation: ${r.model_short} (${r.device_confirmed})`;
  } else if (r.model_exported) {
    badge.textContent = `LOCAL AI: READY · ${r.model_short}`;
    badge.className = "badge rail";
  } else {
    badge.textContent = "DETERMINISTIC MODE — NO MODEL";
    badge.className = "badge rail warn";
  }
  const lg = r.last_generation;
  $("runtime-detail").innerHTML = [
    `model: <b>${escapeHtml(r.model_label)}</b> (<code>${escapeHtml(r.model_dir)}</code>) · exported: <b>${r.model_exported}</b>`,
    `runtime: OpenVINO GenAI · endpoint: <b>${escapeHtml(r.endpoint)}</b>`,
    `device requested: <b>${escapeHtml((r.device_requested ?? []).join(" → "))}</b>`,
    `device confirmed: <b>${r.device_confirmed ?? "not loaded yet"}</b>` +
      (r.load_s ? ` · load/compile <b>${r.load_s.toFixed(1)}s</b>` : ""),
    lg ? `last generation: <b>${lg.device}</b> · <b>${lg.tokens_per_s}</b> tok/s · TTFT <b>${lg.ttft_ms}ms</b>`
       : "last generation: none this session",
    `speech-to-text: <b>${r.stt_loaded ? "Whisper on " + r.stt_device : "loads on first use"}</b>`,
  ].map(l => `<div>${l}</div>`).join("");
  $("diag-runtime").textContent = r.loaded
    ? `AI on ${r.device_confirmed} (measured)` : (r.model_exported
      ? "AI ready · not loaded yet" : "deterministic mode");
}

/* ---- guardian --------------------------------------------------------------- */

const G_STAGES = ["detected", "verified", "decided", "acted", "confirmed"];

// Plain-language meaning of each autonomy level, shown with the selector.
const G_LEVELS = {
  observe:   "watches and logs only — never recommends, never acts",
  advise:    "explains risks and recommends actions — you do everything",
  ask:       "prepares the fix and waits for your approval",
  protect:   "fixes preauthorized, reversible things on its own; asks for the rest",
  emergency: "protect + immediate electrical interlocks (e.g. cooktop cutoff)",
};

async function refreshGuardian() {
  const g = await (await fetch("/api/guardian")).json();
  if ($("g-level-sel").value !== g.level) $("g-level-sel").value = g.level;
  const armed = $("g-armed");
  armed.textContent = g.armed
    ? `ARMED · ${g.mode.toUpperCase()} POLICY`
    : (g.level === "observe" ? "OBSERVING ONLY" : "STANDBY");
  armed.className = g.armed ? "status good" : "status plain";

  const active = g.active;
  const tl = $("g-timeline");
  const body = $("g-body");
  const approveRow = $("g-approve-row");
  approveRow.classList.toggle("hidden", !(active && active.stage === "proposed"));

  if (active && active.stage !== "confirmed") {
    const stageIdx = active.stage === "proposed" ? 2 : G_STAGES.indexOf(active.stage);
    tl.classList.remove("hidden");
    tl.innerHTML = G_STAGES.map((s, i) => {
      const cls = i < stageIdx ? "done" : i === stageIdx ? "now" : "";
      const label = (s === "decided" && active.stage === "proposed") ? "PROPOSED" : s.toUpperCase();
      return `<span class="g-step ${cls}">${label}</span>`;
    }).join(`<span class="g-arrow">→</span>`);
  } else {
    tl.classList.add("hidden");
  }

  const ev = (g.events ?? [])[0];
  if (active && ev) {
    body.innerHTML = `<b>${escapeHtml(ev.title)}</b> — ${escapeHtml(ev.detail)}`;
    body.title = `${ev.title} — ${ev.detail}`;
  } else if (ev && (Date.now() / 1000 - ev.ts) < 3600) {
    const t = new Date(ev.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    body.innerHTML = `<b>${ev.stage.toUpperCase()} ${t}</b> · ${escapeHtml(ev.title)} — ${escapeHtml(ev.detail)}`;
    body.title = `${ev.title} — ${ev.detail}`;
  } else {
    body.innerHTML = "Current risk: <b>none</b> · watching reserve forecast, " +
      "voltage sag, charging path, and sensor health";
    body.title = "";
  }
  $("g-policy").innerHTML =
    `<div title="${escapeHtml(G_LEVELS[g.level] ?? "")}"><b>${escapeHtml(g.level)}</b>: ${escapeHtml(G_LEVELS[g.level] ?? "")}</div>` +
    `<div title="can do alone: ${escapeHtml(g.allowed_auto.join(" · "))}">can do alone: ${escapeHtml(g.allowed_auto.join(" · "))}</div>` +
    `<div title="asks first: ${escapeHtml(g.requires_approval.join(" · "))} | never: ${escapeHtml((g.never ?? []).join(" · "))}">` +
    `asks first: ${escapeHtml(g.requires_approval.join(" · "))} · never: ${escapeHtml((g.never ?? []).slice(0, 2).join(" · "))}</div>`;
  const sel = $("g-level-sel");
  sel.title = Object.entries(G_LEVELS)
    .map(([k, v]) => `${k}: ${v}`).join("\n");
  Array.from(sel.options).forEach(o => { o.title = G_LEVELS[o.value] ?? ""; });
}

$("g-level-sel").addEventListener("change", async () => {
  try {
    await postJson("/api/guardian/level", { level: $("g-level-sel").value });
    refreshGuardian(); refreshAudit();
  } catch (e) { console.warn(e); }
});
$("g-approve").addEventListener("click", async () => {
  try { await postJson("/api/guardian/approve", {}); refreshGuardian(); refreshAudit(); }
  catch (e) { console.warn(e); }
});
$("g-dismiss").addEventListener("click", async () => {
  try { await postJson("/api/guardian/dismiss", {}); refreshGuardian(); }
  catch (e) { console.warn(e); }
});

/* ---- watchdog --------------------------------------------------------------- */

const WD_SEV = { nominal: "info", attention: "advisory", warning: "warning",
                 critical: "critical" };

async function refreshWatchdog() {
  const w = await (await fetch("/api/watchdog")).json();
  if (!w.last) {
    $("wd-meta").textContent =
      `watchdog armed · first check shortly · every ${w.interval_min} min`;
    return;
  }
  const t = new Date(w.last.ts * 1000).toLocaleTimeString(
    [], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  $("wd-status").textContent = w.last.status.toUpperCase();
  $("wd-status").className = `sev ${WD_SEV[w.last.status] ?? "info"}`;
  $("wd-meta").textContent =
    `last check ${t} · every ${w.interval_min} min · ${w.count_today} today · ${w.last.source}`;
  $("wd-summary").textContent = w.last.summary;
}

$("wd-run").addEventListener("click", async () => {
  $("wd-meta").textContent = "patrolling…";
  try {
    await postJson("/api/watchdog/run", {});
    await refreshWatchdog();
    refreshAudit();
  } catch (e) { $("wd-meta").textContent = String(e.message); }
});

$("mode-sel").addEventListener("change", async () => {
  try {
    const r = await postJson("/api/mode", { mode: $("mode-sel").value });
    $("diag-summary").title = r.policy.note;
    refreshInsight(); refreshAlerts(); refreshAudit();
  } catch (e) { console.warn(e); }
});

/* ---- alerts ------------------------------------------------------------------------ */

async function refreshAlerts() {
  const { alerts } = await (await fetch("/api/alerts")).json();
  const banner = $("alert-banner");
  const urgent = (alerts ?? []).filter(a => ["critical", "warning"].includes(a.severity));
  if (urgent.length === 0) { banner.className = "hidden"; }
  else {
    const worst = urgent.some(a => a.severity === "critical") ? "critical" : "warning";
    banner.className = worst;
    banner.textContent = (worst === "critical" ? "✖ " : "⚠ ") +
      urgent.map(a => a.message).join("  ·  ");
  }
  const list = $("alert-list");
  if (!alerts || alerts.length === 0) {
    list.innerHTML = `<li><span class="sev info">normal</span>no active alerts · all sensor timestamps fresh</li>`;
  } else {
    list.innerHTML = alerts.map(a =>
      `<li><span class="sev ${a.severity}">${a.severity}</span>${escapeHtml(a.message)}</li>`).join("");
  }
  $("alert-count").textContent = alerts?.length ? `${alerts.length} active` : "clear";
}

/* ---- trip -------------------------------------------------------------------------- */

async function refreshTrip() {
  const t = await (await fetch("/api/trip")).json();
  if (!t.fix) { $("trip-pos").textContent = "no GPS fix"; return; }
  $("trip-mi").textContent = t.miles_today.toFixed(1);
  $("trip-state").textContent = t.fix.moving
    ? `moving · ${t.fix.speed_mph.toFixed(0)} mph` : "parked";
  const db = $("drive-btn");
  if (!(db.dataset.pendingUntil && Date.now() < Number(db.dataset.pendingUntil))) {
    db.textContent = t.fix.moving ? "⏸ Park" : "▶ Drive";
    db.classList.toggle("on", t.fix.moving);
    db.dataset.on = t.fix.moving ? "1" : "0";
    db.setAttribute("aria-pressed", t.fix.moving ? "true" : "false");
  }
  $("trip-pos").textContent = `${t.fix.lat.toFixed(4)}, ${t.fix.lon.toFixed(4)}`;
  $("poi-list").innerHTML = (t.nearby ?? []).slice(0, 3).map(p =>
    `<li>${escapeHtml(p.name)} <span class="dist">· ${p.type} · ${p.dist_mi} mi</span></li>`
  ).join("");
}

$("drive-btn").addEventListener("click", async () => {
  const on = $("drive-btn").dataset.on !== "1";
  const db = $("drive-btn");
  db.textContent = on ? "⏸ Park" : "▶ Drive";
  db.classList.toggle("on", on);
  db.dataset.on = on ? "1" : "0";
  db.dataset.pendingUntil = String(Date.now() + 6000);
  try {
    await postJson("/api/drive", { on });
    if (!on) {
      // Park = take reset: guardian cooldowns/episode cleared, autonomy
      // re-armed to Protect, so the next Drive plays identically.
      await postJson("/api/guardian/reset", {});
      refreshGuardian();
    }
    refreshAudit();
    setTimeout(refreshTrip, 2500);
  } catch (e) { $("trip-pos").textContent = String(e.message); }
});

/* ---- diagnostics ---------------------------------------------------------------------- */

let auditCount = 0;

function updateDiagSummary(rd, serverTs) {
  let n = 0, stale = 0;
  for (const per of Object.values(rd ?? {})) {
    for (const { ts } of Object.values(per)) {
      n += 1;
      if (serverTs - ts > 45) stale += 1;
    }
  }
  $("diag-summary").textContent =
    `${n} readings · ${stale === 0 ? "all fresh" : `${stale} stale`} · ` +
    `${auditCount} local tool calls · 0 external calls (no cloud endpoints exist)`;
}

function ageClass(age) {
  if (age < 15) return "val-ok";
  if (age < 45) return "val-warn";
  return "val-bad";
}

function fillTable(rd, serverTs) {
  const tbody = $("readings-table").querySelector("tbody");
  const rows = [];
  for (const source of Object.keys(rd ?? {}).sort()) {
    for (const metric of Object.keys(rd[source]).sort()) {
      const { ts, value } = rd[source][metric];
      const age = serverTs - ts;
      rows.push(
        `<tr><td class="dev" data-source="${source}" data-age="${age}" ` +
        `title="click to toggle this sensor offline (sim)">${source}</td>` +
        `<td>${metric}</td>` +
        `<td class="num ${ageClass(age)}">${Number(value.toFixed(3))}</td>` +
        `<td>${fmtAge(age)}</td></tr>`);
    }
  }
  tbody.innerHTML = rows.join("");
  tbody.querySelectorAll("td.dev").forEach(td =>
    td.addEventListener("click", () => {
      if (!["shunt", "dcc50s", "hvac", "gps", "inverter", "chassis"].includes(td.dataset.source)) return;
      const offline = Number(td.dataset.age) > 45;
      postJson("/api/sensor", { source: td.dataset.source, offline: !offline })
        .then(refreshAudit).catch(() => {});
    }));
}

async function refreshAudit() {
  const { entries } = await (await fetch("/api/audit?limit=40")).json();
  auditCount = entries?.length ?? 0;
  const tbody = $("audit-table").querySelector("tbody");
  tbody.innerHTML = (entries ?? []).map(e =>
    `<tr><td>${new Date(e.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</td>` +
    `<td>${escapeHtml(e.tool)}</td>` +
    `<td><code>${escapeHtml(e.args)}</code></td>` +
    `<td>${escapeHtml(e.device ?? "–")}</td>` +
    `<td class="num">${e.duration_ms}</td></tr>`).join("");
}

$("diag-open").addEventListener("click", () => {
  $("drawer").classList.remove("hidden");
  refreshRuntime(); refreshAudit();
});
$("drawer-close").addEventListener("click", () => $("drawer").classList.add("hidden"));
document.addEventListener("keydown", ev => {
  if (ev.key === "Escape") $("drawer").classList.add("hidden");
});

/* ---- chat -------------------------------------------------------------------------- */

const chatHistory = [];

async function sendChat(question) {
  const log = $("chat-log"), input = $("chat-input"), btn = $("chat-send");
  log.insertAdjacentHTML("afterbegin",
    `<div class="msg user">${escapeHtml(question)}</div>`);
  const pending = document.createElement("div");
  pending.className = "msg assistant pending";
  pending.textContent = "thinking… (first question loads the model)";
  log.prepend(pending);
  input.value = ""; btn.disabled = true;

  chatHistory.push({ role: "user", content: question });
  while (chatHistory.length > 8) chatHistory.shift();
  try {
    const data = await postJson("/v1/chat/completions", { messages: chatHistory });
    const answer = data.choices[0].message.content;
    chatHistory.push({ role: "assistant", content: answer });
    const vg = data.vanguard ?? {};
    const evidence = (vg.tool_calls ?? []).filter(t => !t.auto);
    pending.classList.remove("pending");
    pending.innerHTML = mdLite(escapeHtml(answer)) +
      `<span class="meta">${escapeHtml(vg.provenance ?? "")}` +
      (vg.tokens_per_s ? ` · ${vg.tokens_per_s} tok/s` : "") +
      (vg.simulated && !PRESENTATION ? " · SIM data" : "") + `</span>` +
      (evidence.length ? `<details class="evidence"><summary>evidence used (${evidence.length} tool call${evidence.length > 1 ? "s" : ""})</summary>` +
        evidence.map(t =>
          `<code>${escapeHtml(t.tool)}(${escapeHtml(JSON.stringify(t.args))}) → ` +
          `${escapeHtml(JSON.stringify(t.result))}</code>`).join("") +
        `</details>` : "");
    refreshAudit();
  } catch (e) {
    pending.classList.remove("pending");
    pending.innerHTML = `<em>error: ${escapeHtml(String(e.message))}</em>`;
    chatHistory.pop();
  } finally {
    btn.disabled = false;
  }
}

$("chat-form").addEventListener("submit", ev => {
  ev.preventDefault();
  const q = $("chat-input").value.trim();
  if (q && !$("chat-send").disabled) sendChat(q);
});
document.querySelectorAll("#chat-chips button").forEach(b =>
  b.addEventListener("click", () => { if (!$("chat-send").disabled) sendChat(b.dataset.q); }));

/* ---- voice: raw 16kHz PCM → WAV → offline Whisper -------------------------- */

const rec = { ctx: null, stream: null, node: null, chunks: [], active: false };

async function startRecording() {
  rec.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  rec.ctx = new AudioContext({ sampleRate: 16000 });
  const src = rec.ctx.createMediaStreamSource(rec.stream);
  rec.node = rec.ctx.createScriptProcessor(4096, 1, 1);
  rec.chunks = [];
  rec.node.onaudioprocess = e => {
    if (rec.active) rec.chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  };
  src.connect(rec.node);
  rec.node.connect(rec.ctx.destination);
  rec.active = true;
  $("chat-mic").classList.add("recording");
  $("mic-badge").textContent = "🎤 LISTENING";
}

async function stopRecording() {
  rec.active = false;
  $("chat-mic").classList.remove("recording");
  $("mic-badge").textContent = "🎤 MIC READY";
  rec.node?.disconnect();
  rec.stream?.getTracks().forEach(t => t.stop());
  const rate = rec.ctx.sampleRate;
  await rec.ctx.close();
  const n = rec.chunks.reduce((s, c) => s + c.length, 0);
  if (n < rate / 4) return;
  const pcm = new Float32Array(n);
  let off = 0;
  for (const c of rec.chunks) { pcm.set(c, off); off += c.length; }
  const wav = encodeWav(rate === 16000 ? pcm : resampleTo16k(pcm, rate));
  const input = $("chat-input");
  input.placeholder = "transcribing…";
  try {
    const r = await fetch("/api/transcribe", { method: "POST", body: wav });
    if (!r.ok) throw new Error((await r.json()).detail ?? r.status);
    const { text } = await r.json();
    if (text) sendChat(text);
    else input.placeholder = "didn't catch that — try again";
  } catch (e) {
    input.placeholder = `voice error: ${e.message}`;
  } finally {
    setTimeout(() => { input.placeholder = "Ask about power, climate, or the trip…"; }, 4000);
  }
}

function resampleTo16k(pcm, fromRate) {
  const ratio = fromRate / 16000;
  const out = new Float32Array(Math.floor(pcm.length / ratio));
  for (let i = 0; i < out.length; i++) out[i] = pcm[Math.floor(i * ratio)];
  return out;
}

function encodeWav(pcm) {
  const buf = new ArrayBuffer(44 + pcm.length * 2);
  const v = new DataView(buf);
  const w = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  w(0, "RIFF"); v.setUint32(4, 36 + pcm.length * 2, true); w(8, "WAVE");
  w(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true);
  v.setUint16(22, 1, true); v.setUint32(24, 16000, true);
  v.setUint32(28, 32000, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  w(36, "data"); v.setUint32(40, pcm.length * 2, true);
  for (let i = 0; i < pcm.length; i++) {
    v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, pcm[i])) * 32767, true);
  }
  return new Blob([buf], { type: "audio/wav" });
}

const micBtn = $("chat-mic");
micBtn.addEventListener("mousedown", () => startRecording().catch(e => {
  $("chat-input").placeholder = `mic error: ${e.message}`;
  $("mic-badge").textContent = "🎤 MIC UNAVAILABLE";
}));
micBtn.addEventListener("mouseup", () => { if (rec.active) stopRecording(); });
micBtn.addEventListener("mouseleave", () => { if (rec.active) stopRecording(); });

/* ---- sparklines ---------------------------------------------------------------------- */

async function refreshSparks() {
  await Promise.all(Object.entries(SPARKS).map(async ([key, spec]) => {
    const q = new URLSearchParams({
      source: spec.source, metric: spec.metric,
      window_s: HISTORY_WINDOW_S, max_points: 300,
    });
    const r = await fetch(`/api/telemetry/history?${q}`);
    const { points } = await r.json();
    drawSpark(document.querySelector(`[data-spark="${key}"]`), points, spec);
  }));
}

function drawSpark(host, points, spec) {
  if (!host) return;
  host.innerHTML = "";
  if (!points || points.length < 2) {
    host.innerHTML = `<span class="minmax">no history yet</span>`;
    return;
  }
  const W = 600, H = 40, PAD = 3;
  const ts = points.map(p => p[0]), vs = points.map(p => p[1]);
  const t0 = ts[0], t1 = ts[ts.length - 1];
  let lo = Math.min(...vs), hi = Math.max(...vs);
  if (hi - lo < 1e-9) { hi += 0.5; lo -= 0.5; }
  const x = t => PAD + (W - 2 * PAD) * (t - t0) / Math.max(1, t1 - t0);
  const y = v => PAD + (H - 2 * PAD) * (1 - (v - lo) / (hi - lo));

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "none");
  const zeroY = y(Math.max(lo, Math.min(hi, 0)));
  if (lo < 0 && hi > 0) svg.appendChild(line(PAD, zeroY, W - PAD, zeroY, "var(--baseline)", 1));
  const poly = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  poly.setAttribute("points", points.map(p => `${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(" "));
  poly.setAttribute("fill", "none");
  poly.setAttribute("stroke", spec.color);
  poly.setAttribute("stroke-width", "2");
  poly.setAttribute("vector-effect", "non-scaling-stroke");
  svg.appendChild(poly);
  const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  dot.setAttribute("cx", x(t1)); dot.setAttribute("cy", y(vs[vs.length - 1]));
  dot.setAttribute("r", "3.5"); dot.setAttribute("fill", spec.color);
  svg.appendChild(dot);

  const cross = line(0, 0, 0, H, "var(--muted)", 1);
  cross.style.display = "none";
  svg.appendChild(cross);
  const hover = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  hover.setAttribute("r", "4"); hover.setAttribute("fill", spec.color);
  hover.setAttribute("stroke", "var(--surface)"); hover.setAttribute("stroke-width", "2");
  hover.style.display = "none";
  svg.appendChild(hover);

  svg.addEventListener("mousemove", ev => {
    const rect = svg.getBoundingClientRect();
    const tx = t0 + (ev.clientX - rect.left) / rect.width * (t1 - t0);
    let best = 0;
    for (let k = 1; k < ts.length; k++) if (Math.abs(ts[k] - tx) < Math.abs(ts[best] - tx)) best = k;
    const px = x(ts[best]), py = y(vs[best]);
    cross.setAttribute("x1", px); cross.setAttribute("x2", px);
    cross.style.display = "";
    hover.setAttribute("cx", px); hover.setAttribute("cy", py);
    hover.style.display = "";
    tooltip.textContent =
      `${new Date(ts[best] * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · ${spec.fmt(vs[best])}`;
    tooltip.classList.remove("hidden");
    tooltip.style.left = `${ev.clientX + 12}px`;
    tooltip.style.top = `${ev.clientY - 30}px`;
  });
  svg.addEventListener("mouseleave", () => {
    cross.style.display = "none";
    hover.style.display = "none";
    tooltip.classList.add("hidden");
  });

  const label = document.createElement("span");
  label.className = "minmax";
  label.textContent = `${spec.fmt(lo)} – ${spec.fmt(hi)}`;
  host.appendChild(svg);
  host.appendChild(label);
}

function line(x1, y1, x2, y2, stroke, w) {
  const l = document.createElementNS("http://www.w3.org/2000/svg", "line");
  l.setAttribute("x1", x1); l.setAttribute("y1", y1);
  l.setAttribute("x2", x2); l.setAttribute("y2", y2);
  l.setAttribute("stroke", stroke); l.setAttribute("stroke-width", w);
  l.setAttribute("vector-effect", "non-scaling-stroke");
  return l;
}

/* ---- demo story mode --------------------------------------------------------
   Drives the LIVE dashboard — real requests, real state changes, all audited.
   Manual pacing (Next/Back) so the presenter controls the take. */

const STORY = [
  { caption: "This is VanGuard: a camper van's entire nervous system, watched by an AI that lives on this tablet. Look at the rail — the model, the NPU, and the promise: data stays on device.",
    target: "header" },
  { caption: "The heart: a 300Ah lithium battery, modeled to the coulomb. State of charge, voltage, current — and live runtime math underneath.",
    target: ".hero" },
  { caption: "Every watt has to reconcile: solar and alternator in, loads out, the battery absorbing the difference. These switches are live — this is a working model, not a picture.",
    target: ".flow-tile" },
  { caption: "Comfort and connectivity in one place — including a roof-mounted Starlink whose power draw the battery model actually feels.",
    target: ".tile:has(#cabin-temp)" },
  { caption: "Here telemetry becomes understanding. The verdict is deterministic rules; the words are the local model's. It patrols on a schedule and signs every report.",
    target: ".insight-tile" },
  { caption: "It doesn't just measure — it forecasts: battery at sunrise, energy to spare tonight, with every assumption disclosed.",
    target: ".tile:has(#outlook-list)" },
  { caption: "It reads the Mercedes side too — engine, fuel, live MPG — read-only, fused with the house data into one picture of the van.",
    target: ".tile:has(#chassis-block)" },
  { caption: "Ask it anything, typed or spoken — Whisper and a 4-billion-parameter model, both on this machine's own silicon.",
    target: ".chat-tile",
    action: () => sendChat("What is charging the battery right now, and how is it doing?") },
  { caption: "\"Can I cook dinner?\" Battery math is never the AI's job — a calculation service renders the verdict; the model just speaks it. That's why it's never wrong.",
    target: ".chat-tile",
    action: () => sendChat("Can I run the cooktop for 25 minutes?") },
  { caption: "Now let's go for a drive. Engine on, alternator charging, Starlink along for the ride. Watch the chassis readout come alive.",
    target: ".tile:has(#chassis-block)",
    action: () => postJson("/api/drive", { on: true }).then(() => { refreshTrip(); refreshAudit(); }) },
  { caption: "Thirty seconds in, we stage a failure: the charging path breaks. The engine is fine — Mercedes sees nothing wrong. Only the fused view catches it. Watch the alerts.",
    target: ".tile:has(#alert-list)" },
  { caption: "The Guardian — a deterministic policy engine, not the model — detects it, verifies it, and does the one legitimate thing: it can't fix the fault, so it sheds the load it can no longer afford. Every stage logged.",
    target: ".guardian" },
  { caption: "And you can ask why. The answer comes from the logged evidence — never from imagination.",
    target: ".chat-tile",
    action: () => sendChat("Why did you turn Starlink off?") },
  { caption: "Proof, not promises: every reading, every tool call, every action — audited. Zero external calls.",
    target: ".diag-tile" },
  { caption: "Monitor. Understand. Protect. Even beyond the reach of the cloud.",
    target: null,
    action: () => postJson("/api/drive", { on: false })
      .then(() => postJson("/api/guardian/reset", {}))
      .then(() => { refreshTrip(); refreshGuardian(); refreshAudit(); }) },
];

let storyStep = -1;

function storyRender() {
  document.querySelectorAll(".story-highlight").forEach(el =>
    el.classList.remove("story-highlight"));
  const active = storyStep >= 0 && storyStep < STORY.length;
  $("storybar").classList.toggle("hidden", !active);
  document.querySelector("main.grid").classList.toggle("story-dim", active);
  if (!active) return;
  const step = STORY[storyStep];
  $("story-caption").textContent = PRESENTATION
    ? step.caption.replace(/^Simulating dinner/, "Dinner time")
    : step.caption;
  $("story-dots").innerHTML = STORY.map((_, i) =>
    `<span class="${i === storyStep ? "on" : ""}">●</span>`).join("");
  if (step.target) {
    const el = document.querySelector(step.target);
    if (el) el.classList.add("story-highlight");
  }
  $("story-back").disabled = storyStep === 0;
  $("story-next").textContent = storyStep === STORY.length - 1 ? "Finish" : "Next ▶";
}

function storyGo(delta) {
  const next = storyStep + delta;
  if (next >= STORY.length || (storyStep === STORY.length - 1 && delta > 0)) {
    storyStep = -1;
    storyRender();
    return;
  }
  storyStep = Math.max(0, next);
  storyRender();
  // Actions fire only moving forward — Back re-points the spotlight without
  // re-running state changes.
  if (delta > 0 && STORY[storyStep].action) {
    Promise.resolve(STORY[storyStep].action()).catch(() => {});
  }
}

$("story-btn").addEventListener("click", () => { storyStep = -1; storyGo(1); });
$("story-next").addEventListener("click", () => storyGo(1));
$("story-back").addEventListener("click", () => storyGo(-1));
$("story-exit").addEventListener("click", () => {
  postJson("/api/appliance", { name: "cooktop", on: false }).catch(() => {});
  storyStep = -1; storyRender();
});

/* ---- boot ------------------------------------------------------------------ */

async function tick() {
  try {
    await Promise.all([refreshLatest(), refreshStatus(), refreshAlerts()]);
  } catch (e) {
    $("stale-chip").classList.remove("hidden");
    $("stale-chip").textContent = "⚠ API UNREACHABLE";
  }
}
tick();
refreshInsight();
refreshSparks();
refreshAudit();
refreshTrip();
refreshRuntime();
refreshWatchdog();
refreshGuardian();
setInterval(refreshWatchdog, 30_000);
setInterval(refreshGuardian, 10_000);
setInterval(tick, REFRESH_LATEST_MS);
setInterval(refreshInsight, REFRESH_INSIGHT_MS);
setInterval(refreshSparks, REFRESH_HISTORY_MS);
setInterval(refreshAudit, 15_000);
setInterval(refreshTrip, 10_000);
setInterval(refreshRuntime, 20_000);

// Deep link for filming: #story starts the guided demo, #story=5 jumps to
// step 5 (visual only — actions fire on real Next clicks, not on jumps).
const storyHash = location.hash.match(/^#story(?:=(\d+))?$/);
if (storyHash) {
  storyStep = storyHash[1]
    ? Math.min(STORY.length - 1, Math.max(0, Number(storyHash[1]) - 1))
    : 0;
  storyRender();
}
