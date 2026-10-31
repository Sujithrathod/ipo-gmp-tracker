"use strict";
const $ = s => document.querySelector(s);
const API = location.pathname.replace(/\/preview\/?.*$/, "");
const inr = n => n == null ? "—" : "₹" + Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 });
// ₹1.12 L / ₹3.4 Cr for big amounts, full digits below a lakh
const inrShort = n => n == null ? "—" : Math.abs(n) >= 1e7 ? `₹${+(n / 1e7).toFixed(2)} Cr` : Math.abs(n) >= 1e5 ? `₹${+(n / 1e5).toFixed(2)} L` : inr(n);
const fmtDate = d => d ? new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : "—";
// Everything shown comes from scraped third-party pages: escape it before it touches innerHTML.
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const todayIST = () => new Date(new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" })).setHours(0, 0, 0, 0);
const DAY = 864e5;

function dir(trend, cur, prev) {
  if (trend === "up" || trend === "down" || trend === "flat") return trend;
  if (cur == null || prev == null) return "flat";
  return cur > prev ? "up" : cur < prev ? "down" : "flat";
}
function badge(l) {
  if (!l || l.gmp == null) return "";
  const d = dir(l.trend, l.gmp, l.change == null ? null : l.gmp - l.change);
  const arrow = { up: "▲", down: "▼", flat: "▶" }[d];
  let t = arrow;
  if (l.change != null) t += ` ${l.change > 0 ? "+" : l.change < 0 ? "−" : "±"}₹${Math.abs(l.change)}`;
  if (l.change_pct != null && l.change) t += ` (${Math.abs(l.change_pct).toFixed(1)}%)`;
  return `<span class="badge ${d}">${t}</span>`;
}
function countdown(ipo) {
  const ld = ipo.listing_date && new Date(ipo.listing_date + "T00:00:00").getTime();
  if (!ld) return ipo.open_date ? `Opens ${fmtDate(ipo.open_date)}` : "";
  const days = Math.round((ld - todayIST()) / DAY);
  return days > 1 ? `Lists in ${days} days` : days === 1 ? "Lists tomorrow" : days === 0 ? "Lists today" : `Listed ${fmtDate(ipo.listing_date)}`;
}

// --------------------------------------------------------------------------
// Groww-style GMP chart: one line coloured by the change over the selected
// range, a dashed reference line at the range's starting GMP, and a scrubber
// that drives the big number above the chart.
// --------------------------------------------------------------------------
const RANGES = [["3D", 3], ["1W", 7], ["2W", 14], ["1M", 30], ["All", Infinity]];
const SVGNS = "http://www.w3.org/2000/svg";

function mountGmpChart(root, history, meta) {
  const all = history.filter(p => p.gmp != null).map(p => ({ ...p, t: new Date(p.date + "T00:00:00").getTime() }));
  if (!all.length) { root.innerHTML = '<div class="center">No GMP reported yet.</div>'; return; }

  // Offer a range only if it actually shows less than "All".
  const span = (all[all.length - 1].t - all[0].t) / DAY + 1;
  const ranges = RANGES.filter(([, days]) => days === Infinity || days < span);
  let range = "All", sel = null;

  root.innerHTML = `
    <div class="gc">
      <div class="gc-meta">${esc(meta)}</div>
      <div class="gc-value"><span id="gcV"></span><span class="gc-change" id="gcC"></span><span class="gc-range" id="gcR"></span></div>
      <div class="gc-plot" id="gcPlot"></div>
      <div class="gc-ranges" id="gcRanges">${ranges.map(([k]) => `<button data-k="${k}">${k}</button>`).join("")}</div>
    </div>`;
  const plot = root.querySelector("#gcPlot");

  function windowed() {
    const days = Object.fromEntries(RANGES)[range];
    const end = all[all.length - 1].t;
    const start = days === Infinity ? -Infinity : end - (days - 1) * DAY;
    const pts = all.filter(p => p.t >= start);
    const before = all.filter(p => p.t < start);
    // Like a previous close: the last GMP before the window, else the window's first.
    const base = before.length ? before[before.length - 1].gmp : pts[0].gmp;
    return { pts, base };
  }

  function header(pts, base) {
    const p = sel != null ? pts[sel] : pts[pts.length - 1];
    const ch = p.gmp - base;
    const pct = base ? (ch / Math.abs(base)) * 100 : null;
    const cls = ch > 0 ? "up" : ch < 0 ? "down" : "flat";
    root.querySelector("#gcV").textContent = inr(p.gmp);
    const c = root.querySelector("#gcC");
    c.className = "gc-change " + cls;
    c.textContent = `${ch > 0 ? "+" : ch < 0 ? "−" : ""}${Math.abs(ch)}${pct != null ? ` (${Math.abs(pct).toFixed(2)}%)` : ""}`;
    root.querySelector("#gcR").textContent = range;
  }

  function render() {
    const { pts, base } = windowed();
    const W = plot.clientWidth, H = 230, top = 30, bottom = 10, edge = 6;
    const vals = pts.map(p => p.gmp).concat(base);
    let lo = Math.min(...vals), hi = Math.max(...vals);
    if (lo === hi) { lo -= 1; hi += 1; }
    const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
    const x = i => pts.length === 1 ? W / 2 : edge + i * (W - 2 * edge) / (pts.length - 1);
    const y = v => top + (hi - v) * (H - top - bottom) / (hi - lo);
    const last = pts[pts.length - 1];
    const color = last.gmp > base ? "var(--up)" : last.gmp < base ? "var(--down)" : "var(--flat)";

    let s = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="GMP chart, ${range}: ${inr(pts[0].gmp)} to ${inr(last.gmp)}">`;
    s += `<line x1="0" x2="${W}" y1="${y(base)}" y2="${y(base)}" stroke="var(--muted)" stroke-opacity=".45" stroke-dasharray="5 5"/>`;
    s += `<path d="${pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.gmp).toFixed(1)}`).join("")}" fill="none" stroke="${color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>`;
    if (sel == null) {
      s += `<circle class="gc-pulse" cx="${x(pts.length - 1)}" cy="${y(last.gmp)}" r="5" fill="${color}"/>`;
      s += `<circle cx="${x(pts.length - 1)}" cy="${y(last.gmp)}" r="4" fill="${color}"/>`;
    } else {
      const p = pts[sel], px = x(sel);
      const arrow = { up: "▲", down: "▼", flat: "" }[dir(p.trend, p.gmp, sel ? pts[sel - 1].gmp : null)];
      s += `<line x1="${px}" x2="${px}" y1="${top - 6}" y2="${H}" stroke="var(--muted)" stroke-opacity=".5"/>`;
      s += `<circle cx="${px}" cy="${y(p.gmp)}" r="8" fill="${color}" fill-opacity=".2"/>`;
      s += `<circle cx="${px}" cy="${y(p.gmp)}" r="4" fill="${color}"/>`;
      s += `<text id="gcLbl" class="gc-label" x="${px}" y="12"><tspan class="v">${inr(p.gmp)}</tspan>${arrow ? ` <tspan fill="${arrow === "▼" ? "var(--down)" : "var(--up)"}">${arrow}</tspan>` : ""} | ${fmtDate(p.date)}${p.last_updated ? ", " + esc(p.last_updated) : ""}${p.source && p.source !== "ipowatch" ? " · " + esc(p.source) : ""}</text>`;
    }
    plot.innerHTML = s + "</svg>";

    const lbl = plot.querySelector("#gcLbl");
    if (lbl) { // centre the label on the scrubber, clamped inside the chart
      const w = lbl.getComputedTextLength();
      lbl.setAttribute("x", Math.max(0, Math.min(W - w, x(sel) - w / 2)));
    }
    root.querySelectorAll("#gcRanges button").forEach(b => b.classList.toggle("on", b.dataset.k === range));
    header(pts, base);
    plot._x = x; plot._n = pts.length; plot._w = W;
  }

  function scrubTo(clientX) {
    const r = plot.getBoundingClientRect(), n = plot._n;
    if (n < 2) { sel = 0; return render(); }
    let best = 0, bestD = Infinity;
    for (let i = 0; i < n; i++) { const d = Math.abs(plot._x(i) - (clientX - r.left)); if (d < bestD) { bestD = d; best = i; } }
    if (best !== sel) { sel = best; render(); if (navigator.vibrate && navigator.userActivation?.isActive) navigator.vibrate(4); }
  }
  const release = () => { if (sel != null) { sel = null; render(); } };
  plot.addEventListener("pointerdown", e => {
    try { plot.setPointerCapture(e.pointerId); } catch { /* capture is optional */ }
    scrubTo(e.clientX);
  });
  plot.addEventListener("pointermove", e => { if (e.pointerType === "mouse" || e.buttons) scrubTo(e.clientX); });
  plot.addEventListener("pointerup", e => { if (e.pointerType !== "mouse") release(); });
  plot.addEventListener("pointercancel", release);
  plot.addEventListener("pointerleave", e => { if (e.pointerType === "mouse") release(); });
  root.querySelector("#gcRanges").onclick = e => { const b = e.target.closest("button"); if (b) { range = b.dataset.k; sel = null; render(); } };
  render();
  new ResizeObserver(() => { if (plot.clientWidth !== plot._w) render(); }).observe(plot);
}

// --------------------------------------------------------------------------
// Screens
// --------------------------------------------------------------------------
let status = "home";

// --------------------------------------------------------------------------
// Home: IPOs open for bidding, ranked by GMP-implied gain
// --------------------------------------------------------------------------
const SORTS = {
  gain: { label: "Gain %", value: i => i.est_gain_pct, fmt: v => v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(1)}%` },
  profit: { label: "Profit / lot", value: i => i.profit_per_lot, fmt: v => inrShort(v) },
};
let sortKey = "gain", desc = true, dash = null;

function sorted(items) {
  const v = SORTS[sortKey].value;
  // IPOs with no GMP yet always sit at the bottom, whichever way we sort.
  return [...items].sort((a, b) => (v(a) == null) - (v(b) == null) || (desc ? v(b) - v(a) : v(a) - v(b)));
}

function sparkline(series, w = 84, h = 38) {
  const pts = series.filter(p => p.gmp != null);
  if (pts.length < 2) return `<svg class="spark" width="${w}" height="${h}"></svg>`;
  const vals = pts.map(p => p.gmp);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (lo === hi) { lo -= 1; hi += 1; }
  const x = i => 3 + i * (w - 6) / (pts.length - 1), y = v => 4 + (hi - v) * (h - 8) / (hi - lo);
  const ch = vals[vals.length - 1] - vals[0];
  const c = ch > 0 ? "var(--up)" : ch < 0 ? "var(--down)" : "var(--flat)";
  return `<svg class="spark" width="${w}" height="${h}" aria-hidden="true">
    <line x1="0" x2="${w}" y1="${y(vals[0])}" y2="${y(vals[0])}" stroke="var(--muted)" stroke-opacity=".35" stroke-dasharray="3 3"/>
    <path d="${pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.gmp).toFixed(1)}`).join("")}" fill="none" stroke="${c}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
    <circle cx="${x(pts.length - 1)}" cy="${y(vals[vals.length - 1])}" r="3" fill="${c}"/></svg>`;
}

function barChart(items) {
  const s = SORTS[sortKey];
  const max = Math.max(1, ...items.map(i => Math.abs(s.value(i) ?? 0)));
  return `<div class="card bars" role="list" aria-label="Open IPOs by ${s.label}">${items.map((i, n) => {
    const v = s.value(i);
    const cls = v == null ? "flat" : v > 0 ? "up" : v < 0 ? "down" : "flat";
    return `<div class="bar-row" role="listitem" data-slug="${esc(i.slug)}">
      <span class="bar-rank">${n + 1}</span><span class="bar-name">${esc(i.name)}</span>
      <span class="bar-track"><span class="bar-fill" style="display:block;width:${v == null ? 0 : Math.max(2, Math.abs(v) / max * 100)}%;background:var(--${cls})"></span></span>
      <span class="bar-val ${cls}">${s.fmt(v)}</span></div>`;
  }).join("")}</div>`;
}

function dashCard(i, n) {
  const closes = i.days_to_close == null ? "" : i.days_to_close > 1 ? `Closes in ${i.days_to_close} days` : i.days_to_close === 1 ? "Closes tomorrow" : i.days_to_close === 0 ? "Closes today" : `Lists ${fmtDate(i.listing_date)}`;
  const g = i.est_gain_pct;
  return `<div class="card ipo dcard" data-slug="${esc(i.slug)}">
    <div class="top"><span class="rank">${n + 1}</span>
      <div class="dname"><div class="name">${esc(i.name)}</div>
        <div class="sub">${i.category === "sme" ? "SME" : "Mainboard"}${closes ? " · " + closes : ""}</div></div>
      ${sparkline(i.gmp_series)}</div>
    <div class="stats">
      <div><span class="label">GMP</span><b>${inr(i.latest_gmp?.gmp)}</b></div>
      <div><span class="label">Est. gain</span><b class="${g == null ? "" : g > 0 ? "up" : g < 0 ? "down" : ""}">${SORTS.gain.fmt(g)}</b></div>
      <div><span class="label">Profit / lot</span><b>${inrShort(i.profit_per_lot)}</b></div>
      <div><span class="label">Min. invest</span><b>${inrShort(i.min_investment)}</b></div>
    </div></div>`;
}

function renderHome() {
  const open = sorted(dash.open), awaiting = sorted(dash.awaiting_listing);
  $("#main").innerHTML = `
    <div class="dh-sub">Open for bidding · as of ${fmtDate(dash.as_of)}</div>
    <div class="dh-title">Ranked by grey-market gain</div>
    <div class="controls">
      <div class="seg" id="sortSeg">${Object.entries(SORTS).map(([k, s]) => `<button data-k="${k}" class="${k === sortKey ? "on" : ""}">${s.label}</button>`).join("")}</div>
      <button class="order" id="order" aria-label="Reverse order">${desc ? "High → Low" : "Low → High"}</button>
    </div>
    ${open.length ? barChart(open) + open.map(dashCard).join("") : '<div class="card center">No IPOs are open for bidding today.</div>'}
    ${awaiting.length ? `<div class="section">Closed · awaiting listing</div>${awaiting.map(dashCard).join("")}` : ""}
    <div class="disclaimer">${esc(dash.disclaimer)}</div>${note()}`;
  $("#sortSeg").onclick = e => { const b = e.target.closest("button"); if (b) { sortKey = b.dataset.k; renderHome(); } };
  $("#order").onclick = () => { desc = !desc; renderHome(); };
  document.querySelectorAll("[data-slug]").forEach(el => el.onclick = () => { location.hash = el.dataset.slug; });
}

// Always ask the server (it has its own 5-minute cache) instead of the browser's HTTP cache,
// which can hold a stale copy for 5 minutes after the data or the API changes.
const api = path => fetch(API + path, { cache: "no-cache" });

// Data changes once a day, so keep each tab's response for the session: swiping back is instant.
const responses = {};
async function load(path) {
  if (!(path in responses)) {
    $("#main").innerHTML = '<div class="center">Loading…</div>';
    responses[path] = api(path).then(r => r.json()).catch(e => { delete responses[path]; throw e; });
  }
  return responses[path];
}

function tabChrome() {
  $("#back").hidden = true; $("#tabs").hidden = false; $("#title").textContent = "IPO GMP Tracker";
  $("#main").style.paddingBottom = "";
  $("#main").classList.add("swipeable");
}

async function showHome() {
  tabChrome();
  const data = await load("/dashboard");
  if (status !== "home" || location.hash.length > 1) return; // user moved on while loading
  dash = data;
  renderHome();
}

async function showList() {
  tabChrome();
  const want = status;
  const items = await load(`/ipos?status=${want}`);
  if (status !== want || location.hash.length > 1) return;
  $("#main").innerHTML = items.length ? items.map(i => `
    <div class="card ipo" data-slug="${esc(i.slug)}">
      <div class="name">${esc(i.name)}</div>
      <div class="sub">${i.category === "sme" ? "SME" : "Mainboard"} · ${inr(i.price_band_max)} · Lot ${i.lot_size ?? "—"}</div>
      <div class="row">
        <div><div class="label">GMP</div><div class="gmp">${inr(i.latest_gmp?.gmp)}</div></div>
        <div>${badge(i.latest_gmp)}</div>
        <div style="text-align:right"><div class="label">Est. gain</div><div>${i.latest_gmp?.gain_pct != null ? i.latest_gmp.gain_pct + "%" : "—"}</div></div>
      </div>
      ${countdown(i) ? `<span class="chip">${countdown(i)}</span>` : ""}
    </div>`).join("") + note() : `<div class="center">No ${status} IPOs right now.</div>`;
  document.querySelectorAll(".ipo").forEach(el => el.onclick = () => { location.hash = el.dataset.slug; });
}

async function showDetail(slug) {
  $("#back").hidden = false; $("#tabs").hidden = true; $("#main").classList.remove("swipeable");
  $("#main").style.paddingBottom = "";
  $("#main").innerHTML = '<div class="center">Loading…</div>';
  const r = await api(`/ipos/${encodeURIComponent(slug)}`);
  if (!r.ok) { $("#main").innerHTML = '<div class="center">IPO not found.</div>'; return; }
  const i = await r.json();
  $("#title").textContent = i.name;
  const rows = [...i.gmp_history].reverse();
  $("#main").innerHTML = `
    <div id="chart"></div>
    ${buyButtons(i)}
    <div class="card">
      <h3>IPO details</h3>
      <div class="kv"><span>Price band</span><span>${inr(i.price_band_min)} – ${inr(i.price_band_max)}</span></div>
      <div class="kv"><span>Est. listing price</span><span>${inr(i.estimated_listing_price)}</span></div>
      <div class="kv"><span>Lot size</span><span>${i.lot_size ?? "—"} shares</span></div>
      <div class="kv"><span>Min. investment</span><span>${i.lot_size && i.price_band_max ? inr(i.lot_size * i.price_band_max) : "—"}</span></div>
      <div class="kv"><span>Open</span><span>${fmtDate(i.open_date)}</span></div>
      <div class="kv"><span>Close</span><span>${fmtDate(i.close_date)}</span></div>
      <div class="kv"><span>Listing</span><span>${fmtDate(i.listing_date)}</span></div>
    </div>
    <div class="card">
      <h3>Day-wise GMP</h3>
      <table><tr><th>Date</th><th>GMP</th><th>Trend</th><th>Gain</th></tr>
      ${rows.map(p => { const d = p.trend || "flat"; return `<tr><td>${fmtDate(p.date)}${p.source !== "ipowatch" ? ' <span class="src" title="From ' + esc(p.source) + '.com">*</span>' : ""}</td><td>${inr(p.gmp)}</td><td class="${d}">${p.trend ? { up: "▲", down: "▼", flat: "▶" }[p.trend] : "–"}</td><td>${p.gain_pct != null ? p.gain_pct + "%" : "—"}</td></tr>`; }).join("")}
      </table>
    </div>
    ${i.sources.includes("investorgain") ? `<div class="note">* GMP from investorgain.com on days ipowatch.in had none. The two sites often quote different figures.</div>` : ""}
    <div class="note">“Track this IPO” and the 10 AM notification live in the Android app.</div>${note()}`;
  const meta = `${i.category === "sme" ? "SME" : "Mainboard"} · GMP · ${i.listing_date ? "Lists " + fmtDate(i.listing_date) : "Listing date TBA"}`;
  mountGmpChart($("#chart"), i.gmp_history, meta);
  if (i.about_summary) showAboutCard(i);
}

// "Apply on Groww / Zerodha": plain https links, which Android opens in the broker's app
// when it's installed. Only links to these two hosts are ever rendered.
const SAFE_BUY = /^https:\/\/(groww\.in|kite\.zerodha\.com)\//;
function buyButtons(i) {
  const b = i.buy_links;
  if (!b || !SAFE_BUY.test(b.groww) || !SAFE_BUY.test(b.zerodha)) return "";
  return `<div class="card buy">
    <h3>Apply for this IPO</h3>
    <div class="buy-row">
      <a class="buy-btn" href="${esc(b.groww)}" target="_blank" rel="noopener noreferrer">Groww</a>
      <a class="buy-btn" href="${esc(b.zerodha)}" target="_blank" rel="noopener noreferrer">Zerodha Kite</a>
    </div>
    <div class="buy-note">Opens the app if it's installed, otherwise the website.
      ${b.groww_exact ? "Groww opens this IPO directly." : "Groww opens its IPO list."} Kite opens its IPO section; pick ${esc(i.name)} there.</div>
  </div>`;
}

// Floating card with what the company does; tap to read the full description, ✕ to dismiss.
function showAboutCard(i) {
  const more = i.about && i.about.length > i.about_summary.length;
  const card = document.createElement("section");
  card.className = "about";
  card.setAttribute("aria-label", `About ${i.name}`);
  card.innerHTML = `
    <div class="about-label">About ${esc(i.name)}</div>
    <div class="about-text" id="aboutText">${esc(i.about_summary)}</div>
    ${more ? '<button class="about-more" id="aboutMore">Read more</button>' : ""}
    <button class="about-x" aria-label="Close">✕</button>`;
  $("#main").appendChild(card);
  const pad = () => { $("#main").style.paddingBottom = card.isConnected ? `${card.offsetHeight + 32}px` : ""; };
  const toggle = () => {
    if (!more) return;
    const open = card.classList.toggle("open");
    $("#aboutText").textContent = open ? i.about : i.about_summary;
    $("#aboutMore").textContent = open ? "Show less" : "Read more";
    if (!open) $("#aboutText").scrollTop = 0;
    pad();
  };
  $("#aboutText").onclick = toggle;
  if (more) $("#aboutMore").onclick = toggle;
  card.querySelector(".about-x").onclick = () => { card.remove(); pad(); };
  pad();
}

const note = () => `<div class="note">Source: ipowatch.in · GMP is unofficial and not investment advice.</div>`;

// --------------------------------------------------------------------------
// Tabs: tap or swipe (left = next tab, right = previous), like an Android pager
// --------------------------------------------------------------------------
const TABS = ["home", "current", "upcoming", "listed"];
const main = $("#main"), ind = $("#ind");

function placeIndicator(pos, animate = true) {
  ind.style.transition = animate ? "" : "none";
  ind.style.transform = `translateX(${pos * 100}%)`;
}

async function setTab(next, dir = 0) {
  status = next;
  document.querySelectorAll("#tabs button").forEach(x => x.classList.toggle("on", x.dataset.s === next));
  placeIndicator(TABS.indexOf(next));
  window.scrollTo(0, 0);
  await (next === "home" ? showHome() : showList());
  if (dir) main.animate([{ transform: `translateX(${dir * 48}px)`, opacity: 0 }, { transform: "none", opacity: 1 }],
                        { duration: 220, easing: "cubic-bezier(.2,.8,.2,1)" });
}

$("#tabs").onclick = e => {
  const b = e.target.closest("button");
  if (!b || b.dataset.s === status) return;
  setTab(b.dataset.s, Math.sign(TABS.indexOf(b.dataset.s) - TABS.indexOf(status)));
};

let swipe = null, suppressClick = false;
const onTabScreen = () => location.hash.length <= 1;

main.addEventListener("pointerdown", e => {
  if (!onTabScreen() || (e.pointerType === "mouse" && e.button !== 0)) return;
  swipe = { id: e.pointerId, x: e.clientX, y: e.clientY, t: performance.now(), dx: 0, axis: null };
});

main.addEventListener("pointermove", e => {
  if (!swipe || e.pointerId !== swipe.id) return;
  const dx = e.clientX - swipe.x, dy = e.clientY - swipe.y;
  if (!swipe.axis) {
    if (Math.hypot(dx, dy) < 10) return;
    swipe.axis = Math.abs(dx) > Math.abs(dy) * 1.2 ? "x" : "y"; // decide once; vertical = normal scroll
    if (swipe.axis === "x") { try { main.setPointerCapture(e.pointerId); } catch {} }
  }
  if (swipe.axis !== "x") return;
  const i = TABS.indexOf(status);
  const atEdge = (i === 0 && dx > 0) || (i === TABS.length - 1 && dx < 0);
  swipe.dx = atEdge ? dx / 4 : dx; // rubber-band past the first/last tab
  main.style.transition = "none";
  main.style.transform = `translateX(${swipe.dx}px)`;
  placeIndicator(i - swipe.dx / main.clientWidth, false);
});

function endSwipe(e) {
  if (!swipe || e.pointerId !== swipe.id) return;
  const s = swipe; swipe = null;
  if (s.axis !== "x") return;
  suppressClick = true; setTimeout(() => (suppressClick = false), 400); // a swipe isn't a tap on a card
  const i = TABS.indexOf(status), w = main.clientWidth;
  const velocity = s.dx / Math.max(1, performance.now() - s.t); // px per ms
  const dir = s.dx < -w * 0.25 || velocity < -0.45 ? 1 : s.dx > w * 0.25 || velocity > 0.45 ? -1 : 0;
  const target = TABS[i + dir];
  main.style.transition = "transform .18s ease-out";
  if (dir && target && e.type !== "pointercancel") {
    main.style.transform = `translateX(${-dir * w}px)`;
    placeIndicator(i + dir);
    setTimeout(() => { main.style.transition = "none"; main.style.transform = ""; setTab(target, dir); }, 180);
  } else {
    main.style.transform = "";
    placeIndicator(i);
  }
}
main.addEventListener("pointerup", endSwipe);
main.addEventListener("pointercancel", endSwipe);
main.addEventListener("click", e => { if (suppressClick) { e.stopPropagation(); e.preventDefault(); } }, true);
const ICONS = {
  moon: '<svg viewBox="0 0 24 24"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>',
  sun: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
};
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  const btn = $("#theme");
  btn.innerHTML = t === "dark" ? ICONS.sun : ICONS.moon; // show the mode you'd switch to
  btn.setAttribute("aria-label", t === "dark" ? "Switch to light mode" : "Switch to dark mode");
  document.querySelector('meta[name="theme-color"]').content = t === "dark" ? "#121212" : "#ffffff";
}
$("#theme").onclick = () => {
  const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  try { localStorage.setItem("theme", t); } catch (e) { /* preference just won't persist */ }
  applyTheme(t);
};
applyTheme(document.documentElement.dataset.theme);

$("#back").onclick =() => { history.length > 1 ? history.back() : (location.hash = ""); };
const route = () => location.hash.length > 1 ? showDetail(decodeURIComponent(location.hash.slice(1)))
  : setTab(status);
window.addEventListener("hashchange", route);
route();
