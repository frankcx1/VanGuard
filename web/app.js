/* VanGuard dashboard. Vanilla JS, zero dependencies, fully offline. */
"use strict";

const REFRESH_LATEST_MS = 5_000;
const REFRESH_HISTORY_MS = 60_000;
const HISTORY_WINDOW_S = 24 * 3600;

/* Each sparkline: fixed entity color, one series, hover crosshair+tooltip. */
const SPARKS = {
  soc:   { source: "shunt",  metric: "soc_pct",    color: "var(--c-soc)",   fmt: v => `${v.toFixed(0)}%` },
  volts: { source: "shunt",  metric: "voltage_v",  color: "var(--c-volts)", fmt: v => `${v.toFixed(2)} V` },
  net:   { source: "shunt",  metric: "power_w",    color: "var(--c-net)",   fmt: v => `${v.toFixed(0)} W` },
  pv:    { source: "dcc50s", metric: "pv_power_w", color: "var(--c-solar)", fmt: v => `${v.toFixed(0)} W` },
};

const $ = id => document.getElementById(id);
const tooltip = $("tooltip");

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

/* ---- latest readings → tiles ---------------------------------------------- */

async function refreshLatest() {
  const r = await fetch("/api/telemetry/latest");
  const data = await r.json();
  const rd = data.readings, dv = data.derived;

  // Integrity guardrail: badge is driven by the payload stamp, nothing else.
  $("sim-badge").classList.toggle("hidden", data.simulated !== true);
  $("src-line").textContent =
    `source: ${data.source_kind}` + (data.simulated ? " · SIMULATED DATA" : " · live van data");

  const soc = get(rd, "shunt", "soc_pct");
  $("soc").textContent = soc == null ? "–" : soc.toFixed(0);
  setSocStatus(soc);

  const tte = fmtHours(dv?.time_to_empty_h);
  const ttf = fmtHours(dv?.time_to_full_h);
  $("tte-ttf").textContent =
    tte ? `≈ ${tte} to empty at current draw`
    : ttf ? `≈ ${ttf} to full at current charge`
    : "holding steady";

  const v = get(rd, "shunt", "voltage_v");
  $("volts").textContent = v == null ? "–" : v.toFixed(2);
  const i = get(rd, "shunt", "current_a");
  $("amps").textContent = i == null ? "–" : `${i > 0 ? "+" : ""}${i.toFixed(1)} A`;
  const bt = get(rd, "shunt", "temp_c");
  $("batt-temp").textContent = bt == null ? "–" : `${bt.toFixed(0)} °C`;

  const net = get(rd, "shunt", "power_w");
  $("net-w").textContent = net == null ? "–" : Math.abs(net).toFixed(0);
  const dir = $("flow-dir");
  if (net == null) { dir.textContent = ""; }
  else if (net > 5)  { dir.textContent = "▲ charging";    dir.className = "status good"; }
  else if (net < -5) { dir.textContent = "▼ discharging"; dir.className = "status plain"; }
  else               { dir.textContent = "· idle";        dir.className = "status plain"; }

  const pv = get(rd, "dcc50s", "pv_power_w");
  $("pv-w").textContent = pv == null ? "–" : pv.toFixed(0);
  const yld = dv?.solar_yield_wh_today;
  $("pv-yield").textContent = yld == null ? "–" : `${yld.toFixed(0)} Wh today`;

  setLoadTile(dv);
  fillTable(rd, data.server_ts);
}

function setSocStatus(soc) {
  const el = $("soc-status");
  if (soc == null) { el.textContent = ""; return; }
  // Reserved status colors, always icon + label — never color alone.
  if (soc >= 50)      { el.textContent = "✓ OK";        el.className = "status good"; }
  else if (soc >= 30) { el.textContent = "⚠ LOW";       el.className = "status warn"; }
  else if (soc >= 15) { el.textContent = "⚠ VERY LOW";  el.className = "status serious"; }
  else                { el.textContent = "✖ CRITICAL";  el.className = "status critical"; }
}

function setLoadTile(dv) {
  const big = $("load-big"), w = $("load-w"), note = $("load-note");
  if (dv?.load_w == null) {
    // The honest state: on shore power the charger is invisible to us, so we
    // refuse to derive a load number rather than display a wrong one.
    big.classList.add("unavailable");
    big.innerHTML = dv?.shore_power_suspected
      ? "unavailable on shore power"
      : "–";
    note.textContent = dv?.shore_power_suspected
      ? "charging from a source telemetry can't see (inverter/charger is CAN-only)"
      : "waiting for readings";
  } else {
    big.classList.remove("unavailable");
    big.innerHTML = `<span id="load-w">${dv.load_w.toFixed(0)}</span><span class="unit">W</span>`;
    note.textContent = "derived: sources in − net battery power · off-grid only";
  }
}

