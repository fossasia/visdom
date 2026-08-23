/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import HParamsCompare from './hparams/HParamsCompare';
import { downloadJson, exportCsv, exportJson } from './hparams/hparamsExport';
import HParamsFilters from './hparams/HParamsFilters';
import HParamsMessage from './hparams/HParamsMessage';
import HParamsMetrics from './hparams/HParamsMetrics';
import HParamsParallelCoords from './hparams/HParamsParallelCoords';
import HParamsSplom from './hparams/HParamsSplom';
import HParamsTable from './hparams/HParamsTable';
import {
  applyFilters,
  buildFilterSpecs,
  buildRowIds,
  collectStatuses,
  countActiveFilters,
  filterRecords,
} from './hparams/hparamsUtils';
import useHParamsColumns from './hparams/useHParamsColumns';
import Pane from './Pane';

const VIEWS = [
  { key: 'table', label: 'Table' },
  { key: 'parcoords', label: 'Parallel coordinates' },
  { key: 'splom', label: 'Scatter matrix' },
  { key: 'compare', label: 'Compare' },
  { key: 'metrics', label: 'Metrics' },
];

const NO_RECORDS = [];

const NO_KEYS = [];

const TAB_KEYS = {
  ArrowRight: 1,
  ArrowLeft: -1,
  ArrowDown: 1,
  ArrowUp: -1,
};

function tabId(contentID, key) {
  return 'hparams-tab-' + contentID + '-' + key;
}

function panelId(contentID) {
  return 'hparams-panel-' + contentID;
}

function readContent(content) {
  if (!content || typeof content !== 'object' || Array.isArray(content)) {
    return null;
  }
  if (!Array.isArray(content.records)) {
    return null;
  }
  const asKeys = (value) => (Array.isArray(value) ? value : []);
  return {
    records: content.records,
    paramKeys: asKeys(content.param_keys),
    metricKeys: asKeys(content.metric_keys),
    tagKeys: asKeys(content.tag_keys),
  };
}

