/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import TreeSelect from 'rc-tree-select';
import React, { useCallback, useMemo, useState } from 'react';

import {
  buildColumns,
  filterRecords,
  formatValue,
  isNumeric,
  makeComparator,
  numericExtent,
  spineStyle,
} from './hparamsUtils';

const RUN_COLUMN_ID = 'run:name';
const CONTROL_STYLE = { width: 150 };

function nextSort(current, columnId) {
  if (current.by !== columnId) return { by: columnId, dir: 'asc' };
  if (current.dir === 'asc') return { by: columnId, dir: 'desc' };
  return { by: null, dir: null };
}

function ariaSort(sort, columnId) {
  if (sort.by !== columnId) return 'none';
  return sort.dir === 'asc' ? 'ascending' : 'descending';
}

function accessorFor(sortBy, columns) {
  if (sortBy === RUN_COLUMN_ID) {
    return (record) => record.name || record.env_id;
  }
  const col = columns.find((c) => c.id === sortBy);
  return col ? col.accessor : null;
}

const SortCaret = ({ sort, columnId }) => {
  const active = sort.by === columnId;
  const glyph = !active ? '⇅' : sort.dir === 'asc' ? '▲' : '▼';
  return (
    <span
      className={
        'hparams-caret ' +
        (active ? 'hparams-caret-active' : 'hparams-caret-idle')
      }
      aria-hidden="true"
    >
      {glyph}
    </span>
  );
};

const SortHeader = ({ sort, columnId, label, scopeClass, onSort }) => {
  const active = sort.by === columnId;
  return (
    <th
      scope="col"
      className={
        'hparams-cell ' + scopeClass + (active ? ' hparams-th-active' : '')
      }
      aria-sort={ariaSort(sort, columnId)}
    >
      <button
        type="button"
        className="hparams-sort-btn"
        onClick={() => onSort(columnId)}
        title={'Sort by ' + label}
      >
        <span className="hparams-th-label">{label}</span>
        <SortCaret sort={sort} columnId={columnId} />
      </button>
    </th>
  );
};

const HParamsRow = React.memo(function HParamsRow({
  record,
  columns,
  colorBy,
  extent,
  isSelected,
  onToggle,
  groupStartIds,
}) {
  const runLabel = record.name || record.env_id || 'run';
  return (
    <tr
      className={
        isSelected ? 'hparams-row hparams-row-selected' : 'hparams-row'
      }
    >
      <td className="hparams-cell hparams-cell-select">
        <input
          type="checkbox"
          checked={isSelected}
          onChange={() => onToggle(record.env_id)}
          aria-label={'Select ' + runLabel}
        />
      </td>
      <th scope="row" className="hparams-cell hparams-cell-run">
        <div className="hparams-run-cell" title={runLabel}>
          <span className="hparams-run-name">{runLabel}</span>
          {record.status ? (
            <span
              className={'hparams-run-status hparams-status-' + record.status}
            >
              {record.status}
            </span>
          ) : null}
        </div>
      </th>
      {columns.map((col) => {
        const value = col.accessor(record);
        const style =
          colorBy && col.id === colorBy ? spineStyle(value, extent) : null;
        const cls =
          'hparams-cell' +
          (isNumeric(value) ? ' hparams-cell-num' : '') +
          (style ? ' hparams-cell-spine' : '') +
          (groupStartIds.has(col.id) ? ' hparams-col-sep' : '');
        return (
          <td key={col.id} className={cls} style={style || undefined}>
            {formatValue(value)}
          </td>
        );
      })}
    </tr>
  );
});

