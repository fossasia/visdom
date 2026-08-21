/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { useCallback, useMemo } from 'react';

import { ColumnSelect } from './ColumnSelect';
import {
  cellClass,
  COLUMN_GROUPS,
  formatValue,
  groupColumnTree,
  makeComparator,
  NUMERIC_GROUPS,
  numericExtent,
  runLabel,
  selectNumericColumns,
  spineStyle,
} from './hparamsUtils';
import StatusBadge from './StatusBadge';
import useHParamsColumns from './useHParamsColumns';

const RUN_COLUMN_ID = 'run:name';

const NO_SORT = { by: null, dir: null };

function sortGlyph(dir) {
  if (dir === 'asc') return '▲';
  if (dir === 'desc') return '▼';
  return '⇅';
}

function nextSort(current, columnId) {
  if (current.by !== columnId) return { by: columnId, dir: 'asc' };
  if (current.dir === 'asc') return { by: columnId, dir: 'desc' };
  return { by: null, dir: null };
}

function ariaSort(sort, columnId) {
  if (sort.by !== columnId) return 'none';
  return sort.dir === 'asc' ? 'ascending' : 'descending';
}

function directionLabel(sort) {
  if (!sort.by) return 'Sort direction';
  if (sort.dir === 'asc') return 'Sorted ascending — click for descending';
  return 'Sorted descending — click to clear';
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
  return (
    <span
      className={
        'hparams-caret ' +
        (active ? 'hparams-caret-active' : 'hparams-caret-idle')
      }
      aria-hidden="true"
    >
      {sortGlyph(active ? sort.dir : null)}
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
          <StatusBadge status={record.status} />
        </div>
      </th>
      {columns.map((col) => {
        const value = col.accessor(record);
        const style =
          colorBy && col.id === colorBy ? spineStyle(value, extent) : null;
        const cls = cellClass(value, {
          spine: !!style,
          separator: groupStartIds.has(col.id),
        });
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
  rowIds,
  paramKeys,
  metricKeys,
  tagKeys,
  sort,
  setSort,
  colorBy,
  setColorBy,
  selected,
  setSelected,
}) => {
  const columns = useHParamsColumns(paramKeys, metricKeys, tagKeys);
  const colorCols = useMemo(
    () => selectNumericColumns(records, columns),
    [records, columns]
  );

  const groupStartIds = useMemo(() => {
    const ids = new Set();
    let prev = null;
    columns.forEach((c) => {
      if (c.group !== prev) ids.add(c.id);
      prev = c.group;
    });
    return ids;
  }, [columns]);

  const activeSort = useMemo(() => {
    if (!sort.by || sort.by === RUN_COLUMN_ID) return sort;
    return columns.some((c) => c.id === sort.by) ? sort : NO_SORT;
  }, [sort, columns]);

  const activeColorBy = useMemo(
    () => (colorBy && colorCols.some((c) => c.id === colorBy) ? colorBy : null),
    [colorBy, colorCols]
  );

  const rows = useMemo(() => {
    if (!activeSort.by) return records;
    const accessor = accessorFor(activeSort.by, columns);
    if (!accessor) return records;
    return records.slice().sort(makeComparator(accessor, activeSort.dir));
  }, [records, activeSort, columns]);

  const extent = useMemo(() => {
    if (!activeColorBy) return null;
    const col = columns.find((c) => c.id === activeColorBy);
    if (!col) return null;
    return numericExtent(records, col.accessor);
  }, [records, activeColorBy, columns]);

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

  const bands = COLUMN_GROUPS.map((b) => ({
    ...b,
    span: columns.filter((c) => c.group === b.key).length,
  })).filter((b) => b.span > 0);

  const sortTreeData = [
    { key: RUN_COLUMN_ID, value: RUN_COLUMN_ID, title: 'run' },
    ...groupColumnTree(columns, COLUMN_GROUPS),
  ];

  const colorTreeData = groupColumnTree(colorCols, NUMERIC_GROUPS);

  const dirLabel = directionLabel(activeSort);

  return (
    <div className="hparams-table-wrap">
      <div className="hparams-toolbar">
        <span className="hparams-sortby">
          sort by:
          <ColumnSelect
            value={activeSort.by}
            placeholder="none"
            treeData={sortTreeData}
            onChange={handleSortSelect}
            label="Sort runs by"
          />
          <button
            type="button"
            className="hparams-dir-btn"
            onClick={cycleDir}
            disabled={!activeSort.by}
            title={dirLabel}
            aria-label={dirLabel}
          >
            {sortGlyph(activeSort.by ? activeSort.dir : null)}
          </button>
        </span>
        {colorCols.length ? (
          <span className="hparams-colorby">
            color by:
            <ColumnSelect
              value={activeColorBy}
              placeholder="none"
              treeData={colorTreeData}
              onChange={setColorBy}
              label="Color the table by"
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
          <caption className="hparams-sr-only">
            {rows.length} runs with their hyper-parameters, latest metric
            values, and tags. Use the column headers to sort.
          </caption>
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
                sort={activeSort}
                columnId={RUN_COLUMN_ID}
                label="run"
                scopeClass="hparams-th-run"
                onSort={handleSort}
              />
              {columns.map((col) => (
                <SortHeader
                  key={col.id}
                  sort={activeSort}
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
                  No runs to show.
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
                    colorBy={activeColorBy}
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