var HParamsPane = (props) => {
  const { content } = props;
  const data = useMemo(() => readContent(content), [content]);
  const [view, setView] = useState('table');
  const [tableSort, setTableSort] = useState({ by: null, dir: null });
  const [tableFilter, setTableFilter] = useState('');
  const [tableColorBy, setTableColorBy] = useState(null);
  const [tableSelected, setTableSelected] = useState(() => new Set());
  const [splomDims, setSplomDims] = useState(null);
  const [splomColorBy, setSplomColorBy] = useState(null);
  const [parcoordsDims, setParcoordsDims] = useState(null);
  const [parcoordsColorBy, setParcoordsColorBy] = useState(null);
  const [metricsKey, setMetricsKey] = useState(null);
  const metricsCache = useRef(null);
  if (metricsCache.current === null) metricsCache.current = new Map();
  const [filtersOpen, setFiltersOpen] = useState(true);
  const [filters, setFilters] = useState({ statuses: [], columns: {} });

  const records = data ? data.records : NO_RECORDS;
  const paramKeys = data ? data.paramKeys : NO_KEYS;
  const metricKeys = data ? data.metricKeys : NO_KEYS;
  const tagKeys = data ? data.tagKeys : NO_KEYS;
  const columns = useHParamsColumns(paramKeys, metricKeys, tagKeys);
  const specs = useMemo(
    () => buildFilterSpecs(records, columns),
    [records, columns]
  );
  const statuses = useMemo(() => collectStatuses(records), [records]);
  const visibleRecords = useMemo(
    () =>
      applyFilters(
        filterRecords(records, tableFilter, columns),
        specs,
        filters
      ),
    [records, tableFilter, columns, specs, filters]
  );
  const activeFilters =
    countActiveFilters(filters, specs) + (tableFilter.trim() ? 1 : 0);

  const rowIds = useMemo(() => buildRowIds(records), [records]);

  useEffect(() => {
    setTableSelected((prev) => {
      if (prev.size === 0) return prev;
      const live = new Set(rowIds.values());
      const next = new Set();
      prev.forEach((id) => {
        if (live.has(id)) next.add(id);
      });
      return next.size === prev.size ? prev : next;
    });
  }, [rowIds]);

  const selectionActive = tableSelected.size > 0;
  const selectedVisible = useMemo(
    () =>
      selectionActive
        ? visibleRecords.filter((r) => tableSelected.has(rowIds.get(r)))
        : visibleRecords,
    [selectionActive, visibleRecords, tableSelected, rowIds]
  );
  const clearSelection = useCallback(() => setTableSelected(new Set()), []);
  const filtersToggleRef = useRef(null);
  const tablistRef = useRef(null);
  const closeFilters = useCallback(() => {
    setFiltersOpen(false);
    if (filtersToggleRef.current) filtersToggleRef.current.focus();
  }, []);

  const handleTabKeyDown = useCallback(
    (e) => {
      let next = null;
      if (e.key === 'Home') next = 0;
      else if (e.key === 'End') next = VIEWS.length - 1;
      else if (TAB_KEYS[e.key]) {
        const at = VIEWS.findIndex((v) => v.key === view);
        next = (at + TAB_KEYS[e.key] + VIEWS.length) % VIEWS.length;
      }
      if (next === null) return;
      e.preventDefault();
      setView(VIEWS[next].key);
      const buttons = tablistRef.current
        ? tablistRef.current.querySelectorAll('.hparams-viewtab')
        : null;
      if (buttons && buttons[next]) buttons[next].focus();
    },
    [view]
  );

  const selectedRecords = selectionActive ? selectedVisible : NO_RECORDS;

  const exportRecords = selectionActive ? selectedVisible : visibleRecords;
  const exportScope = selectionActive ? 'selected' : 'shown';
  const handleExportCsv = useCallback(() => {
    exportCsv(exportRecords, columns, 'visdom_hparams.csv');
  }, [exportRecords, columns]);
  const handleExportJson = useCallback(() => {
    exportJson(
      exportRecords,
      { paramKeys, metricKeys, tagKeys },
      'visdom_hparams.json'
    );
  }, [exportRecords, paramKeys, metricKeys, tagKeys]);

  const handleDownload = useCallback(() => {
    downloadJson(content, 'visdom_hparams.json');
  }, [content]);

  const renderView = () => {
    if (visibleRecords.length === 0) {
      return <HParamsMessage>No runs match your filters.</HParamsMessage>;
    }
    const isPlot = view === 'splom' || view === 'parcoords';
    const plotRecords =
      isPlot && selectionActive ? selectedVisible : visibleRecords;
    const viewProps = {
      columnRecords: records,
      rowIds,
      paramKeys,
      metricKeys,
      tagKeys,
    };

    if (view === 'compare') {
      return <HParamsCompare {...viewProps} records={selectedRecords} />;
    }

    if (view === 'metrics') {
      return (
        <HParamsMetrics
          {...viewProps}
          records={selectedRecords}
          metric={metricsKey}
          onMetric={setMetricsKey}
          cacheRef={metricsCache}
        />
      );
    }

    let viewEl;
    if (view === 'splom') {
      viewEl = (
        <HParamsSplom
          {...viewProps}
          records={plotRecords}
          selectedDims={splomDims}
          onSelectedDims={setSplomDims}
          colorBy={splomColorBy}
          onColorBy={setSplomColorBy}
        />
      );
    } else if (view === 'parcoords') {
      viewEl = (
        <HParamsParallelCoords
          {...viewProps}
          records={plotRecords}
          selectedDims={parcoordsDims}
          onSelectedDims={setParcoordsDims}
          colorBy={parcoordsColorBy}
          onColorBy={setParcoordsColorBy}
        />
      );
    } else {
      viewEl = (
        <HParamsTable
          {...viewProps}
          records={visibleRecords}
          sort={tableSort}
          setSort={setTableSort}
          colorBy={tableColorBy}
          setColorBy={setTableColorBy}
          selected={tableSelected}
          setSelected={setTableSelected}
        />
      );
    }

    if (!isPlot || !selectionActive) return viewEl;
    return (
      <div className="hparams-plot-area">
        <div className="hparams-selection-banner">
          <span>
            Plotting <b>{plotRecords.length}</b> selected{' '}
            {plotRecords.length === 1 ? 'run' : 'runs'}
          </span>
          <button
            type="button"
            className="hparams-link-btn"
            onClick={clearSelection}
          >
            Show all
          </button>
        </div>
        {plotRecords.length === 0 ? (
          <HParamsMessage>
            Every selected run is hidden by the current filters.
          </HParamsMessage>
        ) : (
          viewEl
        )}
      </div>
    );
  };

  let body;
  if (data === null) {
    body = (
      <HParamsMessage tone="error">
        Could not read hyper-parameter data for this window.
      </HParamsMessage>
    );
  } else if (data.records.length === 0) {
    body = (
      <HParamsMessage>No experiments match this selection.</HParamsMessage>
    );
  } else {
    body = (
      <div className="hparams-body">
        <div className="hparams-summary">
          <span className="hparams-stat">
            <b>{data.records.length}</b> runs
          </span>
          <span className="hparams-stat">
            <b>{data.paramKeys.length}</b> params
          </span>
          <span className="hparams-stat">
            <b>{data.metricKeys.length}</b> metrics
          </span>
          <span className="hparams-stat">
            <b>{data.tagKeys.length}</b> tags
          </span>
          {visibleRecords.length !== records.length ? (
            <span className="hparams-stat hparams-stat-filtered">
              showing <b>{visibleRecords.length}</b> of {records.length}
            </span>
          ) : null}
          {selectionActive ? (
            <span className="hparams-stat hparams-stat-selected">
              <b>{tableSelected.size}</b> selected for plots
              <button
                type="button"
                className="hparams-chip-clear"
                onClick={clearSelection}
                aria-label="Clear selection"
                title="Clear selection"
              >
                ×
              </button>
            </span>
          ) : null}
        </div>
        <div className="hparams-views">
          <div
            className="hparams-viewtabs"
            role="tablist"
            aria-label="Hyper-parameter views"
            ref={tablistRef}
          >
            {VIEWS.map((v) => (
              <button
                key={v.key}
                type="button"
                role="tab"
                id={tabId(props.contentID, v.key)}
                aria-selected={view === v.key}
                aria-controls={panelId(props.contentID)}
                tabIndex={view === v.key ? 0 : -1}
                className={
                  'hparams-viewtab' +
                  (view === v.key ? ' hparams-viewtab-active' : '')
                }
                onClick={() => setView(v.key)}
                onKeyDown={handleTabKeyDown}
              >
                {v.label}
              </button>
            ))}
            <span className="hparams-viewtools">
              <input
                type="text"
                className="hparams-filter"
                placeholder="Search runs…"
                value={tableFilter}
                onChange={(e) => setTableFilter(e.target.value)}
                aria-label="Search runs"
              />
              <button
                type="button"
                ref={filtersToggleRef}
                className={
                  'hparams-filters-toggle' +
                  (filtersOpen ? ' hparams-filters-toggle-active' : '')
                }
                onClick={() => setFiltersOpen((open) => !open)}
                aria-expanded={filtersOpen}
                title="Filter runs across every view"
              >
                Filters{activeFilters ? ' (' + activeFilters + ')' : ''}
              </button>
              <span className="hparams-export">
                <span className="hparams-export-label">export</span>
                <button
                  type="button"
                  className="hparams-export-btn"
                  onClick={handleExportCsv}
                  disabled={exportRecords.length === 0}
                  title={'Download the ' + exportScope + ' runs as a CSV table'}
                >
                  CSV
                </button>
                <button
                  type="button"
                  className="hparams-export-btn"
                  onClick={handleExportJson}
                  disabled={exportRecords.length === 0}
                  title={'Download the ' + exportScope + ' runs as JSON'}
                >
                  JSON
                </button>
              </span>
            </span>
          </div>
          <p className="hparams-sr-only" role="status" aria-live="polite">
            {visibleRecords.length} of {records.length} runs shown
            {selectionActive ? ', ' + tableSelected.size + ' selected' : ''}
          </p>
          <div
            className="hparams-layout"
            role="tabpanel"
            id={panelId(props.contentID)}
            aria-labelledby={tabId(props.contentID, view)}
          >
            {filtersOpen ? (
              <HParamsFilters
                specs={specs}
                statuses={statuses}
                filters={filters}
                setFilters={setFilters}
                setSearch={setTableFilter}
                onClose={closeFilters}
                visibleCount={visibleRecords.length}
                totalCount={records.length}
              />
            ) : null}
            {renderView()}
          </div>
        </div>
      </div>
    );
  }

  return (
    <Pane {...props} handleDownload={handleDownload}>
      <div className="content-hparams">{body}</div>
    </Pane>
  );
};

HParamsPane = React.memo(HParamsPane, (props, nextProps) => {
  if (props.contentID !== nextProps.contentID) return false;
  else if (props.h !== nextProps.h || props.w !== nextProps.w) return false;
  else if (props.isFocused !== nextProps.isFocused) return false;
  return true;
});

export default HParamsPane;
