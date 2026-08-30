/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import TreeSelect from 'rc-tree-select';
import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { fetchExperimentComparison } from '../../api/experimentsApi';

/*
 * Shared helpers for the hyper-parameter views, so the ordering and formatting
 * rules live in one place and can mirror the Python backend exactly. The
 * comparator matches
 * visdom.experiments.store._order_key for every value the backend can order --
 * including booleans, which Python orders by str(value), i.e. "True"/"False"
 * -- and visdom.experiments.store._is_absent for values with nothing to sort
 * by, which sort last in both directions. NaN is one of those on both sides:
 * the backend counts a non-finite number as absent, matching what survives its
 * own JSON round trip, and isMissing() here counts it the same way.
 */

const SPINE_LIGHT = [235, 240, 249];
const SPINE_DARK = [59, 89, 152];

const SPINE_TEXT_CANDIDATES = [
  { color: '#333', rgb: [51, 51, 51] },
  { color: '#fff', rgb: [255, 255, 255] },
  { color: '#000', rgb: [0, 0, 0] },
];

const MIN_CONTRAST = 4.5;

const PRECISION = 4;
const EXPONENTIAL_ABOVE = 1e6;
const EXPONENTIAL_BELOW = 1e-4;

export const COLUMN_GROUPS = [
  { key: 'param', label: 'params' },
  { key: 'metric', label: 'metrics' },
  { key: 'tag', label: 'tags' },
];

export const NUMERIC_GROUPS = COLUMN_GROUPS.slice(0, 2);

export function runLabel(record) {
  return (record && (record.name || record.env_id)) || 'run';
}

export function isMissing(value) {
  return (
    value === undefined ||
    value === null ||
    (typeof value === 'number' && Number.isNaN(value))
  );
}

