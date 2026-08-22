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
import { applySnapshotButton, observePlotResize } from './hparamsPlot';
import {
  buildSplomDimensions,
  numericExtent,
  runLabel,
  toNumericColumn,
} from './hparamsUtils';
import useHParamsAxes from './useHParamsAxes';

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
  const plotRef = useRef(null);
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

  useEffect(() => {
    const el = plotRef.current;
    if (!el) return;
    return observePlotResize(el);
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

    const config = applySnapshotButton(
      {
        showLink: false,
        displaylogo: false,
        responsive: true,
        doubleClick: 'reset',
      },
      'hparams_scatter.png'
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
  }, [records, columns, effectiveDims, effectiveColorBy]);

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
      {effectiveDims.length < 2 ? (
        <div className="hparams-plot-overlay">
          Select at least two dimensions to plot.
        </div>
      ) : null}
    </div>
  );
};

export default HParamsSplom;
