/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import { useEffect } from 'react';

const SNAPSHOT_NOTICE_DELAY = 700;

export const PLOT_COLORSCALE = 'Viridis';

export const RUN_PALETTE = [
  '#1f77b4',
  '#ff7f0e',
  '#2ca02c',
  '#d62728',
  '#9467bd',
  '#8c564b',
  '#e377c2',
  '#7f7f7f',
  '#bcbd22',
  '#17becf',
];

export function runColor(index) {
  const i = Number.isFinite(index) ? Math.abs(Math.trunc(index)) : 0;
  return RUN_PALETTE[i % RUN_PALETTE.length];
}

export function notify(message, kind) {
  const lib = window.Plotly && window.Plotly.Lib;
  if (lib && typeof lib.notifier === 'function') lib.notifier(message, kind);
}

export function downloadPlotPng(gd, filename) {
  if (!window.Plotly || typeof window.Plotly.toImage !== 'function') return;
  let done = false;
  const timer = setTimeout(() => {
    if (!done) notify('Taking snapshot - this may take a few seconds', 'long');
  }, SNAPSHOT_NOTICE_DELAY);

  window.Plotly.toImage(gd, {
    format: 'png',
    width: gd.offsetWidth || 900,
    height: gd.offsetHeight || 600,
  })
    .then((url) => {
      done = true;
      clearTimeout(timer);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    })
    .catch(() => {
      done = true;
      clearTimeout(timer);
      notify('Snapshot failed', 'long');
    });
}

export function applySnapshotButton(config, filename) {
  const icons = window.Plotly && window.Plotly.Icons;
  const icon = icons && icons.camera;
  if (!icon) return config;
  config.modeBarButtonsToRemove = ['toImage'];
  config.modeBarButtonsToAdd = [
    {
      name: 'downloadPng',
      title: 'Download plot as PNG',
      icon,
      click: (gd) => downloadPlotPng(gd, filename),
    },
  ];
  return config;
}

export function observePlotResize(el) {
  const isDisplayed = (node) =>
    !!(node && node.offsetWidth > 0 && node.offsetHeight > 0);
  const resizeObserver = new ResizeObserver(() => {
    if (window.Plotly && el._fullLayout && isDisplayed(el)) {
      window.Plotly.Plots.resize(el);
    }
  });
  resizeObserver.observe(el);
  return () => {
    resizeObserver.disconnect();
    if (window.Plotly && el._fullLayout) window.Plotly.purge(el);
  };
}

export function usePlotResize(ref) {
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    return observePlotResize(el);
  }, [ref]);
}

export function plotBaseLayout() {
  return {
    font: { family: '"Open Sans", sans-serif', size: 11, color: '#333' },
    paper_bgcolor: '#ffffff',
    plot_bgcolor: '#ffffff',
  };
}

export function plotAxisStyle() {
  return {
    showline: true,
    linecolor: '#aab8d8',
    linewidth: 1,
    gridcolor: '#f0f2f8',
    zeroline: false,
    ticklen: 3,
    tickfont: { size: 10, color: '#666' },
    automargin: true,
  };
}

export function plotRevision(...parts) {
  return parts.join('::');
}

export function plotColorbar(label) {
  return {
    title: { text: label, side: 'right', font: { size: 11 } },
    thickness: 12,
    len: 0.6,
    outlinewidth: 0,
  };
}

export function renderPlot(el, data, layout, filename, onReady) {
  if (!el || !window.Plotly) return;
  const config = applySnapshotButton(
    {
      showLink: false,
      displaylogo: false,
      responsive: true,
      doubleClick: 'reset',
    },
    filename
  );
  try {
    window.Plotly.react(el, data, layout, config)
      .then(() => {
        if (el._fullLayout && el.offsetWidth > 0) {
          window.Plotly.Plots.resize(el);
        }
        if (onReady) onReady(el);
      })
      .catch(() => window.Plotly.purge(el));
  } catch (e) {
    window.Plotly.purge(el);
  }
}
