/* HA Manager sidebar panel. Plain JavaScript, no build step. */

const TABS = [
  ["overview", "Overview"],
  ["safety", "Life safety"],
  ["activity", "Automations"],
  ["blast", "Blast radius"],
];

const SEVERITY = {
  critical: { label: "Critical", hint: "Fix these first" },
  warning: { label: "Warning", hint: "Sort these soon" },
  tidy: { label: "Tidy-up", hint: "When you have a spare ten minutes" },
};

const STATUS = {
  broken: "Broken",
  flapping: "Firing too often",
  zombie: "Not run in 90 days",
  off: "Switched off",
  ok: "Fine",
};

const KIND_PLURAL = {
  automation: "Automations",
  script: "Scripts",
  scene: "Scenes",
  group: "Groups",
  dashboard: "Dashboards",
};

const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );

const ago = (iso) => {
  if (!iso) return "never";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} hours ago`;
  return `${Math.round(hours / 24)} days ago`;
};

const STYLE = `
  :host { display:block; height:100%; overflow:auto; background:var(--primary-background-color,#fafafa);
    color:var(--primary-text-color); font-family:var(--paper-font-body1_-_font-family, Roboto, sans-serif);
    --hm-primary:var(--primary-color,#03a9f4); --hm-divider:var(--divider-color,#e0e0e0);
    --crit:var(--error-color,#db4437); --warn:var(--warning-color,#ffa600);
    --tidy:var(--info-color,#039be5); --ok:var(--success-color,#43a047); }
  header { display:flex; align-items:center; gap:8px; padding:0 12px; height:56px;
    background:var(--app-header-background-color,var(--hm-primary));
    color:var(--app-header-text-color,#fff); position:sticky; top:0; z-index:2; }
  header h1 { font-size:20px; font-weight:400; margin:0; flex:1; }
  header button { background:none; border:1px solid currentColor; color:inherit; border-radius:16px;
    padding:6px 14px; cursor:pointer; font:inherit; }
  nav { display:flex; gap:4px; padding:8px 12px 0; flex-wrap:wrap; border-bottom:1px solid var(--hm-divider); }
  nav button { background:none; border:none; border-bottom:3px solid transparent; padding:10px 14px;
    color:var(--secondary-text-color,#727272); cursor:pointer; font:inherit; font-weight:500; }
  nav button.on { color:var(--hm-primary); border-color:var(--hm-primary); }
  main { padding:16px; max-width:1000px; margin:0 auto; }
  .card { background:var(--card-background-color,#fff); border-radius:12px; padding:16px; margin-bottom:16px;
    box-shadow:var(--ha-card-box-shadow,0 1px 3px rgba(0,0,0,.2)); }
  .muted { color:var(--secondary-text-color,#727272); font-size:14px; }
  .score { display:flex; gap:24px; align-items:center; flex-wrap:wrap; }
  .dial { width:120px; height:120px; border-radius:50%; display:grid; place-items:center; flex:none; }
  .dial div { width:96px; height:96px; border-radius:50%; background:var(--card-background-color,#fff);
    display:grid; place-items:center; font-size:36px; font-weight:500; }
  .grade { font-size:22px; margin:0 0 4px; }
  .chips { display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }
  .chip { border-radius:14px; padding:4px 12px; font-size:13px; font-weight:500; color:#fff; white-space:nowrap; }
  .critical { background:var(--crit); } .warning { background:var(--warn); color:#000; }
  .tidy { background:var(--tidy); } .ok { background:var(--ok); }
  .excluded, .off { background:var(--disabled-color,#9e9e9e); }
  .broken { background:var(--crit); } .flapping { background:var(--warn); color:#000; } .zombie { background:var(--tidy); }
  h2 { font-size:18px; font-weight:500; margin:24px 0 4px; }
  h2 small { font-weight:400; color:var(--secondary-text-color,#727272); font-size:14px; margin-left:8px; }
  details.finding { background:var(--card-background-color,#fff); border-radius:10px; margin:8px 0;
    border-left:5px solid var(--hm-divider); box-shadow:var(--ha-card-box-shadow,0 1px 2px rgba(0,0,0,.15)); }
  details.finding.critical { border-left-color:var(--crit); background:var(--card-background-color,#fff); }
  details.finding.warning { border-left-color:var(--warn); background:var(--card-background-color,#fff); color:inherit; }
  details.finding.tidy { border-left-color:var(--tidy); background:var(--card-background-color,#fff); }
  summary { padding:12px 14px; cursor:pointer; display:flex; gap:10px; align-items:baseline; }
  summary .cat { color:var(--secondary-text-color,#727272); font-size:12px; text-transform:uppercase; letter-spacing:.04em;
    flex:none; min-width:110px; }
  summary .title { flex:1; }
  .body { padding:0 14px 14px; }
  .body p { margin:6px 0; }
  .advice { border-left:3px solid var(--hm-primary); padding-left:10px; }
  ul.items { margin:8px 0; padding-left:20px; }
  ul.items li { margin:3px 0; }
  code { font-size:12px; color:var(--secondary-text-color,#727272); }
  .actions { display:flex; gap:8px; margin-top:10px; flex-wrap:wrap; }
  .btn { border:1px solid var(--hm-primary); color:var(--hm-primary); background:none; border-radius:16px;
    padding:6px 14px; cursor:pointer; font:inherit; font-size:14px; text-decoration:none; }
  .btn.solid { background:var(--hm-primary); color:var(--text-primary-color,#fff); }
  table { width:100%; border-collapse:collapse; }
  th, td { text-align:left; padding:8px 6px; border-bottom:1px solid var(--hm-divider); vertical-align:top; }
  th { font-size:12px; text-transform:uppercase; color:var(--secondary-text-color,#727272); letter-spacing:.04em; }
  .units { display:grid; gap:12px; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); }
  .unit { background:var(--card-background-color,#fff); border-radius:12px; padding:14px;
    border-top:5px solid var(--ok); box-shadow:var(--ha-card-box-shadow,0 1px 3px rgba(0,0,0,.2)); }
  .unit.s-critical { border-top-color:var(--crit); } .unit.s-warning { border-top-color:var(--warn); }
  .unit.s-excluded { border-top-color:var(--disabled-color,#9e9e9e); opacity:.7; }
  .unit h3 { margin:0 0 2px; font-size:16px; font-weight:500; }
  .unit dl { display:grid; grid-template-columns:auto 1fr; gap:2px 12px; margin:10px 0; font-size:14px; }
  .unit dt { color:var(--secondary-text-color,#727272); } .unit dd { margin:0; }
  .alarm { background:var(--crit); color:#fff; border-radius:8px; padding:6px 10px; margin:8px 0; font-weight:500; }
  input[type=search] { width:100%; box-sizing:border-box; padding:12px; font:inherit; border-radius:8px;
    border:1px solid var(--hm-divider); background:var(--card-background-color,#fff); color:inherit; }
  .results { margin-top:6px; }
  .result { display:flex; gap:10px; width:100%; text-align:left; background:none; border:none;
    border-bottom:1px solid var(--hm-divider); padding:10px 6px; cursor:pointer; font:inherit; color:inherit; }
  .result:hover { background:var(--secondary-background-color); }
  .result .type { flex:none; width:60px; color:var(--secondary-text-color,#727272); font-size:12px; text-transform:uppercase; }
  .verdict { font-size:18px; font-weight:500; margin:0 0 6px; }
  .error { color:var(--crit); }
  @media (max-width:600px) { summary { flex-direction:column; gap:2px; } summary .cat { min-width:0; } }
`;

class HaManagerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._tab = "overview";
    this._data = null;
    this._targets = null;
    this._query = "";
    this._blast = null;
    this._busy = false;
    this._error = "";
    this._open = new Set();
    this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
    this.shadowRoot.addEventListener("input", (ev) => this._onInput(ev));
    this.shadowRoot.addEventListener(
      "toggle",
      (ev) => {
        const id = ev.target.dataset && ev.target.dataset.finding;
        if (!id) return;
        if (ev.target.open) this._open.add(id);
        else this._open.delete(id);
      },
      true
    );
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    const menu = this.shadowRoot.querySelector("ha-menu-button");
    if (menu) menu.hass = hass;
    if (first) this._load(false);
  }

  set narrow(value) {
    this._narrow = value;
    const menu = this.shadowRoot.querySelector("ha-menu-button");
    if (menu) menu.narrow = value;
  }

  connectedCallback() {
    this._render();
  }

  async _ws(message) {
    return this._hass.callWS(message);
  }

  async _load(refresh) {
    this._busy = true;
    this._error = "";
    this._render();
    try {
      this._data = await this._ws({ type: "ha_manager/scan", refresh });
      if (refresh) this._targets = null;
    } catch (err) {
      this._error = (err && err.message) || "Could not load the scan.";
    }
    this._busy = false;
    this._render();
    if (this._tab === "blast") this._loadTargets();
  }

  async _loadTargets() {
    if (this._targets) return;
    try {
      this._targets = await this._ws({ type: "ha_manager/targets" });
    } catch (err) {
      this._targets = [];
    }
    this._renderResults();
  }

  async _action(message) {
    try {
      this._data = await this._ws(message);
    } catch (err) {
      this._error = (err && err.message) || "That did not work.";
    }
    this._render();
  }

  _onClick(ev) {
    const el = ev.target.closest("[data-act]");
    if (!el) return;
    const act = el.dataset.act;
    if (act === "tab") {
      this._tab = el.dataset.tab;
      this._render();
      if (this._tab === "blast") this._loadTargets();
    } else if (act === "rescan") {
      this._load(true);
    } else if (act === "ignore") {
      ev.preventDefault();
      this._action({
        type: "ha_manager/ignore",
        finding_id: el.dataset.id,
        ignored: el.dataset.value === "1",
      });
    } else if (act === "log-test") {
      this._action({ type: "ha_manager/safety/log_test", unit_id: el.dataset.id });
    } else if (act === "exclude") {
      this._action({
        type: "ha_manager/safety/set_excluded",
        unit_id: el.dataset.id,
        excluded: el.dataset.value === "1",
      });
    } else if (act === "pick") {
      this._pick(el.dataset.type, el.dataset.id);
    } else if (act === "more-info") {
      ev.preventDefault();
      this.dispatchEvent(
        new CustomEvent("hass-more-info", {
          detail: { entityId: el.dataset.id },
          bubbles: true,
          composed: true,
        })
      );
    } else if (act === "nav") {
      ev.preventDefault();
      history.pushState(null, "", el.getAttribute("href"));
      window.dispatchEvent(new CustomEvent("location-changed", { bubbles: true, composed: true }));
    }
  }

  _onInput(ev) {
    if (ev.target.id !== "search") return;
    this._query = ev.target.value;
    this._blast = null;
    this._renderResults();
  }

  async _pick(type, id) {
    try {
      this._blast = await this._ws({
        type: "ha_manager/blast_radius",
        target_type: type,
        target_id: id,
      });
    } catch (err) {
      this._error = (err && err.message) || "Could not work that out.";
    }
    this._render();
  }

  /* ---------- rendering ---------- */

  _render() {
    if (!this.isConnected) return;
    const tabs = TABS.map(
      ([id, label]) =>
        `<button data-act="tab" data-tab="${id}" class="${this._tab === id ? "on" : ""}">${label}</button>`
    ).join("");
    let body = "";
    if (this._error) body += `<div class="card error">${esc(this._error)}</div>`;
    if (!this._data) {
      body += `<div class="card">${this._busy ? "Scanning your setup…" : "No scan yet."}</div>`;
    } else if (this._tab === "overview") body += this._overview();
    else if (this._tab === "safety") body += this._safety();
    else if (this._tab === "activity") body += this._activity();
    else body += this._blastTab();

    this.shadowRoot.innerHTML = `<style>${STYLE}</style>
      <header>
        <ha-menu-button></ha-menu-button>
        <h1>HA Manager</h1>
        <button data-act="rescan" ${this._busy ? "disabled" : ""}>${this._busy ? "Scanning…" : "Scan now"}</button>
      </header>
      <nav>${tabs}</nav>
      <main>${body}</main>`;
    const menu = this.shadowRoot.querySelector("ha-menu-button");
    if (menu) {
      menu.hass = this._hass;
      menu.narrow = this._narrow;
    }
    if (this._tab === "blast") this._renderResults();
  }

  _items(items) {
    if (!items || !items.length) return "";
    const rows = items.map((item) => {
      const name = item.entity_id
        ? `<a href="#" data-act="more-info" data-id="${esc(item.entity_id)}">${esc(item.name)}</a>`
        : esc(item.name);
      const id = item.entity_id && item.entity_id !== item.name ? ` <code>${esc(item.entity_id)}</code>` : "";
      const area = item.area ? ` <span class="muted">· ${esc(item.area)}</span>` : "";
      const note = item.note ? ` <span class="muted">· ${esc(item.note)}</span>` : "";
      return `<li>${name}${id}${area}${note}</li>`;
    });
    return `<ul class="items">${rows.join("")}</ul>`;
  }

  _finding(f, ignored) {
    const link = f.link
      ? `<a class="btn solid" data-act="nav" href="${esc(f.link)}">Open in Home Assistant</a>`
      : "";
    const open = this._open.has(f.id) ? "open" : "";
    return `<details class="finding ${f.severity}" data-finding="${esc(f.id)}" ${open}>
      <summary><span class="cat">${esc(f.category)}</span><span class="title">${esc(f.title)}</span>
        ${f.counts ? "" : '<span class="muted">not scored</span>'}</summary>
      <div class="body">
        ${f.detail ? `<p>${esc(f.detail)}</p>` : ""}
        ${this._items(f.items)}
        ${f.advice ? `<p class="advice"><strong>What to do:</strong> ${esc(f.advice)}</p>` : ""}
        <div class="actions">${link}
          <button class="btn" data-act="ignore" data-id="${esc(f.id)}" data-value="${ignored ? "0" : "1"}">
            ${ignored ? "Stop ignoring" : "Ignore this"}</button></div>
      </div></details>`;
  }

  _overview() {
    const d = this._data;
    const s = d.score;
    const colour = s.counts.critical ? "var(--crit)" : s.value >= 75 ? "var(--ok)" : "var(--warn)";
    const t = d.totals;
    let html = `<div class="card score">
      <div class="dial" style="background:conic-gradient(${colour} ${s.value * 3.6}deg, var(--hm-divider) 0)">
        <div>${s.value}</div></div>
      <div>
        <p class="grade">${esc(s.grade)}</p>
        <div class="muted">Checked ${t.entities} entities, ${t.devices} devices, ${t.automations} automations,
          ${t.scripts} scripts, ${t.scenes} scenes and ${t.dashboards} dashboards. Last scan ${ago(d.generated)}.</div>
        <div class="chips">
          <span class="chip critical">${s.counts.critical} critical</span>
          <span class="chip warning">${s.counts.warning} warning</span>
          <span class="chip tidy">${s.counts.tidy} tidy-up</span>
        </div>
      </div></div>`;
    if (!d.findings.length) {
      html += `<div class="card">Nothing to report. Everything checked out.</div>`;
    }
    for (const [key, meta] of Object.entries(SEVERITY)) {
      const list = d.findings.filter((f) => f.severity === key);
      if (!list.length) continue;
      html += `<h2>${meta.label} <small>${meta.hint}</small></h2>`;
      html += list.map((f) => this._finding(f, false)).join("");
    }
    if (d.ignored.length) {
      html += `<h2>Ignored <small>${d.ignored.length} hidden from the score</small></h2>`;
      html += d.ignored.map((f) => this._finding(f, true)).join("");
    }
    const src = d.sources;
    html += `<p class="muted">Also reading: Home Assistant Repairs (always),
      Spook (${src.spook ? "reporting issues" : "nothing reported or not installed"}),
      Watchman (${src.watchman ? "found" : "not installed"}).</p>`;
    return html;
  }

  _safety() {
    const units = this._data.safety.units;
    const days = this._data.safety.test_interval_days;
    let html = `<div class="card"><strong>Smoke, carbon monoxide, gas and leak sensors.</strong>
      <div class="muted">Press the test button on the device itself, then log it here. A test is due every ${days} days.
      This page is a reminder and a log. It cannot prove an alarm will sound.
      To add something else, give the entity the label “Life safety” in Home Assistant.</div></div>`;
    if (!units.length) {
      return html + `<div class="card">No life-safety sensors found.</div>`;
    }
    const cards = units.map((u) => {
      const battery =
        u.battery !== null && u.battery !== undefined
          ? `${Math.round(u.battery)}%`
          : u.battery_low
            ? "Low"
            : "Not reported";
      const label =
        u.status === "ok" ? "All good" : u.status === "excluded" ? "Not monitored" : u.problems.join(", ");
      const types = [...new Set(u.sensors.map((s) => s.type))].join(", ");
      return `<div class="unit s-${u.status}">
        <h3>${esc(u.name)}</h3>
        <div class="muted">${esc(u.area || "No room")} · ${esc(types)}</div>
        ${u.alarm && !u.excluded ? '<div class="alarm">Currently detecting something</div>' : ""}
        <div class="chips"><span class="chip ${u.status}">${esc(label)}</span></div>
        <dl>
          <dt>Battery</dt><dd>${battery}</dd>
          <dt>Last heard from</dt><dd>${ago(u.last_seen)}</dd>
          <dt>Last tested</dt><dd>${u.last_test ? ago(u.last_test) : "No test logged"}</dd>
          <dt>Tests logged</dt><dd>${u.test_count}</dd>
        </dl>
        <div class="actions">
          ${u.excluded ? "" : `<button class="btn solid" data-act="log-test" data-id="${esc(u.id)}">I tested it today</button>`}
          <button class="btn" data-act="exclude" data-id="${esc(u.id)}" data-value="${u.excluded ? "0" : "1"}">
            ${u.excluded ? "Monitor this" : "Not a safety device"}</button>
        </div></div>`;
    });
    return html + `<div class="units">${cards.join("")}</div>`;
  }

  _activity() {
    const rows = this._data.activity;
    let html = "";
    const since = this._data.sources.counting_since;
    if (since && Date.now() - new Date(since).getTime() < 24 * 3600 * 1000) {
      html += `<div class="card muted">HA Manager started counting ${ago(since)}, so the
        “fired in 24 hours” figures are still filling up.</div>`;
    }
    if (!rows.length) return html + `<div class="card">No automations or scripts found.</div>`;
    const body = rows.map((r) => {
      const name = r.edit_url
        ? `<a data-act="nav" href="${esc(r.edit_url)}">${esc(r.name)}</a>`
        : esc(r.name);
      return `<tr>
        <td>${name}<div class="muted">${esc(r.kind)}${r.note ? " · " + esc(r.note) : ""}</div></td>
        <td><span class="chip ${r.status}">${STATUS[r.status]}</span></td>
        <td>${ago(r.last_triggered)}</td>
        <td>${r.triggers_24h === null || r.triggers_24h === undefined ? "–" : r.triggers_24h}</td></tr>`;
    });
    return (
      html +
      `<div class="card"><table><thead><tr><th>Name</th><th>Status</th><th>Last ran</th>
        <th>Fired in 24h</th></tr></thead><tbody>${body.join("")}</tbody></table></div>`
    );
  }

  _blastTab() {
    let html = `<div class="card"><strong>What uses this?</strong>
      <div class="muted">Pick an entity, device or room to see every automation, script, scene, group and
      dashboard that relies on it. Check here before you rename or delete anything.</div>
      <p><input id="search" type="search" placeholder="Start typing a name, e.g. kitchen light"
        value="${esc(this._query)}" autocomplete="off"></p>
      <div class="results" id="results"></div></div>`;
    const b = this._blast;
    if (b) {
      const total = b.used_by.length;
      const verdict = b.safe
        ? `Nothing uses “${esc(b.target.name)}”.`
        : `${total} ${total === 1 ? "thing uses" : "things use"} “${esc(b.target.name)}”.`;
      html += `<div class="card"><p class="verdict">${verdict}</p>
        <div class="muted">${
          b.safe
            ? "Nothing in your automations, scripts, scenes, groups or editable dashboards points at it, so renaming or removing it should be safe. Voice assistants and other apps are not checked."
            : "Renaming or deleting it will affect everything below."
        }${b.target.type !== "entity" ? ` Includes its ${b.target.entity_count} entities.` : ""}</div>`;
      for (const [kind, label] of Object.entries(KIND_PLURAL)) {
        const list = b.used_by.filter((u) => u.kind === kind);
        if (!list.length) continue;
        html += `<h2>${label} <small>${list.length}</small></h2><ul class="items">`;
        html += list
          .map((u) => {
            const name = u.edit_url
              ? `<a data-act="nav" href="${esc(u.edit_url)}">${esc(u.name)}</a>`
              : esc(u.name);
            return `<li>${name} <span class="muted">· ${esc(u.why.join("; "))}</span></li>`;
          })
          .join("");
        html += `</ul>`;
      }
      html += `</div>`;
    }
    return html;
  }

  _renderResults() {
    const box = this.shadowRoot.getElementById("results");
    if (!box) return;
    if (!this._targets) {
      box.innerHTML = `<div class="muted">Loading the list…</div>`;
      return;
    }
    const words = this._query.toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length || this._blast) {
      box.innerHTML = "";
      return;
    }
    const matches = [];
    for (const target of this._targets) {
      const text = `${target.name} ${target.id} ${target.area || ""}`.toLowerCase();
      if (words.every((w) => text.includes(w))) {
        matches.push(target);
        if (matches.length >= 25) break;
      }
    }
    box.innerHTML = matches.length
      ? matches
          .map(
            (m) => `<button class="result" data-act="pick" data-type="${m.type}" data-id="${esc(m.id)}">
              <span class="type">${m.type === "area" ? "room" : m.type}</span>
              <span>${esc(m.name)}${m.type === "entity" ? ` <code>${esc(m.id)}</code>` : ""}
              ${m.area ? `<span class="muted"> · ${esc(m.area)}</span>` : ""}</span></button>`
          )
          .join("")
      : `<div class="muted">No matches.</div>`;
  }
}

customElements.define("ha-manager-panel", HaManagerPanel);
