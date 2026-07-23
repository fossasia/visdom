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

import { applySnapshotButton, observePlotResize } from './hparamsPlot';
import {
  buildColumns,
  buildParcoordsDimensions,
  completeRecords,
  defaultDimIds,
  groupColumnTree,
  isNumeric,
  NUMERIC_GROUPS,
  numericExtent,
  runLabel,
  selectNumericColumns,
  toNumericColumn,
} from './hparamsUtils';

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

  /*
   * Which columns can be plotted is derived from the unfiltered records, so a
   * filter that empties a column does not make it vanish from the axis picker
   * and silently reset the user's selection.
   */
  const pickerRecords = columnRecords || records;

  const columns = useMemo(
    () => buildColumns(paramKeys, metricKeys, tagKeys),
    [paramKeys, metricKeys, tagKeys]
  );
  const numericCols = useMemo(
    () => selectNumericColumns(pickerRecords, columns),
    [pickerRecords, columns]
  );

  const effectiveDims = useMemo(() => {
    const validIds = new Set(numericCols.map((c) => c.id));
    let ids = (selectedDims || []).filter((id) => validIds.has(id));
    if (ids.length === 0) {
      ids = defaultDimIds(numericCols, (col) =>
        records.every((record) => isNumeric(col.accessor(record)))
      );
    }
    return ids.slice(0, MAX_DIMS);
  }, [selectedDims, numericCols, records]);

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

  const hasPlot = numericCols.length >= 2;

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

  const handleDims = (value) => {
    onSelectedDims(Array.isArray(value) ? value.slice(0, MAX_DIMS) : []);
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
            treeData={treeData}
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
            treeData={treeData}
            onChange={(value) => onColorBy(value || null)}
            aria-label="Color parallel coordinates by"
          />
        </span>
        {rows.length < records.length ? (
          <span className="hparams-splom-note">
            {rows.length} of {records.length} runs have all selected axes
          </span>
        ) : truncated ? (
          <span className="hparams-splom-note">showing first {MAX_DIMS}</span>
        ) : null}
      </div>
      <div className="hparams-parcoords-plot" ref={plotRef} />
      {effectiveDims.length < 2 ? (
        <div className="hparams-splom-overlay">
          Select at least two dimensions to plot.
        </div>
      ) : rows.length === 0 ? (
        <div className="hparams-splom-overlay">
          No run has a value on every selected axis. Remove a sparse axis to see
          lines.
        </div>
      ) : null}
    </div>
  );
};

export default HParamsParallelCoords;
