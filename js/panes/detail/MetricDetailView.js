/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import { Download, X } from 'lucide-react';
import React, { useContext, useEffect, useMemo, useRef, useState } from 'react';

import ApiContext from '../../api/ApiContext';
import { useAnnotations } from '../utils/annotations';

// exponential moving average, W&B-style: 0 = raw, -> 1 = very smooth.
// Causal (only looks backward), so it suits a live, ever-growing series:
// nothing it already drew is recomputed when a new point streams in.
const ema = (ys, weight) => {
  if (!weight) return ys.slice();
  const out = [];
  let last = null;
  for (let i = 0; i < ys.length; i++) {
    const v = ys[i];
    if (typeof v !== 'number' || Number.isNaN(v)) {
      out.push(v);
      continue;
    }
    last = last === null ? v : last * weight + v * (1 - weight);
    out.push(last);
  }
  return out;
};

// validated categorical order (shared with the planned Plotly template)
const COLORWAY = [
  '#2a78d6',
  '#eb6834',
  '#1baf7a',
  '#eda100',
  '#e87ba4',
  '#008300',
  '#4a3aa7',
  '#e34948',
];

const isLineTrace = (t) =>
  t && (t.type === undefined || t.type === 'scatter' || t.type === 'scattergl');

// a per-point marker.color array isn't a valid line.color, so only reuse a
// scalar color and fall back to the palette otherwise
const scalarColor = (c) => (typeof c === 'string' ? c : null);

const traceColor = (t, ordinal) =>
  scalarColor(t.line && t.line.color) ||
  scalarColor(t.marker && t.marker.color) ||
  COLORWAY[ordinal % COLORWAY.length];

// a single unnamed trace gets the literal name "1" from the server
// (scatter()'s Y defaults to np.ones), which isn't a real metric label, so
// fall back to the pane's own title instead of showing that raw digit.
// Multi-trace digit names (e.g. a multi-class scatter's class labels, or a
// multi-column line plot's 1..M series numbers) are real labels from the
// server and are shown as-is.
const isAutoNumericName = (name) => /^\d+$/.test(name);

const traceName = (t, i, paneTitle, total) => {
  const given = typeof t.name === 'string' ? t.name.trim() : '';
  if (total <= 1 && (!given || isAutoNumericName(given)) && paneTitle) {
    return paneTitle;
  }
  return given || `series ${i + 1}`;
};

const num = (v) => (typeof v === 'number' && !Number.isNaN(v) ? v : null);

