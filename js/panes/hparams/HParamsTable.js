/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import TreeSelect from 'rc-tree-select';
import React, { useCallback, useEffect, useMemo } from 'react';

import {
  buildColumns,
  COLUMN_GROUPS,
  filterRecords,
  formatValue,
  groupColumnTree,
  isNumberLike,
  makeComparator,
  NUMERIC_GROUPS,
  numericExtent,
  runLabel,
  selectNumericColumns,
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

function directionLabel(sort) {
  if (!sort.by) return 'Sort direction';
  if (sort.dir === 'asc') return 'Sorted ascending — click for descending';
  return 'Sorted descending — click to clear';
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
  rowId,
  columns,
  colorBy,
  extent,
  isSelected,
  onToggle,
  groupStartIds,
}) {
  const label = runLabel(record);
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
          onChange={() => onToggle(rowId)}
          aria-label={'Select ' + label}
        />
      </td>
      <th scope="row" className="hparams-cell hparams-cell-run">
        <div className="hparams-run-cell" title={label}>
          <span className="hparams-run-name">{label}</span>
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
          (isNumberLike(value) ? ' hparams-cell-num' : '') +
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

const HParamsTable = ({
  records,
  paramKeys,
  metricKeys,
  tagKeys,
  sort,
  setSort,
  filter,
  setFilter,
  colorBy,
  setColorBy,
  selected,
  setSelected,
}) => {
  const columns = useMemo(
    () => buildColumns(paramKeys, metricKeys, tagKeys),
    [paramKeys, metricKeys, tagKeys]
  );
  const colorCols = useMemo(
    () => selectNumericColumns(records, columns),
    [records, columns]
  );

  const rowIds = useMemo(() => {
    const ids = new Map();
    records.forEach((record, index) => {
      ids.set(record, record.env_id || 'row:' + index);
    });
    return ids;
  }, [records]);

  useEffect(() => {
    setSort((prev) => {
      if (!prev.by || prev.by === RUN_COLUMN_ID) return prev;
      return columns.some((c) => c.id === prev.by)
        ? prev
        : { by: null, dir: null };
    });
  }, [columns]);

  useEffect(() => {
    setColorBy((prev) =>
      prev && !colorCols.some((c) => c.id === prev) ? null : prev
    );
  }, [colorCols]);

  useEffect(() => {
    setSelected((prev) => {
      if (prev.size === 0) return prev;
      const live = new Set(rowIds.values());
      const next = new Set();
      prev.forEach((id) => {
        if (live.has(id)) next.add(id);
      });
      return next.size === prev.size ? prev : next;
    });
  }, [rowIds]);

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
    setSort((prev) => {
      if (!value) return { by: null, dir: null };
      if (prev.by === value) return { by: value, dir: prev.dir || 'asc' };
      return { by: value, dir: 'asc' };
    });
  }, []);

  const cycleDir = useCallback(() => {
    setSort((prev) => {
      if (!prev.by) return prev;
      if (prev.dir === 'asc') return { by: prev.by, dir: 'desc' };
      return { by: null, dir: null };
    });
  }, []);

  const toggle = useCallback((rowId) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(rowId)) next.delete(rowId);
      else next.add(rowId);
      return next;
    });
  }, []);

  const allSelected =
    rows.length > 0 && rows.every((r) => selected.has(rowIds.get(r)));

  const visibleSelected = useMemo(
    () =>
      rows.reduce(
        (total, r) => (selected.has(rowIds.get(r)) ? total + 1 : total),
        0
      ),
    [rows, rowIds, selected]
  );

  const handleSelectAll = useCallback(() => {
    setSelected((prev) => {
      const next = new Set(prev);
      const everyOn =
        rows.length > 0 && rows.every((r) => next.has(rowIds.get(r)));
      rows.forEach((r) =>
        everyOn ? next.delete(rowIds.get(r)) : next.add(rowIds.get(r))
      );
      return next;
    });
  }, [rows, rowIds]);

  const bands = useMemo(
    () =>
      COLUMN_GROUPS.map((b) => ({
        ...b,
        span: columns.filter((c) => c.group === b.key).length,
      })).filter((b) => b.span > 0),
    [columns]
  );

  const sortTreeData = useMemo(
    () => [
      { key: RUN_COLUMN_ID, value: RUN_COLUMN_ID, title: 'run' },
      ...groupColumnTree(columns, COLUMN_GROUPS),
    ],
    [columns]
  );

  const colorTreeData = useMemo(
    () => groupColumnTree(colorCols, NUMERIC_GROUPS),
    [colorCols]
  );

  const dirLabel = directionLabel(sort);

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
            title={dirLabel}
            aria-label={dirLabel}
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
            {visibleSelected === selected.size
              ? selected.size + ' selected'
              : visibleSelected + ' of ' + selected.size + ' selected'}
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
              rows.map((record) => {
                const rowId = rowIds.get(record);
                return (
                  <HParamsRow
                    key={rowId}
                    record={record}
                    rowId={rowId}
                    columns={columns}
                    colorBy={colorBy}
                    extent={extent}
                    isSelected={selected.has(rowId)}
                    onToggle={toggle}
                    groupStartIds={groupStartIds}
                  />
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default HParamsTable;
