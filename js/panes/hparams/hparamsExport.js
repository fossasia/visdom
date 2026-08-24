/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import { isMissing, runLabel } from './hparamsUtils';

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
