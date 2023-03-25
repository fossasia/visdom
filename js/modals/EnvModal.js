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
  const { activeEnv, envList, onModalClose, onEnvSave, onEnvDelete, show } =
    props;

  // effects
  // -------

  // change input / select value when activeEnv changes
  const [inputText, setInputText] = useState(activeEnv);
  const [selectText, setSelectText] = useState(activeEnv);
  useEffect(() => {
    setInputText(activeEnv);
    setSelectText(activeEnv);
  }, [activeEnv]);

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
      Delete environment selected in dropdown:
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
          {envList.map((env) => {
            return (
              <option key={env} value={env}>
                {env}
              </option>
            );
          })}
        </select>
        <button
          className="btn btn-default"
          disabled={!connected || !selectText || selectText == 'main'}
          onClick={() => onEnvDelete(selectText, activeEnv)}
        >
          Delete
        </button>
      </div>
    </ReactModal>
  );
}

export default EnvModal;
