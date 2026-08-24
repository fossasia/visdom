/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { useEffect, useRef } from 'react';

import HParamsAxisToolbar from './HParamsAxisToolbar';
import {
  PLOT_COLORSCALE,
  plotAxisStyle,
  plotBaseLayout,
  plotColorbar,
  plotRevision,
  renderPlot,
  usePlotResize,
} from './hparamsPlot';
import {
  coincidentRuns,
  formatValue,
  HParamsMessage,
  resolveColor,
  toNumericColumn,
} from './hparamsUtils';
import useHParamsAxes from './useHParamsAxes';

const MAX_DIMS = 6;

const AXIS_STYLE = {
  ...plotAxisStyle(),
  mirror: 'all',
  tickfont: { size: 9, color: '#666' },
};

function axisDimIndex(axis) {
  const id = (axis && (axis._id || axis.id)) || '';
  const n = parseInt(String(id).replace(/[^0-9]/g, ''), 10);
  return Number.isNaN(n) ? 0 : n - 1;
}

function tipNode(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderTip(tip, names, colX, colY, x, y) {
  while (tip.firstChild) tip.removeChild(tip.firstChild);
  tip.appendChild(
    tipNode(
      'div',
      'hparams-splom-tip-head',
      names.length > 1 ? names.length + ' runs here' : names[0]
    )
  );
  if (names.length > 1) {
    const list = tipNode('ul', 'hparams-splom-tip-list');
    names.forEach((n) => list.appendChild(tipNode('li', '', n)));
    tip.appendChild(list);
  }
  const coord = tipNode('div', 'hparams-splom-tip-coord');
  coord.appendChild(tipNode('span', '', colX.label + ': ' + formatValue(x)));
  if (colX.id !== colY.id) {
    coord.appendChild(document.createElement('br'));
    coord.appendChild(tipNode('span', '', colY.label + ': ' + formatValue(y)));
  }
  tip.appendChild(coord);
}

const HParamsSplom = ({
  records,
  columnRecords,
  paramKeys,
  metricKeys,
  tagKeys,
  selectedDims,
  onSelectedDims,
  colorBy,
  onColorBy,
}) => {
  const wrapRef = useRef(null);
  const plotRef = useRef(null);
  const tipRef = useRef(null);
  const prevDimCount = useRef(0);

  const {
    columns,
    dims: effectiveDims,
    colorBy: effectiveColorBy,
    treeData,
    truncated,
    hasPlot,
  } = useHParamsAxes({
    records,
    columnRecords,
    paramKeys,
    metricKeys,
    tagKeys,
    selectedDims,
    colorBy,
    maxDims: MAX_DIMS,
  });

  usePlotResize(plotRef);

  useEffect(() => {
    const el = plotRef.current;
    if (!el || !window.Plotly) return undefined;

    const plotted = [];
    const dimensions = [];
    effectiveDims.forEach((id) => {
      const col = columns.find((c) => c.id === id);
      if (!col) return;
      const values = toNumericColumn(records, col.accessor);
      if (values.every((v) => v === null)) return;
      plotted.push(col);
      dimensions.push({ label: col.label, values });
    });
    if (dimensions.length < 2) {
      window.Plotly.purge(el);
      prevDimCount.current = 0;
      return undefined;
    }

    const color = resolveColor(records, columns, effectiveColorBy);

    const data = [
      {
        type: 'splom',
        dimensions,
        hoverinfo: 'none',
        marker: {
          size: 7,
          line: { color: '#ffffff', width: 0.6 },
          color: color.values,
          colorscale: PLOT_COLORSCALE,
          showscale: true,
          cmin: color.cmin,
          cmax: color.cmax,
          colorbar: plotColorbar(color.label),
        },
        diagonal: { visible: true },
        showupperhalf: true,
        showlowerhalf: true,
        opacity: 1,
      },
    ];

    const layout = {
      ...plotBaseLayout(),
      margin: { l: 60, r: 20, t: 34, b: 44 },
      dragmode: 'select',
      hovermode: 'closest',
      showlegend: false,
      datarevision: plotRevision(
        effectiveDims.join('|'),
        effectiveColorBy || 'order',
        records.length
      ),
    };
    for (let i = 1; i <= dimensions.length; i++) {
      const suffix = i === 1 ? '' : String(i);
      layout['xaxis' + suffix] = { ...AXIS_STYLE };
      layout['yaxis' + suffix] = { ...AXIS_STYLE };
    }

    if (el._fullLayout && prevDimCount.current !== dimensions.length) {
      window.Plotly.purge(el);
    }
    prevDimCount.current = dimensions.length;

    const hideTip = () => {
      if (tipRef.current) tipRef.current.style.display = 'none';
    };
    const showTip = (ev) => {
      const tip = tipRef.current;
      const wrap = wrapRef.current;
      if (!tip || !wrap || !ev || !ev.points || !ev.points.length) return;
      const p = ev.points[0];
      const colX = plotted[axisDimIndex(p.xaxis)];
      const colY = plotted[axisDimIndex(p.yaxis)];
      if (!colX || !colY) return;
      const names = coincidentRuns(records, colX, colY, p.x, p.y);
      if (names.length === 0) return;

      renderTip(tip, names, colX, colY, p.x, p.y);
      tip.style.display = 'block';
      const rect = wrap.getBoundingClientRect();
      const me = ev.event;
      let left = (me ? me.clientX - rect.left : 0) + 14;
      let top = (me ? me.clientY - rect.top : 0) + 12;
      if (left + tip.offsetWidth > wrap.clientWidth) {
        left = wrap.clientWidth - tip.offsetWidth - 6;
      }
      if (top + tip.offsetHeight > wrap.clientHeight) {
        top = wrap.clientHeight - tip.offsetHeight - 6;
      }
      tip.style.left = Math.max(0, left) + 'px';
      tip.style.top = Math.max(0, top) + 'px';
    };

    renderPlot(el, data, layout, 'hparams_scatter.png', (gd) => {
      if (!gd || typeof gd.on !== 'function') return;
      if (gd.removeAllListeners) {
        gd.removeAllListeners('plotly_hover');
        gd.removeAllListeners('plotly_unhover');
      }
      gd.on('plotly_hover', showTip);
      gd.on('plotly_unhover', hideTip);
    });

    return () => {
      const gd = plotRef.current;
      if (gd && gd.removeAllListeners) {
        gd.removeAllListeners('plotly_hover');
        gd.removeAllListeners('plotly_unhover');
      }
      hideTip();
    };
  }, [records, columns, effectiveDims, effectiveColorBy]);

  if (!hasPlot) {
    return (
      <HParamsMessage wrapClass="hparams-splom-wrap">
        A scatter matrix needs at least two numeric params or metrics.
      </HParamsMessage>
    );
  }

  return (
    <div className="hparams-splom-wrap" ref={wrapRef}>
      <HParamsAxisToolbar
        axesLabel="dimensions"
        axesName="scatter matrix"
        colorFallback="none"
        treeData={treeData}
        dims={effectiveDims}
        onDims={onSelectedDims}
        colorBy={effectiveColorBy}
        onColorBy={onColorBy}
        maxDims={MAX_DIMS}
        note={truncated ? 'showing first ' + MAX_DIMS : null}
      />
      <div className="hparams-splom-plot" ref={plotRef} />
      <div className="hparams-splom-tip" ref={tipRef} />
      {effectiveDims.length < 2 ? (
        <div className="hparams-plot-overlay">
          Select at least two dimensions to plot.
        </div>
      ) : null}
    </div>
  );
};

export default React.memo(HParamsSplom);
