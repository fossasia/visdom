/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

function buildExportHtml(title, paneData, validIds) {
  const safeData = JSON.stringify(paneData).replace(
    /<\/script/gi,
    '<\\/script'
  );
  const safeIds = JSON.stringify(validIds).replace(
    /<\/script/gi,
    '<\\/script'
  );
  const S = '<' + '/script>';
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>${title}</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js">${S}
<style>
*{box-sizing:border-box}
body{margin:0;padding:14px;font-family:Arial,sans-serif;background:#f0f2f5}
h1{text-align:center;color:#337ab7;font-size:1.2rem;margin:0 0 16px}
#board{display:flex;flex-wrap:wrap;gap:14px;align-items:flex-start}
.pw{background:#fff;border:1px solid #d1d5db;border-radius:5px;
    box-shadow:0 1px 5px rgba(0,0,0,.09);display:flex;flex-direction:column;
    resize:both;overflow:hidden;min-width:180px;min-height:120px}
.ph{background:#337ab7;color:#fff;padding:6px 10px;font-size:12px;
    font-weight:bold;flex-shrink:0;white-space:nowrap;overflow:hidden;
    text-overflow:ellipsis}
.pc{flex:1;overflow:auto;min-height:0;position:relative}
.pc img,.pc video{max-width:100%;height:auto;display:block;margin:auto}
.pc audio{width:100%;display:block}
.pad{padding:8px}
.pc table{width:100%;border-collapse:collapse;font-size:12px}
.pc td,.pc th{border:1px solid #e5e7eb;padding:4px 8px}
.pc th{background:#f5f7fa;font-weight:600}
.note{padding:10px;font-size:11px;color:#999;font-style:italic}
</style>
</head>
<body>
<h1>${title}</h1>
<div id="board"></div>
<script>
const DATA = ${safeData};
const IDS  = ${safeIds};

const plotEls = {};

function mkEl(tag, cls) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  return e;
}

function renderContent(id, pane, pc) {
  const c = pane.content;
  const t = pane.type;

  // Any Plotly-compatible pane (plot, surface, or unknown with .data)
  if ((t === 'plot' || t === 'surface') && c && c.data) {
    const layout = Object.assign({}, c.layout || {});
    layout.autosize = true;
    if (!layout.margin) layout.margin = {};
    layout.margin.b = Math.max(layout.margin.b || 0, 50);
    const w = mkEl('div');
    w.style.cssText = 'width:100%;height:100%;min-height:160px';
    pc.appendChild(w);
    Plotly.newPlot(
      w,
      c.data,
      layout,
      { responsive: true, scrollZoom: true }
    );
    plotEls[id] = w;
    return;
  }

  // Image
  if (t === 'image') {
    const src = c && (c.src || (typeof c === 'string' ? c : null));
    if (!src) {
      pc.innerHTML = '<p class="note">Image unavailable</p>';
      return;
    }
    const d = mkEl('div', 'pad');
    const img = mkEl('img'); img.src = src;
    d.appendChild(img); pc.appendChild(d);
    return;
  }

  // Image history
  if (t === 'image_history') {
    let src = c && c.src;
    if (!src && Array.isArray(c) && c.length) {
      const idx = typeof pane.selected === 'number'
        ? pane.selected : c.length - 1;
      const item = c[Math.min(c.length - 1, Math.max(0, idx))];
      src = item && (item.src || (typeof item === 'string' ? item : null));
    }
    if (!src) {
      pc.innerHTML = '<p class="note">Image unavailable</p>';
      return;
    }
    const d = mkEl('div', 'pad');
    const img = mkEl('img'); img.src = String(src);
    d.appendChild(img); pc.appendChild(d);
    return;
  }

  // Text
  if (t === 'text') {
    const d = mkEl('div', 'pad');
    d.style.fontSize = '13px';
    d.innerHTML = c ? String(c) : '';
    pc.appendChild(d);
    return;
  }

  // SVG
  if (t === 'svg') {
    const raw = c ? (c.content || (typeof c === 'string' ? c : '')) : '';
    const d = mkEl('div', 'pad');
    d.style.textAlign = 'center';
    d.innerHTML = raw;
    const s = d.querySelector('svg');
    if (s) { s.style.maxWidth = '100%'; s.style.height = 'auto'; }
    pc.appendChild(d);
    return;
  }

  // Audio
  if (t === 'audio') {
    const src = c
      && (c.src || c.contentUrl || (typeof c === 'string' ? c : null));
    if (!src) {
      pc.innerHTML = '<p class="note">Audio unavailable</p>';
      return;
    }
    const d = mkEl('div', 'pad');
    const a = mkEl('audio'); a.controls = true; a.src = String(src);
    d.appendChild(a); pc.appendChild(d);
    return;
  }

  // Video
  if (t === 'video') {
    const src = c
      && (c.src || c.contentUrl || (typeof c === 'string' ? c : null));
    if (!src) {
      pc.innerHTML = '<p class="note">Video unavailable</p>';
      return;
    }
    const d = mkEl('div', 'pad');
    const v = mkEl('video');
    v.controls = true;
    v.src = String(src);
    v.style.maxWidth = '100%';
    d.appendChild(v); pc.appendChild(d);
    return;
  }

  // Properties
  if (t === 'properties') {
    const props = Array.isArray(c) ? c : (c && c.properties) || [];
    const tbl = mkEl('table');
    tbl.innerHTML = '<thead><tr><th>Property</th><th>Value</th></tr></thead>';
    const tb = tbl.createTBody();
    props.forEach((p) => {
      if (!p) return;
      const r = tb.insertRow();
      r.insertCell().textContent = p.name || '';
      r.insertCell().textContent = p.value !== undefined ? String(p.value) : '';
    });
    pc.appendChild(tbl);
    return;
  }

  // Network -> Plotly scatter
  // Circular initial layout; edges as one line trace with null separators.
  if (t === 'network') {
    const nodes = (c && c.nodes) || [];
    const edges = (c && c.edges) || [];
    if (!nodes.length) {
      pc.innerHTML = '<p class="note">Network: no node data</p>';
      return;
    }

    const step = (2 * Math.PI) / nodes.length;
    const pos  = {};
    nodes.forEach((n, i) => {
      const nid = n.id !== undefined ? n.id : i;
      pos[nid] = {
        x: Math.cos(i * step - Math.PI / 2),
        y: Math.sin(i * step - Math.PI / 2),
      };
    });

    const ex = [], ey = [];
    edges.forEach((e) => {
      const from = e.from ?? (e.source && (e.source.id ?? e.source));
      const to   = e.to   ?? (e.target && (e.target.id ?? e.target));
      const f = pos[from];
      const t2 = pos[to];
      if (f && t2) { ex.push(f.x, t2.x, null); ey.push(f.y, t2.y, null); }
    });

    const traces = [];
    if (ex.length) {
      traces.push({
        type: 'scatter', mode: 'lines', x: ex, y: ey,
        line: { color: '#bbb', width: 1 },
        hoverinfo: 'none', showlegend: false,
      });
    }
    traces.push({
      type: 'scatter', mode: 'markers+text',
      x: nodes.map((n, i) => pos[n.id !== undefined ? n.id : i].x),
      y: nodes.map((n, i) => pos[n.id !== undefined ? n.id : i].y),
      text: nodes.map((n) => String(
        n.label !== undefined ? n.label
          : (n.id !== undefined ? n.id : ''),
      )),
      textposition: 'top center',
      marker:       { size: 10, color: '#337ab7', opacity: 0.85 },
      showlegend:   false,
    });

    const w = mkEl('div');
    w.style.cssText = 'width:100%;height:100%;min-height:160px';
    pc.appendChild(w);
    Plotly.newPlot(w, traces, {
      autosize: true,
      margin:   { t: 10, b: 10, l: 10, r: 10 },
      xaxis:    { showgrid: false, zeroline: false, showticklabels: false },
      yaxis:    { showgrid: false, zeroline: false, showticklabels: false },
    }, { responsive: true });
    plotEls[id] = w;
    return;
  }

  // Embeddings
  if (t === 'embeddings') {
    let xs, ys, labels = (c && c.labels) || [];

    const pts = c && (c.points || c.embeddings);
    if (Array.isArray(pts) && pts.length) {
      xs = pts.map((p) => p[0]);
      ys = pts.map((p) => p[1]);
    }
    else if (c && Array.isArray(c.x) && Array.isArray(c.y)) {
      xs = c.x; ys = c.y;
    }

    else if (c && Array.isArray(c.X) && c.X.length) {
      xs = c.X.map((p) => p[0]);
      ys = c.X.map((p) => p[1]);
      if (!labels.length && c.Y) labels = c.Y;
    }

    if (xs && xs.length) {
      const w = mkEl('div');
      w.style.cssText = 'width:100%;height:100%;min-height:160px';
      pc.appendChild(w);
      Plotly.newPlot(w, [{
        type: 'scatter', mode: labels.length ? 'markers+text' : 'markers',
        x: xs, y: ys,
        text:         labels,
        textposition: 'top center',
        textfont:     { size: 9 },
        marker:       { size: 5, opacity: 0.7 },
      }], {
        autosize: true,
        margin: { t: 20, b: 30, l: 30, r: 10 },
      }, { responsive: true });
      plotEls[id] = w;
      return;
    }
    pc.innerHTML = '<p class="note">Embeddings: unsupported data format</p>';
    return;
  }

  const note = mkEl('p', 'note');
  note.textContent = 'Type "' + t + '" not supported for export';
  pc.appendChild(note);
}

function renderPane(id) {
  const pane  = DATA[id];
  const board = document.getElementById('board');

  const pw = mkEl('div', 'pw');
  pw.style.width  = pane.initW + 'px';
  pw.style.height = pane.initH + 'px';

  const ph = mkEl('div', 'ph'); ph.textContent = pane.title;
  const pc = mkEl('div', 'pc');

  pw.appendChild(ph);
  pw.appendChild(pc);
  board.appendChild(pw);

  renderContent(id, pane, pc);
  if (window.ResizeObserver && plotEls[id]) {
    new ResizeObserver(() => {
      try { Plotly.Plots.resize(plotEls[id]); } catch (_) {}
    }).observe(pw);
  }
}

IDS.forEach(renderPane);
${S}
</body>
</html>`;
}

export default buildExportHtml;