export function isNumeric(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

export function isNumberLike(value) {
  return typeof value === 'number' && !Number.isNaN(value);
}

export function orderKey(value) {
  if (typeof value === 'boolean') {
    return [1, 0, value ? 'True' : 'False'];
  }
  if (isNumberLike(value)) {
    return [0, value, ''];
  }
  return [1, 0, String(value)];
}

export function compareOrderKeys(a, b) {
  if (a[0] !== b[0]) return a[0] - b[0];
  if (a[1] !== b[1]) return a[1] < b[1] ? -1 : 1;
  if (a[2] < b[2]) return -1;
  if (a[2] > b[2]) return 1;
  return 0;
}

export function makeComparator(accessor, direction) {
  const descending = direction === 'desc';
  return (rowA, rowB) => {
    const va = accessor(rowA);
    const vb = accessor(rowB);
    const ma = isMissing(va);
    const mb = isMissing(vb);
    if (ma && mb) return 0;
    if (ma) return 1;
    if (mb) return -1;
    const cmp = compareOrderKeys(orderKey(va), orderKey(vb));
    return descending ? -cmp : cmp;
  };
}

export function buildColumns(paramKeys, metricKeys, tagKeys) {
  const columns = [];
  (paramKeys || []).forEach((key) => {
    columns.push({
      id: 'param:' + key,
      label: key,
      group: 'param',
      accessor: (record) => (record.params ? record.params[key] : undefined),
    });
  });
  (metricKeys || []).forEach((key) => {
    columns.push({
      id: 'metric:' + key,
      label: key,
      group: 'metric',
      metricKey: key,
      accessor: (record) => (record.metrics ? record.metrics[key] : undefined),
    });
  });
  (tagKeys || []).forEach((key) => {
    columns.push({
      id: 'tag:' + key,
      label: key,
      group: 'tag',
      accessor: (record) => (record.tags ? record.tags[key] : undefined),
    });
  });
  return columns;
}

export function groupColumnTree(columns, groups) {
  const cols = columns || [];
  return (groups || [])
    .map(({ key, label }) => {
      const children = cols.filter((col) => col.group === key);
      if (children.length === 0) return null;
      return {
        key: '__g_' + key,
        value: '__g_' + key,
        title: label,
        selectable: false,
        checkable: false,
        children: children.map((col) => ({
          key: col.id,
          value: col.id,
          title: col.label,
        })),
      };
    })
    .filter(Boolean);
}

export function formatValue(value) {
  if (isMissing(value)) return '—';
  if (typeof value === 'number') {
    if (value === Infinity) return '∞';
    if (value === -Infinity) return '-∞';
    if (Number.isInteger(value)) return String(value);
    const rounded = parseFloat(value.toPrecision(PRECISION));
    const magnitude = Math.abs(rounded);
    if (
      magnitude >= EXPONENTIAL_ABOVE ||
      (magnitude > 0 && magnitude < EXPONENTIAL_BELOW)
    ) {
      return rounded.toExponential(PRECISION - 1).replace('e+', 'e');
    }
    return String(rounded);
  }
  return String(value);
}

export function filterRecords(records, query, columns) {
  const q = (query || '').trim().toLowerCase();
  if (!q) return records;
  return records.filter((record) => {
    const label = String(record.name || record.env_id || '').toLowerCase();
    if (label.indexOf(q) !== -1) return true;
    for (let i = 0; i < columns.length; i++) {
      const v = columns[i].accessor(record);
      if (!isMissing(v) && String(v).toLowerCase().indexOf(q) !== -1) {
        return true;
      }
    }
    return false;
  });
}

export function toNumericColumn(records, accessor) {
  return (records || []).map((record) => {
    const value = accessor(record);
    return isNumeric(value) ? value : null;
  });
}

export function numericExtent(records, accessor) {
  let min = Infinity;
  let max = -Infinity;
  records.forEach((record) => {
    const v = accessor(record);
    if (isNumeric(v)) {
      if (v < min) min = v;
      if (v > max) max = v;
    }
  });
  if (min === Infinity) return null;
  return { min, max };
}

function channelLuminance(channel) {
  const c = channel / 255;
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

export function relativeLuminance(rgb) {
  return (
    0.2126 * channelLuminance(rgb[0]) +
    0.7152 * channelLuminance(rgb[1]) +
    0.0722 * channelLuminance(rgb[2])
  );
}

export function contrastRatio(rgbA, rgbB) {
  const a = relativeLuminance(rgbA);
  const b = relativeLuminance(rgbB);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

export function textColorFor(rgb) {
  let fallback = SPINE_TEXT_CANDIDATES[0];
  let fallbackRatio = 0;
  for (let i = 0; i < SPINE_TEXT_CANDIDATES.length; i++) {
    const candidate = SPINE_TEXT_CANDIDATES[i];
    const ratio = contrastRatio(rgb, candidate.rgb);
    if (ratio >= MIN_CONTRAST) return candidate.color;
    if (ratio > fallbackRatio) {
      fallbackRatio = ratio;
      fallback = candidate;
    }
  }
  return fallback.color;
}

export function spineColor(value, extent) {
  if (!extent || !isNumeric(value)) return null;
  const { min, max } = extent;
  let t = max > min ? (value - min) / (max - min) : 1;
  if (t < 0) t = 0;
  else if (t > 1) t = 1;
  return SPINE_LIGHT.map((from, i) =>
    Math.round(from + (SPINE_DARK[i] - from) * t)
  );
}

export function spineStyle(value, extent) {
  const rgb = spineColor(value, extent);
  if (!rgb) return null;
  return {
    backgroundColor: 'rgb(' + rgb.join(', ') + ')',
    color: textColorFor(rgb),
  };
}

export function buildRowIds(records) {
  const ids = new Map();
  (records || []).forEach((record, index) => {
    ids.set(record, record.env_id || 'row:' + index);
  });
  return ids;
}

export function cellClass(value, options) {
  const opts = options || {};
  return (
    'hparams-cell' +
    (isNumberLike(value) ? ' hparams-cell-num' : '') +
    (opts.spine ? ' hparams-cell-spine' : '') +
    (opts.separator ? ' hparams-col-sep' : '')
  );
}

/*
 * Numeric param/metric columns only — the axes a scatter matrix (SPLOM) or a
 * "color by" ramp can actually plot. Tags are excluded (categorical) and any
 * column whose values are all missing/non-numeric is dropped.
 */
export function selectNumericColumns(records, columns) {
  return (columns || []).filter(
    (col) =>
      (col.group === 'param' || col.group === 'metric') &&
      numericExtent(records, col.accessor) !== null
  );
}

export function defaultDimIds(numericCols, isDense) {
  const cols = numericCols || [];
  const dense = isDense ? cols.filter(isDense) : cols;
  const pick = (group) =>
    dense.find((col) => col.group === group) ||
    cols.find((col) => col.group === group);
  const param = pick('param');
  const metric = pick('metric');
  if (param && metric) return [param.id, metric.id];
  return cols.slice(0, 2).map((col) => col.id);
}

export function coincidentRuns(records, colX, colY, x, y) {
  if (!colX || !colY) return [];
  const names = [];
  (records || []).forEach((record) => {
    const vx = colX.accessor(record);
    const vy = colY.accessor(record);
    if (isNumeric(vx) && isNumeric(vy) && vx === x && vy === y) {
      names.push(runLabel(record));
    }
  });
  return names;
}

export function resolveColor(records, columns, colorById) {
  const col = colorById
    ? (columns || []).find((c) => c.id === colorById)
    : null;
  if (col) {
    const ext = numericExtent(records, col.accessor);
    return {
      values: toNumericColumn(records, col.accessor),
      label: col.label,
      cmin: ext ? ext.min : 0,
      cmax: ext ? ext.max : 1,
    };
  }
  return {
    values: (records || []).map((_, i) => i + 1),
    label: 'run order',
    cmin: 1,
    cmax: Math.max((records || []).length, 1),
  };
}

export function completeRecords(records, cols) {
  return (records || []).filter((record) =>
    (cols || []).every((col) => isNumeric(col.accessor(record)))
  );
}

/*
 * Build Plotly `parcoords` dimensions. Plotly cannot render null/NaN cells —
 * one sparse axis corrupts every line -- so callers pass records that already
 * hold a numeric value on every axis (see completeRecords). Each axis spans its
 * exact data range; an axis whose values are all equal gets a small symmetric
 * range so it does not collapse to zero height.
 */
export function buildParcoordsDimensions(records, columns, selectedIds) {
  const byId = new Map((columns || []).map((col) => [col.id, col]));
  const dimensions = [];
  (selectedIds || []).forEach((id) => {
    const col = byId.get(id);
    if (!col) return;
    const extent = numericExtent(records, col.accessor);
    if (extent === null) return;
    const values = (records || []).map((record) => col.accessor(record));
    const dimension = { label: col.label, values };
    if (extent.min === extent.max) {
      const delta = Math.abs(extent.max) * 0.05 || 1;
      dimension.range = [extent.min - delta, extent.max + delta];
    } else {
      dimension.range = [extent.min, extent.max];
    }
    dimensions.push(dimension);
  });
  return dimensions;
}

const MAX_CATEGORIES = 12;

export const STATUS_ORDER = ['running', 'finished', 'failed'];

function distinctValues(records, accessor) {
  const seen = new Map();
  let missing = 0;
  (records || []).forEach((record) => {
    const value = accessor(record);
    if (isMissing(value)) {
      missing += 1;
      return;
    }
    const key = typeof value + ':' + String(value);
    if (!seen.has(key)) seen.set(key, value);
  });
  return { values: Array.from(seen.values()), missing };
}

export function buildFilterSpecs(records, columns) {
  const specs = [];
  (columns || []).forEach((col) => {
    const { values, missing } = distinctValues(records, col.accessor);
    if (values.length === 0) return;
    const numericColumn =
      (col.group === 'param' || col.group === 'metric') &&
      values.every((value) => isNumeric(value));
    if (numericColumn && values.length > 2) {
      const extent = numericExtent(records, col.accessor);
      const integral = values.every((value) => Number.isInteger(value));
      const span = extent.max - extent.min;
      specs.push({
        id: col.id,
        label: col.label,
        group: col.group,
        accessor: col.accessor,
        kind: 'range',
        min: extent.min,
        max: extent.max,
        step: integral ? 1 : span / 100 || 1,
        missing,
      });
      return;
    }
    if (values.length <= MAX_CATEGORIES) {
      specs.push({
        id: col.id,
        label: col.label,
        group: col.group,
        accessor: col.accessor,
        kind: 'category',
        values: values
          .slice()
          .sort((a, b) => compareOrderKeys(orderKey(a), orderKey(b))),
        missing,
      });
    }
  });
  return specs;
}

export function collectStatuses(records) {
  const present = new Set();
  (records || []).forEach((record) => {
    if (record.status) present.add(record.status);
  });
  const known = STATUS_ORDER.filter((status) => present.has(status));
  const extra = Array.from(present)
    .filter((status) => STATUS_ORDER.indexOf(status) === -1)
    .sort();
  return known.concat(extra);
}

export function keepsMissing(entry) {
  return !entry || entry.includeMissing !== false;
}

function passesSpec(record, spec, entry, accessor) {
  if (!entry) return true;
  const value = accessor(record);
  if (isMissing(value)) return keepsMissing(entry);
  if (spec.kind === 'range') {
    if (!isNumeric(value)) return keepsMissing(entry);
    return value >= entry.lo && value <= entry.hi;
  }
  if (!entry.values || entry.values.length === 0) return true;
  return entry.values.indexOf(value) !== -1;
}

export function applyFilters(records, specs, filters) {
  const state = filters || {};
  const statuses = state.statuses;
  const columns = state.columns || {};
  const active = (specs || []).filter((spec) => columns[spec.id]);
  if ((!statuses || statuses.length === 0) && active.length === 0) {
    return records;
  }
  return (records || []).filter((record) => {
    if (statuses && statuses.length > 0) {
      if (statuses.indexOf(record.status) === -1) return false;
    }
    for (let i = 0; i < active.length; i++) {
      const spec = active[i];
      if (!passesSpec(record, spec, columns[spec.id], spec.accessor)) {
        return false;
      }
    }
    return true;
  });
}

export function countActiveFilters(filters, specs) {
  const state = filters || {};
  const columns = state.columns || {};
  let count = state.statuses && state.statuses.length > 0 ? 1 : 0;
  (specs || []).forEach((spec) => {
    const entry = columns[spec.id];
    if (!entry) return;
    const narrowed =
      spec.kind === 'range'
        ? entry.lo > spec.min || entry.hi < spec.max
        : entry.values && entry.values.length > 0;
    if (narrowed || !keepsMissing(entry)) count += 1;
  });
  return count;
}

export function sameValue(a, b) {
  if (typeof a === 'boolean' || typeof b === 'boolean') return a === b;
  if (typeof a === 'number' && typeof b === 'number') {
    if (Number.isNaN(a) && Number.isNaN(b)) return true;
    return a === b;
  }
  return a === b;
}

export function buildComparison(records, columns) {
  const runs = records || [];
  const sections = { param: [], metric: [], tag: [] };
  (columns || []).forEach((col) => {
    const cells = runs.map((record) => col.accessor(record));
    let present = 0;
    const groups = [];
    cells.forEach((value) => {
      if (isMissing(value)) return;
      present += 1;
      const group = groups.find((g) => sameValue(g.value, value));
      if (group) group.count += 1;
      else groups.push({ value, count: 1 });
    });
    if (present === 0) return;
    const shared = present === runs.length && groups.length === 1;
    if (!sections[col.group]) return;
    sections[col.group].push({
      id: col.id,
      label: col.label,
      group: col.group,
      accessor: col.accessor,
      cells,
      groups,
      shared,
    });
  });
  return sections;
}

export function buildMetricSeries(experiments) {
  const runs = [];
  const metricKeys = new Set();
  (experiments || []).forEach((exp) => {
    if (!exp || typeof exp !== 'object') return;
    if (typeof exp.env_id !== 'string') return;
    const raw = new Map();
    (exp.metrics || []).forEach((metric) => {
      if (!metric || typeof metric.key !== 'string') return;
      if (!raw.has(metric.key)) raw.set(metric.key, []);
      raw.get(metric.key).push(metric);
      metricKeys.add(metric.key);
    });
    const series = {};
    raw.forEach((observations, key) => {
      const usesIndex = !observations.every((obs) => isNumeric(obs.step));
      const x = [];
      const y = [];
      if (usesIndex) {
        observations.forEach((obs, index) => {
          x.push(index);
          y.push(isNumeric(obs.value) ? obs.value : null);
        });
      } else {
        const byStep = new Map();
        observations.forEach((obs) => {
          byStep.set(obs.step, isNumeric(obs.value) ? obs.value : null);
        });
        Array.from(byStep.keys())
          .sort((a, b) => a - b)
          .forEach((step) => {
            x.push(step);
            y.push(byStep.get(step));
          });
      }
      series[key] = { x, y, usesIndex };
    });
    runs.push({
      env_id: exp.env_id,
      label: runLabel(exp),
      series,
    });
  });
  return { runs, metricKeys: Array.from(metricKeys).sort() };
}

export function selectMetricSeries(runs, metricKey, colorIndex) {
  const plotted = [];
  const missing = [];
  (runs || []).forEach((run) => {
    const series = metricKey && run.series ? run.series[metricKey] : null;
    if (!series || !series.y.some((value) => isNumeric(value))) {
      missing.push(run.label);
      return;
    }
    const index = colorIndex ? colorIndex.get(run.env_id) : undefined;
    plotted.push({
      env_id: run.env_id,
      label: run.label,
      x: series.x,
      y: series.y,
      usesIndex: series.usesIndex,
      colorIndex: index === undefined ? plotted.length : index,
    });
  });
  return { plotted, missing };
}

export const StatusBadge = ({ status }) =>
  status ? (
    <span className={'hparams-run-status hparams-status-' + status}>
      {status}
    </span>
  ) : null;

const TREE_PROPS = {
  treeLine: true,
  treeDefaultExpandAll: true,
  dropdownMatchSelectWidth: false,
};

export const HParamsMessage = ({ wrapClass, tone, children }) => {
  const message = (
    <div className={'hparams-message hparams-' + (tone || 'empty')}>
      {children}
    </div>
  );
  return wrapClass ? <div className={wrapClass}>{message}</div> : message;
};

export const ColumnSelect = ({
  value,
  placeholder,
  treeData,
  onChange,
  label,
}) => (
  <TreeSelect
    {...TREE_PROPS}
    className="hparams-treeselect hparams-select-narrow"
    value={value || undefined}
    placeholder={placeholder}
    allowClear
    treeData={treeData}
    onChange={(next) => onChange(next || null)}
    aria-label={label}
  />
);

export const ColumnMultiSelect = ({
  value,
  placeholder,
  treeData,
  maxCount,
  onChange,
  label,
}) => (
  <TreeSelect
    {...TREE_PROPS}
    className="hparams-treeselect hparams-select-wide"
    value={value}
    placeholder={placeholder}
    treeCheckable
    multiple
    showCheckedStrategy="SHOW_CHILD"
    maxTagCount={3}
    treeData={treeData}
    onChange={(next) =>
      onChange(Array.isArray(next) ? next.slice(0, maxCount) : [])
    }
    aria-label={label}
  />
);

const CSV_MIME = 'text/csv;charset=utf-8';
const JSON_MIME = 'application/json';
const NEEDS_QUOTING = /[",\r\n]/;
const FORMULA_START = /^[=+\-@\t\r]/;
const NUMERIC = /^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/;

function csvCell(value) {
  if (isMissing(value)) return '';
  const raw =
    value !== null && typeof value === 'object'
      ? JSON.stringify(value)
      : String(value);
  if (FORMULA_START.test(raw) && !NUMERIC.test(raw)) {
    return '"\'' + raw.replace(/"/g, '""') + '"';
  }
  if (NEEDS_QUOTING.test(raw)) return '"' + raw.replace(/"/g, '""') + '"';
  return raw;
}

export function buildCsv(records, columns) {
  const cols = columns || [];
  const header = ['run', 'env_id', 'status'].concat(
    cols.map((col) => col.group + '.' + col.label)
  );
  const lines = [header.map(csvCell).join(',')];
  (records || []).forEach((record) => {
    const row = [runLabel(record), record.env_id, record.status].concat(
      cols.map((col) => col.accessor(record))
    );
    lines.push(row.map(csvCell).join(','));
  });
  return lines.join('\r\n');
}

export function buildJson(records, paramKeys, metricKeys, tagKeys) {
  return JSON.stringify(
    {
      records: records || [],
      param_keys: paramKeys || [],
      metric_keys: metricKeys || [],
      tag_keys: tagKeys || [],
    },
    null,
    2
  );
}

export function downloadText(text, filename, mime) {
  const blob = new Blob([text], { type: mime });
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.download = filename;
  link.href = url;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  window.URL.revokeObjectURL(url);
}

export function downloadJson(value, filename) {
  downloadText(JSON.stringify(value), filename, JSON_MIME);
}

export function exportCsv(records, columns, filename) {
  downloadText(buildCsv(records, columns), filename, CSV_MIME);
}

export function exportJson(records, keys, filename) {
  const text = buildJson(
    records,
    keys.paramKeys,
    keys.metricKeys,
    keys.tagKeys
  );
  downloadText(text, filename, JSON_MIME);
}

/*
 * The Plotly-facing helpers below are the one part of this module that reaches
 * for the global Plotly instance and the DOM rather than staying pure.
 */

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

export function useHParamsColumns(paramKeys, metricKeys, tagKeys) {
  return useMemo(
    () => buildColumns(paramKeys, metricKeys, tagKeys),
    [paramKeys, metricKeys, tagKeys]
  );
}

export function useHParamsAxes({
  records,
  columnRecords,
  paramKeys,
  metricKeys,
  tagKeys,
  selectedDims,
  colorBy,
  maxDims,
  preferDense = false,
}) {
  const pickerRecords = columnRecords || records;

  const columns = useHParamsColumns(paramKeys, metricKeys, tagKeys);

  const numericCols = useMemo(
    () => selectNumericColumns(pickerRecords, columns),
    [pickerRecords, columns]
  );

  const dims = useMemo(() => {
    const valid = new Set(numericCols.map((col) => col.id));
    if (Array.isArray(selectedDims)) {
      const chosen = selectedDims.filter((id) => valid.has(id));
      if (chosen.length > 0 || selectedDims.length === 0) {
        return chosen.slice(0, maxDims);
      }
    }
    const isDense = preferDense
      ? (col) => records.every((record) => isNumeric(col.accessor(record)))
      : null;
    return defaultDimIds(numericCols, isDense).slice(0, maxDims);
  }, [selectedDims, numericCols, records, maxDims, preferDense]);

  const activeColorBy = useMemo(() => {
    if (!colorBy) return null;
    return numericCols.some((col) => col.id === colorBy) ? colorBy : null;
  }, [colorBy, numericCols]);

  const treeData = useMemo(
    () => groupColumnTree(numericCols, NUMERIC_GROUPS),
    [numericCols]
  );

  const truncated =
    (selectedDims || []).filter((id) =>
      numericCols.some((col) => col.id === id)
    ).length > maxDims;

  return {
    columns,
    numericCols,
    dims,
    colorBy: activeColorBy,
    treeData,
    truncated,
    hasPlot: numericCols.length >= 2,
  };
}

const NO_EXPERIMENTS = [];
const COMPARE_BATCH_SIZE = 1000;

function batchIds(ids) {
  const batches = [];
  for (let i = 0; i < ids.length; i += COMPARE_BATCH_SIZE) {
    batches.push(ids.slice(i, i + COMPARE_BATCH_SIZE));
  }
  return batches;
}

export function useExperimentMetrics(records, cacheRef) {
  const [nonce, setNonce] = useState(0);
  const [state, setState] = useState({
    status: 'idle',
    error: null,
    experiments: NO_EXPERIMENTS,
  });

  const envIds = useMemo(
    () => (records || []).map((r) => r.env_id).filter((id) => !!id),
    [records]
  );

  const refresh = useCallback(() => {
    const cache = cacheRef.current;
    if (cache) envIds.forEach((id) => cache.delete(id));
    setNonce((n) => n + 1);
  }, [cacheRef, envIds]);

  useEffect(() => {
    const cache = cacheRef.current;
    if (envIds.length === 0) {
      setState({ status: 'idle', error: null, experiments: NO_EXPERIMENTS });
      return undefined;
    }

    const readCache = () => envIds.map((id) => cache.get(id)).filter(Boolean);
    const wanted = envIds.filter((id) => !cache.has(id));
    if (wanted.length === 0) {
      setState({ status: 'ready', error: null, experiments: readCache() });
      return undefined;
    }

    let cancelled = false;
    const controller = new AbortController();
    setState((prev) => ({ ...prev, status: 'loading', error: null }));

    Promise.all(
      batchIds(wanted).map((ids) =>
        fetchExperimentComparison(ids, controller.signal)
      )
    )
      .then((replies) => {
        if (cancelled) return;
        replies.forEach((reply) => {
          const loaded = (reply && reply.experiments) || [];
          loaded.forEach((exp) => {
            if (exp && typeof exp.env_id === 'string')
              cache.set(exp.env_id, exp);
          });
        });
        setState({ status: 'ready', error: null, experiments: readCache() });
      })
      .catch((err) => {
        if (cancelled || (err && err.name === 'AbortError')) return;
        setState({
          status: 'error',
          error: (err && err.message) || 'Could not load metric history.',
          experiments: NO_EXPERIMENTS,
        });
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [envIds, nonce, cacheRef]);

  const parsed = useMemo(
    () => buildMetricSeries(state.experiments),
    [state.experiments]
  );

  return {
    status: state.status,
    error: state.error,
    runs: parsed.runs,
    metricKeys: parsed.metricKeys,
    refresh,
  };
}
