/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import TreeSelect from 'rc-tree-select';
import React, { useEffect, useMemo, useRef, useState } from 'react';

import {
  buildColumns,
  buildParcoordsDimensions,
  numericExtent,
  selectNumericColumns,
} from './hparamsUtils';

const MAX_DIMS = 10;

const PARCOORDS_COLORSCALE = 'Viridis';

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
      link.download = 'hparams_parcoords.png';
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

function groupedTreeData(cols) {
  const params = cols.filter((c) => c.group === 'param');
  const metrics = cols.filter((c) => c.group === 'metric');
  const branch = (key, title, children) =>
    children.length
      ? [
          {
            key: '__g_' + key,
            value: '__g_' + key,
            title,
            selectable: false,
            checkable: false,
            children: children.map((c) => ({
              key: c.id,
              value: c.id,
              title: c.label,
            })),
          },
        ]
      : [];
  return [
    ...branch('param', 'params', params),
    ...branch('metric', 'metrics', metrics),
  ];
}

const HParamsParallelCoords = ({ records, paramKeys, metricKeys, tagKeys }) => {
  const plotRef = useRef(null);

  const columns = useMemo(
    () => buildColumns(paramKeys, metricKeys, tagKeys),
    [paramKeys, metricKeys, tagKeys]
  );
  const numericCols = useMemo(
    () => selectNumericColumns(records, columns),
    [records, columns]
  );

  const [selectedDims, setSelectedDims] = useState(null);
  const [colorBy, setColorBy] = useState(null);

  const effectiveDims = useMemo(() => {
    const validIds = new Set(numericCols.map((c) => c.id));
    let ids = (selectedDims || []).filter((id) => validIds.has(id));
    if (ids.length === 0) ids = numericCols.slice(0, MAX_DIMS).map((c) => c.id);
    return ids.slice(0, MAX_DIMS);
  }, [selectedDims, numericCols]);

  const effectiveColorBy = useMemo(() => {
    if (!colorBy) return null;
    return numericCols.some((c) => c.id === colorBy) ? colorBy : null;
  }, [colorBy, numericCols]);

  const truncated =
    (selectedDims || []).filter((id) => numericCols.some((c) => c.id === id))
      .length > MAX_DIMS;

  const dimTreeData = useMemo(
    () => groupedTreeData(numericCols),
    [numericCols]
  );
  const colorTreeData = useMemo(
    () => groupedTreeData(numericCols),
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

    const dimensions = buildParcoordsDimensions(
      records,
      columns,
      effectiveDims
    );
    if (dimensions.length < 2) {
      window.Plotly.purge(el);
      return;
    }

    const colorCol = effectiveColorBy
      ? columns.find((c) => c.id === effectiveColorBy)
      : null;
    let line;
    if (colorCol) {
      const ext = numericExtent(records, colorCol.accessor);
      line = {
        color: records.map((r) => {
          const v = colorCol.accessor(r);
          return typeof v === 'number' && Number.isFinite(v) ? v : null;
        }),
        colorscale: PARCOORDS_COLORSCALE,
        showscale: true,
        cmin: ext ? ext.min : 0,
        cmax: ext ? ext.max : 1,
        colorbar: {
          title: { text: colorCol.label, side: 'right', font: { size: 11 } },
          thickness: 12,
          len: 0.6,
          outlinewidth: 0,
        },
      };
    } else {
      line = {
        color: records.map((_, i) => i + 1),
        colorscale: PARCOORDS_COLORSCALE,
        showscale: true,
        cmin: 1,
        cmax: Math.max(records.length, 1),
        colorbar: {
          title: { text: 'run order', side: 'right', font: { size: 11 } },
          thickness: 12,
          len: 0.6,
          outlinewidth: 0,
        },
      };
    }

    const data = [
      {
        type: 'parcoords',
        dimensions,
        line,
        labelfont: { size: 12 },
        tickfont: { size: 10 },
        rangefont: { size: 10 },
      },
    ];

    const layout = {
      margin: { l: 60, r: 40, t: 30, b: 24 },
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
    setSelectedDims(Array.isArray(value) ? value.slice(0, MAX_DIMS) : []);
  };

  if (!hasPlot) {
    return (
      <div className="hparams-parcoords-wrap">
        <div className="hparams-message hparams-empty">
          Parallel coordinates need at least two numeric params or metrics.
        </div>
      </div>
    );
  }

  return (
    <div className="hparams-parcoords-wrap">
      <div className="hparams-toolbar">
        <span className="hparams-sortby">
          axes:
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
            treeData={dimTreeData}
            onChange={handleDims}
            aria-label="Parallel coordinates axes"
          />
        </span>
        <span className="hparams-colorby">
          color by:
          <TreeSelect
            className="hparams-treeselect hparams-select-narrow"
            value={effectiveColorBy || undefined}
            placeholder="run order"
            allowClear
            treeLine
            treeDefaultExpandAll
            dropdownMatchSelectWidth={false}
            treeData={colorTreeData}
            onChange={(value) => setColorBy(value || null)}
            aria-label="Color parallel coordinates by"
          />
        </span>
        {truncated ? (
          <span className="hparams-splom-note">showing first {MAX_DIMS}</span>
        ) : null}
      </div>
      <div className="hparams-parcoords-plot" ref={plotRef} />
      {effectiveDims.length < 2 ? (
        <div className="hparams-splom-overlay">
          Select at least two dimensions to plot.
        </div>
      ) : null}
    </div>
  );
};

export default HParamsParallelCoords;
