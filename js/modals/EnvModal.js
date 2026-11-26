/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import './EnvModal.css';

import { Folder, Tags, Trash2 } from 'lucide-react';
import React, { useContext, useEffect, useState } from 'react';
import ReactModal from 'react-modal';

import ApiContext from '../api/ApiContext';
import { showToast } from '../toasts/toastEvents';
import EnvDeleteList from './EnvDeleteList';

const TASKS = [
  { label: 'General', Icon: Folder },
  { label: 'Tags', Icon: Tags },
  { label: 'Delete', Icon: Trash2 },
];

const MAX_TAG_NAME_LENGTH = 50;
const MAX_TAGS_PER_ENV = 20;
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
  const [task, setTask] = useState('General');
  const [inputText, setInputText] = useState(activeEnv);
  const [tagEnv, setTagEnv] = useState(activeEnv);
  const [tagRows, setTagRows] = useState([]);
  const [tagSaveStatus, setTagSaveStatus] = useState('idle');
  const [tagSaveError, setTagSaveError] = useState('');
  const [selectedEnvs, setSelectedEnvs] = useState([]);
  useEffect(() => {
    setInputText(activeEnv);
    setTagEnv(activeEnv || envList[0] || '');
    setTagSaveStatus('idle');
    setTagSaveError('');
  }, [activeEnv, show]);

  useEffect(() => {
    setTask('General');
    setSelectedEnvs([]);
  }, [show]);

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

  const selectedEnvsSet = new Set(selectedEnvs);
  return (
    <ReactModal
      isOpen={show}
      onRequestClose={onModalClose}
      contentLabel="Environment Management Modal"
      ariaHideApp={false}
      className="env-manager"
      overlayClassName="env-manager-overlay"
    >
      <header className="env-manager-header">
        <h2>Manage Environments</h2>
        <button
          className="env-close"
          type="button"
          aria-label="Close dialog"
          onClick={onModalClose}
        >
          ×
        </button>
      </header>
      <div className="env-manager-body">
        <nav className="env-task-nav" aria-label="Environment tasks">
          {TASKS.map(({ label, Icon }) => (
            <button
              key={label}
              type="button"
              aria-current={task === label ? 'page' : undefined}
              onClick={() => setTask(label)}
            >
              <Icon size={16} aria-hidden="true" />
              {label}
            </button>
          ))}
        </nav>
        <section hidden={task !== 'General'}>
          <h3>Save or fork</h3>
          <div className="env-save-row">
            <label htmlFor="env-save-name">Environment name</label>
            <input
              id="env-save-name"
              className="form-control"
              type="text"
              value={inputText}
              onChange={(ev) => {
                setInputText(ev.target.value);
              }}
            />
            <button
              className="btn btn-primary"
              disabled={!(canWrite && inputText && inputText.length > 0)}
              onClick={() => onEnvSave(inputText)}
            >
              {envList.indexOf(inputText) >= 0 ? 'Save' : 'Fork'}
            </button>
          </div>
          <p className="env-field-hint">
            Enter a new name to fork the current environment.
          </p>
        </section>
        <section hidden={task !== 'Tags'} className="env-tags-section">
          <h3>Environment tags</h3>
          <div className="env-tag-target">
            <label htmlFor="env-tags-target">Environment</label>
            <select
              id="env-tags-target"
              aria-label="Tag environment"
              className="form-control"
              disabled={!connected || tagSaveStatus === 'saving'}
              value={tagEnv || ''}
              onChange={(ev) => {
                setTagEnv(ev.target.value);
                setTagSaveStatus('idle');
                setTagSaveError('');
              }}
            >
              {envList.map((env) => (
                <option key={env} value={env}>
                  {env}
                </option>
              ))}
            </select>
          </div>

          <div className="env-tag-editor">
            <div className="env-tag-toolbar">
              <strong>
                Tags{' '}
                <span>
                  ({tagRows.length}/{MAX_TAGS_PER_ENV})
                </span>
              </strong>
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
              </button>
            </div>
            <div className="env-tag-list">
              {tagRows.length === 0 && (
                <p className="env-empty-tags">No tags yet</p>
              )}
              {tagRows.map((row, index) => (
                <div className="env-tag-row" key={row.id}>
                  <label className="env-tag-field">
                    <span>Tag name</span>
                    <input
                      aria-label={`Tag name ${index + 1}`}
                      className="form-control"
                      disabled={!canWrite || tagSaveStatus === 'saving'}
                      onChange={(ev) =>
                        updateTagRow(row.id, 'name', ev.target.value)
                      }
                      placeholder="Tag name"
                      aria-invalid={
                        (!row.name.trim() && !!row.value) ||
                        duplicateNames.has(row.name.trim()) ||
                        row.name.trim().length > MAX_TAG_NAME_LENGTH
                      }
                      type="text"
                      value={row.name}
                    />
                  </label>
                  <label className="env-tag-field">
                    <span>Value (optional)</span>
                    <input
                      aria-label={`Tag value ${index + 1}`}
                      className="form-control"
                      disabled={!canWrite || tagSaveStatus === 'saving'}
                      onChange={(ev) =>
                        updateTagRow(row.id, 'value', ev.target.value)
                      }
                      placeholder="Value (optional)"
                      type="text"
                      value={row.value}
                    />
                  </label>
                  <button
                    title="Remove tag"
                    aria-label={`Remove tag ${index + 1}`}
                    className="btn btn-default"
                    disabled={!canWrite || tagSaveStatus === 'saving'}
                    onClick={() => removeTagRow(row.id)}
                    type="button"
                  >
                    <Trash2 size={16} aria-hidden="true" />
                  </button>
                </div>
              ))}
            </div>
          </div>
          {hasUnnamedValue && (
            <div className="env-tag-error" role="alert">
              A tag value cannot be saved without a tag name.
            </div>
          )}
          {hasLongName && (
            <div className="env-tag-error" role="alert">
              Tag names must not exceed {MAX_TAG_NAME_LENGTH} characters.
            </div>
          )}
          {hasTooManyTags && (
            <div className="env-tag-error" role="alert">
              Environments may have at most {MAX_TAGS_PER_ENV} tags.
            </div>
          )}
          {duplicateNames.size > 0 && (
            <div className="env-tag-error" role="alert">
              Tag names must be unique: {Array.from(duplicateNames).join(', ')}.
            </div>
          )}
          {tagSaveError && (
            <div className="env-tag-error" role="alert">
              Unable to update tags: {tagSaveError}
            </div>
          )}
          <div className="env-tag-actions">
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
        </section>
        <section hidden={task !== 'Delete'} className="env-delete-section">
          <h3>Delete environments</h3>
          <EnvDeleteList
            activeEnv={activeEnv}
            disabled={!canWrite}
            envList={envList}
            onChange={setSelectedEnvs}
            selectedEnvs={selectedEnvs}
          >
            <button
              className="btn btn-danger"
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
                const requestedDeletions = onEnvDelete(sortedEnvs, activeEnv);
                if (requestedDeletions.length === 0) {
                  showToast(
                    'Unable to delete environments because the server connection is unavailable.',
                    'error'
                  );
                  return;
                }
                const requestedDeletionSet = new Set(requestedDeletions);
                const failedDeletions = deletedEnvs.filter(
                  (env) => !requestedDeletionSet.has(env)
                );
                if (
                  requestedDeletionSet.has(tagEnv) &&
                  !requestedDeletionSet.has(activeEnv)
                ) {
                  setTagEnv(activeEnv || 'main');
                  setTagSaveStatus('idle');
                  setTagSaveError('');
                }
                setSelectedEnvs(failedDeletions);
                if (failedDeletions.length > 0) {
                  showToast(
                    'Some environment deletion requests could not be sent.',
                    'error'
                  );
                  return;
                }
                const count = deletedEnvs.length;
                showToast(
                  count === 1
                    ? `Successfully deleted environment "${deletedEnvs[0]}".`
                    : `Successfully deleted ${count} environments.`,
                  'success'
                );
              }}
              type="button"
            >
              Delete Selected
            </button>
          </EnvDeleteList>
        </section>
      </div>
    </ReactModal>
  );
}

export default EnvModal;
