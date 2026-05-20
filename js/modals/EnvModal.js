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
  const [selectedEnvs, setSelectedEnvs] = useState([]);
  useEffect(() => {
    setInputText(activeEnv);
    setSelectedEnvs([]);
  }, [activeEnv, show]);

  // rendering
  // ---------

  const selectableEnvs = envList.filter(env => env !== 'main');
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
      Select environments to delete:
      <br />
     <div className="form-inline">
        <div style={{ border: '1px solid #ccc', padding: '10px', height: '140px', overflowY: 'scroll', marginBottom: '10px', width: '100%', borderRadius: '4px', backgroundColor: '#fff' }}>
          
          <label style={{ display: 'block', fontWeight: 'bold', cursor: 'pointer' }}>
            <input
              type="checkbox"
              style={{ marginRight: '8px' }}
              disabled={!connected || selectableEnvs.length === 0}
              checked={isAllSelected}
              onChange={(ev) => {
                setSelectedEnvs(ev.target.checked ? selectableEnvs : []);
              }}
            />
            Select All
          </label>
          <hr style={{ margin: '5px 0' }} />

          {envList.map((env) => (
            <label key={env} style={{ display: 'block', fontWeight: 'normal', cursor: env === 'main' ? 'not-allowed' : 'pointer', color: env === 'main' ? '#999' : '#333', wordBreak: 'break-all' }}>
              <input
                type="checkbox"
                style={{ marginRight: '8px' }}
                value={env}
                disabled={!connected || env === 'main'}
                checked={selectedEnvsSet.has(env)}
                onChange={(ev) => {
                  if (ev.target.checked) {
                    setSelectedEnvs((prev) => 
                    Array.from(new Set([...prev, env]))
                  );
                  } else {
                    setSelectedEnvs(prev => prev.filter(e => e !== env));
                  }
                }}
              />
              {env} {env === 'main' && <span style={{ fontSize: '0.8em' }}>(protected)</span>}
            </label>
          ))}
        </div>

        <button
          className="btn btn-default"
          disabled={!connected || selectedEnvs.length === 0 || selectedEnvsSet.has('main')}
          onClick={() => {
            // push active env at last to prevent breaking the queue
            let sortedEnvs = selectedEnvs.filter(env => env !== activeEnv);
            if (selectedEnvsSet.has(activeEnv)) {
                sortedEnvs.push(activeEnv);
            }
            sortedEnvs.forEach(env => {
                onEnvDelete(env, activeEnv);
            });
            setSelectedEnvs([]);
            onModalClose();
          }}
        >
          Delete Selected
        </button>
      </div>
    </ReactModal>
  );
}

export default EnvModal;
