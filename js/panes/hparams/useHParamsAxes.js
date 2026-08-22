/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import { useMemo } from 'react';

import {
  buildColumns,
  defaultDimIds,
  groupColumnTree,
  isNumeric,
  NUMERIC_GROUPS,
  selectNumericColumns,
} from './hparamsUtils';

/*
 * Resolves which axes a plot should draw, shared by the scatter matrix and
 * parallel coordinates because both answer the question identically.
 *
 * `columnRecords` is the unfiltered set: which columns can be plotted at all is
 * decided from it, so a filter that empties a column cannot make it vanish from
 * the picker and silently reset a selection. `records` is what actually gets
 * drawn, and only informs which columns are dense.
 *
 * `preferDense` suits parallel coordinates, where a column with gaps costs the
 * plot whole lines and is a poor opening axis; a scatter matrix just leaves a
 * marker out, so it does not care.
 */
export default function useHParamsAxes({
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

  const columns = useMemo(
    () => buildColumns(paramKeys, metricKeys, tagKeys),
    [paramKeys, metricKeys, tagKeys]
  );

  const numericCols = useMemo(
    () => selectNumericColumns(pickerRecords, columns),
    [pickerRecords, columns]
  );

  const dims = useMemo(() => {
    const valid = new Set(numericCols.map((col) => col.id));
    const chosen = (selectedDims || []).filter((id) => valid.has(id));
    if (chosen.length > 0) return chosen.slice(0, maxDims);
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