const csvCell = (v) => {
  const s = String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

// traces aren't guaranteed to share one x axis (different length/cadence
// per trace), so match each trace's own x/y pairs and merge on the actual
// x value instead of assuming every trace's row r lines up with trace 0's
const buildMatchedRows = (traces, idxs) => {
  const byTrace = idxs.map((i) => {
    const t = traces[i];
    const txs = Array.isArray(t.x) ? t.x : [];
    const tys = Array.isArray(t.y) ? t.y : [];
    const map = new Map();
    txs.forEach((x, r) => map.set(x, tys[r]));
    return map;
  });
  const allX = new Set();
  byTrace.forEach((map) => map.forEach((_, x) => allX.add(x)));
  return [...allX]
    .sort((a, b) => a - b)
    .map((x) => ({
      x,
      values: byTrace.map((map) => (map.has(x) ? map.get(x) : undefined)),
    }));
};

function MetricDetailView({ pane, envID, onClose }) {
  const isPlot = pane.type === 'plot' || pane.type === 'plot_history';
  const isHistory = pane.type === 'plot_history';

  const plotRef = useRef(null);
  const storageKey = `${envID}_${pane.id}_detail`;
  const { sendPlotLayoutUpdate, sessionInfo } = useContext(ApiContext);

  const [settings, setSettings] = useState(() => {
    const fallback = {
      points: true,
      smoothing: 0,
      logY: false,
      hidden: [],
      frame: 0,
    };
    try {
      const raw = localStorage.getItem(storageKey);
      return raw ? { ...fallback, ...JSON.parse(raw) } : fallback;
    } catch (e) {
      return fallback;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(settings));
    } catch (e) {
      // storage unavailable
    }
  }, [settings, storageKey]);

  const set = (patch) => setSettings((s) => ({ ...s, ...patch }));

  const content = useMemo(() => {
    if (!isHistory) return pane.content || {};
    const arr = Array.isArray(pane.content) ? pane.content : [pane.content];
    return arr[Math.min(settings.frame, arr.length - 1)] || arr[0] || {};
  }, [pane.content, isHistory, settings.frame]);

  const annotations = useAnnotations({
    plotlyRef: plotRef,
    content,
    envID,
    paneID: pane.id,
    frame: settings.frame,
    sendPlotLayoutUpdate,
    readonly: sessionInfo?.readonly,
  });

  const allTraces =
    (content && Array.isArray(content.data) && content.data) || [];
  const names = allTraces.map((t, i) =>
    traceName(t, i, pane.title, allTraces.length)
  );
  const hiddenSet = new Set(settings.hidden);
  const visibleIdx = allTraces
    .map((_, i) => i)
    .filter((i) => !hiddenSet.has(names[i]));

  // ----- per-step stats table -----
  const [stepsDesc, setStepsDesc] = useState(false);
  const stepRows = visibleIdx.length
    ? (() => {
        const rows = buildMatchedRows(allTraces, visibleIdx).map((row, r) => ({
          key: r,
          x: row.x,
          cells: row.values.map(num),
        }));
        return stepsDesc ? rows.reverse() : rows;
      })()
    : [];

  // ----- plot render -----
  useEffect(() => {
    if (!isPlot || !plotRef.current || typeof Plotly === 'undefined') return;

    const data = [];
    visibleIdx.forEach((i, ordinal) => {
      const src = allTraces[i];
      const line = isLineTrace(src);
      const color = traceColor(src, ordinal);
      const base = { ...src };
      if (line) {
        base.mode = settings.points ? 'lines+markers' : 'lines';
        base.line = { ...(src.line || {}), color };
        base.marker = { ...(src.marker || {}), color };
      }

      if (settings.smoothing > 0 && line && Array.isArray(src.y)) {
        base.opacity = 0.22;
        base.showlegend = false;
        base.hoverinfo = 'skip';
        data.push(base);
        data.push({
          ...src,
          y: ema(src.y, settings.smoothing),
          mode: settings.points ? 'lines+markers' : 'lines',
          opacity: 1,
          line: { ...(src.line || {}), color, width: 2 },
          marker: { ...(src.marker || {}), color },
        });
      } else {
        base.opacity = 1;
        data.push(base);
      }
    });

    const srcLayout = (content && content.layout) || {};
    const ink =
      (typeof getComputedStyle !== 'undefined' &&
        getComputedStyle(document.documentElement)
          .getPropertyValue('--vis-text')
          .trim()) ||
      '#333';

    const layout = {
      ...srcLayout,
      title: { text: '' },
      autosize: true,
      showlegend: visibleIdx.length > 1,
      margin: { l: 56, r: 20, t: 16, b: 40 },
      hovermode: 'x unified',
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: {
        family:
          'system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
        size: 12,
        color: ink,
      },
      xaxis: {
        ...(srcLayout.xaxis || {}),
        title: (srcLayout.xaxis && srcLayout.xaxis.title) || { text: 'step' },
        gridcolor: 'rgba(128,128,128,0.18)',
        zerolinecolor: 'rgba(128,128,128,0.35)',
      },
      yaxis: {
        ...(srcLayout.yaxis || {}),
        type: settings.logY ? 'log' : 'linear',
        gridcolor: 'rgba(128,128,128,0.18)',
        zerolinecolor: 'rgba(128,128,128,0.35)',
        autorange: true,
      },
      datarevision: `${pane.version}:${settings.frame}:${settings.smoothing}:${settings.logY}:${settings.points}:${settings.hidden.join(',')}`,
    };

    Plotly.react(plotRef.current, data, layout, {
      displaylogo: false,
      doubleClick: 'reset',
      doubleClickDelay: 500,
      modeBarButtonsToAdd: ['drawopenpath', 'eraseshape'].concat(
        annotations.modebarButton ? [annotations.modebarButton] : []
      ),
      modeBarButtonsToRemove: ['toImage', 'sendDataToCloud'],
      edits: { annotationTail: !sessionInfo?.readonly },
    });
  }, [
    isPlot,
    content,
    visibleIdx.join(','),
    annotations.modebarButton,
    sessionInfo,
    settings.points,
    settings.smoothing,
    settings.logY,
    pane.version,
  ]);

  useEffect(() => {
    const el = plotRef.current;
    if (!el || typeof Plotly === 'undefined') return undefined;
    const ro = new ResizeObserver(() => {
      if (el._fullLayout) Plotly.Plots.resize(el);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const onKey = (e) => {
      // the annotation editor's own input already handles Escape (it
      // cancels the pending note); without this guard the keydown bubbles
      // here too and closes the whole view out from under it
      if (e.key === 'Escape' && !e.target.closest?.('.annotate-editor')) {
        onClose();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const downloadCsv = () => {
    if (!visibleIdx.length) return;
    const cols = visibleIdx.map((i) => names[i]);
    const lines = ['step,' + cols.map(csvCell).join(',')];
    buildMatchedRows(allTraces, visibleIdx).forEach((row) => {
      const cells = row.values.map((y) =>
        y === undefined || y === null ? '' : y
      );
      lines.push([row.x, ...cells].map(csvCell).join(','));
    });
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${pane.title || pane.id}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const historyFrames = isHistory
    ? Array.isArray(pane.content)
      ? pane.content.length
      : 1
    : 0;

  return (
    <div className="metric-detail" role="dialog" aria-modal="true">
      <div className="metric-detail-breadcrumb">
        <span className="crumb">{envID}</span>
        <span className="crumb-sep">{'›'}</span>
        <span className="crumb crumb-current">{pane.title || pane.id}</span>
        <button
          className="metric-detail-close"
          title="Close (Esc)"
          onClick={onClose}
        >
          <X size={16} />
        </button>
      </div>

      {isPlot ? (
        <div className="metric-detail-body">
          <aside className="metric-detail-rail">
            <div className="rail-meta">
              {stepRows.length
                ? `${stepRows.length} points`
                : 'no numeric data'}
            </div>

            <label className="rail-row rail-toggle">
              <span>Points</span>
              <input
                type="checkbox"
                checked={settings.points}
                onChange={(e) => set({ points: e.target.checked })}
              />
            </label>

            <div className="rail-row">
              <span>Line smoothness</span>
              <input
                type="range"
                min="0"
                max="0.99"
                step="0.01"
                value={settings.smoothing}
                onChange={(e) => set({ smoothing: parseFloat(e.target.value) })}
              />
              <span className="rail-num">{settings.smoothing.toFixed(2)}</span>
            </div>

            <div className="rail-row rail-group">
              <span>X-axis</span>
              <label>
                <input type="radio" checked readOnly /> Step
              </label>
              <label className="rail-disabled">
                <input type="radio" disabled /> Time (Wall)
              </label>
              <label className="rail-disabled">
                <input type="radio" disabled /> Time (Relative)
              </label>
            </div>

            <div className="rail-row rail-group">
              <span>Metrics</span>
              {names.map((n, i) => (
                <label key={`${n}-${i}`}>
                  <input
                    type="checkbox"
                    checked={!hiddenSet.has(n)}
                    onChange={(e) => {
                      const next = new Set(settings.hidden);
                      if (e.target.checked) next.delete(n);
                      else next.add(n);
                      set({ hidden: [...next] });
                    }}
                  />{' '}
                  {n}
                </label>
              ))}
            </div>

            <label className="rail-row rail-toggle">
              <span>Y-axis log scale</span>
              <input
                type="checkbox"
                checked={settings.logY}
                onChange={(e) => set({ logY: e.target.checked })}
              />
            </label>

            {historyFrames > 1 && (
              <div className="rail-row">
                <span>Frame</span>
                <input
                  type="range"
                  min="0"
                  max={historyFrames - 1}
                  value={settings.frame}
                  onChange={(e) => set({ frame: parseInt(e.target.value, 10) })}
                />
                <span className="rail-num">
                  {settings.frame}/{historyFrames - 1}
                </span>
              </div>
            )}

            <button
              className="btn btn-default btn-sm rail-csv"
              onClick={downloadCsv}
            >
              <Download size={13} /> Download CSV
            </button>
          </aside>

          <div className="metric-detail-chart">
            {annotations.hint}
            <div ref={plotRef} style={{ width: '100%', height: '100%' }} />
            {annotations.editor}
          </div>
        </div>
      ) : (
        <div className="metric-detail-note">
          The expanded metric view is available for line and scatter plots.
          {` "${pane.type}" panes are not supported yet.`}
        </div>
      )}

      {isPlot && stepRows.length > 0 && (
        <div className="metric-detail-stats">
          <table>
            <thead>
              <tr>
                <th onClick={() => setStepsDesc((d) => !d)}>
                  Step{stepsDesc ? ' ▼' : ' ▲'}
                </th>
                {visibleIdx.map((i) => (
                  <th key={i}>{names[i]}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {stepRows.map((row) => (
                <tr key={row.key}>
                  <td>{row.x}</td>
                  {row.cells.map((c, ci) => (
                    <td key={ci}>{c === null ? '—' : c}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default MetricDetailView;
