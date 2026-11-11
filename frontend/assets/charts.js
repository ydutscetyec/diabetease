/* Minimal accessible SVG charts. No library: the whole module is ~5 kB and
   works offline, which matters more here than feature count.

   Every chart renders a <title> and a <desc> plus a visually hidden data table,
   so a screen reader gets the numbers rather than an unlabelled graphic. */
(function (global) {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";
  function el(name, attrs) {
    var n = document.createElementNS(NS, name);
    for (var k in attrs) if (attrs[k] !== undefined && attrs[k] !== null) n.setAttribute(k, attrs[k]);
    return n;
  }
  function css(name, fallback) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }
  function fmt(v, dp) {
    if (v === null || v === undefined || isNaN(v)) return "—";
    return dp === 0 ? String(Math.round(v)) : Number(v).toFixed(dp === undefined ? 1 : dp);
  }

  function dataTable(rows, head) {
    var w = document.createElement("div");
    w.className = "vh";
    var t = document.createElement("table");
    var tr = document.createElement("tr");
    head.forEach(function (h) { var th = document.createElement("th"); th.textContent = h; tr.appendChild(th); });
    t.appendChild(tr);
    rows.forEach(function (r) {
      var row = document.createElement("tr");
      r.forEach(function (c) { var td = document.createElement("td"); td.textContent = c; row.appendChild(td); });
      t.appendChild(row);
    });
    w.appendChild(t);
    return w;
  }

  /* -------------------------------------------------- reference-band chart
     A measured value plotted against published reference bands. Used for
     glucose and HbA1c, where the bands come from a citable source. Bands are
     labelled in text as well as colour, so colour never carries the meaning
     on its own. */
  function referenceBands(host, opt) {
    host.innerHTML = "";
    var W = 640, H = 92, padL = 8, padR = 8, barY = 26, barH = 26;
    var min = opt.min, max = opt.max, span = max - min;
    var innerW = W - padL - padR;
    var svg = el("svg", {
      class: "chart", viewBox: "0 0 " + W + " " + H, role: "img",
      "aria-labelledby": opt.id + "-t " + opt.id + "-d", preserveAspectRatio: "none",
      style: "height:" + H + "px"
    });
    svg.appendChild(Object.assign(el("title", { id: opt.id + "-t" }), { textContent: opt.label }));
    var descText = opt.value === null || opt.value === undefined
      ? "No value recorded for " + opt.label + "."
      : opt.label + " is " + fmt(opt.value, opt.dp) + " " + opt.unit + ", which falls in the " + opt.bandLabel + " band.";
    svg.appendChild(Object.assign(el("desc", { id: opt.id + "-d" }), { textContent: descText }));

    var x = function (v) { return padL + ((v - min) / span) * innerW; };

    opt.bands.forEach(function (b) {
      var x0 = x(Math.max(b.from, min)), x1 = x(Math.min(b.to, max));
      svg.appendChild(el("rect", {
        x: x0, y: barY, width: Math.max(1, x1 - x0), height: barH,
        fill: css(b.token, "#eee"), rx: 4
      }));
      if (x1 - x0 > 56) {
        var lab = el("text", { x: (x0 + x1) / 2, y: barY + barH + 15, "text-anchor": "middle" });
        lab.textContent = b.label;
        svg.appendChild(lab);
      }
    });
    svg.appendChild(el("rect", { x: padL, y: barY, width: innerW, height: barH, fill: "none", rx: 4, class: "axis" }));

    [min, max].forEach(function (v, i) {
      var t = el("text", { x: i === 0 ? padL : W - padR, y: barY - 8, "text-anchor": i === 0 ? "start" : "end" });
      t.textContent = fmt(v, 0) + (i === 1 ? " " + opt.unit : "");
      svg.appendChild(t);
    });

    if (opt.value !== null && opt.value !== undefined) {
      var cx = x(Math.min(Math.max(opt.value, min), max));
      svg.appendChild(el("line", { x1: cx, y1: barY - 5, x2: cx, y2: barY + barH + 5, stroke: css("--text", "#45364B"), "stroke-width": 2.5 }));
      svg.appendChild(el("circle", { cx: cx, cy: barY - 7, r: 4.5, fill: css("--text", "#45364B") }));
      var vt = el("text", {
        x: Math.min(Math.max(cx, 30), W - 30), y: barY - 14, "text-anchor": "middle",
        "font-weight": "700", fill: css("--text", "#45364B")
      });
      vt.textContent = fmt(opt.value, opt.dp);
      svg.appendChild(vt);
    }
    host.appendChild(svg);
    host.appendChild(dataTable(
      opt.bands.map(function (b) { return [b.label, fmt(b.from, opt.dp) + "–" + fmt(b.to, opt.dp) + " " + opt.unit]; })
        .concat(opt.value != null ? [["Recorded value", fmt(opt.value, opt.dp) + " " + opt.unit]] : []),
      [opt.label, "Range"]
    ));
  }

  /* --------------------------------------------------------- bar chart */
  function bars(host, opt) {
    host.innerHTML = "";
    var items = opt.items || [];
    if (!items.length) { host.innerHTML = '<div class="empty"><p>No data to chart yet.</p></div>'; return; }
    var W = 640, rowH = 34, padL = opt.labelWidth || 150, padR = 56;
    var H = items.length * rowH + 14;
    var maxV = Math.max.apply(null, items.map(function (i) { return i.value; }).concat([1]));
    var svg = el("svg", {
      class: "chart", viewBox: "0 0 " + W + " " + H, role: "img",
      "aria-labelledby": opt.id + "-t", style: "height:" + H + "px", preserveAspectRatio: "xMinYMin meet"
    });
    svg.appendChild(Object.assign(el("title", { id: opt.id + "-t" }), { textContent: opt.label }));

    items.forEach(function (it, i) {
      var y = i * rowH + 7;
      var lab = el("text", { x: padL - 10, y: y + 16, "text-anchor": "end" });
      lab.textContent = it.label;
      svg.appendChild(lab);
      var w = (it.value / maxV) * (W - padL - padR);
      svg.appendChild(el("rect", { x: padL, y: y + 4, width: W - padL - padR, height: 16, fill: css("--line", "#eee"), rx: 8 }));
      svg.appendChild(el("rect", { x: padL, y: y + 4, width: Math.max(it.value > 0 ? 3 : 0, w), height: 16, fill: css(it.token || "--green", "#64A985"), rx: 8 }));
      var val = el("text", { x: W - padR + 8, y: y + 17, "font-weight": "700", fill: css("--text", "#45364B") });
      val.textContent = fmt(it.value, 0);
      svg.appendChild(val);
    });
    host.appendChild(svg);
    host.appendChild(dataTable(items.map(function (i) { return [i.label, fmt(i.value, 0)]; }), [opt.label, "Count"]));
  }

  /* -------------------------------------------------------- line chart */
  function line(host, opt) {
    host.innerHTML = "";
    var pts = opt.points || [];
    if (pts.length < 2) {
      host.innerHTML = '<div class="empty"><h3>Not enough points to draw a trend</h3><p>' +
        (opt.emptyText || "A trend needs at least two recorded values.") + "</p></div>";
      return;
    }
    var W = 640, H = 220, padL = 44, padR = 14, padT = 14, padB = 34;
    var ys = pts.map(function (p) { return p.y; });
    var lo = Math.min.apply(null, ys), hi = Math.max.apply(null, ys);
    if (lo === hi) { lo -= 1; hi += 1; }
    var pad = (hi - lo) * 0.12; lo -= pad; hi += pad;
    var X = function (i) { return padL + (i / (pts.length - 1)) * (W - padL - padR); };
    var Y = function (v) { return padT + (1 - (v - lo) / (hi - lo)) * (H - padT - padB); };

    var svg = el("svg", { class: "chart", viewBox: "0 0 " + W + " " + H, role: "img", "aria-labelledby": opt.id + "-t", style: "height:" + H + "px" });
    svg.appendChild(Object.assign(el("title", { id: opt.id + "-t" }), { textContent: opt.label }));

    for (var g = 0; g <= 4; g++) {
      var v = lo + (g / 4) * (hi - lo), y = Y(v);
      svg.appendChild(el("line", { x1: padL, y1: y, x2: W - padR, y2: y, class: "gridline" }));
      var t = el("text", { x: padL - 8, y: y + 4, "text-anchor": "end" });
      t.textContent = fmt(v, opt.dp);
      svg.appendChild(t);
    }
    svg.appendChild(el("line", { x1: padL, y1: H - padB, x2: W - padR, y2: H - padB, class: "axis" }));

    var d = pts.map(function (p, i) { return (i ? "L" : "M") + X(i) + " " + Y(p.y); }).join(" ");
    svg.appendChild(el("path", { d: d, fill: "none", stroke: css("--green", "#64A985"), "stroke-width": 2.5, "stroke-linejoin": "round" }));
    pts.forEach(function (p, i) {
      svg.appendChild(el("circle", { cx: X(i), cy: Y(p.y), r: 4, fill: css("--card", "#fff"), stroke: css("--green", "#64A985"), "stroke-width": 2 }));
      if (i === 0 || i === pts.length - 1 || pts.length <= 6) {
        var lt = el("text", { x: X(i), y: H - padB + 16, "text-anchor": i === 0 ? "start" : (i === pts.length - 1 ? "end" : "middle") });
        lt.textContent = p.x;
        svg.appendChild(lt);
      }
    });
    host.appendChild(svg);
    host.appendChild(dataTable(pts.map(function (p) { return [p.x, fmt(p.y, opt.dp)]; }), ["Point", opt.label]));
  }

  global.Charts = { referenceBands: referenceBands, bars: bars, line: line };
})(window);
