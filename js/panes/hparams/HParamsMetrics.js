/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { useEffect, useMemo, useRef } from 'react';

import {
  plotAxisStyle,
  plotBaseLayout,
  renderPlot,
  runColor,
  usePlotResize,
} from './hparamsPlot';
import { selectMetricSeries } from './hparamsUtils';
import useExperimentMetrics from './useExperimentMetrics';

const MAX_MISSING_NAMED = 3;

function missingNote(missing, metric) {
  if (missing.length === 0) return null;
  const named = missing.slice(0, MAX_MISSING_NAMED).join(', ');
  const rest = missing.length - MAX_MISSING_NAMED;
  const who = rest > 0 ? named + ' +' + rest + ' more' : named;
  return 'no ' + metric + ' logged by ' + who;
}

var HParamsMetrics = (props) => {
  const { records, columnRecords, metric, onMetric, cacheRef } = props;
  const plotRef = useRef(null);
  const { status, error, runs, metricKeys, refresh } = useExperimentMetrics(
    records,
    cacheRef
  );

  /* Colour by position in the unfiltered records so a run keeps its line
     colour when the selection or the filters change. */
  const colorIndex = useMemo(() => {
    const index = new Map();
    (columnRecords || []).forEach((record, i) => {
      if (record && record.env_id) index.set(record.env_id, i);
    });
    return index;
  }, [columnRecords]);

  const activeMetric = useMemo(() => {
    if (metric && metricKeys.indexOf(metric) > -1) return metric;
    return metricKeys.length > 0 ? metricKeys[0] : null;
  }, [metric, metricKeys]);

  const { plotted, missing } = useMemo(
    () => selectMetricSeries(runs, activeMetric, colorIndex),
    [runs, activeMetric, colorIndex]
  );

  const xLabel = useMemo(() => {
    if (plotted.length === 0) return 'step';
    const indexed = plotted.filter((run) => run.usesIndex).length;
    if (indexed === 0) return 'step';
    return indexed === plotted.length ? 'observation' : 'step / observation';
  }, [plotted]);

  usePlotResize(plotRef);

  useEffect(() => {
    const el = plotRef.current;
    if (!el || !window.Plotly) return;
    if (plotted.length === 0 || !activeMetric) {
      window.Plotly.purge(el);
      return;
    }

    const data = plotted.map((run) => ({
      type: 'scatter',
      mode: 'lines',
      name: run.label,
      x: run.x,
      y: run.y,
      connectgaps: false,
      line: { color: runColor(run.colorIndex), width: 1.6 },
      hovertemplate:
        '%{fullData.name}<br>' +
        xLabel +
        ' %{x}<br>' +
        activeMetric +
        ' %{y}<extra></extra>',
    }));

    const points = plotted.reduce((total, run) => total + run.x.length, 0);
    const layout = {
      ...plotBaseLayout(),
      margin: { l: 56, r: 16, t: 12, b: 44 },
      xaxis: {
        ...plotAxisStyle(),
        title: { text: xLabel, font: { size: 11 } },
      },
      yaxis: {
        ...plotAxisStyle(),
        title: { text: activeMetric, font: { size: 11 } },
      },
      showlegend: true,
      legend: { font: { size: 10 } },
      hovermode: 'closest',
      datarevision:
        activeMetric +
        '::' +
        plotted.map((run) => run.env_id).join('|') +
        '::' +
        points,
    };

    renderPlot(el, data, layout, 'hparams_metrics.png');
  }, [plotted, activeMetric, xLabel]);

  if (records.length === 0) {
    return (
      <div className="hparams-metrics-wrap">
        <div className="hparams-message hparams-empty">
          Pick one or more runs in the table to plot their metric history.
        </div>
      </div>
    );
  }

  if (status === 'error') {
    return (
      <div className="hparams-metrics-wrap">
        <div className="hparams-message hparams-error">
          {error}{' '}
          <button type="button" className="hparams-link-btn" onClick={refresh}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (status === 'ready' && metricKeys.length === 0) {
    return (
      <div className="hparams-metrics-wrap">
        <div className="hparams-message hparams-empty">
          None of these runs logged any metrics.
        </div>
      </div>
    );
  }

  const note = missingNote(missing, activeMetric);

  return (
    <div className="hparams-metrics-wrap">
      <div className="hparams-toolbar">
        <label className="hparams-colorby">
          metric
          <select
            className="hparams-metric-select"
            value={activeMetric || ''}
            onChange={(e) => onMetric(e.target.value)}
            disabled={metricKeys.length === 0}
            aria-label="Metric to plot"
          >
            {metricKeys.map((key) => (
              <option key={key} value={key}>
                {key}
              </option>
            ))}
          </select>
        </label>
        <span className="hparams-plot-note">
          {plotted.length} of {records.length}{' '}
          {records.length === 1 ? 'run' : 'runs'}
          {note ? ' · ' + note : ''}
        </span>
        <button type="button" className="hparams-link-btn" onClick={refresh}>
          Refresh
        </button>
      </div>
      <div className="hparams-metrics-plot" ref={plotRef} />
      {status === 'loading' ? (
        <div className="hparams-plot-overlay">Loading metric history…</div>
      ) : plotted.length === 0 && activeMetric ? (
        <div className="hparams-plot-overlay">
          No run logged {activeMetric} yet.
        </div>
      ) : null}
    </div>
  );
};

export default React.memo(HParamsMetrics);
