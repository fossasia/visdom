/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { useEffect, useRef, useState } from 'react';

const PROTECTED_ENV = 'main';
const VISIBLE_CHIP_COUNT = 3;

function EnvSelectDropdown(props) {
  const {
    activeEnv,
    disabled = false,
    envList,
    onChange,
    resetToken,
    selectedEnvs,
  } = props;

  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState('');
  const wrapperRef = useRef(null);
  const triggerRef = useRef(null);
  const filterRef = useRef(null);
  const listRef = useRef(null);
  const panelRef = useRef(null);

  useEffect(() => {
    setOpen(false);
    setFilter('');
  }, [resetToken]);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (ev) => {
      if (wrapperRef.current && !wrapperRef.current.contains(ev.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onPointerDown);
    return () => document.removeEventListener('mousedown', onPointerDown);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    if (filterRef.current) filterRef.current.focus({ preventScroll: true });
    if (panelRef.current) panelRef.current.scrollIntoView({ block: 'nearest' });
  }, [open]);

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
    if (!open || !panel) return undefined;
    const onKeyDown = (ev) => {
      if (ev.key === 'Escape') {
        ev.preventDefault();
        ev.stopPropagation();
        setOpen(false);
        if (triggerRef.current) triggerRef.current.focus();
        return;
      }
      if (ev.key !== 'ArrowDown' && ev.key !== 'ArrowUp') return;
      if (!listRef.current) return;
      ev.preventDefault();
      const boxes = Array.from(
        listRef.current.querySelectorAll(
          'input[type="checkbox"]:not(:disabled)'
        )
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
  }, [open]);

  const chips = selectedEnvs.slice(0, VISIBLE_CHIP_COUNT);
  const overflowCount = selectedEnvs.length - chips.length;

  return (
    <div className="env-select" ref={wrapperRef}>
      <button
        aria-controls="env-select-panel"
        aria-expanded={open}
        aria-haspopup="true"
        aria-label="Select environments to delete"
        className="btn btn-default dropdown-toggle env-select-trigger"
        disabled={disabled}
        onClick={() => setOpen((prev) => !prev)}
        ref={triggerRef}
        type="button"
      >
        <span className="env-select-value">
          {selectedEnvs.length === 0 ? (
            <span className="env-select-placeholder">
              Select environments to delete
            </span>
          ) : (
            <>
              {chips.map((env) => (
                <span className="env-select-chip" key={env}>
                  {env}
                </span>
              ))}
              {overflowCount > 0 && <span>+{overflowCount}</span>}
            </>
          )}
        </span>
        <span className="caret" />
      </button>

      {open && (
        <div
          className="dropdown-menu show env-select-menu"
          id="env-select-panel"
          ref={panelRef}
        >
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
                onChange={(ev) => toggleAll(ev.target.checked)}
                type="checkbox"
              />
              <span className="env-select-option-label">Select All</span>
              <span className="env-select-badge">{selectableEnvs.length}</span>
            </label>
          )}

          <div className="env-select-list" ref={listRef}>
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
                      disabled={isProtected}
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
            <span>
              {selectedEnvs.length === 0
                ? 'Nothing selected'
                : `${selectedEnvs.length} selected`}
              {selectedOutsideFilter.length > 0 &&
                ` (${selectedOutsideFilter.length} hidden by the filter)`}
            </span>
            <button
              className="env-select-clear"
              disabled={selectedEnvs.length === 0}
              onClick={() => onChange([])}
              type="button"
            >
              Clear selection
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default EnvSelectDropdown;
