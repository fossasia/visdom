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

function EnvModal(props) {
  const { connected } = useContext(ApiContext);
  const {
    activeEnv,
    envList,
    onModalClose,
    onEnvSave,
    onEnvDelete,
    onTagsSave,
    tags,
    show,
  } = props;

  // effects
  // -------

  // change input / select value when activeEnv changes
  const [inputText, setInputText] = useState(activeEnv);
  const [selectText, setSelectText] = useState(activeEnv);
  const [tagEnv, setTagEnv] = useState(activeEnv);
  const [tagText, setTagText] = useState('');
  const [saveStatus, setSaveStatus] = useState('idle'); // idle, saving, saved, error

  useEffect(() => {
    setInputText(activeEnv);
    setSelectText(activeEnv);
    setTagEnv(activeEnv);
  }, [activeEnv]);

  // Update tagText whenever the selected tag environment
  // or the global tags index changes
  useEffect(() => {
    const currentTags = (tags && tags[tagEnv]) || [];
    setTagText(currentTags.join(', '));
  }, [tagEnv, tags, show]);

  const handleTagsSave = () => {
    // 1. Data Sanitization (The Comma-Separated Trap Prevention)
    const cleanTags = tagText
      .split(',')
      .map((tag) => tag.trim())
      .filter((tag) => tag.length > 0);

    setSaveStatus('saving');
    onTagsSave(tagEnv, cleanTags)
      .done(() => {
        setSaveStatus('saved');
        setTimeout(() => setSaveStatus('idle'), 2000);
      })
      .fail(() => {
        setSaveStatus('error');
        setTimeout(() => setSaveStatus('idle'), 3000);
      });
  };

  // rendering
  // ---------

  return (
    <ReactModal
      isOpen={show}
      onRequestClose={onModalClose}
      contentLabel="Environment Management Modal"
      ariaHideApp={false}
      style={MODAL_STYLE}
    >
      <span className="visdom-title">Manage Environments</span>
      <br />
      Save or fork current environment:
      <br />
      <div className="form-inline">
        <input
          className="form-control"
          type="text"
          value={inputText}
          onChange={(ev) => {
            setInputText(ev.target.value);
          }}
        />
        <button
          className="btn btn-default"
          disabled={!(connected && inputText && inputText.length > 0)}
          onClick={() => onEnvSave(inputText)}
        >
          {envList.indexOf(inputText) >= 0 ? 'save' : 'fork'}
        </button>
      </div>
      <br />
      Delete environment:
      <br />
      <div className="form-inline">
        <select
          className="form-control"
          disabled={!connected}
          value={selectText}
          onChange={(ev) => {
            setSelectText(ev.target.value);
          }}
        >
          {envList.map((env) => (
            <option key={env} value={env}>
              {env}
            </option>
          ))}
        </select>
        <button
          className="btn btn-default"
          disabled={!connected || !selectText || selectText == 'main'}
          onClick={() => onEnvDelete(selectText, activeEnv)}
        >
          Delete
        </button>
      </div>
      <hr />
      <span className="visdom-title">Manage Tags</span>
      <br />
      Assign tags to an environment (comma separated):
      <br />
      <div className="form-inline">
        <select
          className="form-control"
          disabled={!connected || saveStatus === 'saving'}
          value={tagEnv}
          onChange={(ev) => {
            setTagEnv(ev.target.value);
          }}
        >
          {envList.map((env) => (
            <option key={env} value={env}>
              {env}
            </option>
          ))}
        </select>
        <input
          className="form-control"
          type="text"
          placeholder="e.g. stable, v1.0"
          disabled={!connected || saveStatus === 'saving'}
          value={tagText}
          onChange={(ev) => setTagText(ev.target.value)}
          style={{ width: '250px' }}
        />
        <button
          className={`btn ${
            saveStatus === 'saved'
              ? 'btn-success'
              : saveStatus === 'error'
              ? 'btn-danger'
              : 'btn-default'
          }`}
          disabled={!connected || saveStatus === 'saving' || !tagEnv}
          onClick={handleTagsSave}
        >
          {saveStatus === 'saving'
            ? 'Saving...'
            : saveStatus === 'saved'
            ? 'Saved!'
            : saveStatus === 'error'
            ? 'Error!'
            : 'Update Tags'}
        </button>
      </div>
    </ReactModal>
  );
}

export default EnvModal;
