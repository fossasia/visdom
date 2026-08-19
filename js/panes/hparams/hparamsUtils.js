/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

/*
 * Pure helpers for the hyper-parameter table. Kept free of React so the
 * ordering and formatting rules live in one place and can mirror the Python
 * backend exactly. The comparator matches
 * visdom.experiments.store._order_key for every value the backend can order --
 * including booleans, which Python orders by str(value), i.e. "True"/"False"
 * -- and visdom.experiments.store._sort_pairs for absent values, which sort
 * last in both directions. NaN is the one deliberate divergence: the backend
 * leaves it in the ordered bucket, where Python's sort gives it no defined
 * position, so the table treats it as missing instead.
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

/*
 * The axes a plot opens on: one param against one metric, so a freshly opened
 * view reads as a single relationship rather than every numeric column at once.
 * Callers may pass `isDense` to prefer columns that hold a value on every run,
 * since a sparse axis costs a parallel-coordinates plot whole lines. Falls back
 * to the first two columns when the data has no param/metric pair to offer.
 */
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

/*
 * Build Plotly `splom` dimensions from the chosen column ids. Order follows
 * selectedIds; unknown ids are skipped; missing/non-numeric cells become null
 * so Plotly leaves a gap instead of plotting a bogus 0.
 */
export function buildSplomDimensions(records, columns, selectedIds) {
  const byId = new Map((columns || []).map((col) => [col.id, col]));
  const dimensions = [];
  (selectedIds || []).forEach((id) => {
    const col = byId.get(id);
    if (!col) return;
    const values = toNumericColumn(records, col.accessor);
    if (values.every((v) => v === null)) return;
    dimensions.push({ label: col.label, values });
  });
  return dimensions;
}

export function completeRecords(records, cols) {
  return (records || []).filter((record) =>
    (cols || []).every((col) => isNumeric(col.accessor(record)))
  );
}

/*
 * Build Plotly `parcoords` dimensions. Plotly cannot render null/NaN cells —
 * one sparse axis corrupts every line — so callers pass records that already
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

/*
 * A column with more distinct values than this is not offered as a checkbox
 * list — the free-text search is the better tool for high-cardinality strings.
 */
const MAX_CATEGORIES = 12;

/*
 * Statuses come from the Python model (visdom.experiments.models), but the
 * order here is lifecycle order rather than alphabetical so the sidebar reads
 * the way a run progresses.
 */
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

/*
 * Derive one filter control per column. A numeric param/metric with more than
 * two distinct values becomes a range slider; anything with few enough distinct
 * values becomes a checkbox list (this deliberately catches low-cardinality
 * numerics such as batch size, where discrete choices beat a slider). Columns
 * that are neither are skipped rather than rendered as an unusable control.
 *
 * Category values are ordered with the same comparator the table uses, which
 * in turn mirrors the backend's _sort_pairs, so numbers precede strings.
 */
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

/*
 * The statuses actually present in the data, in lifecycle order. Derived rather
 * than hardcoded so a run in a status this build does not know about still gets
 * a checkbox instead of silently becoming unfilterable.
 */
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

/*
 * Whether a filter still admits runs that have no value for its column. Absent
 * means yes: a filter should only ever remove runs it actually judged, so
 * excluding the unmeasured ones has to be asked for.
 */
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

/*
 * Faceted semantics: every active column filter must pass (AND), but within one
 * category list any checked value is enough (OR). A run whose value is missing
 * survives only while that filter keeps missing values, which is what makes a
 * range filter safe to apply to sparse metric columns.
 */
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

/*
 * How many filters the badge should report. A range left at its full extent is
 * not counted: it excludes nothing, so claiming it as active would make the
 * badge disagree with what the user sees.
 */
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
