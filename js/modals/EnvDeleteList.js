/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import './EnvDeleteList.css';

import React, { useEffect, useRef, useState } from 'react';

const PROTECTED_ENV = 'main';

function EnvDeleteList(props) {
  const {
    activeEnv,
    disabled = false,
    envList,
    onChange,
    children,
    selectedEnvs,
  } = props;

  const [filter, setFilter] = useState('');
  const filterRef = useRef(null);
  const panelRef = useRef(null);

  const normalizedFilter = filter.trim().toLowerCase();
  const filteredEnvs = envList.filter((env) =>
    env.toLowerCase().includes(normalizedFilter)
  );
  const selectableEnvs = filteredEnvs.filter((env) => env !== PROTECTED_ENV);
  const selectedSet = new Set(selectedEnvs);
  const isAllSelected =
    selectableEnvs.length > 0 &&
    selectableEnvs.every((env) => selectedSet.has(env));
  const selectedOutsideFilter = selectedEnvs.filter(
    (env) => !filteredEnvs.includes(env)
  );

  const toggleEnv = (env, checked) => {
    if (checked) {
      onChange(Array.from(new Set([...selectedEnvs, env])));
    } else {
      onChange(selectedEnvs.filter((candidate) => candidate !== env));
    }
  };

  const toggleAll = (checked) => {
    if (checked) {
      onChange(Array.from(new Set([...selectedEnvs, ...selectableEnvs])));
    } else {
      const dropped = new Set(selectableEnvs);
      onChange(selectedEnvs.filter((env) => !dropped.has(env)));
    }
  };

  useEffect(() => {
    const panel = panelRef.current;
    const onKeyDown = (ev) => {
      if (ev.key !== 'ArrowDown' && ev.key !== 'ArrowUp') return;
      ev.preventDefault();
      const boxes = Array.from(
        panel.querySelectorAll('input[type="checkbox"]:not(:disabled)')
      );
      if (boxes.length === 0) return;
      const step = ev.key === 'ArrowDown' ? 1 : -1;
      let next;
      if (ev.target === filterRef.current) {
        next = step > 0 ? 0 : boxes.length - 1;
      } else {
        next = boxes.indexOf(document.activeElement) + step;
        if (next < 0) next = boxes.length - 1;
        if (next >= boxes.length) next = 0;
      }
      boxes[next].focus();
    };
    panel.addEventListener('keydown', onKeyDown);
    return () => panel.removeEventListener('keydown', onKeyDown);
  }, []);

  return (
    <div className="env-delete-list" id="env-select-panel" ref={panelRef}>
      <div className="env-select-search">
        <input
          aria-label="Filter environments"
          className="form-control"
          onChange={(ev) => setFilter(ev.target.value)}
          placeholder="Filter environments..."
          ref={filterRef}
          type="search"
          value={filter}
        />
      </div>

      {selectableEnvs.length > 0 && (
        <label className="env-select-option env-select-all">
          <input
            aria-label="Select All"
            checked={isAllSelected}
            disabled={disabled}
            onChange={(ev) => toggleAll(ev.target.checked)}
            type="checkbox"
          />
          <span className="env-select-option-label">Select All</span>
          <span className="env-select-badge">{selectableEnvs.length}</span>
        </label>
      )}

      <div className="env-select-list">
        {filteredEnvs.length === 0 ? (
          <div className="env-select-empty">
            No environment matches that filter.
          </div>
        ) : (
          filteredEnvs.map((env) => {
            const isProtected = env === PROTECTED_ENV;
            return (
              <label
                className={
                  isProtected
                    ? 'env-select-option env-select-protected'
                    : 'env-select-option'
                }
                key={env}
              >
                <input
                  checked={selectedSet.has(env)}
                  disabled={disabled || isProtected}
                  onChange={(ev) => toggleEnv(env, ev.target.checked)}
                  type="checkbox"
                  value={env}
                />
                <span className="env-select-option-label">{env}</span>
                {isProtected && (
                  <span className="env-select-badge">protected</span>
                )}
                {!isProtected && env === activeEnv && (
                  <span className="env-select-badge">active</span>
                )}
              </label>
            );
          })
        )}
      </div>

      <div className="env-select-footer">
        <span role="status">
          {selectedEnvs.length === 0
            ? 'Nothing selected'
            : `${selectedEnvs.length} selected for permanent deletion`}
          {selectedOutsideFilter.length > 0 &&
            ` (${selectedOutsideFilter.length} hidden by the filter)`}
        </span>
        <button
          className="env-select-clear"
          disabled={disabled || selectedEnvs.length === 0}
          onClick={() => onChange([])}
          type="button"
        >
          Clear selection
        </button>
        {children}
      </div>
    </div>
  );
}

export default EnvDeleteList;
