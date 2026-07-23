/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import Slider from 'rc-slider';
import React, { useCallback, useEffect, useState } from 'react';

import { COLUMN_GROUPS, formatValue } from './hparamsUtils';

/*
 * A range control that tracks the drag locally and lifts the value only once
 * the handle is released. Every commit re-filters the records feeding the
 * Plotly views, so committing per drag frame would rebuild those plots
 * continuously.
 */
const RangeFilter = ({ spec, entry, onChange }) => {
  const bounds = [entry ? entry.lo : spec.min, entry ? entry.hi : spec.max];
  const [dragging, setDragging] = useState(null);
  const value = dragging || bounds;

  useEffect(() => {
    setDragging(null);
  }, [entry, spec.min, spec.max]);

  const commit = (next) => {
    setDragging(null);
    onChange(spec.id, {
      lo: next[0],
      hi: next[1],
      includeMissing: entry ? entry.includeMissing !== false : true,
    });
  };

  return (
    <div className="hparams-filter-range">
      <div className="hparams-filter-bounds">
        <span>{formatValue(value[0])}</span>
        <span>{formatValue(value[1])}</span>
      </div>
      <Slider
        range
        min={spec.min}
        max={spec.max}
        step={spec.step}
        value={value}
        allowCross={false}
        onChange={(next) => setDragging(next)}
        onChangeComplete={commit}
        ariaLabelForHandle={[spec.label + ' minimum', spec.label + ' maximum']}
      />
    </div>
  );
};

const CategoryFilter = ({ spec, entry, onChange }) => {
  const selected = (entry && entry.values) || [];
  const toggle = (value) => {
    const next = selected.slice();
    const at = next.indexOf(value);
    if (at === -1) next.push(value);
    else next.splice(at, 1);
    onChange(spec.id, {
      values: next,
      includeMissing: entry ? entry.includeMissing !== false : true,
    });
  };

  return (
    <div className="hparams-filter-categories">
      {spec.values.map((value, index) => (
        <label className="hparams-filter-check" key={index}>
          <input
            type="checkbox"
            checked={selected.indexOf(value) !== -1}
            onChange={() => toggle(value)}
          />
          <span>{formatValue(value)}</span>
        </label>
      ))}
    </div>
  );
};

const FilterSection = ({ spec, entry, onChange }) => {
  const toggleMissing = () => {
    const base =
      entry ||
      (spec.kind === 'range' ? { lo: spec.min, hi: spec.max } : { values: [] });
    onChange(spec.id, {
      ...base,
      includeMissing: entry ? entry.includeMissing === false : false,
    });
  };

  return (
    <div className="hparams-filter-row">
      <div className="hparams-filter-label" title={spec.label}>
        {spec.label}
      </div>
      {spec.kind === 'range' ? (
        <RangeFilter spec={spec} entry={entry} onChange={onChange} />
      ) : (
        <CategoryFilter spec={spec} entry={entry} onChange={onChange} />
      )}
      <label
        className="hparams-filter-check hparams-filter-missing"
        title={
          spec.missing === 0
            ? 'Every run has a value for ' + spec.label
            : spec.missing + ' run(s) have no value for ' + spec.label
        }
      >
        <input
          type="checkbox"
          checked={!entry || entry.includeMissing !== false}
          onChange={toggleMissing}
        />
        <span>include missing ({spec.missing})</span>
      </label>
    </div>
  );
};

const HParamsFilters = ({
  specs,
  statuses,
  filters,
  setFilters,
  setSearch,
  onClose,
  visibleCount,
  totalCount,
}) => {
  const setColumn = useCallback(
    (id, entry) => {
      setFilters((prev) => ({
        ...prev,
        columns: { ...prev.columns, [id]: entry },
      }));
    },
    [setFilters]
  );

  const toggleStatus = useCallback(
    (status) => {
      setFilters((prev) => {
        const next = (prev.statuses || []).slice();
        const at = next.indexOf(status);
        if (at === -1) next.push(status);
        else next.splice(at, 1);
        return { ...prev, statuses: next };
      });
    },
    [setFilters]
  );

  const clearAll = useCallback(() => {
    setFilters({ statuses: [], columns: {} });
    setSearch('');
  }, [setFilters, setSearch]);

  const groups = COLUMN_GROUPS.map((group) => ({
    ...group,
    specs: specs.filter((spec) => spec.group === group.key),
  })).filter((group) => group.specs.length > 0);

  return (
    <div className="hparams-filters">
      <div className="hparams-filters-head">
        <span className="hparams-filters-title">Filters</span>
        <button
          type="button"
          className="hparams-filters-close"
          onClick={onClose}
          aria-label="Close filters"
          title="Close filters"
        >
          ✕
        </button>
      </div>

      <div className="hparams-filters-body">
        {statuses.length > 0 ? (
          <div className="hparams-filter-group">
            <div className="hparams-filter-eyebrow">status</div>
            <div className="hparams-filter-categories">
              {statuses.map((status) => (
                <label className="hparams-filter-check" key={status}>
                  <input
                    type="checkbox"
                    checked={(filters.statuses || []).indexOf(status) !== -1}
                    onChange={() => toggleStatus(status)}
                  />
                  <span>{status}</span>
                </label>
              ))}
            </div>
          </div>
        ) : null}

        {groups.map((group) => (
          <div className="hparams-filter-group" key={group.key}>
            <div className="hparams-filter-eyebrow">{group.label}</div>
            {group.specs.map((spec) => (
              <FilterSection
                key={spec.id}
                spec={spec}
                entry={filters.columns[spec.id]}
                onChange={setColumn}
              />
            ))}
          </div>
        ))}

        {groups.length === 0 ? (
          <div className="hparams-filter-none">
            No params or metrics can be filtered on.
          </div>
        ) : null}
      </div>

      <div className="hparams-filters-foot">
        <span className="hparams-filters-count">
          showing <b>{visibleCount}</b> of {totalCount} runs
        </span>
        <button
          type="button"
          className="hparams-dir-btn"
          onClick={clearAll}
          title="Clear every filter"
        >
          clear all
        </button>
      </div>
    </div>
  );
};

export default HParamsFilters;
