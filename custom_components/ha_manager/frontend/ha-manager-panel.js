/* HA Manager sidebar panel. Plain JavaScript, no build step. */

const TABS = [
  ["overview", "Overview"],
  ["safety", "Life safety"],
  ["activity", "Automations"],
  ["blast", "Blast radius"],
  ["batteries", "Batteries"],
  ["plan", "Floor plan"],
  ["rooms", "Rooms"],
  ["names", "Names"],
  ["log", "Log"],
  ["report", "Weekly report"],
];

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

const NAME_PROBLEMS = {
  wrong_room: "Wrong room in name",
  duplicate: "Duplicate",
  technical: "Technical name",
  no_room: "No room in name",
  has_room: "Room repeated",
};

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
  .explain { background:var(--secondary-background-color,#f5f5f5); border-radius:8px; padding:10px 12px; margin-top:8px; }
  .explain p { margin:4px 0; } .explain pre { margin:4px 0; white-space:pre-wrap; font:inherit; }
  .linkbtn { background:none; border:none; padding:0; color:var(--hm-primary); cursor:pointer; font:inherit; font-size:13px; }
  .meter { height:8px; border-radius:4px; background:var(--hm-divider); overflow:hidden; min-width:80px; }
  .meter div { height:100%; background:var(--ok); } .meter.low div { background:var(--crit); } .meter.mid div { background:var(--warn); }
  .spark { display:flex; align-items:flex-end; gap:4px; height:70px; margin-top:8px; }
  .spark div { flex:1; max-width:28px; background:var(--hm-primary); border-radius:3px 3px 0 0; min-height:3px; }
  .reportbox { white-space:pre-wrap; background:var(--secondary-background-color,#f5f5f5); border-radius:8px; padding:12px; }
  .form { display:flex; gap:12px; flex-wrap:wrap; align-items:flex-end; }
  .form label { display:flex; flex-direction:column; gap:4px; font-size:13px; color:var(--secondary-text-color,#727272); }
  .tiles { display:grid; gap:12px; grid-template-columns:repeat(auto-fill,minmax(170px,1fr)); }
  .room { background:var(--card-background-color,#fff); border-radius:12px; padding:12px; border:2px solid var(--hm-divider);
    box-shadow:0 1px 3px rgba(0,0,0,.15); min-height:74px; }
  .room.lit { border-color:#f5b400; box-shadow:0 0 18px rgba(245,180,0,.55); }
  .room.bad { border-color:var(--crit); }
  .room h3 { margin:0 0 4px; font-size:15px; font-weight:500; }
  .room .live { font-size:13px; color:var(--secondary-text-color,#727272); line-height:1.5; }
  .room .live b { color:var(--crit); font-weight:500; } .room .live i { color:#b07d00; font-style:normal; font-weight:500; }
  .canvas { position:relative; border-radius:12px; overflow:hidden; background:var(--card-background-color,#fff);
    touch-action:none; user-select:none; }
  .canvas img { display:block; width:100%; pointer-events:none; }
  .canvas .room { position:absolute; transform:translate(-50%,-50%); min-height:0; padding:6px 10px; max-width:150px;
    background:color-mix(in srgb, var(--card-background-color,#fff) 88%, transparent); }
  .canvas.edit .room { cursor:move; border-style:dashed; }
  .notice { background:var(--hm-primary); color:var(--text-primary-color,#fff); border-radius:10px; padding:10px 14px;
    margin-bottom:16px; display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
  .notice span { flex:1; } .notice button { background:none; border:1px solid currentColor; color:inherit;
    border-radius:14px; padding:4px 12px; cursor:pointer; font:inherit; }
  .bar { position:sticky; top:56px; z-index:1; display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
  select, input[type=text] { font:inherit; padding:8px; border-radius:8px; border:1px solid var(--hm-divider);
    background:var(--card-background-color,#fff); color:inherit; max-width:100%; }
  .board { display:grid; gap:12px; grid-template-columns:repeat(auto-fill,minmax(230px,1fr)); align-items:start; }
  .col { background:var(--secondary-background-color,#f0f0f0); border-radius:12px; padding:10px; min-height:70px;
    border:2px dashed transparent; }
  .col.over { border-color:var(--hm-primary); }
  .col.homeless { background:color-mix(in srgb, var(--warn) 18%, var(--card-background-color,#fff)); }
  .col h3 { margin:0 0 2px; font-size:15px; font-weight:500; display:flex; justify-content:space-between; gap:8px; }
  .col select { font-size:12px; padding:3px; margin:2px 0 8px; width:100%; }
  .thing { background:var(--card-background-color,#fff); border-radius:8px; padding:8px; margin:6px 0; display:flex;
    gap:8px; align-items:flex-start; cursor:grab; box-shadow:0 1px 2px rgba(0,0,0,.15); }
  .thing.sel { outline:2px solid var(--hm-primary); }
  .thing input { margin-top:3px; }
  .thing .n { font-size:14px; overflow-wrap:anywhere; }
  .namerow { display:grid; grid-template-columns:1fr 1.2fr auto; gap:10px; align-items:center; padding:10px 0;
    border-bottom:1px solid var(--hm-divider); }
  .namerow input { width:100%; box-sizing:border-box; }
  .entry { border-bottom:1px solid var(--hm-divider); padding:12px 0; }
  .entry.undone { opacity:.6; }
  .entry .top { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
  .entry .top strong { flex:1; font-weight:500; }
  @media (max-width:600px) { .namerow { grid-template-columns:1fr; } }
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
    this._rooms = null;
    this._names = null;
    this._log = null;
    this._sel = new Set();
    this._roomFilter = "";
    this._notice = null;
    this._explained = {};
    this._report = null;
    this._plan = null;
    this._floor = null;
    this._planEdit = false;
    for (const type of ["pointerdown", "pointermove", "pointerup"]) {
      this.shadowRoot.addEventListener(type, (ev) => this._onPointer(ev));
    }
    this.shadowRoot.addEventListener("change", (ev) => this._onChange(ev));
    for (const type of ["dragstart", "dragover", "dragleave", "drop"]) {
      this.shadowRoot.addEventListener(type, (ev) => this._onDrag(ev));
    }
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
    else if (this._tab === "plan" && !this._liveTimer) {
      this._liveTimer = setTimeout(() => {
        this._liveTimer = null;
        this._updatePlanLive();
      }, 1000);
    }
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
    if (refresh) {
      this._rooms = this._names = this._log = this._report = this._plan = null;
      this._explained = {};
    }
    this._render();
    this._loadTab();
  }

  async _loadTab() {
    const loaders = {
      blast: () => this._loadTargets(),
      rooms: async () => {
        if (!this._rooms) this._rooms = await this._ws({ type: "ha_manager/rooms" });
      },
      names: async () => {
        if (!this._names) this._names = await this._ws({ type: "ha_manager/names" });
      },
      report: async () => {
        if (!this._report) this._report = await this._ws({ type: "ha_manager/report" });
      },
      plan: async () => {
        if (!this._plan) this._plan = await this._ws({ type: "ha_manager/plan" });
      },
      log: async () => {
        if (!this._log) this._log = await this._ws({ type: "ha_manager/changes" });
      },
    };
    const loader = loaders[this._tab];
    if (!loader) return;
    try {
      await loader();
    } catch (err) {
      this._error = (err && err.message) || "Could not load that.";
    }
    if (this._tab !== "blast") this._render();
  }

  async _explain(id, ai) {
    const previous = this._explained[id];
    this._explained[id] = { ...(previous || {}), loading: true };
    this._render();
    try {
      this._explained[id] = await this._ws({ type: "ha_manager/explain", entity_id: id, ai });
    } catch (err) {
      this._explained[id] = { summary: (err && err.message) || "Could not explain that.", then: [], when: [], only_if: [] };
    }
    this._render();
  }

  async _saveReport() {
    const get = (id) => this.shadowRoot.getElementById(id);
    try {
      this._report = await this._ws({
        type: "ha_manager/report/settings",
        enabled: get("report-enabled").checked,
        weekday: Number(get("report-weekday").value),
        hour: Number(get("report-hour").value),
        notify: get("report-notify").value || null,
      });
      this._notice = { text: "Report settings saved." };
    } catch (err) {
      this._error = (err && err.message) || "Could not save that.";
    }
    this._render();
  }

  /* ---------- floor plan ---------- */

  _floorKey() {
    return this._floor || "_none";
  }

  _planAreas() {
    const key = this._floor || null;
    return this._plan.areas.filter((a) => (a.floor_id || null) === key);
  }

  _roomLive(area) {
    const states = this._hass ? this._hass.states : {};
    const state = (id) => (states[id] ? states[id].state : undefined);
    const on = area.lights.filter((id) => state(id) === "on").length;
    const temps = area.temps.map((id) => parseFloat(state(id))).filter((n) => !Number.isNaN(n));
    const motion = area.motion.some((id) => state(id) === "on");
    const alarm = area.safety.some((id) => state(id) === "on");
    const offline = area.all.filter((id) => state(id) === "unavailable").length;
    const bits = [];
    if (alarm) bits.push("<b>ALARM</b>");
    if (area.lights.length) bits.push(on ? `<i>${on} light${on === 1 ? "" : "s"} on</i>` : "Lights off");
    if (temps.length) bits.push(`${(temps.reduce((a, b) => a + b, 0) / temps.length).toFixed(1)}°`);
    if (motion) bits.push("Motion");
    if (offline) bits.push(`<b>${offline} offline</b>`);
    if (!bits.length) bits.push(area.all.length ? "Quiet" : "Nothing here yet");
    return { html: bits.join(" · "), lit: on > 0, bad: alarm || offline > 0 };
  }

  _updatePlanLive() {
    if (this._tab !== "plan" || !this._plan) return;
    for (const el of this.shadowRoot.querySelectorAll(".room[data-area]")) {
      const area = this._plan.areas.find((a) => a.id === el.dataset.area);
      if (!area) continue;
      const live = this._roomLive(area);
      el.classList.toggle("lit", live.lit);
      el.classList.toggle("bad", live.bad);
      const box = el.querySelector(".live");
      if (box && box.innerHTML !== live.html) box.innerHTML = live.html;
    }
  }

  _positions() {
    const layout = (this._plan.layouts || {})[this._floorKey()] || {};
    const saved = layout.positions || {};
    const areas = this._planAreas();
    const cols = Math.ceil(Math.sqrt(areas.length || 1));
    const rows = Math.ceil(areas.length / cols) || 1;
    const result = {};
    areas.forEach((area, index) => {
      result[area.id] = saved[area.id] || [
        ((index % cols) + 0.5) * (100 / cols),
        (Math.floor(index / cols) + 0.5) * (100 / rows),
      ];
    });
    return result;
  }

  _onPointer(ev) {
    if (this._tab !== "plan" || !this._planEdit) return;
    if (ev.type === "pointerdown") {
      const room = ev.target.closest && ev.target.closest(".canvas .room");
      if (!room) return;
      this._dragRoom = room;
      room.setPointerCapture(ev.pointerId);
      ev.preventDefault();
    } else if (ev.type === "pointermove" && this._dragRoom) {
      const box = this.shadowRoot.querySelector(".canvas").getBoundingClientRect();
      const x = Math.min(100, Math.max(0, ((ev.clientX - box.left) / box.width) * 100));
      const y = Math.min(100, Math.max(0, ((ev.clientY - box.top) / box.height) * 100));
      this._dragRoom.style.left = `${x}%`;
      this._dragRoom.style.top = `${y}%`;
      this._dragRoom.dataset.x = x.toFixed(2);
      this._dragRoom.dataset.y = y.toFixed(2);
    } else if (ev.type === "pointerup") {
      this._dragRoom = null;
    }
  }

  async _savePlan() {
    const positions = {};
    for (const el of this.shadowRoot.querySelectorAll(".canvas .room")) {
      positions[el.dataset.area] = [Number(el.dataset.x), Number(el.dataset.y)];
    }
    try {
      this._plan.layouts = await this._ws({ type: "ha_manager/plan/save", floor: this._floorKey(), positions });
      this._planEdit = false;
      this._notice = { text: "Layout saved." };
    } catch (err) {
      this._error = (err && err.message) || "Could not save the layout.";
    }
    this._render();
  }

  async _uploadPlan(file) {
    try {
      const url = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });
      const img = await new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = reject;
        image.src = url;
      });
      const scale = Math.min(1, 1600 / Math.max(img.width, img.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(img.width * scale);
      canvas.height = Math.round(img.height * scale);
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#fff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      const image = canvas.toDataURL("image/jpeg", 0.8);
      this._plan.layouts = await this._ws({ type: "ha_manager/plan/save", floor: this._floorKey(), image });
      this._planEdit = true;
      this._notice = { text: "Picture added. Drag each room onto its spot, then press Save layout." };
    } catch (err) {
      this._error = (err && err.message) || "That picture could not be used.";
    }
    this._render();
  }

  _planTab() {
    const p = this._plan;
    if (!p) return `<div class="card">Loading the floor plan…</div>`;
    if (!p.areas.length) {
      return `<div class="card">No rooms yet. Create some under
        <a data-act="nav" href="/config/areas/dashboard">Settings, Areas</a> and they will appear here.</div>`;
    }
    const floors = p.floors.map((f) => [f.id, f.name]);
    if (p.areas.some((a) => !a.floor_id)) floors.push(["", floors.length ? "No floor" : "All rooms"]);
    if (this._floor === null || !floors.some(([id]) => id === this._floor)) this._floor = floors[0][0];
    const layout = (p.layouts || {})[this._floorKey()] || {};
    const areas = this._planAreas();
    const tile = (area, style, data) => {
      const live = this._roomLive(area);
      return `<div class="room ${live.lit ? "lit" : ""} ${live.bad ? "bad" : ""}" data-area="${esc(area.id)}" ${style} ${data}>
        <h3>${esc(area.name)}</h3><div class="live">${live.html}</div></div>`;
    };
    let html = `<div class="card bar">
      ${floors.length > 1 ? floors.map(([id, name]) => `<button class="btn ${id === this._floor ? "solid" : ""}" data-act="floor" data-id="${esc(id)}">${esc(name)}</button>`).join("") : ""}
      <span style="flex:1"></span>
      <input id="plan-file" type="file" accept="image/*" hidden>
      ${
        layout.image
          ? this._planEdit
            ? `<button class="btn solid" data-act="plan-save">Save layout</button>`
            : `<button class="btn" data-act="plan-edit">Arrange rooms</button>`
          : ""
      }
      <button class="btn" data-act="plan-upload">${layout.image ? "Change picture" : "Add a picture of this floor"}</button>
      ${layout.image ? `<button class="btn" data-act="plan-remove">Remove picture</button>` : ""}
    </div>`;
    if (layout.image) {
      const positions = this._positions();
      html += `<div class="canvas ${this._planEdit ? "edit" : ""}"><img src="${esc(layout.image)}" alt="Floor plan">
        ${areas
          .map((a) => {
            const [x, y] = positions[a.id];
            return tile(a, `style="left:${x}%;top:${y}%"`, `data-x="${x}" data-y="${y}"`);
          })
          .join("")}</div>`;
      if (this._planEdit) html += `<p class="muted">Drag each room label onto its place in the picture, then press Save layout.</p>`;
    } else {
      html += `<div class="tiles">${areas.map((a) => tile(a, "", "")).join("")}</div>
        <p class="muted">Rooms glow when a light is on and go red when something in them is offline or a safety sensor is
        detecting something. Add a photo or drawing of the floor to place the rooms where they really are.</p>`;
    }
    return html;
  }

  _batteriesTab() {
    const list = this._data.batteries || [];
    let html = `<div class="card"><strong>Battery forecast.</strong>
      <div class="muted">Worked out from how fast each battery has been dropping since it was last changed.
      Batteries often fall off a cliff at the end, so treat “days left” as a guide and swap early on anything
      safety-related. A forecast needs about a week of readings.</div></div>`;
    if (!list.length) return html + `<div class="card">No battery sensors found.</div>`;
    const rows = list.map((b) => {
      const level = b.level === null || b.level === undefined ? null : Math.round(b.level);
      let outlook;
      if (b.status === "forecast") {
        const date = new Date(b.empty_on).toLocaleDateString(undefined, { day: "numeric", month: "short" });
        outlook = `<strong>About ${b.days_left} day${b.days_left === 1 ? "" : "s"}</strong>
          <div class="muted">around ${date} · losing ${b.rate_per_day}% a day · ${b.confidence === "good" ? "good estimate" : "rough estimate"}</div>`;
      } else if (b.status === "steady") {
        outlook = `Holding steady<div class="muted">no drop seen in ${b.days_of_data} days</div>`;
      } else {
        outlook = `<span class="muted">Still learning (${b.days_of_data} day${b.days_of_data === 1 ? "" : "s"} of readings)</span>`;
      }
      return `<tr>
        <td><a href="#" data-act="more-info" data-id="${esc(b.entity_id)}">${esc(b.name)}</a>
          <div class="muted">${esc(b.area || "No room")}${b.safety ? " · life safety" : ""}${b.offline ? " · offline" : ""}</div></td>
        <td>${level === null ? "–" : `${level}%<div class="meter ${level <= 15 ? "low" : level <= 35 ? "mid" : ""}"><div style="width:${level}%"></div></div>`}</td>
        <td>${outlook}</td></tr>`;
    });
    return html + `<div class="card"><table><thead><tr><th>Device</th><th>Now</th><th>Outlook</th></tr></thead>
      <tbody>${rows.join("")}</tbody></table></div>`;
  }

  _reportTab() {
    const r = this._report;
    if (!r) return `<div class="card">Loading the report…</div>`;
    const s = r.settings;
    const hours = Array.from({ length: 24 }, (_, h) => `<option value="${h}" ${h === s.hour ? "selected" : ""}>${String(h).padStart(2, "0")}:00</option>`).join("");
    const days = WEEKDAYS.map((d, i) => `<option value="${i}" ${i === s.weekday ? "selected" : ""}>${d}</option>`).join("");
    const targets = r.notify_services.map((n) => `<option value="${esc(n)}" ${n === s.notify ? "selected" : ""}>${esc(n.replace("mobile_app_", "").replace(/_/g, " "))}</option>`).join("");
    let html = `<div class="card"><strong>Weekly report.</strong>
      <div class="muted">A short summary once a week: the score, what is new, what got fixed, batteries to buy and
      safety tests due. It always appears under Notifications in Home Assistant, and can go to your phone too.</div>
      <div class="form" style="margin-top:12px">
        <label><span><input type="checkbox" id="report-enabled" ${s.enabled ? "checked" : ""}> Send it every week</span></label>
        <label>Day<select id="report-weekday">${days}</select></label>
        <label>Time<select id="report-hour">${hours}</select></label>
        <label>Also send to<select id="report-notify"><option value="">Nowhere else</option>${targets}</select></label>
        <button class="btn solid" data-act="report-save">Save</button>
        <button class="btn" data-act="report-send">Send one now</button>
      </div></div>`;
    if (r.preview) {
      html += `<div class="card"><strong>If it were sent right now</strong>
        <div class="reportbox" style="margin-top:8px">${esc(r.preview.text)}</div></div>`;
    }
    if (r.history.length) {
      const bars = r.history
        .map((h) => `<div style="height:${Math.max(4, h.score)}%" title="${new Date(h.when).toLocaleDateString()}: ${h.score}"></div>`)
        .join("");
      html += `<div class="card"><strong>Score, week by week</strong><div class="spark">${bars}</div>
        <div class="muted">${r.history.length} week${r.history.length === 1 ? "" : "s"} so far. Latest: ${r.history[r.history.length - 1].score}.</div></div>`;
    } else {
      html += `<p class="muted">The week-by-week chart starts after the first scheduled report.</p>`;
    }
    return html;
  }

  /* Run something that changes Home Assistant, then refresh everything. */
  async _change(message, describe) {
    this._error = "";
    try {
      const result = await this._ws(message);
      if (result.rooms) this._rooms = result.rooms;
      else this._rooms = null;
      if (result.names) this._names = result.names;
      else this._names = null;
      this._log = null;
      this._targets = null;
      this._plan = null;
      const change = result.change;
      if (change && change.items && change.items.length) {
        this._notice = { text: describe ? describe(change) : change.summary + ".", id: change.id };
      } else if (change) {
        this._notice = { text: "Nothing needed changing." };
      }
      this._ws({ type: "ha_manager/scan" }).then((data) => {
        this._data = data;
      });
      return result;
    } catch (err) {
      this._error = (err && err.message) || "That did not work.";
      return null;
    } finally {
      this._render();
      this._loadTab();
    }
  }

  async _undo(id) {
    const result = await this._change({ type: "ha_manager/undo", change_id: id });
    if (!result) return;
    const skipped = result.skipped.length;
    this._notice = {
      text:
        `Undone: ${result.reverted} put back` +
        (skipped ? `, ${skipped} left alone because they had changed again or gone.` : "."),
    };
    this._render();
  }

  _move(keys, areaId) {
    const items = [...keys].map((key) => {
      const [type, ...rest] = key.split("|");
      return { type, id: rest.join("|") };
    });
    if (!items.length) return;
    this._sel.clear();
    this._change({ type: "ha_manager/move", items, area_id: areaId || null });
  }

  _onChange(ev) {
    const el = ev.target;
    const act = el.dataset && el.dataset.change;
    if (act === "select") {
      if (el.checked) this._sel.add(el.dataset.key);
      else this._sel.delete(el.dataset.key);
      this._render();
    } else if (act === "floor") {
      this._change({ type: "ha_manager/set_floor", area_id: el.dataset.id, floor_id: el.value || null });
    } else if (el.id === "plan-file" && el.files && el.files[0]) {
      this._uploadPlan(el.files[0]);
    } else if (act === "style") {
      this._ws({ type: "ha_manager/set_naming_style", style: el.value }).then((names) => {
        this._names = names;
        this._render();
      });
    }
  }

  _onDrag(ev) {
    if (this._tab !== "rooms") return;
    if (ev.type === "dragstart") {
      const card = ev.target.closest && ev.target.closest(".thing");
      if (!card) return;
      const key = card.dataset.key;
      this._dragging = this._sel.has(key) ? new Set(this._sel) : new Set([key]);
      ev.dataTransfer.effectAllowed = "move";
      ev.dataTransfer.setData("text/plain", key);
      return;
    }
    const col = ev.target.closest && ev.target.closest(".col");
    if (!col || !this._dragging) return;
    if (ev.type === "dragover") {
      ev.preventDefault();
      col.classList.add("over");
    } else if (ev.type === "dragleave") {
      if (!col.contains(ev.relatedTarget)) col.classList.remove("over");
    } else if (ev.type === "drop") {
      ev.preventDefault();
      const keys = this._dragging;
      this._dragging = null;
      this._move(keys, col.dataset.area);
    }
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
      this._notice = null;
      this._render();
      this._loadTab();
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
    } else if (act === "explain") {
      this._explain(el.dataset.id, false);
    } else if (act === "explain-ai") {
      this._explain(el.dataset.id, true);
    } else if (act === "explain-hide") {
      delete this._explained[el.dataset.id];
      this._render();
    } else if (act === "report-save") {
      this._saveReport();
    } else if (act === "report-send") {
      this._ws({ type: "ha_manager/report/send" }).then((report) => {
        this._report = report;
        this._notice = { text: "Report sent. Look for it under Notifications in the sidebar." };
        this._render();
      });
    } else if (act === "floor") {
      this._floor = el.dataset.id;
      this._planEdit = false;
      this._render();
    } else if (act === "plan-edit") {
      this._planEdit = true;
      this._render();
    } else if (act === "plan-save") {
      this._savePlan();
    } else if (act === "plan-upload") {
      this.shadowRoot.getElementById("plan-file").click();
    } else if (act === "plan-remove") {
      if (window.confirm("Remove this floor's picture? The rooms go back to simple tiles.")) {
        this._ws({ type: "ha_manager/plan/save", floor: this._floorKey(), image: null }).then((layouts) => {
          this._plan.layouts = layouts;
          this._planEdit = false;
          this._render();
        });
      }
    } else if (act === "undo") {
      this._undo(el.dataset.id);
    } else if (act === "dismiss") {
      this._notice = null;
      this._render();
    } else if (act === "move-selected") {
      const select = this.shadowRoot.getElementById("move-to");
      if (select && select.value !== "") this._move(this._sel, select.value === "__none__" ? null : select.value);
    } else if (act === "clear-selection") {
      this._sel.clear();
      this._render();
    } else if (act === "rename") {
      const input = this.shadowRoot.querySelector(`input[data-name-for="${CSS.escape(el.dataset.key)}"]`);
      const name = input ? input.value.trim() : "";
      if (name) {
        this._change({
          type: "ha_manager/rename",
          items: [{ type: el.dataset.type, id: el.dataset.id, name }],
        });
      }
    } else if (act === "rename-all") {
      const items = (this._names ? this._names.issues : [])
        .filter((i) => i.suggestion)
        .map((i) => ({ type: i.type, id: i.id, name: i.suggestion }));
      if (items.length && window.confirm(`Rename ${items.length} things to the suggested names? You can undo this from the Log tab.`)) {
        this._change({ type: "ha_manager/rename", items });
      }
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
    if (ev.target.id === "room-filter") {
      this._roomFilter = ev.target.value;
      const words = this._roomFilter.toLowerCase().split(/\s+/).filter(Boolean);
      for (const card of this.shadowRoot.querySelectorAll(".thing")) {
        const text = card.dataset.text;
        card.style.display = words.every((w) => text.includes(w)) ? "" : "none";
      }
      return;
    }
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
    if (this._notice) {
      body += `<div class="notice"><span>${esc(this._notice.text)}</span>
        ${this._notice.id ? `<button data-act="undo" data-id="${esc(this._notice.id)}">Undo</button>` : ""}
        <button data-act="dismiss">OK</button></div>`;
    }
    if (!this._data) {
      body += `<div class="card">${this._busy ? "Scanning your setup…" : "No scan yet."}</div>`;
    } else if (this._tab === "overview") body += this._overview();
    else if (this._tab === "safety") body += this._safety();
    else if (this._tab === "activity") body += this._activity();
    else if (this._tab === "rooms") body += this._roomsTab();
    else if (this._tab === "batteries") body += this._batteriesTab();
    else if (this._tab === "report") body += this._reportTab();
    else if (this._tab === "plan") body += this._planTab();
    else if (this._tab === "names") body += this._namesTab();
    else if (this._tab === "log") body += this._logTab();
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

  _explainBox(id) {
    const e = this._explained[id];
    if (!e) return `<button class="linkbtn" data-act="explain" data-id="${esc(id)}">What does this do?</button>`;
    if (e.loading && !e.summary) return `<div class="explain muted">Reading it…</div>`;
    const list = (title, lines) =>
      lines && lines.length ? `<p class="muted">${title}</p><pre>${lines.map((l) => esc(l.replace(/^(\s*)/, "$1• "))).join("\n")}</pre>` : "";
    let ai = "";
    if (e.ai_text) ai = `<p class="muted">In the AI’s words</p><p>${esc(e.ai_text)}</p>`;
    else if (e.loading) ai = `<p class="muted">Asking the AI…</p>`;
    else if (e.ai_error) ai = `<p class="error">The AI could not answer: ${esc(e.ai_error)}</p>`;
    const askAi =
      e.ai_available && !e.ai_text && !e.loading
        ? `<button class="linkbtn" data-act="explain-ai" data-id="${esc(id)}">Ask Home Assistant’s AI for a friendlier version</button> · `
        : "";
    return `<div class="explain"><p><strong>${esc(e.summary)}</strong></p>
      ${list("Starts when any of these happen", e.when && e.when.length > 1 ? e.when : [])}
      ${list("Steps", e.then && (e.then.length > 3 || e.note || e.then.some((l) => l.startsWith(" "))) ? e.then : [])}
      ${e.note ? `<p class="muted">${esc(e.note)}</p>` : ""}${ai}
      <p>${askAi}<button class="linkbtn" data-act="explain-hide" data-id="${esc(id)}">Hide</button></p></div>`;
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
        <td>${name}<div class="muted">${esc(r.kind)}${r.note ? " · " + esc(r.note) : ""}</div>
          ${this._explainBox(r.entity_id)}</td>
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

  _roomsTab() {
    const r = this._rooms;
    if (!r) return `<div class="card">Loading your rooms…</div>`;
    const floorOptions = (current) =>
      `<option value="">No floor</option>` +
      r.floors
        .map((f) => `<option value="${esc(f.id)}" ${f.id === current ? "selected" : ""}>${esc(f.name)}</option>`)
        .join("");
    const card = (item) => {
      const key = `${item.type}|${item.id}`;
      const selected = this._sel.has(key);
      return `<div class="thing ${selected ? "sel" : ""}" draggable="true" data-key="${esc(key)}"
          data-text="${esc((item.name + " " + item.detail).toLowerCase())}">
        <input type="checkbox" data-change="select" data-key="${esc(key)}" ${selected ? "checked" : ""}
          aria-label="Select ${esc(item.name)}">
        <div><div class="n">${esc(item.name)}</div><div class="muted">${esc(item.detail)}</div></div></div>`;
    };
    const column = (areaId, name, floorId) => {
      const items = r.items.filter((i) => (i.area_id || "") === areaId);
      const floor = areaId
        ? `<select data-change="floor" data-id="${esc(areaId)}" aria-label="Floor for ${esc(name)}">${floorOptions(floorId)}</select>`
        : "";
      return `<div class="col ${areaId ? "" : "homeless"}" data-area="${esc(areaId)}">
        <h3><span>${esc(name)}</span><span class="muted">${items.length}</span></h3>${floor}
        ${items.map(card).join("")}</div>`;
    };
    const roomOptions = r.areas.map((a) => `<option value="${esc(a.id)}">${esc(a.name)}</option>`).join("");
    let html = `<div class="card bar">
      <input id="room-filter" type="text" placeholder="Filter by name" value="${esc(this._roomFilter)}" style="flex:1;min-width:160px">
      ${
        this._sel.size
          ? `<strong>${this._sel.size} selected</strong>
        <select id="move-to" aria-label="Move to"><option value="">Move to…</option>${roomOptions}
          <option value="__none__">No room</option></select>
        <button class="btn solid" data-act="move-selected">Move</button>
        <button class="btn" data-act="clear-selection">Clear</button>`
          : `<span class="muted">Drag a card to another room, or tick several and move them together.</span>`
      }</div>`;
    const homeless = r.items.filter((i) => !i.area_id).length;
    if (homeless || !r.areas.length) {
      html += `<h2>Not in a room <small>${homeless} to place</small></h2><div class="board">${column("", "No room", null)}</div>`;
    }
    const groups = r.floors.map((f) => [f.id, f.name]);
    groups.push([null, r.floors.length ? "Rooms with no floor" : "Rooms"]);
    for (const [floorId, floorName] of groups) {
      const areas = r.areas.filter((a) => (a.floor_id || null) === floorId);
      if (!areas.length) continue;
      html += `<h2>${esc(floorName)} <small>${areas.length} rooms</small></h2>
        <div class="board">${areas.map((a) => column(a.id, a.name, a.floor_id)).join("")}</div>`;
    }
    if (!homeless && r.areas.length) {
      html += `<h2>Not in a room</h2><div class="board">${column("", "No room (drop here to remove)", null)}</div>`;
    }
    html += `<p class="muted">Rooms and floors themselves are created in Home Assistant under
      <a data-act="nav" href="/config/areas/dashboard">Settings, Areas</a>. Every move here is recorded on the Log tab and can be undone.</p>`;
    return html;
  }

  _namesTab() {
    const n = this._names;
    if (!n) return `<div class="card">Checking your names…</div>`;
    const withSuggestion = n.issues.filter((i) => i.suggestion).length;
    let html = `<div class="card"><strong>Which naming style do you want?</strong>
      <p><select data-change="style" aria-label="Naming style">
        <option value="room_first" ${n.style === "room_first" ? "selected" : ""}>Room first, e.g. “Kitchen Ceiling Light”</option>
        <option value="no_room" ${n.style === "no_room" ? "selected" : ""}>No room in the name, e.g. “Ceiling Light”</option>
      </select></p>
      <div class="muted">Only the friendly name you see on screen is changed. The entity ID behind it stays the same,
      so automations, scripts and dashboards keep working. Every rename is recorded on the Log tab and can be undone.</div>
      ${
        withSuggestion
          ? `<div class="actions"><button class="btn solid" data-act="rename-all">Apply all ${withSuggestion} suggestions</button></div>`
          : ""
      }</div>`;
    if (!n.issues.length) return html + `<div class="card">Every name fits. Nothing to do.</div>`;
    const rows = n.issues.map((i) => {
      const key = `${i.type}|${i.id}`;
      return `<div class="namerow">
        <div><div>${esc(i.name)}</div>
          <div class="muted">${esc(i.area || "No room")} · ${i.type === "device" ? "device" : esc(i.id)}</div></div>
        <div><span class="chip tidy">${NAME_PROBLEMS[i.problem]}</span> <span class="muted">${esc(i.reason)}</span>
          <input type="text" data-name-for="${esc(key)}" value="${esc(i.suggestion || i.name)}" aria-label="New name for ${esc(i.name)}"></div>
        <button class="btn" data-act="rename" data-key="${esc(key)}" data-type="${i.type}" data-id="${esc(i.id)}">Rename</button>
      </div>`;
    });
    return html + `<div class="card">${rows.join("")}</div>`;
  }

  _logTab() {
    const log = this._log;
    if (!log) return `<div class="card">Loading the log…</div>`;
    let html = `<div class="card"><strong>Captain’s Log.</strong>
      <div class="muted">Every change HA Manager has made, newest first. Undo puts things back as they were,
      and leaves alone anything that has been changed again since.</div></div>`;
    if (!log.length) return html + `<div class="card">No changes yet. Nothing has been touched.</div>`;
    const entries = log.map((e) => {
      const items = e.items
        .map((i) => `<li>${esc(i.label)} <span class="muted">· ${esc(i.before_text)} → ${esc(i.after_text)}</span></li>`)
        .join("");
      const skipped = (e.undo_skipped || [])
        .map((s) => `<li>${esc(s.label)} <span class="muted">· not put back: ${esc(s.reason)}</span></li>`)
        .join("");
      return `<div class="entry ${e.undone ? "undone" : ""}">
        <div class="top"><strong>${esc(e.summary)}</strong>
          <span class="muted">${ago(e.when)}${e.user ? " · " + esc(e.user) : ""}</span>
          ${
            e.undone
              ? `<span class="chip off">Undone ${ago(e.undone)}</span>`
              : `<button class="btn" data-act="undo" data-id="${esc(e.id)}">Undo</button>`
          }</div>
        <details><summary class="muted">${e.items.length} ${e.items.length === 1 ? "change" : "changes"}</summary>
          <ul class="items">${items}${skipped}</ul></details></div>`;
    });
    return html + `<div class="card">${entries.join("")}</div>`;
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
