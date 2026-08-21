/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import TreeSelect from 'rc-tree-select';
import React, { useEffect, useMemo, useRef } from 'react';

import {
  buildColumns,
  buildSplomDimensions,
  groupColumnTree,
  NUMERIC_GROUPS,
  numericExtent,
  runLabel,
  selectNumericColumns,
  toNumericColumn,
} from './hparamsUtils';

const MAX_DIMS = 6;

const SPLOM_COLORSCALE = 'Viridis';

const AXIS_STYLE = {
  showline: true,
  linecolor: '#aab8d8',
  linewidth: 1,
  mirror: 'all',
  gridcolor: '#f0f2f8',
  zeroline: false,
  ticklen: 3,
  tickfont: { size: 9, color: '#666' },
  automargin: true,
};

const SNAPSHOT_NOTICE_DELAY = 700;

function notify(message, kind) {
  const lib = window.Plotly && window.Plotly.Lib;
  if (lib && typeof lib.notifier === 'function') lib.notifier(message, kind);
}

function downloadSnapshot(gd) {
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
      link.download = 'hparams_scatter.png';
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

const HParamsSplom = ({
  records,
  paramKeys,
  metricKeys,
  tagKeys,
  selectedDims,
  onSelectedDims,
  colorBy,
  onColorBy,
}) => {
  const plotRef = useRef(null);
  const prevDimCount = useRef(0);

  const columns = useMemo(
    () => buildColumns(paramKeys, metricKeys, tagKeys),
    [paramKeys, metricKeys, tagKeys]
  );
  const numericCols = useMemo(
    () => selectNumericColumns(records, columns),
    [records, columns]
  );

  const effectiveDims = useMemo(() => {
    const defaults = () => numericCols.slice(0, MAX_DIMS).map((c) => c.id);
    if (!Array.isArray(selectedDims)) return defaults();
    const validIds = new Set(numericCols.map((c) => c.id));
    const ids = selectedDims.filter((id) => validIds.has(id));
    if (ids.length === 0 && selectedDims.length > 0) return defaults();
    return ids.slice(0, MAX_DIMS);
  }, [selectedDims, numericCols]);

  const effectiveColorBy = useMemo(() => {
    if (!colorBy) return null;
    return numericCols.some((c) => c.id === colorBy) ? colorBy : null;
  }, [colorBy, numericCols]);

  const truncated =
    (selectedDims || []).filter((id) => numericCols.some((c) => c.id === id))
      .length > MAX_DIMS;

  const treeData = useMemo(
    () => groupColumnTree(numericCols, NUMERIC_GROUPS),
    [numericCols]
  );

  const hasPlot = numericCols.length >= 2;

  useEffect(() => {
    const el = plotRef.current;
    if (!el) return;
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
  }, []);

  useEffect(() => {
    const el = plotRef.current;
    if (!el || !window.Plotly) return;

    const dimensions = buildSplomDimensions(records, columns, effectiveDims);
    if (dimensions.length < 2) {
      window.Plotly.purge(el);
      prevDimCount.current = 0;
      return;
    }

    const names = records.map(runLabel);

    const colorCol = effectiveColorBy
      ? columns.find((c) => c.id === effectiveColorBy)
      : null;
    let colorValues;
    let colorLabel;
    let cmin;
    let cmax;
    if (colorCol) {
      colorValues = toNumericColumn(records, colorCol.accessor);
      colorLabel = colorCol.label;
      const ext = numericExtent(records, colorCol.accessor);
      if (ext) {
        cmin = ext.min;
        cmax = ext.max;
      }
    } else {
      colorValues = records.map((_, i) => i + 1);
      colorLabel = 'run order';
      cmin = 1;
      cmax = Math.max(records.length, 1);
    }

    const data = [
      {
        type: 'splom',
        dimensions,
        text: names,
        hovertemplate: '<b>%{text}</b><br>x: %{x}<br>y: %{y}<extra></extra>',
        marker: {
          size: 7,
          line: { color: '#ffffff', width: 0.6 },
          color: colorValues,
          colorscale: SPLOM_COLORSCALE,
          showscale: true,
          cmin,
          cmax,
          colorbar: {
            title: { text: colorLabel, side: 'right', font: { size: 11 } },
            thickness: 12,
            len: 0.6,
            outlinewidth: 0,
          },
        },
        diagonal: { visible: true },
        showupperhalf: true,
        showlowerhalf: true,
        opacity: 1,
      },
    ];

    const layout = {
      margin: { l: 60, r: 20, t: 34, b: 44 },
      dragmode: 'select',
      hovermode: 'closest',
      showlegend: false,
      font: { family: '"Open Sans", sans-serif', size: 11, color: '#333' },
      paper_bgcolor: '#ffffff',
      plot_bgcolor: '#ffffff',
      datarevision:
        effectiveDims.join('|') +
        '::' +
        (effectiveColorBy || 'order') +
        '::' +
        records.length,
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

    const config = {
      showLink: false,
      displaylogo: false,
      responsive: true,
      doubleClick: 'reset',
    };
    const cameraIcon = window.Plotly.Icons && window.Plotly.Icons.camera;
    if (cameraIcon) {
      config.modeBarButtonsToRemove = ['toImage'];
      config.modeBarButtonsToAdd = [
        {
          name: 'downloadPng',
          title: 'Download plot as PNG',
          icon: cameraIcon,
          click: downloadSnapshot,
        },
      ];
    }

    try {
      window.Plotly.react(el, data, layout, config)
        .then(() => {
          if (el._fullLayout && el.offsetWidth > 0) {
            window.Plotly.Plots.resize(el);
          }
        })
        .catch(() => window.Plotly.purge(el));
    } catch (e) {
      window.Plotly.purge(el);
    }
  }, [records, columns, effectiveDims, effectiveColorBy]);

  const handleDims = (value) => {
    onSelectedDims(Array.isArray(value) ? value.slice(0, MAX_DIMS) : []);
  };

  if (!hasPlot) {
    return (
      <div className="hparams-splom-wrap">
        <div className="hparams-message hparams-empty">
          A scatter matrix needs at least two numeric params or metrics.
        </div>
      </div>
    );
  }

  return (
    <div className="hparams-splom-wrap">
      <div className="hparams-toolbar">
        <span className="hparams-sortby">
          dimensions:
          <TreeSelect
            className="hparams-treeselect hparams-select-wide"
            value={effectiveDims}
            placeholder="pick axes"
            treeCheckable
            multiple
            showCheckedStrategy="SHOW_CHILD"
            treeLine
            treeDefaultExpandAll
            maxTagCount={3}
            dropdownMatchSelectWidth={false}
            treeData={treeData}
            onChange={handleDims}
            aria-label="Scatter matrix dimensions"
          />
        </span>
        <span className="hparams-colorby">
          color by:
          <TreeSelect
            className="hparams-treeselect hparams-select-narrow"
            value={effectiveColorBy || undefined}
            placeholder="none"
            allowClear
            treeLine
            treeDefaultExpandAll
            dropdownMatchSelectWidth={false}
            treeData={treeData}
            onChange={(value) => onColorBy(value || null)}
            aria-label="Color scatter matrix by"
          />
        </span>
        {truncated ? (
          <span className="hparams-splom-note">showing first {MAX_DIMS}</span>
        ) : null}
      </div>
      <div className="hparams-splom-plot" ref={plotRef} />
      {effectiveDims.length < 2 ? (
        <div className="hparams-splom-overlay">
          Select at least two dimensions to plot.
        </div>
      ) : null}
    </div>
  );
};

export default HParamsSplom;