const HParamsTable = ({ records, paramKeys, metricKeys, tagKeys }) => {
  const [sort, setSort] = useState({ by: null, dir: null });
  const [filter, setFilter] = useState('');
  const [colorBy, setColorBy] = useState(null);
  const [selected, setSelected] = useState(() => new Set());

  const columns = useMemo(
    () => buildColumns(paramKeys, metricKeys, tagKeys),
    [paramKeys, metricKeys, tagKeys]
  );
  const colorCols = useMemo(
    () =>
      columns.filter(
        (c) =>
          (c.group === 'param' || c.group === 'metric') &&
          numericExtent(records, c.accessor)
      ),
    [columns, records]
  );
  const colorParamCols = colorCols.filter((c) => c.group === 'param');
  const colorMetricCols = colorCols.filter((c) => c.group === 'metric');

  const groupStartIds = useMemo(() => {
    const ids = new Set();
    let prev = null;
    columns.forEach((c) => {
      if (c.group !== prev) ids.add(c.id);
      prev = c.group;
    });
    return ids;
  }, [columns]);

  const filtered = useMemo(
    () => filterRecords(records, filter, columns),
    [records, filter, columns]
  );

  const rows = useMemo(() => {
    if (!sort.by) return filtered;
    const accessor = accessorFor(sort.by, columns);
    if (!accessor) return filtered;
    return filtered.slice().sort(makeComparator(accessor, sort.dir));
  }, [filtered, sort, columns]);

  const extent = useMemo(() => {
    if (!colorBy) return null;
    const col = columns.find((c) => c.id === colorBy);
    if (!col) return null;
    return numericExtent(records, col.accessor);
  }, [records, colorBy, columns]);

  const handleSort = useCallback((columnId) => {
    setSort((prev) => nextSort(prev, columnId));
  }, []);

  const handleSortSelect = useCallback((value) => {
    setSort((prev) =>
      value ? { by: value, dir: prev.dir || 'asc' } : { by: null, dir: null }
    );
  }, []);

  const cycleDir = useCallback(() => {
    setSort((prev) => {
      if (!prev.by) return prev;
      if (prev.dir === 'asc') return { by: prev.by, dir: 'desc' };
      return { by: null, dir: null };
    });
  }, []);

  const toggle = useCallback((envId) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(envId)) next.delete(envId);
      else next.add(envId);
      return next;
    });
  }, []);

  const allSelected =
    rows.length > 0 && rows.every((r) => selected.has(r.env_id));

  const handleSelectAll = useCallback(() => {
    setSelected((prev) => {
      const next = new Set(prev);
      const everyOn = rows.length > 0 && rows.every((r) => next.has(r.env_id));
      rows.forEach((r) =>
        everyOn ? next.delete(r.env_id) : next.add(r.env_id)
      );
      return next;
    });
  }, [rows]);

  const bands = [
    { key: 'param', label: 'params' },
    { key: 'metric', label: 'metrics' },
    { key: 'tag', label: 'tags' },
  ]
    .map((b) => ({
      ...b,
      span: columns.filter((c) => c.group === b.key).length,
    }))
    .filter((b) => b.span > 0);

  const sortTreeData = [
    { key: RUN_COLUMN_ID, value: RUN_COLUMN_ID, title: 'run' },
    ...bands.map((b) => ({
      key: '__g_' + b.key,
      value: '__g_' + b.key,
      title: b.label,
      selectable: false,
      children: columns
        .filter((c) => c.group === b.key)
        .map((c) => ({ key: c.id, value: c.id, title: c.label })),
    })),
  ];

  const colorTreeData = [];
  if (colorParamCols.length) {
    colorTreeData.push({
      key: '__cg_param',
      value: '__cg_param',
      title: 'params',
      selectable: false,
      children: colorParamCols.map((c) => ({
        key: c.id,
        value: c.id,
        title: c.label,
      })),
    });
  }
  if (colorMetricCols.length) {
    colorTreeData.push({
      key: '__cg_metric',
      value: '__cg_metric',
      title: 'metrics',
      selectable: false,
      children: colorMetricCols.map((c) => ({
        key: c.id,
        value: c.id,
        title: c.label,
      })),
    });
  }

  return (
    <div className="hparams-table-wrap">
      <div className="hparams-toolbar">
        <input
          type="text"
          className="hparams-filter"
          placeholder="Filter runs…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          aria-label="Filter runs"
        />
        <span className="hparams-sortby">
          sort by:
          <TreeSelect
            className="hparams-treeselect"
            style={CONTROL_STYLE}
            value={sort.by || undefined}
            placeholder="none"
            allowClear
            treeLine
            treeDefaultExpandAll
            dropdownMatchSelectWidth={false}
            treeData={sortTreeData}
            onChange={(value) => handleSortSelect(value || '')}
          />
          <button
            type="button"
            className="hparams-dir-btn"
            onClick={cycleDir}
            disabled={!sort.by}
            title={
              sort.dir === 'asc'
                ? 'Ascending — click for descending'
                : 'Descending — click to clear'
            }
            aria-label={
              sort.dir === 'desc' ? 'Sort descending' : 'Sort ascending'
            }
          >
            {!sort.by ? '⇅' : sort.dir === 'asc' ? '▲' : '▼'}
          </button>
        </span>
        {colorCols.length ? (
          <span className="hparams-colorby">
            color by:
            <TreeSelect
              className="hparams-treeselect"
              style={CONTROL_STYLE}
              value={colorBy || undefined}
              placeholder="none"
              allowClear
              treeLine
              treeDefaultExpandAll
              dropdownMatchSelectWidth={false}
              treeData={colorTreeData}
              onChange={(value) => setColorBy(value || null)}
            />
          </span>
        ) : null}
        {selected.size ? (
          <span className="hparams-selected-count">
            {selected.size} selected
          </span>
        ) : null}
      </div>

      <div className="hparams-table-scroll">
        <table className="hparams-table">
          <thead>
            <tr className="hparams-group-row">
              <th
                className="hparams-cell hparams-col-blank"
                aria-hidden="true"
              />
              <th
                className="hparams-cell hparams-col-blank"
                aria-hidden="true"
              />
              {bands.map((b) => (
                <th
                  key={b.key}
                  className={'hparams-col-group hparams-group-' + b.key}
                  colSpan={b.span}
                >
                  {b.label}
                </th>
              ))}
            </tr>
            <tr className="hparams-head-row">
              <th className="hparams-cell hparams-th-select" scope="col">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={handleSelectAll}
                  aria-label="Select all runs"
                />
              </th>
              <SortHeader
                sort={sort}
                columnId={RUN_COLUMN_ID}
                label="run"
                scopeClass="hparams-th-run"
                onSort={handleSort}
              />
              {columns.map((col) => (
                <SortHeader
                  key={col.id}
                  sort={sort}
                  columnId={col.id}
                  label={col.label}
                  scopeClass={
                    'hparams-th-' +
                    col.group +
                    (groupStartIds.has(col.id) ? ' hparams-col-sep' : '')
                  }
                  onSort={handleSort}
                />
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td className="hparams-nomatch" colSpan={2 + columns.length}>
                  No runs match “{filter}”.
                </td>
              </tr>
            ) : (
              rows.map((record, index) => (
                <HParamsRow
                  key={record.env_id || index}
                  record={record}
                  columns={columns}
                  colorBy={colorBy}
                  extent={extent}
                  isSelected={selected.has(record.env_id)}
                  onToggle={toggle}
                  groupStartIds={groupStartIds}
                />
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default HParamsTable;