function fillTable(rd, serverTs) {
  const tbody = $("readings-table").querySelector("tbody");
  const rows = [];
  for (const source of Object.keys(rd ?? {}).sort()) {
    for (const metric of Object.keys(rd[source]).sort()) {
      const { ts, value } = rd[source][metric];
      rows.push(`<tr><td>${source}</td><td>${metric}</td>` +
        `<td class="num">${Number(value.toFixed(3))}</td>` +
        `<td>${fmtAge(serverTs - ts)}</td></tr>`);
    }
  }
  tbody.innerHTML = rows.join("");
}

/* ---- status / staleness ---------------------------------------------------- */

async function refreshStatus() {
  const r = await fetch("/api/status");
  const s = await r.json();
  const chip = $("stale-chip");
  chip.classList.toggle("hidden", !s.stale);
  if (s.stale) chip.textContent = `⚠ STALE ${fmtAge(s.staleness_s)}`;
  $("clock").textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/* ---- sparklines ------------------------------------------------------------ */

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
  const W = 600, H = 64, PAD = 3;
  const ts = points.map(p => p[0]), vs = points.map(p => p[1]);
  const t0 = ts[0], t1 = ts[ts.length - 1];
  let lo = Math.min(...vs), hi = Math.max(...vs);
  if (hi - lo < 1e-9) { hi += 0.5; lo -= 0.5; }
  const x = t => PAD + (W - 2 * PAD) * (t - t0) / Math.max(1, t1 - t0);
  const y = v => PAD + (H - 2 * PAD) * (1 - (v - lo) / (hi - lo));

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "none");
  const base = line(PAD, y(Math.max(lo, Math.min(hi, 0))), W - PAD, y(Math.max(lo, Math.min(hi, 0))), "var(--baseline)", 1);
  if (lo < 0 && hi > 0) svg.appendChild(base);   // zero line only when it's in-range
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

/* ---- chat ------------------------------------------------------------------ */

const chatHistory = [];   // client-side context, capped to keep prompts small

async function sendChat(question) {
  const log = $("chat-log"), input = $("chat-input"), btn = $("chat-send");
  log.insertAdjacentHTML("beforeend",
    `<div class="msg user">${escapeHtml(question)}</div>`);
  const pending = document.createElement("div");
  pending.className = "msg assistant pending";
  pending.textContent = "thinking… (first question loads the model)";
  log.appendChild(pending);
  log.scrollTop = log.scrollHeight;
  input.value = ""; btn.disabled = true;

  chatHistory.push({ role: "user", content: question });
  while (chatHistory.length > 8) chatHistory.shift();   // context discipline
  try {
    const r = await fetch("/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: chatHistory }),
    });
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
    const data = await r.json();
    const answer = data.choices[0].message.content;
    chatHistory.push({ role: "assistant", content: answer });
    const vg = data.vanguard ?? {};
    const tools = (vg.tool_calls ?? []).map(t => t.tool).join(", ");
    pending.classList.remove("pending");
    pending.innerHTML = escapeHtml(answer) +
      `<span class="meta">${vg.device ?? "?"} · ${vg.tokens_per_s ?? "?"} tok/s` +
      (tools ? ` · tools: ${escapeHtml(tools)}` : " · no tools used") +
      (vg.simulated ? " · SIM data" : "") + `</span>`;
    refreshAudit();
  } catch (e) {
    pending.classList.remove("pending");
    pending.innerHTML = `<em>error: ${escapeHtml(String(e.message))}</em>`;
    chatHistory.pop();
  } finally {
    btn.disabled = false;
    log.scrollTop = log.scrollHeight;
  }
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

$("chat-form").addEventListener("submit", ev => {
  ev.preventDefault();
  const q = $("chat-input").value.trim();
  if (q && !$("chat-send").disabled) sendChat(q);
});

/* ---- audit view ------------------------------------------------------------ */

async function refreshAudit() {
  const r = await fetch("/api/audit?limit=25");
  const { entries } = await r.json();
  const tbody = $("audit-table").querySelector("tbody");
  tbody.innerHTML = (entries ?? []).map(e =>
    `<tr><td>${new Date(e.ts * 1000).toLocaleTimeString()}</td>` +
    `<td>${escapeHtml(e.tool)}</td>` +
    `<td><code>${escapeHtml(e.args)}</code></td>` +
    `<td>${escapeHtml(e.device ?? "–")}</td>` +
    `<td class="num">${e.duration_ms}</td>` +
    `<td><code>${escapeHtml(e.result_hash)}</code></td></tr>`).join("");
}

/* ---- boot ------------------------------------------------------------------ */

async function tick() {
  try {
    await Promise.all([refreshLatest(), refreshStatus()]);
  } catch (e) {
    $("stale-chip").classList.remove("hidden");
    $("stale-chip").textContent = "⚠ API UNREACHABLE";
  }
}
tick();
refreshSparks();
refreshAudit();
setInterval(tick, REFRESH_LATEST_MS);
setInterval(refreshSparks, REFRESH_HISTORY_MS);
setInterval(refreshAudit, 15_000);
