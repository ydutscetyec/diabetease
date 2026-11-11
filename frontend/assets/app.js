/* DiabetEASE frontend.
   Structure: Settings → Api → Store → views (each a render function) → Chat.
   No framework and no build step: the whole app is three files served statically
   by the backend, which keeps the deployment to one service. */
(function () {
  "use strict";

  /* =================================================== settings (local) */
  var SKEY = "diabetease.settings.v1";
  var Settings = {
    data: { theme: "auto", density: "normal", motion: false, api: "", municipality: "",
            tileProvider: "esri-street", tileUrl: "", tileAttribution: "" },
    load: function () {
      try {
        var raw = localStorage.getItem(SKEY);
        if (raw) Object.assign(this.data, JSON.parse(raw));
      } catch (e) { /* storage blocked: defaults are fine */ }
      this.apply();
    },
    save: function () {
      try { localStorage.setItem(SKEY, JSON.stringify(this.data)); } catch (e) { }
      this.apply();
    },
    apply: function () {
      var r = document.documentElement;
      r.setAttribute("data-theme", this.data.theme);
      r.setAttribute("data-density", this.data.density);
      r.setAttribute("data-motion", this.data.motion ? "off" : "on");
    }
  };

  /* ============================================================== api */
  var Api = {
    base: function () {
      if (Settings.data.api) return Settings.data.api.replace(/\/$/, "");
      return location.protocol === "file:" ? "http://127.0.0.1:8000" : "";
    },
    call: function (path, options, timeoutMs) {
      options = options || {};
      var ctrl = new AbortController();
      var timer = setTimeout(function () { ctrl.abort(); }, timeoutMs || 12000);
      options.signal = ctrl.signal;
      options.headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
      return fetch(Api.base() + path, options).then(function (res) {
        clearTimeout(timer);
        return res.json().catch(function () { return {}; }).then(function (body) {
          if (!res.ok) {
            var e = new Error(body.detail || "Request failed");
            e.status = res.status; e.body = body;
            throw e;
          }
          return body;
        });
      }, function (err) { clearTimeout(timer); throw err; });
    },
    describe: function (err) {
      if (err && err.name === "AbortError") return "The server took too long to answer. Check that the backend is running, then try again.";
      if (err && err.status === 422) {
        var f = (err.body && err.body.fields) || [];
        return f.length
          ? "The server rejected: " + f.map(function (x) { return x.field + " (" + x.message + ")"; }).join("; ")
          : "The server rejected one of the values.";
      }
      if (err && err.status === 429) return "Too many requests. Wait a minute and try again.";
      if (err && err.status === 401) return "Not signed in, or the session expired. Sign in again.";
      if (err && err.status === 503) return "Accounts are not enabled on this server. Set SECRET_KEY in backend/.env and restart it.";
      if (err && err.status === 404) return "That endpoint does not exist on the running server. The backend may be an older version than this page.";
      if (err && err.status) return "The server returned an error (" + err.status + ").";
      return "Could not reach the DiabetEASE server. Confirm it is running on the expected address.";
    }
  };

  /* ============================================================ store */
  var Auth = {
    token: null, username: null, role: null,
    load: function () {
      try {
        var raw = sessionStorage.getItem("diabetease.session");
        if (raw) { var d = JSON.parse(raw); this.token = d.t; this.username = d.u; this.role = d.r; }
      } catch (e) { }
    },
    set: function (token, username, role) {
      this.token = token; this.username = username; this.role = role;
      // sessionStorage, not localStorage: the token dies with the tab.
      try { sessionStorage.setItem("diabetease.session", JSON.stringify({ t: token, u: username, r: role })); } catch (e) { }
      applyRole();
    },
    clear: function () {
      this.token = this.username = this.role = null;
      try { sessionStorage.removeItem("diabetease.session"); } catch (e) { }
      applyRole();
    },
    headers: function () { return this.token ? { Authorization: "Bearer " + this.token } : {}; },
    isStaff: function () { return this.role === "researcher" || this.role === "admin"; }
  };

  var Store = {
    lastResult: null,      // the real API response, never a reconstruction
    lastInputs: null,
    history: [],           // session only, in memory
    municipalities: [],
    health: null
  };

  /* ========================================================= helpers */
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function card(titleText) {
    var c = el("div", "card");
    if (titleText) { var h = el("div", "card-head"); h.appendChild(el("h2", null, titleText)); c.appendChild(h); }
    return c;
  }
  function note(kind, titleText, bodyText) {
    var n = el("div", "note note-" + kind);
    if (titleText) n.appendChild(el("h3", null, titleText));
    if (bodyText) n.appendChild(el("p", null, bodyText));
    return n;
  }
  var EMPTY_ART = {
    // Small inline SVGs: nothing to download on a slow connection.
    clipboard: '<svg width="54" height="54" viewBox="0 0 48 48" fill="none" stroke="currentColor" '
      + 'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
      + '<rect x="11" y="8" width="26" height="33" rx="3"/><path d="M19 8V6a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v2"/>'
      + '<path d="M18 20h12M18 27h12M18 34h7"/></svg>',
    pin: '<svg width="54" height="54" viewBox="0 0 48 48" fill="none" stroke="currentColor" '
      + 'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
      + '<path d="M24 5c-6.6 0-12 5.2-12 11.7C12 25.3 24 43 24 43s12-17.7 12-26.3C36 10.2 30.6 5 24 5z"/>'
      + '<circle cx="24" cy="17" r="4.5"/></svg>',
    search: '<svg width="54" height="54" viewBox="0 0 48 48" fill="none" stroke="currentColor" '
      + 'stroke-width="2" stroke-linecap="round" aria-hidden="true">'
      + '<circle cx="21" cy="21" r="12"/><path d="M30 30l9 9"/></svg>',
    chart: '<svg width="54" height="54" viewBox="0 0 48 48" fill="none" stroke="currentColor" '
      + 'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
      + '<path d="M8 40V8"/><path d="M8 40h32"/><rect x="14" y="26" width="6" height="10"/>'
      + '<rect x="24" y="18" width="6" height="18"/><rect x="34" y="30" width="6" height="6"/></svg>'
  };

  function emptyState(head, body, art, action) {
    var e = el("div", "empty");
    if (art && EMPTY_ART[art]) {
      var ill = el("div");
      ill.style.color = "var(--line-strong)";
      ill.innerHTML = EMPTY_ART[art];
      e.appendChild(ill);
    }
    e.appendChild(el("h3", null, head));
    e.appendChild(el("p", null, body));
    if (action) {
      var row = el("div", "btnrow");
      row.style.marginTop = "4px";
      var a = el("a", "btn btn-primary btn-sm", action.label);
      a.href = action.href;
      row.appendChild(a);
      e.appendChild(row);
    }
    return e;
  }
  function stamp() {
    var d = new Date();
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  /* ========================================================= nav spec */
  var NAV = [
    {
      group: "Overview", items: [
        { id: "dashboard", label: "Dashboard", icon: "M3 11 12 3l9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" },
        { id: "guide", label: "User guide", icon: "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm-1-13h2v6h-2zm0 8h2v2h-2z" }
      ]
    },
    {
      group: "Assessment", items: [
        { id: "assess", label: "Risk assessment", icon: "M9 3h6v2h3v16H6V5h3zm0 8h6M9 15h6" },
        { id: "forecast", label: "Risk forecasting", icon: "M3 17l5-5 4 4 8-8M16 8h5v5" },
        { id: "parameters", label: "Health parameters", icon: "M3 12h4l3-8 4 16 3-8h4" }
      ]
    },
    {
      group: "Services", items: [
        { id: "centers", label: "Testing centre map", icon: "M12 2a7 7 0 0 0-7 7c0 5 7 13 7 13s7-8 7-13a7 7 0 0 0-7-7zm0 9.5A2.5 2.5 0 1 1 12 6.5a2.5 2.5 0 0 1 0 5z" },
        { id: "learn", label: "Educational resources", icon: "M4 5h7a2 2 0 0 1 2 2v12a2 2 0 0 0-2-2H4zM20 5h-7a2 2 0 0 0-2 2v12a2 2 0 0 1 2-2h7z" }
      ]
    },
    {
      group: "Records", items: [
        { id: "reports", label: "Reports and history", roles: ["patient", "researcher", "admin", "guest"], icon: "M6 2h9l5 5v15H6zM14 2v6h6M9 13h8M9 17h5" },
        { id: "research", label: "Research and evaluation", roles: ["researcher", "admin"], icon: "M5 20V10M10 20V4M15 20v-7M20 20V8" }
      ]
    },
    {
      group: "System", items: [
        { id: "account", label: "Account", icon: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0" },
        { id: "settings", label: "Settings and privacy", icon: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 1 1-4 0v-.1A1.6 1.6 0 0 0 7.5 19.4a1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.6 1.6 0 0 0 3 14.5a2 2 0 1 1 0-4h.1A1.6 1.6 0 0 0 4.6 7.5a1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 2.7 1.1 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0 1.1 2.7H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1.1z" }
      ]
    }
  ];
  var VIEW_IDS = ["dashboard", "guide", "assess", "results", "forecast", "parameters", "centers", "learn", "reports", "research", "account", "settings"];
  var CRUMBS = {
    dashboard: "Dashboard", guide: "User guide", assess: "Risk assessment", results: "Assessment result",
    forecast: "Risk forecasting", parameters: "Health parameters", centers: "Testing centre map",
    learn: "Educational resources", reports: "Reports and history",
    research: "Research and evaluation", account: "Account", settings: "Settings and privacy"
  };

function buildNav() {
  var host = $("railNav");
  NAV.forEach(function (g) {
    var box = el("div", "rail-group");
    box.appendChild(el("h4", null, g.group));
    g.items.forEach(function (it) {
      var a = document.createElement("a");
      a.href = "#" + it.id;
      a.dataset.nav = it.id;
      a.dataset.tip = it.label;
      a.innerHTML = '<span class="ico"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" ' +
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="' + it.icon + '"/></svg></span>';
      a.appendChild(el("span", "lbl", it.label));
      var candy = el("span", "navcandy");
      candy.setAttribute("aria-hidden", "true");
      candy.innerHTML = '<svg width="22" height="14" viewBox="0 0 60 36"><path d="M14 18 2 6v24z" fill="#E46B43"/>'
        + '<path d="M46 18 58 6v24z" fill="#E46B43"/><ellipse cx="30" cy="18" rx="17" ry="13" fill="#F91A10"/>'
        + '<path d="M18 9c6 3 6 15 0 18M26 6c6 4 6 20 0 24M34 6c6 4 6 20 0 24M42 9c6 3 6 15 0 18" '
        + 'stroke="#EDB195" stroke-width="3" fill="none"/><ellipse cx="24" cy="12" rx="5" ry="2.5" '
        + 'fill="#fff" opacity=".6"/></svg>';
      a.appendChild(candy);
      box.appendChild(a);
    });
    host.appendChild(box);
  });
}

  /* ================================================== role visibility */
  function applyRole() {
    var role = Auth.role || "guest";
    document.querySelectorAll("[data-nav]").forEach(function (a) {
      var spec = null;
      NAV.forEach(function (g) { g.items.forEach(function (i) { if (i.id === a.dataset.nav) spec = i; }); });
      var allowed = !spec || !spec.roles || spec.roles.indexOf(role) >= 0;
      a.hidden = !allowed;
    });
    var btn = $("authBtn");
    if (Auth.token) {
      btn.innerHTML = "";
      btn.appendChild(el("span", "rolebadge", Auth.role));
      btn.appendChild(document.createTextNode(" " + Auth.username));
    } else {
      btn.textContent = "Sign in";
    }
    $("signOutBtn").hidden = !Auth.token;
    $("deleteAccount").hidden = !Auth.token;
    $("adminPanel").hidden = Auth.role !== "admin";
    // A staff-only view must not stay open after a sign-out.
    var current = (location.hash || "#dashboard").replace(/^#/, "");
    if (current === "research" && !Auth.isStaff()) location.hash = "#dashboard";
    if (current === "research" || current === "account") { if (RENDER[current]) RENDER[current](); }
  }

  /* ========================================================== router */
  var RENDER = {};
  function show(id) {
    if (VIEW_IDS.indexOf(id) < 0) id = "dashboard";
    VIEW_IDS.forEach(function (v) {
      var n = $("v-" + v);
      if (n) n.classList.toggle("active", v === id);
    });
    document.querySelectorAll("[data-nav]").forEach(function (a) {
      if (a.dataset.nav === id) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    $("crumb").textContent = CRUMBS[id] || id;
    document.title = (CRUMBS[id] || "DiabetEASE") + " — DiabetEASE";
    closeRail();
    window.scrollTo(0, 0);
    if (RENDER[id]) RENDER[id]();
  }

  /* ===================================================== rail / shell */
  function openRail() {
    $("rail").classList.add("open");
    $("scrim").hidden = false; $("scrim").classList.add("show");
    $("burger").setAttribute("aria-expanded", "true");
  }
  function closeRail() {
    $("rail").classList.remove("open");
    $("scrim").classList.remove("show"); $("scrim").hidden = true;
    $("burger").setAttribute("aria-expanded", "false");
  }

  /* ======================================================= dashboard */
  function countUp(node, target) {
    // Short, and skipped entirely under reduced motion. A number that takes a
    // second to settle is charming once and irritating every time after.
    var reduced = document.documentElement.getAttribute("data-motion") === "off" ||
      (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    if (reduced || target <= 0 || target > 999) { node.textContent = String(target); return; }
    var start = performance.now(), dur = 420;
    (function frame(now) {
      var t = Math.min(1, (now - start) / dur);
      node.textContent = String(Math.round(target * (1 - Math.pow(1 - t, 3))));
      if (t < 1) requestAnimationFrame(frame);
    })(start);
  }

  var STAT_ICONS = {
    "--mint": '<path d="M3 12h4l2-6 4 12 2-6h6"/>',
    "--sky": '<path d="M4 20V9M10 20V4M16 20v-7M22 20H2"/>',
    "--lavender": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
    "--yellow": '<path d="M10.5 3h3a2 2 0 0 1 2 2v2h3a2 2 0 0 1 2 2v3M3 10.5V9a2 2 0 0 1 2-2h2"/><circle cx="12" cy="14" r="6"/>'
  };
  var STAT_TONES = { "--mint": "tone-mint", "--sky": "tone-blue",
                     "--lavender": "tone-peach", "--yellow": "tone-lav" };

  function statCard(key, value, note, token, small) {
    var s = el("div", "stat");
    var tile = el("span", "stat-tile " + (STAT_TONES[token] || "tone-mint"));
    tile.setAttribute("aria-hidden", "true");
    tile.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
      + 'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
      + (STAT_ICONS[token] || STAT_ICONS["--mint"]) + "</svg>";
    s.appendChild(tile);
    var body = el("div", "stat-body");
    body.appendChild(el("span", "k", key));
    var v = el("div", "v" + (small ? " sm" : ""));
    if (/^\d+$/.test(String(value))) {
      v.className += " statnum";
      v.textContent = "0";
      countUp(v, Number(value));
      s.classList.add("ready");
    } else {
      v.textContent = value;
    }
    body.appendChild(v);
    body.appendChild(el("span", "n", note));
    s.appendChild(body);
    return s;
  }

  RENDER.dashboard = function () {
    var today = $("todayLabel");
    if (today) {
      today.textContent = new Date().toLocaleDateString([],
        { weekday: "long", day: "numeric", month: "long" }).toUpperCase();
    }
    var host = $("dashStats");
    clear(host);
    host.appendChild(statCard("Model status", "Loading…", "", "--lavender", true));
    host.appendChild(statCard("Testing centres", "…", "", "--sky", true));
    host.appendChild(statCard("With a confirmed service", "…", "", "--mint", true));
    host.appendChild(statCard("Pharmacies", "…", "", "--yellow", true));

    Promise.all([
      Api.call("/health").catch(function () { return null; }),
      Api.call("/api/v1/facilities?limit=500").catch(function () { return null; })
    ]).then(function (r) {
      var h = r[0], f = r[1];
      Store.health = h;
      clear(host);
      var testing = 0, pharmacies = 0, confirmedTesting = 0;
      if (f) f.items.forEach(function (x) {
        if (isPharmacy(x)) { pharmacies++; return; }
        testing++;
        if (x.services.some(function (sv) { return sv.confirmed; })) confirmedTesting++;
      });
      host.appendChild(statCard("Model status",
        h ? (h.model === "unavailable" ? "Not trained" : h.model) : "Unknown",
        h && h.model === "unavailable" ? "no probability is produced" : "see research page",
        "--lavender", true));
      host.appendChild(statCard("Testing centres", f ? String(testing) : "—",
        f ? "hospitals, clinics, laboratories, health units" : "server unreachable", "--sky"));
      host.appendChild(statCard("With a confirmed service", f ? String(confirmedTesting) : "—",
        f ? (testing - confirmedTesting) + " still to confirm" : "server unreachable", "--mint"));
      host.appendChild(statCard("Pharmacies", f ? String(pharmacies) : "—",
        f ? "insulin availability to be confirmed by phone" : "server unreachable", "--yellow"));
    });

    renderDashAssessment();
    renderActivity();
    renderMuniChart();
  };

  function renderDashAssessment() {
    var host = $("dashAssess"); clear(host);
    var tag = $("dashAssessTag");
    if (!Store.lastResult) {
      tag.textContent = "None this session";
      tag.className = "tag";
      host.appendChild(emptyState("No assessment yet",
        "Complete the five-step check and the result appears here with its reasoning.",
        "clipboard"));
      var b = el("div", "btnrow");
      var a = el("a", "btn btn-primary btn-sm", "Start assessment"); a.href = "#assess";
      b.appendChild(a); host.appendChild(b);
      return;
    }
    var r = Store.lastResult;
    tag.textContent = r.tier.replace(/_/g, " ");
    tag.className = "tag " + (r.emergency ? "tag-bad" : (["urgent", "followup"].indexOf(r.tier) >= 0 ? "tag-warn" : "tag-ok"));
    host.appendChild(el("h3", null, r.headline));
    host.appendChild(el("p", null, r.explanation));
    var tags = el("div", "tags");
    tags.appendChild(el("span", "tag", "Source: rule check"));
    tags.appendChild(el("span", "tag", "Model: " + (r.model.available ? r.model.version : "not trained")));
    host.appendChild(tags);
    var row = el("div", "btnrow"); row.style.marginTop = "14px";
    var v = el("a", "btn btn-ghost btn-sm", "View full result"); v.href = "#results";
    row.appendChild(v);
    host.appendChild(row);
  }

  function renderActivity() {
    var host = $("dashActivity"); clear(host);
    if (!Store.history.length) {
      host.appendChild(emptyState("Nothing yet", "Anything you do in this tab appears here.", "chart"));
      return;
    }
    var list = el("div");
    Store.history.slice().reverse().slice(0, 6).forEach(function (h) {
      var row = el("div");
      row.style.cssText = "display:flex;gap:10px;align-items:center;padding:8px 0;border-bottom:1px solid var(--line)";
      var t = el("span", "tag " + h.tagClass, h.tier.replace(/_/g, " "));
      row.appendChild(t);
      var s = el("span", null, h.headline);
      s.style.cssText = "font-size:.85rem;flex:1;min-width:0";
      row.appendChild(s);
      var w = el("small", null, h.at);
      w.style.color = "var(--text-2)";
      row.appendChild(w);
      list.appendChild(row);
    });
    host.appendChild(list);
  }

  function renderMuniChart() {
    var host = $("dashMuniChart");
    host.innerHTML = '<div class="skel"></div><div class="skel"></div><div class="skel"></div>';
    Api.call("/api/v1/facilities?limit=500&status=verified").then(function (body) {
      var counts = {};
      Store.municipalities.forEach(function (m) { counts[m.name] = 0; });
      body.items.forEach(function (f) { counts[f.municipality] = (counts[f.municipality] || 0) + 1; });
      var items = Object.keys(counts).map(function (k) { return { label: k, value: counts[k] }; });
      if (!body.total) {
        clear(host);
        host.appendChild(emptyState("No facility records yet",
          "Records appear here once they are imported or added.", "chart",
          { label: "Open the map", href: "#centers" }));
        return;
      }
      window.Charts.bars(host, { id: "muni", label: "Verified facilities per municipality", items: items });
    }).catch(function (err) {
      clear(host);
      host.appendChild(note("warn", null, Api.describe(err)));
    });
  }

  /* ===================================================== range scale */
  /* Minimum / average / maximum scale. Cut-offs are ADA values:
       glucose < 54 and < 70 mg/dL  hypoglycaemia levels 2 and 1
       fasting 100-125             intermediate
       fasting >= 126, random >= 200, HbA1c >= 6.5   diabetes range
     HbA1c has NO recognised low cut-off, so that end is labelled
     "uncommon" and explicitly is not presented as a diagnosis. */
  var SCALES = {
    fasting: {
      label: "Fasting plasma glucose", unit: "mg/dL", min: 40, max: 220, dp: 0,
      bands: [
        { from: 40, to: 70, cls: "low", name: "Below normal" },
        { from: 70, to: 100, cls: "normal", name: "Normal" },
        { from: 100, to: 126, cls: "mid", name: "Intermediate" },
        { from: 126, to: 220, cls: "high", name: "Diabetes range" }
      ],
      ticks: [70, 100, 126],
      read: function (v) {
        if (v < 54) return ["low", "Clinically significant low (below 54 mg/dL)"];
        if (v < 70) return ["low", "Below normal (under 70 mg/dL)"];
        if (v < 100) return ["normal", "Normal fasting range (70–99 mg/dL)"];
        if (v < 126) return ["mid", "Intermediate range (100–125 mg/dL)"];
        return ["high", "At or above the diagnostic threshold (126 mg/dL)"];
      }
    },
    random: {
      label: "Random plasma glucose", unit: "mg/dL", min: 40, max: 320, dp: 0,
      bands: [
        { from: 40, to: 70, cls: "low", name: "Below normal" },
        { from: 70, to: 200, cls: "normal", name: "Typical" },
        { from: 200, to: 320, cls: "high", name: "Diabetes range" }
      ],
      ticks: [70, 200],
      note: "A random sample has no intermediate band; only the 200 mg/dL cut-off, with symptoms, is defined. Source: ADA Standards of Care 2026.",
      read: function (v) {
        if (v < 54) return ["low", "Clinically significant low (below 54 mg/dL)"];
        if (v < 70) return ["low", "Below normal (under 70 mg/dL)"];
        if (v < 200) return ["normal", "Below the diagnostic threshold"];
        return ["high", "At or above the diagnostic threshold (200 mg/dL)"];
      }
    },
    hba1c: {
      label: "HbA1c", unit: "%", min: 3, max: 10, dp: 1,
      bands: [
        { from: 3, to: 4, cls: "low", name: "Below typical" },
        { from: 4, to: 5.7, cls: "normal", name: "Normal" },
        { from: 5.7, to: 6.5, cls: "mid", name: "Intermediate" },
        { from: 6.5, to: 10, cls: "high", name: "Diabetes range" }
      ],
      ticks: [4, 5.7, 6.5],
      note: "There is no recognised low HbA1c category. Values under 4% are uncommon and "
        + "can reflect conditions affecting the blood test itself; ask a clinician.",
      read: function (v) {
        if (v < 4) return ["low", "Below the typical range — uncommon, not a diabetes category"];
        if (v < 5.7) return ["normal", "Normal range (below 5.7%)"];
        if (v < 6.5) return ["mid", "Intermediate range (5.7–6.4%)"];
        return ["high", "At or above the diagnostic threshold (6.5%)"];
      }
    }
  };

  function renderScale(host, spec, value) {
    if (!host) return;
    clear(host);
    var box = el("div", "rs");
    var tiers = el("div", "rs-tiers");
    ["Minimum · below normal", "Average · normal", "Maximum · above normal"].forEach(function (t) {
      tiers.appendChild(el("span", null, t));
    });
    box.appendChild(tiers);

    var span = spec.max - spec.min;
    var pct = function (v) { return ((Math.min(Math.max(v, spec.min), spec.max) - spec.min) / span) * 100; };
    var track = el("div", "rs-track");
    track.setAttribute("role", "img");
    spec.bands.forEach(function (b) {
      var band = el("div", "rs-band b-" + b.cls);
      band.style.width = ((b.to - b.from) / span * 100) + "%";
      band.title = b.name + ": " + b.from + "–" + b.to + " " + spec.unit;
      track.appendChild(band);
    });

    var hasValue = value !== null && value !== undefined && value !== "" && !isNaN(value);
    if (hasValue) {
      var mk = el("div", "rs-marker");
      mk.style.left = pct(Number(value)) + "%";
      track.appendChild(mk);
    }
    box.appendChild(track);

    var ticks = el("div", "rs-ticks");
    var tmin = el("span", "edge-l", String(spec.min)); tmin.style.left = "0%"; ticks.appendChild(tmin);
    spec.ticks.forEach(function (t) {
      var tk = el("span", null, String(t)); tk.style.left = pct(t) + "%"; ticks.appendChild(tk);
    });
    var tmax = el("span", "edge-r", spec.max + "+ " + spec.unit); tmax.style.left = "100%"; ticks.appendChild(tmax);
    box.appendChild(ticks);

    var legend = el("div", "rs-labels");
    spec.bands.forEach(function (b) {
      var item = el("span");
      var sw = el("i"); sw.className = "rs-band b-" + b.cls;
      item.appendChild(sw);
      item.appendChild(document.createTextNode(b.name));
      legend.appendChild(item);
    });
    box.appendChild(legend);

    if (hasValue) {
      var r = spec.read(Number(value));
      var read = el("div", "rs-read t-" + r[0], Number(value).toFixed(spec.dp) + " " + spec.unit + " — " + r[1]);
      box.appendChild(read);
      track.setAttribute("aria-label", spec.label + " " + value + " " + spec.unit + ": " + r[1]);
    } else {
      track.setAttribute("aria-label", spec.label + " reference scale");
      box.appendChild(el("div", "rs-note", "Enter a value to see where it falls."));
    }
    if (spec.note) box.appendChild(el("div", "rs-note", spec.note));
    host.appendChild(box);
  }

  /* ====================================================== parameters */
  RENDER.parameters = function () {
    var host = $("paramBody"); clear(host);
    var inputs = Store.lastInputs;

    if (!inputs) {
      var c = card();
      c.appendChild(emptyState("No parameters recorded this session",
        "Any laboratory values you enter are charted here against published reference ranges.", "chart",
        { label: "Start an assessment", href: "#assess" }));
      var b = el("div", "btnrow"); b.style.justifyContent = "center";
      var a = el("a", "btn btn-primary btn-sm", "Start assessment"); a.href = "#assess";
      b.appendChild(a); c.appendChild(b);
      host.appendChild(c);
      return;
    }

    host.appendChild(note("info", "Session values only",
      "These are the values you typed during this assessment. They are not stored on the server and are not a medical record. There is no history to trend because nothing is kept between sessions."));

    var any = false;
    if (inputs.glucose_mgdl !== null && inputs.glucose_test_type !== "none") {
      any = true;
      var gspec = SCALES[inputs.glucose_test_type];
      var gc = card(gspec.label);
      var gh = el("div"); gc.appendChild(gh);
      host.appendChild(gc);
      renderScale(gh, gspec, inputs.glucose_mgdl);
    }
    if (inputs.hba1c_pct !== null) {
      any = true;
      var ac = card(SCALES.hba1c.label);
      var ah = el("div"); ac.appendChild(ah);
      host.appendChild(ac);
      renderScale(ah, SCALES.hba1c, inputs.hba1c_pct);
    }

    var tc = card("All recorded values");
    var rows = [
      ["Age", inputs.age + " years", "entered"],
      ["Family history of Type 1", { yes: "Yes", no: "No", unknown: "Unknown" }[inputs.family_history_t1d], "entered"],
      ["Symptoms reported", String(inputs.symptoms.length), "entered"],
      ["Urgent signs reported", String(inputs.urgent_signs.length), "entered"],
      ["Blood glucose", inputs.glucose_mgdl === null ? "Not provided" : inputs.glucose_mgdl + " mg/dL (" + inputs.glucose_test_type + ")", "entered"],
      ["HbA1c", inputs.hba1c_pct === null ? "Not provided" : inputs.hba1c_pct + " %", "entered"],
      ["Islet autoantibodies", { none: "Not tested", negative: "Negative", one_positive: "One positive", two_or_more_positive: "Two or more positive" }[inputs.autoantibodies], "entered"]
    ];
    var w = el("div", "tablewrap");
    var t = document.createElement("table");
    var hr = document.createElement("tr");
    ["Parameter", "Value", "Origin"].forEach(function (h) { var th = document.createElement("th"); th.textContent = h; hr.appendChild(th); });
    t.appendChild(hr);
    rows.forEach(function (r) {
      var tr = document.createElement("tr");
      r.forEach(function (cl, i) {
        var td = document.createElement("td");
        if (i === 2) { var sp = el("span", "tag", "User entered"); td.appendChild(sp); }
        else td.textContent = cl;
        tr.appendChild(td);
      });
      t.appendChild(tr);
    });
    w.appendChild(t); tc.appendChild(w);
    tc.appendChild(el("p", null, "")).innerHTML =
      "<small>Every value above was typed by the user. None is a measurement taken by this system, an estimate, or a model output. Reference bands are from the ADA diagnostic criteria — verify the edition before citing.</small>";
    host.appendChild(tc);

    if (!any) {
      host.appendChild(note("warn", "No laboratory values to chart",
        "You did not enter a glucose or HbA1c result, so there is nothing to place against a reference range."));
    }
  };

  /* ========================================================= centres */
  var SVCLABEL = {
    glucose: "Blood glucose test", hba1c: "HbA1c test", ogtt: "Glucose tolerance test",
    autoantibody: "Islet autoantibody test", consultation: "Diabetes consultation",
    insulin: "Insulin", glucose_supplies: "Glucose meters & strips"
  };
  // What each kind of facility should be checked for. Anything not confirmed
  // is shown as "not confirmed" rather than hidden, so a gap is visible.
  var EXPECTED = {
    Pharmacy: ["insulin", "glucose_supplies"],
    _testing: ["glucose", "hba1c", "consultation"]
  };
  function isPharmacy(f) { return f.facility_type === "Pharmacy"; }

  function serviceRow(f, compact) {
    var wrap = el("div");
    var confirmed = {};
    f.services.forEach(function (sv) { if (sv.confirmed) confirmed[sv.service_code] = true; });
    var expect = (EXPECTED[f.facility_type] || EXPECTED._testing).slice();
    Object.keys(confirmed).forEach(function (c) { if (expect.indexOf(c) < 0) expect.push(c); });
    if (!compact) wrap.appendChild(el("div", "svchead", isPharmacy(f) ? "Medicines and supplies" : "Services"));
    var row = el("div", "svcrow");
    expect.forEach(function (code) {
      var yes = !!confirmed[code];
      var chip = el("span", "svc " + (yes ? "yes" : "no"),
        SVCLABEL[code] + (yes ? "" : " — not confirmed"));
      chip.title = yes ? "Confirmed by the research team" : "Not yet confirmed. Ask the facility.";
      row.appendChild(chip);
    });
    wrap.appendChild(row);
    return wrap;
  }

  var MapView = { map: null, layer: null, failed: false, tiles: null,
                  failedUrls: null, generation: 0 };

  /* openstreetmap.org blocks apps that do not follow its tile usage policy,
     which covers most browser apps. That returns 403 images and fills the map
     with "Access blocked" tiles. CARTO basemaps are free with attribution and
     carry no such restriction, so they lead; OSM stays as a last resort. */
  /* Tile providers, tried in order. All of these serve tiles without an API key.

     Two that do NOT belong here, learned the hard way:
       - openstreetmap.org blocks apps that do not follow its tile usage policy
         and returns 403 "Access blocked" images.
       - CARTO basemaps now watermark "API KEY REQUIRED" over every tile. That
         arrives as a normal 200 response, so no tileerror fires and the
         fallback never triggers. It has to be kept out of the list entirely. */
  var TILE_PROVIDERS = [
    { id: "esri-street", name: "Esri Street Map",
      url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
      options: { maxZoom: 19,
        attribution: 'Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ, USGS, Intermap, iPC, NRCAN, Esri Japan, METI, Esri China (Hong Kong), Esri (Thailand), TomTom' } },
    { id: "esri-topo", name: "Esri Topographic",
      url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
      options: { maxZoom: 19, attribution: 'Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ, TomTom, USGS' } },
    { id: "opentopo", name: "OpenTopoMap",
      url: "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
      options: { maxZoom: 17, subdomains: "abc",
        attribution: 'Map data &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, tiles courtesy of <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)' } },
    { id: "osm", name: "OpenStreetMap",
      url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
      options: { maxZoom: 18,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' } }
  ];

  function providerStartIndex() {
    var want = Settings.data.tileProvider;
    for (var i = 0; i < TILE_PROVIDERS.length; i++) {
      if (TILE_PROVIDERS[i].id === want) return i;
    }
    return 0;
  }

  function addTileLayer(index) {
    if (!MapView.map) return;
    var custom = Settings.data.tileUrl;
    var provider = custom
      ? { id: "custom", name: "Custom",
          url: custom,
          options: { maxZoom: 19, attribution: Settings.data.tileAttribution || "Custom tiles" } }
      : TILE_PROVIDERS[index];
    if (!provider) { tilesUnavailable(); return; }
    // Count DISTINCT failed tiles. Leaflet retries a tile and fires tileerror
    // each time, so counting events made one slow tile look like four failures
    // and skipped past a provider that was merely warming up.
    MapView.failedUrls = Object.create(null);
    var generation = (MapView.generation += 1);
    if (MapView.tiles) MapView.map.removeLayer(MapView.tiles);
    MapView.tiles = window.L.tileLayer(provider.url, provider.options).addTo(MapView.map);
    var tag = $("mapModeTag");
    if (tag) tag.textContent = provider.name;
    MapView.tiles.on("tileerror", function (e) {
      // A late error from a layer we have already replaced must not advance again.
      if (generation !== MapView.generation) return;
      var url = (e && e.tile && e.tile.src) || ("unknown-" + Math.random());
      if (MapView.failedUrls[url]) return;
      MapView.failedUrls[url] = true;
      if (Object.keys(MapView.failedUrls).length < 4) return;
      if (custom) tilesUnavailable();
      else addTileLayer(index + 1);
    });
  }

  function tilesUnavailable() {
    if (MapView.failed) return;
    MapView.failed = true;
    var note = $("mapNote");
    if (note) note.textContent = "Map tiles could not be loaded from any provider. " +
      "Showing the schematic locator; facility coordinates are unaffected.";
    $("leafmap").hidden = true;
    $("locator").hidden = false;
    buildLocator();
  }

  /* Map markers.

     Colour alone cannot carry the verified/unconfirmed distinction: that is the
     difference between "someone phoned and confirmed this clinic does the test"
     and "nobody has checked", and a red-green or blue-yellow colourblind reader
     sees three similar blobs. Each status therefore has its own SHAPE and its
     own GLYPH as well as its colour:

       verified      filled teardrop + check
       unconfirmed   hollow teardrop + question mark
       outdated      hollow teardrop + dash
       pharmacy      square + cross
       municipality  hollow circle + dot

     The legend is built from this same table, so the two cannot drift apart. */
  var MARKERS = {
    verified: {
      label: "Service confirmed", fill: "#06628D", ink: "#FFFFFF", shape: "pin", solid: true,
      glyph: '<path d="M8.6 13.2l2.6 2.6 4.6-5.2" fill="none" stroke="INK" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>'
    },
    unconfirmed: {
      label: "Not yet confirmed", fill: "#E46B43", ink: "#8A3414", shape: "pin", solid: false,
      glyph: '<text x="12" y="17" text-anchor="middle" font-family="Inter,sans-serif" font-size="12" font-weight="700" fill="INK">?</text>'
    },
    outdated: {
      label: "Record outdated", fill: "#F91A10", ink: "#A60F08", shape: "pin", solid: false,
      glyph: '<path d="M8.4 12.6h7.2" fill="none" stroke="INK" stroke-width="2.4" stroke-linecap="round"/>'
    },
    pharmacy: {
      label: "Pharmacy", fill: "#2AA7C9", ink: "#04284D", shape: "square", solid: true,
      glyph: '<path d="M12 7.6v8M8 11.6h8" fill="none" stroke="INK" stroke-width="2.4" stroke-linecap="round"/>'
    },
    municipality: {
      label: "Nothing mapped here yet", fill: "#04284D", ink: "#04284D", shape: "circle", solid: false,
      glyph: '<circle cx="12" cy="12" r="2.4" fill="INK"/>'
    }
  };

  function markerSvg(status, size) {
    var m = MARKERS[status] || MARKERS.unconfirmed;
    var body;
    if (m.shape === "pin") {
      body = '<path d="M12 1.6c-4.3 0-7.8 3.4-7.8 7.6 0 5.6 7.8 13.2 7.8 13.2s7.8-7.6 7.8-13.2c0-4.2-3.5-7.6-7.8-7.6z"';
    } else if (m.shape === "square") {
      body = '<rect x="3.4" y="3.4" width="17.2" height="17.2" rx="4"';
    } else {
      body = '<circle cx="12" cy="12" r="8.6"';
    }
    // Solid markers are filled; hollow ones keep a white centre so the glyph
    // stays legible and the outline reads as "not filled in yet".
    body += m.solid
      ? ' fill="' + m.fill + '" stroke="#FFFFFF" stroke-width="1.6"/>'
      : ' fill="#FFFFFF" stroke="' + m.fill + '" stroke-width="2.4"/>';
    var h = m.shape === "pin" ? 24 : 24;
    return '<svg xmlns="http://www.w3.org/2000/svg" width="' + size + '" height="'
      + Math.round(size * h / 24) + '" viewBox="0 0 24 24" aria-hidden="true">'
      + body + m.glyph.split("INK").join(m.solid ? m.ink : m.fill) + "</svg>";
  }

  function pinIcon(status) {
    var m = MARKERS[status] ? status : "unconfirmed";
    var isPin = MARKERS[m].shape === "pin";
    return window.L.divIcon({
      className: "pin-wrap",
      iconSize: [30, 30],
      iconAnchor: isPin ? [15, 29] : [15, 15],
      popupAnchor: [0, isPin ? -27 : -15],
      html: markerSvg(m, 30)
    });
  }

  function buildMapLegend() {
    var host = $("mapLegend");
    if (!host) return;
    clear(host);
    [["verified", "Testing centre, service confirmed"],
     ["unconfirmed", "Testing centre, not yet confirmed"],
     ["outdated", "Record outdated"],
     ["pharmacy", "Pharmacy"],
     ["municipality", "Municipality, nothing mapped"]].forEach(function (row) {
      var item = el("span", "lgitem");
      var ico = el("span", "lgico");
      ico.innerHTML = markerSvg(row[0], 20);
      item.appendChild(ico);
      item.appendChild(document.createTextNode(row[1]));
      host.appendChild(item);
    });
  }


  function buildMap(facilities) {
    if (!window.L) { MapView.failed = true; buildLocator(); return; }
    var host = $("leafmap");
    if (!MapView.map) {
      try {
        MapView.map = window.L.map(host, { scrollWheelZoom: true, attributionControl: true })
          .setView([6.39, 124.86], 10);
        MapView.map.scrollWheelZoom.enable();
        addTileLayer(providerStartIndex());
        MapView.layer = window.L.layerGroup().addTo(MapView.map);
        buildMapLegend();
      } catch (e) {
        MapView.failed = true; host.hidden = true; $("locator").hidden = false;
        buildLocator(); return;
      }
    }
    MapView.layer.clearLayers();

    var bounds = [];
    (facilities || []).forEach(function (f) {
      if (f.latitude == null || f.longitude == null) return;
      var confirmed = f.services.filter(function (x) { return x.confirmed; });
      var html = "<span class=\"pop-type\"></span><h4></h4><p class=\"m\"></p>"
        + "<div class=\"s\"></div><p class=\"v\"></p>";
      var m = window.L.marker([f.latitude, f.longitude],
                              { icon: pinIcon(isPharmacy(f) ? "pharmacy" : f.status), title: f.name })
        .bindPopup(html, { minWidth: 240, maxWidth: 300, autoPanPadding: [20, 20] });
      m.on("popupopen", function (e) {
        var n = e.popup.getElement();
        var badge = n.querySelector(".pop-type");
        badge.textContent = isPharmacy(f) ? "Pharmacy" : f.facility_type;
        badge.className = "pop-type" + (isPharmacy(f) ? " ph" : "");
        n.querySelector("h4").textContent = f.name;
        n.querySelector(".m").textContent = f.municipality +
          (f.address ? " · " + f.address : "") + (f.contact ? " · " + f.contact : "");
        var sbox = n.querySelector(".s"); clear(sbox);
        sbox.appendChild(serviceRow(f, true));
        var statusKey = isPharmacy(f) ? "pharmacy" : f.status;
        var vrow = n.querySelector(".v");
        clear(vrow);
        var vico = el("span", "lgico");
        vico.innerHTML = markerSvg(MARKERS[statusKey] ? statusKey : "unconfirmed", 16);
        vrow.appendChild(vico);
        vrow.appendChild(document.createTextNode(
          (MARKERS[statusKey] ? MARKERS[statusKey].label : f.status)
          + " · checked " + (f.verified_on || "not recorded")));
      });
      MapView.layer.addLayer(m);
      bounds.push([f.latitude, f.longitude]);
    });

    // Municipalities with no mapped facility still show, so coverage gaps are visible.
    var mapped = {};
    (facilities || []).forEach(function (f) { if (f.latitude != null) mapped[f.municipality] = true; });
    Store.municipalities.forEach(function (mu) {
      if (mapped[mu.name] || mu.centroid.lat == null) return;
      var m = window.L.marker([mu.centroid.lat, mu.centroid.lon], { icon: pinIcon("municipality") })
        .bindPopup("<h4>" + mu.name + "</h4><p>No facility mapped here yet. Centroid is approximate.</p>",
                   { minWidth: 220, maxWidth: 280 });
      MapView.layer.addLayer(m);
      bounds.push([mu.centroid.lat, mu.centroid.lon]);
    });

    if (bounds.length) MapView.map.fitBounds(bounds, { padding: [34, 34], maxZoom: 12 });
    setTimeout(function () { if (MapView.map) MapView.map.invalidateSize(); }, 80);
  }

  function buildLocator() {
    var area = $("locator"); clear(area);
    var LON0 = 124.58, LON1 = 125.10, LAT0 = 6.18, LAT1 = 6.60;
    Store.municipalities.forEach(function (m) {
      if (m.centroid.lat === null) return;
      var b = el("button", "pin");
      b.type = "button";
      b.style.left = ((m.centroid.lon - LON0) / (LON1 - LON0) * 100) + "%";
      b.style.top = ((LAT1 - m.centroid.lat) / (LAT1 - LAT0) * 100) + "%";
      b.appendChild(el("b"));
      b.appendChild(el("span", null, m.name));
      b.setAttribute("aria-label", "Filter facilities in " + m.name);
      b.addEventListener("click", function () {
        $("fMuni").value = m.name;
        renderFacilities();
        $("facilityList").scrollIntoView({ block: "start" });
      });
      area.appendChild(b);
    });
  }

  function facilityNode(f) {
    var d = el("div", "card");
    d.style.cssText = "padding:14px;box-shadow:none;margin-bottom:10px";
    var head = el("div", "card-head");
    head.style.marginBottom = "6px";
    head.appendChild(el("h3", null, f.name));
    var sp = el("span", "spacer"); head.appendChild(sp);
    var cls = { verified: "tag-ok", unconfirmed: "tag-warn", outdated: "tag-bad" }[f.status] || "tag";
    head.appendChild(el("span", "tag " + cls, f.status));
    d.appendChild(head);

    var meta = el("p");
    meta.style.cssText = "color:var(--text-2);font-size:.85rem;margin-bottom:8px";
    meta.textContent = f.facility_type + " · " + f.municipality +
      (f.address ? " · " + f.address : "") +
      (f.contact ? " · " + f.contact : "") +
      (f.latitude != null && f.longitude != null ? " · " + f.latitude + ", " + f.longitude : " · coordinates not recorded");
    d.appendChild(meta);

    d.appendChild(serviceRow(f, false));
    if (/philhealth|yakap|konsulta/i.test(f.source || "") &&
        f.services.some(function (sv) { return sv.confirmed; })) {
      var ph = el("p");
      ph.style.cssText = "color:var(--text-2);font-size:.8rem;margin:8px 0 0";
      ph.textContent = "Confirmed through PhilHealth accreditation: the test is available "
        + "through this provider, and may be done at a partner laboratory. Call to check.";
      d.appendChild(ph);
    }

    var src = el("p");
    src.style.cssText = "color:var(--text-2);font-size:.8rem;margin:8px 0 0";
    src.textContent = "Source: " + (f.source || "not recorded") + " · Verified: " + (f.verified_on || "not recorded");
    d.appendChild(src);

    var acts = el("div", "btnrow");
    acts.style.marginTop = "10px";
    var anyConfirmed = f.services.some(function (sv) { return sv.confirmed; });
    if (!anyConfirmed && f.contact) {
      // The useful action on an unconfirmed record is a phone call, not a map.
      var tel = el("a", "btn btn-soft btn-sm", "Call to verify");
      tel.href = "tel:" + f.contact.replace(/[^+0-9]/g, "");
      tel.title = "Ask whether they offer blood glucose or HbA1c testing";
      acts.appendChild(tel);
    } else if (f.contact) {
      var call = el("a", "btn btn-ghost btn-sm", "Call");
      call.href = "tel:" + f.contact.replace(/[^+0-9]/g, "");
      acts.appendChild(call);
    }
    if (f.latitude != null && f.longitude != null) {
      var a = el("a", "btn btn-ghost btn-sm", "Directions");
      a.href = "https://www.openstreetmap.org/?mlat=" + f.latitude + "&mlon=" + f.longitude + "#map=16/" + f.latitude + "/" + f.longitude;
      a.target = "_blank"; a.rel = "noopener";
      acts.appendChild(a);
    }
    if (acts.childNodes.length) d.appendChild(acts);
    return d;
  }

  function renderFacilities() {
    var host = $("facilityList");
    host.innerHTML = '<div class="skel"></div><div class="skel"></div>';
    var p = new URLSearchParams();
    var q = $("fSearch").value.trim();
    if (q) p.set("q", q);
    if ($("fMuni").value) p.set("municipality", $("fMuni").value);
    if ($("fStatus").value) p.set("status", $("fStatus").value);
    if ($("fSvc").value) { p.set("service", $("fSvc").value); p.set("confirmed_only", "true"); }
    var kind = { Pharmacy: "pharmacy", testing: "testing" }[$("fType").value];
    if (kind) p.set("kind", kind);
    p.set("limit", "500");

    Api.call("/api/v1/facilities?" + p.toString()).then(function (body) {
      clear(host);
      $("facCount").textContent = body.items.length + " shown of " + body.total;
      $("facAttribution").textContent = body.attribution;
      if (!body.total) {
        host.appendChild(emptyState("No facility records yet",
          "A map listing facilities nobody has checked is worse than an empty one. Sign in as a researcher and add each record as you confirm it.", "pin"));
        return;
      }
      if (!body.items.length) {
        host.appendChild(emptyState("No match",
          "No record matches those filters. Clear the search box or choose any municipality.", "search"));
        return;
      }
      $("facCount").textContent = body.items.length + " shown of " + body.total;
      body.items.forEach(function (f) { host.appendChild(facilityNode(f)); });
    }).then(function () {
      // the map always shows everything, not just the filtered list
      var mk = { Pharmacy: "pharmacy", testing: "testing" }[$("fType").value];
      return Api.call("/api/v1/facilities?limit=500" + (mk ? "&kind=" + mk : ""))
        .then(function (all) { buildMap(all.items); })
        .catch(function () { });
    }).catch(function (err) {
      clear(host);
      host.appendChild(note("warn", null, Api.describe(err)));
    });
  }

  RENDER.centers = function () { renderFacilities(); };

  /* ========================================================= reports */
  RENDER.reports = function () {
    var host = $("historyBody"); clear(host);
    if (!Store.history.length) {
      host.appendChild(emptyState("No assessments yet this session",
        "Each completed assessment is listed here with its result and reasoning.", "clipboard",
        { label: "Start an assessment", href: "#assess" }));
      return;
    }
    var w = el("div", "tablewrap");
    var t = document.createElement("table");
    var hr = document.createElement("tr");
    ["Time", "Result", "Headline", "Labs entered", "Model"].forEach(function (h) {
      var th = document.createElement("th"); th.textContent = h; hr.appendChild(th);
    });
    t.appendChild(hr);
    Store.history.slice().reverse().forEach(function (h) {
      var tr = document.createElement("tr");
      var td1 = document.createElement("td"); td1.textContent = h.at; tr.appendChild(td1);
      var td2 = document.createElement("td"); td2.appendChild(el("span", "tag " + h.tagClass, h.tier.replace(/_/g, " "))); tr.appendChild(td2);
      var td3 = document.createElement("td"); td3.textContent = h.headline; tr.appendChild(td3);
      var td4 = document.createElement("td"); td4.textContent = h.labs; tr.appendChild(td4);
      var td5 = document.createElement("td"); td5.textContent = h.model; tr.appendChild(td5);
      t.appendChild(tr);
    });
    w.appendChild(t); host.appendChild(w);
    var p = el("p"); p.style.marginTop = "12px";
    p.innerHTML = "<small>Held in this tab’s memory only. Closing the tab deletes it. Nothing was sent to a server for storage.</small>";
    host.appendChild(p);
  };

  /* ======================================================== research */
  RENDER.research = function () {
    var host = $("researchBody"); clear(host);
    if (!Auth.isStaff()) {
      $("resTag").textContent = "Sign in required";
      $("resTag").className = "tag tag-warn";
      host.appendChild(emptyState("Researcher access required",
        "Evaluation metrics are protected on the server. Sign in with a researcher or admin account from the top bar. Hiding the link would not be access control."));
      return;
    }
    host.innerHTML = '<div class="skel"></div><div class="skel"></div><div class="skel"></div>';
    Api.call("/api/v1/admin/metrics", { headers: Auth.headers() })
      .then(function (b) {
        clear(host);
        $("resTag").textContent = b.model.status === "active" ? "Model active" : "No active model";
        $("resTag").className = "tag " + (b.model.status === "active" ? "tag-ok" : "tag-warn");

        if (b.model.status !== "active") {
          host.appendChild(note("warn", "No active model",
            "No metric is reported because none has been measured. The training pipeline exists and runs, but it refuses to activate a model trained on synthetic data, so the API keeps reporting that no model is available."));
        } else {
          var meta = el("p");
          meta.textContent = "Version " + b.model.version + " (" + b.model.algorithm + "), task: " +
            b.model.prediction_task + ". Dataset: " + b.model.dataset_label +
            (b.model.dataset_is_synthetic ? " — SYNTHETIC" : "") +
            ", n_train=" + b.model.n_train + ", n_test=" + b.model.n_test + ".";
          host.appendChild(meta);
          var items = Object.keys(b.model.metrics).filter(function (k) {
            return typeof b.model.metrics[k] === "number";
          }).map(function (k) {
            return { label: k, value: Math.round(b.model.metrics[k] * 1000) / 10 };
          });
          var ch = el("div"); host.appendChild(ch);
          window.Charts.bars(ch, { id: "metrics", label: "Model metrics (percent)", items: items });
        }

        var fc = el("div", "grid g3");
        fc.style.marginTop = "16px";
        fc.appendChild(statCard("Facility records", String(b.facilities.total_records), "total in database", "--sky"));
        fc.appendChild(statCard("Verified", String(b.facilities.by_status.verified),
          b.facilities.by_status.unconfirmed + " unconfirmed", "--mint"));
        fc.appendChild(statCard("Confirmed services", String(b.facilities.confirmed_service_claims),
          "each backed by a source and date", "--lavender"));
        host.appendChild(fc);

        host.appendChild(note("info", "Coverage denominator", b.facilities.coverage_denominator));
        host.appendChild(note("info", "Usability evaluation",
          b.usability_evaluation.status + ", " + b.usability_evaluation.respondents + " respondents."));
      })
      .catch(function (err) {
        clear(host);
        host.appendChild(note("warn", null, Api.describe(err)));
      });
  };



  /* ===================================================== onboarding
     Shown once on a first visit. Four steps, and the middle two carry the
     weight: what this does, and plainly what it does not. Someone who
     expects a diagnosis and gets a threshold check has been misled by the
     interface, not by the result.

     The municipality it asks for is a preference, not health data: it only
     pre-selects a dropdown, and it is stored with the theme and text-size
     settings, never sent anywhere. */
/* ===================================================== onboarding
A visual, step-by-step guide shown on the first visit. 
Explains how to use the Assessment, Map, and Chat before the user starts.
*/
  var Onboard = {
      step: 0,
      lastFocus: null,
      steps: [
          {
              eyebrow: "WELCOME",
              title: "How to use DiabetEASE",
              render: function (host) {
                  host.appendChild(el("p", null,
                      "DiabetEASE helps you check if a diabetes test is worth getting and shows you where to get one. Here is a quick guide before you start."));
                  var illus = el("div", "onboard-illustration");
                  illus.innerHTML = '<svg width="50" height="50" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg>';
                  host.appendChild(illus);
              }
          },
          {
              eyebrow: "STEP 1 OF 3",
              title: "Take the Risk Assessment",
              render: function (host) {
                  host.appendChild(el("p", null, "Go to 'Risk assessment' in the menu. It takes 5 steps and about 2 minutes."));
                  var grid = el("div", "onboard-steps-visual");
                  [
                      { t: "About you", d: "Age & location" },
                      { t: "Symptoms", d: "What you feel" },
                      { t: "Labs", d: "Blood results" }
                  ].forEach(function(s) {
                      var item = el("div", "onboard-step-item");
                      item.appendChild(el("b", null, s.t));
                      item.appendChild(el("span", null, s.d));
                      grid.appendChild(item);
                  });
                  host.appendChild(grid);
                  host.appendChild(el("p", null, "Leave anything blank if you don't know. Blanks are treated as 'unknown', never as 'normal'."));
              }
          },
          {
              eyebrow: "STEP 2 OF 3",
              title: "View Results & Find Care",
              render: function (host) {
                  host.appendChild(el("p", null, "Your result will tell you the next best step. It is not a diagnosis."));
                  var grid = el("div", "onboard-steps-visual");
                  [
                      { t: "Results", d: "See your tier" },
                      { t: "Map", d: "Find a clinic" },
                      { t: "Candie", d: "Ask questions" }
                  ].forEach(function(s) {
                      var item = el("div", "onboard-step-item");
                      item.appendChild(el("b", null, s.t));
                      item.appendChild(el("span", null, s.d));
                      grid.appendChild(item);
                  });
                  host.appendChild(grid);
                  host.appendChild(el("p", null, "Use the Testing centre map to find verified facilities near you, or ask Candie in the chat."));
              }
          },
          {
              eyebrow: "STEP 3 OF 3",
              title: "Your Privacy is Protected",
              render: function (host) {
                  host.appendChild(el("p", null, "We do not ask for your name, birth date, or contact number."));
                  var illus = el("div", "onboard-illustration");
                  illus.style.background = "var(--ok-bg)"; illus.style.color = "var(--ok-ink)";
                  illus.innerHTML = '<svg width="50" height="50" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>';
                  host.appendChild(illus);
                  host.appendChild(el("p", null, "Your answers are used to compute your result and then discarded. Nothing is stored unless you explicitly consent later."));
              }
          },
          {
              eyebrow: "ALMOST THERE",
              title: "Where are you located?",
              render: function (host) {
                  host.appendChild(el("p", null, "Pick your municipality so the map and assessment can start there. This is saved on your device only."));
                  var sel = $("obMuni");
                  clear(sel);
                  sel.appendChild(new Option("Skip this", ""));
                  Store.municipalities.forEach(function (m) {
                      sel.appendChild(new Option(m.name, m.name));
                  });
                  sel.value = Settings.data.municipality || "";
              }
          }
      ],
      shouldShow: function () {
          try { return localStorage.getItem("diabetease.onboarded") !== "1"; }
          catch (e) { return false; }
      },
      markDone: function () {
          try { localStorage.setItem("diabetease.onboarded", "1"); } catch (e) { }
      },
      open: function (step) {
          this.lastFocus = document.activeElement;
          this.step = step || 0;
          $("onboard").hidden = false;
          document.body.style.overflow = "hidden";
          this.paint();
      },
      close: function (completed) {
          this.markDone();
          var sel = $("obMuni");
          if (completed && sel && sel.value) {
              Settings.data.municipality = sel.value;
              Settings.save();
              var muni = $("muni"), fMuni = $("fMuni");
              if (muni) muni.value = sel.value;
              if (fMuni) { fMuni.value = sel.value; }
          }
          $("onboard").hidden = true;
          document.body.style.overflow = "";
          if (this.lastFocus && this.lastFocus.focus) this.lastFocus.focus();
          if (completed) RENDER.dashboard();
      },
      paint: function () {
          var spec = this.steps[this.step];
          $("obStepLabel").textContent = spec.eyebrow;
          $("obTitle").textContent = spec.title;
          var body = $("obBody");
          clear(body);
          $("obField").hidden = this.step !== this.steps.length - 1;
          spec.render(body);
          var dots = $("obDots");
          clear(dots);
          var self = this;
          this.steps.forEach(function (_s, i) {
              dots.appendChild(el("i", i === self.step ? "on" : ""));
          });
          $("obBack").disabled = this.step === 0;
          $("obNext").textContent = this.step === this.steps.length - 1 ? "Start using DiabetEASE" : "Next";
          $("obNext").focus();
      },
      next: function () {
          if (this.step < this.steps.length - 1) { this.step++; this.paint(); }
          else this.close(true);
      },
      back: function () {
          if (this.step > 0) { this.step--; this.paint(); }
      }
  };

  /* ========================================================= account */
  var authMode = "login";

  function setAuthMode(mode) {
    authMode = mode;
    var isReg = mode === "register";
    $("tabLogin").setAttribute("aria-pressed", String(!isReg));
    $("tabRegister").setAttribute("aria-pressed", String(isReg));
    $("authTitle").textContent = isReg ? "Create account" : "Sign in";
    $("authSubmit").textContent = isReg ? "Create account" : "Sign in";
    $("authNameField").hidden = !isReg;
    $("authPass").setAttribute("autocomplete", isReg ? "new-password" : "current-password");
    $("authPassHint").textContent = isReg
      ? "At least 10 characters. Length matters more than symbols."
      : "At least 10 characters.";
    $("authStatus").textContent = "";
  }

  RENDER.account = function () {
    var st = $("authStatus");
    if (Store.health && Store.health.accounts_enabled === false) {
      st.textContent = "Accounts are not enabled on this server. Set SECRET_KEY in backend/.env and restart.";
      $("authSubmit").disabled = true;
    } else {
      $("authSubmit").disabled = false;
    }
    if (Auth.token) {
      $("authLead").textContent = "Signed in as " + Auth.username + " (" + Auth.role + ").";
      st.textContent = "";
    } else {
      $("authLead").textContent = "Accounts are optional. The assessment works without one.";
    }
    if (Auth.role === "admin") loadAccounts();
  };

  function loadAccounts() {
    var host = $("accountList");
    host.innerHTML = '<div class="skel"></div>';
    Api.call("/api/v1/auth/accounts", { headers: Auth.headers() }).then(function (b) {
      $("acctCount").textContent = b.items.length + " account(s)";
      clear(host);
      if (!b.items.length) { host.appendChild(emptyState("No accounts yet", "Patients appear here once they sign up.")); return; }
      var w = el("div", "tablewrap"), t = document.createElement("table");
      var hr = document.createElement("tr");
      ["Username", "Role", "Granted by"].forEach(function (h) {
        var th = document.createElement("th"); th.textContent = h; hr.appendChild(th);
      });
      t.appendChild(hr);
      b.items.forEach(function (a) {
        var tr = document.createElement("tr");
        [a.username, a.role, a.granted_by || "—"].forEach(function (v) {
          var td = document.createElement("td"); td.textContent = v; tr.appendChild(td);
        });
        t.appendChild(tr);
      });
      w.appendChild(t); host.appendChild(w);
    }).catch(function (err) {
      clear(host); host.appendChild(note("warn", null, Api.describe(err)));
    });
  }

  /* ============================================================ quiz */
  var QUIZ = [
    { q: "What causes Type 1 diabetes?",
      a: ["Eating too much sugar", "The immune system destroying insulin-producing cells", "Not exercising enough", "Being overweight"],
      correct: 1,
      why: "It is an autoimmune disease. Diet and weight do not cause it, and nothing a parent or child did brings it on." },
    { q: "Can Type 1 diabetes be prevented by changing your lifestyle?",
      a: ["Yes, with diet and exercise", "No, it cannot currently be prevented"],
      correct: 1,
      why: "Prevention works for Type 2 in many cases. For Type 1 there is no proven way to prevent it, which is exactly why early detection matters." },
    { q: "A fasting blood glucose of 130 mg/dL is:",
      a: ["Normal", "In the intermediate range", "At or above the diagnostic threshold"],
      correct: 2,
      why: "The published fasting cut-off is 126 mg/dL. One reading is not a diagnosis; it needs confirming by a clinician." },
    { q: "Most people who develop Type 1 diabetes have:",
      a: ["A parent or sibling with it", "No family history at all"],
      correct: 1,
      why: "About 85 in 100 new cases appear in families with no history. A parent or sibling with it raises risk to about 1 in 20 in US studies." },
    { q: "Which test can detect Type 1 diabetes before any symptoms appear?",
      a: ["Fasting glucose", "HbA1c", "Islet autoantibody testing", "Blood pressure"],
      correct: 2,
      why: "Glucose and HbA1c only become abnormal late. Autoantibodies appear months to years earlier, which is what makes presymptomatic screening possible." },
    { q: "Vomiting, stomach pain, fast breathing and drowsiness together mean you should:",
      a: ["Book an appointment next week", "Finish the online assessment first", "Go to an emergency department now"],
      correct: 2,
      why: "That pattern can be diabetic ketoacidosis. Its severe symptoms can appear quickly and it is an emergency. Nothing online should delay you." },
    { q: "Can a blood glucose test tell Type 1 apart from Type 2?",
      a: ["Yes, the numbers differ", "No, it only shows that glucose is abnormal"],
      correct: 1,
      why: "Both types raise glucose. Telling them apart needs antibody testing and clinical judgement." },
    { q: "A DiabetEASE result saying nothing crosses a threshold means:",
      a: ["You definitely do not have Type 1 diabetes", "Nothing you entered met a published cut-off today"],
      correct: 1,
      why: "Early-stage disease is silent on glucose testing, so a normal result cannot rule it out. It is reassuring about today, not a clean bill of health." }
  ];

  function renderQuiz() {
    var host = $("quizBody");
    if (!host || host.dataset.built) return;
    host.dataset.built = "1";
    var answered = 0, right = 0;
    QUIZ.forEach(function (item, qi) {
      var box = el("div", "quizq");
      box.appendChild(el("p", null, (qi + 1) + ". " + item.q));
      var why = el("p", "quizwhy", item.why);
      why.hidden = true;
      item.a.forEach(function (text, ai) {
        var b = el("button", "quizopt", text);
        b.type = "button";
        b.addEventListener("click", function () {
          if (box.dataset.done) return;
          box.dataset.done = "1";
          answered++;
          var correct = ai === item.correct;
          if (correct) right++;
          box.querySelectorAll(".quizopt").forEach(function (o, oi) {
            o.disabled = true;
            if (oi === item.correct) o.classList.add("right");
            else if (oi === ai) o.classList.add("wrong");
          });
          why.hidden = false;
          $("quizScore").textContent = right + " / " + answered;
        });
        box.appendChild(b);
      });
      box.appendChild(why);
      host.appendChild(box);
    });
  }

  var MYTHS = [
    ["Eating too many sweets causes Type 1 diabetes.", "Myth",
     "It is autoimmune. Sugar intake does not cause it, and this myth leads to a lot of misplaced blame on parents and children."],
    ["Type 1 diabetes only appears in children.", "Myth",
     "It is most common in childhood and adolescence, but it can begin at any age, including in adults in their thirties and forties."],
    ["You can have Type 1 diabetes for months without knowing.", "Fact",
     "The autoimmune process starts months to years before symptoms appear. That silent window is what screening is for."],
    ["People with Type 1 diabetes must avoid all sugar forever.", "Myth",
     "Management is about matching insulin to food, not banning food groups. A clinician and dietitian set the plan."],
    ["A normal blood sugar result rules out Type 1 diabetes.", "Myth",
     "Glucose becomes abnormal only in the later stages. Only antibody testing detects the early ones."],
    ["Type 1 diabetes can run in families but usually does not.", "Fact",
     "A parent or sibling with it raises risk to roughly 1 in 20, yet most new cases have no family history at all."]
  ];

  function renderMyths() {
    var host = $("mythGrid");
    if (!host || host.dataset.built) return;
    host.dataset.built = "1";
    MYTHS.forEach(function (m) {
      var b = el("button", "myth");
      b.type = "button";
      b.setAttribute("aria-expanded", "false");
      var front = el("b", null, m[0]);
      var hint = el("span", "verdict", "Tap to reveal");
      b.appendChild(front); b.appendChild(hint);
      var body = el("p", null, m[2]); body.hidden = true;
      b.appendChild(body);
      b.addEventListener("click", function () {
        var open = b.classList.toggle("flipped");
        hint.textContent = open ? m[1] : "Tap to reveal";
        body.hidden = !open;
        b.setAttribute("aria-expanded", String(open));
      });
      host.appendChild(b);
    });
  }

  function renderSources() {
    var host = $("eduSources");
    if (!host || host.dataset.built) return;
    Api.call("/api/v1/sources").then(function (b) {
      host.dataset.built = "1";
      clear(host);
      var HOW = { publisher: "Publisher's page seen", index: "Bibliographic record seen",
                  secondary: "Located, not queried" };
      var w = el("div", "tablewrap"), t = document.createElement("table");
      var hr = document.createElement("tr");
      ["Source", "Used for", "How it was checked"].forEach(function (h) {
        var th = document.createElement("th"); th.textContent = h; hr.appendChild(th);
      });
      t.appendChild(hr);
      Object.keys(b.sources).forEach(function (k) {
        var src = b.sources[k], tr = document.createElement("tr");
        var td1 = document.createElement("td");
        var a = document.createElement("a");
        a.href = src.url; a.target = "_blank"; a.rel = "noopener";
        a.textContent = src.citation;
        td1.appendChild(a);
        var td2 = document.createElement("td"); td2.textContent = src.supports;
        var td3 = document.createElement("td");
        td3.appendChild(el("span", "tag " + (src.checked === "publisher" ? "tag-ok" : "tag-warn"),
                           HOW[src.checked] || src.checked));
        tr.appendChild(td1); tr.appendChild(td2); tr.appendChild(td3);
        t.appendChild(tr);
      });
      w.appendChild(t); host.appendChild(w);
      var n = el("p"); n.style.marginTop = "10px"; n.innerHTML = "<small></small>";
      n.querySelector("small").textContent = "Checked " + b.checked_on
        + ". Confirm the edition and page yourself before citing any of these.";
      host.appendChild(n);
    }).catch(function (err) {
      clear(host);
      host.appendChild(note("warn", null, Api.describe(err)));
    });
  }

  RENDER.learn = function () {
    renderSources(); renderQuiz(); renderMyths(); };

  /* =========================================================== voice */
  var Voice = {
    on: false,
    supported: typeof window.speechSynthesis !== "undefined",
    voice: null,
    pickVoice: function () {
      var voices = window.speechSynthesis.getVoices() || [];
      if (!voices.length) return null;
      var english = voices.filter(function (v) { return /^en/i.test(v.lang); });
      if (!english.length) english = voices;

      // Name lists cover the voices Windows, macOS, Android and Chrome actually
      // ship. "Andrew" was missing and is a standard Windows Natural voice, so a
      // male voice was winning on the quality bonus alone.
      var FEMALE = /(zira|hazel|susan|linda|heera|eva|aria|jenny|michelle|ana|sonia|natasha|clara|amelie|emily|ava|allison|samantha|karen|moira|tessa|fiona|serena|victoria|kathy|nora|luna|female|woman|girl|google uk english female|google us english)/i;
      var MALE = /(david|mark|george|james|richard|sean|ravi|andrew|brian|christopher|eric|roger|steffan|liam|william|thomas|oliver|ryan|guy|davis|jason|tony|antoni|adam|ethan|noah|daniel|alex|fred|rishi|tom|angelo|male|man|google uk english male)/i;

      var scored = english.map(function (v) {
        var male = MALE.test(v.name) && !FEMALE.test(v.name);
        var score = 0;
        if (FEMALE.test(v.name)) score += 15;
        if (male) score -= 15;
        // Quality bonus is withheld from male-sounding voices on purpose. Applied
        // to everything, +20 would outrank the -15 gender penalty and a male
        // "Natural" voice would win, which is not the voice Candie should have.
        if (!male && /natural|premium|online|enhanced|neural/i.test(v.name)) score += 20;
        if (/local|default/i.test(v.name)) score -= 5;
        if (/en[-_]PH/i.test(v.lang)) score += 10;
        if (/en[-_](GB|AU)/i.test(v.lang)) score += 4;
        if (v.localService) score += 2;
        return { v: v, score: score, male: male };
      }).sort(function (a, b) { return b.score - a.score; });

      // Prefer any non-male voice over the best male one, whatever it scores.
      var notMale = scored.filter(function (x) { return !x.male; });
      var pick = notMale.length ? notMale[0] : scored[0];
      return pick ? pick.v : english[0];
    },
    speak: function (text) {
      if (!this.on || !this.supported) return;
      try {
        window.speechSynthesis.cancel();
        // Markdown characters are read aloud literally by some engines.
        var cleanText = String(text).replace(/[*_~`]/g, "").slice(0, 600);
        var u = new SpeechSynthesisUtterance(cleanText);
        if (!this.voice) this.voice = this.pickVoice();
        if (this.voice) { u.voice = this.voice; u.lang = this.voice.lang; }
        u.pitch = 1.1;
        u.rate = 1.0;
        u.volume = 1;
        window.speechSynthesis.speak(u);
      } catch (e) { /* speech is a nicety; never let it break the reply */ }
    },
    stop: function () { try { window.speechSynthesis.cancel(); } catch (e) { } }
  };

  if (typeof window.speechSynthesis !== "undefined") {
    window.speechSynthesis.onvoiceschanged = function () { Voice.voice = Voice.pickVoice(); };
  }

  /* ====================================================== assessment */
  var step = 1, MAXSTEP = 5, data = {};
  var STEPNAMES = ["About you", "Family history", "Symptoms", "Laboratory results", "Review"];
  // One plain line per step. Each answers the question people actually have at
  // that moment, rather than reassuring in general.
  var STEPNOTES = [
    "No name, birth date or contact number is asked for, here or anywhere.",
    "If you are not sure, leave it as “I do not know”. That is a real answer here.",
    "Tick only what you have noticed. Leaving one unticked does not count against you.",
    "All optional. These are values from a laboratory you have already visited.",
    "Check your answers. Nothing is sent until you press the button below."
  ];

  function buildStepper() {
    var host = $("stepper");
    if (!host || host.dataset.built) return;
    host.dataset.built = "1";
    STEPNAMES.forEach(function (name, i) {
      var seg = el("div", "stepseg");
      seg.appendChild(el("div", "bar"));
      seg.appendChild(el("span", "nm", name));
      seg.setAttribute("aria-hidden", "true");
      host.appendChild(seg);
    });
  }
  var SYMLABEL = {
    thirst: "excessive thirst", urination: "frequent urination", weight_loss: "unexplained weight loss",
    fatigue: "fatigue", blurred_vision: "blurred vision", hunger: "constant hunger"
  };

  function paintSteps() {
    buildStepper();
    document.querySelectorAll("#stepper .stepseg").forEach(function (seg, i) {
      seg.className = "stepseg" + (i + 1 < step ? " done" : (i + 1 === step ? " now" : ""));
    });
    $("stepLabel").textContent = "Step " + step + " of " + MAXSTEP + " · " + STEPNAMES[step - 1];
    $("stepNote").textContent = STEPNOTES[step - 1] || "";
    document.querySelectorAll(".step").forEach(function (f) {
      f.hidden = Number(f.dataset.step) !== step;
    });
    $("backBtn").disabled = step === 1;
    $("nextBtn").textContent = step === MAXSTEP ? "See what this means" : "Continue";
  }
  function setErr(id, msg) {
    var e = $("err-" + id), i = $(id);
    e.textContent = msg || "";
    e.classList.toggle("show", !!msg);
    i.setAttribute("aria-invalid", msg ? "true" : "false");
    return !msg;
  }
  function validStep() {
    if (step === 1) {
      var a = $("age").value;
      if (a === "") return setErr("age", "Enter an age so the check knows which thresholds apply.");
      a = Number(a);
      if (!(a >= 1 && a <= 120)) return setErr("age", "Enter an age between 1 and 120.");
      return setErr("age", "");
    }
    if (step === 4) {
      var ok = true;
      var gt = $("gluType").value, g = $("glucose").value;
      if (gt !== "none") {
        if (g === "") ok = setErr("glucose", "Enter the result, or set the test type back to “No glucose result”.") && ok;
        else if (Number(g) < 20 || Number(g) > 900) ok = setErr("glucose", "A value outside 20–900 mg/dL is not plausible. Check the units.") && ok;
        else ok = setErr("glucose", "") && ok;
      } else ok = setErr("glucose", "") && ok;
      var h = $("hba1c").value;
      if (h !== "" && (Number(h) < 3 || Number(h) > 20)) ok = setErr("hba1c", "HbA1c outside 3–20% is not plausible.") && ok;
      else ok = setErr("hba1c", "") && ok;
      return ok;
    }
    return true;
  }
  function collect() {
    var gt = $("gluType").value;
    data = {
      age: Number($("age").value),
      sex: $("sex").value === "Female" ? "female" : ($("sex").value === "Male" ? "male" : "not_given"),
      municipality: $("muni").value || null,
      family_history_t1d: $("fam").value,
      family_autoimmune: $("autoimm").value,
      symptoms: Array.prototype.map.call(document.querySelectorAll(".sym:checked"), function (c) { return c.value; }),
      urgent_signs: Array.prototype.map.call(document.querySelectorAll(".dka:checked"), function (c) { return c.value; }),
      glucose_test_type: gt,
      glucose_mgdl: gt === "none" || $("glucose").value === "" ? null : Number($("glucose").value),
      hba1c_pct: $("hba1c").value === "" ? null : Number($("hba1c").value),
      autoantibodies: $("aab").value,
      consent_to_store: false
    };
  }
  function buildReview() {
    collect();
    var rows = [
      ["Age", data.age + " years"],
      ["Sex", data.sex.replace("_", " ")],
      ["Municipality", data.municipality || "not given"],
      ["First-degree relative with Type 1", { yes: "Yes", no: "No", unknown: "Unknown" }[data.family_history_t1d]],
      ["Autoimmune conditions in family", { yes: "Yes", no: "None known", unknown: "Unknown" }[data.family_autoimmune]],
      ["Symptoms reported", data.symptoms.length ? data.symptoms.map(function (s) { return SYMLABEL[s]; }).join(", ") : "none ticked"],
      ["Urgent signs", data.urgent_signs.length ? data.urgent_signs.length + " ticked" : "none ticked"],
      ["Glucose", data.glucose_mgdl === null ? "not provided" : data.glucose_mgdl + " mg/dL (" + data.glucose_test_type + ")"],
      ["HbA1c", data.hba1c_pct === null ? "not provided" : data.hba1c_pct + " %"],
      ["Islet autoantibodies", { none: "Not tested", negative: "Negative", one_positive: "One positive", two_or_more_positive: "Two or more positive" }[data.autoantibodies]]
    ];
    var tb = document.querySelector("#reviewTable tbody");
    clear(tb);
    rows.forEach(function (r) {
      var tr = document.createElement("tr");
      var th = document.createElement("th"); th.scope = "row"; th.textContent = r[0];
      var td = document.createElement("td"); td.textContent = r[1];
      tr.appendChild(th); tr.appendChild(td); tb.appendChild(tr);
    });
  }

  function renderResult(body) {
    var host = $("resultBody"); clear(host);
    var kind = body.emergency ? "danger" : (["urgent", "followup"].indexOf(body.tier) >= 0 ? "warn" : "info");
    var URGENCY = {
      emergency: "Seek care now", urgent: "Follow up soon", followup: "Worth checking",
      insufficient: "More information needed", no_threshold: "Nothing crossed today"
    };
    var ALERT_ICON = body.emergency
      ? '<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.2 2.5 17a2 2 0 0 0 1.7 3h15.6a2 2 0 0 0 1.7-3L13.7 3.2a2 2 0 0 0-3.4 0z"/>'
      : '<path d="M20.8 8.6a5.5 5.5 0 0 0-9.3-2.9l-.5.5-.5-.5A5.5 5.5 0 0 0 3.2 13l8.3 8.3 8.3-8.3a5.5 5.5 0 0 0 1-4.4z"/>';
    var alert = el("div", "resultalert note-" + kind);
    var ai = el("span", "alerticon");
    ai.setAttribute("aria-hidden", "true");
    ai.innerHTML = '<svg width="23" height="23" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
      + 'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + ALERT_ICON + "</svg>";
    alert.appendChild(ai);
    var ab = el("div", "alertbody");
    ab.appendChild(el("span", "alert-eyebrow",
      body.emergency ? "ACT NOW" : "A NEXT STEP TO CONSIDER"));
    ab.appendChild(el("h2", null, body.headline));
    ab.appendChild(el("p", null, body.explanation));
    alert.appendChild(ab);
    alert.appendChild(el("span", "urgency", URGENCY[body.tier] || body.tier));
    host.appendChild(alert);

    if (!body.emergency) {
      var prov = card("Method");
      prov.appendChild(el("p", null,
        "Evaluated against published diagnostic thresholds. " + body.model.detail));
      var s = el("p");
      s.innerHTML = "<small></small>";
      s.querySelector("small").textContent =
        "Model status: " + body.model.status + " · Version: " + (body.model.version || "none") +
        " · Prediction task: " + (body.model.prediction_task || "not yet defined") +
        " · Stored: " + (body.stored ? "yes" : "no");
      prov.appendChild(s);
      host.appendChild(prov);
    }

    body.reasons.forEach(function (r) {
      var c = card(r.label);
      c.appendChild(el("p", null, r.text));
      host.appendChild(c);
    });

    // The values that drove the result, on the same scale used elsewhere, so
    // the reasoning above can be checked against the numbers by eye.
    var inp = Store.lastInputs;
    if (!body.emergency && inp) {
      var hasG = inp.glucose_mgdl !== null && inp.glucose_test_type !== "none";
      var hasA = inp.hba1c_pct !== null;
      if (hasG || hasA) {
        var vals = card("Your values");
        if (hasG) {
          vals.appendChild(el("h3", null, SCALES[inp.glucose_test_type].label));
          var gs = el("div"); vals.appendChild(gs);
          renderScale(gs, SCALES[inp.glucose_test_type], inp.glucose_mgdl);
        }
        if (hasA) {
          var ah3 = el("h3", null, SCALES.hba1c.label);
          if (hasG) ah3.style.marginTop = "16px";
          vals.appendChild(ah3);
          var as = el("div"); vals.appendChild(as);
          renderScale(as, SCALES.hba1c, inp.hba1c_pct);
        }
        host.appendChild(vals);
      }
    }

    // Where to go next. An emergency result shows nothing here on purpose: the
    // only instruction on that screen should be to seek emergency care.
    if (!body.emergency) {
      var where = card(inp && inp.municipality
        ? "Testing centres for " + inp.municipality : "Where to get tested");
      var wbody = el("div"); where.appendChild(wbody);
      host.appendChild(where);
      renderNearby(wbody, inp && inp.municipality);
    }

    var src = card("Reference");
    var sp = el("p"); sp.innerHTML = "<small></small>";
    sp.querySelector("small").textContent = body.threshold_source;
    src.appendChild(sp);
    host.appendChild(src);

    var row = el("div", "btnrow");
    row.style.marginTop = "16px";
    [["Find a testing centre", "#centers", "btn-primary"],
     ["See your parameters", "#parameters", "btn-ghost"],
     ["Read about Type 1", "#learn", "btn-ghost"],
     ["Start over", "#assess", "btn-ghost"]].forEach(function (b) {
      var a = el("a", "btn " + b[2], b[0]); a.href = b[1]; row.appendChild(a);
    });
    var pr = el("button", "btn btn-ghost", "Print this result");
    pr.type = "button";
    pr.addEventListener("click", function () { window.print(); });
    row.appendChild(pr);
    host.appendChild(row);
  }

  function renderNearby(host, municipality) {
    clear(host);
    if (!municipality) {
      host.appendChild(el("p", null,
        "You did not give a municipality, so no list can be tailored. The map shows every testing centre on record."));
      var b0 = el("div", "btnrow");
      var a0 = el("a", "btn btn-primary btn-sm", "Open the map"); a0.href = "#centers";
      b0.appendChild(a0); host.appendChild(b0);
      return;
    }
    host.innerHTML = '<div class="skel"></div><div class="skel"></div>';
    Api.call("/api/v1/facilities/nearby?limit=4&municipality=" + encodeURIComponent(municipality))
      .then(function (b) {
        clear(host);
        if (!b.items.length) {
          host.appendChild(emptyState("No testing centres on record",
            "Ask at your municipal health office, which can tell you what is available locally.", "pin"));
          return;
        }
        if (!b.confirmed_in_municipality) {
          host.appendChild(note("info", null,
            "No facility in " + b.municipality + " has a confirmed diabetes test on record yet. "
            + "The nearest ones with a confirmed service are listed first."));
        }
        b.items.forEach(function (n) {
          var f = n.facility;
          var row = el("div", "nearrow");
          var top = el("div", "neartop");
          top.appendChild(el("strong", null, f.name));
          var where = f.municipality + (n.distance_km !== null ? " · about " + n.distance_km + " km" : "");
          top.appendChild(el("span", "nearmeta", where));
          row.appendChild(top);
          if (f.contact) row.appendChild(el("div", "nearmeta", f.contact));
          row.appendChild(serviceRow(f, true));
          host.appendChild(row);
        });
        var basis = el("p"); basis.innerHTML = "<small></small>";
        basis.querySelector("small").textContent = b.distance_basis
          + " Call first to confirm the service and whether a referral is needed.";
        host.appendChild(basis);
        var br = el("div", "btnrow");
        var am = el("a", "btn btn-ghost btn-sm", "See all on the map"); am.href = "#centers";
        br.appendChild(am); host.appendChild(br);
      })
      .catch(function (err) {
        clear(host);
        host.appendChild(note("warn", null, Api.describe(err)));
      });
  }

  function renderResultError(err) {
    var host = $("resultBody"); clear(host);
    var n = note("warn", "No result could be produced", Api.describe(err));
    n.appendChild(el("p", null, "Nothing you entered was lost. Go back and submit again once the connection is working."));
    host.appendChild(n);
    var row = el("div", "btnrow");
    var a = el("a", "btn btn-primary", "Back to the assessment"); a.href = "#assess";
    row.appendChild(a); host.appendChild(row);
  }

  function submitAssessment() {
    collect();
    var btn = $("nextBtn");
    btn.disabled = true; $("backBtn").disabled = true;
    btn.textContent = "Checking…";
    Api.call("/api/v1/assessments", { method: "POST", body: JSON.stringify(data) })
      .then(function (body) {
        Store.lastResult = body;
        Store.lastInputs = data;
        Store.history.push({
          at: stamp(), tier: body.tier, headline: body.headline,
          tagClass: body.emergency ? "tag-bad" : (["urgent", "followup"].indexOf(body.tier) >= 0 ? "tag-warn" : "tag-ok"),
          labs: [data.glucose_mgdl !== null ? "glucose" : null, data.hba1c_pct !== null ? "HbA1c" : null,
                 data.autoantibodies !== "none" ? "antibodies" : null].filter(Boolean).join(", ") || "none",
          model: body.model.available ? body.model.version : "not trained"
        });
        renderResult(body);
        location.hash = "#results";
      })
      .catch(function (err) { renderResultError(err); location.hash = "#results"; })
      .then(function () {
        btn.disabled = false; $("backBtn").disabled = step === 1;
        paintSteps();
      });
  }

  /* ============================================================ chat */
  var Chat = {
    open: false,
    history: [],   // in memory only, sent for context, never stored anywhere
    log: function () { return $("chatLog"); },
    bubble: function (text, who) {
      var row = el("div", "chatrow " + (who === "me" ? "me" : "bot"));
      if (who !== "me") {
        var av = document.createElement("img");
        av.className = "miniavatar";
        av.src = "/assets/candie-avatar.png";
        av.alt = "";
        av.width = 28; av.height = 28;
        row.appendChild(av);
      }
      var d = el("div", "bubble " + who);
      String(text).split("\n").forEach(function (para) {
        if (para) d.appendChild(el("p", null, para));
      });
      if (who === "me") {
        d.appendChild(el("span", "msgtime", new Date().toLocaleTimeString([],
          { hour: "2-digit", minute: "2-digit" })));
      }
      row.appendChild(d);
      this.log().appendChild(row);
      this.log().scrollTop = this.log().scrollHeight;
      return d;
    },
    greet: function () {
      clear(this.log());
      this.history = [];
      this.syncSuggestions();
      this.log().appendChild(el("div", "chatday",
        new Date().toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" })
          .toUpperCase()));
      this.bubble("Hi! I'm Candie. I can help you understand the screening, explore local services, or find trusted information about Type 1 diabetes. What's on your mind?", "bot");
    },
    toggle: function (force) {
      this.open = force === undefined ? !this.open : force;
      $("chatPanel").classList.toggle("open", this.open);
      $("chatFab").setAttribute("aria-expanded", String(this.open));
      var sheet = window.innerWidth < 1024;
      var scrim = $("chatScrim");
      if (scrim) {
        scrim.hidden = !(this.open && sheet);
        scrim.classList.toggle("show", this.open && sheet);
      }
      document.body.style.overflow = (this.open && sheet) ? "hidden" : "";
      if (this.open) {
        this.syncSuggestions();
        warmUpModel();
        // Not focusing the input on a phone: the keyboard would cover the sheet
        // before the greeting has been read.
        if (!sheet) $("chatInput").focus();
      } else {
        $("chatPanel").classList.remove("sheet-peek");
      }
    },
    /* Chips are a prompt for the first question. Once anything has been asked
       they are clutter, so visibility follows the conversation, not a one-off
       flag that an early return could skip. */
    syncSuggestions: function () { },
    /* "Explain my latest assessment" is answered from the stored API response,
       never regenerated. If there is no result, it says so rather than inventing. */
    explainLatest: function () {
      if (!Store.lastResult) {
        this.bubble("You have not completed an assessment in this tab yet, so there is nothing for me to explain. I will not invent a result. Open Risk assessment from the menu and the five steps take about a minute.", "bot");
        return true;
      }
      var r = Store.lastResult;
      var txt = "Your recorded result was: " + r.headline + ".\n\n" + r.explanation;
      if (r.reasons && r.reasons.length) {
        txt += "\n\nThe server gave these reasons: " + r.reasons.map(function (x) { return x.text; }).join(" ");
      }
      txt += "\n\nThis came from a rule check against published thresholds, not from a trained model (" +
        (r.model.available ? "model " + r.model.version : "no model is loaded") +
        "). It is not a diagnosis, and a clinician has to interpret your actual results.";
      this.bubble(txt, "bot");
      Voice.speak(txt);
      this.history.push({ role: "assistant", content: txt.slice(0, 900) });
      return true;
    },
    send: function (q) {
      this.history.push({ role: "user", content: q });
      this.syncSuggestions();
      this.bubble(q, "me");
      var self = this;
      var lower = q.toLowerCase();
      if (/\b(my|latest|last)\b.*(assessment|result)|explain my/.test(lower)) {
        if (this.explainLatest()) return;
      }
      var pending = this.bubble("", "bot");
      pending.classList.add("thinking");
      pending.setAttribute("aria-label", "Candie is thinking");
      pending.innerHTML = "<i></i><i></i><i></i>";
      // A local model loads ~2 GB into RAM on its first call, routinely 30-60 s
      // on CPU. Say so rather than letting the user watch a silent dot.
      // After a few seconds, explain the wait rather than leaving dots alone.
      var slowTimer = setTimeout(function () {
        if (!pending.classList.contains("thinking")) return;
        var note = el("span", "thinking-note",
          "loading the language model, this is slow only the first time");
        pending.appendChild(note);
      }, 7000);

      Api.call("/api/v1/chat", {
        method: "POST",
        body: JSON.stringify({ message: q, history: self.history.slice(-6) })
      }, 180000)
        .then(function (body) {
          clearTimeout(slowTimer);
          pending.classList.remove("thinking");
          pending.removeAttribute("aria-label");
          clear(pending);
          String(body.reply).split("\n\n").forEach(function (p) { pending.appendChild(el("p", null, p)); });
          if (body.refused || body.route === "declined") pending.className = "bubble sys";

          // Label every answer with how it was produced. A reader should never
          // have to guess whether a sentence is reviewed text or generated.
          // Reviewed and generated answers must be tellable apart at a glance.
          // A reviewed answer names the document behind it; a generated one is
          // tinted and labelled as unreviewed.
          var CHECK = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" '
            + 'stroke="currentColor" stroke-width="3" stroke-linecap="round" '
            + 'stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>';
          var WARN = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" '
            + 'stroke="currentColor" stroke-width="2.4" stroke-linecap="round" '
            + 'aria-hidden="true"><path d="M12 8v5M12 17h.01"/>'
            + '<path d="M10.3 3.2 2.5 17a2 2 0 0 0 1.7 3h15.6a2 2 0 0 0 1.7-3L13.7 3.2a2 2 0 0 0-3.4 0z"/></svg>';
          if (body.route === "open") {
            pending.classList.add("generated");
            var gp = el("p", "prov gen");
            gp.innerHTML = WARN;
            gp.appendChild(document.createTextNode("Generated — not reviewed by the research team"));
            pending.appendChild(gp);
          } else if (body.route === "grounded" || body.route === "emergency") {
            pending.classList.add("reviewed");
            var src = body.matched_topic === "facility_lookup"
              ? "From the facility records"
              : (SOURCE_OF[body.matched_topic] || "Reviewed answer");
            var rp = el("p", "prov");
            rp.innerHTML = CHECK;
            rp.appendChild(document.createTextNode("Reviewed · " + src));
            pending.appendChild(rp);
          }

          Voice.speak(body.reply);
          self.history.push({ role: "assistant", content: String(body.reply).slice(0, 900) });
          if (self.history.length > 8) self.history = self.history.slice(-8);

          $("chatMode").textContent = body.mode === "rule_based" ? "Local corpus" : "AI assisted";
        })
        .catch(function (err) {
          clearTimeout(slowTimer);
          pending.classList.remove("thinking");
          pending.removeAttribute("aria-label");
          clear(pending);
          pending.className = "bubble sys";
          pending.appendChild(el("p", null,
            (err && err.name === "AbortError")
              ? "The model did not answer in three minutes. It is probably too large for "
                + "this computer. In PowerShell run: ollama pull llama3.2:1b — the smaller "
                + "model is detected automatically. Settings has a diagnostic that times it."
              : Api.describe(err)));
        });
    }
  };

  var warmed = false;
  function warmUpModel() {
    if (warmed) return;
    warmed = true;
    // Fire and forget: moves the 30-60 s model load off the first question.
    Api.call("/api/v1/chat/warmup", { method: "POST" }, 240000).catch(function () {
      warmed = false;   // let the next open try again
    });
  }

  var SOURCE_OF = {};
  function loadChatTopics() {
    return Api.call("/api/v1/chat/topics").then(function (b) {
      b.topics.forEach(function (t) { SOURCE_OF[t.id] = t.source; });
      $("chatMode").textContent = b.open_answering ? "AI assisted" : "Reviewed topics";
      var tag = $("aiTag"), state = $("aiState"), setup = $("aiSetup");
      if (!tag) return;
      if (b.open_answering) {
        tag.textContent = "Open conversation on";
        tag.className = "tag tag-ok";
        state.textContent = "Connected to " + ((b.assistant && b.assistant.model) || "a language model")
          + " (" + ((b.assistant && b.assistant.source) || "configured") + "). Candie can answer questions outside the "
          + b.topic_count + " reviewed topics. Clinical questions remain restricted to reviewed sources.";
        setup.hidden = true;
      } else {
        tag.textContent = "Reviewed topics only";
        tag.className = "tag tag-warn";
        state.textContent = "Candie answers from " + b.topic_count
          + " reviewed topics. No language model was found on this computer, so questions outside that set are not answered.";
        setup.hidden = false;
      }
    }).catch(function () { /* attribution is a nicety; silence is correct here */ });
  }

  var Drag = {
    attach: function (panel, handle) {
      var sx = 0, sy = 0, ox = 0, oy = 0, active = false;

      var sheetStartY = 0, sheetDragging = false;

      function sheetDown(e) {
        if (e.target.closest("button")) return;
        sheetStartY = e.clientY;
        sheetDragging = true;
        panel.classList.add("dragging");
        handle.setPointerCapture(e.pointerId);
      }

      function sheetMove(e) {
        if (!sheetDragging) return;
        var dy = Math.max(0, e.clientY - sheetStartY);
        panel.style.transform = "translateY(" + dy + "px)";
      }

      function sheetUp(e) {
        if (!sheetDragging) return;
        sheetDragging = false;
        panel.classList.remove("dragging");
        var dy = Math.max(0, e.clientY - sheetStartY);
        panel.style.transform = "";
        try { handle.releasePointerCapture(e.pointerId); } catch (err) { }
        // A short drag springs back; a long one dismisses, as in any sheet.
        if (dy > 110) { Chat.toggle(false); $("chatFab").focus(); }
      }

      function down(e) {
        // Buttons in the header keep working; only the bar itself drags.
        if (e.target.closest("button")) return;
        if (window.innerWidth < 1024) { sheetDown(e); return; }
        var r = panel.getBoundingClientRect();
        panel.style.left = r.left + "px";
        panel.style.top = r.top + "px";
        panel.style.right = "auto";
        panel.style.bottom = "auto";
        ox = r.left; oy = r.top;
        sx = e.clientX; sy = e.clientY;
        active = true;
        panel.classList.add("dragging");
        handle.setPointerCapture(e.pointerId);
      }

      function move(e) {
        if (window.innerWidth < 1024) { sheetMove(e); return; }
        if (!active) return;
        var r = panel.getBoundingClientRect();
        // Keep at least a strip of the panel on screen so it cannot be lost.
        var x = Math.min(Math.max(ox + e.clientX - sx, 8 - r.width + 120), window.innerWidth - 120);
        var y = Math.min(Math.max(oy + e.clientY - sy, 8), window.innerHeight - 60);
        panel.style.left = x + "px";
        panel.style.top = y + "px";
      }

      function up(e) {
        if (window.innerWidth < 1024) { sheetUp(e); return; }
        if (!active) return;
        active = false;
        panel.classList.remove("dragging");
        try { handle.releasePointerCapture(e.pointerId); } catch (err) { }
      }

      handle.addEventListener("pointerdown", down);
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", up);
      handle.addEventListener("pointercancel", up);

      // A resize can leave the panel off-screen; snap it back to the corner.
      window.addEventListener("resize", function () {
        if (window.innerWidth < 1024 || !panel.style.left) {
          panel.style.left = panel.style.top = "";
          panel.style.right = ""; panel.style.bottom = "";
          return;
        }
        var r = panel.getBoundingClientRect();
        if (r.left > window.innerWidth - 120 || r.top > window.innerHeight - 60) {
          panel.style.left = panel.style.top = "";
          panel.style.right = ""; panel.style.bottom = "";
        }
      });
    }
  };
  /* ============================================================ init */
  var SUGGESTIONS = [

  ];

  function wire() {
    buildNav();
    // ... rest of wire() unchanged ...

    $("burger").addEventListener("click", function () {
      $("rail").classList.contains("open") ? closeRail() : openRail();
    });
    $("scrim").addEventListener("click", closeRail);
    var chatScrim = $("chatScrim");
    if (chatScrim) chatScrim.addEventListener("click", function () { Chat.toggle(false); });
    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      if ($("rail").classList.contains("open")) { closeRail(); $("burger").focus(); }
      else if (Chat.open) { Chat.toggle(false); $("chatFab").focus(); }
    });
    $("railToggle").addEventListener("click", function () {
      var collapsed = document.documentElement.getAttribute("data-rail") === "collapsed";
      document.documentElement.setAttribute("data-rail", collapsed ? "expanded" : "collapsed");
      this.setAttribute("aria-pressed", String(!collapsed));
    });

    window.addEventListener("hashchange", function () {
      show((location.hash || "#dashboard").replace(/^#/, ""));
    });

    /* assessment */
    $("nextBtn").addEventListener("click", function () {
      if (!validStep()) {
        var bad = document.querySelector(".err.show");
        if (bad) bad.parentElement.querySelector("input").focus();
        return;
      }
      if (step === MAXSTEP) { submitAssessment(); return; }
      step++;
      if (step === MAXSTEP) buildReview();
      paintSteps();
      window.scrollTo(0, 0);
    });
    $("backBtn").addEventListener("click", function () {
      if (step > 1) { step--; paintSteps(); window.scrollTo(0, 0); }
    });
    function liveGlucose() {
      var t = $("gluType").value;
      if (t === "none") { clear($("gluScale")); return; }
      renderScale($("gluScale"), SCALES[t], $("glucose").value === "" ? null : Number($("glucose").value));
    }
    function liveA1c() {
      renderScale($("a1cScale"), SCALES.hba1c, $("hba1c").value === "" ? null : Number($("hba1c").value));
    }
    $("gluType").addEventListener("change", function () {
      $("gluWrap").hidden = this.value === "none";
      liveGlucose();
    });
    $("glucose").addEventListener("input", liveGlucose);
    $("hba1c").addEventListener("input", liveA1c);
    liveA1c();
    document.querySelectorAll(".dka").forEach(function (c) {
      c.addEventListener("change", function () {
        var n = document.querySelectorAll(".dka:checked").length;
        $("dkaAlert").hidden = n < 2;
        if (n >= 2) $("dkaAlert").scrollIntoView({ block: "center" });
      });
    });
    paintSteps();

    /* centres */
    ["fSearch", "fMuni", "fSvc", "fStatus", "fType"].forEach(function (id) {
      $(id).addEventListener(id === "fSearch" ? "input" : "change", renderFacilities);
    });
    $("fReset").addEventListener("click", function () {
      $("fSearch").value = ""; $("fMuni").value = ""; $("fSvc").value = ""; $("fStatus").value = ""; $("fType").value = "";
      renderFacilities();
    });
    $("viewMap").addEventListener("click", function () {
      $("mapCard").hidden = false;
      this.setAttribute("aria-pressed", "true");
      $("viewList").setAttribute("aria-pressed", "false");
    });
    $("viewList").addEventListener("click", function () {
      $("mapCard").hidden = true;
      this.setAttribute("aria-pressed", "true");
      $("viewMap").setAttribute("aria-pressed", "false");
      $("facilityList").scrollIntoView({ block: "start" });
    });

    $("addFacility").addEventListener("click", function () {
      var flash = $("facilityFlash");
      function say(msg, kind) { flash.hidden = false; flash.className = "note note-" + kind; flash.textContent = msg; }
      if (!Auth.isStaff()) {
        say("Facility records can only be added by a researcher or admin account. Sign in from the top bar.", "warn");
        return;
      }
      var name = $("nfName").value.trim();
      if (!name) { $("nfName").focus(); return; }
      var date = $("nfDate").value || null;
      var source = $("nfSource").value.trim() || null;
      var services = Array.prototype.map.call(document.querySelectorAll(".nfSvc:checked"), function (c) {
        return { service_code: c.value, confirmed: true, source: source, verified_on: date };
      });
      var lat = $("nfLat").value, lon = $("nfLon").value;
      var payload = {
        name: name, facility_type: $("nfType").value, municipality: $("nfMuni").value,
        address: $("nfAddress").value.trim() || null,
        latitude: lat === "" ? null : Number(lat), longitude: lon === "" ? null : Number(lon),
        contact: $("nfContact").value.trim() || null,
        source: source, verified_on: date, services: services
      };
      var btn = this; btn.disabled = true; btn.textContent = "Saving…";
      Api.call("/api/v1/facilities", {
        method: "POST", body: JSON.stringify(payload),
        headers: Auth.headers()
      }).then(function (f) {
        say("Saved “" + f.name + "” as " + f.status + ".", "ok");
        $("nfName").value = ""; $("nfContact").value = ""; $("nfAddress").value = "";
        document.querySelectorAll(".nfSvc:checked").forEach(function (c) { c.checked = false; });
        renderFacilities();
      }).catch(function (err) {
        say(Api.describe(err), "warn");
      }).then(function () { btn.disabled = false; btn.textContent = "Save record"; });
    });

    /* history */
    $("clearHistory").addEventListener("click", function () {
      Store.history = [];
      RENDER.reports();
    });

    /* settings */
    $("setTheme").value = Settings.data.theme;
    $("setDensity").value = Settings.data.density;
    $("setMotion").checked = Settings.data.motion;
    $("setApi").value = Settings.data.api;
    $("setTheme").addEventListener("change", function () { Settings.data.theme = this.value; Settings.save(); });
    $("setDensity").addEventListener("change", function () { Settings.data.density = this.value; Settings.save(); });
    $("setMotion").addEventListener("change", function () { Settings.data.motion = this.checked; Settings.save(); });
    $("setApi").addEventListener("change", function () { Settings.data.api = this.value.trim(); Settings.save(); pingHealth(); });

    var tileSel = $("setTileProvider");
    TILE_PROVIDERS.forEach(function (p) { tileSel.appendChild(new Option(p.name, p.id)); });
    tileSel.value = Settings.data.tileProvider;
    function reloadMap() {
      MapView.map = null; MapView.tiles = null; MapView.failed = false;
      MapView.failedUrls = null;
      $("leafmap").hidden = false; $("locator").hidden = true;
      if (location.hash === "#centers") renderFacilities();
    }
    tileSel.addEventListener("change", function () {
      Settings.data.tileProvider = this.value; Settings.save(); reloadMap();
    });
    $("setTiles").value = Settings.data.tileUrl;
    $("setTiles").addEventListener("change", function () {
      Settings.data.tileUrl = this.value.trim(); Settings.save(); reloadMap();
    });
    $("setReset").addEventListener("click", function () {
      Settings.data = { theme: "auto", density: "normal", motion: false, api: "", municipality: "",
                        tileProvider: "esri-street", tileUrl: "", tileAttribution: "" };
      Settings.save();
      $("setTheme").value = "auto"; $("setDensity").value = "normal";
      $("setMotion").checked = false; $("setApi").value = "";
    });

    /* account */
    $("authBtn").addEventListener("click", function () { location.hash = "#account"; });
    $("tabLogin").addEventListener("click", function () { setAuthMode("login"); });
    $("tabRegister").addEventListener("click", function () { setAuthMode("register"); });
    setAuthMode("login");

    $("authForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var st = $("authStatus"), btn = $("authSubmit");
      var username = $("authUser").value.trim(), password = $("authPass").value;
      if (!username || !password) { st.textContent = "Enter a username and password."; return; }
      var path = authMode === "register" ? "/api/v1/auth/register" : "/api/v1/auth/login";
      var payload = { username: username, password: password };
      if (authMode === "register" && $("authName").value.trim()) payload.display_name = $("authName").value.trim();
      btn.disabled = true; st.textContent = authMode === "register" ? "Creating account…" : "Signing in…";
      Api.call(path, { method: "POST", body: JSON.stringify(payload) })
        .then(function (b) {
          Auth.set(b.token, username, b.role);
          $("authPass").value = "";
          st.textContent = "Signed in as " + username + " (" + b.role + ").";
          RENDER.account();
        })
        .catch(function (err) {
          st.textContent = err && err.status === 409
            ? "That username is taken. Pick another."
            : Api.describe(err);
        })
        .then(function () { btn.disabled = false; });
    });

    $("signOutBtn").addEventListener("click", function () {
      Auth.clear();
      $("authStatus").textContent = "Signed out.";
      setAuthMode("login");
    });

    $("deleteAccount").addEventListener("click", function () {
      if (!window.confirm("Delete your account and every assessment stored under it? This cannot be undone.")) return;
      Api.call("/api/v1/auth/me", { method: "DELETE", headers: Auth.headers() })
        .then(function (b) {
          Auth.clear();
          $("authStatus").textContent = "Account deleted. " + b.assessments_removed + " stored assessment(s) removed.";
          setAuthMode("login");
        })
        .catch(function (err) { $("authStatus").textContent = Api.describe(err); });
    });

    $("grantBtn").addEventListener("click", function () {
      var out = $("grantStatus");
      out.textContent = "Granting…";
      Api.call("/api/v1/auth/grant", {
        method: "POST", headers: Auth.headers(),
        body: JSON.stringify({ username: $("grantUser").value.trim(), role: $("grantRole").value })
      }).then(function (b) {
        out.textContent = b.username + " is now " + b.role + ".";
        loadAccounts();
      }).catch(function (err) { out.textContent = Api.describe(err); });
    });

    var recheck = $("aiRecheck");
    if (recheck) recheck.addEventListener("click", function () {
      this.disabled = true; this.textContent = "Checking…";
      var btn = this;
      loadChatTopics().then(function () {
        btn.disabled = false; btn.textContent = "Check again";
      });
    });

    /* onboarding */
    $("obNext").addEventListener("click", function () { Onboard.next(); });
    $("obBack").addEventListener("click", function () { Onboard.back(); });
    $("obSkip").addEventListener("click", function () { Onboard.close(false); });
    var replay = $("replayOnboard");
    if (replay) replay.addEventListener("click", function () { Onboard.open(0); });

    // Keep focus inside the dialog while it is open, and let Escape dismiss it.
    $("onboard").addEventListener("keydown", function (e) {
      if (e.key === "Escape") { Onboard.close(false); return; }
      if (e.key !== "Tab") return;
      var focusables = this.querySelectorAll(
        "button:not([disabled]), select, input, a[href]");
      if (!focusables.length) return;
      var first = focusables[0], last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });

    /* chat */
    $("chatFab").addEventListener("click", function () { Chat.toggle(); });

    var vbtn = $("chatVoice");
    if (!Voice.supported) { vbtn.hidden = true; }
    vbtn.addEventListener("click", function () {
      Voice.on = !Voice.on;
      this.setAttribute("aria-pressed", String(Voice.on));
      this.classList.toggle("voicepulse", Voice.on);
      this.title = Voice.on ? "Stop reading answers aloud" : "Read answers aloud";
      this.setAttribute("aria-label", this.title);
      if (!Voice.on) {
        Voice.stop();
      } else {
        Voice.speak("Voice is on. I will read my answers aloud.");
        // The ring marks that speech is in progress, not that it is enabled.
        var btn = this;
        setTimeout(function () { btn.classList.remove("voicepulse"); }, 2600);
      }
    });
    $("chatClose").addEventListener("click", function () { Chat.toggle(false); $("chatFab").focus(); });
    $("chatNew").addEventListener("click", function () { Chat.greet(); $("chatInput").focus(); });
    $("chatForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var i = $("chatInput"), q = i.value.trim();
      if (!q) return;
      i.value = "";
      Chat.send(q);
    });
    var sug = $("chatSug");
    SUGGESTIONS.forEach(function (s) {
        var b = el("button", null, s);
        b.type = "button";
        b.addEventListener("click", function () { Chat.send(s); });
        sug.appendChild(b);
    });
    Chat.greet();
    Drag.attach($("chatPanel"), $("chatPanel").querySelector("header"));

    $("askCandie").addEventListener("click", function () {
      Chat.toggle(true);
    });
  }

  function pingHealth() {
    var pill = $("apiPill"), txt = $("apiPillText");
    txt.textContent = "Checking…";
    pill.className = "pill";
    return Api.call("/health", {}, 8000).then(function (h) {
      Store.health = h;
      pill.className = "pill " + (h.status === "ok" ? "is-ok" : "is-warn");
      txt.textContent = h.status === "ok" ? "Connected" : "Server degraded";
      pill.title = "Build " + h.build + " · database " + h.database +
        (h.model === "unavailable"
          ? " · no model trained, assessment uses published thresholds"
          : " · model " + h.model);
    }).catch(function () {
      pill.className = "pill is-bad";
      txt.textContent = "Backend offline";
      pill.title = "The API could not be reached.";
    });
  }

  function loadMunicipalities() {
    return Api.call("/api/v1/municipalities").then(function (body) {
      Store.municipalities = body.items;
      var names = body.items.map(function (m) { return m.name; });
      [["muni", "Prefer not to say"], ["fMuni", "All municipalities"], ["nfMuni", null]].forEach(function (cfg) {
        var s = $(cfg[0]);
        clear(s);
        if (cfg[1]) s.appendChild(new Option(cfg[1], ""));
        names.forEach(function (n) { s.appendChild(new Option(n, n)); });
      });
      // A municipality chosen during onboarding pre-selects both dropdowns.
      if (Settings.data.municipality) {
        var pre = Settings.data.municipality;
        if (names.indexOf(pre) >= 0) {
          $("muni").value = pre;
          $("fMuni").value = pre;
        }
      }
      buildLocator();
    }).catch(function () {
      var s = $("fMuni");
      clear(s);
      s.appendChild(new Option("All municipalities", ""));
      $("locator").innerHTML = '<div class="empty" style="height:100%;display:grid;place-content:center">' +
        "<p>Municipality list unavailable while the backend is offline.</p></div>";
    });
  }

  Settings.load();
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();

  function bootMsg(text) {
    var n = $("bootMsg");
    if (n) n.textContent = text;
  }

  function hideBoot() {
    var b = $("boot");
    if (!b) return;
    b.classList.add("gone");
    setTimeout(function () { b.remove(); }, 400);
  }

  function boot() {
    Auth.load();
    wire();
    applyRole();
    bootMsg("Contacting the server");

    var started = Date.now();
    Promise.resolve()
      .then(function () { return pingHealth(); })
      .then(function () { bootMsg("Loading municipalities"); return loadMunicipalities(); })
      .then(function () { bootMsg("Loading assistant"); return loadChatTopics(); })
      .catch(function () { /* every step already handles its own failure */ })
      .then(function () {
        show((location.hash || "#dashboard").replace(/^#/, ""));
        // a flash of spinner is worse than a beat of it; hold ~500ms minimum
        var wait = Math.max(0, 500 - (Date.now() - started));
        setTimeout(function () {
          hideBoot();
          // After the loading screen, so the two are never stacked. Not shown
          // when a link points at a specific view: that person came for it.
          if (Onboard.shouldShow() && !location.hash) {
            setTimeout(function () { Onboard.open(0); }, 260);
          }
        }, wait);
      });
  }
})();
