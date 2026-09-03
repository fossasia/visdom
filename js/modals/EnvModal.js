/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { useContext, useEffect, useState } from 'react';
import ReactModal from 'react-modal';

import ApiContext from '../api/ApiContext';
import { MODAL_STYLE } from '../settings';
import { showToast } from '../toasts/toastEvents';

const MAX_TAG_NAME_LENGTH = 50;
const MAX_TAGS_PER_ENV = 20;
const ENV_MODAL_STYLE = {
  ...MODAL_STYLE,
  content: {
    ...MODAL_STYLE.content,
    maxHeight: 'calc(100vh - 40px)',
    overflowY: 'auto',
    width: 'min(760px, calc(100vw - 40px))',
  },
};

let nextTagRowID = 0;
const createTagRow = (name = '', value = '') => ({
  id: `environment-tag-${nextTagRowID++}`,
  name: name,
  value: value,
});

const rowsFromTags = (tags) =>
  Object.entries(tags || {}).map(([name, value]) => createTagRow(name, value));

function EnvModal(props) {
  const { connected, sessionInfo } = useContext(ApiContext);
  const {
    activeEnv,
    envList,
    onModalClose,
    onEnvSave,
    onEnvDelete,
    onTagsSave,
    tags = {},
    show,
  } = props;
  const canWrite = connected && !sessionInfo.readonly;

  // effects
  // -------

  // change input / select value when activeEnv changes
  const [inputText, setInputText] = useState(activeEnv);
  const [tagEnv, setTagEnv] = useState(activeEnv);
  const [tagRows, setTagRows] = useState([]);
  const [tagSaveStatus, setTagSaveStatus] = useState('idle');
  const [tagSaveError, setTagSaveError] = useState('');
  const [envFilter, setEnvFilter] = useState('');
  const [selectedEnvs, setSelectedEnvs] = useState([]);
  useEffect(() => {
    setInputText(activeEnv);
    setTagEnv(activeEnv || envList[0] || '');
    setTagSaveStatus('idle');
    setTagSaveError('');
    setEnvFilter('');
    setSelectedEnvs([]);
  }, [activeEnv, show]);

  useEffect(() => {
    setTagRows(rowsFromTags(tags[tagEnv]));
  }, [tagEnv, tags, show]);

  const updateTagRow = (id, field, value) => {
    setTagSaveStatus('idle');
    setTagSaveError('');
    setTagRows((prev) =>
      prev.map((row) => (row.id === id ? { ...row, [field]: value } : row))
    );
  };

  const removeTagRow = (id) => {
    setTagSaveStatus('idle');
    setTagSaveError('');
    setTagRows((prev) => prev.filter((row) => row.id !== id));
  };

  const normalizedNames = tagRows
    .map((row) => row.name.trim())
    .filter((name) => name.length > 0);
  const duplicateNames = new Set(
    normalizedNames.filter(
      (name, index) => normalizedNames.indexOf(name) !== index
    )
  );
  const hasUnnamedValue = tagRows.some(
    (row) => row.name.trim().length === 0 && row.value.length > 0
  );
  const hasLongName = normalizedNames.some(
    (name) => name.length > MAX_TAG_NAME_LENGTH
  );
  const hasTooManyTags = normalizedNames.length > MAX_TAGS_PER_ENV;
  const hasInvalidTags =
    hasUnnamedValue || hasLongName || hasTooManyTags || duplicateNames.size > 0;

  const handleTagsSave = () => {
    if (hasInvalidTags) return;

    const nextTags = {};
    tagRows.forEach((row) => {
      const name = row.name.trim();
      if (name.length > 0) {
        nextTags[name] = row.value;
      }
    });

    setTagSaveStatus('saving');
    setTagSaveError('');
    onTagsSave(tagEnv, nextTags)
      .done(() => {
        setTagSaveStatus('saved');
      })
      .fail((xhr) => {
        setTagSaveStatus('error');
        setTagSaveError(
          xhr.statusText || 'The server rejected the environment tags.'
        );
      });
  };

  // rendering
  // ---------

  const normalizedEnvFilter = envFilter.trim().toLowerCase();
  const filteredEnvs = envList.filter((env) =>
    env.toLowerCase().includes(normalizedEnvFilter)
  );
  const selectableEnvs = filteredEnvs.filter((env) => env !== 'main');
  const selectedEnvsSet = new Set(selectedEnvs);
  const isAllSelected =
    selectableEnvs.length > 0 &&
    selectableEnvs.every((env) => selectedEnvsSet.has(env));
  return (
    <ReactModal
      isOpen={show}
      onRequestClose={onModalClose}
      contentLabel="Environment Management Modal"
      ariaHideApp={false}
      style={ENV_MODAL_STYLE}
    >
      <span className="visdom-title">Manage Environments</span>
      <br />
      Save or fork current environment:
      <br />
      <div className="form-inline">
        <input
          aria-label="Environment name"
          className="form-control"
          type="text"
          value={inputText}
          onChange={(ev) => {
            setInputText(ev.target.value);
          }}
        />
        <button
          className="btn btn-default"
          disabled={!(canWrite && inputText && inputText.length > 0)}
          onClick={() => onEnvSave(inputText)}
        >
          {envList.indexOf(inputText) >= 0 ? 'save' : 'fork'}
        </button>
      </div>
      <br />
      Select environments to delete:
      <br />
      <input
        aria-label="Filter environments"
        className="form-control"
        type="search"
        placeholder="Filter environments..."
        value={envFilter}
        onChange={(ev) => {
          setEnvFilter(ev.target.value);
          setSelectedEnvs([]);
        }}
        style={{ marginBottom: '10px', width: '100%' }}
      />
      <div className="form-inline">
        <div
          style={{
            border: '1px solid #ccc',
            padding: '10px',
            height: '140px',
            overflowY: 'scroll',
            marginBottom: '10px',
            width: '100%',
            borderRadius: '4px',
            backgroundColor: '#fff',
          }}
        >
          <label
            style={{ display: 'block', fontWeight: 'bold', cursor: 'pointer' }}
          >
            <input
              type="checkbox"
              style={{ marginRight: '8px' }}
              disabled={!canWrite || selectableEnvs.length === 0}
              checked={isAllSelected}
              onChange={(ev) => {
                setSelectedEnvs(ev.target.checked ? selectableEnvs : []);
              }}
            />
            Select All
          </label>
          <hr style={{ margin: '5px 0' }} />

          {filteredEnvs.length === 0 ? (
            <div style={{ color: '#777' }}>No environments match.</div>
          ) : (
            filteredEnvs.map((env) => (
              <label
                key={env}
                style={{
                  display: 'block',
                  fontWeight: 'normal',
                  cursor: env === 'main' ? 'not-allowed' : 'pointer',
                  color: env === 'main' ? '#999' : '#333',
                  wordBreak: 'break-all',
                }}
              >
                <input
                  type="checkbox"
                  style={{ marginRight: '8px' }}
                  value={env}
                  disabled={!canWrite || env === 'main'}
                  checked={selectedEnvsSet.has(env)}
                  onChange={(ev) => {
                    if (ev.target.checked) {
                      setSelectedEnvs((prev) =>
                        Array.from(new Set([...prev, env]))
                      );
                    } else {
                      setSelectedEnvs((prev) => prev.filter((e) => e !== env));
                    }
                  }}
                />
                {env}{' '}
                {env === 'main' && (
                  <span style={{ fontSize: '0.8em' }}>(protected)</span>
                )}
              </label>
            ))
          )}
        </div>

        <button
          className="btn btn-default"
          disabled={
            !canWrite ||
            selectedEnvs.length === 0 ||
            selectedEnvsSet.has('main')
          }
          onClick={() => {
            const deletedEnvs = [...selectedEnvs];
            // push active env at last to prevent breaking the queue
            let sortedEnvs = deletedEnvs.filter((env) => env !== activeEnv);
            if (selectedEnvsSet.has(activeEnv)) {
              sortedEnvs.push(activeEnv);
            }
            onEnvDelete(sortedEnvs, activeEnv);
            setSelectedEnvs([]);
            showToast(
              deletedEnvs.length === 1
                ? `Successfully deleted environment "${deletedEnvs[0]}".`
                : `Successfully deleted ${deletedEnvs.length} environments.`,
              'success'
            );
          }}
        >
          Delete Selected
        </button>
      </div>
      <hr />
      <span className="visdom-title">Manage Tags</span>
      <br />
      Add optional key/value tags to an environment:
      <br />
      <div style={{ marginTop: '8px' }}>
        <select
          aria-label="Tag environment"
          className="form-control"
          disabled={!connected || tagSaveStatus === 'saving'}
          value={tagEnv || ''}
          onChange={(ev) => {
            setTagEnv(ev.target.value);
            setTagSaveStatus('idle');
            setTagSaveError('');
          }}
          style={{ marginBottom: '8px' }}
        >
          {envList.map((env) => (
            <option key={env} value={env}>
              {env}
            </option>
          ))}
        </select>

        {tagRows.length === 0 && (
          <div style={{ color: '#777', marginBottom: '8px' }}>
            This environment has no tags.
          </div>
        )}

        {tagRows.map((row, index) => (
          <div
            className="form-inline"
            key={row.id}
            style={{ display: 'flex', gap: '6px', marginBottom: '6px' }}
          >
            <input
              aria-label={`Tag name ${index + 1}`}
              className="form-control"
              disabled={!canWrite || tagSaveStatus === 'saving'}
              onChange={(ev) => updateTagRow(row.id, 'name', ev.target.value)}
              placeholder="name"
              style={{ flex: 1 }}
              type="text"
              value={row.name}
            />
            <input
              aria-label={`Tag value ${index + 1}`}
              className="form-control"
              disabled={!canWrite || tagSaveStatus === 'saving'}
              onChange={(ev) => updateTagRow(row.id, 'value', ev.target.value)}
              placeholder="optional value"
              style={{ flex: 1 }}
              type="text"
              value={row.value}
            />
            <button
              aria-label={`Remove tag ${index + 1}`}
              className="btn btn-default"
              disabled={!canWrite || tagSaveStatus === 'saving'}
              onClick={() => removeTagRow(row.id)}
              type="button"
            >
              Remove
            </button>
          </div>
        ))}

        <div className="form-inline">
          <button
            className="btn btn-default"
            disabled={
              !canWrite ||
              tagSaveStatus === 'saving' ||
              tagRows.length >= MAX_TAGS_PER_ENV
            }
            onClick={() => {
              setTagRows((prev) => [...prev, createTagRow()]);
              setTagSaveStatus('idle');
              setTagSaveError('');
            }}
            type="button"
          >
            Add Tag
          </button>{' '}
          <button
            className={
              tagSaveStatus === 'saved'
                ? 'btn btn-success'
                : tagSaveStatus === 'error'
                  ? 'btn btn-danger'
                  : 'btn btn-primary'
            }
            disabled={
              !canWrite ||
              !tagEnv ||
              tagSaveStatus === 'saving' ||
              hasInvalidTags
            }
            onClick={handleTagsSave}
            type="button"
          >
            {tagSaveStatus === 'saving'
              ? 'Saving...'
              : tagSaveStatus === 'saved'
                ? 'Saved!'
                : tagSaveStatus === 'error'
                  ? 'Retry Save'
                  : 'Update Tags'}
          </button>
        </div>

        {hasUnnamedValue && (
          <div style={{ color: '#d9534f' }}>
            A tag value cannot be saved without a tag name.
          </div>
        )}
        {hasLongName && (
          <div style={{ color: '#d9534f' }}>
            Tag names must not exceed {MAX_TAG_NAME_LENGTH} characters.
          </div>
        )}
        {hasTooManyTags && (
          <div style={{ color: '#d9534f' }}>
            Environments may have at most {MAX_TAGS_PER_ENV} tags.
          </div>
        )}
        {duplicateNames.size > 0 && (
          <div style={{ color: '#d9534f' }}>
            Tag names must be unique: {Array.from(duplicateNames).join(', ')}.
          </div>
        )}
        {tagSaveError && (
          <div style={{ color: '#d9534f' }}>
            Unable to update tags: {tagSaveError}
          </div>
        )}
      </div>
    </ReactModal>
  );
}

export default EnvModal;
