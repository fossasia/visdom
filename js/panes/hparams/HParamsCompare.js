/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { useMemo, useState } from 'react';

import HParamsMessage from './HParamsMessage';
import {
  buildComparison,
  cellClass,
  formatValue,
  numericExtent,
  runLabel,
  spineStyle,
} from './hparamsUtils';
import StatusBadge from './StatusBadge';
import useHParamsColumns from './useHParamsColumns';

const HParamsCompare = ({ records, paramKeys, metricKeys, tagKeys }) => {
  const [showIdentical, setShowIdentical] = useState(true);

  const columns = useHParamsColumns(paramKeys, metricKeys, tagKeys);
  const comparison = useMemo(
    () => buildComparison(records, columns),
    [records, columns]
  );

  if (records.length < 2) {
    return (
      <HParamsMessage wrapClass="hparams-compare-wrap">
        Pick two or more runs in the table to compare them.
      </HParamsMessage>
    );
  }

  const inputs = comparison.param.concat(comparison.tag);
  const differing = inputs.filter((field) => !field.shared);
  const identical = inputs.filter((field) => field.shared);
  const metrics = comparison.metric;
  const span = records.length + 1;

  const fieldRow = (field, spine) => {
    const extent = spine ? numericExtent(records, field.accessor) : null;
    return (
      <tr key={field.id} className="hparams-compare-row">
        <th scope="row" className="hparams-compare-field" title={field.label}>
          {field.label}
        </th>
        {field.cells.map((value, i) => {
          const style = extent ? spineStyle(value, extent) : null;
          const cls = cellClass(value, { spine: !!style });
          return (
            <td key={i} className={cls} style={style || undefined}>
              {formatValue(value)}
            </td>
          );
        })}
      </tr>
    );
  };

  const sectionRow = (key, label) => (
    <tr key={key} className="hparams-compare-section">
      <th
        className="hparams-compare-section-label"
        colSpan={span}
        scope="colgroup"
      >
        {label}
      </th>
    </tr>
  );

  const rows = [];
  rows.push(sectionRow('s-differs', 'what differs'));
  if (differing.length === 0) {
    rows.push(
      <tr key="differs-none">
        <td className="hparams-compare-note" colSpan={span}>
          These runs share every parameter and tag.
        </td>
      </tr>
    );
  } else {
    differing.forEach((field) => rows.push(fieldRow(field, false)));
  }

  if (metrics.length) {
    rows.push(sectionRow('s-metrics', 'metrics'));
    metrics.forEach((field) => rows.push(fieldRow(field, true)));
  }

  if (identical.length) {
    rows.push(
      <tr key="s-identical" className="hparams-compare-section">
        <th colSpan={span} scope="colgroup">
          <button
            type="button"
            className="hparams-compare-toggle"
            onClick={() => setShowIdentical((open) => !open)}
            aria-expanded={showIdentical}
          >
            identical ({identical.length}){' '}
            <span aria-hidden="true">{showIdentical ? '▾' : '▸'}</span>
          </button>
        </th>
      </tr>
    );
    if (showIdentical) {
      identical.forEach((field) => rows.push(fieldRow(field, false)));
    }
  }

  return (
    <div className="hparams-compare-wrap">
      <div className="hparams-compare-lead">
        Comparing <b>{records.length}</b> runs — {differing.length} differ,{' '}
        {identical.length} identical
      </div>
      <div className="hparams-compare-scroll">
        <table className="hparams-compare-table">
          <thead>
            <tr className="hparams-compare-head">
              <th
                className="hparams-compare-corner"
                scope="col"
                aria-hidden="true"
              />
              {records.map((record) => {
                const label = runLabel(record);
                return (
                  <th
                    key={record.env_id}
                    scope="col"
                    className="hparams-compare-run"
                    title={label}
                  >
                    <span className="hparams-compare-run-name">{label}</span>
                    <StatusBadge status={record.status} />
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </div>
  );
};

export default HParamsCompare;
