/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { useEffect, useMemo, useRef } from 'react';

import HParamsAxisToolbar from './HParamsAxisToolbar';
import { applySnapshotButton, observePlotResize } from './hparamsPlot';
import {
  buildParcoordsDimensions,
  completeRecords,
  numericExtent,
  runLabel,
  toNumericColumn,
} from './hparamsUtils';
import useHParamsAxes from './useHParamsAxes';

const RUN_LABEL_MAX = 18;

const MAX_DIMS = 10;

const PARCOORDS_COLORSCALE = 'Viridis';

const HParamsParallelCoords = ({
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
  const plotRef = useRef(null);

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
    preferDense: true,
  });

  const rows = useMemo(() => {
    const colorCol = effectiveColorBy
      ? columns.find((c) => c.id === effectiveColorBy)
      : null;
    const axisCols = effectiveDims
      .map((id) => columns.find((c) => c.id === id))
      .filter(Boolean);
    const requiredCols = colorCol ? axisCols.concat(colorCol) : axisCols;
    return completeRecords(records, requiredCols);
  }, [records, columns, effectiveDims, effectiveColorBy]);

  useEffect(() => {
    const el = plotRef.current;
    if (!el) return;
    return observePlotResize(el);
  }, []);

  useEffect(() => {
    const el = plotRef.current;
    if (!el || !window.Plotly) return;

    const colorCol = effectiveColorBy
      ? columns.find((c) => c.id === effectiveColorBy)
      : null;

    const numericDimensions = buildParcoordsDimensions(
      rows,
      columns,
      effectiveDims
    );
    if (numericDimensions.length < 2 || rows.length === 0) {
      window.Plotly.purge(el);
      return;
    }

    const runName = (record) => {
      const name = runLabel(record);
      return name.length > RUN_LABEL_MAX
        ? name.slice(0, RUN_LABEL_MAX - 1) + '…'
        : name;
    };
    const runDimension = {
      label: 'run',
      values: rows.map((_, i) => i),
      tickvals: rows.map((_, i) => i),
      ticktext: rows.map(runName),
      range: [-0.5, Math.max(rows.length - 1, 0.5)],
    };
    const dimensions = [runDimension, ...numericDimensions];

    let line;
    if (colorCol) {
      const ext = numericExtent(rows, colorCol.accessor);
      line = {
        color: toNumericColumn(rows, colorCol.accessor),
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
        color: rows.map((_, i) => i + 1),
        colorscale: PARCOORDS_COLORSCALE,
        showscale: true,
        cmin: 1,
        cmax: Math.max(rows.length, 1),
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
        labelangle: 0,
        labelside: 'top',
        labelfont: { size: 12, color: '#333' },
        tickfont: { size: 10, color: '#666' },
        rangefont: { size: 10, color: '#888' },
      },
    ];

    const layout = {
      margin: { l: 120, r: 80, t: 64, b: 76 },
      font: { family: '"Open Sans", sans-serif', size: 11, color: '#333' },
      paper_bgcolor: '#ffffff',
      plot_bgcolor: '#ffffff',
      datarevision:
        effectiveDims.join('|') +
        '::' +
        (effectiveColorBy || 'order') +
        '::' +
        rows.length,
    };

    const config = applySnapshotButton(
      {
        showLink: false,
        displaylogo: false,
        responsive: true,
        doubleClick: 'reset',
      },
      'hparams_parcoords.png'
    );

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
  }, [rows, columns, effectiveDims, effectiveColorBy]);

  if (!hasPlot) {
    return (
      <div className="hparams-parcoords-wrap">
        <div className="hparams-message hparams-empty">
          Parallel coordinates need at least two numeric params or metrics.
        </div>
      </div>
    );
  }

  const note =
    rows.length < records.length
      ? rows.length + ' of ' + records.length + ' runs have all selected axes'
      : truncated
        ? 'showing first ' + MAX_DIMS
        : null;

  return (
    <div className="hparams-parcoords-wrap">
      <HParamsAxisToolbar
        axesLabel="axes"
        axesName="parallel coordinates"
        colorFallback="run order"
        treeData={treeData}
        dims={effectiveDims}
        onDims={onSelectedDims}
        colorBy={effectiveColorBy}
        onColorBy={onColorBy}
        maxDims={MAX_DIMS}
        note={note}
      />
      <div className="hparams-parcoords-plot" ref={plotRef} />
      {effectiveDims.length < 2 ? (
        <div className="hparams-plot-overlay">
          Select at least two dimensions to plot.
        </div>
      ) : rows.length === 0 ? (
        <div className="hparams-plot-overlay">
          No run has a value on every selected axis. Remove a sparse axis to see
          lines.
        </div>
      ) : null}
    </div>
  );
};

export default HParamsParallelCoords;
